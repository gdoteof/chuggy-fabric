#!/usr/bin/env bash
# What `scripts/publish-build-results` does to a repository, run against a real
# one rather than read off the script.
#
# The publisher is the only thing in this tree that pushes to the branch Flux
# follows without a person in the loop, and its failure modes are all silent:
# a run that overwrites a record replaces provenance with different provenance
# under the same name, a run that deletes takes history with it, and a run that
# commits when it had nothing to publish puts a commit on the live branch every
# few minutes forever. None of those is visible in the script's exit status, so
# each is a case below, and each is checked by looking at what arrived in the
# remote -- not at what the script printed.
#
# THE REMOTE IS A BARE REPOSITORY OVER `file://` and the records are made the way
# `record-build-provenance` makes them: canonical payload, digest of the payload
# inside the record, checksum of the record beside it. So a case that says
# "refused" is refused by the same arithmetic the recorder and the verifier use,
# and a published record is one `tests/build-results.py` accepts -- which the
# last case runs over a fresh clone rather than asserting.
#
# THE TOKEN IS A STRING NOTHING ELSE IN THE BUILD KNOWS, so the two assertions
# that it never reaches the clone or the history are greps and not judgement.
# The askpass port is exercised on the push itself: the wrapper below asks the
# port for both answers git would ask for, which is also what proves the
# trailing newline of the Secret's value is stripped rather than pushed.
set -o errexit -o nounset -o pipefail

root=${1:?root is required}
scripts=${2:?scripts directory is required}
work=$PWD

export HOME="$work/home"
export PATH="$work/bin:$PATH"
mkdir -p "$HOME" "$work/bin" "$work/host-records" "$work/rendered" "$work/run"

token='installation-token-nothing-else-in-this-build-knows'
export EXPECT_SECRET=example-github-finalizer-token
export EXPECT_NAMESPACE=chuggy
export EXPECT_TOKEN="$token"
export ASKPASS_USERNAME="$work/askpass-username"
export ASKPASS_PASSWORD="$work/askpass-password"

# The stubs are written with the interpreter and the git this build actually
# has: there is no /usr/bin/env in the sandbox, and the wrapper's own name must
# not decide which git it runs.
bash_command=$(command -v bash)
git_command=$(command -v git)

stub() {
  printf '#!%s\n' "$bash_command" > "$work/bin/$1"
  cat >> "$work/bin/$1"
  chmod 0755 "$work/bin/$1"
}

stub kubectl <<'STUB'
set -o errexit -o nounset -o pipefail
test "$1" = --kubeconfig
test "$3" = --namespace
test "$4" = "$EXPECT_NAMESPACE"
test "$5" = get
test "$6" = secret
test "$7" = "$EXPECT_SECRET"
test "$8" = -o
# The refresher stores the value the API returned, newline and all. A Secret
# whose key is not there yet answers with nothing, which is what jsonpath does
# with a missing field.
test -z "${EMPTY_TOKEN:-}" || exit 0
printf '%s\n' "$EXPECT_TOKEN" | base64 -w0
STUB

stub git-observed <<STUB
set -o errexit -o nounset -o pipefail
test -n "\${GIT_ASKPASS:-}"
test -x "\$GIT_ASKPASS"
test "\${GIT_TERMINAL_PROMPT:-}" = 0
case " \$* " in
  *' push '*)
    "\$GIT_ASKPASS" "Username for 'https://github.com': " > "\$ASKPASS_USERNAME"
    "\$GIT_ASKPASS" "Password for 'https://x-access-token@github.com': " > "\$ASKPASS_PASSWORD"
    ;;
esac
exec $git_command "\$@"
STUB

stub git-reject <<STUB
set -o errexit -o nounset -o pipefail
case " \$* " in
  *' push '*) echo 'simulated rejection' >&2; exit 1 ;;
  *) exec $git_command "\$@" ;;
esac
STUB

fixture=(git -c user.name=fixture -c user.email=fixture@invalid)

