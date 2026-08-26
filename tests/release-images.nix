{ pkgs }:

pkgs.runCommand "chuggy-release-images" {
  nativeBuildInputs = [ pkgs.python3 ];
} ''
  set -eu
  cp -R ${../cluster/apps} manifests
  chmod -R u+w manifests
  check=${../scripts/check-release-consistency}
  run_check() {
    python3 "$check" "$1"
  }

  run_check manifests
  test "$(grep -Fc 'credentialReference:' manifests/chuggy-ticket-service.yaml || true)" -eq 0

  cp -R manifests mixed-digest
  sed -i '0,/sha256:/s/sha256:[0-9a-f]*/sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/' \
    mixed-digest/chuggy-api.yaml
  if run_check mixed-digest 2>mixed-digest-error; then
    echo "accepted mixed control-plane image digests" >&2
    exit 1
  fi
  grep -F 'control-plane manifests do not select one API image digest' mixed-digest-error

  cp -R manifests mixed-source
  sed -i '0,/source-commit:/s/source-commit: .*/source-commit: abcdef0/' \
    mixed-source/chuggy-web.yaml
  if run_check mixed-source 2>mixed-source-error; then
    echo "accepted mixed release source commits" >&2
    exit 1
  fi
  grep -F 'release manifests do not identify one source commit' mixed-source-error

  cp -R manifests mixed-console-source
  sed -i '0,/source-commit:/s/source-commit: .*/source-commit: abcdef0/' \
    mixed-console-source/chuggy-ui.yaml
  if run_check mixed-console-source 2>mixed-console-source-error; then
    echo "accepted a second console at another source commit" >&2
    exit 1
  fi
  grep -F 'release manifests do not identify one source commit' mixed-console-source-error

  cp -R manifests shared-console-digest
  shared=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  for console in chuggy-web chuggy-ui; do
    sed -i "0,/chuggy\/web@sha256:/s|chuggy/web@sha256:[0-9a-f]*|chuggy/web@$shared|" \
      "shared-console-digest/$console.yaml"
  done
  if run_check shared-console-digest 2>shared-console-digest-error; then
    echo "accepted one web image digest serving both consoles" >&2
    exit 1
  fi
  grep -F 'console manifests select one web image digest for both consoles' \
    shared-console-digest-error

  cp -R manifests stale-migration
  sed -i '0,/name: chuggy-migrate-/s/name: chuggy-migrate-[a-z0-9-]*/name: chuggy-migrate-abcdef0-registry/' \
    stale-migration/chuggy-migrate.yaml
  if run_check stale-migration 2>stale-migration-error; then
    echo "accepted a stale migration Job identity" >&2
    exit 1
  fi
  grep -F 'migration Job identity does not match the release source commit' stale-migration-error

  touch "$out"
''
