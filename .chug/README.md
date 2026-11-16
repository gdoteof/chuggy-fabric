# Chuggy tickets in this repository

`.chug/configurations/chuggy-fabric.json` is what chuggy works a ticket here
under. An agent builds the change from `.chug/prompts/work.md`.
`.chug/tasks/ci.sh` checks it, and a reviewer judges it by
`.chug/tasks/review-change.md`, from `.chug/prompts/review.md`. Then, by
default, a person approves it before it merges, because `main` is live and the
merge is the deployment.

A ticket lands only at a commit that holds `main`'s tip. If `main` moves while
the ticket waits, the checks and the approval run again, and the review runs
again only if the ticket's own diff changed.

The image a run works in carries no Nix. What the check stage covers, and what
it leaves for `nix flake check`, is stated in `.chug/tasks/ci.sh`, and
`tests/chug-ci.nix` is what holds that file. The reviewer names the Nix checks a
change still needs, and the approval is where they are run.

The declaration's shape is Chuggy's, and is stated in Chuggy's own repository
rather than restated here: the envelope in `.chug/configurations/README.md`
there, and the schema in `src/contract/configurationDocument.ts`. No ticket
makes a release: the top-level `README.md` says how one is made.
