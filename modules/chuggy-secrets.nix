{ config, pkgs, lib, ... }:

# The credentials chuggy needs that no external authority has to issue, and the
# one-way boundary that puts them into Kubernetes.
#
# Two units, and the split is the point:
#
#   chuggy-secrets-generate  writes files under a root-only directory. Knows
#                            nothing about Kubernetes, so it works on a box
#                            where k3s has never started.
#   chuggy-secrets-sync      copies those values into Kubernetes Secrets, and
#                            is the only thing here that can fail for a reason
#                            outside this host.
#
# NOTHING HERE OVERWRITES A VALUE. Not the host files, not the Secret keys. A
# key already in the cluster is left exactly as it is and copied *back* into
# host state if this host has no record of it. That asymmetry is not caution for
# its own sake -- it is the only shape that is safe against the failure this rig
# can actually produce.
#
# THE FAILURE, precisely. A PostgreSQL password is two facts that have to agree:
# a string in a Secret, and a string PostgreSQL was told to accept for a role.
# Only the first is here. A sync that wrote a freshly generated password over
# the Secret would change the first and not the second, and the running API --
# whose role still holds the old password -- would be locked out of its own
# database by a rebuild that reported success. D21 says rebuilds reuse existing
# values, and this is what that has to mean in code.
#
# WHICH MAKES ADOPTION THE INTERESTING CASE. On a rig where the Secret was
# issued by hand before this module existed, the cluster holds the truth and the
# host holds nothing. Reading the value out of the Secret into host state is
# what makes the two agree, and it is the only direction that cannot lose
# anything: the value already exists, already authenticates, and is already
# readable by anything that can read the Secret.
#
# THE OTHER HALF OF A GENERATED PASSWORD IS NOT HERE, and pretending otherwise
# would be the worst thing this file could do. A password this module generates
# authenticates nothing until PostgreSQL is told about it. That is what
# kasofsk/chuggy's deploy/rig/postgres/postgres-roles.sql does, reading the same
# values out of CHUG_PG_*_PASSWORD, and it is run by an operator against a
# running database -- not by this module. Three reasons it is not run here:
# activation happens while PostgreSQL is still a pod that has not been
# scheduled; the file lives in another repository and would have to be vendored
# or fetched; and re-running it rotates every role, which is exactly the
# destructive operation D21 says must be explicit. `chuggy-pg-role-env` below is
# how the values reach it without passing through a terminal.
#
# WHAT IS NOT PROVIDED: rotation. Rotating one of these correctly means fencing
# writers, changing the role, changing the Secret and restarting the workloads
# that hold a connection, in that order -- and getting the order wrong locks out
# the process the rotation was for. Nothing here does any of it, and nothing
# here pretends to: the value is generated once and then only ever read.

