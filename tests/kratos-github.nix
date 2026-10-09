# What signing in with GitHub may do on this rig, and who a registration makes
# an identity for, read out of the config document Kratos mounts, the files
# mounted beside it and the environment its container is given. The argument
# for each assertion is in kratos-github.py's own header.
#
# The mapper and the two hook bodies are Jsonnet, and the check evaluates
# them. `go-jsonnet` is the implementation Kratos embeds and not necessarily
# its release: flake.lock decides the one here and Kratos's `go.mod` the one
# in the image ory-kratos.yaml pins.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-kratos-github" {
  nativeBuildInputs = [ python pkgs.go-jsonnet ];
} ''
  set -eu
  python3 ${./kratos-github.py} ${rendered}/cluster.yaml
  touch "$out"
''
