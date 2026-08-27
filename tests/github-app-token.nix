{ pkgs }:

let
  clusterStore = "/var/lib/fake-cluster";
  githubStore = "/var/lib/fake-github";

  curlStub = final: final.writeShellApplication {
    name = "curl";
    runtimeInputs = [ final.coreutils ];
    text = ''
      mkdir -p ${githubStore}
      attempts=0
      if [ -f ${githubStore}/attempts ]; then
        attempts="$(cat ${githubStore}/attempts)"
      fi
      attempts="$((attempts + 1))"
      printf '%s\n' "$attempts" > ${githubStore}/attempts
      if [ -e ${githubStore}/fail-next ]; then
        rm ${githubStore}/fail-next
        echo "transient GitHub failure" >&2
        exit 22
      fi
      printf '{"token":"token-%s"}\n' "$attempts"
    '';
  };

  kubectlStub = final: final.writeShellApplication {
    name = "kubectl";
    runtimeInputs = [ final.coreutils final.jq ];
    text = ''
      ns=default
      patchfile=""
      tokenfile=""
      dryrun=false
      rest=()
      while [ "$#" -gt 0 ]; do
        case "$1" in
          --kubeconfig) shift 2 ;;
          -n|--namespace) ns="$2"; shift 2 ;;
          --patch-file) patchfile="$2"; shift 2 ;;
          --from-file=token=*) tokenfile="''${1#--from-file=token=}"; shift ;;
          --dry-run=client) dryrun=true; shift ;;
          --type=*|-o) if [ "$1" = "-o" ]; then shift 2; else shift; fi ;;
          *) rest+=("$1"); shift ;;
        esac
      done
      dir=${clusterStore}/$ns
      case "''${rest[0]:-} ''${rest[1]:-}" in
        "get secret")
          object="$dir/''${rest[2]}.json"
          [ -f "$object" ] || exit 1
          cat "$object"
          ;;
        "create secret")
          [ "$dryrun" = true ] || exit 64
          token="$(base64 -w0 < "$tokenfile")"
          jq -n --arg name "''${rest[3]}" --arg namespace "$ns" --arg token "$token" \
            '{apiVersion:"v1",kind:"Secret",metadata:{name:$name,namespace:$namespace},data:{token:$token}}'
          ;;
        "create -f")
          body="$(cat)"
          object="$(printf '%s' "$body" | jq -r '.metadata.name')"
          ns="$(printf '%s' "$body" | jq -r '.metadata.namespace')"
          dir=${clusterStore}/$ns
          mkdir -p "$dir"
          printf '%s\n' "$body" | jq . > "$dir/$object.json"
          ;;
        "patch secret")
          jq -s '.[0] * .[1]' "$dir/''${rest[2]}.json" "$patchfile" > "$dir/''${rest[2]}.next"
          mv "$dir/''${rest[2]}.next" "$dir/''${rest[2]}.json"
          ;;
        *)
          echo "kubectl stub: unhandled call: ''${rest[*]}" >&2
          exit 64
          ;;
      esac
    '';
  };

  testKey = pkgs.runCommand "github-app-test-key.pem" {
    nativeBuildInputs = [ pkgs.openssl ];
  } ''
    openssl genrsa -out "$out" 2048 2>/dev/null
  '';