render() {
  "$scripts/render-build-request" \
    --repository-id example-service \
    --source-url https://git.example.com/team/example-service.git \
    --source-commit "$1" \
    --source-secret example-source-read \
    --target-image-repository registry.example.internal/team/example-service \
    --output-secret example-registry-push \
    --profile mini \
    --output-root "$work/rendered"
}

# One host record for a rendered request, made the way the recorder makes one.
# It prints the attempt name; the record is under the request digest directory
# the recorder would have used.
make_record() {
  local manifest=$1 request commit target renderer controller profile profile_digest
  local attempt directory
  request=$(grep -m1 -F 'fabric.chuggy.dev/request-digest:' "$manifest" | awk '{print $2}')
  commit=$(grep -m1 -F 'fabric.chuggy.dev/source-commit:' "$manifest" | awk '{print $2}')
  target=$(grep -m1 -F 'fabric.chuggy.dev/target-image-repository:' "$manifest" | awk '{print $2}' | tr -d '"')
  renderer=$(grep -m1 -F 'fabric.chuggy.dev/renderer:' "$manifest" | awk '{print $2}')
  controller=$(grep -m1 -F 'fabric.chuggy.dev/shipwright-version:' "$manifest" | awk '{print $2}')
  profile=$(grep -m1 -F 'fabric.chuggy.dev/profile:' "$manifest" | awk '{print $2}')
  profile_digest=$(grep -m1 -F 'fabric.chuggy.dev/profile-digest:' "$manifest" | awk '{print $2}')
  attempt="build-${request#sha256:}"
  attempt="${attempt:0:46}-a1"
  directory="$work/host-records/$request"
  mkdir -p "$directory"
  jq -nS --arg request "$request" --arg attempt "$attempt" --arg commit "$commit" \
    --arg target "$target" --arg renderer "$renderer" --arg controller "$controller" \
    --arg profile "$profile" --arg profileDigest "$profile_digest" '{
      attempt: {name: $attempt, ordinal: 1},
      controller: $controller,
      output: {digest: "sha256:2c1cd2f0c4b8a4d4c6f5e3b1a09f8e7d6c5b4a39281706f5e4d3c2b1a0998877", repository: $target},
      profile: {digest: $profileDigest, name: $profile},
      renderer: $renderer,
      requestDigest: $request,
      source: {observedCommit: $commit, repositoryId: "example-service", requestedCommit: $commit},
      terminalCondition: {
        lastTransitionTime: "2026-01-01T00:00:00Z",
        message: "All Steps have completed executing",
        reason: "Succeeded",
        status: "True",
        type: "Succeeded"
      },
      timestamps: {completed: "2026-01-01T00:00:00Z", started: "2026-01-01T00:00:00Z"}
    }' > "$work/payload"
  jq -nS --arg digest "$(sha256sum "$work/payload" | awk '{print "sha256:" $1}')" \
    --slurpfile result "$work/payload" \
    '{provenanceRecordDigest: $digest, result: $result[0]}' > "$directory/$attempt.json"
  sha256sum "$directory/$attempt.json" | awk '{print "sha256:" $1}' > "$directory/$attempt.json.sha256"
  printf '%s\n' "$attempt"
}

publish() {
  rm -rf "$work/run"
  mkdir -p "$work/run"
  env RESULTS_PATH="${RESULTS_UNDER_TEST:-$work/host-records}" \
    REPOSITORY_URL="file://$work/${REPOSITORY_UNDER_TEST:-origin.git}" \
    BRANCH=main \
    CLONE_PATH="$work/clone" \
    TOKEN_SECRET="$EXPECT_SECRET" \
    TOKEN_NAMESPACE="$EXPECT_NAMESPACE" \
    AUTHOR_NAME='chuggy-fabric build results' \
    AUTHOR_EMAIL=noreply@invalid \
    KUBECTL="$work/bin/kubectl" \
    GIT="${GIT_UNDER_TEST:-$work/bin/git-observed}" \
    RUNTIME_DIRECTORY="$work/run" \
    "$scripts/publish-build-results"
}

