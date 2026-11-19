#!/usr/bin/env python3
"""Run the three scripts of the worker admission against stand-ins for what
they speak to, and hold what each does.

usage: worker-admit.py BUILD_SYSTEM_DIRECTORY SCHEDULER_FILE PLANE_FILE WORK

BUILD_SYSTEM_DIRECTORY holds worker-admit-{read,prepare}.sh, admit-publish.sh
and admit-worker.sh. WORK is an empty directory. `sh`, `git`, `jq`, `curl`'s
callers' tools and python3 come from the PATH this is run with; `kubectl` and
`curl` are stand-ins written into WORK, so no cluster and no network is touched.

THE CASES, by the script each is the only reader of:

- read: the newest inputs' two succeeded runs are the pair, with their digests
  and the worker run's commit; an older pair is not chosen when the newest
  inputs have a run unfinished, failed or missing; a run of another task, one
  with no annotation and one of another image are not counted; a digest or a
  commit that is not a full hash is refused; no runs is nothing, and succeeds;
  the chat image's digest is read with the pair's, a pair whose chat run is
  missing, unfinished or failed is nothing, and a chat run of newer inputs
  beside a pair does not move which inputs are the newest;
- prepare: over a repository holding this tree's scheduler file, the change is
  made, the placement check is run and the hand-off is the file, the message,
  the branch named for the worker digest and the blob and commit it was made
  against, with `ready` last; a digest the file already holds, and no pair, hand
  off nothing; a placement check that fails fails the step and hands off nothing;
  the pool plane's file is handed off as the second file, with its own blob,
  where the chat image moved, and not where the file already names it;
- publish: against a stand-in GitHub, a hand-off becomes a branch, one file
  written with the blob it was made from, and one pull request merged at its
  head, titled with the message's first line; a branch of another
  admission's prefix, and a prefix that is not one, are refused; the site's
  admission's hand-off, of its own prefix and one file, is published the same
  way; an open pull request is merged and not opened again; a branch with no
  open pull request is left alone; a `main` that moved is not merged over and
  nothing is made; a conflict closes the pull request and deletes the branch and
  fails; no hand-off and no token are as they say; and the token is in no
  argument of any request and in no output; a hand-off carrying the pool
  plane's file writes it second, from its own blob, and merges at that write's
  head, each file with its own content; that write refused deletes the branch
  and opens nothing; a chat hand-off that is partial, linked, or names a path
  that is not plain, makes no request.
"""

import base64
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

BUILD = Path(sys.argv[1]).resolve()
SCHEDULER = Path(sys.argv[2]).resolve()
PLANE = Path(sys.argv[3]).resolve()
WORK = Path(sys.argv[4]).resolve()
PLANE_PATH = "cluster/chuggy/chuggy-pool-plane.yaml"
FAILURES = []
ANNOTATION = "fabric.chuggy.dev/worker-inputs"
TASK = "build-two-platform-image"
WORKER_IMAGE = "registry.example/chuggy/worker"
RUNTIME_IMAGE = "registry.example/chuggy/worker-runtime"
CHAT_IMAGE = "registry.example/chuggy/chat"
COMMIT = "1" * 40
WORKER = "sha256:" + "a" * 64
RUNTIME = "sha256:" + "b" * 64
CHAT = "sha256:" + "5" * 64
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


def pair(inputs, stamp, outcome="True", worker=WORKER, runtime=RUNTIME, commit=COMMIT, chat=CHAT, chat_outcome="True"):
    """The worker's run, the runtime's and then the chat image's, which `chat`
    as nothing leaves out."""
    runs = [
        task_run(f"w-{inputs[7:]}", f"2026-01-01T{stamp}:00Z", inputs, WORKER_IMAGE, outcome, worker, commit),
        task_run(f"r-{inputs[7:]}", f"2026-01-01T{stamp}:01Z", inputs, RUNTIME_IMAGE, outcome, runtime, commit),
    ]
    if chat is not None:
        runs.append(task_run(f"c-{inputs[7:]}", f"2026-01-01T{stamp}:02Z", inputs, CHAT_IMAGE, chat_outcome, chat, commit))
    return runs


def read(case, items, code=0, *, found=None, stdout=()):
    out = WORK / "out" / case.replace(" ", "-")
    write(WORK / "runs.json", json.dumps({"items": items}))
    result = run(
        "worker-admit-read.sh",
        case,
        {
            "RUNS_NAMESPACE": "chuggy-build", "TASK": TASK, "WORKER_IMAGE": WORKER_IMAGE,
            "RUNTIME_IMAGE": RUNTIME_IMAGE, "CHAT_IMAGE": CHAT_IMAGE, "ANNOTATION": ANNOTATION, "OUT": str(out),
        },
    )
    expect(f"read: {case}", result, code, stdout=stdout)
    held = (out / "pair.env").read_text() if (out / "pair.env").exists() else None
    if held != found:
        report(f"read: {case}", f"left {held!r}, not {found!r}")


