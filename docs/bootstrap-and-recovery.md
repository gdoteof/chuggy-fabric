# Bootstrap, source cutover, and recovery

This runbook covers two operations that must not be confused:

- **new-authority bootstrap** creates infrastructure with a fresh database,
  credentials, Git history, and registry, ready for Chuggy to establish a new
  authority identity;
- **same-authority recovery** restores those things from that installation's
  off-installation backups.

Starting this repository against an empty disk performs the first operation.
It never recovers an existing installation.

## External recovery root

Keep a private, immutable copy of the following outside the installation it
creates:

- this repository at a full commit SHA, including `flake.lock`, the selected
  host configuration, `modules/`, `cluster/`, and this runbook;
- the NixOS hardware configuration and documented Nix trust/cache inputs;
- an encrypted credential package sufficient to reach bootstrap Git and the
  machine, with its decryption procedure kept separately;
- expected DNS names, CA chain or `known_hosts`, and network route for Git.

A private external repository, off-cluster mirror, or signed archive in durable
object storage can be the root. Verify its SHA or digest before relying on it.
Internal Git must not be its only copy. Never put keys, passwords, or private CA
material in Nix options: expressions and generated manifests are store-readable.

## Create a new authority

1. Create a host entry from `hosts/example`; replace every documentation
   address, hostname, account/key, storage path, budget, and ingress value. Do
   not copy `/var/lib/chuggy`, a PostgreSQL volume, or another host's secrets.
2. Point `chuggy.flux.repositoryUrl`, `.branch`, and `.path` at an anonymously
   readable external bootstrap source and leave `.secretRef = null`. This is
   stage one: Kubernetes and `flux-system` do not exist before first activation,
   so a Secret inside them cannot authenticate that first fetch.
3. Run `nix flake check`; build the host from the same full commit SHA.
4. Before activation, record that the target database volume and
   `/var/lib/chuggy/secrets` do not exist or are intentionally empty. Existing
   values require an explicit adoption or recovery decision.
5. Activate the pinned configuration. Confirm new secrets were generated,
   PostgreSQL initialized an empty journal, `GitRepository/fabric` reports the
   expected revision, and `Kustomization/apps` becomes Ready.
6. Complete [Chuggy #272] and record its generated installation identity before
   declaring the installation an autonomous ticket authority. A fresh volume
   and independently generated secrets prove fresh infrastructure, not an
application authority identity.

Before creating any ticket, query `SELECT count(*) FROM journal_entry;` as the
database owner and retain the zero result with the bootstrap record. A schema
that does not contain `journal_entry` has not completed Chuggy migration and is
not evidence of an empty initialized journal.

[Chuggy #272]: https://github.com/kasofsk/chuggy/issues/272

The anonymous source is intentionally a bootstrap-only authority. An operator
whose recovery root itself must remain private can fetch and verify a signed
fabric archive outside Flux, but the initial Flux Git source must remain
anonymously readable until secure machine-layer credential provisioning exists.
This repository does not claim that capability today.

## Private Flux source

This is stage two, after stage one has created Kubernetes, `flux-system`, and a
healthy bootstrap reconciliation. `chuggy.flux.secretRef` names a Secret in
`flux-system`; it never carries the credential. Create it before activating the
machine revision that selects private Git. For SSH, Flux requires the private
key and pinned host keys:

```sh
kubectl -n flux-system create secret generic fabric-source-auth \
  --from-file=identity=/root/bootstrap/fabric-read-only \
  --from-file=known_hosts=/root/bootstrap/known_hosts
```

For HTTPS, use `username` and `password` keys. Add `ca.crt` when the certificate
does not chain to the controllers' public roots. Grant read access only. From
the cluster network, resolve the host, connect to its Git port, and verify TLS
or the SSH host key against the independently recorded value.

This Secret is an explicit cutover operation. Keep its source in the encrypted
external credential package; never commit the rendered Secret. If it is lost,
return to the anonymously readable bootstrap revision, recreate it, and repeat
cutover; do not put its bytes in Nix configuration.

## Cut over to installation-owned Git

Cutover changes the one machine-layer `GitRepository/fabric`; it never adds a
second reconciler for `cluster/apps`.

1. Mirror the exact currently reconciled fabric commit into the destination.
   Verify that commit and the configured path there.
2. Provision destination-scoped read credentials. From the cluster network,
   verify DNS, TCP reachability, authentication, and TLS/SSH trust.
3. In one host change, set `repositoryUrl`, `branch`, and `secretRef` to the
   destination. Commit it and record the full fabric commit SHA.
4. Run `nix flake check`, then build from that SHA. Activation is an operator
   action: use `nixos-rebuild test` first, inspect the generated source, and
   only then `switch` from the same SHA.
5. Confirm `GitRepository/fabric` reports the destination revision and
   `Kustomization/apps` is Ready at the expected commit. Confirm exactly one
   Kustomization owns each object set.
6. Revoke the old read credential only after those checks succeed.

Rollback means activating another committed machine revision that restores the
old URL, branch, and credential reference. Do not add a second GitRepository or
Kustomization: overlapping reconcilers make ownership ambiguous and can prune
each other's objects.

## Same-authority disaster recovery

Recovery requires off-installation backups of all authority-bearing state:

- the canonical PostgreSQL journal and tested database restore procedure;
- the installation identity once Chuggy defines it;
- `/var/lib/chuggy/secrets` and externally issued credentials, encrypted under
  a separately recoverable key;
- authoritative Git repositories and refs;
- registry content for every selected digest, or a verified source for them;
- the pinned fabric commit and host configuration from the external root.

Restore those as one installation and then reconcile from its restored Git.
An empty PostgreSQL volume or newly generated secrets create a different
authority and must never be presented as recovery of the old one.

This repository does not yet implement database, Git, registry, or identity
backup jobs. Until each passes a restore rehearsal, this is a backup contract,
not a demonstrated disaster-recovery claim.