tip() {
  git -C "$work/origin.git" rev-parse refs/heads/main
}

land() {
  git -C "$work/seed" fetch --quiet origin main
  git -C "$work/seed" reset --quiet --hard origin/main
  cp -R "$work/staging/." "$work/seed/"
  git -C "$work/seed" add -A
  "${fixture[@]}" -C "$work/seed" commit --quiet -m "$1"
  git -C "$work/seed" push --quiet origin main
  rm -rf "$work/staging"
}

# ---------------------------------------------------------------- fixtures ---

git init --quiet --bare -b main "$work/origin.git"
git init --quiet -b main "$work/seed"
git -C "$work/seed" remote add origin "file://$work/origin.git"

commit_a=1111111111111111111111111111111111111111
commit_b=2222222222222222222222222222222222222222
commit_c=3333333333333333333333333333333333333333
commit_d=4444444444444444444444444444444444444444
commit_e=5555555555555555555555555555555555555555
commit_f=6666666666666666666666666666666666666666
for commit in "$commit_a" "$commit_b" "$commit_c" "$commit_d" "$commit_e" "$commit_f"; do
  render "$commit" >/dev/null
done
manifest_for() {
  echo "$work/rendered/builds/example-service/$1/$(ls "$work/rendered/builds/example-service/$1")"
}

mkdir -p "$work/seed/docs"
printf 'this file is nothing to do with build results\n' > "$work/seed/docs/keep-me"
mkdir -p "$work/seed/builds/example-service"
for commit in "$commit_a" "$commit_b" "$commit_c" "$commit_d" "$commit_f"; do
  cp -R "$work/rendered/builds/example-service/$commit" "$work/seed/builds/example-service/"
done

# C is already published and identical on the host; D is already published and
# the host holds different bytes under the same name.
attempt_c=$(make_record "$(manifest_for "$commit_c")")
attempt_d=$(make_record "$(manifest_for "$commit_d")")
request_c=$(basename "$(dirname "$(echo "$work/host-records"/*/"$attempt_c.json")")")
request_d=$(basename "$(dirname "$(echo "$work/host-records"/*/"$attempt_d.json")")")
published_c="$work/seed/results/example-service/$commit_c/${request_c#sha256:}"
published_d="$work/seed/results/example-service/$commit_d/${request_d#sha256:}"
mkdir -p "$published_c" "$published_d"
cp "$work/host-records/$request_c/$attempt_c.json" "$published_c/"
cp "$work/host-records/$request_c/$attempt_c.json.sha256" "$published_c/"
cp "$work/host-records/$request_d/$attempt_d.json" "$published_d/"
cp "$work/host-records/$request_d/$attempt_d.json.sha256" "$published_d/"
git -C "$work/seed" add -A
"${fixture[@]}" -C "$work/seed" commit --quiet -m 'fixture: requests, one unrelated file, two published results'
git -C "$work/seed" push --quiet origin main

# D's host record is not D's published record. Rewriting the payload's message
# keeps every identity the same and changes the bytes, which is the shape of the
# failure this refuses: two records claiming one attempt.
jq -S '.result | .terminalCondition.message = "All Steps have completed executing."' \
  "$work/host-records/$request_d/$attempt_d.json" > "$work/payload"
jq -nS --arg digest "$(sha256sum "$work/payload" | awk '{print "sha256:" $1}')" \
  --slurpfile result "$work/payload" '{provenanceRecordDigest: $digest, result: $result[0]}' \
  > "$work/host-records/$request_d/$attempt_d.json"
sha256sum "$work/host-records/$request_d/$attempt_d.json" | awk '{print "sha256:" $1}' \
  > "$work/host-records/$request_d/$attempt_d.json.sha256"
divergent=$(cat "$work/host-records/$request_d/$attempt_d.json")
mv "$work/host-records/$request_d" "$work/withheld-d"

# ------------------------------------------------------- an empty host run ---

