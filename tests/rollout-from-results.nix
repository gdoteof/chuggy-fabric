# The one command a rollout ticket runs, driven against a real remote and this
# repository's own release. What each case is and why it is that case is in
# rollout-from-results.py's header.
#
# It runs against a copy of `scripts/` rather than the store paths because the
# command resolves the two it wraps beside itself, and a suite that pointed at
# anything else would be proving a different arrangement than the one a worker
# runs.
{ pkgs }:

pkgs.runCommand "chuggy-rollout-from-results" {
  nativeBuildInputs = [
    pkgs.python3
    pkgs.git
    pkgs.jq
    pkgs.bash
    pkgs.coreutils
    pkgs.gawk
    pkgs.gnugrep
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
  export HOME=$PWD/work
  python3 ${./rollout-from-results.py} "$root" "$PWD/scripts-under-test" "$PWD/work"
  # The runbook is where an operator goes for the commands of this loop, and one
  # named nowhere in it is one nobody finds when a rollout has not arrived.
  grep -F 'scripts/rollout-from-results' "$root/docs/build-operations-runbook.md" >/dev/null
  touch "$out"
''
