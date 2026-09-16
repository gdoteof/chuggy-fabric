# The commands that file a source's build requests and answer them, driven over
# this repository's own builds and results. What each case is and why it is that
# case is in build-requests.py's header.
#
# They run against a copy of `scripts/` rather than the store paths because each
# resolves its siblings -- the declaration they read, the renderer they render
# through, the verifier the results gate reaches for -- beside itself, and a
# suite that pointed at anything else would be proving a different arrangement
# than the one the host runs.
{ pkgs }:

pkgs.runCommand "chuggy-build-requests" {
  nativeBuildInputs = [
    pkgs.python3
    pkgs.bash
    pkgs.coreutils
    pkgs.gawk
    pkgs.git
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
  # The runbook is where an operator goes for the commands of this loop, and one
  # named nowhere in it is one nobody finds when a ticket's build has not
  # arrived.
  grep -F 'scripts/request-build' "$root/docs/build-operations-runbook.md" >/dev/null
  grep -F 'scripts/await-build-results' "$root/docs/build-operations-runbook.md" >/dev/null
  touch "$out"
''
