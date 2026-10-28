#!/bin/sh
# One image of one commit: the registry's if it has one, built here if not.
#
# The second step of `build-image` runs this over the tree `fetch.sh` checked
# out, and writes the image's digest where RESULT_DIGEST names. The second
# step of `build-two-platform-image` runs it with INDEX, and leaves what it
# found or built there for index.sh, which writes the digest.
#
# A COMMIT'S IMAGE IS BUILT ONCE. Two builds of one tree give one digest only
# when the second takes the image's layers from the first's cache, so a tag
# built twice can name two images, and a release made from the second then
# moves every pod off the first for no change. The tag is the commit, and a
# tag the registry already serves is the answer: its digest is the result and
# nothing is built. That holds only while nothing else is building the same
# commit, which is the trigger's to keep -- it starts one run at a time. For
# two platforms the tag is left in INDEX as `served`, and index.sh takes it
# only as an index of the two: a tag that is one image stays one, and the run
# fails rather than build the commit again.
#
# THE DIGEST IS THE ONE THE REGISTRY SERVES UNDER THE TAG, on both paths.
# After a build it is read back and held to the digest BuildKit reported, so
# the result is never a digest a pull would not get. After a build of two
# platforms index.sh holds the index's the same way.
#
# TWO PLATFORMS ARE TWO BUILDS AT ONCE, AND NEITHER IS TAGGED. With INDEX,
# linux/amd64 is built here as one platform is, and pushed under its digest
# alone. linux/arm64 is built by the daemon ARM64_BUILDER names, over mutual
# TLS with the files in ARM64_BUILDER_TLS and the daemon's address as the name
# its certificate is held to, and comes back into INDEX as an OCI archive.
# Each line either prints carries its platform.
# The digest each build reported is written into INDEX for index.sh, which
# pushes the archive and the index of the two under the tag.
#
# THE CACHE HAS A REFERENCE OF ITS OWN. An image is built only when its tag is
# absent, so a cache read from the image's own tag is never there to read. It
# is imported from and exported to `buildcache` in the image's repository, and
# a reference that does not exist yet is a build with nothing imported. The
# daemon that builds linux/arm64 keeps its own.
#
# PLAIN HTTP, BY NAME. The registry is this cluster's own Service and serves
# no TLS, which is said in each reference a build below names, because
# BuildKit asks for it per reference.
set -eu

refuse() {
  echo "build: $*" >&2
  exit 1
}

: "${IMAGE:?}" "${COMMIT:?}" "${SOURCE:?}" "${CONTEXT:?}" "${DOCKERFILE:?}" "${RESULT_DIGEST:?}"
TARGET=${TARGET:-}
INDEX=${INDEX:-}

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
if [ -n "$INDEX" ]; then
  : "${ARM64_BUILDER_TLS:?}"
  ARM64_BUILDER=${ARM64_BUILDER:-}
  [ -n "$ARM64_BUILDER" ] || refuse "the run names no daemon to build linux/arm64 with"
  case $ARM64_BUILDER in
    tcp://*[!a-z0-9.:-]* | tcp://?*:*[!0-9]*) refuse "$ARM64_BUILDER is not a daemon's address, tcp://<address>:<port>" ;;
    tcp://?*:[0-9]*) ;;
    *) refuse "$ARM64_BUILDER is not a daemon's address, tcp://<address>:<port>" ;;
  esac
  server=${ARM64_BUILDER#tcp://}
  server=${server%:*}
  for file in ca.crt tls.crt tls.key; do
    [ -f "$ARM64_BUILDER_TLS/$file" ] ||
      refuse "$ARM64_BUILDER_TLS holds no $file, which $ARM64_BUILDER is spoken to with"
  done
fi

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
  if [ -n "$INDEX" ]; then
    mkdir -p "$INDEX"
    printf '%s' "$digest" > "$INDEX/served"
  else
    printf '%s' "$digest" > "$RESULT_DIGEST"
  fi
  exit 0
fi

[ -d "$SOURCE/$CONTEXT" ] || refuse "$CONTEXT is not a directory of the commit"
[ -f "$SOURCE/$DOCKERFILE" ] || refuse "$DOCKERFILE is not a file of the commit"

# One half of a build of two platforms, every line of its output headed by the
# platform, and its status in INDEX once it has ended.
half() {
  platform=$1
  shift
  { status=0; "$@" 2>&1 || status=$?; echo "$status" > "$INDEX/$platform.status"; } |
    sed "s|^|linux/$platform: |"
}

# The digest of one half, as its build reported it.
reported() {
  built=$(sed -n 's/.*"containerimage\.digest": *"\(sha256:[0-9a-f]\{64\}\)".*/\1/p' "$INDEX/$1.json" 2>/dev/null || true)
  [ -n "$built" ] || refuse "BuildKit reported no digest for the linux/$1 half of $IMAGE:$COMMIT"
  printf '%s' "$built"
}

if [ -n "$INDEX" ]; then
  mkdir -p "$INDEX"
  set -- \
    --frontend=dockerfile.v0 \
    --opt "filename=$(basename "$DOCKERFILE")" \
    --local "context=$SOURCE/$CONTEXT" \
    --local "dockerfile=$(dirname "$SOURCE/$DOCKERFILE")" \
    --progress=plain
  [ -z "$TARGET" ] || set -- "$@" --opt "target=$TARGET"
  half amd64 buildctl-daemonless.sh build "$@" \
    --opt platform=linux/amd64 \
    --output "type=image,name=$IMAGE,push-by-digest=true,oci-mediatypes=true,push=true,registry.insecure=true" \
    --import-cache "type=registry,ref=$IMAGE:buildcache,registry.insecure=true" \
    --export-cache "type=registry,ref=$IMAGE:buildcache,mode=max,registry.insecure=true" \
    --metadata-file "$INDEX/amd64.json" &
  half arm64 buildctl --addr "$ARM64_BUILDER" \
    --tlsservername "$server" \
    --tlscacert "$ARM64_BUILDER_TLS/ca.crt" \
    --tlscert "$ARM64_BUILDER_TLS/tls.crt" \
    --tlskey "$ARM64_BUILDER_TLS/tls.key" \
    build "$@" \
    --opt platform=linux/arm64 \
    --output "type=oci,dest=$INDEX/arm64.tar" \
    --metadata-file "$INDEX/arm64.json" &
  wait
  for platform in amd64 arm64; do
    status=$(cat "$INDEX/$platform.status" 2>/dev/null || echo none)
    [ "$status" = 0 ] || refuse "the linux/$platform half of $IMAGE:$COMMIT ended $status"
  done
  amd64=$(reported amd64)
  arm64=$(reported arm64)
  printf '%s' "$amd64" > "$INDEX/amd64"
  printf '%s' "$arm64" > "$INDEX/arm64"
  echo "build: built $IMAGE:$COMMIT for linux/amd64 at $amd64 and for linux/arm64 at $arm64"
  exit 0
fi

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
