# The site admission's read and prepare steps, run against a stand-in for the
# API server and over this tree's Deployment; the cases are in
# chug-gy-admit.py's header.
{ pkgs }:

pkgs.runCommand "chuggy-chug-gy-admit" {
  nativeBuildInputs = [ pkgs.python3 pkgs.git pkgs.jq pkgs.gnused pkgs.coreutils pkgs.gnugrep pkgs.gawk ];
} ''
  set -eu
  mkdir work
  export HOME="$PWD/work/home"
  python3 ${./chug-gy-admit.py} ${../cluster/build-system} ${../cluster/chug-gy/chug-gy.yaml} "$PWD/work"
  touch "$out"
''
