# The bounded wait a rollout ticket runs, driven against a real remote. What
# each case is and why it is that case is in await-build-results.py's header.
#
# It runs against a copy of `scripts/` rather than the store paths because the
# suite imports the command for the bound it states, and a suite that pointed at
# anything else would be proving a different arrangement than the one a worker
# runs.
{ pkgs }:

pkgs.runCommand "chuggy-await-build-results" {
  nativeBuildInputs = [ pkgs.python3 pkgs.git pkgs.coreutils ];
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
  python3 ${./await-build-results.py} "$root" "$PWD/scripts-under-test" "$PWD/work"
  touch "$out"
''
