# The prepare step of the contract Task and the gh it gives the publish
# script, against fakes of git, npm and the script. The cases are in
# contract-prepare.py's header.
{ pkgs }:

pkgs.runCommand "chuggy-contract-prepare" {
  nativeBuildInputs = [ pkgs.python3 pkgs.nodejs ];
} ''
  set -eu
  python3 ${./contract-prepare.py} ${pkgs.nodejs}/bin/node ${../cluster/build-system}
  touch "$out"
''
