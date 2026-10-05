# Where the selector is configured to go and where it is permitted to go, held
# against each other over the rendered manifests.
#
# The property this holds is one the file cannot: the selector's destinations
# are written twice, as URLs in a JSON string and as peers on a NetworkPolicy,
# and both halves read correctly alone while a connection is dropped. The
# retired policy host is the worked example -- a URL to a name no Service
# resolved, on a port no arm permitted, which stood in the manifest for as long
# as the replica count under it was zero. Raising that count is what makes the
# disagreement a running process reaching for something, so the gate lands with
# the raise.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-selector-reach" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./selector-reach.py} ${rendered}/cluster.yaml
  touch "$out"
''
