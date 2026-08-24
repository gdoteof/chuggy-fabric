{ pkgs, host }:

let
  registry = import ../modules/registry-contract.nix;
  registryConfig = host.config.environment.etc."rancher/k3s/registries.yaml".source;
  endpoint = "http://${registry.clusterIP}:${toString registry.port}";
in
pkgs.runCommand "chuggy-registry-wiring" { } ''
  grep -F ${pkgs.lib.escapeShellArg registry.logicalName} ${registryConfig} >/dev/null
  grep -F ${pkgs.lib.escapeShellArg endpoint} ${registryConfig} >/dev/null
  grep -F ${pkgs.lib.escapeShellArg "clusterIP: ${registry.clusterIP}"} \
    ${../cluster/apps/registry.yaml} >/dev/null
  touch $out
''
