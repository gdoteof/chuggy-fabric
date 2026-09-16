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

THE DEADLINE IS A SECOND OR THREE. `--within-secs 1 --every-secs 1` is the whole
of the waiting in most cases: what is being checked is which verdict a bound
produces, not how long a bound lasts, and a suite that waited for a real one
would be a suite nobody runs. The two cases about the bound itself are the
exception -- they measure, and what they assert is that the command came back
inside a multiple of the bound it was given.

WHAT STANDS IN FOR A BROKEN NETWORK. A remote that never answers is a socket
this suite binds and never accepts on: `git` completes the connection out of the
listen backlog, sends its request and waits for a reply that cannot come, which
is the shape of a stalled proxy and of a connection whose conntrack entry was
evicted. A remote that answers late, slowly, or not after the first time is a
`git` on PATH that does that to a fetch and then is the real one. Neither needs
a network the sandbox does not have.

THE EXIT CODE IS THE VERDICT. Zero is a request this site has answered, 3 is a
deadline that passed without one, and 2 is a run that could not look. The ticket
that runs this reads them as: go on, give up, and the fabric is broken. A
command reporting any as another either rolls out a release for a build that did
not happen or abandons one that did, and a command reporting none at all is
three attempts that each end at the pod's own deadline hours later.
"""

import json
import os
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


def stalled(case):
    """A remote that accepts a connection and answers nothing, ever. Bound and
    listened on and never accepted: the handshake completes out of the backlog,
    so `git` is connected and waiting rather than refused."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    return listener, f"git://127.0.0.1:{listener.getsockname()[1]}/{case}.git"


def shimmed_git(case, on_fetch):
    """A `git` for the front of PATH that is the real one except before a
    fetch, where it runs `on_fetch` -- Python, with the count of fetches so far
    in `fetches` -- and so blinks, stalls or goes dark on cue. Returns the
    directory and the counter of fetches."""
    directory = WORK / f"{case}-bin"
    directory.mkdir(parents=True)
    counter = directory / "fetches"
    counter.write_text("0")
    stub = directory / "git"
    real = shutil.which("git")
    stub.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys, time\n"
        f"counter = pathlib.Path({str(counter)!r})\n"
        'if "fetch" in sys.argv[1:]:\n'
        "    fetches = int(counter.read_text()) + 1\n"
        "    counter.write_text(str(fetches))\n"
        f"    {on_fetch}\n"
        f"os.execv({real!r}, [{real!r}] + sys.argv[1:])\n"
    )
    stub.chmod(0o755)
    return directory, counter


def blinking_git(case):
    """Fails its first fetch and is the real one from then on, which is a name
    that did not resolve or a gateway or a token that expired, and not a fabric
    that is broken."""
    return shimmed_git(
        case,
        'if fetches == 1: sys.stderr.write("fixture: the remote blinked\\n"); raise SystemExit(128)',
    )


def slow_git(case, fetch_secs):
    """Every fetch takes that long: a remote over a network."""
    return shimmed_git(case, f"time.sleep({fetch_secs})")


def darkening_git(case):
    """The first fetch is the real one and every fetch after it fails: a token
    that expired late in a wait."""
    return shimmed_git(
        case,
        'if fetches > 1: sys.stderr.write("fixture: the remote went dark\\n"); raise SystemExit(128)',
    )


def await_results(clone, within=1, every=1, extra=(), path=None):
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
            env=environment,
            timeout=within * 5 + 30,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemExit(
            f"await build results: the command did not come back in {error.timeout:.0f} "
            f"seconds against a bound of {within}, so its bound is no bound"
        )


