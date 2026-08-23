{ pkgs }:

# Boots the substrate and asks it the questions evaluation cannot answer.
#
# Every claim below is about something that only exists once systemd has run:
# a directory's mode, a file that was generated rather than declared, a value
# that is the same after a reboot as before it, a unit that reports a
# precondition it cannot satisfy instead of reporting success.
#
# WHAT IT DOES NOT COVER, and the list matters more than the list above. It does
# not start k3s, so it proves nothing about the firewall rules, the auto-deploy
# ordering, the image import, or Flux. Those need a cluster, and a cluster in a
# test VM is a second rig with its own failure modes -- one that would make this
# check slow enough to be skipped, which is the state in which a check enforces
# nothing. The synchronisation is exercised only in its could-not-run path, and
# its create-if-absent behaviour against a real Secret is not tested here at
# all.
#
# The secret values are not in the Nix store, and this test does not prove that
# either. It is structural: what the store holds is a generator, and the value
# comes into existence when the generator runs on the host. What the test does
# check is that they do not leak into the journal, which is the way a script
# like this normally spills one.

pkgs.testers.runNixOSTest {
  name = "chuggy-substrate";

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
  };

  testScript = ''
    keys = [
        "owner-password",
        "api-password",
        "ticket-service-password",
        "selector-service-password",
        "scheduler-password",
        "finalizer-password",
    ]
    pgdir = "/var/lib/chuggy/secrets/chuggy-postgres-credentials"


    def read_secrets():
        out = {}
        for key in keys:
            out[key] = machine.succeed("cat " + pgdir + "/" + key).strip()
        out["idempotency-keying"] = machine.succeed(
            "cat /var/lib/chuggy/secrets/chuggy-api/idempotency-keying"
        ).strip()
        return out


    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("chuggy-secrets-generate.service")

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
        for key in keys:
            machine.fail("journalctl -b --no-pager | grep -qF " + first[key])
            machine.fail("grep -RqF " + first[key] + " /etc")

    with subtest("running the generator again reuses what is already there"):
        machine.succeed("systemctl restart chuggy-secrets-generate.service")
        assert read_secrets() == first

    with subtest("synchronisation reports could-not-run, not success"):
        # Nothing here runs k3s, so there is no kubeconfig. The distinction the
        # unit has to make is between "the cluster refused this" and "there was
        # no cluster to ask", and exit 2 is how it says the second.
        machine.wait_until_succeeds(
            "journalctl -u chuggy-secrets-sync.service --no-pager"
            " | grep -q 'has not written a kubeconfig'"
        )
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
