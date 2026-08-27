#!/usr/bin/env bash
set -o errexit -o nounset -o pipefail

unavailable() { echo "integration prerequisite unavailable: $*" >&2; exit 2; }
require_environment() { local name=$1; [[ -n ${!name:-} ]] || unavailable "$name is required"; }
probe() { local description=$1; shift; "$@" >/dev/null 2>&1 || unavailable "$description"; }

require_environment BUILD_TEST_TARGET_REPOSITORY
require_environment BUILD_TEST_SOURCE_SECRET
require_environment BUILD_TEST_OUTPUT_SECRET
require_environment BUILD_TEST_FLUX_WORKTREE
require_environment BUILD_TEST_FLUX_BRANCH

source_url=${BUILD_TEST_SOURCE_URL:-https://github.com/docker-library/hello-world.git}
source_commit=${BUILD_TEST_SOURCE_COMMIT:-522bcd2faf422c60b9d20e64d7cd6d56600aec97}
context_dir=${BUILD_TEST_CONTEXT_DIR:-amd64/hello-world}
flux_namespace=${BUILD_TEST_FLUX_NAMESPACE:-flux-system}
flux_kustomization=${BUILD_TEST_FLUX_KUSTOMIZATION:-build-test}
namespace=chuggy-build
root=$(cd "$(dirname "$0")/../.." && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/chuggy-build-integration.XXXXXX")
trap 'rm -rf "$scratch"' EXIT

for command in kubectl jq git crane; do probe "$command executable" command -v "$command"; done
probe "Kubernetes API connectivity" kubectl get --raw=/readyz
probe "$namespace namespace" kubectl get namespace "$namespace"
probe "Shipwright rootless BuildKit strategy" kubectl get clusterbuildstrategy.shipwright.io buildkit-rootless-v1
probe "source credential Secret" kubectl -n "$namespace" get secret "$BUILD_TEST_SOURCE_SECRET"
probe "registry credential Secret" kubectl -n "$namespace" get secret "$BUILD_TEST_OUTPUT_SECRET"
probe "Flux test Kustomization" kubectl -n "$flux_namespace" get kustomization.kustomize.toolkit.fluxcd.io "$flux_kustomization"
probe "disposable Flux Git worktree" git -C "$BUILD_TEST_FLUX_WORKTREE" rev-parse --is-inside-work-tree
probe "clean disposable Flux Git worktree" git -C "$BUILD_TEST_FLUX_WORKTREE" diff --quiet
probe "clean disposable Flux Git index" git -C "$BUILD_TEST_FLUX_WORKTREE" diff --cached --quiet

current_branch=$(git -C "$BUILD_TEST_FLUX_WORKTREE" branch --show-current) || unavailable "Git branch lookup"
[[ $current_branch == "$BUILD_TEST_FLUX_BRANCH" ]] || unavailable "worktree is on $current_branch, expected disposable branch $BUILD_TEST_FLUX_BRANCH"
flux_json=$(kubectl -n "$flux_namespace" get kustomization.kustomize.toolkit.fluxcd.io "$flux_kustomization" -o json) || unavailable "Flux test Kustomization read"
printf '%s' "$flux_json" | jq -e '
  .spec.path == "./builds" and
  (.spec.healthCheckExprs // [] | any(
    .apiVersion == "shipwright.io/v1beta1" and .kind == "BuildRun" and
    (.current | contains("status.output.digest")) and
    (.current | contains("fabric.chuggy.dev/source-commit"))
  ))
' >/dev/null || unavailable "Flux test Kustomization must watch ./builds and carry BuildRun CEL digest health"
source_name=$(printf '%s' "$flux_json" | jq -r '.spec.sourceRef.name // empty')
source_kind=$(printf '%s' "$flux_json" | jq -r '.spec.sourceRef.kind // "GitRepository"')
[[ $source_kind == GitRepository && -n $source_name ]] || unavailable "Flux test Kustomization must reference a GitRepository"
probe "Flux test GitRepository" kubectl -n "$flux_namespace" get gitrepository.source.toolkit.fluxcd.io "$source_name"
source_json=$(kubectl -n "$flux_namespace" get gitrepository.source.toolkit.fluxcd.io "$source_name" -o json) || unavailable "Flux test GitRepository read"
source_branch=$(printf '%s' "$source_json" | jq -r '.spec.ref.branch // empty')
source_url_configured=$(printf '%s' "$source_json" | jq -r '.spec.url // empty')
worktree_remote=$(git -C "$BUILD_TEST_FLUX_WORKTREE" remote get-url origin) || unavailable "disposable worktree origin"
[[ $source_branch == "$BUILD_TEST_FLUX_BRANCH" ]] || unavailable "Flux GitRepository does not watch disposable branch $BUILD_TEST_FLUX_BRANCH"
[[ $source_url_configured == "$worktree_remote" ]] || unavailable "worktree origin does not match the Flux GitRepository URL"
printf '%s' "$source_json" | jq -e '.status.conditions // [] | any(.type == "Ready" and .status == "True")' >/dev/null || unavailable "Flux test GitRepository is not Ready"

nodes=$(kubectl get nodes -l chuggy.dev/node-role=builder -o json) || unavailable "builder node discovery"
printf '%s' "$nodes" | jq -e '
  .items | any(
    (.spec.unschedulable // false) == false and
    .metadata.labels["kubernetes.io/os"] == "linux" and
    .metadata.labels["kubernetes.io/arch"] == "amd64" and
    (.spec.taints // [] | any(.key == "chuggy.dev/node-role" and .value == "builder" and .effect == "NoSchedule"))
  )
' >/dev/null || unavailable "schedulable linux/amd64 builder node with matching NoSchedule taint"

request_path=$("$root/scripts/render-build-request" \
  --repository-id build-platform-fixture --source-url "$source_url" --source-commit "$source_commit" \
  --source-secret "$BUILD_TEST_SOURCE_SECRET" --target-image-repository "$BUILD_TEST_TARGET_REPOSITORY" \
  --output-secret "$BUILD_TEST_OUTPUT_SECRET" --context-dir "$context_dir" --cache disabled \
  --output-root "$BUILD_TEST_FLUX_WORKTREE")
manifest="$BUILD_TEST_FLUX_WORKTREE/$request_path"
buildrun=$(awk '/^kind: BuildRun$/{found=1} found && /^  name:/{print $2; exit}' "$manifest")
tag=$(awk -F'"' '/^    image:/{print $2; exit}' "$manifest")
existing=$(kubectl -n "$namespace" get "buildrun/$buildrun" --ignore-not-found -o name) || unavailable "BuildRun existence check"
if [[ -n $existing ]]; then
  unavailable "$buildrun already exists; use a fresh target repository so the gate proves a new Flux execution"
fi

git -C "$BUILD_TEST_FLUX_WORKTREE" add -- "$request_path"
git -C "$BUILD_TEST_FLUX_WORKTREE" -c user.name=chuggy-build-test -c user.email=build-test@invalid commit -m "test: materialize $buildrun"
test_commit=$(git -C "$BUILD_TEST_FLUX_WORKTREE" rev-parse HEAD)
git -C "$BUILD_TEST_FLUX_WORKTREE" push origin "HEAD:$BUILD_TEST_FLUX_BRANCH"
kubectl -n "$flux_namespace" annotate kustomization.kustomize.toolkit.fluxcd.io "$flux_kustomization" \
  "reconcile.fluxcd.io/requestedAt=$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite >/dev/null

deadline=$((SECONDS + 4500))
while (( SECONDS < deadline )); do
  flux_json=$(kubectl -n "$flux_namespace" get kustomization.kustomize.toolkit.fluxcd.io "$flux_kustomization" -o json) || unavailable "Flux status read during reconciliation"
  if printf '%s' "$flux_json" | jq -e --arg commit "$test_commit" '
    .metadata.generation == .status.observedGeneration and
    (.status.lastAppliedRevision // "" | endswith($commit)) and
    (.status.conditions // [] | any(.type == "Ready" and .status == "True"))
  ' >/dev/null; then break; fi
  sleep 5
done
(( SECONDS < deadline )) || { echo "Flux did not report the test revision Ready through BuildRun CEL health" >&2; exit 1; }

buildrun_json=$(kubectl -n "$namespace" get "buildrun/$buildrun" -o json) || { echo "Flux reported Ready without materializing $buildrun" >&2; exit 1; }
observed_commit=$(printf '%s' "$buildrun_json" | jq -r '.status.source.git.commitSha // empty')
reported_digest=$(printf '%s' "$buildrun_json" | jq -r '.status.output.digest // empty')
[[ $observed_commit == "$source_commit" ]] || { echo "built $observed_commit, expected $source_commit" >&2; exit 1; }
[[ $reported_digest =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "Shipwright did not report an image digest" >&2; exit 1; }
registry_digest=$(crane digest "$tag") || { echo "cannot read the pushed image from the registry" >&2; exit 1; }
[[ $registry_digest == "$reported_digest" ]] || { echo "registry has $registry_digest, Shipwright reported $reported_digest" >&2; exit 1; }
printf '%s@%s\n' "${tag%:*}" "$reported_digest"