let
  cfg = config.chuggy.secrets;

  # The inventory is fixed rather than an option, and that is a claim worth
  # being explicit about: these are chuggy's internal credentials, so they are
  # the same on every adopting machine. What varies by site is where the host
  # keeps them and which namespace they are synchronised into, and those are
  # options below. A site that needed a different set of keys would not have a
  # different rig -- it would have a different chuggy.
  #
  # Key names match what the workloads in cluster/apps/ read. They are the
  # contract; changing one here without changing it there produces a pod that
  # will not start, which is the loud failure and the one to prefer.
  inventory = {
    # One login role per control-plane process, which is what
    # deploy/rig/postgres/postgres-roles.sql creates. A shared credential would
    # not merely widen a process's reach -- every command asserts current_user
    # at start-up, so it would stop the others from starting at all.
    "chuggy-postgres-credentials" = {
      "owner-password" = "password";
      "api-password" = "password";
      "ticket-service-password" = "password";
      "selector-service-password" = "password";
      "scheduler-password" = "password";
      "finalizer-password" = "password";
    };
    # Not a password: the versioned keyset a client idempotency key is HMAC'd
    # under. It is generated with one version because a rig that has never run
    # has nothing stored under an older one.
    "chuggy-api" = {
      "idempotency-keying" = "keyset";
    };
  };

  secretNames = lib.attrNames inventory;
  keysOf = secret: lib.attrNames inventory.${secret};

  # `CHUG_PG_API_PASSWORD` from `api-password`. Mechanical, so a key added above
  # needs no second edit here, and so a reader can check the mapping rather than
  # trust a table.
  envVarFor = key: "CHUG_PG_" + lib.toUpper (lib.replaceStrings [ "-" ] [ "_" ] key);

  # Hex, not base64. These values are pasted into a PostgreSQL connection URI by
  # cluster/apps/, and `/`, `+` and `=` all mean something inside one. A
  # password that has to be percent-encoded to be usable is a password that will
  # eventually not be.
  generate = pkgs.writeShellApplication {
    name = "chuggy-secrets-generate";
    runtimeInputs = [ pkgs.openssl pkgs.coreutils ];
    text = ''
      umask 077
      install -d -m 0700 -o root -g root "${cfg.stateDir}"

      ensure() {
        local path="$1" kind="$2" tmp
        [ -s "$path" ] && return 0
        tmp="$path.new.$$"
        case "$kind" in
          password)
            openssl rand -hex 32 | tr -d '\n' > "$tmp"
            ;;
          keyset)
            printf '{"current":"v1","versions":[{"version":"v1","secret":"%s"}]}' \
              "$(openssl rand -hex 32 | tr -d '\n')" > "$tmp"
            ;;
          *)
            echo "chuggy.secrets: unknown generator '$kind' for $path" >&2
            return 1
            ;;
        esac
        chmod 0600 "$tmp"
        mv "$tmp" "$path"
        echo "generated $path"
      }

      ${lib.concatStrings (lib.concatMap
        (secret: [ ''install -d -m 0700 -o root -g root "${cfg.stateDir}/${secret}"''
                   "\n" ] ++ lib.concatMap
          (key: [ ''ensure "${cfg.stateDir}/${secret}/${key}" "${inventory.${secret}.${key}}"''
                  "\n" ])
          (keysOf secret))
        secretNames)}
    '';
  };

  sync = pkgs.writeShellApplication {
    name = "chuggy-secrets-sync";
    runtimeInputs = [ pkgs.kubectl pkgs.jq pkgs.coreutils ];
    text = ''
      umask 077
      kc="${cfg.kubeconfig}"
      ns="${cfg.namespace}"
      state="${cfg.stateDir}"
      run="''${RUNTIME_DIRECTORY:-$(mktemp -d)}"

      # Every diagnostic below exits 2, not 1. A precondition this host cannot
      # satisfy on its own -- k3s still starting, a namespace Flux has not
      # created yet -- is a could-not-run, and reporting it as a failure of the
      # synchronisation would put the blame on the wrong thing.
      if [ ! -r "$kc" ]; then
        echo "chuggy.secrets: $kc is not readable; k3s has not written a kubeconfig." >&2
        exit 2
      fi

      k() { kubectl --kubeconfig "$kc" -n "$ns" "$@"; }

      # The namespace belongs to cluster/apps/, so on a cold boot it does not
      # exist until Flux has reconciled once. Waiting here rather than failing
      # immediately is what keeps the bootstrap order from mattering; the unit
      # also restarts, which covers a Flux that takes longer than this.
      deadline=$(( $(date +%s) + ${toString cfg.namespaceTimeoutSeconds} ))
      until k get --request-timeout=5s namespace "$ns" >/dev/null 2>&1; do
        if [ "$(date +%s)" -ge "$deadline" ]; then
          echo "chuggy.secrets: namespace $ns does not exist; Flux has not created it." >&2
          exit 2
        fi
        sleep 5
      done

      sync_secret() {
        local secret="$1"
        shift
        local dir="$state/$secret" key
        install -d -m 0700 -o root -g root "$dir"

        if ! k get secret "$secret" -o json > "$run/live.json" 2>/dev/null; then
          k create secret generic "$secret" >/dev/null
          echo '{"data":{}}' > "$run/live.json"
        fi

        # The label states who synchronises this object. cluster/apps/ reads
        # ownership labels by value elsewhere for the same reason: a Secret this
        # host writes and a Secret someone applied by hand are otherwise
        # indistinguishable.
        echo '{"metadata":{"labels":{"chuggy.dev/managed-by":"nixos"}}}' > "$run/patch.json"

        for key in "$@"; do
          jq -r --arg k "$key" '(.data // {})[$k] // empty' "$run/live.json" > "$run/live.b64"

          if [ -s "$run/live.b64" ]; then
            if [ -s "$dir/$key" ]; then
              base64 -w0 < "$dir/$key" > "$run/host.b64"
              if ! cmp -s "$run/host.b64" "$run/live.b64"; then
                echo "chuggy.secrets: $secret/$key differs between host state and the cluster." >&2
                echo "  Neither was changed. One of them is what PostgreSQL was told; the other is not." >&2
              fi
            else
              base64 -d < "$run/live.b64" > "$run/adopt"
              install -m 0600 -o root -g root "$run/adopt" "$dir/$key"
              echo "adopted $secret/$key from the cluster"
            fi
            continue
          fi

          if [ ! -s "$dir/$key" ]; then
            echo "chuggy.secrets: $dir/$key is missing and the cluster has no $key either." >&2
            echo "  chuggy-secrets-generate should have written it." >&2
            exit 2
          fi

          base64 -w0 < "$dir/$key" > "$run/host.b64"
          jq --arg k "$key" --rawfile v "$run/host.b64" \
            '.data[$k] = ($v | rtrimstr("\n"))' "$run/patch.json" > "$run/patch.next"
          mv "$run/patch.next" "$run/patch.json"
          echo "creating $secret/$key"
        done

        # --patch-file, never --patch: an argument is in the process table for
        # anything on this box to read, and so is an environment variable of a
        # process someone can strace. The runtime directory is tmpfs, 0700, and
        # systemd removes it when the unit stops.
        k patch secret "$secret" --type=merge --patch-file "$run/patch.json" >/dev/null
      }

      ${lib.concatMapStrings
        (secret: ''
          sync_secret ${lib.escapeShellArg secret} ${lib.escapeShellArgs (keysOf secret)}
        '')
        secretNames}
    '';
  };

  # Runs a command with the PostgreSQL passwords in its environment, which is
  # the interface deploy/rig/postgres/postgres-roles.sql already asks for. It
  # exists so that giving the roles their passwords does not require reading the
  # values onto a terminal, into shell history, or through an argument list.
  #
  #   sudo chuggy-pg-role-env psql -h 127.0.0.1 -U postgres -d chuggy \
  #     -f deploy/rig/postgres/postgres-roles.sql
  #
  # Running that file rotates every role it names. That is safe on a cluster
  # whose roles were set from these same values and destructive on one whose
  # were not -- see the header.
  pgRoleEnv = pkgs.writeShellApplication {
    name = "chuggy-pg-role-env";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      if [ "$#" -eq 0 ]; then
        echo "usage: chuggy-pg-role-env <command> [args...]" >&2
        exit 64
      fi
      ${lib.concatMapStrings (key: ''
        if [ ! -r "${cfg.stateDir}/chuggy-postgres-credentials/${key}" ]; then
          echo "chuggy-pg-role-env: ${cfg.stateDir}/chuggy-postgres-credentials/${key} is not readable." >&2
          echo "  Run as root, after chuggy-secrets-generate has run." >&2
          exit 2
        fi
        ${envVarFor key}="$(cat "${cfg.stateDir}/chuggy-postgres-credentials/${key}")"
        export ${envVarFor key}
      '') (keysOf "chuggy-postgres-credentials")}
      exec "$@"
    '';
  };
