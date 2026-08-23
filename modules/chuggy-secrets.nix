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
# AND THE BOOT ORDER DOES NOT REACH IT. The generator runs first and writes
# every value it does not find, so the host never holds nothing and the adoption
# below is reached only for a key deleted by hand. An adopting host reports
# divergence on each key the cluster already had instead, and fails -- both
# sides honest, the host's copy simply never having been anywhere, and the unit
# in `systemctl --failed` where that is findable. Seeding host state from the
# cluster before the generator first runs is what an adopting host does, and the
# README carries it; gdoteof/chuggy-fabric#12 is the ordering that would make
# the step unnecessary.
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
#
# WHAT THE SYNCHRONISATION'S EXIT STATUS MEANS, in one place, because the unit's
# Restart= and RestartPreventExitStatus= read it and a second version of this
# list would be a unit that retries what it should not or gives up on what it
# should retry:
#
#   0  every key agreed, or was created from host state.
#   2  could-not-run. Nothing this host controls has gone wrong -- no
#      kubeconfig, no namespace, a key neither side holds. RETRIES.
#   3  divergence. Both sides answered and disagreed, and only a person can say
#      which value PostgreSQL was told about. DOES NOT RETRY.
#   *  a command failed. `set -o errexit` carries kubectl's, jq's or base64's
#      own status out, and kubectl exits 1 on an API error it could not reach
#      past -- a leader election, a compaction, a request timeout. Transient by
#      nature, so it RETRIES. Divergence is 3 and not 1 for exactly this
#      reason: a `RestartPreventExitStatus = 1` makes every one of those a
#      permanently failed unit that nothing on the box retries.

