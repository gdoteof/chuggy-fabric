#!/bin/sh
# The change that admits a worker release, written from what its builds
# reported: usage
# `admit-worker.sh FILE COMMIT WORKER_DIGEST RUNTIME_DIGEST [PLANE_FILE CHAT_DIGEST]`.
#
# FILE is cluster/chuggy/chuggy-scheduler.yaml. COMMIT is the chuggy commit the
# builds were started for. The digests are the `digest` results of the runs of
# worker-image-run.yaml and worker-runtime-image-run.yaml for one inputs digest,
# as `sha256:<64 hex>`. The file is rewritten in place and the diff is printed;
# MESSAGE_FILE, where set, is given the commit message.
#
# THE CHAT IMAGE MOVES WITH THE WORKER WHERE THE LAST TWO ARE GIVEN. PLANE_FILE
# is cluster/chuggy/chuggy-pool-plane.yaml and CHAT_DIGEST the result of the
# run of chat-image-run.yaml for the same inputs: CHUG_POOL_PLANE_CHAT_IMAGE
# there is moved to it, so a chat host's core is the worker's. A plane file
# that does not name exactly one chat image is refused before anything is
# written, and one that already names the digest is left as it is.
#
# IN FILE IT WRITES WHAT THE MANUAL COMMITS DID, and nothing else: in
# CHUG_SCHEDULER_OFFERED_IMAGES one entry appended, last, as `chuggy-worker`
# at the next version after the highest the list holds, for the worker digest;
# the `image` of CHUG_SCHEDULER_SESSION_POLICY moved to that digest; and
# CHUG_SCHEDULER_WORKER_RUNTIME moved to the runtime digest.
#
# LAST, BECAUSE OFFER ORDER IS RELEASE ORDER. The scheduler resolves a
# capability to the last entry publishing it, and `generic-worker` sits before
# the newest `chuggy-worker` so that it takes no capability task;
# tests/session-placement.py refuses an order that hands it any. An entry
# appended at the end keeps that, and the version is the next in the sequence
# of `chuggy-worker` versions, `0.<n>`, which is assigned here when an image is
# first offered and never afterwards.
#
# THE FILE IS READ AS THE LINES IT IS, not as YAML: the scheduler's variables
# are JSON documents inside block scalars, and a YAML round trip would rewrite
# everything around them. An entry is `image`, `name` and `version` on lines of
# that order, as every entry in the file is, and the three places are found by
# the variable names above. A file that is not that shape is refused and left as
# it was, and so is a result in which any of the three places was not changed
# exactly once.
#
# REFUSED, NOT REPAIRED: a digest already offered under any name, which is a
# worker admitted twice or a runtime digest given as the worker's; a worker
# whose digest is the newest `chuggy-worker` entry, which is exited 0 with
# nothing written if the session policy, the runtime and the chat image where
# one is given already name the digests given, so that a run of this that
# already landed is not repeated.
#
# WHO RUNS IT: the CronJob of worker-admit.yaml, from a fresh checkout of
# `main`, on the newest pair worker-admit-read.sh finds; or a person, by hand,
# on a branch. The pull request is opened and merged by a GitHub App of its own,
# which worker-admit.yaml's header says the owner creates.
#
# NOT HANDLED: that a registry holds the digests, or that they are those of the
# runs of one inputs digest: worker-admit-read.sh chooses them, and nothing
# here can tell a digest from the right run from one from another. A worker
# that landed without its chat image is refused, not completed: the chat image
# is then a person's to write.
set -eu

refuse() {
  echo "admit-worker: $*" >&2
  exit 1
}

case $# in
  4 | 6) ;;
  *) refuse "usage: admit-worker.sh FILE COMMIT WORKER_DIGEST RUNTIME_DIGEST [PLANE_FILE CHAT_DIGEST]" ;;
esac
file=$1
commit=$2
worker=$3
runtime=$4
plane=${5:-}
chat=${6:-}

[ -f "$file" ] || refuse "$file is not a file"
[ "$#" -eq 4 ] || [ -f "$plane" ] || refuse "$plane is not a file"
case $commit in
  *[!0-9a-f]* | "") refuse "commit '$commit' is not a full commit hash" ;;
