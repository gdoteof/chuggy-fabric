# The `fetch` and `build` steps of the release pipeline, each run as its pod
# is given it: the fetch against a repository this build commits to, the
# build against a registry that is a file. What is the render's and what is
# this suite's, and the part of a script each case is the only reader of, are
# in release-build.py's header.
#
# `busybox` for the reason release-publish.nix gives: the steps' image is
# Alpine as well. `git` is the real one, as it is in that image.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-build-system.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-release-build" {
  nativeBuildInputs = [ python pkgs.git ];
} ''
  set -eu
  mkdir work
  python3 ${./release-build.py} ${rendered} ${pkgs.busybox}/bin "$PWD/work"
  touch "$out"
''
