# The runner release step against a GitHub that is a server of the test's own.
# The cases are in runner-release.py's header.
{ pkgs }:

pkgs.runCommand "chuggy-runner-release" {
  nativeBuildInputs = [ pkgs.python3 pkgs.nodejs ];
} ''
  set -eu
  python3 ${./runner-release.py} ${pkgs.nodejs}/bin/node ${../cluster/build-system/runner-release.mjs}
  touch "$out"
''
