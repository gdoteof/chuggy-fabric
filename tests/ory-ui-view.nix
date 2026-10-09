# The image the self-service UI runs against the one each of its views names,
# read off the rendered manifests: a view reaches the pod through a generated
# ConfigMap whose name only the render knows. The argument is in
# ory-ui-view.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-ory-ui-view" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./ory-ui-view.py} ${rendered}/cluster.yaml
  touch "$out"
''
