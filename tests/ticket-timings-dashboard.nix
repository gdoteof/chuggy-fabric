# The ticket timings dashboard, read off the rendered `apps` layer: its uid and
# the sidecar's label, every query against the families the metrics plane
# serves, and each distribution's bars against its family's buckets; and its
# manifest, held to what dashboards/ticket_timings.py writes. What each
# assertion holds and why is in ticket-timings-dashboard.py's header and
# dashboard.py's.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
  checks = pkgs.lib.fileset.toSource { root = ./.; fileset = ./dashboard.py; };
in
pkgs.runCommand "chuggy-ticket-timings-dashboard" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  PYTHONPATH=${../dashboards}:${checks} python3 ${./ticket-timings-dashboard.py} \
    ${cluster}/apps.yaml ${../cluster/apps/ticket-timings-dashboard.yaml}
  touch "$out"
''
