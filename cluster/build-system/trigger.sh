#!/bin/sh
# Whether a run is started now, and the runs that are kept.
#
# A CronJob runs this each minute: `release-trigger` for a chuggy release and
# `site-trigger` for the site's. Each compares what two Flux sources hold, a
# source of what is built and a source of the manifests, with the newest run
# of its pipeline, and creates at most one run, from the run manifest beside
# it: release-run.yaml or site-run.yaml. Which sources, which pipeline and
# which manifest are the CronJob's environment, and so are the two annotations
# the comparison reads a run by.
#
# IT COMPARES, SO NOTHING IS MISSED. Nothing here waits for an event. A commit
# that landed while the node was down, a run that died with it and a cluster
# that has never run one all read the same at the next minute: the sources
# hold something the newest run did not release.
#
# ONE RUN AT A TIME. A run that has not finished is the whole answer, whatever
# it was started for. That is what lets a commit's image tag be written once
# and a version be taken in the order runs finish.
#
# A RUN THIS STARTED IS KEPT ONLY IF IT IS THE ONE UNFINISHED RUN. Reading the
# runs and creating one are two requests, so two of this script in the same
# moment each read none unfinished and each create one. The CronJob's `Forbid`
# does not rule that out: it holds a tick back for a Job the CronJob is
# tracking, and a person may create one from it at any time. So after creating
# its run this reads the runs again and deletes its own if another has not
# finished. Whichever was created second always finds the first. Both may
# delete, and then the next minute starts one.
#
# A RUN IS OF THE PIPELINE IF ITS `pipelineRef` SAYS SO. Tekton labels a run
# with its pipeline only once it has reconciled it, so a label would not show
# a run created a minute ago under a controller that is down, and the next
# minute would start a second.
#
# WHAT A RUN WAS STARTED FOR IS TWO ANNOTATIONS this script wrote on it: the
# commit of what is built, and the digest of the manifests source's artifact.
# The digest and not the manifests commit, because the commit moves with every
# push to the fabric and the digest only when a byte the source keeps does:
# for a release, the fabric's two release directories.
#
# RELEASED IS WHAT THE NEWEST RUN SAYS, AND THE REGISTRY IS NOT ASKED. A run
# that succeeded for what the sources hold is the end of it, whether or not
# the release it published is still where the source reads. That is what lets
# a release be undone by deleting it: the next minute does not publish it
# again. It is also why a registry that has lost its releases, or a source
# moved to a registry that never held them, is filled by nothing this does
# until a source holds something else or a person deletes the newest run.
#
# A FAILED RUN IS RETRIED AFTER RETRY_DELAY_SECONDS, for as long as the
# sources hold what it failed on, and at once when they hold something else.
# A person retries sooner by deleting the newest run.
#
# THEN IT KEEPS THE NEWEST KEEP_RUNS RUNS and deletes the finished ones
# before them, which nothing in this Tekton does. A run takes its TaskRuns and
# their pods with it.
#
# A SOURCE WITH NO ARTIFACT YET STARTS NOTHING AND IS NOT A FAILURE: it is
# what a cluster looks like before source-controller has fetched. A read the
# API server refuses is one.
set -eu

say() {
  echo "trigger: $*"
}

refuse() {
  echo "trigger: $*" >&2
  exit 1
}

: "${SOURCES_NAMESPACE:?}" "${SOURCE:?}" "${MANIFESTS_SOURCE:?}"
: "${RUNS_NAMESPACE:?}" "${PIPELINE:?}" "${RUN_MANIFEST:?}"
: "${COMMIT_ANNOTATION:?}" "${DIGEST_ANNOTATION:?}"
: "${RETRY_DELAY_SECONDS:?}" "${KEEP_RUNS:?}"

case $RETRY_DELAY_SECONDS$KEEP_RUNS in
  *[!0-9]*) refuse "RETRY_DELAY_SECONDS and KEEP_RUNS are counts" ;;
esac
[ "$KEEP_RUNS" -ge 1 ] || refuse "KEEP_RUNS of $KEEP_RUNS would delete the run the next comparison reads"

