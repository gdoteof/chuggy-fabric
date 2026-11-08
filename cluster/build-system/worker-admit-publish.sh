#!/bin/sh
# Step three of the worker admission: the pull request, opened and merged.
#
# The only step with the GitHub token, and it runs nothing the checkout wrote:
# it reads what worker-admit-prepare.sh left under IN as regular files, and
# speaks to the GitHub API with curl. There is no `git push`, so no hook or
# configuration a checkout carries is run beside the token. The branch is made
# and the file written through the API, as the App, so the commit is the App's.
#
# WHAT IT DOES, IN ORDER, AND EACH IS SAFE TO REPEAT:
# - no `ready` marker is nothing to admit, and succeeds;
# - an open pull request for the branch is resumed, and not opened again; a
#   branch with no open pull request is a pull request a person closed or one
#   merged, and is left alone, so a rejected admission is not made again until
#   the branch is deleted;
# - otherwise `main` must still be the commit the change was made against:
#   the branch is created at it, the file written to it with the blob it was
#   made from, and the pull request opened;
# - then `main` must still be that commit, and the pull request is merged at
#   the head it was opened at.
#
# A MERGE THAT CANNOT BE MADE IS NOT FORCED. If `main` moved, or the pull
# request conflicts, the pull request is closed and the branch deleted, and the
# next run makes the change over `main` as it is. A merge refused for any other
# reason is a failure, and the pull request is left open for the next run to
# resume.
#
# THE TOKEN IS A FILE, never an argument or a message: it is written into a
# curl configuration under a private umask, and no response is printed.
#
# NOT HANDLED: `main` moving between the second check and the merge, which the
# merge does not ask about, merges the change over that commit; GitHub
# conflicts it if the same lines moved and does not otherwise.
set -eu

: "${IN:?}" "${REPOSITORY:?}" "${TOKEN:?}" "${API:?}"

say() {
  echo "worker-admit: $*"
}

refuse() {
  echo "worker-admit: $*" >&2
  exit 1
}

[ -f "$IN/ready" ] || { say "nothing to admit"; exit 0; }
[ -r "$TOKEN" ] || refuse "no token at $TOKEN: the App's token is not delivered"

# Only regular files, and never through a link.
for name in branch path blob base version target message content; do
  [ -f "$IN/$name" ] && [ ! -L "$IN/$name" ] || refuse "$IN/$name is not a regular file"
done
branch=$(cat "$IN/branch")
path=$(cat "$IN/path")
blob=$(cat "$IN/blob")
base=$(cat "$IN/base")
version=$(cat "$IN/version")
target=$(cat "$IN/target")
case $branch in
  admit/worker-*[!0-9a-f]* | admit/worker- | "") refuse "branch '$branch' is not one this makes" ;;
  admit/worker-????????????) ;;
  *) refuse "branch '$branch' is not one this makes" ;;
