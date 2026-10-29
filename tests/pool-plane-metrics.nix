# Whether the pool plane's runners' reports are served on their own port to
# Prometheus alone, out of every public route's reach, and scraped by one
# monitor more often than a runner reports, read off the rendered manifests.
#
# The listener, the two Services, the routes, the ingress policy and the
# monitor are each written in a file that reads correctly alone. The argument
# for holding each is in pool-plane-metrics.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-pool-plane-metrics" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./pool-plane-metrics.py} ${rendered}/cluster.yaml
  touch "$out"
''
