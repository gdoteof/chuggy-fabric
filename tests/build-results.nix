# Every record this tree carries, held against the request it answers rather
# than against itself. The argument for each assertion is in build-results.py's
# own header; the verifier it drives is the one the retry and retirement
# commands drive, so what a release will select an image from and what this
# gate accepts cannot drift apart.
{ pkgs }:

pkgs.runCommand "chuggy-build-results" {
  nativeBuildInputs = [ pkgs.python3 pkgs.jq pkgs.coreutils pkgs.gawk pkgs.gnugrep ];
} ''
  set -eu
  root=${../.}
  cp -R "$root/scripts" scripts-under-test
  chmod -R u+w scripts-under-test
  set +u
  patchShebangs scripts-under-test
  set -u
  python3 ${./build-results.py} "$root" "$PWD/scripts-under-test"
  touch "$out"
''
