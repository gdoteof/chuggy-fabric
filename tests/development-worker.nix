{ pkgs }:

pkgs.runCommand "chuggy-development-worker" {
  nativeBuildInputs = [ pkgs.gnugrep pkgs.kubectl ];
} ''
  set -eu
  root=${../.}
  scheduler="$root/cluster/apps/chuggy-scheduler.yaml"
  network="$root/cluster/apps/chuggy-work.yaml"

  kubectl kustomize "$root/cluster/apps" > rendered.yaml
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:de1409a2a51b82bc18f6517bc62603956ad5698b26e36ed64b7f84c793e62cae' "$scheduler" >/dev/null
  grep -F '"secretName": "chuggy-git-worker"' "$scheduler" >/dev/null
  grep -F '"secretName": "claude-code"' "$scheduler" >/dev/null
  grep -F '"CHUG_WORKER_WORKSPACE": "/workspace"' "$scheduler" >/dev/null
  grep -F '"mayCompleteTask": false' "$scheduler" >/dev/null
  grep -F 'kubernetes.io/metadata.name: chuggy-git' "$network" >/dev/null
  grep -F '{ protocol: TCP, port: 443 }' "$network" >/dev/null
  touch "$out"
''
