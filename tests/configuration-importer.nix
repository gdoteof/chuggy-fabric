{ pkgs }:

pkgs.runCommand "chuggy-configuration-importer" {
  nativeBuildInputs = [ pkgs.kubectl pkgs.gnugrep ];
} ''
  set -eu
  root=${../.}
  manifest="$root/cluster/apps/chuggy-configuration-importer.yaml"

  kubectl kustomize "$root/cluster/apps" > rendered.yaml
  grep -F 'name: chuggy-configuration-importer' rendered.yaml >/dev/null

  # One ref is resolved once per run and becomes the command's exact commit.
  grep -F 'git ls-remote --exit-code "$repository" refs/heads/main' "$manifest" >/dev/null
  grep -F 'commit: process.env.CHUG_CONFIGURATION_IMPORT_COMMIT' "$manifest" >/dev/null
  test "$(grep -c 'git ls-remote' "$manifest")" -eq 1

  # The pod has only reader Git material and its own database login.
  grep -F 'secretName: chuggy-git-sync' "$manifest" >/dev/null
  grep -F 'key: configuration-importer-password' "$manifest" >/dev/null
  grep -F 'role%3Dchuggy_configuration_importer' "$manifest" >/dev/null
  test "$(grep -c 'git-operator\|github-app' "$manifest" || true)" -eq 0
  test "$(grep -c 'HOME=' "$manifest" || true)" -eq 0
  grep -F 'GIT_CONFIG_GLOBAL=/dev/null' "$manifest" >/dev/null
  grep -F 'automountServiceAccountToken: false' "$manifest" >/dev/null

  # Overlap is refused and failed runs remain visible for inspection.
  grep -F 'concurrencyPolicy: Forbid' "$manifest" >/dev/null
  grep -F 'backoffLimit: 0' "$manifest" >/dev/null
  grep -F 'failedJobsHistoryLimit: 3' "$manifest" >/dev/null

  grep -F 'name: chuggy-configuration-importer-egress' \
    "$root/cluster/apps/chuggy-control-plane-network-policy.yaml" >/dev/null
  touch "$out"
''
