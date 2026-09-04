# What the mirror sync moves, and what it is permitted to reach, read off the
# rendered manifests rather than off the text that produces them.
#
# The property is one no grep can hold: the two repositories this job keeps
# equal are written again in the scheduler's mirrors map, its repositories map
# and the importer's script, and a job pointed at the wrong pair runs green
# forever -- which is kasofsk/chuggy#554 with a job in front of it. The argument
# for each assertion is in git-mirror.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-git-mirror" {
  nativeBuildInputs = [ pkgs.kubectl python ];
} ''
  set -eu
  kubectl kustomize ${../cluster/apps} > rendered.yaml
  python3 ${./git-mirror.py} rendered.yaml
  touch "$out"
''
