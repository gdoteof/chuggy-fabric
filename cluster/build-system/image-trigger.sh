#!/bin/sh
# Whether a build of one image is started now, and the builds that are kept.
#
# A CronJob of the image runs this each minute: `chug-gy-image-trigger` for
# the site's. It compares what one Flux source holds with the newest build of
# the image and creates at most one TaskRun, from the run manifest beside it.
# It is trigger.sh over one source and one Task instead of two sources and a
# Pipeline, and each rule below that trigger.sh also has is argued there.
#
# IT COMPARES, SO NOTHING IS MISSED. Nothing here waits for an event. A commit
# that landed while the node was down, a run that died with it and a cluster
# that has never built the image all read the same at the next minute: the
# source holds a commit the newest run did not build.
#
# ONE BUILD OF THE IMAGE AT A TIME. A run that has not finished is the whole
# answer, whatever commit it was started for. build.sh takes a tag the
# registry already serves as that commit's image and builds only when there is
# none, which holds only while nothing else builds the same commit of the same
# image; this is what keeps it.
#
# A RUN IS OF THE IMAGE IF ITS `taskRef` NAMES THE TASK AND ITS `image`
# PARAMETER NAMES THE IMAGE. Tekton labels a run with its Task only once it
# has reconciled it, and a release run's own TaskRuns are of the same Task for
# other images. A TaskRun of another Task, or of this Task for another image,
# is neither unfinished nor newest nor deleted here.
#
# WHAT A RUN WAS STARTED FOR IS ITS `commit` PARAMETER, which is what the Task
# builds and tags by. Nothing more is written on the run.
#
# BUILT IS WHAT THE NEWEST RUN SAYS, AND THE REGISTRY IS NOT ASKED. A run that
# succeeded for the commit the source holds is the end of it. A registry that
# has lost the image is filled by nothing this does until the source holds
# another commit or a person deletes the newest run.
#
# A FAILED RUN IS RETRIED AFTER RETRY_DELAY_SECONDS, for as long as the source
# holds the commit it failed on, and at once when it holds another. A person
# retries sooner by deleting the newest run.
#
# A RUN THIS STARTED IS KEPT ONLY IF IT IS THE ONE UNFINISHED RUN of the
# image, for the reason trigger.sh gives: two of this in one moment each read
# none unfinished and each create one, and whichever was created second
# always finds the first.
#
# THEN IT KEEPS THE NEWEST KEEP_RUNS RUNS OF THE IMAGE and deletes the finished
# ones before them, which nothing in this Tekton does. A run takes its pod
# with it. What its token can delete is any TaskRun in the namespace, a
# release run's among them; what this deletes is a finished run of this image.
#
# A SOURCE WITH NO ARTIFACT YET STARTS NOTHING AND IS NOT A FAILURE. A read the
# API server refuses is one.
set -eu

say() {
  echo "trigger: $*"
}

refuse() {
  echo "trigger: $*" >&2
  exit 1
}

: "${SOURCES_NAMESPACE:?}" "${SOURCE:?}" "${RUNS_NAMESPACE:?}" "${TASK:?}" "${IMAGE:?}"
: "${RUN_MANIFEST:?}" "${RETRY_DELAY_SECONDS:?}" "${KEEP_RUNS:?}"

case $RETRY_DELAY_SECONDS$KEEP_RUNS in
  *[!0-9]*) refuse "RETRY_DELAY_SECONDS and KEEP_RUNS are counts" ;;
esac
[ "$KEEP_RUNS" -ge 1 ] || refuse "KEEP_RUNS of $KEEP_RUNS would delete the run the next comparison reads"

# The URL the source fetches and the revision of the artifact it holds, the
# second empty until it holds one.
source_of() {
  kubectl --namespace "$SOURCES_NAMESPACE" get gitrepositories.source.toolkit.fluxcd.io "$1" \
    --output 'jsonpath={.spec.url}{"|"}{.status.artifact.revision}{"\n"}'
}

# The commit of a revision Flux writes as `<branch>@sha1:<commit>`.
commit_of() {
  case $1 in
    *@sha1:*) ;;
    *) refuse "revision '$1' is not a branch and a commit" ;;
  esac
  commit=${1##*@sha1:}
  case $commit in
    *[!0-9a-f]*) refuse "revision '$1' names no commit hash" ;;
  esac
  [ "${#commit}" -eq 40 ] || refuse "revision '$1' names no full commit hash"
  printf '%s\n' "$commit"
}

