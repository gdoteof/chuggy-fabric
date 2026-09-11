{ pkgs }:

pkgs.runCommand "chuggy-configuration-importer" {
  nativeBuildInputs = [ pkgs.kubectl pkgs.gnugrep ];
} ''
  set -eu
  root=${../.}
  manifest="$root/cluster/apps/chuggy-configuration-importer.yaml"

  kubectl kustomize "$root/cluster/apps" > rendered.yaml
  grep -F 'name: chuggy-configuration-importer' rendered.yaml >/dev/null

  # The run is the estate and not a list. A repository, a commit or a partition
  # named here is a second copy of what the bindings say, and the command
  # refuses a configuration carrying one outright -- so this is the difference
  # between a CronJob that imports nothing and one that fails every run.
  test "$(grep -c 'CHUG_CONFIGURATION_IMPORT_REPOSITORIES' "$manifest" || true)" -eq 0
  test "$(grep -Ec '"(repository|commit|partitions)":' "$manifest" || true)" -eq 0
  test "$(grep -Fc 'git ls-remote' "$manifest" || true)" -eq 0

  # The pod mints every read from the App key and carries no Git material of its
  # own: no per-repository token, and none of the credentials that would let it
  # write. `credentialSources` stays an empty list rather than going away,
  # because the command reads the key and the list together and refuses a
  # configuration naming neither.
  grep -F '"credentialSources": []' "$manifest" >/dev/null
  grep -F '"keyFile": "/var/run/chuggy/forge-app/private-key"' "$manifest" >/dev/null
  grep -F 'secretName: chuggy-github-app-portal' "$manifest" >/dev/null
  grep -F '"credentialUsername": "x-access-token"' "$manifest" >/dev/null
  test "$(grep -c 'reader-token\|finalizer-token\|worker-token\|git-operator\|chuggy-git-sync' "$manifest" || true)" -eq 0
  test "$(grep -Fc 'credentialReference:' "$manifest" || true)" -eq 0
  grep -F 'key: configuration-importer-password' "$manifest" >/dev/null
  grep -F 'postgres://chuggy_configuration_importer_login:$(CHUG_CONFIGURATION_IMPORTER_PASSWORD)' "$manifest" >/dev/null
  test "$(grep -c 'role%3Dchuggy_configuration_importer' "$manifest" || true)" -eq 0
  grep -F 'automountServiceAccountToken: false' "$manifest" >/dev/null
  grep -F 'name: wait-for-postgres' "$manifest" >/dev/null
  grep -F 'pg_isready -h postgres.chuggy.svc.cluster.local -U chuggy_configuration_importer_login -t 2' "$manifest" >/dev/null
  test "$(grep -Fc 'for i in $(seq 1 15)' "$manifest")" -eq 1

  # How long the whole run takes is the estate's and cannot be read out of this
  # file, so what is held is that one binding always fits inside the deadline:
  # the wait for PostgreSQL, and then one repository at the remote timeout the
  # configuration names. A deadline under that is a run that reports
  # DeadlineExceeded having imported nothing, for ever.
  remote_timeout="$(sed -n 's/^[[:space:]]*"remoteTimeoutSecsMax":[[:space:]]*\([0-9]\{1,\}\).*$/\1/p' "$manifest")"
  test "$(printf '%s\n' "$remote_timeout" | grep -c .)" -eq 1
  outer_deadline="$(sed -n 's/^[[:space:]]*activeDeadlineSeconds:[[:space:]]*\([0-9]\{1,\}\)$/\1/p' "$manifest")"
  test "$(printf '%s\n' "$outer_deadline" | grep -c .)" -eq 1
  postgres_wait=$((15 * (2 + 2)))
  test "$outer_deadline" -gt "$((postgres_wait + remote_timeout))"

  # Overlap is refused and failed runs remain visible for inspection.
  grep -F 'concurrencyPolicy: Forbid' "$manifest" >/dev/null
  grep -F 'backoffLimit: 0' "$manifest" >/dev/null
  grep -F 'failedJobsHistoryLimit: 3' "$manifest" >/dev/null

  grep -F 'name: chuggy-configuration-importer-egress' \
    "$root/cluster/apps/chuggy-control-plane-network-policy.yaml" >/dev/null
  grep -F 'cidr: 0.0.0.0/0' \
    "$root/cluster/apps/chuggy-control-plane-network-policy.yaml" >/dev/null
  grep -F 'test "$(git rev-parse --short=7 HEAD)" = e92cce9' "$root/README.md" >/dev/null
  grep -F 'CHUG_PG_CONFIGURATION_IMPORTER_PASSWORD' "$root/README.md" >/dev/null
  grep -F 'systemctl is-active chuggy-secrets-sync' "$root/README.md" >/dev/null
  touch "$out"
''
