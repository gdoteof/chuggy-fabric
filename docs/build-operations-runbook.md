# Build operations

This site builds a source's images when asked, records what it built, and
releases from the record. The loop is four paths in this repository, in
order, and every move between them is a commit to the branch Flux follows:

| Path | What lands there | Written by |
|---|---|---|
| `requests/<repository-id>/<source-commit>/<request-digest>.json` | the document asking for a build of one commit | `scripts/request-build`, run by a `fabric-change` ticket and landed by its merge |
| `builds/<repository-id>/<source-commit>/<build-request-digest>.yaml` | one Shipwright request per image, each at its own digest, `scripts/build_sources.py` declares for the source; Flux applies them | `scripts/fulfil-build-requests`, run and pushed by `chuggy-build-results-publish.service` on the host |
| `results/<repository-id>/<source-commit>/<request-digest>/<attempt>.json` | the recorded result of one attempt, beside its checksum | recorded by `chuggy-build-provenance.service`, pushed by the publisher unit |
| `results/<repository-id>/<source-commit>/request-<request-digest>.json` | the record: every build the request rendered has a result | `scripts/fulfil-build-requests`, in the activation that pushed the last result |

The record is what a rollout waits for. A failed build writes one too: what a
failed build refuses is the release, and `scripts/render-release` is where
that refusal is. `tests/build-results-publish-unit.nix` holds that the unit
gtr builds can run the consumer from the copy of `scripts/` it names.

## The chain a chuggy change rolls out by

Three tickets, filed at once and ordered so each lands before the next runs.
Nothing in any of them names a commit or a digest; each command resolves
chuggy `main` when it runs, so a `main` that moved between two of them is a
wait with nothing filed at it, reported as could-not-run and cleared by
asking for the new commit.

1. The chuggy change, in chuggy. Done at its merge.
2. A `fabric-change` ticket, whose work is
   `scripts/request-build --repository-id chuggy --source-ref refs/heads/main`.
   It writes the request document for the commit `main` is at and nothing
   else; the merge lands it, and the publisher's next activation answers it.
3. A `fabric-rollout` ticket, whose work is
   `scripts/rollout-from-results --within-secs <n>`. It resolves the same
   ref, waits for the record, renders the release with
   `scripts/render-release`, and prints one JSON object naming what it
   released; the merge deploys it.

The two configurations are in `.chug/configurations/`, each declaring its
work as that one line; the rules each script enforces are in its own header.
A refusal (exit 3) from either is the ticket's failure and its attempts are
its budget: the request was already filed, this site has not answered within
the bound, or the release cannot be cut from what it answered. A failed build
is the operator's, below, and not a reason to file another ticket.

By hand, in a checkout of the branch Flux follows, the same steps take the
commit rather than resolving it:

```text
scripts/request-build --repository-id chuggy --source-commit <full commit>
scripts/await-build-results --repository-id chuggy --source-commit <full commit> \
  --within-secs <seconds>
git merge --ff-only origin/main
scripts/render-release --target-commit <full commit>
```

The fast-forward is what `scripts/rollout-from-results` does between the two:
the wait reads the branch, the render reads the checkout, and the record is
on the branch before it is in any checkout taken earlier.

The first stages nothing, so what it wrote is committed and pushed like any
other change; it refuses a commit that already carries a request, its own
included, because a run with nothing to write is a ticket with nothing to
land. The first two print one JSON object on stdout and their account on
stderr, so a ticket engine reads the result and a person reads the reason.

## Sizing the wait

`--within-secs` is the rollout command's whole life: the resolve, the wait,
the fast-forward and the render each get what is left of it. It has to undercut the deadline
of the pod that runs it -- `CHUG_SCHEDULER_WORKER_DEADLINE_SECS` in
`cluster/apps/chuggy-scheduler.yaml` -- by the clone and setup before the
command, because a pod killed at its deadline has reached no verdict: what
follows is another attempt from the beginning, not a decision about the
build. It cannot exceed the cap `scripts/await-build-results` states, past
which a wait holds open a ticket and not a build. The value `fabric-rollout`
carries was sized by this rule against those two homes.

What a wait costs is a worker. The scheduler holds the attempt's claim for
the command's whole life, and this site runs one work pod at a time
(`chuggy.work` in `hosts/gtr/default.nix`), so nothing else runs while a
rollout waits. A build that outruns one attempt's wait -- each `Build`
carries the timeout `scripts/render-build-request` writes into it, and a
result reaches the branch a recorder activation and a publisher activation
after it finishes -- is the next attempt's to find answered, and the ticket's
attempts are the budget for that.

## A request rendered and never answered

`builds/<repository-id>/<source-commit>/` carries the manifests and
`results/<repository-id>/<source-commit>/` has no `request-*.json` past the
build timeout. In order:

1. `journalctl -u chuggy-build-results-publish` on the host. A line beginning
   `fulfil-build-requests:` names a document this site will never answer --
   an undeclared source, a profile or namespace that is not the declared one
   -- and the unit is not red for it; it is cleared on the branch by declaring
   what the document asks for, never by editing the document. A red unit is a
   push the branch refused, or a record this host holds that differs from the
   branch's copy.
2. `chuggy-build-attempt-alerts.service`, under Diagnose: a failed or stalled
   attempt. A failed attempt still gets a result and its record is still
   written; the rollout is what refuses. Retry it as under Retry.
3. A `BuildRun` that never reaches a terminal condition gets no result, so
   the record is never written. The alerts unit reports it as stalled, and
   the attempt is retried or retired as below.

## What is immutable here

A record `results/<repository-id>/<source-commit>/request-<request-digest>.json`
is written once and never rewritten: `scripts/fulfil-build-requests` reads
its existence to know a request is answered, so a rewrite would be a request
answered twice. A request document, once answered, is not withdrawn either:
`tests/build-results.nix` re-resolves every record against the document it
answers, so removing that document from `requests/` reds the gate for as long
as the record stands. What is cleared by removing a document is one that was
never answered.

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
| durable result | retained with installation backups after live-resource removal, and in `results/` once published |
| Build, BuildRun, TaskRun, pod, and cluster log | pruned only after the result is durable and the Git declaration is retired |
| registry digest | retained until a selected-digest inventory can prove it unselected immediately before collection |

Retirement is ordered:

1. let the recorder persist and checksum terminal provenance;
2. run `scripts/retire-build-request` with the same results path;
3. commit and push the removal;
4. verify the `builds` Kustomization applied that revision and the BuildRun and
   Build disappeared through Flux pruning.

Retirement and publication do not compose yet. `results/` carries a record for
every request the publisher has reached, and `tests/build-results.py` resolves
each of them against the declaration in `builds/` it answers, so removing a
declaration whose result is published makes that gate a finding. Nothing has
been retired here; the first retirement is what decides whether the gate learns
to read history or a published result is retired with its request.

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
