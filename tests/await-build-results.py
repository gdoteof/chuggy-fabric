#!/usr/bin/env python3
"""Drive `scripts/await-build-results` against a real remote.

WHAT THE FIXTURE IS. A bare repository standing in for the branch Flux follows,
a seed checkout standing in for the publisher that pushes to it, and a third
checkout standing in for the worker the command runs in. Every case is a
question about what that worker's command concludes from the branch, so nothing
here reads the command's source: it is run, and what it printed and exited with
is the verdict.

WHY THE THREE CHECKOUTS ARE SEPARATE. The failures this command has are all of
the same shape -- concluding from the wrong tree. A record staged in the
worker's own checkout, or one pushed after that checkout was made, each read as
an answer or a silence in exactly the way that is wrong, and each is a case
below. Neither is visible in a run against a tree the command also wrote.

THE DEADLINE IS A SECOND. `--within-secs 1 --every-secs 1` is the whole of the
waiting here: what is being checked is which verdict a bound produces, not how
long a bound lasts, and a suite that waited for a real one would be a suite
nobody runs.

THE EXIT CODE IS THE VERDICT. Zero is a request this site has answered, 3 is a
deadline that passed without one, and 2 is a run that could not look. The ticket
that runs this reads them as: go on, give up, and the fabric is broken. A
command reporting any as another either rolls out a release for a build that did
not happen or abandons one that did.
"""

import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
SCRIPTS = Path(sys.argv[2]).resolve()
WORK = Path(sys.argv[3]).resolve()

COMMIT = "5e37c51f5e588a11903bdfdc3d22e1e64f9bb96e"
ONE = "c" * 64
TWO = "d" * 64
BUILD = "e" * 64
FETCHED = 0
DEADLINE = 3
UNRUNNABLE = 2