def pair_env(inputs, worker=WORKER, runtime=RUNTIME, commit=COMMIT, chat=CHAT):
    return f"INPUTS={inputs}\nCOMMIT={commit}\nWORKER_DIGEST={worker}\nRUNTIME_DIGEST={runtime}\nCHAT_DIGEST={chat}\n"


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
    read("no chat run", pair("sha256:in1", "10", chat=None), stdout=["no run of the chat image"])
    read("a chat run unfinished", pair("sha256:in1", "10", chat=None, chat_outcome="Unknown") + [task_run("c", "2026-01-01T10:02:00Z", "sha256:in1", CHAT_IMAGE, "Unknown")], stdout=["nothing to admit"])
    read("a chat run failed", pair("sha256:in1", "10", chat_outcome="False"), stdout=["nothing to admit"])
    read("a chat digest that is not one", pair("sha256:in1", "10", chat="sha256:xyz"), 1, stdout=["not a sha256 digest"])
    ahead = [task_run("c-ahead", "2026-01-01T11:00:00Z", "sha256:in2", CHAT_IMAGE, "True", "sha256:" + "6" * 64)]
    read("a chat run of newer inputs", pair("sha256:in1", "10") + ahead, found=wanted)
    read("only chat runs", ahead, stdout=["nothing to admit"])


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
    write(root / PLANE_PATH, PLANE.read_text())
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
            "SCHEDULER": "cluster/chuggy/chuggy-scheduler.yaml", "PLANE": PLANE_PATH,
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
        if not re.match(r"Admit worker [0-9.]+,", (out / "message").read_text()) or (out / "version").exists():
            report("prepare: a pair", "the message does not open with the version, or a version file is handed off")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        if (out / "base").read_text() != head:
            report("prepare: a pair", "the base is not the commit checked out")
        blob = subprocess.run(["git", "rev-parse", "HEAD:cluster/chuggy/chuggy-scheduler.yaml"], cwd=repo, capture_output=True, text=True).stdout.strip()
        if (out / "blob").read_text() != blob:
            report("prepare: a pair", "the blob is not the file's at the base")
        chat_blob = subprocess.run(["git", "rev-parse", f"HEAD:{PLANE_PATH}"], cwd=repo, capture_output=True, text=True).stdout.strip()
        held = {name: (out / name).read_text() if (out / name).exists() else None for name in ("second-path", "second-blob")}
        if held != {"second-path": PLANE_PATH, "second-blob": chat_blob}:
            report("prepare: a pair", f"the chat hand-off is {held}")
        if not (out / "second-content").exists() or (out / "second-content").read_text() != PLANE.read_text().replace(_held_chat(), CHAT):
            report("prepare: a pair", "the chat content is not the plane file with its chat image moved")
        if CHAT not in (out / "message").read_text():
            report("prepare: a pair", "the message does not name the chat digest")
    if (repo / PLANE_PATH).read_text() != PLANE.read_text():
        report("prepare: a pair", "the plane file of the repository it cloned from was changed")
    out = prepare("a chat image already named", repo, pair_env("sha256:in1", chat=_held_chat()), stdout=["is ready on"])
    if any((out / name).exists() for name in ("second-path", "second-blob", "second-content")):
        report("prepare: a chat image already named", "the plane file was handed off unchanged")
    if not out.joinpath("content").exists() or WORKER not in (out / "content").read_text():
        report("prepare: a chat image already named", "the worker was not handed off")
    prepare("a chat digest that is not one", repo, pair_env("sha256:in1", chat="latest"), 1, ready=False, stdout=["not a sha256 digest"])
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


def _held_chat():
    import re
    (held,) = re.findall(r"chuggy/chat@(sha256:[0-9a-f]{64})", PLANE.read_text())
    return held


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
    first = "written" not in state
    state["written" if first else "written_chat"] = {**body, "path": path.split("/contents/", 1)[1]}
    done(state.get("write_status" if first else "chat_write_status", 200), {"commit": {"sha": ("9" if first else "7") * 40}, "message": "write refused"})
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


def handoff(name, chat=False):
    out = WORK / "handoff" / name
    out.mkdir(parents=True)
    files = {
        "branch": "admit/worker-" + "a" * 12, "path": "cluster/chuggy/chuggy-scheduler.yaml", "blob": "2" * 40,
        "base": "3" * 40, "target": "main",
        "message": "Admit worker 0.99, and run sessions and chat on it\n\nbody\n", "content": "new content\n",
    }
    if chat:
        files.update({"second-path": PLANE_PATH, "second-blob": "6" * 40, "second-content": "new plane\n"})
    for key, value in files.items():
        write(out / key, value)
    write(out / "ready", "")
    return out