# The URL a source fetches, and the revision and digest of the artifact it
# holds, the last two empty until it holds one.
source_of() {
  kubectl --namespace "$SOURCES_NAMESPACE" get gitrepositories.source.toolkit.fluxcd.io "$1" \
    --output 'jsonpath={.spec.url}{"|"}{.status.artifact.revision}{"|"}{.status.artifact.digest}{"\n"}'
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

# Each read is an assignment of its own: a command substituted into a longer
# line fails without failing the line, and a read that failed would then be a
# source with no artifact, or a namespace with no runs.
built=$(source_of "$SOURCE")
manifests=$(source_of "$MANIFESTS_SOURCE")
IFS='|' read -r built_url built_revision _ <<EOF
$built
EOF
IFS='|' read -r manifests_url manifests_revision manifests_digest <<EOF
$manifests
EOF

# An annotation's key as a jsonpath names it: each dot escaped.
path_of() {
  printf '%s' "$1" | sed 's/\./\\./g'
}

# Every run in the namespace, a line each: when it was created, its name, its
# pipeline, whether it succeeded (`True`, `False`, or neither while it runs),
# when that was decided, and what it was started for.
list_runs() {
  kubectl --namespace "$RUNS_NAMESPACE" get pipelineruns.tekton.dev \
    --output "jsonpath={range .items[*]}{.metadata.creationTimestamp}{\"|\"}{.metadata.name}{\"|\"}{.spec.pipelineRef.name}{\"|\"}{.status.conditions[?(@.type==\"Succeeded\")].status}{\"|\"}{.status.conditions[?(@.type==\"Succeeded\")].lastTransitionTime}{\"|\"}{.metadata.annotations.$(path_of "$COMMIT_ANNOTATION")}{\"|\"}{.metadata.annotations.$(path_of "$DIGEST_ANNOTATION")}{\"\n\"}{end}"
}

# The runs of the pipeline among those lines, oldest first.
of_the_pipeline() {
  printf '%s\n' "$1" | awk -F '|' -v pipeline="$PIPELINE" '$3 == pipeline' | LC_ALL=C sort
}

# The names of the runs among those lines that have not finished.
unfinished_of() {
  printf '%s\n' "$1" | awk -F '|' 'NF && $4 != "True" && $4 != "False" { print $2 }'
}

listed=$(list_runs)
runs=$(of_the_pipeline "$listed")

start() {
  for value in "$built_url" "$manifests_url"; do
    case $value in
      *[!A-Za-z0-9:/._-]*) refuse "source address '$value' is not one this writes into a manifest" ;;
    esac
  done
  case $manifests_digest in
    *[!a-z0-9:]*) refuse "digest '$manifests_digest' is not one this writes into a manifest" ;;
  esac
  created=$(sed \
    -e "s|@source-url@|$built_url|g" \
    -e "s|@source-commit@|$built_commit|g" \
    -e "s|@manifests-url@|$manifests_url|g" \
    -e "s|@manifests-commit@|$manifests_commit|g" \
    -e "s|@manifests-digest@|$manifests_digest|g" \
    "$RUN_MANIFEST" | kubectl create --filename - --output name)
  created=${created##*/}
  say "started $created"

  listed=$(list_runs)
  runs=$(of_the_pipeline "$listed")
  others=$(unfinished_of "$runs" | awk -v created="$created" '$0 != created')
  if [ -n "$others" ]; then
    kubectl --namespace "$RUNS_NAMESPACE" delete pipelineruns.tekton.dev --wait=false "$created"
    say "$(echo $others) had not finished either: $created is deleted, and the next minute decides again"
    runs=$(printf '%s\n' "$runs" | awk -F '|' -v created="$created" '$2 != created')
  fi
}

if [ -z "$built_revision" ] || [ -z "$manifests_digest" ]; then
  say "a source holds no artifact yet ($SOURCE '$built_revision', $MANIFESTS_SOURCE '$manifests_revision'): nothing is started"
else
  built_commit=$(commit_of "$built_revision")
  manifests_commit=$(commit_of "$manifests_revision")
  unfinished=$(unfinished_of "$runs")
  IFS='|' read -r _ newest _ succeeded decided for_commit for_digest <<EOF
$(printf '%s\n' "$runs" | tail -n 1)
EOF
  if [ -n "$unfinished" ]; then
    say "$(echo $unfinished) has not finished: nothing is started"
  elif [ "$for_commit" != "$built_commit" ] || [ "$for_digest" != "$manifests_digest" ]; then
    say "the sources hold $SOURCE $built_commit and manifests $manifests_digest, and the newest run ${newest:-(there is none)} was started for '$for_commit' and '$for_digest'"
    start
  elif [ "$succeeded" = True ]; then
    say "$newest released $SOURCE $built_commit and manifests $manifests_digest: nothing is started"
  else
    retry_after=$(date -u -d "@$(($(date +%s) - RETRY_DELAY_SECONDS))" +%Y-%m-%dT%H:%M:%SZ)
    if awk -v decided="$decided" -v after="$retry_after" 'BEGIN { exit !(decided "" > after "") }'; then
      say "$newest failed on these at $decided, inside the retry delay: nothing is started"
    else
      say "$newest failed on these at $decided: retrying"
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
      if (field[4] == "True" || field[4] == "False") print field[2]
    }
  }')
if [ -n "$expired" ]; then
  # shellcheck disable=SC2086
  kubectl --namespace "$RUNS_NAMESPACE" delete pipelineruns.tekton.dev --wait=false $expired
fi
