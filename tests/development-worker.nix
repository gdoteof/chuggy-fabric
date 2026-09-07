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
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:3e37aa3529dd22235c3ff13c05a3f7ef3ec4694ce1652eeeb29cde3a8f58ca82' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:782b97c2f557fda741dedf58005d830aae1556e29d9433aa286f3da9694ced33' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:eccacebea8fccaab485fac4d2bfb8990173853a7c44d1f0eec49806b274920b6' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:00598efb07666fbe0a66ce7a8951b0aadf93cbb5ca2bca00581142f77ec17458' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:a49a5244f556be7996b1d8a20e61a23504546e32f9eb1a3d636d4fb2b421d071' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:0f728b620c5e35fa5872fe9642ee90d75b49c5b33f822999926f17f2b00e4009' "$scheduler" >/dev/null
  grep -F 'registry.chuggy.internal/chuggy/worker@sha256:528b60992328f9076fc97a731027f2aef38e23c42f1261067ef417e03b06bb27' "$scheduler" >/dev/null
  grep -F '"credentials": ["chuggy-git-worker", "chuggy-github-worker", "claude-code"]' "$scheduler" >/dev/null
  grep -F '"secretName": "claude-code"' "$scheduler" >/dev/null
  grep -F '"CHUG_WORKER_WORKSPACE": "/workspace"' "$scheduler" >/dev/null
  grep -F '"ephemeralStorageLimit": "20Gi"' "$scheduler" >/dev/null
  grep -F '"fsGroup":1000' "$scheduler" >/dev/null
  grep -F '"mayCompleteTask": false' "$scheduler" >/dev/null
  grep -F 'kubernetes.io/metadata.name: chuggy-git' "$network" >/dev/null
  grep -F '{ protocol: TCP, port: 443 }' "$network" >/dev/null

  # The PostgreSQL an attempt runs gates against is a sidecar of its pod: the
  # scheduler names the image, and neither the work namespace's egress nor the
  # server's ingress admits a path from a worker to the control plane's server.
  grep -F '"image": "docker.io/library/postgres:18-alpine@sha256:' "$scheduler" >/dev/null
  if grep -F '"chuggy.dev/postgres-client"' "$scheduler" >/dev/null; then
    echo "worker pods are labelled as postgres clients" >&2; exit 1
  fi
  if grep -F 'port: 5432' "$network" >/dev/null; then
    echo "the work namespace has an egress to PostgreSQL" >&2; exit 1
  fi
  grep -F 'name: postgres-admits-labelled-clients' "$policy" >/dev/null
  if grep -F 'kubernetes.io/metadata.name: chuggy-work' "$policy" >/dev/null; then
    echo "the server's ingress admits the work namespace" >&2; exit 1
  fi
  touch "$out"
''
