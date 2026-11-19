#!/usr/bin/env python3
"""Run the site admission's two steps of its own against stand-ins for what
they speak to, and hold what each does.

usage: chug-gy-admit.py BUILD_SYSTEM_DIRECTORY DEPLOYMENT_FILE WORK

BUILD_SYSTEM_DIRECTORY holds chug-gy-admit.yaml and
chug-gy-admit-{read,prepare}.sh; DEPLOYMENT_FILE
is this tree's cluster/chug-gy/chug-gy.yaml. WORK is an empty directory. `sh`,
`git`, `jq` and python3 come from the PATH this is run with; `kubectl` is a
stand-in written into WORK, so no cluster is touched. The last step,
admit-publish.sh, is the worker admission's too, and tests/worker-admit.py runs
it, with a hand-off of the site's among its cases.

THE CASES, by the script each is the only reader of:

- read: the newest run that succeeded, of the Task, for the site's image, is
  read with its digest and commit and the line of IMAGES it is of; a newer run
  failed or unfinished leaves the one before it, and a failed run alone is
  nothing, and succeeds; a run of another Task or another image is not
  counted; no runs is nothing; a digest or a commit that is not a full hash is
  refused; of two images, one with no build is left out and the other read;
- prepare: over a repository holding this tree's Deployment, a digest it does
  not name is written as the `web` container's image, and that line alone
  changes; the hand-off is the file, the message titled as a person titled
  each of the site's images, the branch named for the digest and the blob and
  commit it was made against, with `ready` last; the digest the file already
  names, and no images, hand off nothing; the second image, of the `docs`
  init container, is one more line and moves with the first under one title,
  and alone where the first is already named; a container the file does not
  have, an image of another repository and a digest that is not one are
  refused and hand off nothing;
- the two together: each line of the CronJob's IMAGES names exactly one
  container or init container of this tree's Deployment, read as the prepare
  step reads it, whose image is of that line's repository by digest; and that
  Deployment, read with each image at the digest it already names, hands off
  nothing.
"""

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

BUILD = Path(sys.argv[1]).resolve()
DEPLOYMENT = Path(sys.argv[2]).resolve()
WORK = Path(sys.argv[3]).resolve()
DEPLOYMENT_PATH = "cluster/chug-gy/chug-gy.yaml"
FAILURES = []
TASK = "build-image"
BUILD_REGISTRY = "registry.example:5000"
REGISTRY = "registry.chuggy.internal"
WEB = f"{BUILD_REGISTRY}/chug-gy/web"
DOCS = f"{BUILD_REGISTRY}/chug-gy/docs"
SITE = "web chug-gy/web kasofsk/chug.gy the site's image"
DOCS_ENTRY = "docs chug-gy/docs kasofsk/chuggy-docs the docs"
COMMIT = "1" * 40
DIGEST = "sha256:" + "a" * 64
OLDER = "sha256:" + "c" * 64


def report(case, message):
    FAILURES.append(case)
    print(f"chug-gy-admit: {case}: {message}", file=sys.stderr)


def write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run(script, environment):
    env = {"PATH": f"{WORK / 'bin'}:{os.environ['PATH']}", "HOME": str(WORK / "home"), **environment}
    return subprocess.run(["sh", str(BUILD / script)], env=env, capture_output=True, text=True, cwd=WORK)


def expect(case, result, code, *, stdout=()):
    if result.returncode != code:
        report(case, f"exited {result.returncode}, not {code}: {result.stderr.strip()[-300:]}")
    for needle in stdout:
        if needle not in result.stdout + result.stderr:
            report(case, f"said nothing of {needle!r}: {(result.stdout + result.stderr).strip()[-300:]}")


def task_run(name, created, outcome, digest=DIGEST, image=WEB, commit=COMMIT, task=TASK):
    status = {"conditions": [{"type": "Succeeded", "status": outcome}]}
    if digest is not None:
        status["results"] = [{"name": "digest", "value": digest}]
    return {
        "metadata": {"name": name, "creationTimestamp": f"2026-01-01T{created}:00Z"},
        "spec": {"taskRef": {"name": task}, "params": [{"name": "image", "value": image}, {"name": "commit", "value": commit}]},
        "status": status,
    }


