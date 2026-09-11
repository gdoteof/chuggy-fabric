{ config, pkgs, lib, ... }:

let
  cfg = config.chuggy.githubAppTokens;
  appModule = lib.types.submodule {
    options = {
      appId = lib.mkOption { type = lib.types.str; };
      privateKeyFile = lib.mkOption { type = lib.types.str; };
      # The Secret the key file above is copied into by hand, for the pods that
      # mint for themselves. Nothing here writes it -- the README's
      # prerequisite 5 is the operator making it by hand from the file above,
      # and this option is the second declaration that makes the name in a
      # manifest a copy of a value rather than a literal that agrees with
      # itself. Which App a pod mounts is then decided by its `secretName` as
      # well as by the id it writes, and `tests/forge-app-key.py` holds the two
      # together.
      keySecret = lib.mkOption { type = lib.types.str; };
    };
  };
  repositoryModule = lib.types.submodule {
    options = {
      repository = lib.mkOption { type = lib.types.str; };
      portalInstallationId = lib.mkOption { type = lib.types.str; };
      buildReaderSecret = lib.mkOption { type = lib.types.str; };
    };
  };
  # The one token a repository this site builds images for needs: the
  # basic-auth credential Shipwright clones its source with. A pod that acts on
  # a repository mints for itself from the App key it mounts, so no token here
  # is a pod's. Which App mints it is the split AGENTS.md states and is not a
  # per-repository choice: the Portal App, reading.
  repositoryTokens = name: repository: {
    "build-reader-${name}" = {
      inherit (cfg.apps.portal) appId privateKeyFile;
      installationId = repository.portalInstallationId;
      inherit (repository) repository;
      permission = "read";
      secretName = repository.buildReaderSecret;
      namespaces = [ "chuggy-build" ];
      secretFormat = "git-basic-auth";
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
    # The Apps this machine holds keys for, by the role AGENTS.md gives each,
    # where it keeps them and which Secret each is handed to a pod through.
    # This module mints under the portal App alone; the worker App is declared
    # here because a pod that mounts its key names its id and the Secret that
    # key arrives in, and `tests/forge-app-key.py` holds both against this.
    apps = lib.mkOption {
      type = lib.types.attrsOf appModule;
      default = { };
    };
    # The repositories whose sources this host mints a clone credential for,
    # which is `repositories.nix` passed through. It exists beside `tokens`
    # below so that a repository is an entry rather than a block: what differs
    # between two of them is an installation id, a Secret name and the
    # repository the rendered script requests.
    repositories = lib.mkOption {
      type = lib.types.attrsOf repositoryModule;
      default = { };
    };
    # What is actually delivered. A host may write one directly -- a token that
    # is no repository's clone credential, the way gtr writes the one its build
    # provenance is published with -- and every entry of `repositories` above
    # arrives here.
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
        assertion = cfg.repositories == { } || cfg.apps ? portal;
        message = "chuggy.githubAppTokens.apps does not name portal";
      }
    ];
    chuggy.githubAppTokens.tokens = lib.concatMapAttrs repositoryTokens cfg.repositories;
    systemd.services = services;
    systemd.timers = timers;
  };
}
