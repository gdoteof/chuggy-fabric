{ pkgs }:

pkgs.runCommand "chuggy-development-worker" {
  nativeBuildInputs = [ pkgs.gnugrep pkgs.kubectl ];
} ''
  set -eu
  root=${../.}
  scheduler="$root/cluster/apps/chuggy-scheduler.yaml"
  worker_plane="$root/cluster/apps/chuggy-worker-plane.yaml"
  network="$root/cluster/apps/chuggy-work.yaml"
  policy="$root/cluster/apps/postgres-network-policy.yaml"

  kubectl kustomize "$root/cluster/apps" > rendered.yaml
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:de1409a2a51b82bc18f6517bc62603956ad5698b26e36ed64b7f84c793e62cae' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:cfe57dd168347730f91aec689be4adaf53750f237af54bb9effedf53319d34a6' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:49cc3c3d713e4b40341f68dfb83e1bf1acabb6d5986e1f1786ea5706afe0690f' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:beb6ed311a398723fc33c47269077a3c55fcac51627f65db5d82932f6183fc38' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:c50b3333142063e90c6d7d6143119bcf1dd9b138e8aa740b831dc48699896e1f' "$scheduler" >/dev/null
  grep -F 'CHUG_SCHEDULER_WORKER_DEADLINE_SECS' "$scheduler" >/dev/null
  grep -F '"attemptLeaseSecs":300' "$scheduler" >/dev/null
  grep -F 'CHUG_WORKER_PLANE_HEARTBEAT_LEASE_SECS' "$worker_plane" >/dev/null
  grep -F '"secretName": "chuggy-git-worker"' "$scheduler" >/dev/null
  grep -F '"secretName": "chuggy-github-worker-token"' "$scheduler" >/dev/null
  grep -F '\"credential\":\"chuggy-github-worker\"' "$scheduler" >/dev/null
  grep -F '\"credentialUsername\":\"x-access-token\"' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:9949c44297be92b3a49d11c3982b897730e4e283031f1b8b21b285e0ca04dbbe' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:fe7018f6ea36630cdbe71f7aba03f93f8f73a14c0ac1405411d6d034aa07a8ef' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:e2aac0fc9347a936dc6b279385f0100e005c4e219227ed4c619f2b61e3e89261' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:06a094c632eb2d6715ab35f3d1cd11c7fdd1ba7e95c04652f5cc259db00e994e' "$scheduler" >/dev/null
  grep -F '"credentials": ["chuggy-git-worker", "chuggy-github-worker", "claude-code"]' "$scheduler" >/dev/null
  grep -F '"secretName": "claude-code"' "$scheduler" >/dev/null
  grep -F '"CHUG_WORKER_WORKSPACE": "/workspace"' "$scheduler" >/dev/null
  grep -F '"ephemeralStorageLimit": "20Gi"' "$scheduler" >/dev/null
  grep -F '"fsGroup":1000' "$scheduler" >/dev/null
  grep -F '"mayCompleteTask": false' "$scheduler" >/dev/null
  grep -F 'kubernetes.io/metadata.name: chuggy-git' "$network" >/dev/null
  grep -F '{ protocol: TCP, port: 443 }' "$network" >/dev/null

  # The shared database an attempt scopes itself on: the Secret the scheduler
  # names, the label both halves of the path key on, the egress that admits the
  # server and the ingress that admits this namespace. Each is half of a reach
  # that fails closed without the other, and a worker that cannot reach
  # PostgreSQL fails every gate that needs one rather than skipping it.
  grep -F '{"secretName":"chuggy-worker-database","key":"url"}' "$scheduler" >/dev/null
  grep -F '"chuggy.dev/postgres-client":"true"' "$scheduler" >/dev/null
  grep -F '{ protocol: TCP, port: 5432 }' "$network" >/dev/null
  grep -F 'kubernetes.io/metadata.name: chuggy-work' "$policy" >/dev/null
  touch "$out"
''
