{ pkgs }:

pkgs.runCommand "chuggy-image-promotion" {
  nativeBuildInputs = [ pkgs.python3 pkgs.jq pkgs.coreutils pkgs.gnugrep pkgs.git ];
} ''
  set -eu
  root=${../.}
  cp -R "$root/scripts" scripts-under-test
  chmod -R u+w scripts-under-test
  set +u
  patchShebangs scripts-under-test
  set -u
  scripts=$PWD/scripts-under-test
  real_git=${pkgs.git}/bin/git
  mkdir bin results seed symlink-seed acts ambient-home
  export HOME="$PWD/ambient-home"
  export LEAK_ME=must-not-cross

  cat > bin/credential <<'EOF'
#!/usr/bin/env bash
test -z "''${LEAK_ME:-}"
test -n "''${PROMOTION_CREDENTIAL_REF:-}"
case "$HOME" in */acts|*/image-promotion.*) ;; *) exit 1 ;; esac
case "$1" in *Username*) printf '%s\n' unused ;; *) printf '%s\n' unused ;; esac
EOF
  cat > bin/crane <<'EOF'
#!/usr/bin/env bash
test -z "''${LEAK_ME:-}"
test -z "''${PROMOTION_REGISTRY_CREDENTIAL_REF:-}"
case "$HOME" in */registry-credential.*) ;; *) exit 1 ;; esac
test -f "$DOCKER_CONFIG/config.json"
test "$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$DOCKER_CONFIG/config.json")" = 0o600
grep -F 'private-registry-auth' "$DOCKER_CONFIG/config.json" >/dev/null
test "$1" = digest
case "$2" in
  registry.example.internal/team/example-service@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)
    printf '%s\n' sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb ;;
  registry.example.internal/team/example-service@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc)
    printf '%s\n' sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc ;;
  *) echo 'manifest unknown' >&2; exit 1 ;;
esac
EOF
  cat > bin/registry-credential <<'EOF'
#!/usr/bin/env bash
test -z "''${LEAK_ME:-}"
test "$PROMOTION_REGISTRY_CREDENTIAL_REF" = registry-reader
case "$HOME" in */registry-credential.*) ;; *) exit 1 ;; esac
printf '%s\n' '{"auths":{"registry.example.internal":{"auth":"private-registry-auth"}}}'
EOF
  cat > bin/crane-missing <<'EOF'
#!/usr/bin/env bash
test -z "''${LEAK_ME:-}"
echo 'manifest unknown' >&2
exit 1
EOF
cat > bin/git-clean <<'EOF'
#!/usr/bin/env bash
test -z "''${LEAK_ME:-}"
case "$HOME" in */acts|*/image-promotion.*) ;; *) exit 1 ;; esac
exec @GIT@ "$@"
EOF
  cat > bin/git-lost-response <<'EOF'
#!/usr/bin/env bash
test -z "''${LEAK_ME:-}"
case " $* " in
  *' push '*) @GIT@ "$@"; echo 'simulated lost response' >&2; exit 1 ;;
  *) exec @GIT@ "$@" ;;
esac
EOF
  cat > bin/git-reject <<'EOF'
#!/usr/bin/env bash
test -z "''${LEAK_ME:-}"
case " $* " in
  *' push '*) echo 'simulated rejection' >&2; exit 1 ;;
  *) exec @GIT@ "$@" ;;
esac
EOF
  cat > bin/git-race <<'EOF'
#!/usr/bin/env bash
test -z "''${LEAK_ME:-}"
case " $* " in
  *' push '*)
    remote="$(dirname "$0")/../remote.git"
    base=$(@GIT@ --git-dir "$remote" rev-parse refs/heads/staging)
    tree=$(@GIT@ --git-dir "$remote" rev-parse "$base^{tree}")
    race=$(printf '%s\n' race | env \
      GIT_AUTHOR_NAME=racer GIT_AUTHOR_EMAIL=racer@invalid GIT_AUTHOR_DATE=2001-01-01T00:00:00Z \
      GIT_COMMITTER_NAME=racer GIT_COMMITTER_EMAIL=racer@invalid GIT_COMMITTER_DATE=2001-01-01T00:00:00Z \
      @GIT@ --git-dir "$remote" commit-tree "$tree" -p "$base")
    @GIT@ --git-dir "$remote" update-ref refs/heads/staging "$race" "$base"
    echo 'simulated racing push' >&2
    exit 1 ;;
  *) exec @GIT@ "$@" ;;
