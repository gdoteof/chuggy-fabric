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
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:de1409a2a51b82bc18f6517bc62603956ad5698b26e36ed64b7f84c793e62cae' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:cfe57dd168347730f91aec689be4adaf53750f237af54bb9effedf53319d34a6' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:49cc3c3d713e4b40341f68dfb83e1bf1acabb6d5986e1f1786ea5706afe0690f' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:beb6ed311a398723fc33c47269077a3c55fcac51627f65db5d82932f6183fc38' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:c50b3333142063e90c6d7d6143119bcf1dd9b138e8aa740b831dc48699896e1f' "$scheduler" >/dev/null
  grep -F 'CHUG_SCHEDULER_WORKER_DEADLINE_SECS' "$scheduler" >/dev/null
  grep -F '"attemptLeaseSecs":300' "$scheduler" >/dev/null
  grep -F 'CHUG_WORKER_PLANE_HEARTBEAT_LEASE_SECS' "$worker_plane" >/dev/null
  grep -F '"secretName": "chuggy-github-worker-token"' "$scheduler" >/dev/null
  grep -F '"secretName": "claude-code"' "$scheduler" >/dev/null
  grep -F '"CHUG_WORKER_WORKSPACE": "/workspace"' "$scheduler" >/dev/null
  grep -F '"ephemeralStorageLimit": "20Gi"' "$scheduler" >/dev/null
  grep -F '"fsGroup":1000' "$scheduler" >/dev/null
  grep -F '"mayCompleteTask": false' "$scheduler" >/dev/null
  grep -F 'https://github.com/kasofsk/chuggy.git' "$scheduler" >/dev/null
  test "$(grep -Fc 'kubernetes.io/metadata.name: chuggy-git' "$network" || true)" -eq 0
  grep -F '{ protocol: TCP, port: 443 }' "$network" >/dev/null
  touch "$out"
''
