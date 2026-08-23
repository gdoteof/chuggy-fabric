{ pkgs }:

# Boots chuggy-state, chuggy-secrets, chuggy-images and chuggy-work, and asks
# them the questions evaluation cannot answer.
#
# Every claim below is about something that only exists once systemd has run: a
# directory's mode, a file that was generated rather than declared, a value that
# is the same after a reboot as before it, a unit that reports a precondition it
# cannot satisfy instead of reporting success.
#
# WHAT IT DOES NOT COVER, and the list matters more than the list above. It is
# four of the modules in flake.nix's substrate list, so it is not the substrate:
# k3s, Flux, WireGuard, the tunnel, dynamic DNS, common and node-prep are not
# imported here and an activation-breaking change to any of them would pass
# this. It does not start k3s, so it proves nothing about the firewall rules,
# the auto-deploy ordering or the image import. Those need a cluster, and a
# cluster in a test VM is a second rig with its own failure modes -- one that
# would make this check slow enough to be skipped, which is the state in which a
# check enforces nothing.
#
# WHAT STANDS IN FOR THE CLUSTER is a kubectl that keeps Secrets as files, and
# what it is worth is bounded by what it fakes: it is not an API server, it does
# not check RBAC, and a real cluster can refuse things it accepts. What it does
# faithfully is the shape the synchronisation reads and writes -- base64 in
# `.data`, a merge patch, a namespace that either exists or does not -- and that
# is enough to run the comparison over an actual Secret with the same jq, base64
# and cmp the unit gets, on the PATH systemd gives it. The comparison's failure
# was environmental twice over, so being on that PATH is the point.
#
# The secret values are not in the Nix store, and this test does not prove that
# either. It is structural: what the store holds is a generator, and the value
# comes into existence when the generator runs on the host. What the test does
# check is that they do not leak into the journal, which is the way a script
# like this normally spills one.

let
  # Where the fake cluster keeps its objects: one directory per namespace, one
  # file per Secret, holding the JSON `kubectl get -o json` would return.
  clusterStore = "/var/lib/fake-cluster";

  kubectlStub = final: final.writeShellApplication {
    name = "kubectl";
    runtimeInputs = [ final.jq final.coreutils ];
    text = ''
      store=${clusterStore}
      ns=default
      patchfile=""
      rest=()
      while [ "$#" -gt 0 ]; do
        case "$1" in
          --kubeconfig) shift 2 ;;
          -n|--namespace) ns="$2"; shift 2 ;;
          --patch-file) patchfile="$2"; shift 2 ;;
          -o) shift 2 ;;
          --request-timeout=*|--type=*) shift ;;
          *) rest+=("$1"); shift ;;
        esac
      done

      dir="$store/$ns"
      case "''${rest[0]:-} ''${rest[1]:-}" in
        "get namespace")
          if [ ! -d "$store/''${rest[2]}" ]; then
            echo "Error from server (NotFound): namespaces \"''${rest[2]}\" not found" >&2
            exit 1
          fi
          echo "namespace/''${rest[2]}"
          ;;
        "get secret")
          if [ ! -f "$dir/''${rest[2]}.json" ]; then
            echo "Error from server (NotFound): secrets \"''${rest[2]}\" not found" >&2
            exit 1
          fi
          cat "$dir/''${rest[2]}.json"
          ;;
        "create secret")
          if [ -f "$dir/''${rest[3]}.json" ]; then
            echo "Error from server (AlreadyExists): secrets \"''${rest[3]}\" already exists" >&2
            exit 1
          fi
          mkdir -p "$dir"
          printf '{"apiVersion":"v1","kind":"Secret","metadata":{"name":"%s","namespace":"%s"},"data":{}}\n' \
            "''${rest[3]}" "$ns" > "$dir/''${rest[3]}.json"
          echo "secret/''${rest[3]} created"
          ;;
        "patch secret")
          jq -s '.[0] * .[1]' "$dir/''${rest[2]}.json" "$patchfile" > "$dir/''${rest[2]}.next"
          mv "$dir/''${rest[2]}.next" "$dir/''${rest[2]}.json"
          echo "secret/''${rest[2]} patched"
          ;;
        *)
          echo "kubectl stub: unhandled call: ''${rest[*]}" >&2
          exit 64
          ;;
      esac
    '';
  };
in

