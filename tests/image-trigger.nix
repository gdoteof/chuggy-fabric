# The image trigger, run as its pod is given it against an API server that
# is a file, as release-trigger.nix runs the release trigger. The cases are in
# image-trigger.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-build-system.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-image-trigger" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  mkdir work
  python3 ${./image-trigger.py} ${rendered} ${pkgs.busybox}/bin "$PWD/work"
  touch "$out"
''