# The read is an assignment of its own: a command substituted into a longer
# line fails without failing the line, and a read that failed would then be a
# source with no artifact.
held=$(source_of "$SOURCE")
IFS='|' read -r url revision <<EOF
$held
EOF

# Every TaskRun in the namespace, a line each: when it was created, its name,
# its Task, the image it was given, whether it succeeded (`True`, `False`, or
# neither while it runs), when that was decided, and the commit it was given.
list_runs() {
  kubectl --namespace "$RUNS_NAMESPACE" get taskruns.tekton.dev \
    --output 'jsonpath={range .items[*]}{.metadata.creationTimestamp}{"|"}{.metadata.name}{"|"}{.spec.taskRef.name}{"|"}{.spec.params[?(@.name=="image")].value}{"|"}{.status.conditions[?(@.type=="Succeeded")].status}{"|"}{.status.conditions[?(@.type=="Succeeded")].lastTransitionTime}{"|"}{.spec.params[?(@.name=="commit")].value}{"\n"}{end}'
}

# The runs of the image among those lines, oldest first.
of_the_image() {
  printf '%s\n' "$1" | awk -F '|' -v task="$TASK" -v image="$IMAGE" '$3 == task && $4 == image' | LC_ALL=C sort
}

# The names of the runs among those lines that have not finished.
unfinished_of() {
  printf '%s\n' "$1" | awk -F '|' 'NF && $5 != "True" && $5 != "False" { print $2 }'
}

listed=$(list_runs)
runs=$(of_the_image "$listed")

start() {
  case $url in
    *[!A-Za-z0-9:/._-]*) refuse "source address '$url' is not one this writes into a manifest" ;;
  esac
  created=$(sed \
    -e "s|@source-url@|$url|g" \
    -e "s|@source-commit@|$commit|g" \
    "$RUN_MANIFEST" | kubectl create --filename - --output name)
  created=${created##*/}
  say "started $created"

  listed=$(list_runs)
  runs=$(of_the_image "$listed")
  others=$(unfinished_of "$runs" | awk -v created="$created" '$0 != created')
  if [ -n "$others" ]; then
    kubectl --namespace "$RUNS_NAMESPACE" delete taskruns.tekton.dev --wait=false "$created"
    say "$(echo $others) had not finished either: $created is deleted, and the next minute decides again"
    runs=$(printf '%s\n' "$runs" | awk -F '|' -v created="$created" '$2 != created')
  fi
}

if [ -z "$revision" ]; then
  say "$SOURCE holds no artifact yet: nothing is started"
else
  commit=$(commit_of "$revision")
  unfinished=$(unfinished_of "$runs")
  IFS='|' read -r _ newest _ _ succeeded decided for_commit <<EOF
$(printf '%s\n' "$runs" | tail -n 1)
EOF
  if [ -n "$unfinished" ]; then
    say "$(echo $unfinished) has not finished: nothing is started"
  elif [ "$for_commit" != "$commit" ]; then
    say "$SOURCE holds $commit, and the newest run of $IMAGE ${newest:-(there is none)} was started for '$for_commit'"
    start
  elif [ "$succeeded" = True ]; then
    say "$newest built $IMAGE at $commit: nothing is started"
  else
    retry_after=$(date -u -d "@$(($(date +%s) - RETRY_DELAY_SECONDS))" +%Y-%m-%dT%H:%M:%SZ)
    if awk -v decided="$decided" -v after="$retry_after" 'BEGIN { exit !(decided "" > after "") }'; then
      say "$newest failed on $commit at $decided, inside the retry delay: nothing is started"
    else
      say "$newest failed on $commit at $decided: retrying"
      start
    fi
  fi
fi

# Oldest first, so everything before the last KEEP_RUNS lines is older than
# every run kept. A run that has not finished is never deleted, wherever it
# sorts.
expired=$(printf '%s\n' "$runs" | awk -F '|' -v keep="$KEEP_RUNS" '
  NF { line[++count] = $0 }
  END {
    for (i = 1; i <= count - keep; i++) {
      split(line[i], field, "|")
      if (field[5] == "True" || field[5] == "False") print field[2]
    }
  }')
if [ -n "$expired" ]; then
  # shellcheck disable=SC2086
  kubectl --namespace "$RUNS_NAMESPACE" delete taskruns.tekton.dev --wait=false $expired
fi