in
pkgs.testers.runNixOSTest {
  name = "chuggy-github-app-token";

  nodes.machine = { ... }: {
    imports = [ ../modules/github-app-token.nix ];
    environment.systemPackages = [ pkgs.jq ];
    chuggy.githubAppTokens = {
      enable = true;
      curlPackage = curlStub pkgs;
      kubectlPackage = kubectlStub pkgs;
      retrySeconds = 1;
      retryWindowSeconds = 30;
      retryBurst = 6;
      tokens.worker = {
        appId = "4728465";
        installationId = "156786211";
        repository = "chuggy";
        permission = "write";
        privateKeyFile = "${testKey}";
        secretName = "chuggy-github-worker-token";
        namespaces = [ "chuggy" "chuggy-work" ];
      };
      tokens.reader = {
        appId = "4708055";
        installationId = "156333284";
        repository = "chuggy";
        permission = "read";
        privateKeyFile = "${testKey}";
        secretName = "chuggy-github-reader-token";
        namespaces = [ "chuggy" ];
      };
      tokens.build-reader = {
        appId = "4708055";
        installationId = "156333284";
        repository = "chuggy";
        permission = "read";
        privateKeyFile = "${testKey}";
        secretName = "chuggy-build-source-read";
        namespaces = [ "chuggy-build" ];
        secretFormat = "git-basic-auth";
      };
    };
    environment.etc."rancher/k3s/k3s.yaml".text = "stub kubeconfig\n";
    systemd.tmpfiles.rules = [
      "d ${clusterStore} 0700 root root -"
      "d ${githubStore} 0700 root root -"
    ];
  };

  testScript = ''
    import json
    import time

    service = "chuggy-github-app-token-worker-refresh.service"
    timer = "chuggy-github-app-token-worker-refresh.timer"
    reader_service = "chuggy-github-app-token-reader-refresh.service"
    build_reader_service = "chuggy-github-app-token-build-reader-refresh.service"
    secret = "chuggy-github-worker-token.json"

    def object_in(namespace):
        return "${clusterStore}/" + namespace + "/" + secret

    def decoded_token(namespace):
        return machine.succeed(
            "jq -r '.data.token' " + object_in(namespace) + " | base64 -d"
        ).strip()

    machine.wait_for_unit("multi-user.target")

    with subtest("evaluation emits bounded retry and periodic refresh units"):
        assert machine.succeed("systemctl show -p Restart --value " + service).strip() == "on-failure"
        assert machine.succeed("systemctl show -p RestartUSec --value " + service).strip() == "1s"
        assert machine.succeed("systemctl show -p StartLimitBurst --value " + service).strip() == "6"
        assert machine.succeed("systemctl show -p Persistent --value " + timer).strip() == "yes"
        assert machine.succeed("systemctl show -p LoadState --value " + reader_service).strip() == "loaded"
        assert machine.succeed("systemctl show -p LoadState --value " + build_reader_service).strip() == "loaded"

    with subtest("a first refresh creates labelled Secrets in every namespace"):
        machine.succeed("systemctl start " + service)
        for namespace in ["chuggy", "chuggy-work"]:
            value = json.loads(machine.succeed("cat " + object_in(namespace)))
            assert value["metadata"]["labels"]["chuggy.dev/managed-by"] == "github-app-token"
            assert decoded_token(namespace) == "token-1"

    with subtest("a later refresh patches a managed Secret"):
        machine.succeed("systemctl restart " + service)
        assert decoded_token("chuggy") == "token-2"
        assert decoded_token("chuggy-work") == "token-2"

    with subtest("an unmanaged Secret is refused and is not retried"):
        path = object_in("chuggy")
        machine.succeed("jq 'del(.metadata.labels)' " + path + " > /tmp/unmanaged && mv /tmp/unmanaged " + path)
        before = decoded_token("chuggy")
        status, _ = machine.execute("systemctl restart " + service)
        assert status != 0
        assert machine.succeed("systemctl show -p ExecMainStatus --value " + service).strip() == "3"
        assert machine.succeed("systemctl show -p ActiveState --value " + service).strip() == "failed"
        assert decoded_token("chuggy") == before

    with subtest("a transient mint failure is retried and replaces the old token"):
        path = object_in("chuggy")
        machine.succeed("jq '.metadata.labels = {\"chuggy.dev/managed-by\":\"github-app-token\"}' " + path + " > /tmp/managed && mv /tmp/managed " + path)
        machine.succeed("systemctl reset-failed " + service)
        machine.succeed("touch ${githubStore}/fail-next")
        machine.succeed("systemctl start --no-block " + service)
        deadline = time.time() + 15
        while time.time() < deadline and decoded_token("chuggy") != "token-5":
            time.sleep(0.5)
        assert decoded_token("chuggy") == "token-5"
        assert decoded_token("chuggy-work") == "token-5"
        assert machine.succeed("cat ${githubStore}/attempts").strip() == "5"

    with subtest("git credentials use Kubernetes basic-auth keys"):
        machine.succeed("systemctl start " + build_reader_service)
        value = json.loads(machine.succeed("cat ${clusterStore}/chuggy-build/chuggy-build-source-read.json"))
        assert value["type"] == "kubernetes.io/basic-auth"
        assert machine.succeed("printf %s '" + value["data"]["username"] + "' | base64 -d").strip() == "x-access-token"
        assert machine.succeed("printf %s '" + value["data"]["password"] + "' | base64 -d").strip() == "token-6"
  '';
}
