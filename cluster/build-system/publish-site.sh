#!/bin/sh
# One release of the site as one OCI artifact: the fabric's cluster/<layer> as
# fetch.sh checked it out, and beside it an overlay that writes in the image
# this run built.
#
# The second step of `publish-site` runs this. It is publish.sh over one
# directory, one image and no Job, and each rule below that publish.sh also
# has is argued there: the overlay beside the fabric's files and not in them;
# the annotation added by kind to objects that have none, quoted; the two
# renders compared with what the overlay may write taken out of both, and the
# render with the overlay read alone; the version as the clock, pushed only
# above every version the repository holds, from a tag list read whole; the
# commit as a second tag; plain HTTP by the registry's name.
#
# WHAT THE OVERLAY WRITES: every line that names the image is an image line
# at this run's digest, and every Deployment carries the source-commit
# annotation, which is the site commit's first eight characters. Nothing
# else: a release that rendered one object fewer would have the layer prune
# it, and a place the overlay cannot write is a refusal and not a second
# digest in one release.
#
# WHAT GIT CARRIES THERE IS NO IMAGE'S DIGEST, sixty-four zeroes, as the two
# release directories carry: the overlay replaces whatever is written, so a
# digest written in git would deploy nothing and a reader of the file would
# believe it.
set -eu

refuse() {
  echo "publish: $*" >&2
  exit 1
}

: "${SOURCE:?}" "${WORK:?}" "${SITE_URL:?}" "${SITE_COMMIT:?}" "${LAYER:?}"
: "${IMAGE:?}" "${DIGEST:?}" "${RELEASE:?}" "${RESULT_VERSION:?}" "${RESULT_DIGEST:?}"

case $SITE_COMMIT in
  *[!0-9a-f]*) refuse "$SITE_COMMIT is not a commit hash" ;;
esac
[ "${#SITE_COMMIT}" -eq 40 ] || refuse "$SITE_COMMIT is not a full commit hash"
case $DIGEST in
  sha256:*) ;;
  *) refuse "$DIGEST is not an image digest" ;;
esac
hex=${DIGEST#sha256:}
case $hex in
  *[!0-9a-f]*) refuse "$DIGEST is not an image digest" ;;
esac
[ "${#hex}" -eq 64 ] || refuse "$DIGEST is not an image digest"
for name in "$IMAGE" "$RELEASE"; do
  case $name in
    */*) ;;
    *) refuse "$name names no repository under a registry" ;;
  esac
  case $name in
    *[!a-z0-9./:_-]*) refuse "$name is not a registry and a repository" ;;
  esac
done
case $LAYER in
  '' | *[!a-z0-9-]*) refuse "'$LAYER' is not the name of a directory under cluster/" ;;
esac

label=$(printf '%s' "$SITE_COMMIT" | cut -c 1-8)
tree=$WORK/artifact

overlay() {
  cat <<OVERLAY
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../cluster/$LAYER
images:
  - name: $IMAGE
    digest: $DIGEST
patches:
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /metadata/annotations/fabric.chuggy.dev~1source-commit
        value: "$label"
OVERLAY
}

# A render with everything the overlay is allowed to write taken out: the
# annotation's line, an `annotations:` key left holding nothing, and the
# digest or tag of an image line naming the image.
without_what_the_overlay_writes() {
  awk -v image="$IMAGE" '
    function indent(line) { match(line, /^ */); return RLENGTH }
    function release() { if (held != "") print held; held = "" }
    /^ +fabric\.chuggy\.dev\/source-commit: / { next }
    held != "" && indent($0) <= indent(held) { held = "" }
    { release() }
    /^ +annotations:$/ { held = $0; next }
    match($0, /^ +(- )?image: /) {
      rest = substr($0, RLENGTH + 1)
      if (rest == image || index(rest, image "@") == 1 || index(rest, image ":") == 1) {
        print substr($0, 1, RLENGTH) image; next
      }
    }
    { print }
    END { release() }
  '
}

