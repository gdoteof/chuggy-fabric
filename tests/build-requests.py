#!/usr/bin/env python3
"""Drive `scripts/fulfil-build-requests` over the requests it answers and every
refusal it states.

WHAT IS REAL HERE AND WHAT IS FIXTURE. The builds and results are this
repository's own: the tree each case runs against is a copy of `builds/` and
`results/`, and the case that matters most renders the request Chuggy would have
sent for commit 5e37c51f and compares the bytes with the two manifests an
operator rendered by hand for it and committed. That is the whole parity claim
between the two sides of the loop -- one renderer, one request digest -- and it
is checked against files rather than restated.

THE REQUEST DOCUMENTS ARE FIXTURES, and one of them is verbatim: `REQUESTED`
below is what chuggy's `handoffOutput` renders, byte for byte, key order
included. Nothing in this repository can hold that to chuggy's renderer, so it
is written here as the contract this side reads, and a case that changed it
would be changing what the fabric claims to consume.

THE EXIT CODE IS THE VERDICT. Zero is a tree this command answered, 3 is a
document it will never answer, 2 is a run that did not happen, and 1 is a crash
because nothing here raises it deliberately. A command reporting any of those as
another is believed by the timer that runs it, so every case asserts the code,
the account, and what the tree carries afterwards -- because the failures that
matter here are silent: a build rendered twice under two digests is a release
that refuses, and a fulfilment record written early is a finalizer concluding on
a build that has not happened.
"""

import hashlib
import json
import shutil
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
SCRIPTS = Path(sys.argv[2]).resolve()
WORK = Path(sys.argv[3]).resolve()

COMMIT = "5e37c51f5e588a11903bdfdc3d22e1e64f9bb96e"
# What chuggy's finalizer renders and commits, verbatim.
REQUESTED = (
    '{"apiVersion":"chuggy.dev/v1","kind":"ContainerBuildRequest","spec":'
    '{"builderProfile":"shipwright-buildkit-rootless-mini/v1","platforms":["linux/amd64"],'
    f'"source":{{"commit":"{COMMIT}",'
    '"repository":"https://github.com/kasofsk/chuggy.git"},'
    '"targetImageRepository":"registry.chuggy-registry.svc.cluster.local:5000/chuggy"}}'
)
API = "9565818d877f3df1c69b4a2776d3ff0fe3dc0da594847aee9b82bc69ea9bcec1"
WEB = "471cd9294f093cb0c498495c3f66c995d943947b9dd72866138165e49b489033"
UNANSWERABLE = 3

failures = []


def report(case, message):
    failures.append(f"{case}: {message}")


def reported():
    """Every case's verdict, and the suite's. Written out where the suite stops
    rather than only at the end, because a case that cannot go on -- the one
    below that holds a record nothing wrote -- would otherwise take every
    verdict before it with it."""
    for failure in failures:
        print(f"build requests: {failure}", file=sys.stderr)
    return 1 if failures else 0


def tree(case):
    """A checkout-shaped copy of what this repository carries under `builds/`
    and `results/`, writable, with nothing requested yet."""
    root = WORK / case
    root.mkdir(parents=True)
    for directory in ("builds", "results"):
        shutil.copytree(ROOT / directory, root / directory)
    for path in root.rglob("*"):
        path.chmod(path.stat().st_mode | 0o200)
    (root / "requests").mkdir()
    return root


def requested(root, document, repository_id="chuggy", commit=COMMIT, digest=None):
    """A request document filed where a finalizer files one. The name is the
    digest of chuggy's identity input, which nothing here can recompute, so a
    digest of the bytes stands in: this side reads it as a name."""
    encoded = document.encode()
    digest = digest or hashlib.sha256(encoded).hexdigest()
    path = root / "requests" / repository_id / commit / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return path.relative_to(root).as_posix(), digest


def altered(**overrides):
    """The verbatim document with one field replaced, minified the way it
    arrives so that what changed is the field and not the formatting."""
    document = json.loads(REQUESTED)
    for key, value in overrides.items():
        if key == "commit" or key == "repository":
            document["spec"]["source"][key] = value
        else:
            document["spec"][key] = value
    return json.dumps(document, separators=(",", ":"))


def fulfil(root):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "fulfil-build-requests"), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def expect(case, completed, code, created, phrases=()):
    if completed.returncode != code:
        report(
            case,
            f"expected exit {code}, got {completed.returncode}\n"
            f"{completed.stdout}\n{completed.stderr}",
        )
        return False
    announced = [line for line in completed.stdout.splitlines() if line]
    if announced != list(created):
        report(case, f"created {announced}, not {list(created)}")
        return False
    for phrase in phrases:
        if phrase not in completed.stderr:
            report(case, f"the account does not say {phrase!r}\n{completed.stderr}")
            return False
    return True


