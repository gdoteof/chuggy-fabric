{ pkgs }:

pkgs.runCommand "chuggy-chug-ci" {
  nativeBuildInputs = [ pkgs.python3 pkgs.coreutils pkgs.gnugrep pkgs.gnused ];
} ''
  set -eu
  full=$PATH
  # Everything ci.sh itself calls, and no python3.
  unequipped=${pkgs.coreutils}/bin
  clean_line='clean: cluster/chuggy-migrate and cluster/chuggy name no release; nix flake check did not run'
  nothing=sha256:0000000000000000000000000000000000000000000000000000000000000000
  another=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

  # ci.sh locates what it reads from its own path, so a case is a whole tree.
  plant() {
    mkdir -p "$1/.chug/tasks" "$1/cluster"
    cp ${../.chug/tasks/ci.sh} "$1/.chug/tasks/ci.sh"
    cp -R ${../cluster/chuggy-migrate} "$1/cluster/chuggy-migrate"
    cp -R ${../cluster/chuggy} "$1/cluster/chuggy"
    chmod -R u+w "$1"
    set +u
    patchShebangs "$1/.chug/tasks/ci.sh"
    set -u
  }

  # An edit that changed nothing leaves the tree as committed, and the case
  # built on it would then be a second run of the clean one.
  edit() {
    cp "$1" "$1.before"
    sed -i "$2" "$1"
    if cmp -s "$1" "$1.before"; then
      echo "the edit '$2' changed nothing in $1" >&2
      exit 1
    fi
    rm "$1.before"
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

  # The tree as committed carries the annotation's key and a Job named for a
  # commit in its comments, so this is also the case that holds a comment is
  # not read.
  plant clean
  expect clean 0 "the tree as committed"
  grep -Fxq "$clean_line" clean.out ||
    { echo "the clean line no longer reports what the run consumed" >&2; cat clean.out >&2; exit 1; }
  test ! -s clean.err ||
    { echo "a clean run wrote to stderr, which the stage report carries" >&2; cat clean.err >&2; exit 1; }

  # A release written into git, one part at a time and each the way a hand
  # would write it. The account names the file and the line, and the line's
  # number is whatever the manifest's comments leave it at.
  refused() {
    expect "$1" 1 "$2"
    grep -Eq "^$3" "$1.err" ||
      { echo "exit 1 without the refusal that earned it" >&2; cat "$1.err" >&2; exit 1; }
    silent "$1.out" "the clean line beside $2"
  }

  plant digest
  edit digest/cluster/chuggy/chuggy-api.yaml "s|chuggy/api@$nothing|chuggy/api@$another|"
  refused digest "an image line at a digest" \
    'cluster/chuggy/chuggy-api\.yaml:[0-9]+ names registry\.chuggy\.internal/chuggy/api and not at the digest of nothing: image: '

  plant tag
  edit tag/cluster/chuggy/chuggy-ui.yaml "s|chuggy/web@$nothing|chuggy/web:482708e4|"
  refused tag "an image line at a tag" \
    'cluster/chuggy/chuggy-ui\.yaml:[0-9]+ names registry\.chuggy\.internal/chuggy/web and not at the digest of nothing: image: '

  plant name-alone
  edit name-alone/cluster/chuggy-migrate/chuggy-migrate.yaml "s|chuggy/api@$nothing|chuggy/api|"
  refused name-alone "an image line that is the name alone" \
    'cluster/chuggy-migrate/chuggy-migrate\.yaml:[0-9]+ names registry\.chuggy\.internal/chuggy/api and not at the digest of nothing: image: '

  # The directory's own kustomization is the other place a digest is written,
  # and the render of it is one this file cannot make.
  plant through-kustomization
  printf 'images:\n  - name: registry.chuggy.internal/chuggy/api\n    digest: %s\n' "$another" \
    >>through-kustomization/cluster/chuggy/kustomization.yaml
  refused through-kustomization "a digest written through the kustomization" \
    'cluster/chuggy/kustomization\.yaml:[0-9]+ names registry\.chuggy\.internal/chuggy/api and not at the digest of nothing: - name: '

  plant annotation
  edit annotation/cluster/chuggy/chuggy-selector.yaml \
    's|^  labels: { app: chuggy-selector }$|&\n  annotations:\n    fabric.chuggy.dev/source-commit: 482708e4|'
  refused annotation "a source commit on a Deployment" \
    'cluster/chuggy/chuggy-selector\.yaml:[0-9]+ carries fabric\.chuggy\.dev/source-commit: '

  # publish.sh writes the key as the path of a JSON patch, and a hand that
  # copies it into the directory's kustomization writes it the same way.
  plant annotation-patch
  printf 'patches:\n  - target: { kind: Deployment }\n    patch: |-\n      - op: add\n        path: /metadata/annotations/fabric.chuggy.dev~1source-commit\n        value: "482708e4"\n' \
    >>annotation-patch/cluster/chuggy/kustomization.yaml
  refused annotation-patch "a source commit patched in through the kustomization" \
    'cluster/chuggy/kustomization\.yaml:[0-9]+ carries fabric\.chuggy\.dev/source-commit: path: '

  plant job-name
  edit job-name/cluster/chuggy-migrate/chuggy-migrate.yaml \
    's|^  name: chuggy-migrate$|  name: chuggy-migrate-482708e4-registry|'
  refused job-name "a commit in the Job's name" \
    'cluster/chuggy-migrate/chuggy-migrate\.yaml names its Job `name: chuggy-migrate-482708e4-registry`'

  # A tree this cannot reach a verdict on. Each is one in which the reading
  # above would otherwise find nothing, and say clean.
  could_not_run() {
    expect "$1" 2 "$2" "''${4:-$full}"
    says "$1.err" "$3" "exit 2 without naming what could not be read"
    silent "$1.out" "the clean line beside $2"
  }

  plant unequipped-tree
  could_not_run unequipped-tree "python3 absent from PATH" \
    'cannot run: python3 is not on PATH' "$unequipped"

  plant missing-services
  rm -r missing-services/cluster/chuggy
  could_not_run missing-services "the services' directory missing" \
    'missing-services/cluster/chuggy is not a directory'

  plant missing-migration
  rm -r missing-migration/cluster/chuggy-migrate
  could_not_run missing-migration "the migration's directory missing" \
    'missing-migration/cluster/chuggy-migrate is not a directory'

  # Nothing but a finding exits the reserved code. Bytes that are not text
  # raise in the reading, which exits as a finding would have had this file
  # read "not zero" instead.
  plant undecodable-manifest
  printf '\377\376 not text\n' >undecodable-manifest/cluster/chuggy/chuggy-api.yaml
  could_not_run undecodable-manifest "a manifest that is not text" \
    'undecodable-manifest/cluster exited 1'

  plant no-console
  rm no-console/cluster/chuggy/chuggy-ui.yaml
  could_not_run no-console "no line naming the console's image" \
    'cannot run: nothing under cluster/chuggy-migrate or cluster/chuggy names registry.chuggy.internal/chuggy/web'

  plant no-job
  edit no-job/cluster/chuggy-migrate/chuggy-migrate.yaml 's|^kind: Job$|kind: CronJob|'
  could_not_run no-job "no document declaring a Job" \
    'cannot run: nothing under cluster/chuggy-migrate or cluster/chuggy declares a Job'

  plant nameless-job
  edit nameless-job/cluster/chuggy-migrate/chuggy-migrate.yaml '/^  name: chuggy-migrate$/d'
  could_not_run nameless-job "a Job whose name is not where this tree writes one" \
    'cannot run: cluster/chuggy-migrate/chuggy-migrate.yaml declares a Job whose name is not a line of its metadata'

  touch "$out"
''
