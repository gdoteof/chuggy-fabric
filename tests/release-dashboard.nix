# The release dashboard and what feeds it, read off the rendered manifests. What
# each assertion holds and why is in release-dashboard.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-release-dashboard" {
  nativeBuildInputs = [ pkgs.kubectl python ];
} ''
  set -eu
  kubectl kustomize ${../cluster/apps} > rendered.yaml
  python3 ${./release-dashboard.py} rendered.yaml
  touch "$out"
''
