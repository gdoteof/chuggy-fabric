# The tickets dashboard, read off the rendered `apps` layer: its uid and the
# sidecar's label, and every query against the families the metrics plane
# serves; and its manifest, held to what dashboards/tickets.py writes. What each
# assertion holds and why is in tickets-dashboard.py's header and dashboard.py's.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
  checks = pkgs.lib.fileset.toSource { root = ./.; fileset = ./dashboard.py; };
in
pkgs.runCommand "chuggy-tickets-dashboard" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  PYTHONPATH=${../dashboards}:${checks} python3 ${./tickets-dashboard.py} \
    ${cluster}/apps.yaml ${../cluster/apps/tickets-dashboard.yaml}
  touch "$out"
''
