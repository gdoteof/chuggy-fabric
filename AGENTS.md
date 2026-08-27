# Agent guide

This repository is the declarative infrastructure for Chuggy's NixOS hosts and
their k3s clusters. Read `README.md` before changing it; it documents the
ownership boundaries, deployment sequence, recovery path, and required checks.

## Architecture

- `hosts/` contains facts specific to a machine. Shared host behaviour and Nix
  options belong in `modules/`.
- `cluster/` is Flux-managed Kubernetes state. `main` is live, so merging a
  manifest change is a deployment action.
- `builds/` contains immutable Shipwright requests pinned to full source commits.
  Generate them with `scripts/render-build-request`; never edit one in place.
- `results/` records immutable build provenance. Image deployment changes are
  generated with `scripts/render-image-promotion` from a verified result.
- Credentials remain outside Git. Commit references, projections, and delivery
  mechanisms, but never private keys or token values.

## GitHub Apps

Two GitHub Apps divide control-plane authority from workload authority:

- **Chuggy Portal** is the control-plane App. It issues repository-scoped tokens
  used for read-only source access and finalization. The `Finalizer owns main`
  repository ruleset reserves updates to protected `main` branches for this App;
  a human administrator token is intentionally not a substitute.
- **Chuggy Worker** is the execution-plane App. Workers use its scoped tokens for
  ticket branches and handoff work. It must not receive finalizer authority or
  update protected `main` branches.

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
