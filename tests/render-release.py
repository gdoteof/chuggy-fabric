#!/usr/bin/env python3
"""Drive `scripts/render-release` through the releases it renders and every
refusal it states.

WHAT IS REAL HERE AND WHAT IS FIXTURE. The manifests are this repository's own
`cluster/apps`, re-annotated to the fixture's live commit: the script edits the
files a release is made of rather than a sketch of them, so a manifest that
grows a second image line or loses its annotation fails here. The source
history is a fixture repository whose paths are the ones the image map names,
because the map's claim -- that these paths are what each Dockerfile copies --
is about chuggy's tree, which no check in this repository can see. That claim
is the script's header and a reviewer's to hold.

The build results are rendered rather than written: each request comes from
`scripts/render-build-request` and each record is the canonical bytes the
recorder would have written for it, so what this drives is the verification
`scripts/build_provenance.py` performs, not a stub of it.

THE EXIT CODE IS THE VERDICT. Zero is a rendered release, 3 is a release the
script refuses, and 2 is a run that did not happen; a script reporting either
of the last two as the other is believed by whatever runs it. Every case
asserts the code and the account beside it.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
SCRIPTS = Path(sys.argv[2]).resolve()
WORK = Path(sys.argv[3]).resolve()

REGISTRY = "registry.chuggy-registry.svc.cluster.local:5000/chuggy"
SOURCE_URL = "https://github.com/kasofsk/chuggy.git"
PROFILE = {
    "name": "shipwright-buildkit-rootless-mini/v1",
    "digest": "sha256:b4d3bb9e36544a6bb1b51bdda3021fd628cb343960d2f0139a3cf1bb5fe5f0c5",
}
CONTROLLER = "v0.18.4"
RENDERER = "shipwright-build-request/v1"
BASE_FILES = {
    "package.json": '{"name":"chuggy"}\n',
    "package-lock.json": '{"lockfileVersion":3}\n',
    "src/roots/nativeHttp.ts": "export const serve = () => undefined\n",
    "src/contract/index.ts": "export type Contract = never\n",
    "scripts/console-policy.ts": "export const policy = []\n",
    "scripts/check-console-policy.ts": "export const check = () => true\n",
    "images/api/Dockerfile": "FROM node\nCOPY src ./src\n",
    "images/chuggy-ui/Dockerfile": "FROM node\nCOPY ui/chuggy-ui ui/chuggy-ui\n",
    "ui/chuggy-ui/app/main.ts": "export const main = () => undefined\n",
    "images/worker/Dockerfile": "FROM node\nCOPY images/worker/entrypoint.mjs .\n",
    "docs/runbook.md": "# runbook\n",
}
# One file per image, and one that belongs to no image: what a case moves is
# what decides which images the script has to find a digest for.
MOVES = {
    "api": ("src/roots/nativeHttp.ts",),
    "ui": ("ui/chuggy-ui/app/main.ts",),
    "both": ("src/roots/nativeHttp.ts", "ui/chuggy-ui/app/main.ts"),
    "worker": ("images/worker/Dockerfile",),
    "documentation": ("docs/runbook.md",),
}
DOCKERFILES = {
    "api": ("images/api/Dockerfile", "api"),
    "chuggy-ui": ("images/chuggy-ui/Dockerfile", "web"),
}
API_MANIFESTS = (
    "chuggy-api.yaml",
    "chuggy-configuration-importer.yaml",
    "chuggy-finalizer.yaml",
    "chuggy-migrate.yaml",
    "chuggy-scheduler.yaml",
    "chuggy-selector.yaml",
    "chuggy-ticket-service.yaml",
    "chuggy-worker-plane.yaml",
)
RELEASE_MANIFESTS = API_MANIFESTS + ("chuggy-ui.yaml",)

failures = []


def report(case, message):
    failures.append(f"{case}: {message}")


def git(repository, *arguments):
    environment = dict(
        os.environ,
        HOME=str(WORK),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="render-release tests",
        GIT_AUTHOR_EMAIL="tests@invalid",
        GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
        GIT_COMMITTER_NAME="render-release tests",
        GIT_COMMITTER_EMAIL="tests@invalid",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
    )
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"git {' '.join(arguments)}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def source_history():
    """A chuggy-shaped history: one base commit every case is deployed at, and
    one child per case moving exactly the paths that case is about."""
    repository = WORK / "source"
    repository.mkdir(parents=True)
    git(repository, "init", "--quiet", "--initial-branch", "main")
    for relative, content in BASE_FILES.items():
        write(repository, relative, content)
    git(repository, "add", "--all")
    git(repository, "commit", "--quiet", "--message", "base")
    base = git(repository, "rev-parse", "HEAD")
    commits = {"base": base}
    for case, paths in MOVES.items():
        git(repository, "checkout", "--quiet", "--detach", base)
        for relative in paths:
            write(repository, relative, BASE_FILES[relative] + f"// {case}\n")
        git(repository, "add", "--all")
        git(repository, "commit", "--quiet", "--message", case)
        commits[case] = git(repository, "rev-parse", "HEAD")
    git(repository, "checkout", "--quiet", "main")
    return repository, commits


def fabric(name, deployed):
    """The release as this repository carries it, moved back to the fixture's
    live commit so that what the script reads as deployed is the base of the
    fixture history."""
    root = WORK / name
    root.mkdir(parents=True)
    apps = root / "cluster" / "apps"
    shutil.copytree(ROOT / "cluster" / "apps", apps)
    # The copy may have come from a read-only store path, and what is under test
    # is a command that edits these files in place.
    for path in apps.rglob("*"):
        path.chmod(path.stat().st_mode | 0o200)
    for path in apps.glob("*.yaml"):
        path.write_text(
            re.sub(
                r"^([ \t]*fabric\.chuggy\.dev/source-commit:[ \t]*).*$",
                rf"\g<1>{deployed[:8]}",
                path.read_text(),
                flags=re.MULTILINE,
            )
        )
    # Only where the Job is: the same name reads in the network policy beside it,
    # and a fixture that re-seeded that one would not be this tree any more.
    job = apps / "chuggy-migrate.yaml"
    job.write_text(
        re.sub(
            r"^([ \t]*name: chuggy-migrate-)[a-z0-9-]*$",
            rf"\g<1>{deployed[:8]}-registry",
            job.read_text(),
            flags=re.MULTILINE,
        )
    )
    return root


def request(root, commit, dockerfile, repository, cache):
    """A build request rendered by the command that renders every other one, so
    what a record is held against here is a real request."""
    completed = subprocess.run(
        [
            str(SCRIPTS / "render-build-request"),
            "--repository-id",
            "chuggy",
            "--source-url",
            SOURCE_URL,
            "--source-commit",
            commit,
            "--source-secret",
            "chuggy-build-source-read",
            "--target-image-repository",
            f"{REGISTRY}/{repository}",
            "--output-secret",
            "chuggy-registry-build-push",
            "--dockerfile",
            dockerfile,
            "--cache",
            cache,
            "--profile",
            "mini",
            "--output-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"render-build-request: {completed.stderr.strip()}")
    return Path(completed.stdout.strip()).stem


def record(root, commit, image, digest, succeeded=True, ordinal=1, cache="disabled"):
    """The bytes the recorder would have published for one attempt: the result
    canonicalized exactly as the verifier canonicalizes it, the record's own
    digest over that, and the checksum over the file. `cache` is how a second
    request for the same image at the same commit gets a second digest, which
    is the only way this tree carries two results for one image."""
    dockerfile, repository = DOCKERFILES[image]
    request_digest = request(root, commit, dockerfile, repository, cache)
    attempt = f"build-{request_digest[:40]}-a{ordinal}"
    result = {
        "attempt": {"name": attempt, "ordinal": ordinal},
        "controller": CONTROLLER,
        "output": {
            "digest": digest if succeeded else None,
            "repository": f"{REGISTRY}/{repository}",
        },
        "profile": PROFILE,
        "renderer": RENDERER,
        "requestDigest": f"sha256:{request_digest}",
        "source": {
            "observedCommit": commit if succeeded else None,
            "repositoryId": "chuggy",
            "requestedCommit": commit,
        },
        "terminalCondition": {
            "lastTransitionTime": "2026-01-01T00:00:00Z",
            "message": "All Steps have completed executing",
            "reason": "Succeeded" if succeeded else "Failed",
            "status": "True" if succeeded else "False",
            "type": "Succeeded",
        },
        "timestamps": {"completed": "2026-01-01T00:00:00Z", "started": "2026-01-01T00:00:00Z"},
    }
    canonical = (json.dumps(result, sort_keys=True, indent=2, separators=(",", ": ")) + "\n").encode()
    document = {
        "provenanceRecordDigest": f"sha256:{hashlib.sha256(canonical).hexdigest()}",
        "result": result,
    }
    directory = root / "results" / "chuggy" / commit / request_digest
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{attempt}.json"
    encoded = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(encoded)
    path.with_name(f"{attempt}.json.sha256").write_text(
        f"sha256:{hashlib.sha256(encoded).hexdigest()}\n"
    )
    return path.relative_to(root).as_posix()


def render(root, target, source, *arguments, environment=None):
    return subprocess.run(
        [
            str(SCRIPTS / "render-release"),
            "--target-commit",
            target,
            "--fabric-root",
            str(root),
            "--source-tree",
            str(source),
            *arguments,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def expect(case, completed, code, phrases):
    if completed.returncode != code:
        report(
            case,
            f"expected exit {code}, got {completed.returncode}\n"
            f"{completed.stdout}\n{completed.stderr}",
        )
        return False
    output = completed.stdout + completed.stderr
    for phrase in phrases:
        if phrase not in output:
            report(case, f"the account does not say {phrase!r}\n{output}")
            return False
    return True


def annotations(root):
    values = set()
    for name in RELEASE_MANIFESTS:
        for match in re.finditer(
            r"^[ \t]*fabric\.chuggy\.dev/source-commit:[ \t]*([0-9a-f]+)[ \t]*$",
            (root / "cluster" / "apps" / name).read_text(),
            re.MULTILINE,
        ):
            values.add(match.group(1))
    return values


def digest_of(root, manifest, repository):
    match = re.search(
        rf"^[ \t]*image: registry\.chuggy\.internal/chuggy/{repository}@(sha256:[0-9a-f]{{64}})[ \t]*$",
        (root / "cluster" / "apps" / manifest).read_text(),
        re.MULTILINE,
    )
    return match.group(1) if match else None


def accepts(case, root):
    completed = subprocess.run(
        [str(SCRIPTS / "check-release-consistency"), str(root / "cluster" / "apps")],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        report(case, f"check-release-consistency refuses the rendered tree: {completed.stderr}")


def fingerprint(root):
    apps = root / "cluster" / "apps"
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(apps.glob("*.yaml"))
    }


NEW_API = "sha256:" + "a1" * 32
NEW_UI = "sha256:" + "b2" * 32
OTHER_UI = "sha256:" + "c3" * 32


def main():
    source, commits = source_history()
    base = commits["base"]

    # A console release: the console's inputs moved and nothing else did, so one
    # manifest takes a digest and every manifest takes the commit.
    case = "console-only"
    root = fabric(case, base)
    carried_api = digest_of(root, "chuggy-api.yaml", "api")
    selected = record(root, commits["ui"], "chuggy-ui", NEW_UI)
    if expect(case, render(root, commits["ui"], source), 0, ["moved, selected from " + selected]):
        accepts(case, root)
        if digest_of(root, "chuggy-ui.yaml", "web") != NEW_UI:
            report(case, "chuggy-ui.yaml does not select the recorded digest")
        if digest_of(root, "chuggy-api.yaml", "api") != carried_api:
            report(case, "the api did not keep the digest it is deployed at")
        if annotations(root) != {commits["ui"][:8]}:
            report(case, f"the release does not annotate one commit: {annotations(root)}")

    # An api release: every control-plane manifest the check names takes the
    # digest, which is the half a per-manifest edit gets wrong.
    case = "api-only"
    root = fabric(case, base)
    carried_ui = digest_of(root, "chuggy-ui.yaml", "web")
    record(root, commits["api"], "api", NEW_API)
    if expect(case, render(root, commits["api"], source), 0, ["api"]):
        accepts(case, root)
        for manifest in API_MANIFESTS:
            if digest_of(root, manifest, "api") != NEW_API:
                report(case, f"{manifest} does not select the recorded api digest")
        if digest_of(root, "chuggy-ui.yaml", "web") != carried_ui:
            report(case, "the console did not keep the digest it is deployed at")
        job = re.search(
            r"^[ \t]*name: (chuggy-migrate-[a-z0-9-]+)[ \t]*$",
            (root / "cluster" / "apps" / "chuggy-migrate.yaml").read_text(),
            re.MULTILINE,
        )
        if job is None or job.group(1) != f"chuggy-migrate-{commits['api'][:8]}-registry":
            report(case, f"the migrate Job is not named for the release: {job and job.group(1)}")

    # Both buildable images at once.
    case = "api-and-console"
    root = fabric(case, base)
    record(root, commits["both"], "api", NEW_API)
    record(root, commits["both"], "chuggy-ui", NEW_UI)
    if expect(case, render(root, commits["both"], source), 0, []):
        accepts(case, root)
        if digest_of(root, "chuggy-api.yaml", "api") != NEW_API:
            report(case, "the api did not move")
        if digest_of(root, "chuggy-ui.yaml", "web") != NEW_UI:
            report(case, "the console did not move")

    # A release no image is in: the annotations and the Job move, and nothing
    # restarts for a commit that changed nothing an image carries.
    case = "documentation-only"
    root = fabric(case, base)
    before = fingerprint(root)
    if expect(case, render(root, commits["documentation"], source), 0, ["carried forward"]):
        accepts(case, root)
        if annotations(root) != {commits["documentation"][:8]}:
            report(case, "the release does not annotate the target commit")
        edited = {name for name, sum_ in fingerprint(root).items() if before[name] != sum_}
        if edited != set(RELEASE_MANIFESTS):
            report(case, f"the edit did not land on exactly the release: {sorted(edited)}")

    # The fulfilment record `scripts/fulfil-build-requests` files beside the
    # attempts of a commit. It is an index of results and not one, so a release
    # that read it as an attempt would refuse every commit a request answered.
    case = "fulfilment-record-beside-the-results"
    root = fabric(case, base)
    selected = record(root, commits["ui"], "chuggy-ui", NEW_UI)
    answered = root / "results" / "chuggy" / commits["ui"] / f"request-{'a5' * 32}.json"
    answered.write_text(json.dumps({"version": 1, "builds": [{"result": selected}]}) + "\n")
    if expect(case, render(root, commits["ui"], source), 0, ["moved, selected from " + selected]):
        accepts(case, root)

    # The refusal the fabric-rollout brief exists for: the inputs moved and the
    # image that would carry them has not been built at that commit.
    case = "no-result"
    root = fabric(case, base)
    before = fingerprint(root)
    expect(
        case,
        render(root, commits["api"], source),
        3,
        ["api", "images/api/Dockerfile", "Render a build request"],
    )
    if fingerprint(root) != before:
        report(case, "a refused release still edited the manifests")

    # A failed attempt at the target commit is not a result, and the refusal
    # says so rather than reporting a request nobody made.
    case = "failed-attempt"
    root = fabric(case, base)
    record(root, commits["api"], "api", None, succeeded=False)
    expect(case, render(root, commits["api"], source), 3, ["did not succeed"])

    # Two results for one image at one commit, selecting different digests.
    # Nothing here can know which is the release, so neither is.
    case = "ambiguous-results"
    root = fabric(case, base)
    record(root, commits["ui"], "chuggy-ui", NEW_UI)
    record(root, commits["ui"], "chuggy-ui", OTHER_UI, cache="registry")
    expect(case, render(root, commits["ui"], source), 3, ["select different digests"])

    # A commit that rebuilds the worker image is not a release of it -- no
    # manifest selects that image -- and the account has to say so anyway.
    case = "worker-moved"
    root = fabric(case, base)
    if expect(case, render(root, commits["worker"], source), 0, ["images/worker moved since"]):
        accepts(case, root)

    # The bytes and the checksum beside them are what make a record a record,
    # and a record that fails that is a fact about the tree: a refusal, not a
    # crash, and not something a caller reads as "the script broke".
    case = "checksum-mismatch"
    root = fabric(case, base)
    selected = record(root, commits["ui"], "chuggy-ui", NEW_UI)
    (root / f"{selected}.sha256").write_text(f"sha256:{'0' * 64}\n")
    expect(case, render(root, commits["ui"], source), 3, ["build result checksum mismatch"])

    # The verifier is a shell script with tools of its own, and a tool it cannot
    # find is a run that did not happen. Reported as a refusal it would read as
    # a rollout that cannot be produced yet, which is a different instruction.
    case = "verifier-cannot-run"
    root = fabric(case, base)
    record(root, commits["ui"], "chuggy-ui", NEW_UI)
    # Everything the run needs except what the verifier reaches for: git for the
    # path diff, and the two interpreters an unpatched checkout resolves its own
    # shebangs through.
    thin = WORK / "thin-path"
    thin.mkdir(exist_ok=True)
    missing = []
    for command in ("git", "python3", "bash"):
        found = shutil.which(command)
        if found is None:
            missing.append(command)
            continue
        link = thin / command
        if not link.exists():
            link.symlink_to(found)
    if missing:
        report(case, f"{', '.join(missing)} is not on PATH, so the thinned PATH proves nothing")
    else:
        expect(
            case,
            render(
                root,
                commits["ui"],
                source,
                environment=dict(os.environ, PATH=str(thin)),
            ),
            2,
            ["cannot run", "sha256sum"],
        )

    # The path is an identity: a request whose annotations declare another
    # commit verifies against its own record perfectly, and would put an image
    # built from that other commit into this release.
    case = "misfiled-request"
    root = fabric(case, base)
    stray = WORK / f"{case}-stray"
    stray.mkdir()
    strayed = record(stray, commits["api"], "chuggy-ui", NEW_UI)
    request_digest = Path(strayed).parent.name
    for source_path, destination in (
        (
            stray / "builds" / "chuggy" / commits["api"] / f"{request_digest}.yaml",
            root / "builds" / "chuggy" / commits["ui"] / f"{request_digest}.yaml",
        ),
        (
            stray / "results" / "chuggy" / commits["api"] / request_digest,
            root / "results" / "chuggy" / commits["ui"] / request_digest,
        ),
    ):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            shutil.copytree(source_path, destination)
        else:
            shutil.copy(source_path, destination)
    expect(
        case,
        render(root, commits["ui"], source),
        3,
        ["declares another repository or source commit"],
    )

    # And the other half of that identity: a record filed under a request that
    # is not the one it answers.
    case = "misfiled-record"
    root = fabric(case, base)
    answered = Path(record(root, commits["ui"], "chuggy-ui", NEW_UI)).parent
    other = request(root, commits["ui"], "images/chuggy-ui/Dockerfile", "web", "registry")
    shutil.copytree(root / answered, root / answered.parent / other)
    shutil.rmtree(root / answered)
    expect(case, render(root, commits["ui"], source), 3, ["records another request digest"])

    # A record whose request this tree does not carry is a record nothing can
    # identify, and identifying it is how the image it belongs to is decided.
    case = "orphan-result"
    root = fabric(case, base)
    selected = record(root, commits["ui"], "chuggy-ui", NEW_UI)
    for stale in (root / "builds").rglob("*.yaml"):
        stale.unlink()
    expect(case, render(root, commits["ui"], source), 3, ["which this tree does not carry"])

    # A tree the consistency check already refuses: what is live cannot be read
    # off manifests that do not agree on it, so nothing is rendered over them.
    case = "inconsistent-tree"
    root = fabric(case, base)
    manifest = root / "cluster" / "apps" / "chuggy-selector.yaml"
    manifest.write_text(
        re.sub(
            r"^([ \t]*fabric\.chuggy\.dev/source-commit:[ \t]*).*$",
            r"\g<1>abcdef0",
            manifest.read_text(),
            flags=re.MULTILINE,
        )
    )
    expect(
        case,
        render(root, commits["api"], source),
        3,
        ["not at a release this command can move", "do not identify one source commit"],
    )

    # The release that is already rendered. Rendering it again would be an
    # empty pull request rather than an error.
    case = "already-there"
    root = fabric(case, base)
    expect(case, render(root, base, source), 0, ["already at", base[:8]])

    # The two ways this cannot run: an argument that is not a commit, and a
    # source that does not carry what the manifests say is live.
    case = "abbreviated-target"
    root = fabric(case, base)
    expect(case, render(root, base[:8], source), 2, ["full 40-character commit"])

    case = "source-without-the-live-commit"
    root = fabric(case, base)
    empty = WORK / "empty-source"
    empty.mkdir()
    git(empty, "init", "--quiet", "--initial-branch", "main")
    expect(
        case,
        render(root, commits["api"], empty),
        2,
        ["what is live cannot be read", base[:8]],
    )

    case = "source-that-is-not-a-checkout"
    root = fabric(case, base)
    expect(case, render(root, commits["api"], WORK / "not-a-repository"), 2, ["not a directory"])

    if failures:
        for failure in failures:
            print(f"render-release tests: {failure}", file=sys.stderr)
        raise SystemExit(1)


main()
