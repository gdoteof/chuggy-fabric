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

`fabric-change` asks this site for a build of chuggy `main`, as
`docs/build-operations-runbook.md` describes. It declares its work as one
command invoking one script, and what that script does and refuses is argued
in its own header. Nothing ticket-specific is in it -- the commit is resolved
by the script when it runs -- and it states its own stages. No ticket here
makes a release, and nothing releases from that build: `README.md` says how a
release is made.

How a ticket lands is not a configuration's to say. It is the binding's
default in Chuggy's console -- a merged pull request, on both live bindings, as
of this writing -- and no file here can state or check it.

What the check stage covers, and what it leaves for `nix flake check`, is
stated in `.chug/tasks/ci.sh`; `tests/chug-ci.nix` is what holds that file.
