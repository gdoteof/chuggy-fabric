#!/bin/sh
# One index of the two halves build.sh built, pushed under the commit's tag.
#
# The third step of `build-two-platform-image` runs this, after build.sh, and
# writes the index's digest where RESULT_DIGEST names.
#
# A SERVED TAG IS THE ANSWER ONLY AS AN INDEX OF THE TWO. build.sh leaves the
# digest the registry served under the tag as `served` and builds nothing.
# That digest is the result when it is an index of linux/amd64 and linux/arm64
# and nothing else, each entry one image of its platform, as this file pushes
# one. Anything else -- one image, as a run of `build-image` leaves, an index
# of other platforms, or one whose entry is not an image of its own -- is
# refused, and not built over: a commit's image is built once.
#
# EACH HALF IS HELD BEFORE THE TAG IS WRITTEN. The linux/arm64 archive the Mac
# sent back is pushed under the digest its build reported, which the registry
# holds the manifest to; the linux/amd64 half is already there under its own.
# Each digest is then held to being one image, not an index, whose
# configuration is for its platform. Only then is the index of the two pushed,
# as the one write under the tag, so the tag never names one half alone or a
# half of the wrong platform, and a run that fails before it leaves a commit
# the next run builds.
#
# THE DIGEST IS THE ONE THE REGISTRY SERVES UNDER THE TAG, held to the one
# regctl reported for the index it pushed. The index the registry serves at it
# lists linux/amd64 and linux/arm64 at the two halves' digests and nothing
# else, or the run fails.
#
# PLAIN HTTP, BY NAME. regctl is told per call, by a `--host` entry for the
# registry's name, that it serves no TLS.
set -eu

refuse() {
  echo "index: $*" >&2
  exit 1
}

: "${IMAGE:?}" "${COMMIT:?}" "${INDEX:?}" "${RESULT_DIGEST:?}"
host="reg=${IMAGE%%/*},tls=disabled"

# What a refused served tag is left as.
stays="a commit's image is built once, so that commit's stays as it is"
# Each entry of an index, as its platform and its digest, one a line.
listing='{{ range .Manifests }}{{ .Platform.OS }}/{{ .Platform.Architecture }} {{ .Digest }}{{ println }}{{ end }}'

# Whether the manifest REF names is one image or an index, or its media type
# when it is neither.
kind() {
  type=$(regctl --host "$host" manifest get "$1" --format '{{ .GetDescriptor.MediaType }}')
  case $type in
    application/vnd.oci.image.manifest.v1+json | application/vnd.docker.distribution.manifest.v2+json) echo 'one image' ;;
    application/vnd.oci.image.index.v1+json | application/vnd.docker.distribution.manifest.list.v2+json) echo 'an index' ;;
    *) echo "$type" ;;
  esac
}

# The linux/PLATFORM half at DIGEST, held to being one image whose
# configuration is for that platform, or refused with WHY appended.
held() {
  what=$(kind "$IMAGE@$2")
  [ "$what" = 'one image' ] || refuse "the linux/$1 half at $2 is $what, not one image$3"
  config=$(regctl --host "$host" image config "$IMAGE@$2" --format '{{ .OS }}/{{ .Architecture }}')
  [ "$config" = "linux/$1" ] || refuse "the linux/$1 half at $2 is an image for '$config'$3"
}

# A digest build.sh left in INDEX, under NAME, described as WHAT.
left() {
  [ -f "$INDEX/$1" ] || refuse "build.sh left no $2 in $INDEX"
  digest=$(cat "$INDEX/$1")
  printf '%s' "$digest" | grep -Eqx 'sha256:[0-9a-f]{64}' ||
    refuse "the $2 is '$digest', which is not a digest"
  printf '%s' "$digest"
}

if [ -f "$INDEX/served" ]; then
  served=$(left served "digest the registry served under the tag")
  what=$(kind "$IMAGE@$served")
  [ "$what" = 'an index' ] ||
    refuse "the registry has $IMAGE:$COMMIT at $served as $what, not an index of linux/amd64 and linux/arm64; $stays"
  listed=$(regctl --host "$host" manifest get "$IMAGE@$served" --format "$listing")
  amd64=$(printf '%s\n' "$listed" | sed -n '1s/^linux\/amd64 \(sha256:[0-9a-f]\{64\}\)$/\1/p')
  arm64=$(printf '%s\n' "$listed" | sed -n '2s/^linux\/arm64 \(sha256:[0-9a-f]\{64\}\)$/\1/p')
  [ -n "$amd64" ] && [ -n "$arm64" ] &&
    [ "$listed" = "$(printf 'linux/amd64 %s\nlinux/arm64 %s' "$amd64" "$arm64")" ] ||
    refuse "the registry has $IMAGE:$COMMIT at $served as an index listing '$listed', not of linux/amd64 and linux/arm64; $stays"
  held amd64 "$amd64" ", in the index the registry has under $IMAGE:$COMMIT at $served; $stays"
  held arm64 "$arm64" ", in the index the registry has under $IMAGE:$COMMIT at $served; $stays"
  echo "index: the registry has $IMAGE:$COMMIT at $served, an index of linux/amd64 and linux/arm64, and nothing is indexed"
  printf '%s' "$served" > "$RESULT_DIGEST"
  exit 0
fi

amd64=$(left amd64 "digest of the linux/amd64 half")
arm64=$(left arm64 "digest of the linux/arm64 half")
[ -f "$INDEX/arm64.tar" ] || refuse "build.sh left no linux/arm64 archive in $INDEX"

regctl --host "$host" image import "$IMAGE@$arm64" "$INDEX/arm64.tar"
held amd64 "$amd64" ""
held arm64 "$arm64" ""

pushed=$(regctl --host "$host" index create "$IMAGE:$COMMIT" \
  --ref "$IMAGE@$amd64" --ref "$IMAGE@$arm64" \
  --format '{{ .Manifest.GetDescriptor.Digest }}')
[ -n "$pushed" ] || refuse "regctl pushed the index of $IMAGE:$COMMIT and reported no digest for it"
served=$(regctl --host "$host" manifest head "$IMAGE:$COMMIT") || true
[ -n "$served" ] || refuse "regctl pushed the index of $IMAGE:$COMMIT as $pushed and the registry serves nothing under it"
[ "$served" = "$pushed" ] ||
  refuse "regctl pushed the index of $IMAGE:$COMMIT as $pushed and the registry serves '$served' under it"
listed=$(regctl --host "$host" manifest get "$IMAGE@$served" --format "$listing")
[ "$listed" = "$(printf 'linux/amd64 %s\nlinux/arm64 %s' "$amd64" "$arm64")" ] ||
  refuse "the index of $IMAGE:$COMMIT lists '$listed', not linux/amd64 at $amd64 and linux/arm64 at $arm64"
echo "index: indexed $IMAGE:$COMMIT at $served"
printf '%s' "$served" > "$RESULT_DIGEST"