esac
EOF
  sed -i "s#@GIT@#$real_git#g" bin/git-clean bin/git-lost-response bin/git-reject bin/git-race
  chmod +x bin/*
  set +u
  patchShebangs bin
  set -u

  jq -S '{
    requestDigest: .items[0].metadata.annotations["fabric.chuggy.dev/request-digest"],
    attempt: {name: .items[0].metadata.name, ordinal: 1},
    source: {
      repositoryId: .items[0].metadata.annotations["fabric.chuggy.dev/source-repository-id"],
      requestedCommit: .items[0].metadata.annotations["fabric.chuggy.dev/source-commit"],
      observedCommit: .items[0].status.source.git.commitSha
    },
    output: {
      repository: .items[0].metadata.annotations["fabric.chuggy.dev/target-image-repository"],
      digest: .items[0].status.output.digest
    },
    terminalCondition: .items[0].status.conditions[0],
    timestamps: {started: .items[0].status.startTime, completed: .items[0].status.completionTime},
    controller: .items[0].metadata.annotations["fabric.chuggy.dev/shipwright-version"],
    profile: {
      name: .items[0].metadata.annotations["fabric.chuggy.dev/profile"],
      digest: .items[0].metadata.annotations["fabric.chuggy.dev/profile-digest"]
    }
  }' "$root/tests/fixtures/build-request/buildruns.json" > payload
  provenance=$(sha256sum payload | awk '{print "sha256:" $1}')
  jq -nS --arg digest "$provenance" --slurpfile result payload \
    '{provenanceRecordDigest:$digest,result:$result[0]}' > results/success.json
  sha256sum results/success.json | awk '{print "sha256:" $1}' > results/success.json.sha256

  "$real_git" init --bare remote.git >/dev/null
  "$real_git" -C seed init -b staging >/dev/null
  printf '%s\n' 'apiVersion: kustomize.config.k8s.io/v1beta1' 'kind: Kustomization' > seed/kustomization.yaml
  "$real_git" -C seed add kustomization.yaml
  "$real_git" -C seed -c user.name=fixture -c user.email=fixture@invalid commit -m seed >/dev/null
  base=$("$real_git" -C seed rev-parse HEAD)
  "$real_git" -C seed remote add origin "$PWD/remote.git"
  "$real_git" -C seed push origin staging >/dev/null

  promotion() {
    "$scripts/render-image-promotion" \
      --build-result "$PWD/results/success.json" \
      --repository-id example-service \
      --repository-url "$PWD/remote.git" \
      --target-ref refs/heads/staging \
      --environment-path environments/staging/example-service.yaml \
      --resource-name example-service --container-name server --namespace staging \
      --act-root "$PWD/acts" --git-command "$1" \
      --credential-command "$PWD/bin/credential" --credential-ref environment-writer \
      --registry-client "$PWD/bin/crane" \
      --registry-credential-command "$PWD/bin/registry-credential" \
      --registry-credential-ref registry-reader
  }

  first=$(promotion "$PWD/bin/git-clean")
  first_commit=$(printf '%s' "$first" | jq -r .commit)
  test "$(printf '%s' "$first" | jq -r .outcome)" = published
  "$real_git" --git-dir=remote.git show staging:environments/staging/example-service.yaml > promoted
  grep -F 'registry.example.internal/team/example-service@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' promoted >/dev/null
  test -z "$(find acts -mindepth 1 -print -quit)"

  first_tree=$("$real_git" --git-dir=remote.git rev-parse "$first_commit^{tree}")
  descendant=$(printf '%s\n' unrelated | env \
    GIT_AUTHOR_NAME=fixture GIT_AUTHOR_EMAIL=fixture@invalid GIT_AUTHOR_DATE=2002-01-01T00:00:00Z \
    GIT_COMMITTER_NAME=fixture GIT_COMMITTER_EMAIL=fixture@invalid GIT_COMMITTER_DATE=2002-01-01T00:00:00Z \
    "$real_git" --git-dir=remote.git commit-tree "$first_tree" -p "$first_commit")
  "$real_git" --git-dir=remote.git update-ref refs/heads/staging "$descendant" "$first_commit"
  ancestry=$(promotion "$PWD/bin/git-clean")
  test "$(printf '%s' "$ancestry" | jq -r .commit)" = "$descendant"
  test "$(printf '%s' "$ancestry" | jq -r .outcome)" = reconciled
  "$real_git" --git-dir=remote.git update-ref refs/heads/staging "$first_commit" "$descendant"

  reconciled=$(promotion "$PWD/bin/git-clean")
  test "$(printf '%s' "$reconciled" | jq -r .commit)" = "$first_commit"
  test "$(printf '%s' "$reconciled" | jq -r .outcome)" = reconciled

  "$real_git" --git-dir=remote.git update-ref refs/heads/staging "$base" "$first_commit"
  deterministic=$(promotion "$PWD/bin/git-clean")
  test "$(printf '%s' "$deterministic" | jq -r .commit)" = "$first_commit"

  "$real_git" --git-dir=remote.git update-ref refs/heads/staging "$base" "$first_commit"
  lost=$(promotion "$PWD/bin/git-lost-response")
  test "$(printf '%s' "$lost" | jq -r .commit)" = "$first_commit"
  test "$(printf '%s' "$lost" | jq -r .outcome)" = reconciled

  "$real_git" --git-dir=remote.git update-ref refs/heads/staging "$base" "$first_commit"
  if promotion "$PWD/bin/git-reject" 2>rejected.log; then
    echo 'promotion accepted two rejected conditional pushes' >&2
    exit 1
  fi
  grep -F 'rejected with target unchanged' rejected.log >/dev/null
  test "$("$real_git" --git-dir=remote.git rev-parse staging)" = "$base"
  recovered=$(promotion "$PWD/bin/git-clean")
  test "$(printf '%s' "$recovered" | jq -r .commit)" = "$first_commit"

  "$real_git" --git-dir=remote.git update-ref refs/heads/staging "$base" "$first_commit"
  if promotion "$PWD/bin/git-race" 2>race.log; then
    echo 'promotion accepted a divergent racing push' >&2
    exit 1
  fi
  grep -F 'promotion blocked: concurrent target change' race.log >/dev/null
  race_commit=$("$real_git" --git-dir=remote.git rev-parse staging)
  test "$race_commit" != "$base"
  promotion "$PWD/bin/git-clean" >/dev/null

  before_unavailable=$("$real_git" --git-dir=remote.git rev-parse staging)
  if "$scripts/render-image-promotion" \
      --build-result results/success.json --repository-id example-service \
      --repository-url "$PWD/remote.git" --target-ref refs/heads/staging \
      --environment-path environments/staging/unavailable.yaml --resource-name example \
      --container-name server --namespace staging --act-root acts \
      --git-command "$PWD/bin/git-clean" --credential-command "$PWD/bin/credential" \
      --credential-ref writer --registry-client "$PWD/bin/crane-missing" \
      --registry-credential-command "$PWD/bin/registry-credential" \
      --registry-credential-ref registry-reader 2>unavailable.log; then
    echo 'promotion accepted an unavailable digest' >&2
    exit 1
  fi
  grep -F 'selected image is unavailable' unavailable.log >/dev/null
  test "$("$real_git" --git-dir=remote.git rev-parse staging)" = "$before_unavailable"
  test -z "$(find acts -mindepth 1 -print -quit)"

  jq '.result.output.digest = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"' \
    results/success.json > results/rollback.json
  jq -S '.result' results/rollback.json > rollback-payload
  rollback_provenance=$(sha256sum rollback-payload | awk '{print "sha256:" $1}')
  jq --arg digest "$rollback_provenance" '.provenanceRecordDigest = $digest' \
    results/rollback.json > rollback-record
  mv rollback-record results/rollback.json
  sha256sum results/rollback.json | awk '{print "sha256:" $1}' > results/rollback.json.sha256
  "$scripts/render-image-promotion" \
    --build-result results/rollback.json --repository-id example-service \
    --repository-url "$PWD/remote.git" --target-ref refs/heads/staging \
    --environment-path environments/staging/example-service.yaml --resource-name example-service \
    --container-name server --namespace staging --act-root acts \
    --git-command "$PWD/bin/git-clean" --credential-command "$PWD/bin/credential" \
    --credential-ref writer --registry-client "$PWD/bin/crane" \
    --registry-credential-command "$PWD/bin/registry-credential" \
    --registry-credential-ref registry-reader >/dev/null
  "$real_git" --git-dir=remote.git show staging:environments/staging/example-service.yaml | \
    grep -F 'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc' >/dev/null

  refuse() {
    expected=$1
    shift
    if "$scripts/render-image-promotion" "$@" 2>refusal.log; then
      echo "promotion accepted invalid configuration: $expected" >&2
      exit 1
    fi
    grep -F "$expected" refusal.log >/dev/null
  }
  common="--build-result $PWD/results/success.json --repository-id example-service --repository-url $PWD/remote.git --target-ref refs/heads/staging --resource-name example-service --container-name server --namespace staging --act-root $PWD/acts --git-command $PWD/bin/git-clean --credential-command $PWD/bin/credential --credential-ref environment-writer --registry-client $PWD/bin/crane --registry-credential-command $PWD/bin/registry-credential --registry-credential-ref registry-reader"
  refuse 'outside .git' $common --environment-path .git/config
  refuse 'must be normalized' $common --environment-path environments//staging/example.yaml
  refuse 'must be normalized' $common --environment-path environments/./staging/example.yaml
  refuse 'must be normalized' $common --environment-path environments/staging/
  refuse 'invalid repository id' $common --repository-id '../escape' --environment-path environments/staging/example.yaml
  refuse 'invalid target ref' $common --target-ref 'refs/heads/bad ref' --environment-path environments/staging/example.yaml
  refuse 'invalid Kubernetes apiVersion' $common --api-version '../v1' --environment-path environments/staging/example.yaml
  refuse 'invalid choice' $common --kind Pod --environment-path environments/staging/example.yaml
  refuse 'invalid resource name' $common --resource-name 'Bad_Name' --environment-path environments/staging/example.yaml
  refuse 'invalid namespace' $common --namespace 'bad.name' --environment-path environments/staging/example.yaml
  refuse 'invalid container name' $common --container-name 'bad.name' --environment-path environments/staging/example.yaml
  refuse 'must not contain credentials' \
    --build-result results/success.json --repository-id example-service \
    --repository-url https://user:secret@git.example.invalid/repository.git \
    --target-ref refs/heads/staging --environment-path environments/staging/example.yaml \
    --resource-name example --container-name server --namespace staging \
    --act-root acts --git-command "$PWD/bin/git-clean" \
    --credential-command "$PWD/bin/credential" --credential-ref writer --registry-client "$PWD/bin/crane" \
    --registry-credential-command "$PWD/bin/registry-credential" --registry-credential-ref registry-reader
  refuse 'must use public HTTPS on port 443' \
    --build-result results/success.json --repository-id example-service \
    --repository-url ssh://git.example.invalid/repository.git \
    --target-ref refs/heads/staging --environment-path environments/staging/example.yaml \
    --resource-name example --container-name server --namespace staging \
    --act-root acts --git-command "$PWD/bin/git-clean" \
    --credential-command "$PWD/bin/credential" --credential-ref writer --registry-client "$PWD/bin/crane" \
    --registry-credential-command "$PWD/bin/registry-credential" --registry-credential-ref registry-reader
  refuse 'must use public HTTPS on port 443' \
    --build-result results/success.json --repository-id example-service \
    --repository-url http://git.example.invalid/repository.git \
    --target-ref refs/heads/staging --environment-path environments/staging/example.yaml \
    --resource-name example --container-name server --namespace staging \
    --act-root acts --git-command "$PWD/bin/git-clean" \
    --credential-command "$PWD/bin/credential" --credential-ref writer --registry-client "$PWD/bin/crane" \
    --registry-credential-command "$PWD/bin/registry-credential" --registry-credential-ref registry-reader
  refuse 'source repository does not match' \
    --build-result results/success.json --repository-id another-service \
    --repository-url "$PWD/remote.git" --target-ref refs/heads/staging \
    --environment-path environments/staging/example.yaml --resource-name example \
    --container-name server --namespace staging --act-root acts \
    --git-command "$PWD/bin/git-clean" --credential-command "$PWD/bin/credential" \
    --credential-ref writer --registry-client "$PWD/bin/crane" \
    --registry-credential-command "$PWD/bin/registry-credential" --registry-credential-ref registry-reader

  "$real_git" -C symlink-seed init -b symlink >/dev/null
  ln -s /tmp symlink-seed/environments
  "$real_git" -C symlink-seed add environments
  "$real_git" -C symlink-seed -c user.name=fixture -c user.email=fixture@invalid commit -m symlink >/dev/null
  "$real_git" -C symlink-seed push "$PWD/remote.git" symlink >/dev/null
  refuse 'traverses a symbolic link in the target tree' \
    --build-result results/success.json --repository-id example-service \
    --repository-url "$PWD/remote.git" --target-ref refs/heads/symlink \
    --environment-path environments/escape.yaml --resource-name example \
    --container-name server --namespace staging --act-root acts \
    --git-command "$PWD/bin/git-clean" --credential-command "$PWD/bin/credential" \
    --credential-ref writer --registry-client "$PWD/bin/crane" \
    --registry-credential-command "$PWD/bin/registry-credential" --registry-credential-ref registry-reader
  test -z "$(find acts -mindepth 1 -print -quit)"
  touch "$out"
''
