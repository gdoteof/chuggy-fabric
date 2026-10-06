# The release dashboard and what feeds it, read off what the tree declares:
# the rendered `apps` layer, Flux's own components and the rendered build
# system, where Tekton is. What each assertion holds and why is in
# release-dashboard.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  build = import ./rendered-build-system.nix { inherit pkgs; };
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-release-dashboard" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./release-dashboard.py} ${cluster}/apps.yaml \
    ${../cluster/flux-system/gotk-components.yaml} ${build}
  touch "$out"
''
