# The release trigger, run as its pod is given it against an API server that
# is a file. What is the render's and what is this suite's, and the line of
# the decision each case is the only reader of, are in release-trigger.py's
# header.
#
# `busybox` for the reason release-publish.nix gives: the trigger's image is
# the same one.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-build-system.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-release-trigger" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  mkdir work
  python3 ${./release-trigger.py} ${rendered} ${pkgs.busybox}/bin "$PWD/work"
  touch "$out"
''
