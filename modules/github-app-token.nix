{ config, pkgs, lib, ... }:

let
  cfg = config.chuggy.githubAppToken;
  refresh = pkgs.writeShellApplication {
    name = "chuggy-github-app-token-refresh";
    runtimeInputs = [ pkgs.coreutils pkgs.curl pkgs.jq pkgs.kubectl pkgs.openssl ];
    text = ''
      umask 077
      run="''${RUNTIME_DIRECTORY:-$(mktemp -d)}"
      trap 'rm -f "$run"/*' EXIT

      base64url() {
        openssl base64 -A | tr '+/' '-_' | tr -d '='
      }

      now="$(date +%s)"
      header="$(printf '%s' '{"alg":"RS256","typ":"JWT"}' | base64url)"
      payload="$(printf '{"iat":%s,"exp":%s,"iss":"%s"}' \
        "$((now - 60))" "$((now + 540))" ${lib.escapeShellArg cfg.appId} | base64url)"
      unsigned="$header.$payload"
      signature="$(printf '%s' "$unsigned" | openssl dgst -sha256 \
        -sign ${lib.escapeShellArg cfg.privateKeyFile} | base64url)"
      jwt="$unsigned.$signature"

      printf '%s\n' \
        'header = "Accept: application/vnd.github+json"' \
        "header = \"Authorization: Bearer $jwt\"" \
        'header = "X-GitHub-Api-Version: 2022-11-28"' \
        > "$run/curl.conf"

      jq -n --arg repository ${lib.escapeShellArg cfg.repository} \
        '{repositories:[$repository],permissions:{contents:"write"}}' > "$run/request.json"
      curl --fail-with-body --silent --show-error \
        --request POST \
        --config "$run/curl.conf" \
        --data-binary "@$run/request.json" \
        ${lib.escapeShellArg "https://api.github.com/app/installations/${cfg.installationId}/access_tokens"} \
        > "$run/response.json"
      jq -er '.token' "$run/response.json" > "$run/token"
      chmod 0600 "$run/token"
      base64 -w0 < "$run/token" > "$run/token.b64"

      for namespace in ${lib.escapeShellArgs cfg.namespaces}; do
        if kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} \
          --namespace "$namespace" get secret chuggy-github-app-token -o json > "$run/live.json" 2>/dev/null; then
          jq -e '.metadata.labels["chuggy.dev/managed-by"] == "github-app-token"' \
            "$run/live.json" >/dev/null
          jq -n --rawfile token "$run/token.b64" \
            '{data:{token:($token | rtrimstr("\n"))}}' > "$run/patch.json"
          kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} \
            --namespace "$namespace" patch secret chuggy-github-app-token \
            --type=merge --patch-file "$run/patch.json" >/dev/null
        else
          kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} \
            --namespace "$namespace" create secret generic chuggy-github-app-token \
            --from-file=token="$run/token" --dry-run=client -o json \
            | jq '.metadata.labels = {"chuggy.dev/managed-by":"github-app-token"}' \
            | kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} create -f - >/dev/null
        fi
      done
    '';
  };
in
{
  options.chuggy.githubAppToken = {
    enable = lib.mkEnableOption "GitHub App installation-token delivery";

    appId = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "GitHub App id used as the JWT issuer.";
    };

    installationId = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Installation whose repository-scoped token is minted.";
    };

    repository = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Repository name within the selected installation.";
    };

    privateKeyFile = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Root-readable GitHub App private key outside the Nix store.";
    };

    namespaces = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Namespaces that receive the rotating token Secret.";
    };

    kubeconfig = lib.mkOption {
      type = lib.types.str;
      default = "/etc/rancher/k3s/k3s.yaml";
      description = "Kubeconfig used to replace the token Secret.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      { assertion = cfg.appId != ""; message = "chuggy.githubAppToken.appId is unset"; }
      { assertion = cfg.installationId != ""; message = "chuggy.githubAppToken.installationId is unset"; }
      { assertion = cfg.repository != ""; message = "chuggy.githubAppToken.repository is unset"; }
      { assertion = cfg.privateKeyFile != ""; message = "chuggy.githubAppToken.privateKeyFile is unset"; }
      { assertion = cfg.namespaces != [ ]; message = "chuggy.githubAppToken.namespaces is empty"; }
    ];

    systemd.services.chuggy-github-app-token-refresh = {
      description = "Refresh Chuggy's repository-scoped GitHub App token";
      after = [ "network-online.target" "k3s.service" ];
      wants = [ "network-online.target" "k3s.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = lib.getExe refresh;
        RuntimeDirectory = "chuggy-github-app-token-refresh";
        RuntimeDirectoryMode = "0700";
      };
    };

    systemd.timers.chuggy-github-app-token-refresh = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2m";
        OnUnitActiveSec = "30m";
        RandomizedDelaySec = "2m";
        Persistent = true;
        Unit = "chuggy-github-app-token-refresh.service";
      };
    };
  };
}
