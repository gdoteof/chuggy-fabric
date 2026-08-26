{ pkgs }:

pkgs.runCommand "github-repository-transition" {
  nativeBuildInputs = [ pkgs.gnugrep pkgs.kubectl ];
} ''
  set -eu
  root=${../.}

  kubectl kustomize "$root/cluster/apps" > rendered.yaml

  for workload in chuggy-api chuggy-ticket-service; do
    manifest="$root/cluster/apps/$workload.yaml"
    grep -F '"repository": "https://github.com/kasofsk/chuggy.git"' "$manifest" >/dev/null
    grep -F 'name: chuggy-github-reader-token' "$manifest" >/dev/null
    grep -F 'path: chuggy-github' "$manifest" >/dev/null
  done

  finalizer="$root/cluster/apps/chuggy-finalizer.yaml"
  grep -F '"repository": "https://github.com/kasofsk/chuggy.git"' "$finalizer" >/dev/null
  grep -F 'name: chuggy-github-finalizer-token' "$finalizer" >/dev/null
  grep -F 'path: chuggy-github' "$finalizer" >/dev/null

  network="$root/cluster/apps/chuggy-control-plane-network-policy.yaml"
  test "$(grep -c 'cidr: 0.0.0.0/0' "$network")" -ge 2
  for range in 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16; do
    test "$(grep -c -- "- $range" "$network")" -ge 2
  done

  importer="$root/cluster/apps/chuggy-configuration-importer.yaml"
  if grep -F 'github.com/kasofsk/chuggy' "$importer"; then
    echo 'configuration importer must remain on internal git during transition' >&2
    exit 1
  fi

  touch "$out"
''
