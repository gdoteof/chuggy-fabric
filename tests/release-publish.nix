# The `publish` step of the release pipeline, run as its pod is given it over
# this repository's own two release directories. What is the render's and what
# is this suite's, and the part of the script each case is the only reader
# of, are in release-publish.py's header.
#
# `busybox` because the step's image is Alpine and its `/bin/sh`, `awk`, `sed`
# and `date` are BusyBox's: a script that leaned on bash or GNU would pass
# under this build's own tools.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-build-system.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-release-publish" {
  nativeBuildInputs = [ python pkgs.kubectl ];
} ''
  set -eu
  mkdir work
  python3 ${./release-publish.py} ${rendered} ${../cluster} ${pkgs.busybox}/bin "$PWD/work"
  touch "$out"
''
