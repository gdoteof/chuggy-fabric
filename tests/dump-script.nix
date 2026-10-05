# The dump the migration Job takes, run as its pod is given it against a
# PostgreSQL started inside the build. What is the render's and what is this
# suite's, and the half of the script each case is the only reader of, are in
# dump-script.py's header.
#
# `postgresql_17` because it is the newest major this nixpkgs pins, and the
# server the pod dumps is a later one: that header says what follows from it.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-dump-script" {
  nativeBuildInputs = [ python pkgs.postgresql_17 pkgs.bash pkgs.coreutils ];
} ''
  set -eu
  mkdir work
  python3 ${./dump-script.py} ${rendered}/chuggy-migrate.yaml "$PWD/work" ||
    { cat work/*.log >&2 || true; exit 1; }
  touch "$out"
''
