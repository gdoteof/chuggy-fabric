{ pkgs }:

pkgs.runCommand "chuggy-image-promotion" {
  nativeBuildInputs = [ pkgs.python3 pkgs.jq pkgs.coreutils pkgs.gnugrep ];
} ''
  set -eu
  root=${../.}
  mkdir bin results environment
  export PATH="$PWD/bin:$PATH"

  cat > bin/crane <<'EOF'
#!/usr/bin/env bash
test "$1" = digest
case "$2" in
  registry.example.internal/team/example-service@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)
    printf '%s\n' sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb ;;
  *) echo "manifest unknown" >&2; exit 1 ;;
esac
EOF
  chmod +x bin/crane

  jq -S '{
    requestDigest: .items[0].metadata.annotations["fabric.chuggy.dev/request-digest"],
    attempt: {name: .items[0].metadata.name, ordinal: 1},
    source: {
      requestedCommit: .items[0].metadata.annotations["fabric.chuggy.dev/source-commit"],
      observedCommit: .items[0].status.sources[0].git.commitSha
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

  promote() {
    "$root/scripts/render-image-promotion" \
      --build-result results/success.json \
      --repository-id example-service \
      --target-ref refs/heads/staging \
      --environment-path environments/staging/example-service.yaml \
      --resource-name example-service \
      --container-name server \
      --namespace staging \
      --output-root environment
  }
  path=$(promote)
  test "$path" = environments/staging/example-service.yaml
  patch="environment/$path"
  grep -F 'registry.example.internal/team/example-service@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' "$patch" >/dev/null
  grep -F 'fabric.chuggy.dev/source-commit' "$patch" >/dev/null
  grep -F 'fabric.chuggy.dev/build-request-digest' "$patch" >/dev/null
  grep -F 'fabric.chuggy.dev/build-provenance-digest' "$patch" >/dev/null
  grep -F 'refs/heads/staging' "$patch" >/dev/null
  cp "$patch" first
  promote >/dev/null
  cmp first "$patch"

  cp results/success.json build-record-before
  cp results/success.json.sha256 build-checksum-before
  jq '.result.output.repository = "registry.example.internal/missing"' results/success.json > results/unavailable.json
  jq -S '.result' results/unavailable.json > unavailable-payload
  unavailable-provenance=$(sha256sum unavailable-payload | awk '{print "sha256:" $1}')
  jq --arg digest "$unavailable-provenance" '.provenanceRecordDigest = $digest' \
    results/unavailable.json > unavailable-record
  mv unavailable-record results/unavailable.json
  checksum=$(sha256sum results/unavailable.json | awk '{print "sha256:" $1}')
  printf '%s\n' "$checksum" > results/unavailable.json.sha256
  if "$root/scripts/render-image-promotion" \
      --build-result results/unavailable.json --repository-id example-service \
      --target-ref refs/heads/production --environment-path environments/production/example-service.yaml \
      --resource-name example-service --container-name server --namespace production \
      --output-root environment 2>unavailable.log; then
    echo "promotion accepted an unavailable digest" >&2
    exit 1
  fi
  grep -F 'selected image is unavailable' unavailable.log >/dev/null
  test ! -e environment/environments/production/example-service.yaml
  cmp build-record-before results/success.json
  cmp build-checksum-before results/success.json.sha256

  jq '.result.output.digest = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"' \
    results/success.json > results/rollback.json
  jq -S '.result' results/rollback.json > rollback-payload
  rollback-provenance=$(sha256sum rollback-payload | awk '{print "sha256:" $1}')
  jq --arg digest "$rollback_provenance" '.provenanceRecordDigest = $digest' \
    results/rollback.json > rollback-record
  mv rollback-record results/rollback.json
  sha256sum results/rollback.json | awk '{print "sha256:" $1}' > results/rollback.json.sha256
  sed -i 's/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc/g' bin/crane
  "$root/scripts/render-image-promotion" \
    --build-result results/rollback.json --repository-id example-service \
    --target-ref refs/heads/staging --environment-path environments/staging/example-service.yaml \
    --resource-name example-service --container-name server --namespace staging \
    --output-root environment >/dev/null
  grep -F 'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc' "$patch" >/dev/null

  if "$root/scripts/render-image-promotion" \
      --build-result results/success.json --repository-id example-service \
      --target-ref refs/heads/staging --environment-path ../escape.yaml \
      --resource-name example-service --container-name server --namespace staging \
      --output-root environment 2>escape.log; then
    echo "promotion accepted a path outside its environment root" >&2
    exit 1
  fi
  grep -F 'normalized relative path' escape.log >/dev/null
  touch "$out"
''
