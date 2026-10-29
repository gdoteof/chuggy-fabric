# The Track Record dashboard, read off the rendered `apps` layer: its uid and
# the sidecar's label, and every query against the series the server serves.
# What each assertion holds and why is in track-record-dashboard.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-track-record-dashboard" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./track-record-dashboard.py} ${cluster}/apps.yaml
  touch "$out"
''
