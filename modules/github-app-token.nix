{ config, pkgs, lib, ... }:

let
  cfg = config.chuggy.githubAppTokens;
  appModule = lib.types.submodule {
    options = {
      appId = lib.mkOption { type = lib.types.str; };
      privateKeyFile = lib.mkOption { type = lib.types.str; };
    };
  };
  repositoryModule = lib.types.submodule {
    options = {
      repository = lib.mkOption { type = lib.types.str; };
      portalInstallationId = lib.mkOption { type = lib.types.str; };
      workerInstallationId = lib.mkOption { type = lib.types.str; };
      readerSecret = lib.mkOption { type = lib.types.str; };
      finalizerSecret = lib.mkOption { type = lib.types.str; };
      buildReaderSecret = lib.mkOption { type = lib.types.str; };
      workerSecret = lib.mkOption { type = lib.types.str; };
    };
  };
  # The four tokens one repository needs, which is what makes a second
  # repository's credentials an entry rather than four copies of a block. Which
  # App mints which is the split AGENTS.md states and is not a per-repository
  # choice: Portal reads and finalizes, Worker executes, and neither is ever
  # given the other's authority.
  repositoryTokens = name: repository:
    let
      portal = permission: {
        inherit (cfg.apps.portal) appId privateKeyFile;
        installationId = repository.portalInstallationId;
        inherit (repository) repository;
        inherit permission;
      };
    in
    {
      "reader-${name}" = portal "read" // {
        secretName = repository.readerSecret;
        namespaces = [ "chuggy" ];
      };
      "finalizer-${name}" = portal "write" // {
        secretName = repository.finalizerSecret;
        namespaces = [ "chuggy" ];
      };
      "build-reader-${name}" = portal "read" // {
        secretName = repository.buildReaderSecret;
        namespaces = [ "chuggy-build" ];
        secretFormat = "git-basic-auth";
      };
      "worker-${name}" = {
        inherit (cfg.apps.worker) appId privateKeyFile;
        installationId = repository.workerInstallationId;
        inherit (repository) repository;
        permission = "write";
        secretName = repository.workerSecret;
        namespaces = [ "chuggy-work" ];
      };
    };
  tokenModule = lib.types.submodule {
    options = {
      appId = lib.mkOption { type = lib.types.str; };
      installationId = lib.mkOption { type = lib.types.str; };
      repository = lib.mkOption { type = lib.types.str; };
      permission = lib.mkOption { type = lib.types.enum [ "read" "write" ]; };
      privateKeyFile = lib.mkOption { type = lib.types.str; };
      secretName = lib.mkOption { type = lib.types.str; };
      namespaces = lib.mkOption { type = lib.types.listOf lib.types.str; };
      secretFormat = lib.mkOption {
        type = lib.types.enum [ "token" "git-basic-auth" ];
        default = "token";
      };
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
      printf '%s' 'x-access-token' | base64 -w0 > "$run/username.b64"

      sync_secret() {
        namespace="$1"
        if kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} \
          --namespace "$namespace" get secret ${lib.escapeShellArg token.secretName} \
          -o json > "$run/live.json" 2>/dev/null; then
          if ! jq -e '.metadata.labels["chuggy.dev/managed-by"] == "github-app-token"' \
            "$run/live.json" >/dev/null; then
            echo "refusing to replace unmanaged Secret $namespace/${lib.escapeShellArg token.secretName}" >&2
            exit 3
          fi
          ${if token.secretFormat == "git-basic-auth" then ''
            jq -n --rawfile username "$run/username.b64" --rawfile password "$run/token.b64" \
              '{type:"kubernetes.io/basic-auth",data:{username:($username | rtrimstr("\n")),password:($password | rtrimstr("\n")),token:null}}' \
              > "$run/patch.json"
          '' else ''
            jq -n --rawfile token "$run/token.b64" \
              '{data:{token:($token | rtrimstr("\n"))}}' > "$run/patch.json"
          ''}
          kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} \
            --namespace "$namespace" patch secret ${lib.escapeShellArg token.secretName} \
            --type=merge --patch-file "$run/patch.json" >/dev/null
        else
          ${if token.secretFormat == "git-basic-auth" then ''
            jq -n --arg name ${lib.escapeShellArg token.secretName} --arg namespace "$namespace" \
              --rawfile username "$run/username.b64" --rawfile password "$run/token.b64" \
              '{apiVersion:"v1",kind:"Secret",type:"kubernetes.io/basic-auth",metadata:{name:$name,namespace:$namespace,labels:{"chuggy.dev/managed-by":"github-app-token"}},data:{username:($username | rtrimstr("\n")),password:($password | rtrimstr("\n"))}}' \
              | kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} create -f - >/dev/null
          '' else ''
            kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} \
              --namespace "$namespace" create secret generic ${lib.escapeShellArg token.secretName} \
              --from-file=token="$run/token" --dry-run=client -o json \
              | jq '.metadata.labels = {"chuggy.dev/managed-by":"github-app-token"}' \
              | kubectl --kubeconfig ${lib.escapeShellArg cfg.kubeconfig} create -f - >/dev/null
          ''}
        fi
      }

      ${lib.concatMapStringsSep "\n" (namespace:
        "sync_secret ${lib.escapeShellArg namespace}") token.namespaces}
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
    # The two Apps, by the role AGENTS.md gives each, and where this machine
    # keeps their keys. The key paths are the host's fact; which App mints what
    # is not.
    apps = lib.mkOption {
      type = lib.types.attrsOf appModule;
      default = { };
    };
    # The repositories this host mints tokens for. One entry is four tokens,
    # which is the whole reason this option exists beside `tokens` below: a
    # second repository under a second owner differs in two installation ids,
    # four Secret names, and the repository each rendered script requests.
    repositories = lib.mkOption {
      type = lib.types.attrsOf repositoryModule;
      default = { };
    };
    # What is actually delivered. A host may write one directly -- a token that
    # is not one of a repository's four -- and every entry of `repositories`
    # above arrives here.
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
      {
        assertion = cfg.repositories == { } || (cfg.apps ? portal && cfg.apps ? worker);
        message = "chuggy.githubAppTokens.apps does not name both portal and worker";
      }
    ];
    chuggy.githubAppTokens.tokens = lib.concatMapAttrs repositoryTokens cfg.repositories;
    systemd.services = services;
    systemd.timers = timers;
  };
}