def announced(records):
    """The whole of what a command a ticket engine runs may put on stdout: one
    JSON object, which is the result the engine reads. A second line, or a line
    that is not that object, is a task that failed whatever the command meant."""
    return [json.dumps({"records": records})]


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
        announced([f"results/chuggy/{COMMIT}/request-{ONE}.json"]),
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
        announced([f"results/chuggy/{COMMIT}/request-{ONE}.json"]),
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

    # And the bound holds over a remote that never answers, which is the only
    # way it is a bound at all: a round consulted between children is no bound
    # on a child that does not return, and a command that returns nothing
    # reaches the ticket as the pod's own deadline, hours later and with no
    # verdict about the build.
    case = "comes-back-from-a-remote-that-never-answers"
    origin, seed = remote(case)
    land(seed, requests(ONE), "the request")
    clone = worker(case, origin)
    listener, url = stalled(case)
    try:
        git(clone, "remote", "set-url", "origin", url)
        started = time.monotonic()
        completed = await_results(clone, within=3, every=1)
        waited = time.monotonic() - started
    finally:
        listener.close()
    if expect(case, completed, UNRUNNABLE, [], ["did not return within the wait"]):
        if waited > 15:
            report(case, f"a 3 second wait took {waited:.0f} seconds to come back")

    # One fetch that fails is a blip -- a name that did not resolve, a gateway,
    # an installation token that expired late in a long wait -- and the build it
    # is waiting on is still running. A ticket that read it as a broken fabric
    # would abandon a change that is already merged.
    case = "waits-out-a-remote-that-answers-late"
    origin, seed = remote(case)
    land(seed, requests(ONE) | record(ONE), "the request and its record")
    clone = worker(case, origin)
    blinking, counter = blinking_git(case)
    if expect(
        case,
        await_results(clone, within=12, every=1, path=blinking),
        FETCHED,
        announced([f"results/chuggy/{COMMIT}/request-{ONE}.json"]),
    ) and counter.read_text() != "2":
        report(case, f"the failed fetch was not retried: {counter.read_text()} fetches")

    # A round started at the deadline gives its fetch the second a child is
    # always given and no more, and against a remote over a network a fetch is
    # longer than that: the round is cut off by the deadline and the wait says
    # the network did not answer, which sends the operator to the network and
    # not to the build that is late. So no round is started that what is left
    # cannot hold, and the deadline is declared on what the last one saw.
    case = "gives-up-at-the-deadline-across-a-fetch-slower-than-a-second"
    origin, seed = remote(case)
    land(seed, requests(ONE), "a request nothing answers")
    clone = worker(case, origin)
    slow, counter = slow_git(case, 1.5)
    started = time.monotonic()
    completed = await_results(clone, within=13, every=1, path=slow)
    waited = time.monotonic() - started
    if expect(case, completed, DEADLINE, [], [f"has no record for {ONE}"]):
        if int(counter.read_text()) < 2:
            report(case, f"the wait stopped looking after {counter.read_text()} fetch")
        if waited < 13:
            report(case, f"the deadline was declared {13 - waited:.1f} seconds before it passed")
        if "could not look" in completed.stderr:
            report(case, f"the last round was cut off by the deadline\n{completed.stderr}")

    # A round that saw the request unanswered and a blink after it is a build
    # that is late, not a fabric that is broken: 2 is for a wait no round of
    # which could look. The blink is still in the account.
    case = "reads-a-blink-after-a-round-that-saw-as-the-deadline"
    origin, seed = remote(case)
    land(seed, requests(ONE), "a request nothing answers")
    clone = worker(case, origin)
    darkening, counter = darkening_git(case)
    if expect(
        case,
        await_results(clone, within=11, every=1, path=darkening),
        DEADLINE,
        [],
        [f"has no record for {ONE}", "could not look", "the remote went dark"],
    ) and int(counter.read_text()) < 2:
        report(case, f"the wait stopped looking after {counter.read_text()} fetch")

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
        announced([f"results/chuggy/{COMMIT}/request-{ONE}.json"]),
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
        announced(
            [
                f"results/chuggy/{COMMIT}/request-{ONE}.json",
                f"results/chuggy/{COMMIT}/request-{TWO}.json",
            ]
        ),
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
