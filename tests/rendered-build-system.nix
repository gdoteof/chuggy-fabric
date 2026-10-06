# What `kubectl kustomize` renders from `cluster/build-system`, as one file.
#
# Apart from rendered-cluster.nix, whose directories declare the cluster's own
# objects: this one also renders a vendored release, and a check that holds
# every object in `cluster.yaml` to this cluster's rules would be holding
# Tekton's.
{ pkgs }:

pkgs.runCommand "chuggy-rendered-build-system" {
  nativeBuildInputs = [ pkgs.kubectl ];
} ''
  set -eu
  kubectl kustomize ${../cluster/build-system} > "$out"
  test -s "$out"
''
