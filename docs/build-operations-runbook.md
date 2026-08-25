# Build operations

The source ticket ends when its configured Git handoff succeeds. Failures here
belong to the fabric operator and never reopen that ticket.

## Diagnose

`chuggy-build-attempt-alerts.service` fails with an identified JSON alert when
an attempt failed or remains non-terminal beyond the profile timeout plus its
reconciliation margin. A clean scan exits successfully, so the unit state is
also the local actionable signal.
This installation has no outbound alert route, so inspect the service journal
and the Prometheus/Flux views during normal operations.

For an alert, inspect the named `BuildRun`, its `Succeeded` condition, and the
Tekton TaskRun and pod carrying the same Shipwright labels. Ownership is:

| Failure | Owner |
|---|---|
| Flux has not materialized the declared request | Flux/fabric operator |
| BuildRun checkout, execution, timeout, or push failed | build-controller operator |
| reported digest is absent from the registry | registry operator |
| selected digest does not roll out | rollout operator |

## Retry

The provenance recorder must first persist the failed terminal attempt. In a
clean checkout of the branch Flux follows, run:

```text
scripts/retry-build-request builds/<repository>/<commit>/<request>.yaml \
  --results-path /var/lib/chuggy/build-results
```

Review, commit, and push the result. The command replaces the failed live
`BuildRun` declaration with the next ordinal attempt and leaves the `Build`
document, request digest, source commit, target, and profile unchanged. Git
retains the retired attempt declaration. Flux prunes the old attempt and creates
the new one; do not delete and recreate an attempt name or edit the `Build`.

## Retire and retain

Terminal resources are not subject to Shipwright TTL cleanup. TTL deletion while
Git still declares an attempt would let Flux recreate and execute it again.
The live retention policy is operator-driven rather than time-driven:

| Material | Retention and collection |
|---|---|
| request and attempt declarations | live until ordered retirement; retained in Git history |
| durable result | retained with installation backups after live-resource removal |
| Build, BuildRun, TaskRun, pod, and cluster log | pruned only after the result is durable and the Git declaration is retired |
| registry digest | retained until a selected-digest inventory can prove it unselected immediately before collection |

Retirement is ordered:

1. let the recorder persist and checksum terminal provenance;
2. run `scripts/retire-build-request` with the same results path;
3. commit and push the removal;
4. verify the `builds` Kustomization applied that revision and the BuildRun and
   Build disappeared through Flux pruning.

Git retains request and attempt declarations. The installation backup retains
`/var/lib/chuggy/build-results`, including attempt-to-request-to-digest records.
Controller pods and logs expire with the pruned BuildRun; export logs before
retirement when an incident needs them.

Registry garbage collection is deliberately separate from live-resource
retirement. No command in this flow deletes registry content. Until digest
promotion supplies an installation-owned selected-digest inventory, registry
artifacts are retained. Once that inventory exists, garbage collection may
delete only an unselected digest whose provenance and request remain durable;
it must re-read the inventory immediately before deletion.
