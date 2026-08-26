{ pkgs }:

pkgs.runCommand "chuggy-development-worker" {
  nativeBuildInputs = [ pkgs.gnugrep pkgs.kubectl ];
} ''
  set -eu
  root=${../.}
  scheduler="$root/cluster/apps/chuggy-scheduler.yaml"
  worker_plane="$root/cluster/apps/chuggy-worker-plane.yaml"
  network="$root/cluster/apps/chuggy-work.yaml"

  kubectl kustomize "$root/cluster/apps" > rendered.yaml
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:c50b3333142063e90c6d7d6143119bcf1dd9b138e8aa740b831dc48699896e1f' "$scheduler" >/dev/null
  grep -F 'CHUG_SCHEDULER_WORKER_DEADLINE_SECS' "$scheduler" >/dev/null
  grep -F '"attemptLeaseSecs":300' "$scheduler" >/dev/null
  grep -F 'CHUG_WORKER_PLANE_HEARTBEAT_LEASE_SECS' "$worker_plane" >/dev/null
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
