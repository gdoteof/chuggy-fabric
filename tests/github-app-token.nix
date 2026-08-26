{ pkgs }:

pkgs.runCommand "chuggy-github-app-token" {
  nativeBuildInputs = [ pkgs.gnugrep ];
} ''
  set -eu
  root=${../.}
  module="$root/modules/github-app-token.nix"
  host="$root/hosts/gtr/default.nix"
  repository='https://github.com/kasofsk/chuggy.git'

  grep -F 'options.chuggy.githubAppTokens' "$module" >/dev/null
  grep -F 'OnUnitActiveSec = "30m"' "$module" >/dev/null
  grep -F 'permissions:{contents:$permission}' "$module" >/dev/null
  grep -F 'chuggy-github-app-token' "$module" >/dev/null
  grep -F 'chuggy.dev/managed-by' "$module" >/dev/null
  test "$(grep -Fc 'kubectl apply' "$module" || true)" -eq 0
  grep -F 'appId = "4708055"' "$host" >/dev/null
  grep -F 'installationId = "156333284"' "$host" >/dev/null
  grep -F 'appId = "4728465"' "$host" >/dev/null
  grep -F 'installationId = "156786211"' "$host" >/dev/null
  grep -F 'repository = "chuggy"' "$host" >/dev/null
  grep -F 'secretName = "chuggy-github-reader-token"' "$host" >/dev/null
  grep -F 'secretName = "chuggy-github-finalizer-token"' "$host" >/dev/null
  grep -F 'secretName = "chuggy-github-worker-token"' "$host" >/dev/null
  for manifest in chuggy-api chuggy-configuration-importer chuggy-finalizer chuggy-scheduler chuggy-ticket-service; do
    grep -F "$repository" "$root/cluster/apps/$manifest.yaml" >/dev/null
  done
  test "$(grep -R -c 'git.chuggy-git.svc.cluster.local./chuggy.git' "$root/cluster/apps" | awk -F: '{ total += $2 } END { print total + 0 }')" -eq 0
  test "$(grep -Fc 'port: 443' "$root/cluster/apps/chuggy-control-plane-network-policy.yaml")" -ge 3
  test "$(grep -R -c 'kind: CronJob' "$root/cluster/apps" | awk -F: '$1 ~ /sync/ { total += $2 } END { print total + 0 }')" -eq 0
  touch "$out"
''