base=$(tip)
mv "$work/host-records/$request_c" "$work/withheld-c"
publish
test "$(tip)" = "$base"
test ! -e "$work/clone/results/example-service/$commit_a"
mv "$work/withheld-c" "$work/host-records/$request_c"

# ----------------------------------------------- the first real publication ---

attempt_a=$(make_record "$(manifest_for "$commit_a")")
attempt_b=$(make_record "$(manifest_for "$commit_b")")
request_a=$(basename "$(dirname "$(echo "$work/host-records"/*/"$attempt_a.json")")")
request_b=$(basename "$(dirname "$(echo "$work/host-records"/*/"$attempt_b.json")")")
publish
test "$(tip)" != "$base"
test "$(git -C "$work/origin.git" rev-list --count "$base..$(tip)")" = 1

git clone --quiet "file://$work/origin.git" "$work/published"
same_as_host() {
  local commit=$1 request=$2 attempt=$3
  local published="$work/published/results/example-service/$commit/${request#sha256:}/$attempt"
  cmp "$work/host-records/$request/$attempt.json" "$published.json"
  cmp "$work/host-records/$request/$attempt.json.sha256" "$published.json.sha256"
}
same_as_host "$commit_a" "$request_a" "$attempt_a"
same_as_host "$commit_b" "$request_b" "$attempt_b"
test -f "$work/published/docs/keep-me"
cmp "$work/host-records/$request_c/$attempt_c.json" \
  "$work/published/results/example-service/$commit_c/${request_c#sha256:}/$attempt_c.json"
# What the port handed git, byte for byte. The Secret carries the newline the
# refresher wrote into it, and what reaches git is the token and none of the
# storage around it.
printf 'x-access-token\n' | cmp - "$ASKPASS_USERNAME"
printf '%s' "$token" | cmp - "$ASKPASS_PASSWORD"
test "$(git -C "$work/origin.git" log -1 --format=%an)" = 'chuggy-fabric build results'
test "$(git -C "$work/origin.git" log -1 --format=%ae)" = noreply@invalid
test "$(git -C "$work/origin.git" log -1 --format=%cn)" = 'chuggy-fabric build results'
test "$(git -C "$work/origin.git" log -1 --format=%s)" = 'publish build results'
git -C "$work/origin.git" log -1 --format=%B | grep -Fxq "$attempt_a"
git -C "$work/origin.git" log -1 --format=%B | grep -Fxq "$attempt_b"
if git -C "$work/origin.git" log -1 --format=%B | grep -Fxq "$attempt_c"; then
  echo "the publication named a record it did not publish" >&2
  exit 1
fi
added() {
  git -C "$work/origin.git" diff-tree --no-commit-id --name-only -r "$@" HEAD
}
test -z "$(added --diff-filter=a)"
test "$(added --diff-filter=A | wc -l)" = 4

# ------------------------------------------------------------ nothing to do ---

published=$(tip)
publish
test "$(tip)" = "$published"

# --------------------------------------------- a request this branch has not ---

attempt_e=$(make_record "$(manifest_for "$commit_e")")
publish 2>"$work/undeclared.log"
test "$(tip)" = "$published"
grep -Fq "$attempt_e" "$work/undeclared.log"
grep -Fq 'does not declare' "$work/undeclared.log"
request_e=$(basename "$(dirname "$(echo "$work/host-records"/*/"$attempt_e.json")")")
rm -r "$work/host-records/$request_e"

# ------------------------------------------------- a record still being written ---

attempt_f=$(make_record "$(manifest_for "$commit_f")")
request_f=$(basename "$(dirname "$(echo "$work/host-records"/*/"$attempt_f.json")")")
mv "$work/host-records/$request_f/$attempt_f.json.sha256" "$work/withheld-checksum"
publish 2>"$work/incomplete.log"
test "$(tip)" = "$published"
test ! -s "$work/incomplete.log"
mv "$work/withheld-checksum" "$work/host-records/$request_f/$attempt_f.json.sha256"

# ------------------------------------------------------- a record that changed ---

