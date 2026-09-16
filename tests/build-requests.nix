# The command that answers a source's build requests, driven over this
# repository's own builds and results. What each case is and why it is that case
# is in build-requests.py's header.
#
# It runs against a copy of `scripts/` rather than the store paths because the
# command resolves its siblings -- the declaration it reads, the renderer it
# renders through, the verifier the results gate reaches for -- beside itself,
# and a suite that pointed at anything else would be proving a different
# arrangement than the one the host runs.
{ pkgs }:

pkgs.runCommand "chuggy-build-requests" {
  nativeBuildInputs = [
    pkgs.python3
    pkgs.bash
    pkgs.coreutils
    pkgs.gawk
    pkgs.gnugrep
    pkgs.jq
  ];
} ''
  set -eu
  root=${../.}
  cp -R "$root/scripts" scripts-under-test
  chmod -R u+w scripts-under-test
  set +u
  patchShebangs scripts-under-test
  set -u
  mkdir work
  python3 ${./build-requests.py} "$root" "$PWD/scripts-under-test" "$PWD/work"
  touch "$out"
''
