# The fetch and prepare steps of the runner release Task, against a real git
# history and a fake of npm. The cases are in runner-prepare.py's header.
{ pkgs }:

pkgs.runCommand "chuggy-runner-prepare" {
  nativeBuildInputs = [ pkgs.python3 pkgs.nodejs pkgs.git ];
} ''
  set -eu
  python3 ${./runner-prepare.py} ${../cluster/build-system}
  touch "$out"
''
