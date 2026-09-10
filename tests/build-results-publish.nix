# The publisher against a real repository. What each case is for is in
# build-results-publish.sh's own header.
{ pkgs }:

pkgs.runCommand "chuggy-build-results-publish" {
  nativeBuildInputs = [
    pkgs.coreutils
    pkgs.diffutils
    pkgs.gawk
    pkgs.git
    pkgs.gnugrep
    pkgs.jq
    pkgs.python3
  ];
} ''
  set -eu
  root=${../.}
  cp -R "$root/scripts" scripts-under-test
  chmod -R u+w scripts-under-test
  set +u
  patchShebangs scripts-under-test
  set -u
  bash ${./build-results-publish.sh} "$root" "$PWD/scripts-under-test"
  touch "$out"
''
