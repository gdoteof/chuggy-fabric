# Whether the access plane verifies a token as the API does, reaches its
# database as the one role it is given, and admits to its port the edge and
# Kratos alone, read off the rendered manifests.
#
# The issuer, the audience and the algorithms are each written in two manifests
# and each reads correctly alone, and so do the URL, the Secret key, the label
# and the egress arm its connection is made of, and the sources its ingress
# policy names. The argument for holding each is in access-plane.py's own
# header.
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