def line(digest=DIGEST, commit=COMMIT, run_name="new", entry=SITE):
    container, repository, rest = entry.split(" ", 2)
    return f"{container} {repository} {digest} {commit} {run_name} {rest}\n"


def read(case, items, code=0, *, found=None, stdout=(), images=SITE + "\n"):
    out = WORK / "out" / case.replace(" ", "-")
    write(WORK / "runs.json", json.dumps({"items": items}))
    result = run(
        "chug-gy-admit-read.sh",
        {"RUNS_NAMESPACE": "chuggy-build", "TASK": TASK, "REGISTRY": BUILD_REGISTRY, "IMAGES": images, "OUT": str(out)},
    )
    expect(f"read: {case}", result, code, stdout=stdout)
    held = (out / "images").read_text() if (out / "images").exists() else None
    if held != found:
        report(f"read: {case}", f"left {held!r}, not {found!r}")


def cases_read():
    read("a build", [task_run("new", "10", "True")], found=line(), stdout=["built"])
    read("no runs", [], stdout=["nothing to admit"])
    older = task_run("old", "09", "True", OLDER)
    read("a newer build failed", [older, task_run("new", "10", "False")], found=line(OLDER, run_name="old"))
    read("a newer build unfinished", [older, task_run("new", "10", "Unknown", None)], found=line(OLDER, run_name="old"))
    read("a failed build alone", [task_run("new", "10", "False")], stdout=["nothing to admit"])
    read("the newest of two builds", [older, task_run("new", "10", "True")], found=line())
    read("a run of another task", [task_run("x", "10", "True", task="build-two-platform-image")], stdout=["nothing to admit"])
    read("a run of another image", [task_run("x", "10", "True", image=f"{BUILD_REGISTRY}/chug-gy/other")], stdout=["nothing to admit"])
    read("a digest that is not one", [task_run("new", "10", "True", "sha256:xyz")], 1, stdout=["not a sha256 digest"])
    read("a short digest", [task_run("new", "10", "True", "sha256:" + "a" * 63)], 1, stdout=["not a full sha256 digest"])
    read("no digest", [task_run("new", "10", "True", None)], 1, stdout=["not a sha256 digest"])
    read("a commit that is not one", [task_run("new", "10", "True", commit="main")], 1, stdout=["not a commit hash"])
    read("a short commit", [task_run("new", "10", "True", commit="1" * 39)], 1, stdout=["not a full commit hash"])
    docs = DOCS_ENTRY
    read("an image with no build beside one with", [task_run("new", "10", "True")], found=line(), images=f"{SITE}\n{docs}\n", stdout=["nothing to admit of it"])
    both = [task_run("new", "10", "True"), task_run("d", "11", "True", OLDER, image=DOCS, commit="2" * 40)]
    read("two images", both, found=line() + line(OLDER, "2" * 40, "d", docs), images=f"{SITE}\n{docs}\n")
    read("an image with no words", [task_run("new", "10", "True")], 1, images="web chug-gy/web kasofsk/chug.gy\n", stdout=["no words"])


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def fabric(name, deployment):
    root = WORK / "fabric" / name
    write(root / DEPLOYMENT_PATH, deployment)
    git("init", "--quiet", "--initial-branch=main", cwd=root)
    git("add", "-A", cwd=root)
    git("commit", "--quiet", "-m", "fabric", cwd=root)
    return root


def prepare(case, repo, images, code=0, *, ready=True, stdout=()):
    directory = WORK / "prep" / case.replace(" ", "-")
    write(directory / "in/images", images) if images is not None else (directory / "in").mkdir(parents=True)
    result = run(
        "chug-gy-admit-prepare.sh",
        {
            "IN": str(directory / "in"), "OUT": str(directory / "out"), "FABRIC_URL": f"file://{repo}",
            "BRANCH": "main", "CHECKOUT": str(directory / "checkout"), "DEPLOYMENT": DEPLOYMENT_PATH,
            "REGISTRY": REGISTRY,
        },
    )
    expect(f"prepare: {case}", result, code, stdout=stdout)
    if (directory / "out" / "ready").exists() != ready:
        report(f"prepare: {case}", f"ready is {not ready}")
    if not ready and (directory / "out").exists() and any((directory / "out").iterdir()):
        report(f"prepare: {case}", "handed off something")
    return directory / "out"


