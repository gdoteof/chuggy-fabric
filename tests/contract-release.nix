# The contract release step against a GitHub that is a server of the test's
# own. The cases are in contract-release.py's header.
{ pkgs }:

pkgs.runCommand "chuggy-contract-release" {
  nativeBuildInputs = [ pkgs.python3 pkgs.nodejs ];
} ''
  set -eu
  python3 ${./contract-release.py} ${pkgs.nodejs}/bin/node ${../cluster/build-system/contract-release.mjs}
  touch "$out"
''
