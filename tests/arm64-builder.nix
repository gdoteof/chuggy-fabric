# cluster/build-system/arm64-builder.sh, run as an operator runs it, against
# the run and the Task that speak to the daemon it starts. What is the tree's
# and what is this suite's, and what each case holds, are in
# arm64-builder.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-build-system.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-arm64-builder" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  mkdir work
  python3 ${./arm64-builder.py} ${../cluster/build-system/arm64-builder.sh} ${rendered} \
    ${../cluster/build-system/worker-image-run.yaml} ${pkgs.busybox}/bin ${pkgs.openssl.bin}/bin "$PWD/work"
  touch "$out"
''
