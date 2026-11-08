#!/usr/bin/env python3
"""Run cluster/build-system/admit-worker.sh over this repository's own
chuggy-scheduler.yaml, and over files shaped to the cases below, and hold what
it writes.

usage: admit-worker.py SCRIPT SCHEDULER_FILE BUSYBOX_BIN WORK

The script runs under a BusyBox shell with BusyBox's tools only, because the
pod or the machine that runs it may have no others.

THE CASES, by the line of the script each is the only reader of:

- the repository's file: the diff is the three changes and no other line, the
  new entry is last, is the next version, parses as the scheduler's
  document, and the session policy and the runtime name the digests given;
  a second run writes nothing and exits 0;
- the version is the next of `chuggy-worker`'s alone, compared as numbers, and
  the entry is last even when the last entry is a `generic-worker`;
- a commit or a digest that is not a full hash is refused, and so is a digest
  already offered, a runtime that is an offered worker, and a newest worker
  that is the digest given while the policy or the runtime names others;
- a file with no `chuggy-worker`, one of the three places missing or doubled,
  and a version that is not `0.<n>` are refused;
- a refused run leaves the file as it was byte for byte;
- MESSAGE_FILE gets a message naming the version, the commit and both digests.
"""

import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

OFFERED = "CHUG_SCHEDULER_OFFERED_IMAGES"
POLICY = "CHUG_SCHEDULER_SESSION_POLICY"
RUNTIME = "CHUG_SCHEDULER_WORKER_RUNTIME"
COMMIT = "1" * 40
WORKER = "sha256:" + "a" * 64
RUNTIME_DIGEST = "sha256:" + "b" * 64
FAILURES = []


def report(case, message):
    FAILURES.append(case)
    print(f"admit-worker: {case}: {message}", file=sys.stderr)


def variables(text):
    """The scheduler's environment as the file declares it."""
    for document in yaml.safe_load_all(text):
        if document and document.get("kind") == "Deployment":
            for container in document["spec"]["template"]["spec"]["containers"]:
                found = {entry["name"]: entry.get("value") for entry in container.get("env", [])}
                if OFFERED in found:
                    return found
    raise SystemExit("admit-worker: the file holds no scheduler Deployment")


class Suite:
    def __init__(self, script, scheduler, busybox, work):
        self.script, self.busybox, self.work = Path(script), Path(busybox), Path(work)
        self.original = Path(scheduler).read_text()

    def run(self, name, text, *arguments, message=False):
        case = self.work / name
        case.mkdir(parents=True, exist_ok=True)
        file = case / "chuggy-scheduler.yaml"
        file.write_text(text)
        environment = {"PATH": str(self.busybox), "TMPDIR": str(case)}
        if message:
            environment["MESSAGE_FILE"] = str(case / "message")
        completed = subprocess.run(
            [str(self.busybox / "sh"), str(self.script), str(file), *arguments],
            env=environment,
            text=True,
            capture_output=True,
        )
        return completed, file.read_text(), case / "message"

    def admits(self, name, text, worker=WORKER, runtime=RUNTIME_DIGEST, commit=COMMIT, **options):
        completed, after, message = self.run(name, text, commit, worker, runtime, **options)
        if completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
        return completed, after, message

    def refuses(self, name, text, *arguments, says):
        completed, after, _ = self.run(name, text, *arguments)
        if completed.returncode == 0:
            report(name, f"exited 0: {completed.stdout.strip()}")
        if says not in completed.stderr:
            report(name, f"did not say `{says}`: {completed.stderr.strip()}")
        if after != text:
            report(name, "was refused and wrote the file")

    def refuses_args(self, name, commit=COMMIT, worker=WORKER, runtime=RUNTIME_DIGEST, text=None, says=""):
        self.refuses(name, self.original if text is None else text, commit, worker, runtime, says=says)


def entry(image, name, version, system=True):
    lines = [f'"image": "registry.chuggy.internal/chuggy/{image}@sha256:{{digest}}"', f'"name": "{name}"', f'"version": "{version}"']
    if system:
        lines += ['"operatingSystem": "Linux"', '"architecture": "Amd64"', '"capabilities": ["Agent:Claude", "Agent:Codex"]']
    return lines


