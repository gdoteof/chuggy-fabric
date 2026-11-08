#!/usr/bin/env python3
"""Run the three scripts of the worker admission against stand-ins for what
they speak to, and hold what each does.

usage: worker-admit.py BUILD_SYSTEM_DIRECTORY SCHEDULER_FILE WORK

BUILD_SYSTEM_DIRECTORY holds worker-admit-{read,prepare,publish}.sh and
admit-worker.sh. WORK is an empty directory. `sh`, `git`, `jq`, `curl`'s
callers' tools and python3 come from the PATH this is run with; `kubectl` and
`curl` are stand-ins written into WORK, so no cluster and no network is touched.

THE CASES, by the script each is the only reader of:

- read: the newest inputs' two succeeded runs are the pair, with their digests
  and the worker run's commit; an older pair is not chosen when the newest
  inputs have a run unfinished, failed or missing; a run of another task, one
  with no annotation and one of another image are not counted; a digest or a
  commit that is not a full hash is refused; no runs is nothing, and succeeds;
- prepare: over a repository holding this tree's scheduler file, the change is
  made, the placement check is run and the hand-off is the file, the message,
  the branch named for the worker digest and the blob and commit it was made
  against, with `ready` last; a digest the file already holds, and no pair, hand
  off nothing; a placement check that fails fails the step and hands off nothing;
- publish: against a stand-in GitHub, a hand-off becomes a branch, one file
  written with the blob it was made from, and one pull request merged at its
  head; an open pull request is merged and not opened again; a branch with no
  open pull request is left alone; a `main` that moved is not merged over and
  nothing is made; a conflict closes the pull request and deletes the branch and
  fails; no hand-off and no token are as they say; and the token is in no
  argument of any request and in no output.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

BUILD = Path(sys.argv[1]).resolve()
SCHEDULER = Path(sys.argv[2]).resolve()
WORK = Path(sys.argv[3]).resolve()
FAILURES = []
ANNOTATION = "fabric.chuggy.dev/worker-inputs"
TASK = "build-two-platform-image"
WORKER_IMAGE = "registry.example/chuggy/worker"
RUNTIME_IMAGE = "registry.example/chuggy/worker-runtime"
COMMIT = "1" * 40
WORKER = "sha256:" + "a" * 64
RUNTIME = "sha256:" + "b" * 64
TOKEN = "ghs_secret_value_0123456789"


def report(case, message):
    FAILURES.append(case)
    print(f"worker-admit: {case}: {message}", file=sys.stderr)


def write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run(script, case, environment, extra_path=None):
    env = {
        "PATH": f"{WORK / 'bin'}:{os.environ['PATH']}",
        "HOME": str(WORK / "home"),
        **environment,
    }
    return subprocess.run(["sh", str(BUILD / script)], env=env, capture_output=True, text=True, cwd=WORK)


def expect(case, result, code, *, stdout=(), absent=()):
    if result.returncode != code:
        report(case, f"exited {result.returncode}, not {code}: {result.stderr.strip()[-300:]}")
    for needle in stdout:
        if needle not in result.stdout + result.stderr:
            report(case, f"said nothing of {needle!r}: {result.stdout.strip()[-200:]}")
    for needle in absent:
        if needle in result.stdout + result.stderr:
            report(case, f"said {needle!r}")


def task_run(name, created, inputs, image, outcome, digest=None, commit=COMMIT, task=TASK):
    annotations = {} if inputs is None else {ANNOTATION: inputs}
    status = {"conditions": [{"type": "Succeeded", "status": outcome}]}
    if digest is not None:
        status["results"] = [{"name": "digest", "value": digest}]
    return {
        "metadata": {"name": name, "creationTimestamp": created, "annotations": annotations},
        "spec": {"taskRef": {"name": task}, "params": [{"name": "image", "value": image}, {"name": "commit", "value": commit}]},
        "status": status,
    }


def pair(inputs, stamp, outcome="True", worker=WORKER, runtime=RUNTIME, commit=COMMIT):
    return [
        task_run(f"w-{inputs[7:]}", f"2026-01-01T{stamp}:00Z", inputs, WORKER_IMAGE, outcome, worker, commit),
        task_run(f"r-{inputs[7:]}", f"2026-01-01T{stamp}:01Z", inputs, RUNTIME_IMAGE, outcome, runtime, commit),
    ]


def read(case, items, code=0, *, found=None, stdout=()):
    out = WORK / "out" / case.replace(" ", "-")
    write(WORK / "runs.json", json.dumps({"items": items}))
    result = run(
        "worker-admit-read.sh",
        case,
        {
            "RUNS_NAMESPACE": "chuggy-build", "TASK": TASK, "WORKER_IMAGE": WORKER_IMAGE,
            "RUNTIME_IMAGE": RUNTIME_IMAGE, "ANNOTATION": ANNOTATION, "OUT": str(out),
        },
    )
    expect(f"read: {case}", result, code, stdout=stdout)
    held = (out / "pair.env").read_text() if (out / "pair.env").exists() else None
    if held != found:
        report(f"read: {case}", f"left {held!r}, not {found!r}")


def pair_env(inputs, worker=WORKER, runtime=RUNTIME, commit=COMMIT):
    return f"INPUTS={inputs}\nCOMMIT={commit}\nWORKER_DIGEST={worker}\nRUNTIME_DIGEST={runtime}\n"


def cases_read():
    wanted = pair_env("sha256:in1")
    read("a pair", pair("sha256:in1", "10"), found=wanted, stdout=["succeeded"])
    read("no runs", [], stdout=["nothing to admit"])
    read("a run of another task", [task_run("x", "2026-01-01T10:00:00Z", "sha256:in1", WORKER_IMAGE, "True", WORKER, task="other")], stdout=["nothing to admit"])
    read("runs with no annotation", [task_run("x", "2026-01-01T10:00:00Z", None, WORKER_IMAGE, "True", WORKER)], stdout=["nothing to admit"])
    read("another image", [task_run("x", "2026-01-01T10:00:00Z", "sha256:in1", "registry.example/other", "True", WORKER)], stdout=["nothing to admit"])
    read("one image only", pair("sha256:in1", "10")[:1], stdout=["none of the other"])
    read("a run unfinished", pair("sha256:in1", "10")[:1] + [task_run("r", "2026-01-01T10:01:00Z", "sha256:in1", RUNTIME_IMAGE, "Unknown")], stdout=["nothing to admit"])
    read("a run failed", pair("sha256:in1", "10")[:1] + [task_run("r", "2026-01-01T10:01:00Z", "sha256:in1", RUNTIME_IMAGE, "False")], stdout=["nothing to admit"])
    older = pair("sha256:old", "09", worker="sha256:" + "c" * 64, runtime="sha256:" + "d" * 64)
    read("only the newest inputs", older + pair("sha256:in1", "10"), found=wanted)
    read("an older pair is overtaken", older + pair("sha256:in1", "10", outcome="False"), stdout=["nothing to admit"])
    rebuilt = [task_run("w-again", "2026-01-01T10:30:00Z", "sha256:in1", WORKER_IMAGE, "True", "sha256:" + "e" * 64)]
    read("the newest run of an image", pair("sha256:in1", "10") + rebuilt, found=pair_env("sha256:in1", worker="sha256:" + "e" * 64))
    read("a digest that is not one", pair("sha256:in1", "10", worker="sha256:xyz"), 1, stdout=["not a sha256 digest"])
    read("a short digest", pair("sha256:in1", "10", runtime="sha256:" + "b" * 63), 1, stdout=["not a full sha256 digest"])
    read("no digest", pair("sha256:in1", "10", worker=""), 1, stdout=["not a sha256 digest"])
    read("a commit that is not one", pair("sha256:in1", "10", commit="main"), 1, stdout=["not a commit hash"])
    read("an annotation with a space", pair("a b", "10"), 1, stdout=["holds whitespace"])


def git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def fabric(name, check):
    """A repository of this tree's scheduler file, the admission script and a
    placement check that is `check`."""
    root = WORK / "fabric" / name
    write(root / "cluster/chuggy/chuggy-scheduler.yaml", SCHEDULER.read_text())
    write(root / "cluster/build-system/admit-worker.sh", (BUILD / "admit-worker.sh").read_text())
    write(root / "tests/session-placement.py", f"import sys\nraise SystemExit({check})\n")
    git("init", "--quiet", "--initial-branch=main", cwd=root)
    git("add", "-A", cwd=root)
    git("commit", "--quiet", "-m", "fabric", cwd=root)
    return root


def prepare(case, repo, pair_text, code=0, *, ready=True, stdout=()):
    directory = WORK / "prep" / case.replace(" ", "-")
    write(directory / "in/pair.env", pair_text) if pair_text is not None else (directory / "in").mkdir(parents=True)
    result = run(
        "worker-admit-prepare.sh",
        case,
        {
            "IN": str(directory / "in"), "OUT": str(directory / "out"), "FABRIC_URL": f"file://{repo}",
            "BRANCH": "main", "CHECKOUT": str(directory / "checkout"),
            "SCHEDULER": "cluster/chuggy/chuggy-scheduler.yaml",
        },
    )
    expect(f"prepare: {case}", result, code, stdout=stdout)
    if (directory / "out" / "ready").exists() != ready:
        report(f"prepare: {case}", f"ready is {not ready}")
    return directory / "out"


def cases_prepare():
    repo = fabric("good", 0)
    out = prepare("a pair", repo, pair_env("sha256:in1"), stdout=["is ready on"])
    if out.joinpath("branch").exists():
        expected = {"branch": "admit/worker-" + "a" * 12, "path": "cluster/chuggy/chuggy-scheduler.yaml", "target": "main"}
        for name, value in expected.items():
            if (out / name).read_text() != value:
                report("prepare: a pair", f"{name} is {(out / name).read_text()!r}, not {value!r}")
        content = (out / "content").read_text()
        if WORKER not in content or RUNTIME not in content:
            report("prepare: a pair", "the content holds not both digests")
        if (out / "version").read_text() == "" or not (out / "message").read_text().startswith(f"Admit worker {(out / 'version').read_text()},"):
            report("prepare: a pair", "the message does not open with the version")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        if (out / "base").read_text() != head:
            report("prepare: a pair", "the base is not the commit checked out")
        blob = subprocess.run(["git", "rev-parse", "HEAD:cluster/chuggy/chuggy-scheduler.yaml"], cwd=repo, capture_output=True, text=True).stdout.strip()
        if (out / "blob").read_text() != blob:
            report("prepare: a pair", "the blob is not the file's at the base")
    if (repo / "cluster/chuggy/chuggy-scheduler.yaml").read_text() != SCHEDULER.read_text():
        report("prepare: a pair", "the repository it cloned from was changed")

    prepare("no pair", repo, None, ready=False, stdout=["no pair to admit"])
    prepare("a digest already held", repo, pair_env("sha256:in1", worker=_held_worker()), ready=False, stdout=["nothing to admit"])
    failing = fabric("failing", 1)
    prepare("a placement check that fails", failing, pair_env("sha256:in1"), 1, ready=False)
    prepare("a digest that is not one", repo, pair_env("sha256:in1", worker="sha256:nope"), 1, ready=False, stdout=["not a sha256 digest"])
    prepare("a runtime digest that is not one", repo, pair_env("sha256:in1", runtime="latest"), 1, ready=False, stdout=["not a sha256 digest"])


def _held_worker():
    import re
    return re.findall(r"sha256:[0-9a-f]{64}", SCHEDULER.read_text())[-1]


GITHUB = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["GITHUB_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
method, url, data, output = "GET", None, None, None
i = 0
while i < len(args):
    a = args[i]
    if a == "--request": method = args[i + 1]; i += 1
    elif a == "--data-binary": data = open(args[i + 1][1:]).read(); i += 1
    elif a == "--output": output = args[i + 1]; i += 1
    elif a == "--config": cfg = open(args[i + 1]).read(); i += 1
    elif a in ("--header", "--write-out"): i += 1
    elif not a.startswith("--"): url = a
    i += 1
assert os.environ["TOKEN_VALUE"] in cfg, "the token is not in the configuration"
state["log"].append([method, url.split("/repos/", 1)[1], args])
path = url.split("/repos/", 1)[1].split("?")[0]
repo = "gdoteof/chuggy-fabric"
body = json.loads(data) if data else None
status, out = 404, {"message": "Not Found"}
def done(s, o):
    global status, out
    status, out = s, o
if method == "GET" and path == repo + "/pulls":
    done(200, state["open"])
elif method == "GET" and path == repo + "/git/ref/heads/main":
    done(200, {"object": {"sha": state["main"]}})
elif method == "GET" and path.startswith(repo + "/git/ref/heads/admit/"):
    done(200 if state["branch"] else 404, {"object": {"sha": "f" * 40}})
elif method == "POST" and path == repo + "/git/refs":
    state["branch"] = True; done(201, {})
elif method == "PUT" and path.startswith(repo + "/contents/"):
    state["written"] = body; done(state.get("write_status", 200), {"commit": {"sha": "9" * 40}, "message": "write refused"})
elif method == "POST" and path == repo + "/pulls":
    state["opened"] = body; done(201, {"number": 7})
elif method == "GET" and path == repo + "/pulls/7":
    done(200, {"mergeable_state": state.get("mergeable_state", "clean")})
elif method == "PATCH" and path == repo + "/pulls/7":
    state["closed"] = True; done(200, {})
elif method == "PUT" and path == repo + "/pulls/7/merge":
    state["merged"] = body; done(state.get("merge_status", 200), {"message": "Merge conflict"})
elif method == "DELETE" and path.startswith(repo + "/git/refs/heads/"):
    state["branch"] = False; state["deleted"] = True; done(204, {})
json.dump(state, open(state_path, "w"))
if output: open(output, "w").write(json.dumps(out))
sys.stdout.write(str(status))
'''


def handoff(name):
    out = WORK / "handoff" / name
    out.mkdir(parents=True)
    files = {
        "branch": "admit/worker-" + "a" * 12, "path": "cluster/chuggy/chuggy-scheduler.yaml", "blob": "2" * 40,
        "base": "3" * 40, "version": "0.99", "target": "main",
        "message": "Admit worker 0.99, and run sessions and chat on it\n\nbody\n", "content": "new content\n",
    }
    for key, value in files.items():
        write(out / key, value)
    write(out / "ready", "")
    return out


def publish(case, state, code=0, *, ready=True, token=True, stdout=(), directory=None):
    out = directory or handoff(case.replace(" ", "-"))
    if not ready:
        (out / "ready").unlink()
    write(WORK / "state.json", json.dumps({"log": [], "open": [], "main": "3" * 40, "branch": False, **state}))
    write(WORK / "token", TOKEN + "\n")
    result = run(
        "worker-admit-publish.sh",
        case,
        {
            "IN": str(out), "REPOSITORY": "gdoteof/chuggy-fabric", "API": "https://api.example",
            "TOKEN": str(WORK / "token") if token else str(WORK / "absent"),
            "GITHUB_STATE": str(WORK / "state.json"), "TOKEN_VALUE": TOKEN,
        },
    )
    expect(f"publish: {case}", result, code, stdout=stdout, absent=[TOKEN])
    final = json.loads((WORK / "state.json").read_text())
    for method, path, args in final["log"]:
        if any(TOKEN in argument for argument in args):
            report(f"publish: {case}", f"the token is an argument of {method} {path}")
    return final


def methods(final):
    return [f"{method} {path.split('?')[0].replace('gdoteof/chuggy-fabric', '')}" for method, path, _ in final["log"]]


def cases_publish():
    final = publish("a hand-off", {}, stdout=["admitted"])
    wanted = [
        "GET /pulls", "GET /git/ref/heads/admit/worker-" + "a" * 12, "GET /git/ref/heads/main", "POST /git/refs",
        "PUT /contents/cluster/chuggy/chuggy-scheduler.yaml", "POST /pulls", "GET /git/ref/heads/main", "PUT /pulls/7/merge",
    ]
    if methods(final) != wanted:
        report("publish: a hand-off", f"made {methods(final)}")
    if final.get("written", {}).get("sha") != "2" * 40 or final["written"]["branch"] != "admit/worker-" + "a" * 12:
        report("publish: a hand-off", "the file was not written from its blob on the branch")
    if final.get("merged", {}).get("sha") != "9" * 40:
        report("publish: a hand-off", "the merge is not at the head the file was written to")
    if final.get("opened", {}).get("base") != "main":
        report("publish: a hand-off", "the pull request is not against main")

    final = publish("an open pull request", {"open": [{"number": 7, "head": {"sha": "8" * 40}}]}, stdout=["resuming"])
    if any(m.startswith(("POST", "PUT /contents")) for m in methods(final)) or final.get("merged", {}).get("sha") != "8" * 40:
        report("publish: an open pull request", f"made {methods(final)}")

    final = publish("a branch with no pull request", {"branch": True}, stdout=["left alone"])
    if methods(final)[-1] != "GET /git/ref/heads/admit/worker-" + "a" * 12 or len(methods(final)) != 2:
        report("publish: a branch with no pull request", f"made {methods(final)}")

    final = publish("a main that moved", {"main": "4" * 40}, stdout=["moved off"])
    if any(m.startswith(("POST", "PUT")) for m in methods(final)):
        report("publish: a main that moved", f"made {methods(final)}")

    final = publish("a main that moved after the pull request", {"open": [{"number": 7, "head": {"sha": "8" * 40}}], "main": "4" * 40}, 1, stdout=["closing pull request 7"])
    if not final.get("closed") or not final.get("deleted") or "merged" in final:
        report("publish: a main that moved after the pull request", "the pull request was not abandoned")

    final = publish("a conflict", {"merge_status": 405, "mergeable_state": "dirty"}, 1, stdout=["conflicts"])
    if not final.get("closed") or not final.get("deleted"):
        report("publish: a conflict", "the pull request was not closed and the branch deleted")

    final = publish("a merge that is refused", {"merge_status": 405}, 1, stdout=["not mergeable"])
    if final.get("closed") or final.get("deleted"):
        report("publish: a merge that is refused", "a pull request not in conflict was abandoned")

    final = publish("a file that cannot be written", {"write_status": 409}, 1, stdout=["answered 409"])
    if not final.get("deleted") or "opened" in final:
        report("publish: a file that cannot be written", "the branch was left or a pull request opened")

    final = publish("no hand-off", {}, ready=False, stdout=["nothing to admit"])
    if final["log"]:
        report("publish: no hand-off", "a request was made")
    final = publish("no token", {}, 1, token=False, stdout=["not delivered"])
    if final["log"]:
        report("publish: no token", "a request was made")

    for name, value in {"branch": "main", "path": "../x", "blob": "zz", "target": "a b"}.items():
        out = handoff(f"bad-{name}")
        write(out / name, value)
        final = publish(f"a hand-off with a bad {name}", {}, 1, directory=out)
        if final["log"]:
            report(f"publish: a hand-off with a bad {name}", "a request was made")
    out = handoff("linked")
    (out / "content").unlink()
    (out / "content").symlink_to("/etc/hostname")
    publish("a linked file", {}, 1, directory=out, stdout=["not a regular file"])


def main():
    write(WORK / "bin/kubectl", '#!/bin/sh\ncase "$*" in\n  *"get taskruns"*) cat "$(dirname "$0")/../runs.json" ;;\n  kustomize*) echo "kind: ConfigMap" ;;\n  *) exit 3 ;;\nesac\n', True)
    write(WORK / "bin/curl", GITHUB.replace("#!/usr/bin/env python3", f"#!{sys.executable}"), True)
    (WORK / "home").mkdir(parents=True, exist_ok=True)
    cases_read()
    cases_prepare()
    cases_publish()
    if FAILURES:
        raise SystemExit(f"worker-admit: {len(FAILURES)} failing: {sorted(set(FAILURES))}")


main()
