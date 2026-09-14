# The release `scripts/render-release` writes, driven over this repository's own
# manifests. What each case is and why it is that case is in render-release.py's
# header; the script under test states the rules, and this is what holds it to
# them.
#
# It runs against a copy of `scripts/` rather than the store paths because the
# script resolves its siblings -- the consistency check whose manifest roster it
# reads, the provenance module, the verifier that module calls -- beside itself,
# and a suite that pointed at anything else would be proving a different
# arrangement than the one a worker runs.
{ pkgs }:

pkgs.runCommand "chuggy-render-release" {
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
  python3 ${./render-release.py} "$root" "$PWD/scripts-under-test" "$PWD/work"
  touch "$out"
''