def held_web():
    (held,) = re.findall(r"image: (registry\.chuggy\.internal/chug-gy/web@sha256:[0-9a-f]{64})", DEPLOYMENT.read_text())
    return held


def images_entries():
    """The lines of the read step's IMAGES in chug-gy-admit.yaml, as the
    block scalar under `- name: IMAGES` holds them."""
    lines = (BUILD / "chug-gy-admit.yaml").read_text().split("\n")
    (start,) = [at for at, text in enumerate(lines) if text.strip() == "- name: IMAGES"]
    if lines[start + 1].strip() != "value: |":
        raise SystemExit(f"chug-gy-admit: IMAGES is not a block scalar: {lines[start + 1]!r}")
    indent = len(lines[start + 2]) - len(lines[start + 2].lstrip(" "))
    entries = []
    for text in lines[start + 2:]:
        if not text.strip() or len(text) - len(text.lstrip(" ")) < indent:
            break
        entries.append(text.strip())
    return entries


def named_images(container):
    """Every image of a list item `- name: <container>`, read as
    chug-gy-admit-prepare.sh reads the Deployment."""
    lines = DEPLOYMENT.read_text().split("\n")
    found = []
    for start, text in enumerate(lines):
        head = re.fullmatch(r"( *)- name: " + re.escape(container) + r" *", text)
        if not head:
            continue
        indent = len(head.group(1))
        for at in range(start + 1, len(lines)):
            inner = lines[at]
            if inner.strip() and len(inner) - len(inner.lstrip(" ")) <= indent:
                break
            named = re.fullmatch(" " * (indent + 2) + r"image: *(\S+) *", inner)
            if named:
                found.append(named.group(1))
    return found


def changed_lines(before, after):
    pairs = list(zip(before.split("\n"), after.split("\n")))
    if len(before.split("\n")) != len(after.split("\n")):
        return None
    return [(old, new) for old, new in pairs if old != new]


