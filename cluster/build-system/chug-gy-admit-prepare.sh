#!/bin/sh
# Step two of the site's admission: the change to the site's Deployment, made
# in a fresh checkout.
#
# It runs after chug-gy-admit-read.sh, with no token of any kind. It reads
# `$IN/images` as data, checks out FABRIC_URL's BRANCH afresh and, for each
# image read, writes `REGISTRY/<repository>@<digest>` as the image of the
# container of that name in DEPLOYMENT, where that container does not already
# name it. A step that fails fails the pod, and the step after it, which is the
# one with the GitHub token, is never started.
#
# AN IMAGE IS ONE LINE OF `$IN/images`, as the read step wrote it from its
# IMAGES: the container, the repository, the digest, the commit, the run, the
# repository the commit is of, and the words the commit message names it by.
# A second image of the Deployment, in `containers` or `initContainers`, is one
# more line of the read step's IMAGES and nothing here.
#
# WHAT IT LEAVES under `$OUT` IS ALL admit-publish.sh READS, as regular files:
# the branch name, the commit message, the changed file's path and new content,
# the blob and the commit it was made against, and a `ready` marker written
# last. When there is nothing to admit it leaves nothing, and succeeds.
#
# NOTHING TO ADMIT is no image read, or every image read already the one its
# container names: an image that landed, whoever landed it, is not admitted
# again.
#
# THE MESSAGE is the one a person wrote for each of the site's images before
# this: `chug-gy: <words>, built at <repository> <short commit>`, with a line
# for each image moved that names the run its digest is from. Two images moved
# at once are one title, joined by `and`.
#
# THE BRANCH IS NAMED FOR THE DIGEST of the first image moved,
# `admit/chug-gy-<12 hex>`, so the same build is the same branch: that is what
# lets admit-publish.sh count a branch or a pull request already there.
#
# THE FILE IS READ AS THIS TREE LAYS ONE OUT, not parsed: the container is the
# list item `- name: <container>` with an `image:` two spaces deeper, and that
# line alone is rewritten. One such item for the name, an image that is not of
# the repository, or a rewrite that changed any other line, is refused rather
# than guessed at. The image this runs in has python3, and the reading is its
# standard library alone.
set -eu

: "${IN:?}" "${OUT:?}" "${FABRIC_URL:?}" "${BRANCH:?}" "${CHECKOUT:?}" "${DEPLOYMENT:?}" "${REGISTRY:?}"

say() {
  echo "chug-gy-admit: $*"
}

refuse() {
  echo "chug-gy-admit: $*" >&2
  exit 1
}

[ -f "$IN/images" ] || { say "no image to admit"; exit 0; }

# Each line as the step before wrote it; it is read, not sourced.
while read -r container repository digest commit run source words; do
  case $container/$repository/$run/$source in
    *[!a-z0-9/._-]*) refuse "images holds '$container $repository $run $source', which this does not write a file from" ;;
  esac
  [ -n "$source" ] && [ -n "$words" ] || refuse "images names no source or no words for $container"
  case $digest in
    sha256:*) ;;
    *) refuse "images holds '$digest', which is not a sha256 digest" ;;
  esac
  case ${digest#sha256:} in
    *[!0-9a-f]* | "") refuse "images holds '$digest', which is not a sha256 digest" ;;
  esac
  case $commit in
    *[!0-9a-f]* | "") refuse "images holds '$commit', which is not a commit hash" ;;
  esac
done < "$IN/images"

rm -rf "$CHECKOUT"
git clone --quiet --depth 1 --no-tags --branch "$BRANCH" "$FABRIC_URL" "$CHECKOUT"
cd "$CHECKOUT"
base=$(git rev-parse HEAD)
blob=$(git rev-parse "HEAD:$DEPLOYMENT")

title='' body='' branch='' count=0
while read -r container repository digest commit run source words; do
  image="$REGISTRY/$repository@$digest"
  outcome=$(python3 - "$DEPLOYMENT" "$container" "$REGISTRY/$repository@sha256:" "$image" <<'PYTHON'
import re
import sys

path, container, repository, image = sys.argv[1:]
lines = open(path, encoding="utf-8").read().split("\n")


def fail(message):
    print(f"chug-gy-admit: {path}: {message}", file=sys.stderr)
    raise SystemExit(1)


found = []
for start, line in enumerate(lines):
    head = re.fullmatch(r"( *)- name: " + re.escape(container) + r" *", line)
    if not head:
        continue
    indent = len(head.group(1))
    for at in range(start + 1, len(lines)):
        text = lines[at]
        if text.strip() and len(text) - len(text.lstrip(" ")) <= indent:
            break
        named = re.fullmatch(" " * (indent + 2) + r"image: *(\S+) *", text)
        if named:
            found.append((at, named.group(1)))
if len(found) != 1:
    fail(f"{len(found)} containers named {container} with an image, not one")
((at, held),) = found
if held == image:
    print("held")
    raise SystemExit(0)
if not held.startswith(repository):
    fail(f"container {container} runs {held}, which is not of {repository[:-len('@sha256:')]}")
before = lines[at]
lines[at] = before.replace(held, image)
open(path, "w", encoding="utf-8").write("\n".join(lines))
print("moved")
PYTHON
) || refuse "the image of container $container could not be written"
  short=$(printf '%s' "$commit" | cut -c1-7)
  if [ "$outcome" = held ]; then
    say "$container already runs $image at $base"
    continue
  fi
  [ "$outcome" = moved ] || refuse "the rewrite of container $container said '$outcome'"
  title="${title:+$title and }$words, built at $source $short"
  count=$((count + 1))
  body="${body:+$body
}The digest TaskRun $run reported, for $container."
  [ -n "$branch" ] || branch="admit/chug-gy-$(printf '%s' "${digest#sha256:}" | cut -c1-12)"
done < "$IN/images"

if [ -z "$title" ]; then
  say "every image read is already in $DEPLOYMENT at $base: nothing to admit"
  exit 0
fi

changed=$(git status --porcelain --untracked-files=no | tr '\n' ';')
[ "$changed" = " M $DEPLOYMENT;" ] || refuse "the rewrite changed '$changed', not $DEPLOYMENT alone"
moved=$(git diff --numstat -- "$DEPLOYMENT" | awk '{ print $1 "/" $2 }')
[ "$moved" = "$count/$count" ] || refuse "the rewrite moved $moved lines of $DEPLOYMENT, not one an image moved"

mkdir -p "$OUT"
cp "$DEPLOYMENT" "$OUT/content"
printf 'chug-gy: %s\n\n%s\n' "$title" "$body" > "$OUT/message"
printf '%s' "$branch" > "$OUT/branch"
printf '%s' "$DEPLOYMENT" > "$OUT/path"
printf '%s' "$blob" > "$OUT/blob"
printf '%s' "$base" > "$OUT/base"
printf '%s' "$BRANCH" > "$OUT/target"
touch "$OUT/ready"
say "chug-gy: $title is ready on $base"
