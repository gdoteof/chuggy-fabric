#!/usr/bin/env python3
"""Drive `scripts/request-build` and `scripts/fulfil-build-requests` over the
requests one files and the other answers, and every refusal each states.

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
would be changing what the fabric claims to consume. `scripts/request-build` is
this site's own writer of that document, and the first case holds what it files
to those same bytes and then answers it: the two are one document, or the loop
has two ends that disagree and each reads correctly alone.

THE EXIT CODE IS THE VERDICT. Zero is a tree these commands answered or filed
into, 3 is a document one will never answer and a request the other will not
file, 2 is a run that did not happen, and 1 is a crash because nothing here
raises it deliberately. A command reporting any of those as another is believed
by the timer that runs one and the ticket that runs the other, so every case
asserts the code, the account, and what the tree carries afterwards -- because
the failures that matter here are silent: a build rendered twice under two
digests is a release that refuses, and a fulfilment record written early is a
rollout concluding on a build that has not happened.
"""

import hashlib
import json
import os
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
# The request document this site is built to answer, verbatim.
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
# The same number from the filing end of the loop: what this site will not do.
REFUSAL = 3
UNRUNNABLE = 2

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
    """A request document filed where the fabric ticket files one. The name is the
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


def moved_declaration(case):
    """A copy of `scripts/` whose declaration for chuggy names another builder
    profile. Filing at one commit on either side of such a move is what leaves
    two documents there; writing the second by hand would be a fixture asserting
    its own shape."""
    moved = WORK / f"{case}-scripts"
    shutil.copytree(SCRIPTS, moved)
    declaration = moved / "build_sources.py"
    text = declaration.read_text()
    moved_text = text.replace('"profile": "mini",', '"profile": "dedicated",')
    assert moved_text != text, "the declaration no longer names the profile it did"
    declaration.write_text(moved_text)
    return moved


def declared_at(case, url):
    """A copy of `scripts/` whose declaration for chuggy names another source
    URL: the one a ref is resolved against, so a case about resolution reaches
    a repository this suite made rather than the network."""
    declared = WORK / f"{case}-scripts"
    shutil.copytree(SCRIPTS, declared)
    declaration = declared / "build_sources.py"
    text = declaration.read_text()
    declared_text = text.replace(
        '"url": "https://github.com/kasofsk/chuggy.git",', f'"url": "{url}",'
    )
    assert declared_text != text, "the declaration no longer names the URL it did"
    declaration.write_text(declared_text)
    return declared


def source(case):
    """A source repository with one commit on `main`, standing in for the
    branch a ticket resolves."""
    repository = WORK / f"{case}-source"
    repository.mkdir(parents=True)
    environment = dict(
        os.environ,
        GIT_AUTHOR_NAME="build requests tests",
        GIT_AUTHOR_EMAIL="tests@invalid",
        GIT_COMMITTER_NAME="build requests tests",
        GIT_COMMITTER_EMAIL="tests@invalid",
    )
    for arguments in (
        ("init", "--quiet", "--initial-branch", "main"),
        ("commit", "--quiet", "--allow-empty", "--message", "the source"),
    ):
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            env=environment, capture_output=True, text=True, check=False,
        )
        if completed.returncode != 0:
            raise SystemExit(f"fixture: git {' '.join(arguments)}: {completed.stderr}")
    return repository, subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def request_build(root, repository_id="chuggy", commit=COMMIT, scripts=None, ref=None):
    return subprocess.run(
        [
            sys.executable,
            str((scripts or SCRIPTS) / "request-build"),
            "--repository-id", repository_id,
            *(["--source-ref", ref] if ref else ["--source-commit", commit]),
            "--root", str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def announced(payload):
    """The whole of what a command a ticket engine runs may put on stdout: one
    JSON object, which is the result the engine reads. A second line, or a line
    that is not that object, is a task that failed whatever the command meant."""
    return [json.dumps(payload)]


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


def unfiled(case, phrases, **asked):
    """A request this site will not file: the run says 3, and the tree is as it
    was. A ticket reading any other verdict either lands a document nobody can
    answer or waits out its deadline for a build nothing asked for."""
    root = tree(case)
    before = fingerprint(root)
    expect(case, request_build(root, **asked), REFUSAL, [], phrases)
    if fingerprint(root) != before:
        report(case, "a request this site refused to file still wrote to the tree")


def main():
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SCRIPTS))
    from build_sources import SOURCES

    # What a source ticket files, and what this site answers, are one document.
    # The bytes are held to `REQUESTED` -- chuggy's own renderer's, which nothing
    # here can reach -- and then handed to the consumer, because a document that
    # matched those bytes and rendered differently would be a parity claim about
    # a string rather than about the loop.
    case = "files-the-document-this-site-answers"
    root = tree(case)
    for request in (API, WEB):
        carried(root, request).unlink()
    digest = hashlib.sha256(REQUESTED.encode()).hexdigest()
    filed = f"requests/chuggy/{COMMIT}/{digest}.json"
    if expect(case, request_build(root), 0, announced({"request": filed})):
        if (root / filed).read_bytes() != REQUESTED.encode():
            report(case, "what was filed is not the document this site is built to answer")
        answers = [
            f"builds/chuggy/{COMMIT}/{API}.yaml",
            f"builds/chuggy/{COMMIT}/{WEB}.yaml",
            f"results/chuggy/{COMMIT}/request-{digest}.json",
        ]
        if expect(case, fulfil(root), 0, answers):
            for request in (API, WEB):
                manifest = carried(root, request)
                if manifest.read_bytes() != (ROOT / manifest.relative_to(root)).read_bytes():
                    report(case, f"{request} is not the manifest this repository carries")

    # A run that finds its own request already filed has written nothing, and a
    # work stage that writes nothing lands an empty change: the finalizer
    # refuses that as contradictory, and a ticket engine makes it a pull request
    # with no commits. So it is a refusal with an account, not a quiet zero.
    case = "refuses-a-request-it-has-already-filed"
    root = tree(case)
    expect(case, request_build(root), 0, announced({"request": filed}))
    before = fingerprint(root)
    expect(case, request_build(root), REFUSAL, [], ["is already filed"])
    if fingerprint(root) != before:
        report(case, "a request this tree already carried was written again")

    # A declaration that moved between two filings would leave two documents at
    # one commit. Nothing downstream recovers from that -- the consumer can
    # never answer the older one again, the wait can never return 0 for the
    # commit again, and `requests/` is never pruned -- so it is refused by the
    # only command that can see it before it lands.
    case = "refuses-a-second-request-at-one-commit"
    root = tree(case)
    expect(case, request_build(root), 0, announced({"request": filed}))
    before = fingerprint(root)
    expect(
        case,
        request_build(root, scripts=moved_declaration(case)),
        REFUSAL,
        [],
        ["already carries", f"{digest}.json"],
    )
    if fingerprint(root) != before:
        report(case, "a commit that already carries a request was filed at again")

    # The name is the digest of the bytes, so anything else under it was written
    # by something that is not this command, and writing over it would be this
    # command deciding what a hand-edited request meant.
    case = "refuses-a-request-that-is-not-the-one-at-its-name"
    root = tree(case)
    (root / filed).parent.mkdir(parents=True, exist_ok=True)
    (root / filed).write_text("{}")
    before = fingerprint(root)
    expect(case, request_build(root), REFUSAL, [], ["is not the request this site would file"])
    if fingerprint(root) != before:
        report(case, "a document this command did not write was written over")

    # A build is pinned to a full commit; an abbreviation names a different one
    # as the source grows, and the consumer would refuse the document later,
    # after a ticket had landed it.
    unfiled(
        "refuses-a-commit-that-is-not-a-full-one",
        ["is not a full source commit"],
        commit=COMMIT[:12],
    )
    unfiled(
        "files-nothing-for-a-source-this-site-declares-no-images-for",
        ["declares no images for"],
        repository_id="someone-else",
    )

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

    # The record is what the rollout's wait concludes on, so it may not appear
    # while a build it names has no result: that rollout would be releasing a
    # build that has not happened.
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
    # A profile this site has but did not declare for this source is a build
    # scheduled against a node property the running host does not carry, which
    # is a request that renders and never starts.
    unrequested(
        "refuses-a-profile-this-site-did-not-declare-for-the-source",
        altered(builderProfile="shipwright-buildkit-rootless/v1"),
        ["builder profile", "is built with the"],
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
    # A name that is not a request digest, carrying a document this site would
    # otherwise answer: what is refused is the name. `results/` mirrors it --
    # the record is `request-<digest>.json` -- so a request filed under anything
    # else is one nothing can record, and a ticket waiting out its deadline.
    unrequested(
        "refuses-a-request-named-by-something-that-is-not-a-digest",
        REQUESTED,
        ["is not filed under a repository, a commit and a request digest"],
        digest="0" * 40,
    )

    # A document nobody can answer is one request and not the run: the others
    # are independent of it and a rollout is waiting for each.
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
    # which is a wait running to its deadline with nothing to read.
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

    # A ticket cannot know the commit it asks for, so it names a ref and the
    # command resolves it -- against the declared source and nothing else,
    # because a URL passed beside the ref would be a second home for the one
    # the document carries. What is filed is the request for that commit.
    case = "resolves-a-ref-against-the-declared-source"
    root = tree(case)
    repository, head = source(case)
    scripts = declared_at(case, repository)
    completed = request_build(root, scripts=scripts, ref="refs/heads/main")
    filed = sorted(path for path in root.glob(f"requests/chuggy/{head}/*.json"))
    if completed.returncode != 0 or len(filed) != 1:
        report(case, f"expected one request filed at {head}, got exit {completed.returncode}: "
               f"{[p.name for p in filed]}\n{completed.stderr}")
    else:
        document = json.loads(filed[0].read_bytes())
        if document["spec"]["source"] != {"commit": head, "repository": str(repository)}:
            report(case, f"the document names another source: {document['spec']['source']}")
        expect(case, completed, 0, announced({"request": filed[0].relative_to(root).as_posix()}))

    # A ref the source does not have is a run that could not start, not a
    # request refused and not one filed: nothing decides it but the source.
    case = "cannot-run-when-the-ref-does-not-resolve"
    root = tree(case)
    repository, head = source(case)
    scripts = declared_at(case, repository)
    before = fingerprint(root)
    if expect(case, request_build(root, scripts=scripts, ref="refs/heads/nowhere"), UNRUNNABLE,
              [], ["refs/heads/nowhere could not be resolved"]) and fingerprint(root) != before:
        report(case, "a request was filed for a ref that does not resolve")

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
