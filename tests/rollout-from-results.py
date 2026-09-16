#!/usr/bin/env python3
"""Drive `scripts/rollout-from-results` through the one run a rollout ticket
makes of it and every verdict it reaches instead.

WHAT THE FIXTURE IS. A bare repository standing in for the branch Flux
follows, carrying the request a source ticket landed and the record this site
answered it with; a clone of it standing in for the rollout ticket's checkout,
with this repository's own `cluster/apps` copied in and re-annotated to the
fixture's live commit; and a chuggy-shaped history whose branches are the
commits a case wants released, so that which commit the command resolves is
read off `--source-ref` and never told to it. No case moves an image's inputs
except the one about the renderer's refusal, so no case needs a verified
result: what is held here is the wrapper -- the order, the bound, the exit
classes and the stdout -- and `tests/render-release.py` holds what it wraps.
The fast-forward between the two is held the same way: after a run whose
record landed while it waited, the checkout is at the branch and carries that
record, and that the renderer reads a record from the tree it is given is that
suite's to hold.

THE EXIT CODE IS THE VERDICT AND STDOUT IS THE RESULT. Zero is a release
rendered and one JSON object naming it; 3 is a refusal, whether the wait's or
the renderer's or the run's own; 2 is a run that could not happen. A ticket
engine reads the code and the object and nothing else, so every case asserts
both, and the account beside them.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
SCRIPTS = Path(sys.argv[2]).resolve()
WORK = Path(sys.argv[3]).resolve()

RELEASED = 0
UNRUNNABLE = 2
REFUSAL = 3
DIGEST = "c" * 64
BASE_FILES = {
    "package.json": '{"name":"chuggy"}\n',
    "src/roots/nativeHttp.ts": "export const serve = () => undefined\n",
    "docs/runbook.md": "# runbook\n",
}
# One branch per case: the commit a case releases is whatever its branch is
# at, resolved by the command and never passed to it.
BRANCHES = {
    "documentation": ("docs/runbook.md",),
    "api": ("src/roots/nativeHttp.ts",),
}

failures = []


def report(case, message):
    failures.append(f"{case}: {message}")


def reported():
    for failure in failures:
        print(f"rollout from results: {failure}", file=sys.stderr)
    return 1 if failures else 0


def command():
    """The command under test, imported for the cap it states rather than for
    anything it does: a cap restated here would be a cap this suite proves
    against itself."""
    sys.dont_write_bytecode = True
    path = SCRIPTS / "rollout-from-results"
    loader = SourceFileLoader("rollout_from_results", str(path))
    spec = spec_from_file_location("rollout_from_results", str(path), loader=loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


CAP_SECS = command().loaded("await-build-results").CAP_SECS


def git(root, *arguments):
    environment = dict(
        os.environ,
        HOME=str(WORK),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="rollout tests",
        GIT_AUTHOR_EMAIL="tests@invalid",
        GIT_COMMITTER_NAME="rollout tests",
        GIT_COMMITTER_EMAIL="tests@invalid",
    )
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"fixture: git {' '.join(arguments)}: {completed.stderr}")
    return completed.stdout.strip()


def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def source_history():
    """A chuggy-shaped history: `base`, which every case is deployed at, and
    one branch per case moving the paths that case is about."""
    repository = WORK / "source"
    repository.mkdir(parents=True)
    git(repository, "init", "--quiet", "--initial-branch", "base")
    for relative, content in BASE_FILES.items():
        write(repository, relative, content)
    git(repository, "add", "--all")
    git(repository, "commit", "--quiet", "--message", "base")
    commits = {"base": git(repository, "rev-parse", "HEAD")}
    for branch, paths in BRANCHES.items():
        git(repository, "checkout", "--quiet", "-b", branch, commits["base"])
        for relative in paths:
            write(repository, relative, BASE_FILES[relative] + f"// {branch}\n")
        git(repository, "add", "--all")
        git(repository, "commit", "--quiet", "--message", branch)
        commits[branch] = git(repository, "rev-parse", "HEAD")
    git(repository, "checkout", "--quiet", "base")
    return repository, commits


def document(commit):
    return json.dumps(
        {
            "apiVersion": "chuggy.dev/v1",
            "kind": "ContainerBuildRequest",
            "spec": {"source": {"commit": commit}},
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def requested(commit):
    return {f"requests/chuggy/{commit}/{DIGEST}.json": document(commit)}


def answered(commit):
    """The record `scripts/fulfil-build-requests` files. Only its name is read
    by the wait, and the renderer reads past it as an index and not a result."""
    return {
        f"results/chuggy/{commit}/request-{DIGEST}.json": json.dumps(
            {"version": 1, "request": f"requests/chuggy/{commit}/{DIGEST}.json", "builds": []}
        )
        + "\n"
    }


def branch(case, files):
    """The branch Flux follows, carrying `files`, and the ticket's clone of it
    with this repository's release copied in at the fixture's base."""
    origin = WORK / case / "origin.git"
    seed = WORK / case / "seed"
    origin.parent.mkdir(parents=True, exist_ok=True)
    git(WORK, "init", "--quiet", "--bare", "-b", "main", str(origin))
    git(WORK, "init", "--quiet", "-b", "main", str(seed))
    git(seed, "remote", "add", "origin", f"file://{origin}")
    write(seed, "docs/keep-me", "so that an empty branch is still a branch\n")
    for relative, content in files.items():
        write(seed, relative, content)
    git(seed, "add", "-A")
    git(seed, "commit", "--quiet", "-m", "the branch")
    git(seed, "push", "--quiet", "origin", "main")
    clone = WORK / case / "clone"
    git(WORK, "clone", "--quiet", f"file://{origin}", str(clone))
    return clone


def land(case, files, message):
    """`files`, pushed to the branch by the publisher's stand-in after the
    ticket's clone was taken."""
    seed = WORK / case / "seed"
    for relative, content in files.items():
        write(seed, relative, content)
    git(seed, "add", "-A")
    git(seed, "commit", "--quiet", "-m", message)
    git(seed, "push", "--quiet", "origin", "main")


