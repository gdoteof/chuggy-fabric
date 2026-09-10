# Which of Keto's ports are reachable from where, read off the rendered
# manifests rather than off the text that produces them.
#
# The property is one no file states alone: a pod label, a list of values on one
# NetworkPolicy, two Services that target container ports by name, a probe, and
# a URL in another namespace are five places, and the ways of getting it wrong
# read correctly in each. The argument for each assertion is in keto.py's own
# header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-keto" {
  nativeBuildInputs = [ pkgs.kubectl python ];
} ''
  set -eu
  kubectl kustomize ${../cluster/apps} > rendered.yaml
  python3 ${./keto.py} rendered.yaml
  touch "$out"
''
