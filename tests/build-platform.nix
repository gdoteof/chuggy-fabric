# What a build stands on and no render shows: that the vendored Tekton release
# is the one pinned, that the Flux install carries the kustomize-controller
# that honours the `deletionPolicy` `apps` and the root set, and that the two
# example nodes still say what cluster/build-system/release-run.yaml and
# worker-image-run.yaml place a build by.
{ pkgs }:

pkgs.runCommand "chuggy-build-platform" {
  nativeBuildInputs = [ pkgs.gnugrep pkgs.coreutils ];
} ''
  set -eu
  root=${../.}
  test "$(sha256sum "$root/cluster/build-system/vendor/tekton-v1.12.0/release.yaml" | cut -d' ' -f1)" = e2765b483924b1c4e3ac15810c996e5cb06f3d1aa10bee4ce0113c8b5b0a078a
  grep -F '"chuggy.dev/node-role=builder"' "$root/examples/builder-node.nix" >/dev/null
  grep -F 'chuggy.dev/node-role=builder:NoSchedule' "$root/examples/builder-node.nix" >/dev/null
  grep -F 'chuggy.mini.enable = true' "$root/examples/mini-chuggy-node.nix" >/dev/null
  grep -F 'kustomize-controller:v1.6.1@sha256:1a50730537bafb7827365b9af95c4eb71ca3d9b0bed9bc9bc765880e976972ef' "$root/cluster/flux-system/gotk-components.yaml" >/dev/null
  touch "$out"
''
