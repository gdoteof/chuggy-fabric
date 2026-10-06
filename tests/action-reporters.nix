# Who reports an action against who verifies the report: the API's roster and
# its Secret volumes, the release pipeline's `report` task, the Provider and
# the Alerts Flux reports a rollout by, and the Secrets the host makes for
# all of them. The argument for each assertion is in action-reporters.py's
# own header.
#
# The host's two scripts are handed over as they are built rather than their
# Secrets restated here, for the reason tests/forge-app-key.nix hands over the
# host's apps: the name a manifest mounts and the name the host synchronises
# are one value and cannot drift. The root's layers and the Flux install are
# the host's for the same reason, as tests/flux-layers.nix and
# tests/flux-components.nix take them.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
  build = import ./rendered-build-system.nix { inherit pkgs; };
  script = unit: host.config.systemd.services.${unit}.serviceConfig.ExecStart;
  layers = ../. + "/${host.config.chuggy.flux.path}";
in
pkgs.runCommand "chuggy-action-reporters" {
  nativeBuildInputs = [ pkgs.kubectl python ];
} ''
  set -eu
  kubectl kustomize ${layers} > layers.yaml
  python3 ${./action-reporters.py} ${cluster} ${build} \
    ${script "chuggy-secrets-generate"} ${script "chuggy-secrets-sync"} \
    layers.yaml ${host.config.services.k3s.manifests.flux-components.source}
  touch "$out"
''
