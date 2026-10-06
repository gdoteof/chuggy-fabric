# Chuggy tickets in this repository

This repository declares no configuration. `.chug/tasks/` holds what one would
point a worker at: the check command and the reviewer's brief. The declaration
envelope and the configuration contract are Chuggy's, and are stated in
Chuggy's own repository rather than restated here: the envelope in
`.chug/configurations/README.md` there, the authored half of the readiness a
configuration has to reach in `src/interpreter/taskConfiguration.ts`, and the
release half it must also reach — `version`, `image` and the execution
requirement — in `releaseConfigurationReadiness` in
`src/interpreter/authoring.ts`. No ticket makes a release: `README.md` says how
one is made.

How a ticket lands is not a configuration's to say. It is the binding's
default in Chuggy's console -- a merged pull request, on both live bindings, as
of this writing -- and no file here can state or check it.

What the check stage covers, and what it leaves for `nix flake check`, is
stated in `.chug/tasks/ci.sh`; `tests/chug-ci.nix` is what holds that file.
