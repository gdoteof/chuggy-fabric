{ pkgs }:

pkgs.runCommand "chuggy-build-platform" {
  nativeBuildInputs = [ pkgs.kubectl pkgs.python3 pkgs.gawk pkgs.gnugrep pkgs.jq pkgs.coreutils pkgs.git ];
} ''
  set -eu
  root=${../.}
  cp -R "$root/scripts" scripts-under-test
  chmod -R u+w scripts-under-test
  cp "$root/tests/fixtures/build-request/kubectl" scripts-under-test/kubectl-fixture
  set +u
  patchShebangs scripts-under-test
  set -u
  scripts=$PWD/scripts-under-test
  test "$(sha256sum "$root/cluster/build-system/vendor/shipwright-v0.18.4/release.yaml" | cut -d' ' -f1)" = 451ad62b1f667103679c6f27c7fcbdf61fadfdd82216e3a90f0d78b0a7f4fe76
  test "$(sha256sum "$root/cluster/build-system/vendor/tekton-v1.12.0/release.yaml" | cut -d' ' -f1)" = e2765b483924b1c4e3ac15810c996e5cb06f3d1aa10bee4ce0113c8b5b0a078a
  test "$(sha256sum "$root/cluster/build-prerequisites/vendor/cert-manager-v1.18.2/release.yaml" | cut -d' ' -f1)" = e200b8fa1de6999989486fdce2c53f5d215916cc54e64ac6db109e64b88dcea7
  test "$(sha256sum "$root/cluster/build-system/buildkit-rootless-v1.yaml" | cut -d' ' -f1)" = 8422c2c6d5109779ec1ccb5d5c678213ef60dae4aff9922e17f1ee212ec39693
  test "$(sha256sum "$root/cluster/build-system/profiles/shipwright-buildkit-rootless-v1.json" | cut -d' ' -f1)" = 935d9e286a60255ae22e5c07447d3d71fd228169cfeb05d97710b0cf894245b4
  test "$(sha256sum "$root/cluster/build-system/profiles/shipwright-buildkit-rootless-mini-v1.json" | cut -d' ' -f1)" = 60002b363a806d55fea2d487d3d15249a4006369a64eb861ec5116303c290122
  kubectl kustomize "$root/cluster/build-prerequisites" > build-prerequisites.yaml
  kubectl kustomize "$root/cluster/build-system" > build-system.yaml
  grep -F '    group: cert-manager.io' "$root/cluster/build-system/webhook-certificate.yaml" >/dev/null
  test "$(grep -c 'apiGroup:' "$root/cluster/build-system/webhook-certificate.yaml" || true)" = 0
  grep -F 'name: buildkit-rootless-v1' build-system.yaml >/dev/null
  grep -F 'moby/buildkit:v0.26.2-rootless@sha256:0ffa2fcf6b8757c47d569b3ef0f03f9d5eb3b9ff5ce68d858f994f89b749da0c' build-system.yaml >/dev/null
  grep -F 'type: Unconfined' build-system.yaml >/dev/null
  grep -F 'allowPrivilegeEscalation: true' build-system.yaml >/dev/null
  grep -F 'chuggy.dev/node-role=builder:NoSchedule' "$root/cluster/build-system/profiles/shipwright-buildkit-rootless-v1.json" >/dev/null
  grep -F 'chuggy.dev/node-role=builder' "$root/examples/builder-node.nix" >/dev/null
  grep -F 'chuggy.dev/node-role=builder:NoSchedule' "$root/examples/builder-node.nix" >/dev/null
  grep -F 'chuggy.mini.enable = true' "$root/examples/mini-chuggy-node.nix" >/dev/null
  bash -n "$root/tests/integration/build-platform.sh"
  grep -F 'git -C "$BUILD_TEST_FLUX_WORKTREE" push' "$root/tests/integration/build-platform.sh" >/dev/null
  grep -F '.status.lastAppliedRevision' "$root/tests/integration/build-platform.sh" >/dev/null
  grep -F 'NoSchedule' "$root/tests/integration/build-platform.sh" >/dev/null
  test "$(grep -c 'kubectl apply' "$root/tests/integration/build-platform.sh" || true)" = 0

  mkdir first second changed
  render() {
    output_root="$1"
    shift
    "$scripts/render-build-request" \
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

  mkdir mini
  mini_path=$(render mini --profile mini)
  grep -F 'fabric.chuggy.dev/profile: shipwright-buildkit-rootless-mini/v1' "mini/$mini_path" >/dev/null
  grep -F 'fabric.chuggy.dev/profile-digest: sha256:60002b363a806d55fea2d487d3d15249a4006369a64eb861ec5116303c290122' "mini/$mini_path" >/dev/null
  grep -F 'chuggy.dev/node-role: builder' "mini/$mini_path" >/dev/null
  test "$(grep -c 'tolerations:' "mini/$mini_path" || true)" = 0
  test "$mini_path" != "$first_path"

  mkdir results
  export RESULTS_PATH="$PWD/results"
  export BATCH_SIZE=1
  export BUILD_RUN_FIXTURE="$root/tests/fixtures/build-request/buildruns.json"
  export BUILD_RUN_FIXTURE_CONTINUED="$root/tests/fixtures/build-request/buildruns.json"
  export PATCH_LOG="$PWD/patch.log"
  export KUBECTL="$scripts/kubectl-fixture"
  "$scripts/record-build-provenance"
  record="$RESULTS_PATH/sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/build-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-a1.json"
  test -f "$record"
  test "$(sha256sum "$record" | awk '{print "sha256:" $1}')" = "$(cat "$record.sha256")"
  test "$(jq -r '.provenanceRecordDigest' "$record")" = "$(jq -S '.result' "$record" | sha256sum | awk '{print "sha256:" $1}')"
  grep -F 'fabric.chuggy.dev/provenance-record-digest' "$PATCH_LOG" >/dev/null
  test "$(jq -r '.result.source.repositoryId' "$record")" = example-service
  test "$(jq -r '.result.renderer' "$record")" = shipwright-build-request/v1
  test "$(jq -r '.result.controller' "$record")" = v0.18.4
  grep -F '"finalizers":[]' "$PATCH_LOG" >/dev/null

  export BUILD_RUN_FIXTURE="$root/tests/fixtures/build-request/buildruns-page-1.json"
  : > "$PATCH_LOG"
  "$scripts/record-build-provenance"
  grep -F 'build-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-a1' "$PATCH_LOG" >/dev/null

  export BUILD_RUN_FIXTURE="$root/tests/fixtures/build-request/buildruns-page-1.json"
  export BUILD_RUN_FIXTURE_CONTINUED="$root/tests/fixtures/build-request/buildruns-operational.json"
  export NOW_EPOCH=1787605200
  if "$scripts/check-build-attempts" 2>attempt-alerts.log; then
    echo "failed and stalled fixture produced no actionable signal" >&2
    exit 1
  fi
  grep -F '"alert":"BuildAttemptFailed"' attempt-alerts.log >/dev/null
  grep -F '"attempt":"build-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-a1"' attempt-alerts.log >/dev/null
  grep -F '"alert":"BuildAttemptStalled"' attempt-alerts.log >/dev/null
  grep -F '"attempt":"build-dddddddddddddddddddddddddddddddddddddddd-a3"' attempt-alerts.log >/dev/null

  export BUILD_RUN_FIXTURE="$root/tests/fixtures/build-request/buildruns.json"
  retry_manifest="first/$first_path"
  retry_request=$(awk '/fabric.chuggy.dev\/request-digest:/{print $2; exit}' "$retry_manifest")
  retry_attempt=$(awk '/^kind: BuildRun$/{run=1} run && /^  name:/{print $2; exit}' "$retry_manifest")
  retry_directory="$RESULTS_PATH/$retry_request"
  retry_record="$retry_directory/$retry_attempt.json"
  mkdir -p "$retry_directory"
  jq -S --arg request "$retry_request" --arg attempt "$retry_attempt" '.result |
    .requestDigest = $request |
    .attempt.name = $attempt |
    .terminalCondition.status = "False" |
    .terminalCondition.reason = "Failed"
  ' "$record" > retry-payload
  retry_digest=$(sha256sum retry-payload | awk '{print "sha256:" $1}')
  jq -nS --arg digest "sha256:fabricated" --slurpfile result retry-payload \
    '{provenanceRecordDigest:$digest,result:$result[0]}' > "$retry_record"
  sha256sum "$retry_record" | awk '{print "sha256:" $1}' > "$retry_record.sha256"
  cp "$retry_manifest" retry-pristine.yaml
  if "$scripts/retry-build-request" "$retry_manifest" --results-path "$RESULTS_PATH" 2>fabricated-digest.log; then
    echo "retry accepted a fabricated canonical provenance digest" >&2
    exit 1
  fi
  cmp retry-pristine.yaml "$retry_manifest"
  grep -F 'canonical provenance digest failed' fabricated-digest.log >/dev/null

  jq -nS --arg digest "$retry_digest" --slurpfile result retry-payload \
    '{provenanceRecordDigest:$digest,result:$result[0]}' > "$retry_record"
  sha256sum "$retry_record" | awk '{print "sha256:" $1}' > "$retry_record.sha256"
  cp "$retry_record" verified-record
  printf ' ' >> "$retry_record"
  if "$scripts/retry-build-request" "$retry_manifest" --results-path "$RESULTS_PATH" 2>outer-checksum.log; then
    echo "retry accepted a record whose outer checksum failed" >&2
    exit 1
  fi
  cmp retry-pristine.yaml "$retry_manifest"
  grep -F 'durable provenance checksum failed' outer-checksum.log >/dev/null
  cp verified-record "$retry_record"

  jq -S '.result | .controller = "v0.18.3"' "$retry_record" > mismatched-controller-payload
  mismatched_controller_digest=$(sha256sum mismatched-controller-payload | awk '{print "sha256:" $1}')
  jq -nS --arg digest "$mismatched_controller_digest" --slurpfile result mismatched-controller-payload \
    '{provenanceRecordDigest:$digest,result:$result[0]}' > "$retry_record"
  sha256sum "$retry_record" | awk '{print "sha256:" $1}' > "$retry_record.sha256"
  if "$scripts/retry-build-request" "$retry_manifest" --results-path "$RESULTS_PATH" 2>controller-mismatch.log; then
    echo "retry accepted mismatched controller provenance" >&2
    exit 1
  fi
  cmp retry-pristine.yaml "$retry_manifest"
  grep -F 'provenance identities do not match' controller-mismatch.log >/dev/null
  cp verified-record "$retry_record"
  sha256sum "$retry_record" | awk '{print "sha256:" $1}' > "$retry_record.sha256"

  cp "$retry_manifest" mismatched-manifest.yaml
  sed -i 's#image: "registry.example.internal/team/example-service:#image: "registry.example.internal/team/wrong:#' mismatched-manifest.yaml
  if "$scripts/retry-build-request" mismatched-manifest.yaml --results-path "$RESULTS_PATH" 2>manifest-mismatch.log; then
    echo "retry accepted a Build output that disagreed with its target identity" >&2
    exit 1
  fi
  grep -F 'Build output does not match the request target' manifest-mismatch.log >/dev/null

  "$scripts/retry-build-request" "$retry_manifest" --results-path "$RESULTS_PATH" >retry-name
  test "$(cat retry-name)" = "''${retry_attempt%-a1}-a2"
  grep -F 'kind: Build' "$retry_manifest" >/dev/null
  grep -F "name: ''${retry_attempt%-a1}-a2" "$retry_manifest" >/dev/null
  grep -F 'fabric.chuggy.dev/attempt-ordinal: "2"' "$retry_manifest" >/dev/null
  test "$(grep -c 'revision: 0123456789abcdef0123456789abcdef01234567' "$retry_manifest")" = 1
  if "$scripts/retry-build-request" "$retry_manifest" --results-path "$RESULTS_PATH" 2>retry-without-provenance.log; then
    echo "retry advanced without durable provenance for the live attempt" >&2
    exit 1
  fi
  grep -F 'durable provenance is incomplete' retry-without-provenance.log >/dev/null

  cp "$retry_manifest" retirement.yaml
  if "$scripts/retire-build-request" retirement.yaml --results-path "$RESULTS_PATH" 2>retire-without-provenance.log; then
    echo "retirement removed a declaration without durable provenance" >&2
    exit 1
  fi
  test -f retirement.yaml
  grep -F 'durable provenance is incomplete' retire-without-provenance.log >/dev/null

  cp "second/$second_path" retirement.yaml
  git init -q retirement-repository
  cp retirement.yaml retirement-repository/request.yaml
  git -C retirement-repository add request.yaml
  git -C retirement-repository -c user.name=test -c user.email=test@invalid commit -qm fixture
  jq -S '.result | .renderer = "shipwright-build-request/v0"' "$retry_record" > mismatched-renderer-payload
  mismatched_renderer_digest=$(sha256sum mismatched-renderer-payload | awk '{print "sha256:" $1}')
  jq -nS --arg digest "$mismatched_renderer_digest" --slurpfile result mismatched-renderer-payload \
    '{provenanceRecordDigest:$digest,result:$result[0]}' > "$retry_record"
  sha256sum "$retry_record" | awk '{print "sha256:" $1}' > "$retry_record.sha256"
  if "$scripts/retire-build-request" retirement-repository/request.yaml --results-path "$RESULTS_PATH" 2>renderer-mismatch.log; then
    echo "retirement accepted mismatched renderer provenance" >&2
    exit 1
  fi
  test -f retirement-repository/request.yaml
  test -z "$(git -C retirement-repository diff --cached --diff-filter=D --name-only)"
  grep -F 'provenance identities do not match' renderer-mismatch.log >/dev/null
  cp verified-record "$retry_record"
  sha256sum "$retry_record" | awk '{print "sha256:" $1}' > "$retry_record.sha256"

  jq -S '.result | .source.repositoryId = "wrong-repository"' "$retry_record" > mismatched-payload
  mismatched_digest=$(sha256sum mismatched-payload | awk '{print "sha256:" $1}')
  jq -nS --arg digest "$mismatched_digest" --slurpfile result mismatched-payload \
    '{provenanceRecordDigest:$digest,result:$result[0]}' > "$retry_record"
  sha256sum "$retry_record" | awk '{print "sha256:" $1}' > "$retry_record.sha256"
  if "$scripts/retire-build-request" retirement-repository/request.yaml --results-path "$RESULTS_PATH" 2>identity-mismatch.log; then
    echo "retirement accepted mismatched repository provenance" >&2
    exit 1
  fi
  test -f retirement-repository/request.yaml
  grep -F 'provenance identities do not match' identity-mismatch.log >/dev/null
  jq -nS --arg digest "$retry_digest" --slurpfile result retry-payload \
    '{provenanceRecordDigest:$digest,result:$result[0]}' > "$retry_record"
  sha256sum "$retry_record" | awk '{print "sha256:" $1}' > "$retry_record.sha256"
  "$scripts/retire-build-request" retirement-repository/request.yaml --results-path "$RESULTS_PATH" >retire.log
  test ! -e retirement-repository/request.yaml
  git -C retirement-repository diff --cached --diff-filter=D --name-only | grep -Fx request.yaml >/dev/null

  cp "$record" pristine-record
  cp "$record.sha256" pristine-checksum
  rm "$record.sha256"
  : > "$PATCH_LOG"
  "$scripts/record-build-provenance" 2>missing-checksum.log
  test ! -s "$PATCH_LOG"
  grep -F 'incomplete durable record' missing-checksum.log >/dev/null

  cp pristine-record "$record"
  cp pristine-checksum "$record.sha256"
  jq '.result.output.digest = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"' "$record" > tampered
  mv tampered "$record"
  sha256sum "$record" | awk '{print "sha256:" $1}' > "$record.sha256"
  : > "$PATCH_LOG"
  "$scripts/record-build-provenance" 2>semantic-mismatch.log
  test ! -s "$PATCH_LOG"
  grep -F 'does not match terminal BuildRun' semantic-mismatch.log >/dev/null

  jq '.items[0].metadata.annotations["fabric.chuggy.dev/request-digest"] = "../../escape"' \
    "$BUILD_RUN_FIXTURE" > invalid-request.json
  export RESULTS_PATH="$PWD/invalid-results"
  export BUILD_RUN_FIXTURE="$PWD/invalid-request.json"
  : > "$PATCH_LOG"
  "$scripts/record-build-provenance" 2>invalid-request.log
  test ! -s "$PATCH_LOG"
  grep -F 'invalid request digest' invalid-request.log >/dev/null
  test ! -e "$PWD/escape"

  jq 'del(.items[0].metadata.annotations["fabric.chuggy.dev/source-repository-id"])' \
    "$root/tests/fixtures/build-request/buildruns.json" > missing-repository-id.json
  export RESULTS_PATH="$PWD/missing-repository-results"
  export BUILD_RUN_FIXTURE="$PWD/missing-repository-id.json"
  export BUILD_RUN_FIXTURE_CONTINUED="$PWD/missing-repository-id.json"
  : > "$PATCH_LOG"
  "$scripts/record-build-provenance" 2>missing-repository-id.log
  test ! -s "$PATCH_LOG"
  grep -F 'invalid source repository id' missing-repository-id.log >/dev/null

  jq '.items[0].metadata.annotations["fabric.chuggy.dev/source-repository-id"] = ("a" * 64)' \
    "$root/tests/fixtures/build-request/buildruns.json" > overlength-repository-id.json
  export RESULTS_PATH="$PWD/overlength-repository-results"
  export BUILD_RUN_FIXTURE="$PWD/overlength-repository-id.json"
  export BUILD_RUN_FIXTURE_CONTINUED="$PWD/overlength-repository-id.json"
  : > "$PATCH_LOG"
  "$scripts/record-build-provenance" 2>overlength-repository-id.log
  test ! -s "$PATCH_LOG"
  grep -F 'invalid source repository id' overlength-repository-id.log >/dev/null

  export RESULTS_PATH="$PWD/mismatched-repository-results"
  export BUILD_RUN_FIXTURE="$root/tests/fixtures/build-request/buildruns.json"
  export BUILD_RUN_FIXTURE_CONTINUED="$root/tests/fixtures/build-request/buildruns.json"
  : > "$PATCH_LOG"
  "$scripts/record-build-provenance"
  jq '.items[0].metadata.annotations["fabric.chuggy.dev/source-repository-id"] = "other-service"' \
    "$root/tests/fixtures/build-request/buildruns.json" > mismatched-repository-id.json
  export BUILD_RUN_FIXTURE="$PWD/mismatched-repository-id.json"
  export BUILD_RUN_FIXTURE_CONTINUED="$PWD/mismatched-repository-id.json"
  : > "$PATCH_LOG"
  "$scripts/record-build-provenance" 2>mismatched-repository-id.log
  test ! -s "$PATCH_LOG"
  grep -F 'does not match terminal BuildRun' mismatched-repository-id.log >/dev/null

  changed_path=$(render changed --cache disabled)
  test "$first_path" != "$changed_path"
  test ! -e "first/$changed_path"
  if "$scripts/render-build-request" \
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
  if "$scripts/render-build-request" \
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
  "$scripts/render-build-request" \
    --repository-id internal-service \
    --source-url http://git.chuggy-git.svc.cluster.local:8080/team/repository.git \
    --source-commit 0123456789abcdef0123456789abcdef01234567 \
    --source-secret source-read \
    --target-image-repository registry.chuggy-registry.svc.cluster.local:5000/team/repository \
    --output-secret registry-push \
    --output-root internal-network >/dev/null
  if "$scripts/render-build-request" \
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
  if grep -F 'has(status)' "$root/modules/flux.nix" >/dev/null; then
    echo "Flux CEL cannot use has() for the top-level status property" >&2
    exit 1
  fi
  grep -F 'has(status.conditions)' "$root/modules/flux.nix" >/dev/null
  grep -F "e.status == 'False'" "$root/modules/flux.nix" >/dev/null
  grep -F "e.status == 'True'" "$root/modules/flux.nix" >/dev/null
  grep -F "s.git.commitSha == metadata.annotations" "$root/modules/flux.nix" >/dev/null
  grep -F "status.output.digest.matches" "$root/modules/flux.nix" >/dev/null
  grep -F 'healthCheckExprs:' "$root/cluster/flux-system/gotk-components.yaml" >/dev/null
  grep -F 'kustomize-controller:v1.5.1@sha256:b89935f9428764c389c5192fdb8f6c53b66e365fa09ac8cec597e82273e9f518' "$root/cluster/flux-system/gotk-components.yaml" >/dev/null
  grep -F 'chuggy-build-attempt-alerts' "$root/modules/build-provenance.nix" >/dev/null
  grep -F 'No command in this flow deletes registry content' "$root/docs/build-operations-runbook.md" >/dev/null
  touch "$out"
''
