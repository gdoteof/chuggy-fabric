{ pkgs }:

pkgs.runCommand "chuggy-configuration-importer" {
  nativeBuildInputs = [ pkgs.kubectl pkgs.gnugrep ];
} ''
  set -eu
  root=${../.}
  manifest="$root/cluster/apps/chuggy-configuration-importer.yaml"

  kubectl kustomize "$root/cluster/apps" > rendered.yaml
  grep -F 'name: chuggy-configuration-importer' rendered.yaml >/dev/null

  # The preflight waits for reachability, then one resolution becomes the
  # command's exact commit. The preflight never supplies an import identity.
  grep -F 'git ls-remote --exit-code "$repository" refs/heads/main' "$manifest" >/dev/null
  grep -F 'commit: process.env.CHUG_CONFIGURATION_IMPORT_COMMIT' "$manifest" >/dev/null
  test "$(grep -Fc 'commit="$(git ls-remote' "$manifest")" -eq 1

  # The pod has only reader Git material and its own database login.
  grep -F 'secretName: chuggy-git-sync' "$manifest" >/dev/null
  grep -F 'key: configuration-importer-password' "$manifest" >/dev/null
  grep -F 'postgres://chuggy_configuration_importer_login:$(CHUG_CONFIGURATION_IMPORTER_PASSWORD)' "$manifest" >/dev/null
  test "$(grep -c 'role%3Dchuggy_configuration_importer' "$manifest" || true)" -eq 0
  test "$(grep -c 'git-operator\|github-app' "$manifest" || true)" -eq 0
  test "$(grep -c 'HOME=' "$manifest" || true)" -eq 0
  grep -F 'GIT_CONFIG_GLOBAL=/dev/null' "$manifest" >/dev/null
  grep -F 'automountServiceAccountToken: false' "$manifest" >/dev/null
  grep -F 'name: wait-for-postgres' "$manifest" >/dev/null
  grep -F 'pg_isready -h postgres.chuggy.svc.cluster.local -U chuggy_configuration_importer_login -t 2' "$manifest" >/dev/null
  test "$(grep -Fc 'for i in $(seq 1 15)' "$manifest")" -eq 2
  grep -F 'timeout 3s git ls-remote --exit-code "$repository" refs/heads/main >/dev/null 2>&1 && break' "$manifest" >/dev/null
  grep -F 'activeDeadlineSeconds: 420' "$manifest" >/dev/null
  postgres_wait=$((15 * (2 + 2)))
  repository_wait=$((15 * (3 + 2)))
  import_remote_timeout=120
  outer_deadline=420
  test "$outer_deadline" -gt "$((postgres_wait + repository_wait + import_remote_timeout))"

  # Overlap is refused and failed runs remain visible for inspection.
  grep -F 'concurrencyPolicy: Forbid' "$manifest" >/dev/null
  grep -F 'backoffLimit: 0' "$manifest" >/dev/null
  grep -F 'failedJobsHistoryLimit: 3' "$manifest" >/dev/null

  grep -F 'name: chuggy-configuration-importer-egress' \
    "$root/cluster/apps/chuggy-control-plane-network-policy.yaml" >/dev/null
  grep -F 'test "$(git rev-parse --short=7 HEAD)" = e92cce9' "$root/README.md" >/dev/null
  grep -F 'CHUG_PG_CONFIGURATION_IMPORTER_PASSWORD' "$root/README.md" >/dev/null
  grep -F 'systemctl is-active chuggy-secrets-sync' "$root/README.md" >/dev/null
  touch "$out"
''
