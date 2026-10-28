# The usage dashboard, read off the rendered `apps` layer: its uid and the
# sidecar's label, and every query against the families the metrics plane
# serves. What each assertion holds and why is in usage-dashboard.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-usage-dashboard" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./usage-dashboard.py} ${cluster}/apps.yaml
  touch "$out"
''
