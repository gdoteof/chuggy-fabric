# What `kubectl kustomize` renders from each directory of `cluster/` that
# declares the cluster's own objects, one file a directory, and `cluster.yaml`,
# which is all of them as one stream.
#
# A check that holds a Deployment against the NetworkPolicy that selects it
# reads objects from more than one of these directories, so the checks that
# resolve one object against another read `cluster.yaml`. A directory added to
# `cluster/` and left out of the list below is one none of them reads.
{ pkgs }:

pkgs.runCommand "chuggy-rendered-cluster" {
  nativeBuildInputs = [ pkgs.kubectl ];
} ''
  set -eu
  mkdir "$out"
  for directory in apps chuggy-migrate chuggy; do
    kubectl kustomize ${../cluster}/"$directory" > "$out/$directory.yaml"
    test -s "$out/$directory.yaml"
    if [ -e "$out/cluster.yaml" ]; then echo '---' >> "$out/cluster.yaml"; fi
    cat "$out/$directory.yaml" >> "$out/cluster.yaml"
  done
''