cp "$work/host-records/$request_f/$attempt_f.json" "$work/pristine-f"
printf ' ' >> "$work/host-records/$request_f/$attempt_f.json"
if publish 2>"$work/checksum.log"; then
  echo "a record whose checksum failed was published" >&2
  exit 1
fi
test "$(tip)" = "$published"
grep -Fq 'durable record checksum mismatch' "$work/checksum.log"
cp "$work/pristine-f" "$work/host-records/$request_f/$attempt_f.json"

# ------------------------------------- two records claiming one published attempt ---

mv "$work/withheld-d" "$work/host-records/$request_d"
if publish 2>"$work/divergent.log"; then
  echo "a record that differs from the published one did not fail the run" >&2
  exit 1
fi
grep -Fq "differs from this host's record" "$work/divergent.log"
git -C "$work/published" fetch --quiet origin main
git -C "$work/published" reset --quiet --hard origin/main
cmp "$work/seed/results/example-service/$commit_d/${request_d#sha256:}/$attempt_d.json" \
  "$work/published/results/example-service/$commit_d/${request_d#sha256:}/$attempt_d.json"
test "$(cat "$work/host-records/$request_d/$attempt_d.json")" = "$divergent"
# The rest of the run still published: a divergence is a finding about one
# attempt and not a reason to hold back every other record.
test -f "$work/published/results/example-service/$commit_f/${request_f#sha256:}/$attempt_f.json"
mv "$work/host-records/$request_d" "$work/withheld-d"
published=$(tip)

# ------------------------------- a copy interrupted between a record and its checksum ---

# A run killed between the two `cp`s leaves the clone holding a record with no
# checksum beside it. Nothing in Git carries it, so the next run must publish
# it -- and would instead compare the stray against the host's record forever.
commit_h=8888888888888888888888888888888888888888
render "$commit_h" >/dev/null
mkdir -p "$work/staging/builds/example-service"
cp -R "$work/rendered/builds/example-service/$commit_h" "$work/staging/builds/example-service/"
land 'fixture: a request whose record is half-copied'
published=$(tip)
attempt_h=$(make_record "$(manifest_for "$commit_h")")
request_h=$(basename "$(dirname "$(echo "$work/host-records"/*/"$attempt_h.json")")")
stray="$work/clone/results/example-service/$commit_h/${request_h#sha256:}"
mkdir -p "$stray"
cp "$work/host-records/$request_h/$attempt_h.json" "$stray/"
publish
test "$(git -C "$work/origin.git" rev-list --count "$published..$(tip)")" = 1
git -C "$work/published" fetch --quiet origin main
git -C "$work/published" reset --quiet --hard origin/main
same_as_host "$commit_h" "$request_h" "$attempt_h"
published=$(tip)

# ------------------------------------------------------------ a refused push ---

render 7777777777777777777777777777777777777777 >/dev/null
mkdir -p "$work/staging/builds/example-service"
cp -R "$work/rendered/builds/example-service/7777777777777777777777777777777777777777" \
  "$work/staging/builds/example-service/"
land 'fixture: one more request'
published=$(tip)
attempt_g=$(make_record "$(manifest_for 7777777777777777777777777777777777777777)")
request_g=$(basename "$(dirname "$(echo "$work/host-records"/*/"$attempt_g.json")")")
if GIT_UNDER_TEST="$work/bin/git-reject" publish 2>"$work/rejected.log"; then
  echo "a refused push reported success" >&2
  exit 1
fi
test "$(tip)" = "$published"
grep -Fq 'push to main failed' "$work/rejected.log"
publish
test "$(git -C "$work/origin.git" rev-list --count "$published..$(tip)")" = 1
git -C "$work/published" fetch --quiet origin main
git -C "$work/published" reset --quiet --hard origin/main
cmp "$work/host-records/$request_g/$attempt_g.json" \
  "$work/published/results/example-service/7777777777777777777777777777777777777777/${request_g#sha256:}/$attempt_g.json"

# ------------------------------------------------- a record that is not its path ---

