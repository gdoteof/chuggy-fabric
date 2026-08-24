# Autonomous installations and release handoffs

This document fixes the target architecture for a production Chuggy and for
independently operated, smaller Chuggy installations. It is a contract for the
implementation issues that follow; the current manifests do not implement all
of it.

## Decisions

1. Every Chuggy installation is autonomous. It has a new installation identity,
   a fresh ticket journal and local credentials. Exactly one desired-state
   source is authoritative for each reconciled object set. Bootstrapping does
   not create a replica of another Chuggy.
2. Ticket authority never crosses an installation boundary. Backup and restore
   preserve one installation's authority; work crosses to another installation
   as an immutable Git object or artifact and is adopted by a new local ticket.
3. A ticket may finish at a configured, durable Git handoff. Flux reconciliation
   and the build that follows are downstream; their later failure does not
   revise the completed ticket.
4. Flux is not a builder. It materializes a declarative build request; a build
   controller executes it and publishes an immutable image digest.
5. Building an image and selecting that image for an environment are separate
   decisions. Flux deploys only a selected digest.
6. Source promotion and downstream publication are repository roles, not
   assumptions about `chuggy` or `chuggy-fabric`.

These decisions deliberately do not create a federation protocol. Two
installations can exchange work without sharing identity, policy, journals, or
administrative trust.

## Authorities and identities

An **installation** is the authority for its tickets. A production installation
and an autonomous mini may run the same software and refer to the same source
commit, but their tickets are different entities. A ticket reference is scoped
by installation identity; a bare ticket number is meaningful only inside its
installation.

Each installation owns:

- a fresh PostgreSQL database and ticket journal;
- its installation identity, users, policy, and credentials;
- its Git providers and repository bindings;
- its registry provider;
- its release refs and Flux sources.

The installation may host Git and the registry itself or bind external
providers. Autonomy is about authority, not physical placement. Bootstrap may
initially point a mini at production-published material, but it conveys no right
to read or write production tickets.

## Bootstrap and recovery

Creating a new installation has two stages:

```text
external bootstrap root -> foundational services -> installation release authority
```

The bootstrap root contains enough versioned material to establish storage, a
fresh database and installation identity, Git, registry, Flux controllers, and
the initial Flux source. It must remain readable while the installation's own
Git service is absent. A private external repository, an off-cluster mirror, or
a signed versioned bundle in durable object storage can satisfy that contract.
An internally hosted Git repository cannot be its own sole bootstrap root.

Disaster recovery is different: it restores the same installation authority.
Its off-installation backup set must include the canonical database journal,
installation identity, required secret material under an appropriate encryption
and access policy, retained Git, and registry data or another source for every
selected digest. Restoring only bootstrap material creates a new installation;
it does not recover the old one. Backup implementation is separate from the
bootstrap work, but bootstrap documentation must say where the same-authority
restore procedure and backups live rather than presenting a fresh database as
recovery.

Cutover is explicit and one-way per operation:

1. establish and verify the destination Git authority and credentials;
2. publish or mirror the immutable release revision there;
3. add private-source `secretRef` support where required, then change the
   host-owned `chuggy.flux.repositoryUrl` and `.branch` together;
4. build and activate that machine-layer change from a pinned fabric commit;
5. reconcile and verify the new source before revoking the old credential.

At every point one source and reconciler are authoritative for a given
desired-state object set. A repository may have several authorized writers;
that is a Git policy and does not create a second Flux authority. A mini may
choose its own repository, fork, or branch after cutover. Rollback is another
pinned machine-layer activation, never overlapping reconciliation of the same
objects from two sources.

## Adopting work from another installation

An installation exposes work however its operator chooses: Git read access, a
contribution branch, a pull request, a mirror, or a signed bundle or patch. The
receiving installation opens an ordinary local ticket to adopt it:

```text
foreign immutable object -> local fetch and evaluation -> local promotion
```

The adoption input names the repository or artifact location, an immutable Git
object ID or expected cryptographic content digest, local credential reference,
and optionally an expected base, signature identity, and provenance. A branch
or artifact URL alone is not an adoption input because it can move. A signature
authenticates the asserted publisher; the content digest fixes the bytes. The
receiver may retain a snapshot when the foreign source is not durable.

The receiver applies its own evaluation and promotion policy. Foreign ticket
history is optional provenance, not evidence that the change is acceptable and
not state imported into the local journal.

## Configurable finalization handoff

A release-producing finalizer binds independent repository roles through its
pinned configuration revision:

| Role | Required configuration |
|---|---|
| work | repository binding, target ref, credential reference |
| handoff | repository binding, target ref, credential reference |
| request | renderer, destination path, handoff mode |

`handoff mode` is either a direct commit or a pull-request proposal. Direct
commit means the request was accepted by the target ref. Pull request means only
that the proposal was created. Neither means that a build succeeded. The
configured mode is the ticket's success contract.

Repository bindings resolve URLs operationally. Credentials resolve separately
and grant least authority; access to the work repository implies no access to
the handoff repository. The renderer receives the immutable commit accepted by
the work repository and emits a deterministic request. Repository names, refs,
paths, provider, and credentials contain no built-in `chuggy` or
`chuggy-fabric` values.