# What a render with the overlay must be, read off that render alone. Prints
# how many image lines it carries, and exits non-zero having said what is
# wrong.
held_to_this_release() {
  awk -v layer="$LAYER" -v label="$label" -v image="$IMAGE" -v digest="$DIGEST" '
    function wrong(message) { print "publish: " layer ": " message > "/dev/stderr"; bad = 1 }
    # True when the line names the image as a whole reference anywhere in
    # it, and not only as the start of a longer one.
    function names(line,    at) {
      while ((at = index(line, image)) > 0) {
        line = substr(line, at + length(image))
        if (line !~ /^[A-Za-z0-9._\/-]/) return 1
      }
      return 0
    }
    /^kind: Deployment$/ { deployments++ }
    /^ +fabric\.chuggy\.dev\/source-commit: / {
      annotated++
      value = $2
      gsub(/["\047]/, "", value)
      if (value != label) wrong("an object is annotated " $0 ", not " label)
    }
    {
      if (names($0)) {
        if (match($0, /^ +(- )?image: /) && substr($0, RLENGTH + 1) == image "@" digest) lines++
        else wrong("this line names " image " and is not an image line at " digest ": " $0)
      }
    }
    END {
      if (annotated != deployments)
        wrong(deployments + 0 " Deployments carry " annotated + 0 " source-commit annotations")
      print lines + 0
      exit bad
    }
  '
}

# Every tag of the release repository, one a line. A repository the registry
# does not have yet has none.
tags() {
  answer=$(wget -q -S -O "$WORK/tags" "http://${RELEASE%%/*}/v2/${RELEASE#*/}/tags/list" 2>&1) || true
  status=$(printf '%s\n' "$answer" | sed -n 's/^ *HTTP\/[0-9.]* \([0-9][0-9][0-9]\).*/\1/p' | tail -n 1)
  case $status in
    200) ;;
    404) return 0 ;;
    *) refuse "the registry did not list the tags of $RELEASE: $answer" ;;
  esac
  if printf '%s\n' "$answer" | grep -i '^ *link:' >/dev/null; then
    refuse "the registry listed part of the tags of $RELEASE and a link to the rest"
  fi
  body=$(tr -d ' \t\r\n' < "$WORK/tags")
  opening="{\"name\":\"${RELEASE#*/}\",\"tags\":"
  case $body in
    "$opening"'null}' | "$opening"'[]}') return 0 ;;
    "$opening"'["'*'"]}') ;;
    *) refuse "the registry answered the tag list of $RELEASE with $body" ;;
  esac
  listed=${body#"$opening"}
  listed=${listed#'["'}
  listed=${listed%'"]}'}
  printf '%s\n' "$listed" | sed 's/","/ /g' | tr ' ' '\n'
}

[ -f "$SOURCE/cluster/$LAYER/kustomization.yaml" ] ||
  refuse "the fabric commit carries no cluster/$LAYER/kustomization.yaml"
mkdir -p "$tree/cluster" "$tree/release/$LAYER"
cp -R "$SOURCE/cluster/$LAYER" "$tree/cluster/$LAYER"
overlay > "$tree/release/$LAYER/kustomization.yaml"

kubectl kustomize "$tree/cluster/$LAYER" > "$WORK/without.yaml"
kubectl kustomize "$tree/release/$LAYER" > "$WORK/with.yaml"
without_what_the_overlay_writes < "$WORK/without.yaml" > "$WORK/without.held"
without_what_the_overlay_writes < "$WORK/with.yaml" > "$WORK/with.held"
if ! cmp -s "$WORK/without.held" "$WORK/with.held"; then
  diff "$WORK/without.held" "$WORK/with.held" >&2 || true
  refuse "the overlay changes more of cluster/$LAYER than image lines and the source-commit annotation"
fi
lines=$(held_to_this_release < "$WORK/with.yaml") ||
  refuse "release/$LAYER is not one release of $SITE_COMMIT"
[ "$lines" -gt 0 ] || refuse "nothing in cluster/$LAYER runs $IMAGE"
echo "publish: the overlay writes $lines image lines for $IMAGE, and nothing else but the annotation"

seconds=$(date +%s)
version=$seconds.0.0
listed=$(tags)
ahead=$(printf '%s\n' "$listed" | awk -v seconds="$seconds" '
  /^v?[0-9]+\.[0-9]+\.[0-9]+/ {
    major = $0
    sub(/^v/, "", major)
    sub(/\..*/, "", major)
    if (major + 0 >= seconds + 0) print
  }')
[ -z "$ahead" ] ||
  refuse "version $version is not above every version $RELEASE holds, and the source selects the highest: $(echo $ahead)"

pushed=$(flux push artifact "oci://$RELEASE:$version" \
  --path "$tree" \
  --source "$SITE_URL" \
  --revision "main@sha1:$SITE_COMMIT" \
  --reproducible \
  --output json)
digest=$(printf '%s' "$pushed" | tr -d ' \t\r\n' | sed -n 's/.*"digest":"\(sha256:[0-9a-f]\{64\}\)".*/\1/p')
[ -n "$digest" ] || refuse "flux pushed $RELEASE:$version and reported no digest: $pushed"
flux tag artifact "oci://$RELEASE:$version" --tag "$SITE_COMMIT"

echo "publish: $RELEASE:$version is $digest, also tagged $SITE_COMMIT"
printf '%s' "$version" > "$RESULT_VERSION"
printf '%s' "$digest" > "$RESULT_DIGEST"
