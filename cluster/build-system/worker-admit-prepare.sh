#!/bin/sh
# Step two of the worker admission: the change, made in a fresh checkout and
# held to the placement checks.
#
# It runs after worker-admit-read.sh, with no token of any kind. It reads
# `$IN/pair.env` as data, checks out FABRIC_URL's BRANCH afresh, runs the
# checkout's own admit-worker.sh over the scheduler file, renders the cluster
# the way tests/rendered-cluster.nix does and runs tests/session-placement.py
# over it. A step that fails fails the pod, and the step after it, which is the
# one with the GitHub token, is never started.
#
# WHAT IT LEAVES under `$OUT` IS ALL THE NEXT STEP READS, as regular files: the
# branch name, the commit message, the changed file's path and new content, the
# blob and the commit it was made against, and a `ready` marker written last.
# When there is nothing to admit it leaves nothing, and succeeds.
#
# NOTHING TO ADMIT is no pair, or a worker digest the checkout's scheduler file
# already holds: a pair that landed, whoever landed it, is not admitted again.
#
# THE BRANCH IS NAMED FOR THE WORKER DIGEST, `admit/worker-<12 hex>`, so the
# same pair is the same branch: that is what lets the next step count a branch
# or a pull request already there.
#
# WHAT IT RUNS IS THE CHECKOUT'S OWN: admit-worker.sh and session-placement.py
# as they are on BRANCH, which is reviewed code, and kubectl's offline
# `kustomize`. Run with no token and no route to the API server, and the next
# step reads their output as files only.
set -eu

: "${IN:?}" "${OUT:?}" "${FABRIC_URL:?}" "${BRANCH:?}" "${CHECKOUT:?}" "${SCHEDULER:?}"

say() {
  echo "worker-admit: $*"
}

refuse() {
  echo "worker-admit: $*" >&2
  exit 1
}

[ -f "$IN/pair.env" ] || { say "no pair to admit"; exit 0; }

# The file is three lines of a form this wrote; it is read, not sourced.
value_of() {
  sed -n "s/^$1=//p" "$IN/pair.env" | head -n 1
}
commit=$(value_of COMMIT)
worker=$(value_of WORKER_DIGEST)
runtime=$(value_of RUNTIME_DIGEST)
for digest in "$worker" "$runtime"; do
  case $digest in
    sha256:*) ;;
    *) refuse "pair.env holds '$digest', which is not a sha256 digest" ;;
  esac
  case ${digest#sha256:} in
    *[!0-9a-f]*) refuse "pair.env holds '$digest', which is not a sha256 digest" ;;
  esac
done

rm -rf "$CHECKOUT"
git clone --quiet --depth 1 --no-tags --branch "$BRANCH" "$FABRIC_URL" "$CHECKOUT"
cd "$CHECKOUT"
base=$(git rev-parse HEAD)

if grep -F "$worker" "$SCHEDULER" > /dev/null; then
  say "$worker is already in $SCHEDULER at $base: nothing to admit"
  exit 0
fi

blob=$(git rev-parse "HEAD:$SCHEDULER")
MESSAGE_FILE=$CHECKOUT/.admit-message sh cluster/build-system/admit-worker.sh "$SCHEDULER" "$commit" "$worker" "$runtime"

changed=$(git status --porcelain --untracked-files=no)
[ "$changed" = " M $SCHEDULER" ] || refuse "the rewrite changed '$changed', not only $SCHEDULER"

# The cluster as the checks read it: every directory that declares the
# cluster's own objects, as one stream.
: > "$CHECKOUT/.cluster.yaml"
for directory in apps track-record chug-gy chuggy-migrate chuggy; do
  kubectl kustomize "cluster/$directory" >> "$CHECKOUT/.cluster.yaml"
  echo '---' >> "$CHECKOUT/.cluster.yaml"
done
python3 tests/session-placement.py "$CHECKOUT/.cluster.yaml"

version=$(sed -n '1s/^Admit worker \([0-9.]*\),.*/\1/p' "$CHECKOUT/.admit-message")
[ -n "$version" ] || refuse "the commit message names no version"
mkdir -p "$OUT"
cp "$SCHEDULER" "$OUT/content"
cp "$CHECKOUT/.admit-message" "$OUT/message"
printf '%s' "admit/worker-$(printf '%s' "${worker#sha256:}" | cut -c1-12)" > "$OUT/branch"
printf '%s' "$SCHEDULER" > "$OUT/path"
printf '%s' "$blob" > "$OUT/blob"
printf '%s' "$base" > "$OUT/base"
printf '%s' "$version" > "$OUT/version"
printf '%s' "$BRANCH" > "$OUT/target"
touch "$OUT/ready"
say "worker $version is ready on $base"
