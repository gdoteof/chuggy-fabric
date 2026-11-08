# The three scripts of the worker admission, run against stand-ins for the API
# server and for GitHub; the cases are in worker-admit.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-worker-admit" {
  nativeBuildInputs = [ python pkgs.git pkgs.jq pkgs.gnused pkgs.coreutils pkgs.gnugrep pkgs.gawk pkgs.diffutils ];
} ''
  set -eu
  mkdir work
  export HOME="$PWD/work/home"
  python3 ${./worker-admit.py} ${../cluster/build-system} ${../cluster/chuggy/chuggy-scheduler.yaml} "$PWD/work"
  touch "$out"
''