def fingerprint(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def carried(root, request):
    return root / "builds" / "chuggy" / COMMIT / f"{request}.yaml"


def record_of(root, digest):
    return root / "results" / "chuggy" / COMMIT / f"request-{digest}.json"


def unrequested(case, document, phrases, **filed):
    """A document this site will never answer: the run says 3, and nothing is
    rendered from it. Building any of it would be building for somewhere this
    site did not mean to publish, or from something it did not mean to clone."""
    root = tree(case)
    requested(root, document, **filed)
    before = fingerprint(root)
    expect(case, fulfil(root), UNANSWERABLE, [], phrases)
    if fingerprint(root) != before:
        report(case, "a request this site cannot answer still wrote to the tree")


def results_gate(root):
    """The gate this tree's results are held to, over a tree a request was
    answered in: it is what re-resolves the record, and this suite is where it
    is handed one."""
    return subprocess.run(
        [sys.executable, str(ROOT / "tests" / "build-results.py"), str(root), str(SCRIPTS)],
        capture_output=True,
        text=True,
        check=False,
    )


def released_images():
    """The images `scripts/render-release` moves, by the Dockerfile that builds
    each: the same pairs `scripts/build_sources.py` declares, read out of the
    renderer rather than restated."""
    sys.path.insert(0, str(SCRIPTS))
    path = SCRIPTS / "render-release"
    loader = SourceFileLoader("render_release", str(path))
    spec = spec_from_file_location("render_release", str(path), loader=loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    release = module.images(module.roster_of(SCRIPTS))
    return {image.dockerfile: image.repository for image in release}


def main():
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SCRIPTS))
    from build_sources import SOURCES

    # The request an operator answered by hand, answered by the command: the
    # same two manifests at the same two paths, byte for byte. Anything else is
    # a second renderer of one digest space, and a release that refuses because
    # one image has two requests at one commit.
    case = "renders-what-was-rendered-by-hand"
    root = tree(case)
    for request in (API, WEB):
        carried(root, request).unlink()
    document, digest = requested(root, REQUESTED)
    rendered = [
        f"builds/chuggy/{COMMIT}/{API}.yaml",
        f"builds/chuggy/{COMMIT}/{WEB}.yaml",
    ]
    answers = rendered + [f"results/chuggy/{COMMIT}/request-{digest}.json"]
    if expect(case, fulfil(root), 0, answers):
        for request in (API, WEB):
            rendered_bytes = carried(root, request).read_bytes()
            if rendered_bytes != (ROOT / carried(root, request).relative_to(root)).read_bytes():
                report(case, f"{request} is not the manifest this repository carries")
        answered = json.loads(record_of(root, digest).read_text())
        if answered != {
            "version": 1,
            "request": document,
            "source": {"repositoryId": "chuggy", "commit": COMMIT},
            "builds": [
                {
                    "dockerfile": "images/api/Dockerfile",
                    "request": API,
                    "result": f"results/chuggy/{COMMIT}/{API}/build-{API[:40]}-a1.json",
                },
                {
                    "dockerfile": "images/chuggy-ui/Dockerfile",
                    "request": WEB,
                    "result": f"results/chuggy/{COMMIT}/{WEB}/build-{WEB[:40]}-a1.json",
                },
            ],
        }:
            report(case, f"the record does not name what answered the request: {answered}")

        # And again over the tree it just answered. A run that rendered or
        # recorded anything a second time is a commit on the live branch every
        # time the timer fires.
        case = "answers-a-request-once"
        before = fingerprint(root)
        expect(case, fulfil(root), 0, [])
        if fingerprint(root) != before:
            report(case, "a second run over an answered request wrote to the tree")

        # And with one of the builds it rendered no longer in the tree, which is
        # what `scripts/retire-build-request` leaves behind. Nothing is written,
        # because the record is what says the request was answered: a command
        # that decided on the rendered path instead would render the retired
        # build back and let Flux run it again -- and would do the same to every
        # request ever answered the day the declaration, a profile digest or the
        # Shipwright version moves a digest.
        case = "renders-nothing-for-a-request-it-has-answered"
        carried(root, API).unlink()
        before = fingerprint(root)
        expect(case, fulfil(root), 0, [])
        if fingerprint(root) != before:
            report(case, "an answered request was rendered again after a build was retired")

    # A retried request is that same file carrying a later attempt. Re-rendering
    # it would report a request that changed, or put the retired attempt back.
    case = "leaves-a-retried-request-alone"
    root = tree(case)
    shutil.rmtree(root / "results" / "chuggy" / COMMIT)
    requested(root, REQUESTED)
    retried = carried(root, API)
    retried.write_text(
        retried.read_text().replace("-a1", "-a2").replace('ordinal: "1"', 'ordinal: "2"')
    )
    before = fingerprint(root)
    if expect(case, fulfil(root), 0, []):
        if fingerprint(root) != before:
            report(case, "a retried request was rendered over")

    # The record is what a finalizer concludes on, so it may not appear while a
    # build it names has no result: that finalizer would be reporting a build
    # that has not happened.
    case = "records-nothing-until-every-build-has-a-result"
    root = tree(case)
    shutil.rmtree(root / "results" / "chuggy" / COMMIT / WEB)
    document, digest = requested(root, REQUESTED)
    if expect(case, fulfil(root), 0, []) and record_of(root, digest).exists():
        report(case, "the request was recorded as answered with one build unanswered")

    # A record this tree carries is never written again: `results/` is
    # immutable, and a rewritten one is provenance replaced with other
    # provenance under the same name.
    case = "never-rewrites-a-record"
    root = tree(case)
    document, digest = requested(root, REQUESTED)
    record_of(root, digest).parent.mkdir(parents=True, exist_ok=True)
    record_of(root, digest).write_text("{}\n")
    before = fingerprint(root)
    if expect(case, fulfil(root), 0, []) and fingerprint(root) != before:
        report(case, "a record this tree already carried was written again")

    # Everything a document can ask for that this site does not answer. Each is
    # an image built from, or published to, somewhere nobody meant.
    unrequested(
        "refuses-another-registry",
        altered(targetImageRepository="registry.example.invalid/chuggy"),
        ["publishes to", "registry.example.invalid/chuggy"],
    )
    unrequested(
        "refuses-another-platform",
        altered(platforms=["linux/arm64"]),
        ["asks for platforms"],
    )
    unrequested(
        "refuses-another-source",
        altered(repository="https://github.com/someone/else.git"),
        ["builds", "someone/else"],
    )
    unrequested(
        "refuses-a-commit-that-is-not-its-path",
        altered(commit="0" * 40),
        ["which is not its path"],
    )
    unrequested(
        "refuses-a-profile-this-site-does-not-have",
        altered(builderProfile="shipwright-buildkit-rootless-enormous/v1"),
        ["builder profile", "does not have"],
    )
    unrequested(
        "refuses-a-source-this-site-does-not-declare",
        REQUESTED,
        ["declares no images for"],
        repository_id="someone-else",
    )
    unrequested(
        "refuses-a-document-of-another-kind",
        json.dumps({"apiVersion": "chuggy.dev/v1", "kind": "Something", "spec": {}}),
        ["is not a ContainerBuildRequest"],
    )
    unrequested("refuses-what-is-not-a-document", "{not json", ["could not be read as a request"])

    # A document nobody can answer is one request and not the run: the others
    # are independent of it and a finalizer is waiting for each.
    case = "answers-the-rest-of-a-tree-it-has-a-finding-in"
    root = tree(case)
    for request in (API, WEB):
        carried(root, request).unlink()
    requested(root, altered(platforms=["linux/arm64"], commit="1" * 40), commit="1" * 40)
    document, digest = requested(root, REQUESTED)
    expect(
        case,
        fulfil(root),
        UNANSWERABLE,
        [
            f"builds/chuggy/{COMMIT}/{API}.yaml",
            f"builds/chuggy/{COMMIT}/{WEB}.yaml",
            f"results/chuggy/{COMMIT}/request-{digest}.json",
        ],
        ["asks for platforms"],
    )

    # A file under `requests/` that is not one is a request nothing answers,
    # which is a finalizer waiting for its deadline with nothing to read.
    case = "refuses-a-stray-under-requests"
    root = tree(case)
    (root / "requests" / "stray.json").write_text("{}\n")
    expect(case, fulfil(root), UNANSWERABLE, [], ["is not <repository-id>/<source-commit>"])

    # The record is provenance like its neighbours, so the gate that holds this
    # tree's results has to resolve it rather than refuse the directory.
    case = "is-accepted-by-the-results-gate"
    root = tree(case)
    document, digest = requested(root, REQUESTED)
    fulfil(root)
    if results_gate(root).returncode != 0:
        report(case, f"the results gate refuses the answered tree: {results_gate(root).stderr}")

    # And the same gate is what makes the record checkable: it says a request
    # was answered by results this tree carries, and a record naming one it does
    # not carry says a build happened that did not.
    case = "is-refused-when-it-names-a-result-this-tree-has-not"
    if not record_of(root, digest).exists():
        report(case, "the request was not answered, so there is no record to hold")
        raise SystemExit(reported())
    answered = json.loads(record_of(root, digest).read_text())
    answered["builds"][0]["result"] = f"results/chuggy/{COMMIT}/{API}/build-{API[:40]}-a9.json"
    record_of(root, digest).write_text(json.dumps(answered))
    if results_gate(root).returncode == 0:
        report(case, "the results gate accepts a record naming a result this tree does not carry")

    # The images this site renders requests for and the images a release moves
    # are one set. An image declared in only one of them is either a build
    # nothing releases or a release that refuses for want of a result.
    case = "declares-the-images-a-release-moves"
    if SOURCES["chuggy"]["images"] != released_images():
        report(
            case,
            f"{SOURCES['chuggy']['images']} is not what render-release moves: {released_images()}",
        )

    raise SystemExit(reported())


main()
