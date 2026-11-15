#!/bin/sh
# The worker contract of one chuggy commit, packed and checked, or nothing to do.
#
# The second step of `publish-worker-contract`: it runs what the commit says,
# and so it holds no credential. `npm ci` and the publish script are the
# commit's own code. What it hands the next step is a tarball, in a directory
# that step reads, the title it is released under, and the tag, written last.
#
# NOTHING TO DO IS SUCCESS. A commit whose `src/contract` is the tree the newest
# release was made from has nothing to release, and neither has the commit that
# release is tagged at, which is a commit the trigger started a second run for.
# Neither writes `tag`, and the release step then does nothing. Every commit of
# chuggy's `main` is run through here, so a commit that is not a release has to
# be the usual case and not a failure.
#
# THE RELEASE IS CHOSEN HERE AND NOT READ FROM THE COMMIT. chuggy's source
# names the version of its wire, which a change to the contract does not move,
# and no label for its package. The label is the minor after the newest
# `worker-contract-v<release>` tag the remote holds, with patch 0, and the
# script is told it with `--release`. Tags of any other form are not counted.
# A remote with no such tag is a failure: there is nothing to number from.
#
# WHETHER THE CONTRACT MOVED IS A COMPARISON OF TWO TREES, this commit's
# `src/contract` and the one at the newest release's commit, which is fetched
# for it. So it is decided before `npm ci`, the slow part. A change to how the
# pack is built that leaves `src/contract` alone is not a release.
#
# IT DOES NOT ASK WHICH OF THE TWO COMMITS IS LATER, since neither is fetched
# with its history. The trigger runs the commit of `main` its source holds,
# which is not behind a release made from `main`; a run made by hand for an
# older commit would release the older contract under the newer label.
#
# THE RELEASE STEP TRUSTS THE TAG THIS WRITES: it checks the tag's pattern and
# that the title is a name and that release, and not that the tag is the
# one chosen here or that the dry run said so. This is where those are checked,
# and the name and tarball rules here are the ones that step applies.
#
# THE TITLE IS THE SCRIPT'S, and so is the package name in it: the workspace
# manifest's, read at the commit, then a space and the release. The script
# releases under that title and the release step must match it, so this reads
# it from the same file and hands it over; the release step builds nothing.
#
# EVERY REFUSAL OF THE SCRIPT IS A FAILURE: a run that passed over one would
# be a release that is never made and a ticket waiting on it.
#
# NO LIFECYCLE SCRIPTS. The script packs with typescript and zod and runs no
# dependency's install step, so none is run in a pod whose next step holds the
# token.
#
# SCRIPTS is where the Task mounts these scripts and is not set there;
# tests/contract-prepare.py sets it.
set -eu

refuse() {
  echo "prepare: $*" >&2
  exit 1
}

: "${SOURCE:?}" "${OUT:?}" "${REPOSITORY:?}" "${GH:?}" "${COMMIT:?}" "${HOME:?}"
mkdir -p "$HOME"

name=$(node -e 'process.stdout.write(JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")).name)' \
  "$SOURCE/src/contract/package.json")
printf '%s\n' "$name" | grep -Eqx '@?[A-Za-z0-9._/-]+' \
  || refuse "src/contract/package.json names no package this can title a release with"


# Only a clean, empty answer is "absent": a failed ls-remote says nothing about the tag.
remote="https://github.com/$REPOSITORY.git"
tab=$(printf '\t')
listed=$(git ls-remote --tags "$remote" 'refs/tags/worker-contract-v*' 2>/dev/null) \
  || refuse "could not ask $REPOSITORY for its releases"
# A tag that is an object of its own is listed twice, and the line ending `^{}`
# is the commit, so it sorts last of its release.
newest=$(printf '%s\n' "$listed" \
  | grep -E "^[0-9a-f]{40}${tab}refs/tags/worker-contract-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(\^\{\})?\$" \
  | sed 's/^\([0-9a-f]*\).refs\/tags\/worker-contract-v\([0-9]*\)\.\([0-9]*\)\.\([0-9]*\)\(.*\)$/\2 \3 \4 \1 \5/' \
  | sort -k1,1n -k2,2n -k3,3n -k5,5 | tail -n 1) || true
[ -n "$newest" ] || refuse "$REPOSITORY holds no worker-contract-v<release> tag to number the next release from"
# shellcheck disable=SC2086
set -- $newest
released="$1.$2.$3"
at=$4
chosen="$1.$(($2 + 1)).0"
tag="worker-contract-v$chosen"

cd "$SOURCE"
[ "$(git rev-parse HEAD)" = "$COMMIT" ] || refuse "$SOURCE is not at $COMMIT"
if [ "$at" = "$COMMIT" ]; then
  echo "prepare: $REPOSITORY released $released at $COMMIT: nothing to publish"
  exit 0
fi
git fetch --quiet --depth 1 "$remote" "$at" 2>/dev/null \
  || refuse "could not fetch the commit $REPOSITORY released $released at"
before=$(git rev-parse --verify --quiet "$at:src/contract") \
  || refuse "the commit $REPOSITORY released $released at has no src/contract"
now=$(git rev-parse --verify --quiet "HEAD:src/contract") \
  || refuse "$COMMIT has no src/contract"
if [ "$before" = "$now" ]; then
  echo "prepare: src/contract is as $REPOSITORY released it in $released: nothing to publish at $COMMIT"
  exit 0
fi

mkdir -p "$GH"
cp "${SCRIPTS:-/scripts}/contract-gh.sh" "$GH/gh"
chmod 0755 "$GH/gh"

npm ci --ignore-scripts --no-audit --no-fund
printed=$(PATH="$GH:$PATH" node --experimental-strip-types scripts/publish-worker-contract.ts \
  --dry-run --release "$chosen" --out "$OUT/pack")
printf '%s\n' "$printed"

tarball=$(printf '%s\n' "$printed" | sed -n 's/^Packed [0-9a-f]\{64\}  \(.*\)$/\1/p')
case $tarball in
  "$OUT/pack/"*) ;;
  *) refuse "the script printed no tarball under $OUT/pack" ;;
esac
printf '%s\n' "${tarball#"$OUT/pack/"}" | grep -Eqx '[A-Za-z0-9._-]+\.tgz' \
  || refuse "the script printed a tarball that is not a .tgz directly in $OUT/pack"

[ -f "$tarball" ] || refuse "$tarball is not a file"
printf '%s\n' "$printed" | grep -qx "would release and tag $tag at $COMMIT" \
  || refuse "the script would not release $tag at $COMMIT"

printf '%s %s\n' "$name" "$chosen" > "$OUT/title"
printf '%s\n' "$tag" > "$OUT/tag"
echo "prepare: $tag is packed as $tarball"
