# The `publish` step of the site pipeline, run as its pod is given it over
# this repository's own site layer, as release-publish.nix runs the release's.
# The cases are in site-publish.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-build-system.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-site-publish" {
  nativeBuildInputs = [ python pkgs.kubectl ];
} ''
  set -eu
  mkdir work
  python3 ${./site-publish.py} ${rendered} ${../cluster} ${pkgs.busybox}/bin "$PWD/work"
  touch "$out"
''
