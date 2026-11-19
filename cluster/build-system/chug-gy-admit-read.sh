#!/bin/sh
# Step one of the site's admission: for each image of the site, the newest
# build that succeeded, and the digest it reports.
#
# The only step with a token for the API server, which is a projected volume
# mounted here and nowhere else in the pod. It reads TaskRuns in
# RUNS_NAMESPACE and writes regular files under OUT; what it finds is
# `$OUT/images`, and when it finds nothing it writes nothing and succeeds.
#
# AN IMAGE IS ONE LINE OF IMAGES: the container that runs it, its repository
# under REGISTRY, the repository its commit is of and the words a commit
# message names it by. A line of `$OUT/images` is the container, the
# repository, the digest, the commit, the run's name, and then the source and
# the words as IMAGES gave them, one per image that has a build which
# succeeded; an image with none is left out, and the others are still read.
#
# THE NEWEST RUN THAT SUCCEEDED, OF TASK FOR THAT IMAGE. A failed run is never
# read, and neither is one unfinished, so a newer commit whose build is running
# or failed leaves the last one that built; image-trigger.sh starts the next
# build and decides when. A run is newer by its creation.
#
# THE DIGEST IS THE RUN'S `digest` RESULT, as `sha256:<64 hex>`, and the commit
# its `commit` parameter, as forty hex; either not one is refused and nothing
# is written. Whether the registry holds the digest is not asked: a run reports
# one only after pushing it.
#
# WHO CAN FORGE A BUILD IS WHO CAN CREATE A TASKRUN IN RUNS_NAMESPACE, and
# nothing here tells a run the trigger started from one a person wrote, as
# worker-admit-read.sh says of its own.
set -eu

: "${RUNS_NAMESPACE:?}" "${TASK:?}" "${REGISTRY:?}" "${IMAGES:?}" "${OUT:?}"

say() {
  echo "chug-gy-admit: $*"
}

refuse() {
  echo "chug-gy-admit: $*" >&2
  exit 1
}

runs=$(kubectl --namespace "$RUNS_NAMESPACE" get taskruns.tekton.dev --output json)

found=''
entries=$(printf '%s\n' "$IMAGES" | awk 'NF')
[ -n "$entries" ] || refuse "IMAGES names no image"
while read -r container repository source words; do
  case $container/$repository/$source in
    *[!a-z0-9/._-]* | /* | *//* | */) refuse "IMAGES holds '$container $repository $source', which is not a container, a repository and a source" ;;
  esac
  [ -n "$words" ] || refuse "IMAGES names no words for $container"
  # The run's name, its commit and its digest, or nothing. A field with
  # nothing in it is `-`, so that splitting the line on spaces keeps place.
  chosen=$(printf '%s' "$runs" | jq -r --arg task "$TASK" --arg image "$REGISTRY/$repository" '
    def param($name): ((.spec.params // []) | map(select(.name == $name)) | .[0].value);
    def outcome: ((.status.conditions // []) | map(select(.type == "Succeeded")) | .[0].status // "");
    def result: ((.status.results // []) | map(select(.name == "digest")) | .[0].value // "");
    [ .items[]
      | select(.spec.taskRef.name == $task and param("image") == $image and outcome == "True")
      | { name: .metadata.name, created: .metadata.creationTimestamp,
          commit: (param("commit") // ""), digest: result } ]
    | sort_by(.created, .name)
    | .[-1] // empty
    | [.name, .commit, .digest]
    | map(if . == "" then "-" else . end)
    | if any(.[]; test("[ \t\n]")) then error("a field of the run holds whitespace: \(.)") else . end
    | join(" ")') || refuse "the runs of $REGISTRY/$repository could not be read"
  if [ -z "$chosen" ]; then
    say "$REGISTRY/$repository has no run of $TASK that succeeded: nothing to admit of it"
    continue
  fi
  # shellcheck disable=SC2086
  set -- $chosen
  run=$1 commit=$2 digest=$3
  case $digest in
    sha256:*) ;;
    *) refuse "$run reported '$digest', which is not a sha256 digest" ;;
  esac
  case ${digest#sha256:} in
    *[!0-9a-f]*) refuse "$run reported '$digest', which is not a sha256 digest" ;;
  esac
  [ "${#digest}" -eq 71 ] || refuse "$run reported '$digest', which is not a full sha256 digest"
  case $commit in
    *[!0-9a-f]*) refuse "$run was started for '$commit', which is not a commit hash" ;;
  esac
  [ "${#commit}" -eq 40 ] || refuse "$run was started for '$commit', which is not a full commit hash"
  say "$run built $REGISTRY/$repository at $commit: $digest"
  found="$found$container $repository $digest $commit $run $source $words
"
done <<ENTRIES
$entries
ENTRIES

if [ -z "$found" ]; then
  say "no image of the site has a build that succeeded: nothing to admit"
  exit 0
fi
mkdir -p "$OUT"
printf '%s' "$found" > "$OUT/images"
