# Every record this tree carries, held against the request it answers rather
# than against itself. The argument for each assertion is in build-results.py's
# own header; the verifier it drives is the one the retry and retirement
# commands drive, so what a promotion will accept and what this gate accepts
# cannot drift apart.
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
  # The README names the timer a reader would go looking for, and a unit named
  # in prose and nowhere else is the way that sentence goes stale.
  grep -F 'chuggy-build-results-publish.timer' "$root/README.md" >/dev/null
  grep -F 'systemd.timers.chuggy-build-results-publish' "$root/modules/build-provenance.nix" >/dev/null
  touch "$out"
''
