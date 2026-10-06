# The alert for a release trigger that has stopped, evaluated by promtool over
# the series a CronJob is exported as. The cases, and the one thing read
# rather than evaluated, are in release-alert.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  build = import ./rendered-build-system.nix { inherit pkgs; };
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-release-alert" {
  nativeBuildInputs = [ python pkgs.prometheus.cli ];
} ''
  set -eu
  mkdir work
  python3 ${./release-alert.py} ${build} ${cluster}/apps.yaml work
  touch "$out"
''
