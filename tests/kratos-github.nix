# What signing in with GitHub may do on this rig, read out of the config
# document Kratos mounts and the environment its container is given. The
# argument for each assertion is in kratos-github.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-kratos-github" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./kratos-github.py} ${rendered}/cluster.yaml
  touch "$out"
''
