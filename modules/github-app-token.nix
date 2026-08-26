{ config, pkgs, lib, ... }:

let
  cfg = config.chuggy.githubAppTokens;
  tokenModule = lib.types.submodule {
    options = {
      appId = lib.mkOption { type = lib.types.str; };
      installationId = lib.mkOption { type = lib.types.str; };
      repository = lib.mkOption { type = lib.types.str; };
      permission = lib.mkOption { type = lib.types.enum [ "read" "write" ]; };
      privateKeyFile = lib.mkOption { type = lib.types.str; };
      secretName = lib.mkOption { type = lib.types.str; };
      namespaces = lib.mkOption { type = lib.types.listOf lib.types.str; };
    };
  };
  refresh = name: token: pkgs.writeShellApplication {
    name = "chuggy-github-app-token-${name}-refresh";
    runtimeInputs = [ pkgs.coreutils cfg.curlPackage pkgs.jq cfg.kubectlPackage pkgs.openssl ];
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
        "$((now - 60))" "$((now + 540))" ${lib.escapeShellArg token.appId} | base64url)"
      unsigned="$header.$payload"
      signature="$(printf '%s' "$unsigned" | openssl dgst -sha256 \
        -sign ${lib.escapeShellArg token.privateKeyFile} | base64url)"
      jwt="$unsigned.$signature"

      printf '%s\n' \
        'header = "Accept: application/vnd.github+json"' \
        "header = \"Authorization: Bearer $jwt\"" \
        'header = "X-GitHub-Api-Version: 2022-11-28"' \
        > "$run/curl.conf"

      jq -n --arg repository ${lib.escapeShellArg token.repository} \
        --arg permission ${lib.escapeShellArg token.permission} \
        '{repositories:[$repository],permissions:{contents:$permission}}' > "$run/request.json"
      curl --fail-with-body --silent --show-error \
        --request POST \
        --config "$run/curl.conf" \
        --data-binary "@$run/request.json" \
        ${lib.escapeShellArg "https://api.github.com/app/installations/${token.installationId}/access_tokens"} \
        > "$run/response.json"
      jq -er '.token' "$run/response.json" > "$run/token"
      chmod 0600 "$run/token"
      base64 -w0 < "$run/token" > "$run/token.b64"

      for namespace in ${lib.escapeShellArgs token.namespaces}; do
        if kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} \
          --namespace "$namespace" get secret ${lib.escapeShellArg token.secretName} \
          -o json > "$run/live.json" 2>/dev/null; then
          if ! jq -e '.metadata.labels["chuggy.dev/managed-by"] == "github-app-token"' \
            "$run/live.json" >/dev/null; then
            echo "refusing to replace unmanaged Secret $namespace/${lib.escapeShellArg token.secretName}" >&2
            exit 3
          fi
          jq -n --rawfile token "$run/token.b64" \
            '{data:{token:($token | rtrimstr("\n"))}}' > "$run/patch.json"
          kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} \
            --namespace "$namespace" patch secret ${lib.escapeShellArg token.secretName} \
            --type=merge --patch-file "$run/patch.json" >/dev/null
        else
          kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} \
            --namespace "$namespace" create secret generic ${lib.escapeShellArg token.secretName} \
            --from-file=token="$run/token" --dry-run=client -o json \
            | jq '.metadata.labels = {"chuggy.dev/managed-by":"github-app-token"}' \
            | kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} create -f - >/dev/null
        fi
      done
    '';
  };
  services = lib.mapAttrs' (name: token:
    lib.nameValuePair "chuggy-github-app-token-${name}-refresh" {
      description = "Refresh Chuggy's ${name} GitHub App token";
      after = [ "network-online.target" "k3s.service" ];
      wants = [ "network-online.target" "k3s.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = lib.getExe (refresh name token);
        RuntimeDirectory = "chuggy-github-app-token-${name}-refresh";
        RuntimeDirectoryMode = "0700";
        Restart = "on-failure";
        RestartPreventExitStatus = 3;
        RestartSec = cfg.retrySeconds;
      };
      unitConfig = {
        StartLimitIntervalSec = cfg.retryWindowSeconds;
        StartLimitBurst = cfg.retryBurst;
      };
    }) cfg.tokens;
  timers = lib.mapAttrs' (name: _:
    lib.nameValuePair "chuggy-github-app-token-${name}-refresh" {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2m";
        OnUnitActiveSec = "30m";
        RandomizedDelaySec = "2m";
        Persistent = true;
        Unit = "chuggy-github-app-token-${name}-refresh.service";
      };
    }) cfg.tokens;
in
{
  options.chuggy.githubAppTokens = {
    enable = lib.mkEnableOption "GitHub App installation-token delivery";
    tokens = lib.mkOption {
      type = lib.types.attrsOf tokenModule;
      default = { };
    };
    kubeconfig = lib.mkOption {
      type = lib.types.str;
      default = "/etc/rancher/k3s/k3s.yaml";
    };
    retrySeconds = lib.mkOption {
      type = lib.types.ints.positive;
      default = 120;
    };
    retryWindowSeconds = lib.mkOption {
      type = lib.types.ints.positive;
      default = 1200;
    };
    retryBurst = lib.mkOption {
      type = lib.types.ints.positive;
      default = 6;
    };
    curlPackage = lib.mkOption {
      type = lib.types.package;
      default = pkgs.curl;
      internal = true;
    };
    kubectlPackage = lib.mkOption {
      type = lib.types.package;
      default = pkgs.kubectl;
      internal = true;
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      { assertion = cfg.tokens != { }; message = "chuggy.githubAppTokens.tokens is empty"; }
    ];
    systemd.services = services;
    systemd.timers = timers;
  };
}
