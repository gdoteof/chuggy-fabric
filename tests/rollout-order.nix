# The order a release rolls out in, read off the three rendered directories a
# release is spread over rather than off the layer declarations. The argument
# for each assertion is in rollout-order.py's own header.
#
# The owner of the dumps directory is handed over from the host rather than
# restated here, so that the uid this holds the dump to is the one the tmpfiles
# rule is built from.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-rollout-order" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./rollout-order.py} ${rendered} \
    ${toString host.config.chuggy.state.dumps.user}
  touch "$out"
''