def scheduler(entries, policy="3" * 64, runtime="4" * 64, extra=""):
    """A minimal scheduler Deployment with the three places, entries being
    (image repository, name, version, digest)."""
    body = []
    for image, name, version, digest in entries:
        lines = [line.replace("{digest}", digest) for line in entry(image, name, version)]
        body.append("                  {\n" + ",\n".join("                    " + line for line in lines) + "\n                  }")
    offered = "                [\n" + ",\n".join(body) + "\n                ]"
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: chuggy-scheduler
spec:
  template:
    spec:
      containers:
        - name: scheduler
          env:
            # The runtime.
            - name: {RUNTIME}
              value: "registry.chuggy.internal/chuggy/worker-runtime@sha256:{runtime}"
            - name: {OFFERED}
              value: |
{offered}
            - name: {POLICY}
              value: |
                {{
                  "image": "registry.chuggy.internal/chuggy/worker@sha256:{policy}",
                  "profile": "chuggy-development"
                }}
{extra}"""


def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: admit-worker.py SCRIPT SCHEDULER_FILE BUSYBOX_BIN WORK")
    suite = Suite(*sys.argv[1:])
    original = suite.original

    # The repository's own file.
    completed, after, message = suite.admits("repository-file", original, message=True)
    before_lines, after_lines = original.splitlines(), after.splitlines()
    removed = [line[1:] for line in difflib.unified_diff(before_lines, after_lines, lineterm="", n=0) if line.startswith("-") and not line.startswith("---")]
    added = [line[1:] for line in difflib.unified_diff(before_lines, after_lines, lineterm="", n=0) if line.startswith("+") and not line.startswith("+++")]
    old, new = variables(original), variables(after)
    if sorted(new) != sorted(old):
        report("repository-file", "the variables of the Deployment changed")
    changed = sorted(name for name in new if new[name] != old[name])
    if changed != sorted([OFFERED, POLICY, RUNTIME]):
        report("repository-file", f"changed {changed}, not the three places")
    offered_before, offered_after = json.loads(old[OFFERED]), json.loads(new[OFFERED])
    if offered_after[:-1] != offered_before:
        report("repository-file", "the entries before the new one are not the entries there were")
    versions = [int(entry["version"][2:]) for entry in offered_before if entry["name"] == "chuggy-worker"]
    last = offered_after[-1]
    if last != {
        "image": f"registry.chuggy.internal/chuggy/worker@{WORKER}",
        "name": "chuggy-worker",
        "version": f"0.{max(versions) + 1}",
        "operatingSystem": "Linux",
        "architecture": "Amd64",
        "capabilities": ["Agent:Claude", "Agent:Codex"],
    }:
        report("repository-file", f"the new entry is {last}")
    if json.loads(new[POLICY])["image"] != f"registry.chuggy.internal/chuggy/worker@{WORKER}":
        report("repository-file", "the session policy does not run on the new worker")
    if {key: value for key, value in json.loads(new[POLICY]).items() if key != "image"} != {
        key: value for key, value in json.loads(old[POLICY]).items() if key != "image"
    }:
        report("repository-file", "the session policy's grant changed")
    if new[RUNTIME] != f"registry.chuggy.internal/chuggy/worker-runtime@{RUNTIME_DIGEST}":
        report("repository-file", f"the runtime is {new[RUNTIME]}")
    # Two lines out, the runtime and the policy's image. In: those two again,
    # the comma the last entry gains, and the new entry, whose closing brace is
    # the one the last entry had.
    if len(removed) != 2 or len(added) != 2 + 1 + 1 + 6:
        report("repository-file", f"{len(removed)} lines out and {len(added)} in")
    again, same, _ = suite.run("repository-file-again", after, COMMIT, WORKER, RUNTIME_DIGEST)
    if same != after or "nothing is written" not in again.stdout:
        report("repository-file-again", f"wrote over what it had written: {again.stdout.strip()}")
    text = (suite.work / "repository-file" / "message").read_text()
    for needed in (last["version"], COMMIT, WORKER, RUNTIME_DIGEST):
        if needed not in text:
            report("repository-file", f"the message does not name {needed}")
    if "--- a/" not in completed.stdout or "+++ b/" not in completed.stdout:
        report("repository-file", "printed no diff")

    # The version is chuggy-worker's, and the entry is last.
    mixed = scheduler([("worker", "chuggy-worker", "0.9", "1" * 64), ("worker-generic", "generic-worker", "0.30", "2" * 64)])
    _, after, _ = suite.admits("version-by-name-and-number", mixed)
    versions = [(entry["name"], entry["version"]) for entry in json.loads(variables(after)[OFFERED])]
    if versions != [("chuggy-worker", "0.9"), ("generic-worker", "0.30"), ("chuggy-worker", "0.10")]:
        report("version-by-name-and-number", f"the entries are {versions}")
    eleven = scheduler([("worker", "chuggy-worker", f"0.{n}", f"{n:02d}" * 32) for n in (2, 10, 9)])
    _, after, _ = suite.admits("version-is-a-number", eleven)
    if json.loads(variables(after)[OFFERED])[-1]["version"] != "0.11":
        report("version-is-a-number", "0.10 was not the highest")

    # Refused.
    suite.refuses_args("commit-is-short", commit="1" * 39, says="not a full commit hash")
    suite.refuses_args("commit-is-no-hex", commit="g" * 40, says="not a full commit hash")
    suite.refuses_args("worker-has-no-prefix", worker="a" * 64, says="is not sha256:<64 hex>")
    suite.refuses_args("worker-is-short", worker="sha256:" + "a" * 63, says="is not sha256:<64 hex>")
    suite.refuses_args("runtime-is-no-hex", runtime="sha256:" + "z" * 64, says="is not sha256:<64 hex>")
    offered = json.loads(variables(original)[OFFERED])
    older = offered[0]["image"].rpartition("@")[2]
    suite.refuses_args("worker-already-offered", worker=older, says="already offered, and not as the newest")
    suite.refuses_args("runtime-is-an-offered-worker", runtime=older, says="is a worker image already offered")
    newest = [entry for entry in offered if entry["name"] == "chuggy-worker"][-1]["image"].rpartition("@")[2]
    suite.refuses_args("newest-is-the-worker-but-not-the-rest", worker=newest, says="names others")

    generic_only = scheduler([("worker-generic", "generic-worker", "0.1", "1" * 64)])
    suite.refuses_args("no-chuggy-worker", text=generic_only, says="offers no chuggy-worker")
    suite.refuses_args(
        "no-runtime",
        text=scheduler([("worker", "chuggy-worker", "0.1", "1" * 64)]).replace(RUNTIME, "SOMETHING_ELSE"),
        says="exactly one worker runtime",
    )
    suite.refuses_args(
        "policy-is-doubled",
        text=scheduler([("worker", "chuggy-worker", "0.1", "1" * 64)], extra=f"            - name: {POLICY}\n              value: '{{\"image\": \"x/worker@sha256:{'3' * 64}\"}}'\n"),
        says="exactly one session policy",
    )
    suite.refuses_args(
        "version-is-no-number",
        text=scheduler([("worker", "chuggy-worker", "0.x", "1" * 64)]),
        says="is not 0.<n>",
    )
    suite.refuses_args(
        "version-is-not-0",
        text=scheduler([("worker", "chuggy-worker", "1.2", "1" * 64)]),
        says="is not 0.<n>",
    )
    completed = subprocess.run([str(suite.busybox / "sh"), str(suite.script), "nothing"], env={"PATH": str(suite.busybox)}, text=True, capture_output=True)
    if completed.returncode == 0 or "usage" not in completed.stderr:
        report("usage", "a call with too few arguments was not refused")
    completed = subprocess.run([str(suite.busybox / "sh"), str(suite.script), str(suite.work / "absent"), COMMIT, WORKER, RUNTIME_DIGEST], env={"PATH": str(suite.busybox)}, text=True, capture_output=True)
    if completed.returncode == 0 or "is not a file" not in completed.stderr:
        report("no-file", "a file that is not there was not refused")

    if FAILURES:
        raise SystemExit(f"admit-worker: {len(FAILURES)} failed: {', '.join(FAILURES)}")


if __name__ == "__main__":
    main()
