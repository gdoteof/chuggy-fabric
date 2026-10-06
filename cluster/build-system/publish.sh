#!/bin/sh
# One release as one OCI artifact: the fabric's two release directories as
# `fetch.sh` checked them out, and beside them an overlay that writes in what
# this run built.
#
# The second step of `publish-release` runs this. Flux's `chuggy-release`
# source selects the artifact by its version, and a layer that reads it
# applies `./release/<directory>`.
#
# THE OVERLAY IS BESIDE THE FABRIC'S FILES, NOT IN THEM.
# `release/<directory>/kustomization.yaml` names `../../cluster/<directory>`
# as its one resource and carries the two image digests, the source-commit
# annotation and, for the migration, the Job's name. A block appended to the
# fabric's own kustomization would silently replace an `images` or `patches`
# key that file came to have.
#
# THE ANNOTATION IS ADDED BY KIND. Selecting the objects that already carry
# it selects none once git stops carrying it, and renders without complaint.
# Its value is quoted because the first characters of a hash can read as a
# number, and an annotation that is a number is an object the API server
# refuses.
#
# WHAT THE OVERLAY MAY CHANGE IS HELD, AND SO IS WHAT IT MUST. Each directory
# is rendered without the overlay and with it, and the two renders have to be
# the same bytes once the overridden image lines, that annotation and the
# Job's name are taken out of both: an artifact that rendered one object fewer
# would have the layer prune it. Then the render with the overlay is read
# alone. Every line naming either image is an image line at the digest this
# run was given, so a place the overlay cannot write -- a value, a string in a
# configuration -- is a refusal and not a second digest in one release. Every
# Deployment, CronJob and Job carries the annotation once and nothing carries
# another value of it. The release has one Job, the migration's, under this
# commit's name.
#
# THE VERSION IS THE CLOCK, AND ITS FIRST NUMBER MUST BE THE HIGHEST. The
# source takes the highest tag that is a semantic version and skips every
# other tag without a word, so the version is `<seconds>.0.0`, which is one.
# A tag here that could be a version and whose first number is not below this
# one's -- a tie, a clock that was ahead once, a clock that is behind now --
# fails the run: published beside it, this release is one the source would
# not select, or one that takes another's tag. Such a tag is deleted from the
# registry only to undo a version taken from a wrong clock, and the registry
# deletes by digest: every tag of that release goes with it, and the source
# selects the release before until another is published.
#
# THE TAG LIST IS READ WHOLE OR THE RUN FAILS. A body that is not the list
# the registry documents, or a list it says continues, reads as "nothing
# higher" to anything looser.
#
# THE COMMIT IS A TAG AS WELL, added after the push. It is not a version, so
# the source ignores it; it is the name a person asks the registry for.
set -eu

refuse() {
  echo "publish: $*" >&2
  exit 1
}

: "${SOURCE:?}" "${WORK:?}" "${CHUGGY_URL:?}" "${CHUGGY_COMMIT:?}"
: "${API_IMAGE:?}" "${API_DIGEST:?}" "${CONSOLE_IMAGE:?}" "${CONSOLE_DIGEST:?}"
: "${RELEASE:?}" "${RESULT_VERSION:?}" "${RESULT_DIGEST:?}"

case $CHUGGY_COMMIT in
  *[!0-9a-f]*) refuse "$CHUGGY_COMMIT is not a commit hash" ;;
esac
[ "${#CHUGGY_COMMIT}" -eq 40 ] || refuse "$CHUGGY_COMMIT is not a full commit hash"
for digest in "$API_DIGEST" "$CONSOLE_DIGEST"; do
  case $digest in
    sha256:*) ;;
    *) refuse "$digest is not an image digest" ;;
  esac
  hex=${digest#sha256:}
  case $hex in
    *[!0-9a-f]*) refuse "$digest is not an image digest" ;;
  esac
  [ "${#hex}" -eq 64 ] || refuse "$digest is not an image digest"
done
for name in "$API_IMAGE" "$CONSOLE_IMAGE" "$RELEASE"; do
  case $name in
    */*) ;;
    *) refuse "$name names no repository under a registry" ;;
  esac
  case $name in
    *[!a-z0-9./:_-]*) refuse "$name is not a registry and a repository" ;;
  esac
done
[ "$API_IMAGE" != "$CONSOLE_IMAGE" ] || refuse "the two images have one name, $API_IMAGE"

label=$(printf '%s' "$CHUGGY_COMMIT" | cut -c 1-8)
job=chuggy-migrate-$label-registry
tree=$WORK/artifact

overlay() {
  cat <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../cluster/$1
images:
  - name: $API_IMAGE
    digest: $API_DIGEST
  - name: $CONSOLE_IMAGE
    digest: $CONSOLE_DIGEST
patches:
  - target:
      kind: (Deployment|CronJob|Job)
    patch: |-
      - op: add
        path: /metadata/annotations/fabric.chuggy.dev~1source-commit
        value: "$label"
EOF
  [ "$1" != chuggy-migrate ] || cat <<EOF
  - target:
      kind: Job
    patch: |-
      - op: replace
        path: /metadata/name
        value: $job
EOF
}

# A render with everything the overlay is allowed to write taken out: the
# annotation's line, an `annotations:` key left holding nothing, the digest or
# tag of an image line naming either image, and a Job's name.
without_what_the_overlay_writes() {
  awk -v api="$API_IMAGE" -v console="$CONSOLE_IMAGE" '
    function indent(line) { match(line, /^ */); return RLENGTH }
    function release() { if (held != "") print held; held = "" }
    /^ +fabric\.chuggy\.dev\/source-commit: / { next }
    held != "" && indent($0) <= indent(held) { held = "" }
    { release() }
    /^---$/ { kind = ""; metadata = 0 }
    /^[^ ]/ { metadata = ($0 == "metadata:") }
    /^kind: / { kind = $2 }
    /^ +annotations:$/ { held = $0; next }
    kind == "Job" && metadata && /^  name: / { print "  name: <the Job of this release>"; next }
    match($0, /^ +(- )?image: /) {
      rest = substr($0, RLENGTH + 1)
      if (rest == api || index(rest, api "@") == 1 || index(rest, api ":") == 1) {
        print substr($0, 1, RLENGTH) api; next
      }
      if (rest == console || index(rest, console "@") == 1 || index(rest, console ":") == 1) {
        print substr($0, 1, RLENGTH) console; next
      }
    }
    { print }
    END { release() }
  '
}

