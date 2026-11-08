# cluster/build-system/admit-worker.sh, run under BusyBox over this repository's
# own chuggy-scheduler.yaml and over files shaped to its cases, and then over a
# copy of the tree whose rewritten scheduler is rendered and held to
# tests/session-placement.py. The cases are in admit-worker.py's header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  script = ../cluster/build-system/admit-worker.sh;
in
pkgs.runCommand "chuggy-admit-worker" {
  nativeBuildInputs = [ python pkgs.kubectl ];
} ''
  set -eu
  mkdir work
  python3 ${./admit-worker.py} ${script} ${../cluster/chuggy/chuggy-scheduler.yaml} ${pkgs.busybox}/bin "$PWD/work"

  # What the rewrite makes of the tree is still a tree the placement checks
  # accept: the new worker is the newest offered and the session policy is on it.
  cp -r ${../cluster} cluster
  chmod -R u+w cluster
  PATH=${pkgs.busybox}/bin sh ${script} cluster/chuggy/chuggy-scheduler.yaml \
    1111111111111111111111111111111111111111 \
    sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb > /dev/null
  for directory in apps track-record chug-gy chuggy-migrate chuggy; do
    kubectl kustomize cluster/"$directory" >> cluster.yaml
    echo '---' >> cluster.yaml
  done
  python3 ${./session-placement.py} cluster.yaml
  touch "$out"
''
