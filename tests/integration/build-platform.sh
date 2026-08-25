#!/usr/bin/env bash
set -o errexit -o nounset -o pipefail

require_environment() {
  local name=$1
  [[ -n ${!name:-} ]] || { echo "$name is required" >&2; exit 2; }
}

require_environment BUILD_TEST_TARGET_REPOSITORY
require_environment BUILD_TEST_SOURCE_SECRET
require_environment BUILD_TEST_OUTPUT_SECRET

source_url=${BUILD_TEST_SOURCE_URL:-https://github.com/docker-library/hello-world.git}
source_commit=${BUILD_TEST_SOURCE_COMMIT:-522bcd2faf422c60b9d20e64d7cd6d56600aec97}
context_dir=${BUILD_TEST_CONTEXT_DIR:-amd64/hello-world}
namespace=chuggy-build
root=$(cd "$(dirname "$0")/../.." && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/chuggy-build-integration.XXXXXX")
trap 'rm -rf "$scratch"' EXIT

for command in kubectl crane; do
  command -v "$command" >/dev/null || { echo "$command is required" >&2; exit 2; }
done
kubectl get clusterbuildstrategy.shipwright.io buildkit-rootless-v1 >/dev/null
kubectl get node -l chuggy.dev/node-role=builder -o name | grep -q . || {
  echo "no node is wired with chuggy.dev/node-role=builder" >&2
  exit 2
}
kubectl -n "$namespace" get secret "$BUILD_TEST_SOURCE_SECRET" "$BUILD_TEST_OUTPUT_SECRET" >/dev/null

request_path=$("$root/scripts/render-build-request" \
  --repository-id build-platform-fixture \
  --source-url "$source_url" \
  --source-commit "$source_commit" \
  --source-secret "$BUILD_TEST_SOURCE_SECRET" \
  --target-image-repository "$BUILD_TEST_TARGET_REPOSITORY" \
  --output-secret "$BUILD_TEST_OUTPUT_SECRET" \
  --context-dir "$context_dir" \
  --cache disabled \
  --output-root "$scratch")
manifest="$scratch/$request_path"
buildrun=$(awk '/^kind: BuildRun$/{found=1} found && /^  name:/{print $2; exit}' "$manifest")
tag=$(awk -F'"' '/^    image:/{print $2; exit}' "$manifest")

if kubectl -n "$namespace" get "buildrun/$buildrun" >/dev/null 2>&1; then
  echo "$buildrun already exists; use a fresh target repository so this gate proves a new execution" >&2
  exit 2
fi
kubectl apply -f "$manifest"
kubectl -n "$namespace" wait --for=condition=Succeeded --timeout=75m "buildrun/$buildrun"
observed_commit=$(kubectl -n "$namespace" get "buildrun/$buildrun" -o jsonpath='{.status.sources[?(@.name=="default")].git.commitSha}')
reported_digest=$(kubectl -n "$namespace" get "buildrun/$buildrun" -o jsonpath='{.status.output.digest}')
[[ $observed_commit == "$source_commit" ]] || { echo "built $observed_commit, expected $source_commit" >&2; exit 1; }
[[ $reported_digest =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "Shipwright did not report an image digest" >&2; exit 1; }
registry_digest=$(crane digest "$tag")
[[ $registry_digest == "$reported_digest" ]] || {
  echo "registry has $registry_digest, Shipwright reported $reported_digest" >&2
  exit 1
}
printf '%s@%s\n' "${tag%:*}" "$reported_digest"