in
{
  options.chuggy.secrets = {
    enable = lib.mkEnableOption "chuggy's generated internal credentials";

    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "${config.chuggy.state.directory}/secrets";
      defaultText = lib.literalExpression ''"''${config.chuggy.state.directory}/secrets"'';
      description = ''
        Where generated values are kept on the host. 0700 root:root, and every
        file under it 0600 -- outside the Nix store, which is world-readable and
        would publish them to every process on the box.

        Deleting this directory is not a reset. The values in the cluster and
        the passwords PostgreSQL holds are unaffected by it, so what it produces
        is a host that adopts back whatever the cluster has and generates
        replacements for whatever it does not -- which is a rig with credentials
        no role was ever given.
      '';
    };

    namespace = lib.mkOption {
      type = lib.types.str;
      default = "chuggy";
      description = ''
        Namespace the Secrets are written into. It is created by cluster/apps/,
        not here: two layers creating one object is the ambiguity D6 exists to
        prevent, and a namespace is the object both would reach for first.
      '';
    };

    kubeconfig = lib.mkOption {
      type = lib.types.str;
      default = "/etc/rancher/k3s/k3s.yaml";
      description = "Credential the synchronisation uses. k3s writes this one at startup.";
    };

    namespaceTimeoutSeconds = lib.mkOption {
      type = lib.types.int;
      default = 120;
      description = ''
        How long one attempt waits for the namespace before reporting
        could-not-run. The unit restarts, so this bounds an attempt rather than
        the bootstrap -- short enough that a genuinely absent namespace is
        visible in the journal early, rather than after a silent wait.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.tmpfiles.rules = [
      "d ${cfg.stateDir} 0700 root root -"
    ];

    systemd.services.chuggy-secrets-generate = {
      description = "Generate chuggy's internal credentials on this host";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = lib.getExe generate;
      };
    };

    systemd.services.chuggy-secrets-sync = {
      description = "Synchronise chuggy's internal credentials into Kubernetes";
      wantedBy = [ "multi-user.target" ];
      requires = [ "chuggy-secrets-generate.service" ];
      after = [ "chuggy-secrets-generate.service" "k3s.service" ];
      wants = [ "k3s.service" ];

      # Retries, because everything it waits for arrives on its own schedule:
      # k3s starting, Flux reconciling the namespace. Bounded, because a unit
      # that retries forever reports a broken cluster as a busy one -- after the
      # burst it stays failed, where `systemctl --failed` shows it.
      startLimitIntervalSec = 3600;
      startLimitBurst = 40;

      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = lib.getExe sync;
        Restart = "on-failure";
        RestartSec = 30;
        RuntimeDirectory = "chuggy-secrets-sync";
        RuntimeDirectoryMode = "0700";
      };
    };

    environment.systemPackages = [ pgRoleEnv ];
  };
}
