# Implement the ticket

You are changing chuggy-fabric: the NixOS hosts and the Flux-managed cluster
chuggy runs on. Implement the one change this ticket asks for, and nothing else
on it.

Read `AGENTS.md` and `README.md` before you change the repository, and
`.chug/tasks/review-change.md`, the brief your change will be reviewed against:
its house rules bind an author as much as a reviewer.

`main` is live: Flux applies `cluster/` from it, so what you write is deployed
once it lands. `cluster/chuggy-migrate` and `cluster/chuggy` are the exception,
and deploy with the next release. This job has no cluster access and needs none. Do not rebuild or
switch a host, reconcile Flux, apply manifests, restart infrastructure, reset
data or deploy.

Read the code you are about to change before you change it, change the least
that satisfies the ticket, and add focused coverage under `tests/` where the
change can carry it. If the ticket cannot be satisfied as written, report that
rather than satisfying something adjacent to it.

`.chug/tasks/ci.sh` is the check this image can run. Its header says what it
covers and what it leaves for `nix flake check`, which needs Nix and this image
has none. Run `ci.sh` once the change is complete; if it finds something, fix it
and run it again. A gate that could not run is not a pass. Name in your report
the `nix flake check` entries, read off `flake.nix`, that the change still
needs run.

Commit the change yourself, with a message that carries its why. The job has no
git identity, so commit as the worker:
`git -c user.name='Chuggy Worker' -c user.email=worker@chuggy.invalid commit`.
At the attempt's end the worker adds a commit of its own on top, naming only the
ticket and the attempt and holding whatever you left uncommitted.

Report one result: a pass only after a run of `ci.sh` that ends clean, or a
failure naming what you could not satisfy and what stopped you.