def publish(case, state, code=0, *, ready=True, token=True, stdout=(), directory=None, prefix="admit/worker-"):
    out = directory or handoff(case.replace(" ", "-"))
    if not ready:
        (out / "ready").unlink()
    write(WORK / "state.json", json.dumps({"log": [], "open": [], "main": "3" * 40, "branch": False, **state}))
    write(WORK / "token", TOKEN + "\n")
    result = run(
        "admit-publish.sh",
        case,
        {
            "IN": str(out), "REPOSITORY": "gdoteof/chuggy-fabric", "API": "https://api.example", "BRANCH_PREFIX": prefix,
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
    final = publish("a hand-off", {}, stdout=["merged pull request 7: Admit worker 0.99"])
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
    if final.get("opened", {}).get("title") != "Admit worker 0.99, and run sessions and chat on it":
        report("publish: a hand-off", f"the pull request is titled {final.get('opened', {}).get('title')!r}")

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
    final = publish("a hand-off with the chat image", {}, stdout=["merged pull request 7"], directory=handoff("chat", chat=True))
    if methods(final) != [*wanted[:5], f"PUT /contents/{PLANE_PATH}", *wanted[5:]]:
        report("publish: a hand-off with the chat image", f"made {methods(final)}")
    second = final.get("written_chat", {})
    if (second.get("sha"), second.get("branch"), second.get("path")) != ("6" * 40, "admit/worker-" + "a" * 12, PLANE_PATH):
        report("publish: a hand-off with the chat image", "the plane file was not written from its blob on the branch")
    contents = [base64.b64decode(final.get(key, {}).get("content", "")).decode() for key in ("written", "written_chat")]
    if contents != ["new content\n", "new plane\n"]:
        report("publish: a hand-off with the chat image", f"the files were written as {contents}")
    if final["written"]["path"] != "cluster/chuggy/chuggy-scheduler.yaml" or final.get("merged", {}).get("sha") != "7" * 40:
        report("publish: a hand-off with the chat image", "the merge is not at the head the plane file was written to")
    final = publish("a chat file that cannot be written", {"chat_write_status": 409}, 1, stdout=["answered 409"], directory=handoff("chat-refused", chat=True))
    if not final.get("deleted") or "opened" in final:
        report("publish: a chat file that cannot be written", "the branch was left or a pull request opened")
    out = handoff("another-prefix")
    write(out / "branch", "admit/chug-gy-" + "a" * 12)
    final = publish("a branch of another admission", {}, 1, directory=out, stdout=["not one this makes"])
    if final["log"]:
        report("publish: a branch of another admission", "a request was made")
    final = publish("a branch prefix that is not one", {}, 1, prefix="worker-", stdout=["is not admit/<name>-"])
    if final["log"]:
        report("publish: a branch prefix that is not one", "a request was made")

    # The site's admission ends in this script too, with a hand-off of one
    # file and branches of its own.
    out = handoff("site")
    site = {
        "branch": "admit/chug-gy-" + "a" * 12, "path": "cluster/chug-gy/chug-gy.yaml",
        "message": "chug-gy: the site's image, built at kasofsk/chug.gy 1111111\n\nThe digest TaskRun r reported, for web.\n",
    }
    for key, value in site.items():
        write(out / key, value)
    final = publish("a hand-off of the site's", {}, directory=out, prefix="admit/chug-gy-", stdout=["merged pull request 7: chug-gy: the site's image"])
    site_wanted = [m.replace("admit/worker-", "admit/chug-gy-").replace("chuggy/chuggy-scheduler.yaml", "chug-gy/chug-gy.yaml") for m in wanted]
    if methods(final) != site_wanted:
        report("publish: a hand-off of the site's", f"made {methods(final)}")
    if final.get("opened", {}).get("title") != "chug-gy: the site's image, built at kasofsk/chug.gy 1111111":
        report("publish: a hand-off of the site's", f"the pull request is titled {final.get('opened', {}).get('title')!r}")
    if final.get("written", {}).get("message") != site["message"]:
        report("publish: a hand-off of the site's", "the commit is not the message handed off")
    final = publish("a worker branch for the site", {}, 1, prefix="admit/chug-gy-", stdout=["not one this makes"])
    if final["log"]:
        report("publish: a worker branch for the site", "a request was made")

    out = handoff("chat-partial", chat=True)
    (out / "second-blob").unlink()
    final = publish("a partial chat hand-off", {}, 1, directory=out, stdout=["not a regular file"])
    if final["log"]:
        report("publish: a partial chat hand-off", "a request was made")
    for name, value in {"second-path": "../x", "second-blob": "zz"}.items():
        out = handoff(f"bad-{name}", chat=True)
        write(out / name, value)
        final = publish(f"a hand-off with a bad {name}", {}, 1, directory=out)
        if final["log"]:
            report(f"publish: a hand-off with a bad {name}", "a request was made")
    out = handoff("chat-linked", chat=True)
    (out / "second-content").unlink()
    (out / "second-content").symlink_to("/etc/hostname")
    final = publish("a linked chat file", {}, 1, directory=out, stdout=["not a regular file"])
    if final["log"]:
        report("publish: a linked chat file", "a request was made")
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
