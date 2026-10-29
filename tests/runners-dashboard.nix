# The runners dashboard, read off the rendered `apps` layer: its uid and the
# sidecar's label, and every query against the families the pool plane serves
# of a runner; and its manifest, held to what dashboards/runners.py writes.
# What each assertion holds and why is in runners-dashboard.py's header and
# dashboard.py's.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
  checks = pkgs.lib.fileset.toSource { root = ./.; fileset = ./dashboard.py; };
in
pkgs.runCommand "chuggy-runners-dashboard" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  PYTHONPATH=${../dashboards}:${checks} python3 ${./runners-dashboard.py} \
    ${cluster}/apps.yaml ${../cluster/apps/runners-dashboard.yaml}
  touch "$out"
''
