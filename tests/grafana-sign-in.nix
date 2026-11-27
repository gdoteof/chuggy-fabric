# Who Grafana lets in, read off the release in the rendered `apps` layer. The
# argument for each assertion is in grafana-sign-in.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-grafana-sign-in" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./grafana-sign-in.py} ${rendered}/apps.yaml
  touch "$out"
''
