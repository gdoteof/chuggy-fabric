"""The images each source repository builds here, and the one place they are
declared.

`repositories.nix` says which repositories this site builds images FOR, because
that is what a host needs in order to mint a clone credential. It does not say
WHICH images a source builds, and until now nothing did: an operator rendered
one build request per image by hand, from the runbook. A request arriving from
Chuggy's finalizer names a commit, a registry namespace, a builder profile and a
platform, and no images at all -- it cannot name them, because which images a
source builds is the fabric's fact and not the source's. This file is where the
fabric states it.

AN ENTRY IS A SOURCE REPOSITORY AND WHAT ONE REQUEST FOR IT RENDERS TO. The key
is the repository id a request document is filed under
(`requests/<repository-id>/<source-commit>/<request-digest>.json`), which is
also the id `builds/` and `results/` file that source under. Every value an
entry carries is an argument `scripts/render-build-request` takes, so
`scripts/fulfil-build-requests` renders through that one renderer rather than
assembling a manifest of its own.

THE SOURCE URL AND THE CLONE SECRET ARE ALSO `repositories.nix`'s, and they are
written again here because a Python script cannot read a Nix expression and the
renderer needs both. `tests/github-repository-transition.py` holds every entry
here to the roster there, which is the same arrangement the build requests
themselves are in: a request naming a Secret this site does not mint is a build
that never starts, and it reads correctly in either file alone.

A REQUEST ALSO NAMES A BUILDER PROFILE, and the profiles this site has are
`scripts/render-build-request`'s. `fulfil-build-requests` reads them there and
refuses a name that is not one of them, so no entry restates that roster.

WHY CHUGGY'S WORKER IMAGE IS NOT LISTED. It is built here and it renders by the
same renderer -- `builds/chuggy/f8dc9194f2d2b88a50619225c521363b5f2822c8/` is
one such request -- but `scripts/render-release` cannot move it: the image a run
uses is named in a Chuggy configuration and no manifest under `cluster/apps`
selects it, so a request that built it would leave a result no release reads and
a Chuggy ticket waiting for one. A worker change stays a `fabric-change` ticket
and a configuration bump. When that stops being true, the worker is one more
line under `images`.
"""

SOURCES = {
    "chuggy": {
        "url": "https://github.com/kasofsk/chuggy.git",
        "sourceSecret": "chuggy-build-source-read",
        "imageNamespace": "registry.chuggy-registry.svc.cluster.local:5000/chuggy",
        "outputSecret": "chuggy-registry-build-push",
        "contextDir": ".",
        "cache": "registry",
        "platform": "linux/amd64",
        # The Dockerfile a build builds, and the image repository under the
        # namespace above that it publishes to. Which image a result is of is
        # the Dockerfile its request names, which is also how
        # `scripts/render-release` reads one.
        "images": {
            "images/api/Dockerfile": "api",
            "images/chuggy-ui/Dockerfile": "web",
        },
    },
}
