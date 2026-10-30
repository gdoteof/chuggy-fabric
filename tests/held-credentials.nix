# The credentials the worker plane holds as files: its roster as chuggy reads
# it, each file against the Secret its pod puts there, and which Secret is
# served under which name to which project. The argument for each assertion is
# in held-credentials.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-held-credentials" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./held-credentials.py} ${rendered}/cluster.yaml
  touch "$out"
''
