{ pkgs }:

pkgs.runCommand "chuggy-github-app-token" {
  nativeBuildInputs = [ pkgs.gnugrep ];
} ''
  set -eu
  root=${../.}
  module="$root/modules/github-app-token.nix"
  host="$root/hosts/gtr/default.nix"
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
  test "$(grep -R -c 'https://github.com/kasofsk/chuggy.git' "$root/cluster/apps" | awk -F: '{ total += $2 } END { print total + 0 }')" -eq 0
  test "$(grep -R -c 'chuggy-github-.*-token' "$root/cluster/apps" | awk -F: '{ total += $2 } END { print total + 0 }')" -eq 0
  test "$(grep -R -c 'git.chuggy-git.svc.cluster.local./chuggy.git' "$root/cluster/apps" | awk -F: '{ total += $2 } END { print total + 0 }')" -gt 0
  test "$(grep -R -c 'kind: CronJob' "$root/cluster/apps" | awk -F: '$1 ~ /sync/ { total += $2 } END { print total + 0 }')" -eq 0
  touch "$out"
''