# What a render with the overlay must be, read off that render alone. Prints
# how many image lines it carries for each image, and exits non-zero having
# said what is wrong.
held_to_this_release() {
  awk -v directory="$1" -v label="$label" -v job="$job" \
    -v api="$API_IMAGE" -v api_digest="$API_DIGEST" \
    -v console="$CONSOLE_IMAGE" -v console_digest="$CONSOLE_DIGEST" '
    function wrong(message) { print "publish: " directory ": " message > "/dev/stderr"; bad = 1 }
    # True when the line names the image as a whole reference anywhere in
    # it, and not only as the start of a longer one.
    function names(line, image,    at) {
      while ((at = index(line, image)) > 0) {
        line = substr(line, at + length(image))
        if (line !~ /^[A-Za-z0-9._\/-]/) return 1
      }
      return 0
    }
    function image_line(image, digest,    rest) {
      if (!names($0, image)) return
      if (match($0, /^ +(- )?image: /)) {
        rest = substr($0, RLENGTH + 1)
        if (rest == image "@" digest) { lines[image]++; return }
      }
      wrong("this line names " image " and is not an image line at " digest ": " $0)
    }
    /^---$/ { kind = ""; metadata = 0 }
    /^[^ ]/ { metadata = ($0 == "metadata:") }
    /^kind: / { kind = $2 }
    /^kind: (Deployment|CronJob|Job)$/ { workloads++ }
    /^kind: Job$/ { jobs++ }
    kind == "Job" && metadata && /^  name: / {
      if ($2 != job) wrong("its Job is named " $2 ", not " job)
    }
    /^ +fabric\.chuggy\.dev\/source-commit: / {
      annotated++
      value = $2
      gsub(/["\047]/, "", value)
      if (value != label) wrong("an object is annotated " $0 ", not " label)
    }
    { image_line(api, api_digest); image_line(console, console_digest) }
    END {
      if (annotated != workloads)
        wrong(workloads + 0 " Deployments, CronJobs and Jobs carry " annotated + 0 " source-commit annotations")
      if (directory == "chuggy-migrate" && jobs != 1) wrong("it renders " jobs + 0 " Jobs, not the one migration")
      if (directory != "chuggy-migrate" && jobs != 0) wrong("it renders a Job this overlay does not name")
      print lines[api] + 0, lines[console] + 0
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

mkdir -p "$tree/cluster"
api_lines=0
console_lines=0
for directory in chuggy-migrate chuggy; do
  [ -f "$SOURCE/cluster/$directory/kustomization.yaml" ] ||
    refuse "the fabric commit carries no cluster/$directory/kustomization.yaml"
  cp -R "$SOURCE/cluster/$directory" "$tree/cluster/$directory"
  mkdir -p "$tree/release/$directory"
  overlay "$directory" > "$tree/release/$directory/kustomization.yaml"

  kubectl kustomize "$tree/cluster/$directory" > "$WORK/$directory.without.yaml"
  kubectl kustomize "$tree/release/$directory" > "$WORK/$directory.with.yaml"
  without_what_the_overlay_writes < "$WORK/$directory.without.yaml" > "$WORK/$directory.without.held"
  without_what_the_overlay_writes < "$WORK/$directory.with.yaml" > "$WORK/$directory.with.held"
  if ! cmp -s "$WORK/$directory.without.held" "$WORK/$directory.with.held"; then
    diff "$WORK/$directory.without.held" "$WORK/$directory.with.held" >&2 || true
    refuse "the overlay changes more of cluster/$directory than image lines, the source-commit annotation and the Job's name"
  fi
  counted=$(held_to_this_release "$directory" < "$WORK/$directory.with.yaml") ||
    refuse "release/$directory is not one release of $CHUGGY_COMMIT"
  api_lines=$((api_lines + ${counted% *}))
  console_lines=$((console_lines + ${counted#* }))
done
[ "$api_lines" -gt 0 ] || refuse "nothing in the release runs $API_IMAGE"
[ "$console_lines" -gt 0 ] || refuse "nothing in the release runs $CONSOLE_IMAGE"
echo "publish: the overlay writes $api_lines image lines for $API_IMAGE and $console_lines for $CONSOLE_IMAGE, and nothing else but the annotation and the Job's name"

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
  --source "$CHUGGY_URL" \
  --revision "main@sha1:$CHUGGY_COMMIT" \
  --reproducible \
  --insecure-registry \
  --output json)
digest=$(printf '%s' "$pushed" | tr -d ' \t\r\n' | sed -n 's/.*"digest":"\(sha256:[0-9a-f]\{64\}\)".*/\1/p')
[ -n "$digest" ] || refuse "flux pushed $RELEASE:$version and reported no digest: $pushed"
flux tag artifact "oci://$RELEASE:$version" --tag "$CHUGGY_COMMIT"

echo "publish: $RELEASE:$version is $digest, also tagged $CHUGGY_COMMIT"
printf '%s' "$version" > "$RESULT_VERSION"
printf '%s' "$digest" > "$RESULT_DIGEST"