def cases_prepare():
    repo = fabric("site", DEPLOYMENT.read_text())
    out = prepare("a build", repo, line(), stdout=["is ready on"])
    if (out / "ready").exists():
        wanted = {
            "branch": "admit/chug-gy-" + "a" * 12,
            "path": DEPLOYMENT_PATH,
            "target": "main",
            "base": git("rev-parse", "HEAD", cwd=repo),
            "blob": git("rev-parse", f"HEAD:{DEPLOYMENT_PATH}", cwd=repo),
        }
        for name, value in wanted.items():
            if (out / name).read_text() != value:
                report("prepare: a build", f"{name} is {(out / name).read_text()!r}, not {value!r}")
        message = (out / "message").read_text()
        if message.split("\n")[0] != "chug-gy: the site's image, built at kasofsk/chug.gy 1111111":
            report("prepare: a build", f"the message is titled {message.split(chr(10))[0]!r}")
        if "TaskRun new" not in message:
            report("prepare: a build", "the message does not name the run")
        changed = changed_lines(DEPLOYMENT.read_text(), (out / "content").read_text())
        image = f"{REGISTRY}/chug-gy/web@{DIGEST}"
        if changed is None or len(changed) != 1 or changed[0][1].strip() != f"image: {image}" or held_web() not in changed[0][0]:
            report("prepare: a build", f"the content changed {changed}, not the web container's image alone")
        if set(p.name for p in out.iterdir()) != {"branch", "path", "blob", "base", "target", "message", "content", "ready"}:
            report("prepare: a build", f"handed off {sorted(p.name for p in out.iterdir())}")
    if (repo / DEPLOYMENT_PATH).read_text() != DEPLOYMENT.read_text():
        report("prepare: a build", "the repository it cloned from was changed")

    held = held_web().split("@", 1)[1]
    prepare("a digest already named", repo, line(held), ready=False, stdout=["nothing to admit"])
    prepare("no images", repo, None, ready=False, stdout=["no image to admit"])
    prepare("a digest that is not one", repo, line("sha256:nope"), 1, ready=False, stdout=["not a sha256 digest"])
    prepare("a digest that is a tag", repo, line("latest"), 1, ready=False, stdout=["not a sha256 digest"])
    prepare("a container the file does not have", repo, line(entry="api chug-gy/api kasofsk/chug.gy the api"), 1, ready=False, stdout=["0 containers named api"])

    other = fabric("other", DEPLOYMENT.read_text().replace(held_web(), f"{REGISTRY}/elsewhere/web@{OLDER}"))
    prepare("an image of another repository", other, line(), 1, ready=False, stdout=["which is not of"])

    # The Deployment's two images: the site's, and the docs' in an init
    # container ahead of it.
    two = DEPLOYMENT.read_text()
    if not named_images("docs"):
        report("prepare: two images", "the Deployment has no `docs` container to move")
    newer_docs = "sha256:" + "d" * 64
    docs = DOCS_ENTRY
    out = prepare("two images", repo, line() + line(newer_docs, "2" * 40, "d", docs), stdout=["is ready on"])
    if (out / "ready").exists():
        title = (out / "message").read_text().split("\n")[0]
        if title != "chug-gy: the site's image, built at kasofsk/chug.gy 1111111 and the docs, built at kasofsk/chuggy-docs 2222222":
            report("prepare: two images", f"the message is titled {title!r}")
        changed = changed_lines(two, (out / "content").read_text())
        if changed is None or [new.strip() for _, new in changed] != [f"image: {REGISTRY}/chug-gy/docs@{newer_docs}", f"image: {REGISTRY}/chug-gy/web@{DIGEST}"]:
            report("prepare: two images", f"the content changed {changed}")
    out = prepare("two images, one already named", repo, line(held) + line(newer_docs, "2" * 40, "d", docs), stdout=["is ready on"])
    if (out / "ready").exists():
        if (out / "branch").read_text() != "admit/chug-gy-" + "d" * 12:
            report("prepare: two images, one already named", f"the branch is {(out / 'branch').read_text()!r}")
        if (out / "message").read_text().split("\n")[0] != "chug-gy: the docs, built at kasofsk/chuggy-docs 2222222":
            report("prepare: two images, one already named", "the title names an image that did not move")


def cases_agree():
    entries = images_entries()
    if [entry.split(" ", 1)[0] for entry in entries] != ["web", "docs"]:
        report("agree: IMAGES", f"names {entries}, not the web and docs containers")
    held = ""
    for entry in entries:
        container, repository, _ = entry.split(" ", 2)
        images = named_images(container)
        if len(images) != 1:
            report("agree: IMAGES", f"{container} is {len(images)} containers with an image in the Deployment, not one")
            continue
        (image,) = images
        if not re.fullmatch(rf"{re.escape(REGISTRY)}/{re.escape(repository)}@sha256:[0-9a-f]{{64}}", image):
            report("agree: IMAGES", f"{container} runs {image}, not {REGISTRY}/{repository} by digest")
            continue
        held += line(image.split("@", 1)[1], run_name="held", entry=entry)
    repo = fabric("agree", DEPLOYMENT.read_text())
    prepare("the Deployment at the digests it names", repo, held, ready=False, stdout=["nothing to admit"])


def main():
    write(WORK / "bin/kubectl", '#!/bin/sh\ncase "$*" in\n  *"get taskruns"*) cat "$(dirname "$0")/../runs.json" ;;\n  *) exit 3 ;;\nesac\n', True)
    (WORK / "home").mkdir(parents=True, exist_ok=True)
    cases_read()
    cases_prepare()
    cases_agree()
    if FAILURES:
        raise SystemExit(f"chug-gy-admit: {len(FAILURES)} failing: {sorted(set(FAILURES))}")


main()
