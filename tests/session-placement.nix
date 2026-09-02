# What an agent session pod is admitted to and isolated from, read off the
# rendered manifests rather than off the text that produces them.
#
# The property this holds is one no grep can: a pod's labels and the policies
# that select them are written in four different objects in three files, and
# every way of getting it wrong looks correct in each file on its own. The worst
# of them is silent -- a pod in `chuggy-work` that no NetworkPolicy selects is
# isolated in NEITHER direction, so dropping the session label from the
# scheduler's configuration would not deny a session anything, it would hand it
# the whole pod network. The other silent one is a destination selector naming
# nothing: right ports, no pod, packets dropped, and every object still reading
# correctly on its own. So the labels are read out of the Deployment's own
# environment, and every selector -- the ones that admit a session and the ones
# a session's own egress names -- is resolved against the pods and the policies
# the render actually contains, which is what the cluster does.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-session-placement" {
  nativeBuildInputs = [ pkgs.kubectl python ];
} ''
  set -eu
  kubectl kustomize ${../cluster/apps} > rendered.yaml
  python3 ${./session-placement.py} rendered.yaml
  touch "$out"
''