let
  cfg = config.chuggy.secrets;

  # What the synchronisation's restart budget is made of. The window is derived
  # from the cycle rather than chosen alongside it: a window the burst cannot
  # fit inside is never reached, the unit restarts forever, and the
  # `systemctl --failed` the bound exists to produce never happens. Changing
  # namespaceTimeoutSeconds moves the window with it, which is the half a pair
  # of literals gets wrong.
  #
  # AND THE WAIT IS A LOWER BOUND ON A RUN, NOT AN UPPER ONE. The loop below
  # sets its deadline before the first probe and exits only on a probe that
  # finds the deadline passed, so a run costs the wait plus the sleep and the
  # request that carry it over -- and a window sized on the wait alone is a
  # window every cycle overruns. That is the arithmetic this got wrong: it is
  # the worst case a restart budget is made of, never the nominal one.
  syncRestartSeconds = 30;
  syncStartLimitBurst = 10;
  syncProbeIntervalSeconds = 5;

  # Applied to every kubectl call. Long enough that a busy API server is not
  # mistaken for a wedged one, short enough that a wedged one is a failed unit
  # rather than a unit that never returns.
  syncRequestTimeoutSeconds = 30;
  syncRequestTimeout = "${toString syncRequestTimeoutSeconds}s";

  # The longest one start-to-start cycle can take: the wait, the sleep and the
  # probe that carry it past its deadline, and the pause before systemd starts
  # the unit again.
  syncCycleSeconds =
    cfg.namespaceTimeoutSeconds
    + syncProbeIntervalSeconds
    + syncRequestTimeoutSeconds
    + syncRestartSeconds;

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
    # diffutils is here for `cmp`, which is not in coreutils and is not on the
    # PATH systemd hands a unit. An absent `cmp` exits 127, `if !` reads that as
    # a difference, and the divergence branch is then taken for every key --
    # a warning indistinguishable from the real one it exists to raise.
    runtimeInputs = [ pkgs.kubectl pkgs.jq pkgs.coreutils pkgs.diffutils ];
    text = ''
      umask 077
      kc="${cfg.kubeconfig}"
      ns="${cfg.namespace}"
      state="${cfg.stateDir}"
      run="''${RUNTIME_DIRECTORY:-$(mktemp -d)}"

      # The runtime directory holds a decoded password and the cluster's own
      # copy of every key, and systemd does not remove it until the unit stops
      # -- which, under RemainAfterExit, is at the next reboot. So the script
      # removes its own working files, on the way out of a failure as well: an
      # exit 2 partway through is exactly when there is a decoded value lying
      # in it.
      trap 'rm -f "$run"/*' EXIT

      # Set by any key this run refused to resolve. It is not a could-not-run:
      # both sides answered and disagreed, and only a person can say which one
      # PostgreSQL was told about. The run finishes -- the keys that do agree
      # are still worth creating -- and then exits 3.
      diverged=0

      # A precondition this host cannot satisfy on its own -- k3s still
      # starting, a namespace Flux has not created yet -- exits 2 instead.
      # Reporting one as a failure of the synchronisation would put the blame on
      # the wrong thing, and the unit's Restart= reads the two differently.
      if [ ! -r "$kc" ]; then
        echo "chuggy.secrets: $kc is not readable; k3s has not written a kubeconfig." >&2
        exit 2
      fi

      # The timeout is on every call, not only the probe below. A `get` or a
      # `patch` against an API server that accepts the connection and then stops
      # answering blocks for ever, and under RemainAfterExit the unit sits in
      # `activating` with nothing in `systemctl --failed` to find.
      k() { kubectl --kubeconfig "$kc" -n "$ns" --request-timeout=${syncRequestTimeout} "$@"; }

      # The namespace belongs to cluster/apps/, so on a cold boot it does not
      # exist until Flux has reconciled once. Waiting here rather than failing
      # immediately is what keeps the bootstrap order from mattering; the unit
      # also restarts, which covers a Flux that takes longer than this.
      deadline=$(( $(date +%s) + ${toString cfg.namespaceTimeoutSeconds} ))
      until k get namespace "$ns" >/dev/null 2>&1; do
        if [ "$(date +%s)" -ge "$deadline" ]; then
          echo "chuggy.secrets: namespace $ns does not exist; Flux has not created it." >&2
          exit 2
        fi
        sleep ${toString syncProbeIntervalSeconds}
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
          # Presence is `has`, not a non-empty value. A key the cluster holds
          # with an empty value is still a key somebody put there, and reading
          # it as absent is what let a previous version patch host state over
          # it -- which the header's NOTHING HERE OVERWRITES A VALUE says it
          # does not do.
          if jq -e --arg k "$key" '(.data // {}) | has($k)' "$run/live.json" >/dev/null; then
            # -j, not -r: `-r` terminates its output with a newline and
            # `base64 -w0` writes none, so the comparison below would find
            # every key different on a cluster that agrees.
            jq -j --arg k "$key" '.data[$k]' "$run/live.json" > "$run/live.b64"

            if [ ! -s "$run/live.b64" ]; then
              echo "chuggy.secrets: $secret/$key is present in the cluster with an empty value." >&2
              echo "  Neither side was changed. An empty key is not a value this can replace, and" >&2
              echo "  it is not one any workload can authenticate with either -- delete it or fill it." >&2
              diverged=1
              continue
            fi

            if [ -s "$dir/$key" ]; then
              base64 -w0 < "$dir/$key" > "$run/host.b64"
              if ! cmp -s "$run/host.b64" "$run/live.b64"; then
                echo "chuggy.secrets: $secret/$key differs between host state and the cluster." >&2
                echo "  Neither was changed. One of them is what PostgreSQL was told; the other is not." >&2
                diverged=1
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
        # process someone can strace. The runtime directory is tmpfs and 0700,
        # and the trap above is what empties it.
        k patch secret "$secret" --type=merge --patch-file "$run/patch.json" >/dev/null
      }

      ${lib.concatMapStrings
        (secret: ''
          sync_secret ${lib.escapeShellArg secret} ${lib.escapeShellArgs (keysOf secret)}
        '')
        secretNames}

      # A divergent run is a failed run. Two lines on stderr and exit 0 put the
      # only record of it in a journal nobody reads, on a host where
      # `systemctl status` says active (exited) and `systemctl --failed` is
      # empty -- and the README's guard on running postgres-roles.sql is "only
      # when the synchronisation reported no divergence", which nothing on the
      # box could then answer. A non-zero exit makes it answerable with
      # `systemctl is-active`, and RestartPreventExitStatus below is what stops
      # the unit burning its restart budget on a disagreement no retry can
      # settle. A status of its own, never 1: 1 is what `set -o errexit` hands
      # out for a kubectl that could not reach the API server, and that one has
      # to retry. The header carries the whole map.
      if [ "$diverged" != 0 ]; then
        echo "chuggy.secrets: the keys above were left as they are on both sides." >&2
        echo "  Decide which value PostgreSQL holds, make the two agree, and start this unit again." >&2
        exit 3
      fi
    '';
  };

  # Runs a command with the PostgreSQL passwords in its environment, which is
  # the interface deploy/rig/postgres/postgres-roles.sql already asks for. It
  # exists so that giving the roles their passwords does not require reading the
  # values onto a terminal, into shell history, or through an argument list.
  #
  #   systemctl is-active chuggy-secrets-sync    # must say `active`
  #   kubectl -n chuggy port-forward svc/postgres 55440:5432 &
  #   forward=$!
  #   export PGPASSWORD="$(kubectl -n chuggy get secret postgres-superuser \
  #     -o jsonpath='{.data.password}' | base64 -d)"
  #   sudo -E chuggy-pg-role-env psql -h 127.0.0.1 -p 55440 -U postgres \
  #     -d <database> -f deploy/rig/postgres/postgres-roles.sql
  #   kill $forward
  #
  # THE FIRST AND LAST LINES ARE THE PROCEDURE, not framing for it. A divergent
  # run exits 3, so `is-active` is the answer to "did this agree" that the box
  # can give -- what this hands psql is host state, and on a key where the two
  # disagree it sets PostgreSQL to a password the workloads do not have. And a
  # port-forward left up is superuser PostgreSQL on 127.0.0.1 for anything on
  # the operator's machine, for as long as the shell lives.
  #
  # PGPASSWORD IS NOT WHAT AUTHENTICATES OVER THAT PORT. The deployment's
  # pg_hba.conf carries `host all all 127.0.0.1 trust` and a port-forward
  # arrives from loopback, so the value is never consulted and a wrong one
  # connects. It is exported anyway because that line is the deployment's and
  # not this repository's; `sudo -E` is what carries it without its becoming an
  # argument, which is true whether or not the server asks.
  #
  # The rest is not decoration either: the server is a headless Service and
  # listens on no address this host has, so a forwarded port is the only
  # transport; the superuser password is not one of the values here, it is in
  # its own Secret beside the server; and the database is the deployment's to
  # name, because a role is cluster-wide but the grants at the end of that file
  # are not. Running the file rotates every role it names: safe on a cluster
  # whose roles were set from these same values, destructive on one whose were
  # not.
  pgRoleEnv = pkgs.writeShellApplication {
    name = "chuggy-pg-role-env";
    # postgresql for the psql this exists to hand the values to. It is on this
    # tool's own PATH rather than the host's: the command above is the whole
    # documented use, and a procedure whose first step is to install a client
    # is a procedure nobody has run. nixpkgs has no client-only output, so what
    # this costs is a server package in the closure of a box that runs its
    # database in a pod.
    runtimeInputs = [ pkgs.coreutils pkgs.postgresql_17 ];
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
        # `$( )` strips every trailing newline, and here that is a wrong value
        # rather than a tidier one. A generated password carries none, but an
        # adopted one is whatever the cluster held -- and a Secret made the
        # ordinary way, `echo hunter2 | base64` or `--from-file` of a file an
        # editor saved, ends in one. Strip it and postgres-roles.sql sets the
        # role to a string the Secret does not hold, locking out every workload
        # that reads the Secret: the failure this module's header is built
        # against, arriving through the tool it supplies for the job. `printf %s
        # "$( )"` does not help -- the bytes are gone before printf sees them.
        # A sentinel appended inside the substitution and removed after it is
        # what survives.
        chuggy_pg_value="$(cat "${cfg.stateDir}/chuggy-postgres-credentials/${key}"; printf x)"
        ${envVarFor key}="''${chuggy_pg_value%x}"
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
        is a host that generates a replacement for every value and then
        disagrees with the cluster about all of them -- recoverable by seeding
        host state back out of the Secrets, which is what the README's adopting
        host does.
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
      #
      # systemd resets the window when `now - begin > StartLimitIntervalSec`,
      # so the start that trips the limit is reached only if the whole burst of
      # worst-case cycles fits inside it: the requirement is
      # `burst * cycle <= interval`, not `burst * wait`. One cycle of margin on
      # top, because process start-up and systemd's own scheduling are real and
      # are not in the derivation above.
      startLimitIntervalSec = (syncStartLimitBurst + 1) * syncCycleSeconds;
      startLimitBurst = syncStartLimitBurst;

      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = lib.getExe sync;
        Restart = "on-failure";
        # Exit 3 is a divergence: both sides answered and disagreed, and no
        # number of retries changes that. Retrying it would spend the whole
        # burst below on a report, and the unit would reach `failed` at the end
        # of that window rather than at the end of the run that found it.
        #
        # 3 and not 1. `set -o errexit` gives a failed command's own status,
        # and kubectl exits 1 on an API error -- so naming 1 here would make a
        # dropped connection during `patch secret` a unit that never runs
        # again, on the boot where a Secret a workload needs was one call away.
        # The header above is the whole map.
        RestartPreventExitStatus = 3;
        RestartSec = syncRestartSeconds;
        RuntimeDirectory = "chuggy-secrets-sync";
        RuntimeDirectoryMode = "0700";
      };
    };

    environment.systemPackages = [ pgRoleEnv ];
  };
}
