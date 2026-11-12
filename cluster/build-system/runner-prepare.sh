#!/bin/sh
# One runner package's release at one commit, packed with its notes, or nothing
# to do.
#
# The second step of `publish-runner-release`: it runs what the commit says,
# and so it holds no credential. `npm ci` and `npm pack` run the commit's
# manifest. What it hands the next step is a tarball, in a directory that step
# reads, the release's notes, and the tag, written last. contract-prepare.sh is
# the same step for the worker contract, and each rule below that one also has
# is argued there.
#
# NOTHING TO DO IS SUCCESS. A commit that does not move the package's version
# names a tag the remote already holds, and neither writes `tag`; the release
# step then does nothing. Every commit of the package's `main` is run through
# here, so that is the usual case.
#
# THE RELEASE IS THE MANIFEST'S. `package.json` names the package, which must
# be the one the run is for, and the version, which must be three numbers;
# the tag is `v` and that version, which is what every release of the package
# was tagged by a person and what kasofsk/chuggy's
# scripts/pin-runner-release.ts fetches the tarball under.
#
# THE NOTES ARE THE RELEASE COMMIT'S MESSAGE. The release commit is the newest
# commit before the run's that changed the manifest's `version` line, and its
# subject must be `release: <version>` or `release: <version>, <summary>`: a
# version moved by a commit that does not say it is the release is a failure,
# and no release is made. The notes are that message's body less its trailers
# (`Co-Authored-By:` and the like), or the summary where the body is empty. A
# message with neither is a failure: a release is made with what changed for
# whoever installs it. Finding the commit needs the history the fetch step
# left out, so this fetches the rest of it; a history that is still shallow is
# a failure, since a shallow root reads as a commit that wrote every line.
#
# THE TARBALL IS `npm pack`'S, named `<package>-<version>.tgz`, and the only
# file in the pack directory. No lifecycle script runs, in `npm ci` or in the
# pack, so none is run in a pod whose next step holds the token.
#
# SCRIPTS is where the Task mounts these scripts and is not read here; the
# variables below are the Task's, and tests/runner-prepare.py sets each.
set -eu

refuse() {
  echo "prepare: $*" >&2
  exit 1
}

: "${SOURCE:?}" "${OUT:?}" "${URL:?}" "${REPOSITORY:?}" "${PACKAGE:?}" "${COMMIT:?}" "${HOME:?}"
mkdir -p "$HOME"
cd "$SOURCE"

manifest=$(node -e '
  const m = JSON.parse(require("fs").readFileSync("package.json", "utf8"));
  process.stdout.write(`${m.name}\n${m.version}\n`);
') || refuse "package.json cannot be read as a manifest"
name=$(printf '%s\n' "$manifest" | sed -n 1p)
version=$(printf '%s\n' "$manifest" | sed -n 2p)
[ "$name" = "$PACKAGE" ] || refuse "package.json names the package '$name', and the run is for $PACKAGE"
printf '%s\n' "$version" | grep -Eqx '[0-9]+\.[0-9]+\.[0-9]+' \
  || refuse "package.json's version '$version' is not three numbers"
tag="v$version"

# Only a clean, empty answer is "absent": a failed ls-remote says nothing about the tag.
held=$(git ls-remote --tags "https://github.com/$REPOSITORY.git" "refs/tags/$tag" 2>/dev/null) \
  || refuse "could not ask $REPOSITORY whether it holds $tag"
if [ -n "$held" ]; then
  echo "prepare: $REPOSITORY holds $tag: nothing to publish at $COMMIT"
  exit 0
fi

[ "$(git rev-parse HEAD)" = "$COMMIT" ] || refuse "$SOURCE is not at $COMMIT"
git fetch --quiet --unshallow "$URL" "$COMMIT" || refuse "could not fetch the history of $COMMIT from $URL"
[ "$(git rev-parse --is-shallow-repository)" = false ] || refuse "the history of $COMMIT is still shallow"

release=$(git log -1 --format=%H -G '^  "version": ' "$COMMIT" -- package.json)
[ -n "$release" ] || refuse "no commit before $COMMIT changed package.json's version"
subject=$(git log -1 --format=%s "$release")
case $subject in
  "release: $version" | "release: $version, "*) ;;
  *) refuse "$release moved the version to $version, and its subject does not say it is release $version" ;;
esac

mkdir -p "$OUT/pack"
git log -1 --format=%B "$release" | VERSION="$version" node -e '
  const message = require("fs").readFileSync(0, "utf8");
  const [first, ...rest] = message.replace(/\r\n/gu, "\n").trim().split(/\n\s*\n/u);
  // The last paragraph is trailers where every line of it is one.
  if (rest.length > 0 && rest.at(-1).split("\n").every((line) => /^[A-Za-z0-9-]+: \S/u.test(line))) rest.pop();
  const summary = first.split("\n")[0].slice(`release: ${process.env.VERSION}`.length).replace(/^, /u, "");
  const notes = rest.length > 0 ? rest.join("\n\n") : summary;
  if (notes.trim() === "") process.exit(3);
  process.stdout.write(`${notes.trim()}\n`);
' > "$OUT/notes.part" || refuse "$release says nothing a release could be noted with: no body and no summary"

npm ci --ignore-scripts --no-audit --no-fund
npm pack --ignore-scripts --pack-destination "$OUT/pack"
tarball="$OUT/pack/$PACKAGE-$version.tgz"
[ -f "$tarball" ] && [ ! -L "$tarball" ] || refuse "npm pack left no $PACKAGE-$version.tgz in $OUT/pack"
[ "$(ls -A "$OUT/pack")" = "$PACKAGE-$version.tgz" ] || refuse "npm pack left more than $PACKAGE-$version.tgz in $OUT/pack"

mv "$OUT/notes.part" "$OUT/notes"
printf '%s\n' "$tag" > "$OUT/tag"
echo "prepare: $tag of $PACKAGE is packed as $tarball, noted from $release"
