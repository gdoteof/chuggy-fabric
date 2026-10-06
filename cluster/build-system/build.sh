#!/bin/sh
# One image of one commit: the registry's if it has one, built here if not.
#
# The second step of `build-image` runs this over the tree `fetch.sh` checked
# out, and writes the image's digest where RESULT_DIGEST names.
#
# A COMMIT'S IMAGE IS BUILT ONCE. Two builds of one tree give one digest only
# when the second takes the image's layers from the first's cache, so a tag
# built twice can name two images, and a release made from the second then
# moves every pod off the first for no change. The tag is the commit, and a
# tag the registry already serves is the answer: its digest is the result and
# nothing is built. That holds only while nothing else is building the same
# commit, which is the trigger's to keep -- it starts one run at a time.
#
# THE DIGEST IS THE ONE THE REGISTRY SERVES UNDER THE TAG, on both paths.
# After a build it is read back and held to the digest BuildKit reported, so
# the result is never a digest a pull would not get.
#
# THE CACHE HAS A REFERENCE OF ITS OWN. An image is built only when its tag is
# absent, so a cache read from the image's own tag is never there to read. It
# is imported from and exported to `buildcache` in the image's repository, and
# a reference that does not exist yet is a build with nothing imported.
#
# PLAIN HTTP, BY NAME. The registry is this cluster's own Service and serves
# no TLS, which is said three times below because BuildKit asks for it per
# reference.
set -eu

refuse() {
  echo "build: $*" >&2
  exit 1
}

: "${IMAGE:?}" "${COMMIT:?}" "${SOURCE:?}" "${CONTEXT:?}" "${DOCKERFILE:?}" "${RESULT_DIGEST:?}"
TARGET=${TARGET:-}

case $IMAGE in
  */*) ;;
  *) refuse "$IMAGE names no repository under a registry" ;;
esac
case $IMAGE in
  *[!a-z0-9./:_-]*) refuse "$IMAGE is not a registry and a repository" ;;
esac
case $COMMIT in
  *[!0-9a-f]*) refuse "$COMMIT is not a commit hash" ;;
esac
[ "${#COMMIT}" -eq 40 ] || refuse "$COMMIT is not a full commit hash"

# The digest the registry serves IMAGE:COMMIT under, or nothing when it has no
# such tag. Any other answer, no answer included, is a failure: reading "could
# not ask" as "absent" is a second build of a commit that has one.
served() {
  answer=$(wget -q -S --spider \
    --header 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
    "http://${IMAGE%%/*}/v2/${IMAGE#*/}/manifests/$COMMIT" 2>&1) || true
  status=$(printf '%s\n' "$answer" | sed -n 's/^ *HTTP\/[0-9.]* \([0-9][0-9][0-9]\).*/\1/p' | tail -n 1)
  case $status in
    200)
      found=$(printf '%s\n' "$answer" | tr -d '\r' |
        sed -n 's/^ *[Dd]ocker-[Cc]ontent-[Dd]igest: *\(sha256:[0-9a-f]\{64\}\)$/\1/p' | tail -n 1)
      [ -n "$found" ] || refuse "the registry serves $IMAGE:$COMMIT and names no digest for it: $answer"
      printf '%s\n' "$found"
      ;;
    404) ;;
    *) refuse "the registry did not say whether it has $IMAGE:$COMMIT: $answer" ;;
  esac
}

digest=$(served)
if [ -n "$digest" ]; then
  echo "build: the registry has $IMAGE:$COMMIT at $digest, and nothing is built"
  printf '%s' "$digest" > "$RESULT_DIGEST"
  exit 0
fi

[ -d "$SOURCE/$CONTEXT" ] || refuse "$CONTEXT is not a directory of the commit"
[ -f "$SOURCE/$DOCKERFILE" ] || refuse "$DOCKERFILE is not a file of the commit"

metadata=$(mktemp)
set -- \
  --frontend=dockerfile.v0 \
  --opt "filename=$(basename "$DOCKERFILE")" \
  --opt platform=linux/amd64 \
  --local "context=$SOURCE/$CONTEXT" \
  --local "dockerfile=$(dirname "$SOURCE/$DOCKERFILE")" \
  --output "type=image,name=$IMAGE:$COMMIT,push=true,registry.insecure=true" \
  --import-cache "type=registry,ref=$IMAGE:buildcache,registry.insecure=true" \
  --export-cache "type=registry,ref=$IMAGE:buildcache,mode=max,registry.insecure=true" \
  --metadata-file "$metadata" \
  --progress=plain
[ -z "$TARGET" ] || set -- "$@" --opt "target=$TARGET"
buildctl-daemonless.sh build "$@"

built=$(sed -n 's/.*"containerimage\.digest": *"\(sha256:[0-9a-f]\{64\}\)".*/\1/p' "$metadata")
[ -n "$built" ] || refuse "BuildKit reported no digest for $IMAGE:$COMMIT: $(cat "$metadata")"
digest=$(served)
[ "$digest" = "$built" ] ||
  refuse "BuildKit pushed $IMAGE:$COMMIT as $built and the registry serves '$digest' under it"
echo "build: built $IMAGE:$COMMIT at $digest"
printf '%s' "$digest" > "$RESULT_DIGEST"
