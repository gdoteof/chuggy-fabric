{ pkgs }:

pkgs.runCommand "chuggy-build-platform" {
  nativeBuildInputs = [ pkgs.kubectl pkgs.python3 pkgs.gawk pkgs.gnugrep pkgs.jq pkgs.coreutils ];
} ''
  set -eu
  root=${../.}
  test "$(sha256sum "$root/cluster/build-system/vendor/shipwright-v0.18.4/release.yaml" | cut -d' ' -f1)" = 451ad62b1f667103679c6f27c7fcbdf61fadfdd82216e3a90f0d78b0a7f4fe76
  test "$(sha256sum "$root/cluster/build-system/vendor/tekton-v1.12.0/release.yaml" | cut -d' ' -f1)" = e2765b483924b1c4e3ac15810c996e5cb06f3d1aa10bee4ce0113c8b5b0a078a
  test "$(sha256sum "$root/cluster/build-prerequisites/vendor/cert-manager-v1.18.2/release.yaml" | cut -d' ' -f1)" = e200b8fa1de6999989486fdce2c53f5d215916cc54e64ac6db109e64b88dcea7
  test "$(sha256sum "$root/cluster/build-system/buildkit-rootless-v1.yaml" | cut -d' ' -f1)" = 8422c2c6d5109779ec1ccb5d5c678213ef60dae4aff9922e17f1ee212ec39693
  test "$(sha256sum "$root/cluster/build-system/profiles/shipwright-buildkit-rootless-v1.json" | cut -d' ' -f1)" = 935d9e286a60255ae22e5c07447d3d71fd228169cfeb05d97710b0cf894245b4
  kubectl kustomize "$root/cluster/build-prerequisites" > build-prerequisites.yaml
  kubectl kustomize "$root/cluster/build-system" > build-system.yaml
  grep -F 'name: buildkit-rootless-v1' build-system.yaml >/dev/null
  grep -F 'moby/buildkit:v0.26.2-rootless@sha256:0ffa2fcf6b8757c47d569b3ef0f03f9d5eb3b9ff5ce68d858f994f89b749da0c' build-system.yaml >/dev/null
  grep -F 'type: Unconfined' build-system.yaml >/dev/null
  grep -F 'allowPrivilegeEscalation: true' build-system.yaml >/dev/null
  grep -F 'chuggy.dev/node-role=builder:NoSchedule' "$root/cluster/build-system/profiles/shipwright-buildkit-rootless-v1.json" >/dev/null
  grep -F 'chuggy.dev/node-role=builder' "$root/examples/builder-node.nix" >/dev/null
  grep -F 'chuggy.dev/node-role=builder:NoSchedule' "$root/examples/builder-node.nix" >/dev/null
  bash -n "$root/tests/integration/build-platform.sh"
  grep -F 'git -C "$BUILD_TEST_FLUX_WORKTREE" push' "$root/tests/integration/build-platform.sh" >/dev/null
  grep -F '.status.lastAppliedRevision' "$root/tests/integration/build-platform.sh" >/dev/null
  grep -F 'NoSchedule' "$root/tests/integration/build-platform.sh" >/dev/null
  test "$(grep -c 'kubectl apply' "$root/tests/integration/build-platform.sh" || true)" = 0

  mkdir first second changed
  render() {
    output_root="$1"
    shift
    "$root/scripts/render-build-request" \
      --repository-id example-service \
      --source-url https://git.example.com/team/example-service.git \
      --source-commit 0123456789abcdef0123456789abcdef01234567 \
      --source-secret example-source-read \
      --target-image-repository registry.example.internal/team/example-service \
      --output-secret example-registry-push \
      --output-root "$output_root" "$@"
  }
  first_path=$(render first)
  second_path=$(render second)
  test "$first_path" = "$second_path"
  cmp "first/$first_path" "second/$second_path"
  grep -F 'revision: 0123456789abcdef0123456789abcdef01234567' "first/$first_path" >/dev/null
  grep -F 'fabric.chuggy.dev/source-repository-id: example-service' "first/$first_path" >/dev/null
  grep -F 'fabric.chuggy.dev/provenance-required' "first/$first_path" >/dev/null
  grep -F 'chuggy.dev/node-role: builder' "first/$first_path" >/dev/null
  grep -F 'kubernetes.io/arch: amd64' "first/$first_path" >/dev/null
  grep -F 'effect: NoSchedule' "first/$first_path" >/dev/null
  test "$(grep -c 'ttlAfter' "first/$first_path" || true)" = 0

  mkdir results
  export RESULTS_PATH="$PWD/results"
  export BATCH_SIZE=1
  export BUILD_RUN_FIXTURE="$root/tests/fixtures/build-request/buildruns.json"
  export BUILD_RUN_FIXTURE_CONTINUED="$root/tests/fixtures/build-request/buildruns.json"
  export PATCH_LOG="$PWD/patch.log"
  export KUBECTL="$root/tests/fixtures/build-request/kubectl"
  "$root/scripts/record-build-provenance"
  record="$RESULTS_PATH/sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/build-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-a1.json"
  test -f "$record"
  test "$(sha256sum "$record" | awk '{print "sha256:" $1}')" = "$(cat "$record.sha256")"
  test "$(jq -r '.provenanceRecordDigest' "$record")" = "$(jq -S '.result' "$record" | sha256sum | awk '{print "sha256:" $1}')"
  grep -F 'fabric.chuggy.dev/provenance-record-digest' "$PATCH_LOG" >/dev/null
  test "$(jq -r '.result.source.repositoryId' "$record")" = example-service
  grep -F '"finalizers":[]' "$PATCH_LOG" >/dev/null

  export BUILD_RUN_FIXTURE="$root/tests/fixtures/build-request/buildruns-page-1.json"
  : > "$PATCH_LOG"
  "$root/scripts/record-build-provenance"
  grep -F 'build-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-a1' "$PATCH_LOG" >/dev/null

  cp "$record" pristine-record
  cp "$record.sha256" pristine-checksum
  rm "$record.sha256"
  : > "$PATCH_LOG"
  "$root/scripts/record-build-provenance" 2>missing-checksum.log
  test ! -s "$PATCH_LOG"
  grep -F 'incomplete durable record' missing-checksum.log >/dev/null

  cp pristine-record "$record"
  cp pristine-checksum "$record.sha256"
  jq '.result.output.digest = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"' "$record" > tampered
  mv tampered "$record"
  sha256sum "$record" | awk '{print "sha256:" $1}' > "$record.sha256"
  : > "$PATCH_LOG"
  "$root/scripts/record-build-provenance" 2>semantic-mismatch.log
  test ! -s "$PATCH_LOG"
  grep -F 'does not match terminal BuildRun' semantic-mismatch.log >/dev/null

  jq '.items[0].metadata.annotations["fabric.chuggy.dev/request-digest"] = "../../escape"' \
    "$BUILD_RUN_FIXTURE" > invalid-request.json
  export RESULTS_PATH="$PWD/invalid-results"
  export BUILD_RUN_FIXTURE="$PWD/invalid-request.json"
  : > "$PATCH_LOG"
  "$root/scripts/record-build-provenance" 2>invalid-request.log
  test ! -s "$PATCH_LOG"
  grep -F 'invalid request digest' invalid-request.log >/dev/null
  test ! -e "$PWD/escape"

  changed_path=$(render changed --cache disabled)
  test "$first_path" != "$changed_path"
  test ! -e "first/$changed_path"
  if "$root/scripts/render-build-request" \
    --repository-id example-service \
    --source-url ssh://git.example.invalid/repository.git \
    --source-commit main \
    --source-secret source-read \
    --target-image-repository registry.example.invalid/repository \
    --output-secret registry-push \
    --output-root invalid; then
    echo "renderer accepted a moving source revision" >&2
    exit 1
  fi
  if "$root/scripts/render-build-request" \
    --repository-id example-service \
    --source-url ssh://git.example.invalid/repository.git \
    --source-commit 0123456789abcdef0123456789abcdef01234567 \
    --source-secret source-read \
    --target-image-repository registry.example.invalid/repository \
    --output-secret registry-push \
    --output-root invalid-network; then
    echo "renderer accepted an endpoint blocked by the network profile" >&2
    exit 1
  fi
  "$root/scripts/render-build-request" \
    --repository-id internal-service \
    --source-url http://git.chuggy-git.svc.cluster.local:8080/team/repository.git \
    --source-commit 0123456789abcdef0123456789abcdef01234567 \
    --source-secret source-read \
    --target-image-repository registry.chuggy-registry.svc.cluster.local:5000/team/repository \
    --output-secret registry-push \
    --output-root internal-network >/dev/null
  if "$root/scripts/render-build-request" \
    --repository-id example-service \
    --source-url ssh://git.example.invalid/repository.git \
    --source-commit 0123456789abcdef0123456789abcdef01234567 \
    --source-secret source-read \
    --target-image-repository registry.example.invalid/repository \
    --output-secret registry-push \
    --platform linux/arm64 \
    --output-root invalid-platform; then
    echo "renderer accepted a platform outside the v1 profile" >&2
    exit 1
  fi

  grep -F 'kind: BuildRun' "$root/modules/flux.nix" >/dev/null
  grep -F "e.status == 'False'" "$root/modules/flux.nix" >/dev/null
  grep -F "e.status == 'True'" "$root/modules/flux.nix" >/dev/null
  grep -F "s.git.commitSha == metadata.annotations" "$root/modules/flux.nix" >/dev/null
  grep -F "status.output.digest.matches" "$root/modules/flux.nix" >/dev/null
  grep -F 'healthCheckExprs:' "$root/cluster/flux-system/gotk-components.yaml" >/dev/null
  grep -F 'kustomize-controller:v1.5.1@sha256:b89935f9428764c389c5192fdb8f6c53b66e365fa09ac8cec597e82273e9f518' "$root/cluster/flux-system/gotk-components.yaml" >/dev/null
  touch "$out"
''
