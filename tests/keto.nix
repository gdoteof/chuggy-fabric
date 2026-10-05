# Which of Keto's ports are reachable from where, read off the rendered
# manifests rather than off the text that produces them.
#
# The property is one no file states alone: a pod label, a list of values on one
# NetworkPolicy, two Services that target container ports by name, a probe, and
# each caller's URL and egress arm in another namespace, and the ways of getting
# it wrong read correctly in each. The argument for each assertion is in
# keto.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-keto" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./keto.py} ${rendered}/cluster.yaml
  touch "$out"
''
