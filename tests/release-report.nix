# The `report` step of the release pipeline, run as its pod is given it
# against an API that is this build's own. What is the render's and what is
# this suite's, and the part of the script each case is the only reader of,
# are in release-report.py's header.
#
# `busybox` for the reason release-publish.nix gives: the step's image is
# Alpine as well. `curl` is the real one, as it is in that image; `openssl`
# makes the certificate this build's API answers with.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-build-system.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-release-report" {
  nativeBuildInputs = [ python pkgs.curl pkgs.openssl ];
} ''
  set -eu
  mkdir work
  python3 ${./release-report.py} ${rendered} ${pkgs.busybox}/bin "$PWD/work"
  touch "$out"
''
