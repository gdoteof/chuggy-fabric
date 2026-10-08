# Whether the access plane verifies a token as the API does, read off the
# rendered manifests.
#
# The issuer, the audience and the algorithms are each written in two manifests
# and each reads correctly alone. The argument for holding them equal is in
# access-plane.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-access-plane" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./access-plane.py} ${rendered}/cluster.yaml
  touch "$out"
''