def deployed(clone, commit):
    """This repository's `cluster/apps`, moved back to the fixture's live
    commit so that what the renderer reads as deployed is the base of the
    history. The copy may have come from a read-only store path, and what is
    under test edits these files in place."""
    apps = clone / "cluster" / "apps"
    shutil.copytree(ROOT / "cluster" / "apps", apps)
    for path in apps.rglob("*"):
        path.chmod(path.stat().st_mode | 0o200)
    for path in apps.glob("*.yaml"):
        path.write_text(
            re.sub(
                r"^([ \t]*fabric\.chuggy\.dev/source-commit:[ \t]*).*$",
                rf"\g<1>{commit[:8]}",
                path.read_text(),
                flags=re.MULTILINE,
            )
        )
    job = apps / "chuggy-migrate.yaml"
    job.write_text(
        re.sub(
            r"^([ \t]*name: chuggy-migrate-)[a-z0-9-]*$",
            rf"\g<1>{commit[:8]}-registry",
            job.read_text(),
            flags=re.MULTILINE,
        )
    )
    return apps


def annotations(apps):
    values = set()
    for path in apps.glob("*.yaml"):
        for match in re.finditer(
            r"^[ \t]*fabric\.chuggy\.dev/source-commit:[ \t]*([0-9a-f]+)[ \t]*$",
            path.read_text(),
            re.MULTILINE,
        ):
            values.add(match.group(1))
    return values


def fingerprint(apps):
    return {path.name: path.read_bytes() for path in sorted(apps.glob("*.yaml"))}


