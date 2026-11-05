#!/bin/sh
# The worker contract of one chuggy commit, packed and checked, or nothing to do.
#
# The second step of `publish-worker-contract`: it runs what the commit says,
# and so it holds no credential. `npm ci` and the publish script are the
# commit's own code. What it hands the next step is a tarball, in a directory
# that step reads, the title it is released under, and the tag, written last.
#
# NOTHING TO DO IS SUCCESS. A commit that does not move the contract's release
# names a tag the remote already holds, and so does a commit the trigger
# started a second run for. Neither writes `tag`, and the release step then
# does nothing. Every commit of chuggy's `main` is run through here, so a
# commit that is not a release has to be the usual case and not a failure.
#
# THE RELEASE IS READ BY ITS DECLARATION AND NOT BY RUNNING IT, because the
# modules cannot be imported before `npm ci` and `npm ci` is the slow part.
# The pattern is the one line workerContract.ts writes it on, and a file that
# does not match it, or matches twice, is a failure and not a skipped release.
#
# THE RELEASE STEP TRUSTS THE TAG THIS WRITES: it checks the tag's pattern and
# that the title is a name and that release, and not that the tag is the
# declared one or that the dry run said so. This is where those are checked,
# and the name and tarball rules here are the ones that step applies.
#
# THE TITLE IS THE SCRIPT'S, and so is the package name in it: the workspace
# manifest's, read at the commit, then a space and the release. The script
# releases under that title and the release step must match it, so this reads
# it from the same file and hands it over; the release step builds nothing.
#
# EVERY OTHER REFUSAL OF THE SCRIPT IS A FAILURE. It refuses a history that
# does not name this release as the wire the tree holds, and a pack whose files
# are not the ones the history records; a run that passed over either would be
# a release that is never made and a ticket waiting on it.
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

declared=$(sed -n 's/^export const workerContractRelease = "\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)";$/\1/p' \
  "$SOURCE/src/contract/workerContract.ts")
case $declared in
  "" | *"
"*) refuse "workerContract.ts does not declare workerContractRelease once, as a version" ;;
esac
tag="worker-contract-v$declared"
name=$(node -e 'process.stdout.write(JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")).name)' \
  "$SOURCE/src/contract/package.json")
printf '%s\n' "$name" | grep -Eqx '@?[A-Za-z0-9._/-]+' \
  || refuse "src/contract/package.json names no package this can title a release with"


# Only a clean, empty answer is "absent": a failed ls-remote says nothing about the tag.
held=$(git ls-remote --tags "https://github.com/$REPOSITORY.git" "refs/tags/$tag" 2>/dev/null) \
  || refuse "could not ask $REPOSITORY whether it holds $tag"
if [ -n "$held" ]; then
  echo "prepare: $REPOSITORY holds $tag: nothing to publish at $COMMIT"
  exit 0
fi

mkdir -p "$GH"
cp "${SCRIPTS:-/scripts}/contract-gh.sh" "$GH/gh"
chmod 0755 "$GH/gh"

cd "$SOURCE"
[ "$(git rev-parse HEAD)" = "$COMMIT" ] || refuse "$SOURCE is not at $COMMIT"
npm ci --ignore-scripts --no-audit --no-fund
printed=$(PATH="$GH:$PATH" node --experimental-strip-types scripts/publish-worker-contract.ts \
  --dry-run --out "$OUT/pack")
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

printf '%s %s\n' "$name" "$declared" > "$OUT/title"
printf '%s\n' "$tag" > "$OUT/tag"
echo "prepare: $tag is packed as $tarball"
