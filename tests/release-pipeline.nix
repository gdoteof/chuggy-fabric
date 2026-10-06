# The release pipeline's manifests, read off what `kubectl kustomize` renders
# from every directory a layer applies. The argument for each assertion is in
# release-pipeline.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  build = import ./rendered-build-system.nix { inherit pkgs; };
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-release-pipeline" {
  nativeBuildInputs = [ python pkgs.kubectl ];
} ''
  set -eu
  kubectl kustomize ${../cluster/flux} > flux.yaml
  kubectl kustomize ${../cluster/build-prerequisites} > build-prerequisites.yaml
  python3 ${./release-pipeline.py} ${build} ${cluster}/apps.yaml flux.yaml ${../cluster/build-system} \
    ${cluster}/chuggy-migrate.yaml ${cluster}/chuggy.yaml build-prerequisites.yaml
  touch "$out"
''
