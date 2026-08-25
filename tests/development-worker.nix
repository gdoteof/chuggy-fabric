{ pkgs }:

pkgs.runCommand "chuggy-development-worker" {
  nativeBuildInputs = [ pkgs.gnugrep pkgs.kubectl ];
} ''
  set -eu
  root=${../.}
  scheduler="$root/cluster/apps/chuggy-scheduler.yaml"
  network="$root/cluster/apps/chuggy-work.yaml"

  kubectl kustomize "$root/cluster/apps" > rendered.yaml
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:cfe57dd168347730f91aec689be4adaf53750f237af54bb9effedf53319d34a6' "$scheduler" >/dev/null
  grep -F '"secretName": "chuggy-git-worker"' "$scheduler" >/dev/null
  grep -F '"secretName": "claude-code"' "$scheduler" >/dev/null
  grep -F '"CHUG_WORKER_WORKSPACE": "/workspace"' "$scheduler" >/dev/null
  grep -F '"ephemeralStorageLimit": "20Gi"' "$scheduler" >/dev/null
  grep -F '"fsGroup":1000' "$scheduler" >/dev/null
  grep -F '"mayCompleteTask": false' "$scheduler" >/dev/null
  grep -F 'kubernetes.io/metadata.name: chuggy-git' "$network" >/dev/null
  grep -F '{ protocol: TCP, port: 443 }' "$network" >/dev/null
  touch "$out"
''
