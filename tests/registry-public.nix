# The registry's public front, read off the rendered manifests. What each
# assertion holds and why is in registry-public.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-registry-public" {
  nativeBuildInputs = [ pkgs.kubectl python ];
} ''
  set -eu
  kubectl kustomize ${../cluster/apps} > rendered.yaml
  python3 ${./registry-public.py} rendered.yaml
  touch "$out"
''
