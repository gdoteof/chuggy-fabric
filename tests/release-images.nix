{ pkgs }:

pkgs.runCommand "chuggy-release-images" {
  nativeBuildInputs = [ pkgs.python3 ];
} ''
  set -eu
  cp -R ${../cluster/apps} manifests
  chmod -R u+w manifests
  check=${../scripts/check-release-consistency}

  # A refusal exits the script's own REFUSAL code and nothing else does, which
  # is what lets `.chug/tasks/ci.sh` tell a refused release from a script it
  # could not run. The code is as much of the contract as the message.
  refused() {
    set +e
    python3 "$check" "$1" 2>"$1-error"
    got=$?
    set -e
    if [ "$got" != 3 ]; then
      echo "$1: expected the refusal exit 3, got $got" >&2
      cat "$1-error" >&2
      exit 1
    fi
    grep -F "$2" "$1-error"
  }

  python3 "$check" manifests
  test "$(grep -Fc 'credentialReference:' manifests/chuggy-ticket-service.yaml || true)" -eq 0

  set +e
  python3 "$check" 2>usage-error
  got=$?
  set -e
  if [ "$got" != 3 ]; then
    echo "no manifest directory: expected the refusal exit 3, got $got" >&2
    cat usage-error >&2
    exit 1
  fi
  grep -F 'usage: check-release-consistency APP_MANIFEST_DIRECTORY' usage-error

  # Retiring or renaming a component is how a manifest the check names stops
  # being in the directory, and the check has to say so rather than raise: a
  # traceback reaches the caller as a script it could not run.
  cp -R manifests retired-component
  rm retired-component/chuggy-selector.yaml
  refused retired-component 'the release does not carry retired-component/chuggy-selector.yaml'

  # Every value the check compares is read through one_match, which refuses a
  # manifest naming its image or its commit twice rather than taking the first.
  cp -R manifests duplicate-image
  duplicate=$(grep -E '^[ \t]*image: registry\.chuggy\.internal/chuggy/api@sha256:' \
    duplicate-image/chuggy-api.yaml)
  printf '%s\n' "$duplicate" >>duplicate-image/chuggy-api.yaml
  refused duplicate-image 'chuggy-api.yaml image: expected one match, found 2'

  cp -R manifests mixed-digest
  sed -i '0,/sha256:/s/sha256:[0-9a-f]*/sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/' \
    mixed-digest/chuggy-api.yaml
  refused mixed-digest 'control-plane manifests do not select one API image digest'

  cp -R manifests mixed-source
  sed -i '0,/source-commit:/s/source-commit: .*/source-commit: abcdef0/' \
    mixed-source/chuggy-web.yaml
  refused mixed-source 'release manifests do not identify one source commit'

  cp -R manifests mixed-console-source
  sed -i '0,/source-commit:/s/source-commit: .*/source-commit: abcdef0/' \
    mixed-console-source/chuggy-ui.yaml
  refused mixed-console-source 'release manifests do not identify one source commit'

  cp -R manifests shared-console-digest
  shared=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  for console in chuggy-web chuggy-ui; do
    sed -i "0,/chuggy\/web@sha256:/s|chuggy/web@sha256:[0-9a-f]*|chuggy/web@$shared|" \
      "shared-console-digest/$console.yaml"
  done
  refused shared-console-digest \
    'console manifests select one web image digest for both consoles'

  cp -R manifests stale-migration
  sed -i '0,/name: chuggy-migrate-/s/name: chuggy-migrate-[a-z0-9-]*/name: chuggy-migrate-abcdef0-registry/' \
    stale-migration/chuggy-migrate.yaml
  refused stale-migration \
    'migration Job identity does not match the release source commit'

  touch "$out"
''