def command():
    """The command under test, imported for the bound it states rather than for
    anything it does: a cap restated here would be a cap this suite proves
    against itself."""
    sys.dont_write_bytecode = True
    path = SCRIPTS / "await-build-results"
    loader = SourceFileLoader("await_build_results", str(path))
    spec = spec_from_file_location("await_build_results", str(path), loader=loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


CAP_SECS = command().CAP_SECS

failures = []


def report(case, message):
    failures.append(f"{case}: {message}")


def reported():
    for failure in failures:
        print(f"await build results: {failure}", file=sys.stderr)
    return 1 if failures else 0


def git(root, *arguments):
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise SystemExit(f"fixture: git {' '.join(arguments)}: {completed.stderr}")
    return completed.stdout


def document():
    """The request document a source ticket files. Only its name is read here --
    the command waits for a record, not for bytes -- so this is the shape and
    not the contract; `tests/build-requests.py` is where the bytes are held."""
    return json.dumps(
        {
            "apiVersion": "chuggy.dev/v1",
            "kind": "ContainerBuildRequest",
            "spec": {"source": {"commit": COMMIT}},
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def record(digest, succeeded=True):
    """What `scripts/fulfil-build-requests` writes when every build one request
    rendered has a result, and the result it names."""
    result = f"results/chuggy/{COMMIT}/{BUILD}/build-{BUILD[:40]}-a1.json"
    return {
        f"results/chuggy/{COMMIT}/request-{digest}.json": json.dumps(
            {
                "version": 1,
                "request": f"requests/chuggy/{COMMIT}/{digest}.json",
                "source": {"repositoryId": "chuggy", "commit": COMMIT},
                "builds": [
                    {
                        "dockerfile": "images/api/Dockerfile",
                        "request": BUILD,
                        "result": result,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        result: json.dumps(
            {
                "result": {
                    "terminalCondition": {
                        "reason": "Succeeded" if succeeded else "Failed",
                        "status": "True" if succeeded else "False",
                    }
                }
            },
            indent=2,
        )
        + "\n",
    }


def requests(*digests):
    return {f"requests/chuggy/{COMMIT}/{digest}.json": document() for digest in digests}


def remote(case):
    """A bare branch, and the publisher's checkout of it."""
    origin = WORK / case / "origin.git"
    seed = WORK / case / "seed"
    origin.parent.mkdir(parents=True, exist_ok=True)
    git(WORK, "init", "--quiet", "--bare", "-b", "main", str(origin))
    git(WORK, "init", "--quiet", "-b", "main", str(seed))
    git(seed, "remote", "add", "origin", f"file://{origin}")
    return origin, seed


def land(seed, files, message):
    for relative, content in files.items():
        path = seed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(seed, "add", "-A")
    git(seed, "-c", "user.name=fixture", "-c", "user.email=fixture@invalid",
        "commit", "--quiet", "-m", message)
    git(seed, "push", "--quiet", "origin", "main")


def worker(case, origin):
    """The checkout the command runs in: a clone of the branch as it stands
    now, so that a case landing a record afterwards is a case about fetching."""
    clone = WORK / case / "clone"
    git(WORK, "clone", "--quiet", f"file://{origin}", str(clone))
    return clone


def await_results(clone, within=1, every=1, extra=()):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "await-build-results"),
            "--repository-id", "chuggy",
            "--source-commit", COMMIT,
            "--within-secs", str(within),
            "--every-secs", str(every),
            "--root", str(clone),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
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
    # The record on the branch is the answer, and the command says which one it
    # found: a ticket that goes on to render a release names the same commit.
    case = "answers-a-request-this-site-has-answered"
    origin, seed = remote(case)
    land(seed, requests(ONE) | record(ONE), "the request and its record")
    expect(
        case,
        await_results(worker(case, origin)),
        FETCHED,
        [f"results/chuggy/{COMMIT}/request-{ONE}.json"],
    )

    # The publisher pushes; nothing local writes a record. A command reading the
    # ref this checkout already had would wait out every deadline on a branch
    # that answered it in the first second.
    case = "fetches-rather-than-reading-the-clone-it-was-given"
    origin, seed = remote(case)
    land(seed, requests(ONE), "the request")
    clone = worker(case, origin)
    land(seed, record(ONE), "the record, after the worker cloned")
    expect(
        case,
        await_results(clone),
        FETCHED,
        [f"results/chuggy/{COMMIT}/request-{ONE}.json"],
    )

    # And the other way: a record in the worker's own tree is not on the branch,
    # so it is not an answer. The release the next ticket renders is cut from
    # what the branch carries, and a wait satisfied by a local file is a rollout
    # of a build whose provenance nobody else can read.
    case = "reads-the-branch-and-not-the-tree-it-runs-in"
    origin, seed = remote(case)
    land(seed, requests(ONE), "the request")
    clone = worker(case, origin)
    for relative, content in record(ONE).items():
        (clone / relative).parent.mkdir(parents=True, exist_ok=True)
        (clone / relative).write_text(content)
    expect(case, await_results(clone), DEADLINE, [], [f"has no record for {ONE}"])

    # The bound is the whole point: a request nothing answers ends the ticket
    # rather than holding a worker forever.
    case = "gives-up-at-the-deadline"
    origin, seed = remote(case)
    land(seed, requests(ONE), "a request nothing answers")
    expect(
        case,
        await_results(worker(case, origin)),
        DEADLINE,
        [],
        [f"has no record for {ONE}"],
    )

    # A commit with no request filed at it is not a wait that could succeed: the
    # request is landed by a ticket before this one runs, so its absence is the
    # chain broken and not a build that is late.
    case = "cannot-look-without-a-request-document"
    origin, seed = remote(case)
    land(seed, {"docs/keep-me": "nothing to do with build requests\n"}, "an empty branch")
    expect(
        case,
        await_results(worker(case, origin)),
        UNRUNNABLE,
        [],
        [f"requests/chuggy/{COMMIT}/"],
    )

    # A remote that cannot be reached is not a deadline either: 3 would tell the
    # ticket the build did not happen, and nothing here knows that.
    case = "cannot-look-without-a-remote"
    origin, seed = remote(case)
    land(seed, requests(ONE) | record(ONE), "the request and its record")
    clone = worker(case, origin)
    git(clone, "remote", "set-url", "origin", f"file://{WORK / case / 'moved.git'}")
    expect(case, await_results(clone), UNRUNNABLE, [], ["could not be fetched"])

    # A failed build is an answer. The release script is what refuses one, and a
    # refusal here would put that verdict in two places -- and would reach the
    # ticket as a deadline, which says the build never ran.
    case = "answers-a-record-naming-a-failed-result"
    origin, seed = remote(case)
    land(seed, requests(ONE) | record(ONE, succeeded=False), "a request answered by a failure")
    expect(
        case,
        await_results(worker(case, origin)),
        FETCHED,
        [f"results/chuggy/{COMMIT}/request-{ONE}.json"],
    )

    # A declaration that moved between two filings puts two documents at one
    # commit, and both are answered or the commit is not built as declared.
    case = "waits-for-every-request-filed-at-one-commit"
    origin, seed = remote(case)
    land(seed, requests(ONE, TWO) | record(ONE), "two requests, one of them answered")
    clone = worker(case, origin)
    expect(case, await_results(clone), DEADLINE, [], [f"has no record for {TWO}"])
    land(seed, record(TWO), "and the other")
    expect(
        case,
        await_results(clone),
        FETCHED,
        [
            f"results/chuggy/{COMMIT}/request-{ONE}.json",
            f"results/chuggy/{COMMIT}/request-{TWO}.json",
        ],
    )

    # The cap is the command's, and a caller cannot ask past it: a wait longer
    # than the fabric's own bounds is a ticket held open, not a build watched.
    case = "refuses-a-wait-past-its-own-cap"
    origin, seed = remote(case)
    land(seed, requests(ONE) | record(ONE), "the request and its record")
    expect(
        case,
        await_results(worker(case, origin), within=CAP_SECS + 1),
        UNRUNNABLE,
        [],
        ["--within-secs"],
    )

    raise SystemExit(reported())


main()
