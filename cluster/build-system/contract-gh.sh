#!/bin/sh
# `gh`, as far as scripts/publish-worker-contract.ts in the prepare step of
# `publish-worker-contract` asks it: `gh release view <tag>`, and nothing else.
#
# THE SCRIPT ASKS BEFORE IT PACKS, even with --dry-run, and the step that runs
# it holds no credential and has no gh. So this answers from what needs none:
# a release is made by creating its tag, and the remote says whether the tag is
# there. A tag it holds is a release, whether or not a release object is, and
# the step has already stopped on one before it runs the script.
#
# A REMOTE THAT CANNOT BE ASKED IS EXIT 2, not an absent release: the script
# accepts 0 and 1 and fails on anything else.
#
# ANYTHING ELSE IS REFUSED, so a call the script grows is a failure and not an
# answer this made up.
set -eu

: "${REPOSITORY:?}"

if [ "$#" -ne 3 ] || [ "$1" != release ] || [ "$2" != view ]; then
  echo "gh: this answers 'release view <tag>' only" >&2
  exit 2
fi

if ! held=$(git ls-remote --tags "https://github.com/$REPOSITORY.git" "refs/tags/$3" 2>/dev/null); then
  echo "gh: could not ask the remote whether it holds $3" >&2
  exit 2
fi
if [ -n "$held" ]; then
  exit 0
fi
echo "release not found" >&2
exit 1