esac
case /$path/$target/ in
  */../* | //* | *//*) refuse "path or target is not a plain relative name" ;;
esac
case $path$target in
  *[!A-Za-z0-9/._-]* | "") refuse "path or target holds a character this does not pass to a URL" ;;
esac
case $blob$base in
  *[!0-9a-f]*) refuse "blob or base is not a hash" ;;
esac

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
umask 077
{
  printf 'header = "Authorization: Bearer %s"\n' "$(tr -d '\n' < "$TOKEN")"
  printf 'header = "Accept: application/vnd.github+json"\n'
  printf 'header = "X-GitHub-Api-Version: 2022-11-28"\n'
} > "$work/curl.conf"

# api METHOD PATH [BODY_FILE]: the status is printed and the body is left in
# $work/response.json.
api() {
  if [ -n "${3:-}" ]; then
    curl --silent --show-error --config "$work/curl.conf" --request "$1" \
      --header 'Content-Type: application/json' --data-binary "@$3" \
      --output "$work/response.json" --write-out '%{http_code}' "$API/repos/$REPOSITORY$2"
  else
    curl --silent --show-error --config "$work/curl.conf" --request "$1" \
      --output "$work/response.json" --write-out '%{http_code}' "$API/repos/$REPOSITORY$2"
  fi
}

expect() {
  status=$(api "$2" "$3" "${4:-}")
  case " $1 " in
    *" $status "*) ;;
    *) refuse "$2 $3 answered $status: $(jq -r '.message // empty' "$work/response.json" 2> /dev/null | head -c 300)" ;;
  esac
}

main_commit() {
  expect 200 GET "/git/ref/heads/$target"
  jq -er '.object.sha' "$work/response.json"
}

abandon() {
  say "$1: closing pull request ${2:-none} and deleting $branch"
  if [ -n "${2:-}" ]; then
    printf '{"state":"closed"}' > "$work/body.json"
    expect 200 PATCH "/pulls/$2" "$work/body.json"
  fi
  expect "204 422" DELETE "/git/refs/heads/$branch"
  exit 1
}

merge() {
  number=$1 head=$2
  [ "$(main_commit)" = "$base" ] || abandon "$target moved off $base" "$number"
  jq -n --arg sha "$head" '{merge_method: "merge", sha: $sha}' > "$work/body.json"
  answered=$(api PUT "/pulls/$number/merge" "$work/body.json")
  case $answered in
    200) say "merged pull request $number: worker $version is admitted" ;;
    405 | 409)
      expect 200 GET "/pulls/$number"
      if [ "$(jq -r '.mergeable_state' "$work/response.json")" = dirty ]; then
        abandon "pull request $number conflicts" "$number"
      fi
      refuse "pull request $number is not mergeable ($answered): $(jq -r '.message // empty' "$work/response.json" | head -c 300)"
      ;;
    *) refuse "merging pull request $number answered $answered" ;;
  esac
}

owner=${REPOSITORY%%/*}

# An open pull request for the branch is resumed.
expect 200 GET "/pulls?state=open&head=$owner:$branch"
open=$(jq -r '.[0] | if . == null then "" else "\(.number) \(.head.sha)" end' "$work/response.json")
if [ -n "$open" ]; then
  # shellcheck disable=SC2086
  set -- $open
  say "pull request $1 is open for $branch: resuming"
  merge "$1" "$2"
  exit 0
fi

status=$(api GET "/git/ref/heads/$branch")
if [ "$status" = 200 ]; then
  say "$branch exists with no open pull request: left alone"
  exit 0
fi
[ "$status" = 404 ] || refuse "GET the ref of $branch answered $status"

[ "$(main_commit)" = "$base" ] || { say "$target moved off $base: the next run makes the change over it"; exit 0; }

jq -n --arg ref "refs/heads/$branch" --arg sha "$base" '{ref: $ref, sha: $sha}' > "$work/body.json"
expect 201 POST /git/refs "$work/body.json"

jq -n --rawfile message "$IN/message" --arg branch "$branch" --arg blob "$blob" \
  --rawfile content "$IN/content" \
  '{message: $message, branch: $branch, sha: $blob, content: ($content | @base64)}' > "$work/body.json"
written=$(api PUT "/contents/$path" "$work/body.json")
if [ "$written" != 200 ]; then
  expect "204 422" DELETE "/git/refs/heads/$branch"
  refuse "writing $path on $branch answered $written"
fi
head=$(jq -er '.commit.sha' "$work/response.json")

title=$(sed -n 1p "$IN/message")
jq -n --arg title "$title" --arg head "$branch" --arg base "$target" --rawfile body "$IN/message" \
  '{title: $title, head: $head, base: $base, body: $body}' > "$work/body.json"
expect 201 POST /pulls "$work/body.json"
number=$(jq -er '.number' "$work/response.json")
say "opened pull request $number for $branch"
merge "$number" "$head"