# The recorder refuses to write any of these, so each is a record edited by hand
# under a name that no longer describes it. The publisher builds a path out of
# three of these fields, which is why the repository id below is a traversal and
# not merely a wrong name.
zeros=0000000000000000000000000000000000000000
refused() {
  local expression=$1 directory=$2 filename=$3 message=$4 before
  before=$(tip)
  rm -rf "$work/malformed"
  mkdir -p "$work/malformed/$directory"
  jq "$expression" "$work/host-records/$request_a/$attempt_a.json" > "$work/malformed/$directory/$filename"
  sha256sum "$work/malformed/$directory/$filename" | awk '{print "sha256:" $1}' \
    > "$work/malformed/$directory/$filename.sha256"
  if RESULTS_UNDER_TEST="$work/malformed" publish 2>"$work/malformed.log"; then
    echo "a record that is not its path was accepted: $message" >&2
    exit 1
  fi
  grep -Fq "$message" "$work/malformed.log"
  test "$(tip)" = "$before"
}

refused ".result.attempt.name = \"build-$zeros-a1\"" \
  "$request_a" "$attempt_a.json" 'the record names attempt'
refused ".result.requestDigest = \"sha256:$zeros$zeros$zeros${zeros:0:4}\"" \
  "$request_a" "$attempt_a.json" "the record's request digest is not its directory"
refused ".result.attempt.name = \"Build-$zeros-a1\"" \
  "$request_a" "Build-$zeros-a1.json" 'invalid attempt name'
refused '.result.source.repositoryId = "../escape"' \
  "$request_a" "$attempt_a.json" 'invalid source repository id'
test ! -e "$work/clone/results/escape"
test ! -e "$work/clone/escape"
refused '.result.source.requestedCommit = "not-a-commit"' \
  "$request_a" "$attempt_a.json" 'invalid requested commit'
refused . 'sha256:not-a-digest' "$attempt_a.json" 'not a request digest directory'

# ------------------------------------------------------- a Secret with no token ---

before=$(tip)
if EMPTY_TOKEN=1 publish 2>"$work/empty-token.log"; then
  echo "a Secret carrying no token reported success" >&2
  exit 1
fi
test "$(tip)" = "$before"
grep -Fq 'carries no token' "$work/empty-token.log"

# ------------------------------------------------------- a repository that moved ---

# The host names the repository and the branch, so both can change under a clone
# that already exists. A run that kept following the old remote would report
# success and publish nothing where anyone is looking.
git clone --quiet --bare "file://$work/origin.git" "$work/moved.git"
commit_i=9999999999999999999999999999999999999999
render "$commit_i" >/dev/null
mkdir -p "$work/staging/builds/example-service"
cp -R "$work/rendered/builds/example-service/$commit_i" "$work/staging/builds/example-service/"
land 'fixture: a request only the moved repository declares'
git -C "$work/seed" push --quiet "file://$work/moved.git" HEAD:refs/heads/main
unmoved=$(tip)
moved=$(git -C "$work/moved.git" rev-parse refs/heads/main)
attempt_i=$(make_record "$(manifest_for "$commit_i")")
request_i=$(basename "$(dirname "$(echo "$work/host-records"/*/"$attempt_i.json")")")
REPOSITORY_UNDER_TEST=moved.git publish
test "$(tip)" = "$unmoved"
test "$(git -C "$work/moved.git" rev-list --count "$moved..refs/heads/main")" = 1
git -C "$work/moved.git" show --format= --name-only refs/heads/main |
  grep -Fxq "results/example-service/$commit_i/${request_i#sha256:}/$attempt_i.json"

# --------------------------------------------------------------- the token ---

if grep -rFq "$token" "$work/clone"; then
  echo "the token was written into the clone" >&2
  exit 1
fi
if git -C "$work/origin.git" log --all -p | grep -Fq "$token"; then
  echo "the token reached the published history" >&2
  exit 1
fi

# ------------------------------------------------- what the layout gate says ---

python3 "$root/tests/build-results.py" "$work/published" "$scripts"