pkgs.testers.runNixOSTest {
  name = "chuggy-state-and-secrets";

  # The stub replaces kubectl for the whole node, which is why nothing here
  # starts k3s: there is no second kubectl to be confused about.
  node.pkgs = pkgs.lib.mkForce (pkgs.extend (final: _prev: { kubectl = kubectlStub final; }));

  nodes.machine = { pkgs, ... }: {
    # The test script reads the keyset with jq; nothing in the modules needs it
    # on the host.
    environment.systemPackages = [ pkgs.jq ];

    imports = [
      ../modules/chuggy-state.nix
      ../modules/chuggy-secrets.nix
      ../modules/chuggy-images.nix
      ../modules/chuggy-work.nix
    ];

    chuggy.state = {
      enable = true;
      artifacts.path = "/var/lib/chuggy/artifacts";
    };
    chuggy.secrets.enable = true;
    chuggy.images.enable = true;
    chuggy.work = {
      enable = true;
      worker = { cpu = "1"; memory = "2Gi"; ephemeralStorage = "10Gi"; };
    };

    # k3s writes this one; nothing here does, so the file is declared and its
    # contents are never read -- the stub takes the flag and ignores it.
    environment.etc."rancher/k3s/k3s.yaml".text = "stub kubeconfig\n";

    # The namespace the synchronisation waits for. cluster/apps/ creates it on a
    # real box; here it is a directory, present from the first boot so that the
    # unit's wait is not what this test spends its time on.
    systemd.tmpfiles.rules = [
      "d ${clusterStore} 0700 root root -"
      "d ${clusterStore}/chuggy 0700 root root -"
    ];
  };

  testScript = { nodes, ... }: ''
    keys = [
        "owner-password",
        "api-password",
        "ticket-service-password",
        "selector-service-password",
        "scheduler-password",
        "finalizer-password",
    ]
    pgdir = "/var/lib/chuggy/secrets/chuggy-postgres-credentials"
    pgsecret = "${clusterStore}/chuggy/chuggy-postgres-credentials.json"
    namespace_timeout = ${toString nodes.machine.chuggy.secrets.namespaceTimeoutSeconds}


    def read_secrets():
        out = {}
        for key in keys:
            out[key] = machine.succeed("cat " + pgdir + "/" + key).strip()
        out["idempotency-keying"] = machine.succeed(
            "cat /var/lib/chuggy/secrets/chuggy-api/idempotency-keying"
        ).strip()
        return out


    def cluster_value(key):
        """The decoded value the fake cluster holds, as a workload would read it."""
        return machine.succeed(
            "jq -r --arg k " + key + " '.data[$k]' " + pgsecret + " | base64 -d"
        ).strip()


    def sync_journal():
        # Two commands, not `journalctl | grep`: a pipeline's status is its last
        # command's, so a journalctl that failed would leave the grep to report
        # nothing found and the check to pass on an empty journal.
        machine.succeed(
            "journalctl -u chuggy-secrets-sync.service --no-pager > /tmp/sync-journal"
        )
        return machine.succeed("cat /tmp/sync-journal")


    def resync():
        """Restart the synchronisation and return only what this run wrote.

        Through systemd rather than by running the script, because both of the
        comparison's failures were about the PATH systemd hands a unit."""
        before = len(sync_journal().splitlines())
        status, _ = machine.execute("systemctl restart chuggy-secrets-sync.service")
        return status, "\n".join(sync_journal().splitlines()[before:])


    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("chuggy-secrets-generate.service")
    machine.wait_for_unit("chuggy-secrets-sync.service")

    with subtest("retained directories carry the ownership they were given"):
        machine.succeed("test -d /var/lib/chuggy")
        assert machine.succeed("stat -c '%a %U %G' /var/lib/chuggy").strip() == "700 root root"
        assert (
            machine.succeed("stat -c '%a %u %g' /var/lib/chuggy/artifacts").strip()
            == "770 1000 1000"
        )
        assert (
            machine.succeed("stat -c '%a %U %G' /var/lib/chuggy/secrets").strip()
            == "700 root root"
        )
        assert (
            machine.succeed(
                "stat -c '%a %U %G' /var/lib/rancher/k3s/agent/images"
            ).strip()
            == "700 root root"
        )

    with subtest("every declared credential exists, root-only, and is not empty"):
        for key in keys:
            assert machine.succeed("stat -c '%a %U' " + pgdir + "/" + key).strip() == "600 root"
            machine.succeed("test -s " + pgdir + "/" + key)
        machine.succeed(
            "stat -c '%a %U' /var/lib/chuggy/secrets/chuggy-api/idempotency-keying"
            " | grep -qx '600 root'"
        )
        # The keying material is a versioned set, not a password: a retry of a
        # request accepted under an earlier version has to still find its
        # operation, which needs the older version to still be listed.
        machine.succeed(
            "jq -e '.current == \"v1\" and (.versions | length) == 1"
            " and (.versions[0].secret | length) > 0'"
            " /var/lib/chuggy/secrets/chuggy-api/idempotency-keying"
        )

    first = read_secrets()

    with subtest("distinct credentials, not one value copied six times"):
        assert len(set(first[key] for key in keys)) == len(keys)

    with subtest("no value reached the journal or /etc"):
        machine.succeed("journalctl -b --no-pager > /tmp/boot-journal")
        for key in keys:
            machine.fail("grep -qF " + first[key] + " /tmp/boot-journal")
            machine.fail("grep -RqF " + first[key] + " /etc")

    with subtest("running the generator again reuses what is already there"):
        machine.succeed("systemctl restart chuggy-secrets-generate.service")
        assert read_secrets() == first

    with subtest("the first synchronisation put every value into the cluster"):
        for key in keys:
            assert cluster_value(key) == first[key], key
        assert (
            machine.succeed(
                "jq -r '.metadata.labels[\"chuggy.dev/managed-by\"]' " + pgsecret
            ).strip()
            == "nixos"
        )

    with subtest("the run left nothing decoded in its runtime directory"):
        assert machine.succeed("ls -A /run/chuggy-secrets-sync | wc -l").strip() == "0"

    with subtest("a cluster that agrees is reported as agreeing"):
        # The whole point of the comparison, and the half that had never been
        # run: every key is present on both sides and identical, so the run says
        # nothing and succeeds.
        status, out = resync()
        assert status == 0, out
        assert "differs" not in out, out
        assert read_secrets() == first

    with subtest("a cluster that has drifted is reported as differing"):
        machine.succeed(
            "jq '.data[\"api-password\"] = \"ZHJpZnQ=\"' " + pgsecret + " > /tmp/drifted"
            " && mv /tmp/drifted " + pgsecret
        )
        status, out = resync()
        assert status == 0, out
        assert out.count("differs") == 1, out
        assert "api-password differs" in out, out
        # Neither side is touched by the report, which is what makes it safe to
        # leave the operator to decide.
        assert read_secrets() == first
        assert cluster_value("api-password") == "drift"

    with subtest("a key the host has lost is adopted back from the cluster"):
        machine.succeed("rm " + pgdir + "/scheduler-password")
        status, out = resync()
        assert status == 0, out
        assert "adopted chuggy-postgres-credentials/scheduler-password" in out, out
        assert read_secrets() == first

    with subtest("the restart budget can be reached before the window closes"):
        # A window shorter than the burst it bounds is never reached: the unit
        # restarts for ever and never lands in `systemctl --failed`, which is
        # the outcome the bound exists to produce. One attempt costs the wait
        # for the namespace plus the pause before systemd tries again.
        unit = "/etc/systemd/system/chuggy-secrets-sync.service"

        def setting(name):
            return int(machine.succeed("sed -n 's/^" + name + "=//p' " + unit).strip())

        attempt = namespace_timeout + setting("RestartSec")
        assert setting("StartLimitIntervalSec") >= (setting("StartLimitBurst") - 1) * attempt

    with subtest("synchronisation reports could-not-run, not success"):
        # The distinction the unit has to make is between "the cluster refused
        # this" and "there was no cluster to ask", and exit 2 is how it says the
        # second. Removing the kubeconfig is the case a box gets before k3s has
        # started; activation puts the file back at the next boot.
        machine.succeed("rm /etc/rancher/k3s/k3s.yaml")
        status, out = resync()
        assert status != 0, out
        assert "has not written a kubeconfig" in out, out
        assert (
            machine.succeed(
                "systemctl show -p ExecMainStatus --value chuggy-secrets-sync.service"
            ).strip()
            == "2"
        )

    machine.succeed("install -m 0644 -o 1000 -g 1000 /dev/null /var/lib/chuggy/artifacts/kept")

    machine.shutdown()
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("chuggy-secrets-generate.service")

    with subtest("a reboot changes neither the values nor the directories"):
        assert read_secrets() == first
        machine.succeed("test -f /var/lib/chuggy/artifacts/kept")
        assert (
            machine.succeed("stat -c '%a %u %g' /var/lib/chuggy/artifacts").strip()
            == "770 1000 1000"
        )
  '';
}
