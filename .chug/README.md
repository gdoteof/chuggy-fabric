# Chuggy tickets in this repository

`.chug/configurations/` declares what Chuggy imports from an exact commit of
this repository, and `.chug/tasks/` holds what those declarations point a
worker at: the check command and the reviewer's brief. The declaration envelope
and the configuration contract are Chuggy's, and are stated in Chuggy's own
repository rather than restated here: the envelope in
`.chug/configurations/README.md` there, the authored half of the readiness a
configuration has to reach in `src/interpreter/taskConfiguration.ts`, and the
release half it must also reach — `version`, `image` and the execution
requirement — in `releaseConfigurationReadiness` in
`src/interpreter/authoring.ts`.

`fabric-change` is for a change written by hand, `fabric-rollout` for one the
release scripts generated; each states its own stages.

What the check stage covers, and what it leaves for `nix flake check`, is
stated in `.chug/tasks/ci.sh`; `tests/chug-ci.nix` is what holds that file.