esac
[ "${#commit}" -eq 40 ] || refuse "commit '$commit' is not a full commit hash"
for digest in "$worker" "$runtime" ${plane:+"$chat"}; do
  case $digest in
    sha256:*) ;;
    *) refuse "digest '$digest' is not sha256:<64 hex>" ;;
  esac
  case ${digest#sha256:} in
    *[!0-9a-f]*) refuse "digest '$digest' is not sha256:<64 hex>" ;;
  esac
  [ "${#digest}" -eq 71 ] || refuse "digest '$digest' is not sha256:<64 hex>"
done

# What the file holds now, as `key value` lines: the highest chuggy-worker
# version, the newest chuggy-worker image's digest, the session policy's and
# the runtime's, and every digest offered under any name. A variable's block
# ends at the next list item of the container's `env`.
held=$(awk '
  /^ *- name: / { block = $3; next }
  block == "CHUG_SCHEDULER_OFFERED_IMAGES" {
    if (match($0, /"image": "[^"]*@sha256:[0-9a-f]+"/)) {
      image = substr($0, RSTART, RLENGTH); sub(/.*@/, "", image); sub(/"$/, "", image)
      print "offered", image
    } else if ($0 ~ /"name": "chuggy-worker"/) {
      newest_image = image
    } else if (match($0, /"version": "[^"]*"/)) {
      version = substr($0, RSTART, RLENGTH); sub(/.*: "/, "", version); sub(/"$/, "", version)
      if (newest_image != "") { print "version", version; print "newest", newest_image; newest_image = "" }
    }
  }
  block == "CHUG_SCHEDULER_SESSION_POLICY" && match($0, /"image": "[^"]*@sha256:[0-9a-f]+"/) {
    image = substr($0, RSTART, RLENGTH); sub(/.*@/, "", image); sub(/"$/, "", image)
    print "policy", image
  }
  block == "CHUG_SCHEDULER_WORKER_RUNTIME" && match($0, /@sha256:[0-9a-f]+/) {
    print "runtime", substr($0, RSTART + 1, RLENGTH - 1)
  }
' "$file")

count_of() {
  printf '%s\n' "$held" | awk -v key="$1" '$1 == key' | wc -l | tr -d ' '
}

[ "$(count_of policy)" -eq 1 ] || refuse "$file does not hold exactly one session policy image"
[ "$(count_of runtime)" -eq 1 ] || refuse "$file does not hold exactly one worker runtime"
[ "$(count_of newest)" -ge 1 ] || refuse "$file offers no chuggy-worker, and the next version has nothing to follow"

# The chat image the plane file names, one line a place that names one.
chat_held=
if [ -n "$plane" ]; then
  chat_held=$(awk '
    /^ *- name: / { block = $3; next }
    block == "CHUG_POOL_PLANE_CHAT_IMAGE" && match($0, /@sha256:[0-9a-f]+/) {
      print substr($0, RSTART + 1, RLENGTH - 1)
    }
  ' "$plane")
  [ "$(printf '%s\n' "$chat_held" | awk 'NF { count++ } END { print count + 0 }')" -eq 1 ] ||
    refuse "$plane does not hold exactly one chat image"
fi

policy=$(printf '%s\n' "$held" | awk '$1 == "policy" { print $2 }')
current_runtime=$(printf '%s\n' "$held" | awk '$1 == "runtime" { print $2 }')
newest=$(printf '%s\n' "$held" | awk '$1 == "newest" { digest = $2 } END { print digest }')

if [ "$newest" = "$worker" ]; then
  if [ "$policy" = "$worker" ] && [ "$current_runtime" = "$runtime" ] && [ "$chat_held" = "$chat" ]; then
    echo "admit-worker: $file already offers $worker and runs on it: nothing is written"
    exit 0
  fi
  refuse "the newest chuggy-worker is already $worker, and the session policy, the runtime or the chat image names others"
fi
if printf '%s\n' "$held" | awk -v digest="$worker" '$1 == "offered" && $2 == digest { found = 1 } END { exit !found }'; then
  refuse "$worker is already offered, and not as the newest chuggy-worker"
fi
if printf '%s\n' "$held" | awk -v digest="$runtime" '$1 == "offered" && $2 == digest { found = 1 } END { exit !found }'; then
  refuse "the runtime digest $runtime is a worker image already offered"
fi

# Every chuggy-worker version is `0.<n>`, and the next is one more than the
# highest, compared as numbers.
versions=$(printf '%s\n' "$held" | awk '$1 == "version" { print $2 }')
highest=-1
for version in $versions; do
  case $version in
    0.*[!0-9]* | 0.) refuse "chuggy-worker version '$version' is not 0.<n>" ;;
    0.*) ;;
    *) refuse "chuggy-worker version '$version' is not 0.<n>" ;;
  esac
  [ "${version#0.}" -le "$highest" ] || highest=${version#0.}
done
next="0.$((highest + 1))"

rewritten=$(mktemp)
trap 'rm -f "$rewritten" "$rewritten.before" "$rewritten.plane"' EXIT
awk -v worker="$worker" -v runtime="$runtime" -v version_next="$next" '
  function indent(line) { match(line, /^ */); return substr(line, 1, RLENGTH) }
  function flush() { if (pending != "") { print pending; pending = "" } }
  /^ *- name: / { flush(); block = $3 }
  block == "CHUG_SCHEDULER_OFFERED_IMAGES" {
    if ($0 ~ /^ *}$/) { flush(); pending = $0; next }
    if ($0 ~ /^ *\]$/ && pending != "") {
      pad = indent(pending)
      print pad "},"
      print pad "{"
      print pad "  \"image\": \"registry.chuggy.internal/chuggy/worker@" worker "\","
      print pad "  \"name\": \"chuggy-worker\","
      print pad "  \"version\": \"" version_next "\","
      print pad "  \"operatingSystem\": \"Linux\","
      print pad "  \"architecture\": \"Amd64\","
      print pad "  \"capabilities\": [\"Agent:Claude\", \"Agent:Codex\"]"
      print pad "}"
      pending = ""
      appended++
      print
      next
    }
    flush()
  }
  block == "CHUG_SCHEDULER_SESSION_POLICY" && /"image": "[^"]*@sha256:[0-9a-f]+"/ {
    sub(/@sha256:[0-9a-f]+/, "@" worker); changed_policy++
  }
  block == "CHUG_SCHEDULER_WORKER_RUNTIME" && /@sha256:[0-9a-f]+/ {
    sub(/@sha256:[0-9a-f]+/, "@" runtime); changed_runtime++
  }
  { flush(); print }
  END {
    flush()
    if (appended != 1 || changed_policy != 1 || changed_runtime != 1) {
      print "admit-worker: appended " appended + 0 ", moved the session policy " changed_policy + 0 " times and the runtime " changed_runtime + 0 " times, not once each" > "/dev/stderr"
      exit 1
    }
  }
