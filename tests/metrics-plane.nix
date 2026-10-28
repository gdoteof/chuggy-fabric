# Whether the metrics plane reaches its database as the one role it is given,
# labels owners under the API's issuer, is scraped once and inside its own read
# bound, and admits Prometheus alone, read off the rendered manifests.
#
# The URL, the Secret key, the label, the egress arms, the issuer, the ingress
# source and the two timeouts are each written in a file that reads correctly
# alone. The argument for holding each is in metrics-plane.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-metrics-plane" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./metrics-plane.py} ${rendered}/cluster.yaml
  touch "$out"
''
