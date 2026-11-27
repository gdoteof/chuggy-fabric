# Whether the agreement plane verifies a token as the API does, reaches its
# database as the one role it is given, admits Traefik alone and reaches its
# three arms alone, is what the console's host sends its prefix to, and names
# the header an agreement's address is taken from, read off the rendered
# manifests.
#
# The issuer, the audience and the algorithms are each written in two
# manifests, and so are the plane's Service's name and port: where it is
# declared and in the Ingress arm that names it. Each reads correctly alone, as
# do the URL, the Secret key, the label and the arms its connection is made
# of. The argument for holding each is in agreement-plane.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-agreement-plane" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./agreement-plane.py} ${rendered}/cluster.yaml
  touch "$out"
''