' "$file" > "$rewritten" || refuse "$file is not the shape this rewrites, and is left as it was"

if cmp -s "$file" "$rewritten"; then
  refuse "the rewrite changed nothing"
fi
if [ "$chat_held" != "$chat" ]; then
  awk -v chat="$chat" '
    /^ *- name: / { block = $3 }
    block == "CHUG_POOL_PLANE_CHAT_IMAGE" && /@sha256:[0-9a-f]+/ { sub(/@sha256:[0-9a-f]+/, "@" chat); changed++ }
    { print }
    END { if (changed != 1) exit 1 }
  ' "$plane" > "$rewritten.plane" || refuse "$plane is not the shape this rewrites, and both files are left as they were"
fi

# over FILE: its rewrite is written over it, and the diff printed.
over() {
  cp "$1" "$rewritten.before"
  cat "$2" > "$1"
  diff -u "$rewritten.before" "$1" | sed -e "1s|.*|--- a/$1|" -e "2s|.*|+++ b/$1|" || true
}
over "$file" "$rewritten"
[ "$chat_held" = "$chat" ] || over "$plane" "$rewritten.plane"

if [ -n "${MESSAGE_FILE:-}" ]; then
  cat > "$MESSAGE_FILE" <<MESSAGE
Admit worker $next, and run sessions and chat on it

Worker $next is chuggy $commit, built from the worker's inputs by the
worker image trigger.

worker   $worker
runtime  $runtime
${plane:+chat     $chat
}
The session policy runs on the worker, and CHUG_SCHEDULER_WORKER_RUNTIME is the
runtime.${plane:+ CHUG_POOL_PLANE_CHAT_IMAGE is the chat image.}
MESSAGE
fi
