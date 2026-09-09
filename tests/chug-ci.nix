{ pkgs }:

pkgs.runCommand "chuggy-chug-ci" {
  nativeBuildInputs = [ pkgs.python3 pkgs.coreutils pkgs.gnugrep ];
} ''
  set -eu
  full=$PATH
  # Everything ci.sh itself calls, and no python3.
  unequipped=${pkgs.coreutils}/bin
  clean_line='clean: the manifests scripts/check-release-consistency names in cluster/apps identify one source; nix flake check did not run'

  # ci.sh locates what it runs from its own path, so a case is a whole tree.
  plant() {
    mkdir -p "$1/.chug/tasks" "$1/scripts" "$1/cluster"
    cp ${../.chug/tasks/ci.sh} "$1/.chug/tasks/ci.sh"
    cp ${../scripts/check-release-consistency} "$1/scripts/check-release-consistency"
    cp -R ${../cluster/apps} "$1/cluster/apps"
    chmod -R u+w "$1"
    set +u
    patchShebangs "$1/.chug/tasks/ci.sh"
    set -u
  }

  # The exit code is the verdict: 1 is a finding, 2 is a run that never
  # happened, and a gate reporting either as the other is believed.
  expect() {
    set +e
    ( PATH="''${4:-$full}"; export PATH; "$1/.chug/tasks/ci.sh" ) >"$1.out" 2>"$1.err"
    got=$?
    set -e
    if [ "$got" != "$2" ]; then
      echo "$3: expected exit $2, got $got" >&2
      cat "$1.out" "$1.err" >&2
      exit 1
    fi
  }

  # A verdict is read by its account as much as by its code: what the failing
  # command wrote is what the stage report carries, so an exit code with
  # nothing behind it is a red nobody can act on. A message naming no path is
  # the same failure one step in: it sends the reader to the wrong cause.
  says() {
    grep -Fq "$2" "$1" || { echo "$3" >&2; cat "$1" >&2; exit 1; }
  }

  # The stage report carries stdout beside stderr, so a clean line printed
  # unconditionally is an account saying the opposite of its own verdict.
  silent() {
    if grep -Fq "$clean_line" "$1"; then
      echo "$2" >&2
      cat "$1" >&2
      exit 1
    fi
  }

  plant clean
  expect clean 0 "the tree as committed"
  grep -Fxq "$clean_line" clean.out ||
    { echo "the clean line no longer reports what the run consumed" >&2; cat clean.out >&2; exit 1; }
  test ! -s clean.err ||
    { echo "a clean run wrote to stderr, which the stage report carries" >&2; cat clean.err >&2; exit 1; }

  # One refused tree is the whole of what this file does with a finding: it
  # runs the check over cluster/apps and hands back what the check said. The
  # defects that check refuses are held in tests/release-images.nix.
  plant refused
  sed -i '0,/sha256:/s/sha256:[0-9a-f]*/sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/' \
    refused/cluster/apps/chuggy-api.yaml
  expect refused 1 "mixed control-plane image digests"
  says refused.err 'control-plane manifests do not select one API image digest' \
    "exit 1 without the refusal that earned it"
  silent refused.out "the clean line beside a refused release"

  # The check exits 1 for a script it could not parse, which is the code a
  # refusal would have used had ci.sh read "not zero" instead of the reserved
  # one. A corrupted check is a run that never happened.
  plant broken-check
  printf 'def main(\n' >broken-check/scripts/check-release-consistency
  expect broken-check 2 "the check script unparseable"
  says broken-check.err 'broken-check/scripts/check-release-consistency exited' \
    "exit 2 without naming the script that could not run"
  silent broken-check.out "the clean line beside a check that never ran"

  # The other half of that contract: nothing but a refusal exits the reserved
  # code. A SyntaxError never reaches the running script, so a handler catching
  # into refuse() would report every runtime failure as a release inconsistency
  # with broken-check still green. Bytes that are not text raise where such a
  # handler would stand.
  plant undecodable-manifest
  printf '\377\376 not text\n' >undecodable-manifest/cluster/apps/chuggy-api.yaml
  expect undecodable-manifest 2 "a manifest the check cannot read as text"
  says undecodable-manifest.err 'undecodable-manifest/scripts/check-release-consistency exited' \
    "exit 2 without naming the script that could not run"
  silent undecodable-manifest.out "the clean line beside a check that never ran"

  plant unequipped-tree
  expect unequipped-tree 2 "python3 absent from PATH" "$unequipped"
  says unequipped-tree.err 'cannot run: python3 is not on PATH' \
    "exit 2 without naming the missing interpreter"
  silent unequipped-tree.out "the clean line beside a missing interpreter"

  plant missing-check
  rm missing-check/scripts/check-release-consistency
  expect missing-check 2 "the check script missing"
  says missing-check.err 'missing-check/scripts/check-release-consistency is missing' \
    "exit 2 without naming the missing script"
  silent missing-check.out "the clean line beside a missing check script"

  plant missing-manifests
  rm -r missing-manifests/cluster/apps
  expect missing-manifests 2 "the manifest directory missing"
  says missing-manifests.err 'missing-manifests/cluster/apps is not a directory' \
    "exit 2 without naming the missing manifest directory"
  silent missing-manifests.out "the clean line beside a missing manifest directory"

  touch "$out"
''