def stalled(case):
    """A remote that accepts a connection and answers nothing, ever."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    return listener, f"git://127.0.0.1:{listener.getsockname()[1]}/{case}.git"


def slow_git(case, resolve_secs, fetch_secs):
    """A `git` for the front of PATH whose `ls-remote` and every `fetch` take
    that long before it is the real one: a remote over a network, where the
    resolve eats most of a second and the wait's last round is not
    milliseconds."""
    directory = WORK / f"{case}-bin"
    directory.mkdir(parents=True)
    stub = directory / "git"
    real = shutil.which("git")
    stub.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, time\n"
        'if "ls-remote" in sys.argv[1:]:\n'
        f"    time.sleep({resolve_secs})\n"
        'if "fetch" in sys.argv[1:]:\n'
        f"    time.sleep({fetch_secs})\n"
        f"os.execv({real!r}, [{real!r}] + sys.argv[1:])\n"
    )
    stub.chmod(0o755)
    return directory


def landing_git(case, files):
    """A `git` for the front of PATH that lands `files` on the branch before
    the first fetch and is the real one otherwise: the publisher pushing the
    record while the run waits, after the checkout the run was given was
    taken."""
    directory = WORK / f"{case}-bin"
    directory.mkdir(parents=True)
    seed = WORK / case / "seed"
    landed = directory / "landed"
    real = shutil.which("git")
    stub = directory / "git"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, subprocess, sys\n"
        f"landed = pathlib.Path({str(landed)!r})\n"
        'if "fetch" in sys.argv[1:] and not landed.exists():\n'
        f"    for relative, content in {files!r}.items():\n"
        f"        path = pathlib.Path({str(seed)!r}) / relative\n"
        "        path.parent.mkdir(parents=True, exist_ok=True)\n"
        "        path.write_text(content)\n"
        "    for arguments in (\n"
        '        ["add", "-A"],\n'
        '        ["-c", "user.name=fixture", "-c", "user.email=fixture@invalid",\n'
        '         "commit", "--quiet", "-m", "the record, while the run waits"],\n'
        '        ["push", "--quiet", "origin", "main"],\n'
        "    ):\n"
        f"        subprocess.run([{real!r}, '-C', {str(seed)!r}, *arguments], "
        "stdout=subprocess.DEVNULL, check=True)\n"
        "    landed.touch()\n"
        f"os.execv({real!r}, [{real!r}] + sys.argv[1:])\n"
    )
    stub.chmod(0o755)
    return directory


def rollout(clone, source, ref, within=2, url=None, extra=(), path=None):
    """The command, given a bound of this suite's own well past the one it was
    given: a command whose bound is no bound would otherwise hang the check
    rather than red it."""
    environment = dict(os.environ)
    if path is not None:
        environment["PATH"] = f"{path}{os.pathsep}{environment['PATH']}"
    try:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "rollout-from-results"),
                "--within-secs", str(within),
                "--every-secs", "1",
                "--fabric-root", str(clone),
                "--source-url", url or str(source),
                "--source-ref", ref,
                "--source-tree", str(source),
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=within * 5 + 30,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemExit(
            f"rollout from results: the command did not come back in {error.timeout:.0f} "
            f"seconds against a bound of {within}, so its bound is no bound"
        )


def expect(case, completed, code, printed=(), phrases=()):
    if completed.returncode != code:
        report(
            case,
            f"expected exit {code}, got {completed.returncode}\n"
            f"{completed.stdout}\n{completed.stderr}",
        )
        return False
    announced = [line for line in completed.stdout.splitlines() if line]
    if announced != list(printed):
        report(case, f"printed {announced}, not {list(printed)}")
        return False
    for phrase in phrases:
        if phrase not in completed.stderr:
            report(case, f"the account does not say {phrase!r}\n{completed.stderr}")
            return False
    return True


def main():
    source, commits = source_history()
    base = commits["base"]

    # The whole run: the branch resolved, its request found answered, the
    # release rendered at that commit, and one object on stdout naming it. The
    # renderer's own account is a page of stdout when run by hand, and it is
    # not on stdout here.
    case = "releases-the-commit-the-branch-answered"
    target = commits["documentation"]
    clone = branch(case, requested(target) | answered(target))
    apps = deployed(clone, base)
    if expect(
        case,
        rollout(clone, source, "refs/heads/documentation"),
        RELEASED,
        [json.dumps({"released": target, "records": [f"results/chuggy/{target}/request-{DIGEST}.json"]})],
        [f"refs/heads/documentation at {source} is {target}"],
    ) and annotations(apps) != {target[:8]}:
        report(case, f"the release does not annotate the resolved commit: {annotations(apps)}")

    # The record lands on the branch while the run waits, and the checkout the
    # run was given is the branch before it: the wait reads the branch, the
    # render reads the checkout, and between them the checkout is advanced to
    # what the wait proved. A run that rendered from the checkout as given
    # would refuse every rollout whose record was not on main at dispatch.
    case = "renders-from-the-branch-the-wait-proved"
    target = commits["documentation"]
    record = f"results/chuggy/{target}/request-{DIGEST}.json"
    clone = branch(case, requested(target))
    apps = deployed(clone, base)
    if expect(
        case,
        rollout(
            clone,
            source,
            "refs/heads/documentation",
            within=4,
            path=landing_git(case, answered(target)),
        ),
        RELEASED,
        [json.dumps({"released": target, "records": [record]})],
        [f"{clone} is at origin/main"],
    ) and annotations(apps) != {target[:8]}:
        report(case, f"the release does not annotate the resolved commit: {annotations(apps)}")
    if not (clone / record).is_file():
        report(case, "the checkout the render read does not carry the record the wait found")
    if git(clone, "rev-parse", "HEAD") != git(clone, "rev-parse", "origin/main"):
        report(case, "the checkout was not advanced to origin/main")

    # A checkout with a commit of its own is not the one a ticket has, and the
    # branch has moved past it: no fast-forward reaches the record, and a run
    # that reset the tree to get there would throw away what it was given.
    case = "cannot-run-when-the-checkout-does-not-fast-forward"
    target = commits["documentation"]
    clone = branch(case, requested(target))
    apps = deployed(clone, base)
    write(clone, "docs/its-own", "a commit the branch does not have\n")
    git(clone, "add", "docs/its-own")
    git(clone, "commit", "--quiet", "-m", "its own")
    land(case, answered(target), "the record, after the checkout diverged")
    before = fingerprint(apps)
    head = git(clone, "rev-parse", "HEAD")
    if expect(
        case,
        rollout(clone, source, "refs/heads/documentation"),
        UNRUNNABLE,
        [],
        [f"the checkout at {clone} does not fast-forward to origin/main"],
    ):
        if fingerprint(apps) != before:
            report(case, "cluster/apps was edited from a checkout that was not advanced")
        if git(clone, "rev-parse", "HEAD") != head:
            report(case, "the checkout was moved off its own commit")

    # The renderer's clean no-op is this command's refusal: a work stage that
    # writes nothing lands an empty change, which the finalizer refuses and
    # which is a pull request with no commits.
    case = "refuses-a-release-that-changes-nothing"
    clone = branch(case, requested(base) | answered(base))
    apps = deployed(clone, base)
    before = fingerprint(apps)
    if expect(
        case,
        rollout(clone, source, "refs/heads/base"),
        REFUSAL,
        [],
        [f"already releases {base}", "nothing to land"],
    ) and fingerprint(apps) != before:
        report(case, "the refused run still edited cluster/apps")

    # The wait's deadline is a refusal and not a render: nothing is written for
    # a build this site has not answered, and the ticket's attempts are its
    # budget for asking again.
    case = "gives-up-when-the-wait-does"
    target = commits["documentation"]
    clone = branch(case, requested(target))
    apps = deployed(clone, base)
    before = fingerprint(apps)
    if expect(
        case,
        rollout(clone, source, "refs/heads/documentation"),
        REFUSAL,
        [],
        [f"has no record for {DIGEST}", "has not answered the request"],
    ) and fingerprint(apps) != before:
        report(case, "cluster/apps was edited for a build with no record")

    # The wait's deadline is its verdict even when its rounds are slow: a
    # resolve and a fetch that each take most of a second inside the bound
    # still end in the wait's refusal, not in this command pre-empting it --
    # and 2 says the fabric is broken where 3 says the build is late.
    case = "reaches-the-deadline-across-a-slow-fetch"
    target = commits["documentation"]
    clone = branch(case, requested(target))
    deployed(clone, base)
    expect(
        case,
        rollout(
            clone, source, "refs/heads/documentation", within=8, path=slow_git(case, 0.7, 0.8)
        ),
        REFUSAL,
        [],
        ["has not answered the request"],
    )

    # No request at the resolved commit is the chain broken, not a build that
    # is late: the wait's could-not-run is this command's, so that a ticket
    # does not spend its attempts waiting for something nobody asked for.
    case = "cannot-run-when-nothing-was-asked"
    clone = branch(case, {})
    deployed(clone, base)
    expect(
        case,
        rollout(clone, source, "refs/heads/documentation"),
        UNRUNNABLE,
        [],
        ["carries no request document", "await-build-results could not run"],
    )

    # The renderer's refusal is passed on as one, with its account: an image
    # whose inputs moved and no verified result at the commit.
    case = "refuses-when-the-release-does"
    target = commits["api"]
    clone = branch(case, requested(target) | answered(target))
    deployed(clone, base)
    expect(
        case,
        rollout(clone, source, "refs/heads/api"),
        REFUSAL,
        [],
        ["no verified result", f"the release of {target} is refused"],
    )

    # A ref the source does not have is a run that cannot start, and it says
    # so before anything waits.
    case = "cannot-run-without-a-commit-to-release"
    clone = branch(case, {})
    deployed(clone, base)
    expect(
        case,
        rollout(clone, source, "refs/heads/nowhere"),
        UNRUNNABLE,
        [],
        ["refs/heads/nowhere could not be resolved"],
    )

    # The bound is the command's whole life, the resolve included: a source
    # that never answers is not a wait of no length.
    case = "comes-back-from-a-source-that-never-answers"
    clone = branch(case, {})
    deployed(clone, base)
    listener, url = stalled(case)
    try:
        started = time.monotonic()
        completed = rollout(clone, source, "refs/heads/documentation", within=3, url=url)
        waited = time.monotonic() - started
    finally:
        listener.close()
    if expect(case, completed, UNRUNNABLE, [], ["did not return within the wait"]) and waited > 15:
        report(case, f"a 3 second bound took {waited:.0f} seconds to come back")

    # The cap is the wait's, held here before anything is resolved: the source
    # named below does not exist, and the refusal is about the bound and not
    # about it.
    case = "refuses-a-bound-past-the-cap-before-looking"
    clone = branch(case, {})
    deployed(clone, base)
    expect(
        case,
        rollout(clone, source, "refs/heads/base", within=CAP_SECS + 1, url=str(WORK / "nowhere")),
        UNRUNNABLE,
        [],
        ["--within-secs"],
    )

    # A checkout with no release in it has nothing to render, and the wait
    # would only hold a worker for a verdict the render could never reach: the
    # branch here carries no request, so a run that waited first would say so
    # instead.
    case = "cannot-run-without-a-release-to-move"
    clone = branch(case, {})
    expect(
        case,
        rollout(clone, source, "refs/heads/base"),
        UNRUNNABLE,
        [],
        ["cluster/apps is not a directory"],
    )

    raise SystemExit(reported())


main()
