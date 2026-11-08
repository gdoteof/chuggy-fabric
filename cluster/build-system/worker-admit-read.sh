#!/bin/sh
# Step one of the worker admission: which pair of builds, if any, is to be
# admitted, and the digests they report.
#
# The only step with a token for the API server, which is a projected volume
# mounted here and nowhere else in the pod. It reads TaskRuns in
# RUNS_NAMESPACE and writes regular files under OUT; a pair it finds is
# `$OUT/pair.env`, and when there is none it writes nothing and succeeds.
#
# A PAIR IS THE TWO RUNS OF ONE INPUTS DIGEST. worker-image-trigger.yaml starts
# a run of the worker and a run of the runtime for each digest of the worker's
# inputs and writes it on the run as ANNOTATION, and a release is those two
# built from one set of inputs. Of the runs of TASK that carry the annotation
# and are of WORKER_IMAGE or RUNTIME_IMAGE, the pair is the newest run of each
# image among those with the annotation of the newest run of all.
#
# ONLY THE NEWEST INPUTS ARE CONSIDERED. An older pair that was never admitted
# was overtaken, and admitting it would offer a worker newer inputs have
# already replaced. The newest inputs with a build unfinished or failed admit
# nothing, and a failed build is retried by its trigger.
#
# THE DIGESTS ARE THE RUNS' `digest` RESULTS, as `sha256:<64 hex>`; a result
# that is not one is refused and nothing is written. Whether the registry
# holds them is not asked: a run reports a digest only after pushing it.
# The commit is the worker run's `commit` parameter.
#
# WHO CAN FORGE A PAIR IS WHO CAN CREATE A TASKRUN IN RUNS_NAMESPACE, and
# nothing here tells a run the trigger started from one a person wrote: a run
# there is trusted as far as that namespace's RBAC, which worker-admit.yaml
# says is the triggers and the cluster's administrators.
set -eu

: "${RUNS_NAMESPACE:?}" "${TASK:?}" "${WORKER_IMAGE:?}" "${RUNTIME_IMAGE:?}" "${ANNOTATION:?}" "${OUT:?}"

say() {
  echo "worker-admit: $*"
}

refuse() {
  echo "worker-admit: $*" >&2
  exit 1
}

runs=$(kubectl --namespace "$RUNS_NAMESPACE" get taskruns.tekton.dev --output json)

# One line: the inputs digest, then for the worker and the runtime the run's
# name, its commit, whether it succeeded and its digest; or nothing. A field
# with nothing in it is `-`, so that splitting the line on spaces keeps place.
chosen=$(printf '%s' "$runs" | jq -r \
  --arg task "$TASK" --arg worker "$WORKER_IMAGE" --arg runtime "$RUNTIME_IMAGE" --arg annotation "$ANNOTATION" '
  def param($name): ((.spec.params // []) | map(select(.name == $name)) | .[0].value);
  def outcome: ((.status.conditions // []) | map(select(.type == "Succeeded")) | .[0].status // "");
  def result: ((.status.results // []) | map(select(.name == "digest")) | .[0].value // "");
  [ .items[]
    | select(.spec.taskRef.name == $task)
    | select(((.metadata.annotations // {})[$annotation]) != null)
    | { name: .metadata.name, created: .metadata.creationTimestamp,
        inputs: .metadata.annotations[$annotation],
        image: param("image"), commit: (param("commit") // ""), outcome: outcome, digest: result }
    | select(.image == $worker or .image == $runtime) ]
  | sort_by(.created, .name)
  | if length == 0 then empty else
      (.[-1].inputs) as $inputs
      | map(select(.inputs == $inputs)) as $group
      | ([$group[] | select(.image == $worker)] | .[-1]) as $w
      | ([$group[] | select(.image == $runtime)] | .[-1]) as $r
      | [$inputs,
         ($w.name // ""), ($w.commit // ""), ($w.outcome // ""), ($w.digest // ""),
         ($r.name // ""), ($r.commit // ""), ($r.outcome // ""), ($r.digest // "")]
      | map(if . == "" then "-" else . end)
      | if any(.[]; test("[ \t\n]")) then error("a field of the runs holds whitespace: \(.)") else . end
      | join(" ")
    end') || refuse "the runs could not be read as a pair"

if [ -z "$chosen" ]; then
  say "no run of $TASK carries $ANNOTATION: nothing to admit"
  exit 0
fi

# shellcheck disable=SC2086
set -- $chosen
inputs=$1 worker_run=${2:-} commit=${3:-} worker_outcome=${4:-} worker_digest=${5:-}
runtime_run=${6:-} runtime_outcome=${8:-} runtime_digest=${9:-}

if [ "$worker_run" = - ] || [ "$runtime_run" = - ]; then
  say "$inputs has a run of one image and none of the other: nothing to admit"
  exit 0
fi
if [ "$worker_outcome" != True ] || [ "$runtime_outcome" != True ]; then
  say "$inputs: $worker_run is '$worker_outcome' and $runtime_run is '$runtime_outcome': nothing to admit"
  exit 0
fi

hash_of() {
  case $1 in
    sha256:*) ;;
    *) refuse "$2 reported '$1', which is not a sha256 digest" ;;
  esac
  case ${1#sha256:} in
    *[!0-9a-f]*) refuse "$2 reported '$1', which is not a sha256 digest" ;;
  esac
  [ "${#1}" -eq 71 ] || refuse "$2 reported '$1', which is not a full sha256 digest"
}
case $inputs in
  *[!A-Za-z0-9:._-]* | -) refuse "the annotation $ANNOTATION is '$inputs', which is not a digest" ;;
esac
hash_of "$worker_digest" "$worker_run"
hash_of "$runtime_digest" "$runtime_run"
case $commit in
  *[!0-9a-f]* | "") refuse "$worker_run was started for '$commit', which is not a commit hash" ;;
esac
[ "${#commit}" -eq 40 ] || refuse "$worker_run was started for '$commit', which is not a full commit hash"

mkdir -p "$OUT"
cat > "$OUT/pair.env" <<PAIR
INPUTS=$inputs
COMMIT=$commit
WORKER_DIGEST=$worker_digest
RUNTIME_DIGEST=$runtime_digest
PAIR
say "$inputs: $worker_run and $runtime_run succeeded: $worker_digest and $runtime_digest"
