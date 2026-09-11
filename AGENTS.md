# Agent guide

This repository is the declarative infrastructure for Chuggy's NixOS hosts and
their k3s clusters. Read `README.md` before changing it; it documents the
ownership boundaries, deployment sequence, recovery path, and required checks.

## Architecture

- `hosts/` contains facts specific to a machine. Shared host behaviour and Nix
  options belong in `modules/`.
- `repositories.nix` declares the repositories whose images this site builds,
  and nothing else is per repository here: a repository a run works on is bound
  from the console, and every credential an act needs is minted from a GitHub
  App key by the pod performing it. The `github-repository-transition` check
  holds the build requests to that roster and refuses a pod carrying a
  per-repository token.
- `cluster/` is Flux-managed Kubernetes state. `main` is live, so merging a
  manifest change is a deployment action.
- `builds/` contains immutable Shipwright requests pinned to full source commits.
  Generate them with `scripts/render-build-request`; never edit one in place.
- `results/` records immutable build provenance, published by the host that
  recorded it. Image deployment changes are generated with
  `scripts/render-image-promotion` from a verified result.
- Credentials remain outside Git. Commit references, projections, and delivery
  mechanisms, but never private keys or token values.

## GitHub Apps

Two GitHub Apps divide control-plane authority from workload authority:

- **Chuggy Portal** is the control-plane App. The api, the ticket service, the
  finalizer and the importer each mount its private key and mint their own
  repository-scoped tokens from it, and the host mints the build-reader token
  Shipwright clones with. A repository ruleset reserves updates to each carried
  repository's protected `main` branch to this App and repository admins -- `Finalizer owns main` on
  gdoteof/chuggy-fabric admits only those two; `chuggy portal + admins own
  main` on kasofsk/chuggy also admits its organization admins -- and a human
  administrator token is intentionally not a substitute for any of them.
- **Chuggy Worker** is the execution-plane App. The worker plane mounts its key
  and mints an attempt's or a session's credential from it for ticket branches
  and handoff work. It must not receive finalizer authority or
  update a protected `main` branch on any carried repository -- the ruleset
  above is what refuses it if it tries.

`modules/github-app-token.nix` mints short-lived installation tokens from
root-only host key files and projects them into narrowly scoped Kubernetes
Secrets. When operating manually, mint the smallest repository and permission
scope needed, never print a token, and do not persist it in the worktree or shell
history.

## Working agreement

- Preserve the split between host configuration, cluster declarations, build
  requests, and provenance; do not patch live objects as a substitute for Git.
- Run focused checks while working and `nix flake check` before handoff. If Nix
  is unavailable, run the portable checks and state exactly which Nix checks CI
  still needs to run.
- Validate Kubernetes changes with a server-side dry run when cluster access is
  available.
- Do not rebuild or switch a host, reconcile Flux, apply manifests, restart
  infrastructure, reset data, or deploy without explicit approval.
