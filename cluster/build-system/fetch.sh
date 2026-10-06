#!/bin/sh
# One commit of one repository, fetched by its hash and by nothing else.
#
# The first step of `build-image` and of `publish-release` runs this, each
# into the directory its second step reads.
#
# BY HASH, SO A RUN IS A FUNCTION OF ITS PARAMETERS. A branch is whatever it
# holds when it is read, and a run that read one would build something its
# parameters do not name. A hash that is not on the remote is a fetch that
# fails. The check after the checkout is on what git wrote, not on what it was
# asked for.
#
# NO CREDENTIAL. The pod has none and the fetch sends none: a repository that
# is not public is a fetch that fails.
set -eu

refuse() {
  echo "fetch: $*" >&2
  exit 1
}

: "${URL:?}" "${COMMIT:?}" "${DIRECTORY:?}"

case $COMMIT in
  *[!0-9a-f]*) refuse "$COMMIT is not a commit hash" ;;
esac
[ "${#COMMIT}" -eq 40 ] || refuse "$COMMIT is not a full commit hash"

git init --quiet "$DIRECTORY"
git -C "$DIRECTORY" fetch --quiet --depth 1 "$URL" "$COMMIT"
git -C "$DIRECTORY" -c advice.detachedHead=false checkout --quiet FETCH_HEAD
fetched=$(git -C "$DIRECTORY" rev-parse HEAD)
[ "$fetched" = "$COMMIT" ] || refuse "asked $URL for $COMMIT and checked out $fetched"
echo "fetch: $URL at $COMMIT is in $DIRECTORY"