The finalizer is a durable two-effect process, not an atomic Git operation:

```text
promote work -> record accepted commit -> publish handoff -> record publication
```

Each recorded fact carries the repository binding, ref, immutable result, and
an idempotency identity derived from the finalization request. Before retrying
an ambiguous write, the finalizer reads the owning repository and reconciles
whether that identity already landed. Once promotion is recorded, retries begin
at publication and never repeat or replace the accepted promotion.

A permanent publication failure after promotion enters an operator-visible
`handoff blocked` state. The operator may retry the same publication or record
an explicit abandonment; ordinary source rework cannot undo the accepted
commit. Abandonment completes the recovery action, not the original successful
handoff contract.

## Build and deployment protocol

The initial repository layout is one immutable request per request identity:

```text
builds/<repository-id>/<source-commit>/<request-digest>.yaml
```

`repository-id` is a stable binding identity, not a display name.
`request-digest` covers the canonical build-affecting input: source repository
and commit, target image repository, versioned builder profile, platform set,
and renderer version. Re-rendering the same finalization request produces
identical content and path; changing any build input produces a different
request identity. Requests are retained with Git history and may be removed
from the live kustomization after their retention window.

```text
ticket finalizer -> Git request -> Flux -> build controller -> registry digest
                                                    |
                                      status and operator alerting

registry digest -> separate promotion policy or ticket -> environment manifest
                                                    |
                                                  Flux
```

The builder publishes an image and records and verifies the registry's immutable
digest on its Kubernetes resource. Alerting observes failed or stalled build
resources; it does not reopen the source ticket. An automated policy may propose
a digest for an environment, but production selection remains a distinct
bounded workflow and records the exact digest.

A request and an attempt have different identities. Retry creates a new attempt
of the unchanged request; it never edits the request to induce reconciliation.
The selected controller must define the attempt resource/name and terminal-state
retry operation. Durable status retains the mapping from attempt to request and,
when successful, digest after live resources are garbage-collected.

The concrete build controller is intentionally selected by a bounded evaluation
issue: this repository has no existing build-resource API, and choosing one
without proving rootless operation, private Git and registry authentication,
multi-architecture needs, cleanup, and Flux health behavior would turn an
implementation detail into an unsupported platform dependency. The protocol
above is independent of that choice.

## Credentials and reachability

- Fetching foreign work uses a receiver-local, read-only credential.
- Finalizer credentials are scoped per repository and target ref where the
  provider permits it.
- Builders alone receive source-read and registry-push credentials.
- Workloads receive registry-pull credentials only when required.
- Bootstrapping another installation copies no credential by implication.

Private Git and registry bindings must state DNS, TLS trust, and network
reachability. An autonomous mini decides whether to expose anything to
production. Production has no privileged back channel merely because it
published the bootstrap material.

## Failure ownership

| Failure | Owner | Effect on source ticket |
|---|---|---|
| work promotion or configured handoff cannot be proven | finalizer/operator | not complete |
| handoff fails after work promotion | finalizer/operator | blocked, resumable |
| Flux cannot materialize a request | fabric operator | already complete |
| build fails or stalls | build controller/operator | already complete |
| digest is not selected | release policy/operator | already complete |
| selected digest cannot roll out | deployment operator/workflow | already complete |

This boundary is the point of the handoff: the source ticket promises a durable
request, not the eventual success of every system downstream of it.

## Delivery sequence

The contracts above are split at ownership and independently verifiable effects:

1. [Bootstrap autonomous installations from an external recovery root][bootstrap].
2. [Select the Kubernetes image-build controller][builder-spike].
3. [Implement configurable cross-repository release finalization][finalizer].
4. [Implement immutable Flux-materialized image builds][builds].
5. [Alert, retry, and retain downstream build attempts][operations].
6. [Promote immutable image digests separately from builds][promotion].
7. [Adopt immutable work from an autonomous Chuggy installation][adoption].

The bootstrap, finalizer, and adoption work can proceed independently of the
builder selection. Build implementation follows the selection; operations and
promotion follow the stable build-request and digest contracts.

## Non-goals

- ticket-journal replication or federation;
- allowing one installation to advance another installation's ticket;
- implicit trust of work produced by another Chuggy;
- treating Flux as an image builder;
- treating every built image as deployable;
- overlapping desired-state reconcilers for the same objects;
- hard-coded repository identities in finalization.

[bootstrap]: https://github.com/gdoteof/chuggy-fabric/issues/26
[builder-spike]: https://github.com/gdoteof/chuggy-fabric/issues/27
[builds]: https://github.com/gdoteof/chuggy-fabric/issues/28
[operations]: https://github.com/gdoteof/chuggy-fabric/issues/29
[promotion]: https://github.com/gdoteof/chuggy-fabric/issues/30
[finalizer]: https://github.com/kasofsk/chuggy/issues/269
[adoption]: https://github.com/kasofsk/chuggy/issues/270
