#!/usr/bin/env python3
"""Run the release trigger as its pod is given it, against an API server that
is a file, and hold what it starts and what it deletes.

WHAT IS RENDERED AND WHAT IS THIS SUITE'S. The script and the run it creates
are the files of the ConfigMap the rendered CronJob mounts, run by the
container's own `command` under a BusyBox shell, which is what its image has,
with every environment value the manifest writes: the retry delay and the
count kept are the manifest's, and the cases are laid out around them. The
clock is the build's. `kubectl` is stood in for, by this file run again.

WHAT THE STAND-IN IS HELD TO. It answers the calls the script makes and
refuses any other. It allows a call only if a Role in the same render, bound
to the ServiceAccount the pod runs as, grants it: a script that came to read
something its token cannot would pass against a stand-in that answered
everything. It evaluates the script's own `jsonpath` templates over whole
objects, so what a case states is an object and not the line the script hopes
to be given; the part of jsonpath it knows is the part named in `select`, and
a template outside it is refused.

WHAT IT IS NOT. It is not kubectl, and whether kubectl prints what this
prints for the same objects is not decided here.

A STARTED RUN IS READ BACK. The first case starts a run, finishes it as
Tekton would, and runs the script again over what it created: the
annotations a run is written with are the ones the next comparison reads, or
a release that succeeded would be started again every minute.

THE CASES, by the line of the decision each is the only reader of:

- no runs at all starts one, with the four parameters and the three
  annotations taken from the two sources and no placeholder left;
- an unfinished run starts nothing: one Tekton has not reconciled, one it is
  running, an old one behind a finished one, two at once -- whatever any of
  them was started for;
- the newest run succeeded for what the sources hold: nothing. For another
  commit, or another digest: a run. An older run for these does not count,
  and newest is by when a run was created, not by its name;
- the newest run failed for these inside the delay: nothing. Past it: a run.
  Failed for anything else, however lately: a run;
- a run of another pipeline is neither unfinished nor newest nor deleted;
- a source with no artifact starts nothing and is not a failure; a source
  that is not there, a read the API server refuses, a revision that names no
  commit, and an address or a digest that could not be written into the
  manifest, are failures, and start nothing;
- a second run created in the same moment has this one delete its own and
  nothing else;
- retention deletes the finished runs before the newest the manifest says to
  keep, by when they were created, counts a run just started, and never
  deletes one that has not finished.
"""

import datetime
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import yaml

CRONJOB = "release-trigger"
SOURCES = "gitrepositories.source.toolkit.fluxcd.io"
RUNS = "pipelineruns.tekton.dev"

COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40
FABRIC_COMMIT = "c" * 40
DIGEST = "sha256:" + "d" * 64
OTHER_DIGEST = "sha256:" + "e" * 64
CHUGGY_URL = "https://chuggy.example.invalid/chuggy.git"
FABRIC_URL = "https://fabric.example.invalid/fabric"

FAILURES = []


def refuse(message):
    raise SystemExit(f"release-trigger: {message}")


def report(case, message):
    FAILURES.append(case)
    print(f"release-trigger: {case}: {message}", file=sys.stderr)


def stamp(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# --------------------------------------------------------------------------
# The stand-in for kubectl.


def select(nodes, path):
    """Apply one jsonpath path to the nodes. Known: `.field`, with `\\.` for a
    dot in the name; `[*]`; `[?(@.field=="value")]`. A field an object lacks
    selects nothing, as kubectl does by default."""
    rest = path
    while rest:
        field = re.match(r"\.((?:\\.|[A-Za-z0-9_/-])+)", rest)
        every = rest.startswith("[*]")
        only = re.match(r'\[\?\(@\.([A-Za-z]+)=="([^"]*)"\)\]', rest)
        if field:
            name = field.group(1).replace("\\.", ".")
            nodes = [node[name] for node in nodes if isinstance(node, dict) and name in node]
            rest = rest[field.end():]
        elif every:
            nodes = [item for node in nodes if isinstance(node, list) for item in node]
            rest = rest[3:]
        elif only:
            nodes = [
                item
                for node in nodes
                if isinstance(node, list)
                for item in node
                if isinstance(item, dict) and item.get(only.group(1)) == only.group(2)
            ]
            rest = rest[only.end():]
        else:
            raise SystemExit(f"stand-in kubectl: jsonpath `{path}` is past what this evaluates")
    return nodes


def evaluate(template, root):
    blocks = re.findall(r'\{((?:"(?:[^"\\]|\\.)*"|[^{}"])*)\}', template)
    if "".join("{" + block + "}" for block in blocks) != template:
        raise SystemExit(f"stand-in kubectl: template `{template}` is past what this evaluates")

    def run(index, node, out):
        while index < len(blocks):
            block = blocks[index]
            if block == "end":
                return index
            if block.startswith("range "):
                items = select([node], block[len("range "):])
                end = None
                for item in items:
                    end = run(index + 1, item, out)
                if end is None:
                    end = run(index + 1, None, [])
                index = end + 1
                continue
            if block.startswith('"'):
                out.append(json.loads(block))
            else:
                found = select([node], block)
                if any(not isinstance(value, str) for value in found):
                    raise SystemExit(f"stand-in kubectl: `{block}` selects what is not text")
                out.append(" ".join(found))
            index += 1
        return index

    out = []
    run(0, root, out)
    return "".join(out)


def allowed(state, namespace, resource, verb, name=None):
    kind, _, group = resource.partition(".")
    for grant in state["grants"]:
        if (
            grant["namespace"] == namespace
            and group in grant["groups"]
            and kind in grant["resources"]
            and verb in grant["verbs"]
            and (not grant["names"] or name in grant["names"])
        ):
            return True
    return False


def forbidden(resource, verb, namespace):
    sys.exit(
        f'Error from server (Forbidden): {resource} is forbidden: cannot {verb} '
        f'resource in the namespace "{namespace}"'
    )


def kubectl(state_path, argv):
    state = json.loads(Path(state_path).read_text())
    state["calls"].append(argv)

    def save():
        Path(state_path).write_text(json.dumps(state))

    save()
    namespace = None
    if argv[:1] == ["--namespace"]:
        namespace, argv = argv[1], argv[2:]

    if argv[:1] == ["get"] and len(argv) == 5 and argv[1] == SOURCES and argv[3] == "--output":
        name, template = argv[2], argv[4]
        if not allowed(state, namespace, SOURCES, "get", name) or SOURCES in state["refused"]:
            forbidden(SOURCES, "get", namespace)
        found = state["sources"].get(namespace, {}).get(name)
        if found is None:
            sys.exit(f'Error from server (NotFound): {SOURCES} "{name}" not found')
        sys.stdout.write(evaluate(template.removeprefix("jsonpath="), found))
    elif argv[:1] == ["get"] and len(argv) == 4 and argv[1] == RUNS and argv[2] == "--output":
        if not allowed(state, namespace, RUNS, "list") or RUNS in state["refused"]:
            forbidden(RUNS, "list", namespace)
        listed = {"kind": "List", "items": state["runs"].get(namespace, [])}
        sys.stdout.write(evaluate(argv[3].removeprefix("jsonpath="), listed))
    elif argv == ["create", "--filename", "-", "--output", "name"]:
        made = yaml.safe_load(sys.stdin.read())
        metadata = made["metadata"]
        resource = made["kind"].lower() + "s." + made["apiVersion"].split("/")[0]
        if not allowed(state, metadata.get("namespace"), resource, "create") or "create" in state["refused"]:
            forbidden(resource, "create", metadata.get("namespace"))
        if resource != RUNS or "name" in metadata:
            sys.exit(f"stand-in kubectl: not an object this creates: {resource} {metadata}")
        state["made"] += 1
        metadata["name"] = f"{metadata.pop('generateName')}new{state['made']}"
        metadata["creationTimestamp"] = stamp(time.time())
        runs = state["runs"].setdefault(metadata["namespace"], [])
        runs.append(made)
        if state["beside"]:
            runs.append(state["beside"])
            state["beside"] = None
        save()
        print(f"{resource}/{metadata['name']}")
    elif argv[:3] == ["delete", RUNS, "--wait=false"] and len(argv) > 3:
        if not allowed(state, namespace, RUNS, "delete"):
            forbidden(RUNS, "delete", namespace)
        runs = state["runs"].get(namespace, [])
        for name in argv[3:]:
            kept = [run for run in runs if run["metadata"]["name"] != name]
            if len(kept) == len(runs):
                sys.exit(f'Error from server (NotFound): {RUNS} "{name}" not found')
            runs[:] = kept
            print(f'pipelinerun.tekton.dev "{name}" deleted')
        save()
    else:
        sys.exit(f"stand-in kubectl: not a call this suite answers: {argv}")


# --------------------------------------------------------------------------
# The suite.


def objects(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def one(documents, kind, name, namespace=None):
    found = [
        document
        for document in documents
        if document["kind"] == kind
        and document["metadata"]["name"] == name
        and (namespace is None or document["metadata"].get("namespace") == namespace)
    ]
    if len(found) != 1:
        refuse(f"the render holds {len(found)} {kind} {name}, not one")
    return found[0]


class Pod:
    """What the rendered CronJob gives its one container."""

    def __init__(self, rendered):
        documents = objects(rendered)
        cronjob = one(documents, "CronJob", CRONJOB)
        self.namespace = cronjob["metadata"]["namespace"]
        pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        if len(pod["containers"]) != 1 or pod.get("initContainers"):
            refuse("the trigger's pod is not one container")
        self.container = pod["containers"][0]
        command = self.container.get("command")
        if not command or command[0] != "/bin/sh" or len(command) != 2:
            refuse(f"the trigger runs {command}, not /bin/sh over one script")
        self.script = command[1]
        volumes = {volume["name"]: volume for volume in pod["volumes"]}
        self.files = {}
        for mount in self.container["volumeMounts"]:
            volume = volumes[mount["name"]]
            if "configMap" in volume:
                config = one(documents, "ConfigMap", volume["configMap"]["name"], self.namespace)
                for name, text in config["data"].items():
                    self.files[f"{mount['mountPath']}/{name}"] = text
            elif "emptyDir" not in volume:
                refuse(f"the trigger mounts {mount['name']}, which this suite does not stand in for")
        if self.script not in self.files:
            refuse(f"{self.script} is not a file of a ConfigMap the trigger mounts")
        self.env = {}
        for entry in self.container["env"]:
            if set(entry) != {"name", "value"}:
                refuse(f"the trigger takes {entry['name']} from a source this suite does not stand in for")
            self.env[entry["name"]] = entry["value"]
        self.delay = int(self.env["RETRY_DELAY_SECONDS"])
        self.keep = int(self.env["KEEP_RUNS"])
        self.sources = self.env["SOURCES_NAMESPACE"]
        self.runs = self.env["RUNS_NAMESPACE"]
        self.pipeline = self.env["PIPELINE"]

        account = pod["serviceAccountName"]
        self.grants = []
        for binding in documents:
            if binding["kind"] != "RoleBinding":
                continue
            if not any(
                subject.get("kind") == "ServiceAccount"
                and subject.get("name") == account
                and subject.get("namespace") == self.namespace
                for subject in binding.get("subjects", [])
            ):
                continue
            if binding["roleRef"]["kind"] != "Role":
                refuse(f"RoleBinding {binding['metadata']['name']} binds the trigger to what is not a Role")
            role = one(documents, "Role", binding["roleRef"]["name"], binding["metadata"]["namespace"])
            for rule in role["rules"]:
                self.grants.append(
                    {
                        "namespace": role["metadata"]["namespace"],
                        "groups": rule["apiGroups"],
                        "resources": rule["resources"],
                        "verbs": rule["verbs"],
                        "names": rule.get("resourceNames", []),
                    }
                )


def source(name, url, commit=COMMIT, digest=DIGEST, revision=None):
    found = {
        "apiVersion": "source.toolkit.fluxcd.io/v1",
        "kind": "GitRepository",
        "metadata": {"name": name, "namespace": "flux-system"},
        "spec": {"url": url, "interval": "1m0s", "ref": {"branch": "main"}},
    }
    if commit:
        found["status"] = {
            "artifact": {
                "revision": revision or f"main@sha1:{commit}",
                **({"digest": digest} if digest else {}),
                "url": f"http://source-controller.flux-system.svc.cluster.local./gitrepository/flux-system/{name}/{commit}.tar.gz",
            },
            "conditions": [{"type": "Ready", "status": "True", "lastTransitionTime": stamp(0)}],
        }
    return found


class Suite:
    def __init__(self, rendered, busybox, work):
        self.pod = Pod(rendered)
        self.busybox = Path(busybox)
        self.work = Path(work)
        self.now = int(time.time())

    def run(self, name, created, state, commit=COMMIT, digest=DIGEST, decided=None, pipeline=None):
        """A run as the API server holds it. `created` and `decided` are
        seconds before now; `state` is new, running, succeeded or failed."""
        found = {
            "apiVersion": "tekton.dev/v1",
            "kind": "PipelineRun",
            "metadata": {
                "name": name,
                "namespace": self.pod.runs,
                "creationTimestamp": stamp(self.now - created),
                "annotations": {
                    "fabric.chuggy.dev/chuggy-commit": commit,
                    "fabric.chuggy.dev/manifests-digest": digest,
                    "fabric.chuggy.dev/manifests-commit": FABRIC_COMMIT,
                },
                "labels": {"tekton.dev/pipeline": pipeline or self.pod.pipeline},
            },
            "spec": {"pipelineRef": {"name": pipeline or self.pod.pipeline}},
        }
        if state != "new":
            status = {"running": "Unknown", "succeeded": "True", "failed": "False"}[state]
            when = created if decided is None else decided
            found["status"] = {
                "startTime": stamp(self.now - created),
                "conditions": [
                    {
                        "type": "Succeeded",
                        "status": status,
                        "reason": state,
                        "lastTransitionTime": stamp(self.now - when),
                    }
                ],
            }
        return found

    def case(self, name, runs=(), chuggy=None, fabric=None, refused=(), beside=None, env=None, state=None):
        """Lay one case out, run the script once, and return what it left."""
        case = self.work / name
        case.mkdir(parents=True, exist_ok=True)
        (case / "tmp").mkdir(exist_ok=True)
        state_path = case / "state.json"
        if state is None:
            sources = {}
            for found in (
                source("chuggy", CHUGGY_URL, digest="sha256:" + "f" * 64) if chuggy is None else chuggy,
                source("fabric-release", FABRIC_URL, commit=FABRIC_COMMIT) if fabric is None else fabric,
            ):
                if found:
                    sources[found["metadata"]["name"]] = found
            state = {
                "grants": self.pod.grants,
                "sources": {self.pod.sources: sources},
                "runs": {self.pod.runs: list(runs)},
                "refused": list(refused),
                "beside": beside,
                "made": 0,
                "calls": [],
            }
        state["calls"] = []
        state_path.write_text(json.dumps(state))
        programs = case / "bin"
        programs.mkdir(exist_ok=True)
        stand_in = programs / "kubectl"
        stand_in.write_text(
            f"#!{sys.executable}\nimport sys\n"
            f"sys.argv = [{str(Path(__file__).resolve())!r}, '--as-kubectl', {str(state_path)!r}] + sys.argv[1:]\n"
            f"exec(compile(open(sys.argv[0]).read(), sys.argv[0], 'exec'))\n"
        )
        stand_in.chmod(stand_in.stat().st_mode | stat.S_IXUSR)
        for path, text in self.pod.files.items():
            target = case / path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        environment = {}
        for key, value in {**self.pod.env, **(env or {})}.items():
            if value == "/tmp" or any(value.startswith(path.rsplit("/", 1)[0] + "/") for path in self.pod.files):
                value = str(case / value.lstrip("/"))
            elif value.startswith("/"):
                refuse(f"the trigger is given the path {value}, which this suite does not stand in for")
            environment[key] = value
        environment["PATH"] = f"{programs}:{self.busybox}"
        completed = subprocess.run(
            [str(self.busybox / "sh"), str(case / self.pod.script.lstrip("/"))],
            env=environment,
            text=True,
            capture_output=True,
        )
        left = json.loads(state_path.read_text())
        before = {run["metadata"]["name"] for run in (state["runs"][self.pod.runs])}
        after = {run["metadata"]["name"]: run for run in left["runs"][self.pod.runs]}
        return {
            "name": name,
            "completed": completed,
            "state": left,
            "started": [after[made] for made in after if made not in before],
            "deleted": sorted(before - after.keys()),
            "creates": sum(1 for call in left["calls"] if call[:1] == ["create"]),
        }

    def expect(self, result, started=0, deleted=(), says=None, fails=False, creates=None):
        name, completed = result["name"], result["completed"]
        if fails and completed.returncode == 0:
            report(name, f"exited 0: {completed.stdout.strip()}")
        if not fails and completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
        if len(result["started"]) != started:
            report(name, f"left {len(result['started'])} new runs, not {started}: {completed.stdout.strip()} {completed.stderr.strip()}")
        if result["creates"] != (started if creates is None else creates):
            report(name, f"asked to create {result['creates']} times")
        if result["deleted"] != sorted(deleted):
            report(name, f"deleted {result['deleted']}, not {sorted(deleted)}")
        said = completed.stderr if fails else completed.stdout
        if says and says not in said:
            report(name, f"did not say `{says}`: {said.strip()}")
        return result

    def nothing(self, name, says="nothing is started", **arguments):
        return self.expect(self.case(name, **arguments), says=says)

    def starts(self, name, says=None, commit=COMMIT, digest=DIGEST, **arguments):
        result = self.expect(self.case(name, **arguments), started=1, says=says)
        if len(result["started"]) == 1:
            self.as_the_sources_say(name, result["started"][0], commit, digest)
        return result

    def as_the_sources_say(self, name, started, commit, digest):
        text = json.dumps(started)
        if "@" in text.replace("main@sha1", ""):
            report(name, f"the run was created with a placeholder left in it: {text}")
        metadata = started["metadata"]
        if metadata["namespace"] != self.pod.runs:
            report(name, f"the run was created in {metadata['namespace']}")
        if started["spec"]["pipelineRef"] != {"name": self.pod.pipeline}:
            report(name, f"the run is of {started['spec']['pipelineRef']}")
        params = {param["name"]: param["value"] for param in started["spec"]["params"]}
        expected = {
            "chuggy-url": CHUGGY_URL,
            "chuggy-commit": commit,
            "manifests-url": FABRIC_URL,
            "manifests-commit": FABRIC_COMMIT,
        }
        if params != expected:
            report(name, f"the run's parameters are {params}, not {expected}")
        annotations = {
            "fabric.chuggy.dev/chuggy-commit": commit,
            "fabric.chuggy.dev/manifests-digest": digest,
            "fabric.chuggy.dev/manifests-commit": FABRIC_COMMIT,
        }
        if metadata.get("annotations") != annotations:
            report(name, f"the run's annotations are {metadata.get('annotations')}, not {annotations}")

    def again(self, name, earlier, finish=None, decided=0, **expected):
        """Run the script over what an earlier case left, having finished the
        run it started the way Tekton would."""
        state = earlier["state"]
        if finish:
            for run in state["runs"][self.pod.runs]:
                if "status" not in run:
                    run["status"] = {
                        "conditions": [
                            {
                                "type": "Succeeded",
                                "status": {"succeeded": "True", "failed": "False"}[finish],
                                "lastTransitionTime": stamp(self.now - decided),
                            }
                        ]
                    }
        result = self.case(name, state=state)
        return self.expect(result, **expected)


def main():
    if len(sys.argv) != 4:
        refuse("usage: release-trigger.py RENDERED_BUILD_SYSTEM BUSYBOX_BIN WORK")
    suite = Suite(*sys.argv[1:])
    pod, run = suite.pod, suite.run
    inside, past = pod.delay - 20, pod.delay + 20
    if inside <= 0:
        refuse(f"a retry delay of {pod.delay} seconds leaves no case inside it")

    first = suite.starts("no-runs", says="(there is none)")
    suite.again("started-run-is-unfinished", first, says="has not finished: nothing is started")
    suite.again("started-run-succeeded", first, finish="succeeded", says="released chuggy")
    failed = suite.starts("no-runs-then-failed")
    suite.again("started-run-failed-lately", failed, finish="failed", says="inside the retry delay")
    failed = suite.starts("no-runs-then-failed-long-ago")
    suite.again("started-run-failed-long-ago", failed, finish="failed", decided=past, started=1, says="retrying")

    suite.nothing("unfinished-new", runs=[run("r1", 30, "new", OTHER_COMMIT)], says="r1 has not finished")
    suite.nothing("unfinished-running", runs=[run("r1", 30, "running", OTHER_COMMIT)], says="r1 has not finished")
    suite.nothing(
        "unfinished-behind-a-finished-one",
        runs=[run("r1", 900, "running"), run("r2", 600, "succeeded", OTHER_COMMIT)],
        says="r1 has not finished",
    )
    suite.nothing(
        "two-unfinished",
        runs=[run("r1", 40, "running"), run("r2", 30, "new", OTHER_COMMIT)],
        says="r1 r2 has not finished",
    )

    suite.nothing("succeeded-for-these", runs=[run("r1", 600, "succeeded")], says="r1 released chuggy")
    suite.starts("succeeded-for-another-commit", runs=[run("r1", 600, "succeeded", OTHER_COMMIT)])
    suite.starts("succeeded-for-another-digest", runs=[run("r1", 600, "succeeded", digest=OTHER_DIGEST)])
    suite.starts(
        "an-older-run-for-these",
        runs=[run("r1", 900, "succeeded"), run("r2", 600, "succeeded", OTHER_COMMIT)],
    )
    suite.nothing(
        "newest-is-by-time-not-name",
        runs=[run("zz", 900, "succeeded", OTHER_COMMIT), run("aa", 600, "succeeded")],
        says="aa released chuggy",
    )

    suite.nothing(
        "failed-for-these-lately",
        runs=[run("r1", 3600, "failed", decided=inside)],
        says="inside the retry delay",
    )
    suite.starts("failed-for-these-long-ago", runs=[run("r1", 3600, "failed", decided=past)], says="retrying")
    suite.starts("failed-for-others-long-ago", runs=[run("r1", 86400, "failed", OTHER_COMMIT)])
    suite.starts("failed-for-others-lately", runs=[run("r1", 60, "failed", OTHER_COMMIT, decided=5)])
    suite.starts(
        "failed-for-another-digest-lately",
        runs=[run("r1", 60, "failed", digest=OTHER_DIGEST, decided=5)],
    )

    suite.starts(
        "another-pipeline-unfinished",
        runs=[run("other", 30, "running", pipeline="another")],
        says="(there is none)",
    )
    suite.starts(
        "another-pipeline-newest",
        runs=[run("r1", 900, "succeeded", OTHER_COMMIT), run("other", 30, "succeeded", pipeline="another")],
    )

    for missing, sources in (
        ("chuggy", {"chuggy": source("chuggy", CHUGGY_URL, commit=None)}),
        ("fabric", {"fabric": source("fabric-release", FABRIC_URL, commit=None)}),
    ):
        suite.nothing(
            f"no-artifact-{missing}",
            runs=[run("r1", 600, "succeeded", OTHER_COMMIT)],
            says="holds no artifact yet",
            **sources,
        )
    suite.nothing(
        "no-digest-fabric",
        fabric=source("fabric-release", FABRIC_URL, commit=FABRIC_COMMIT, digest=None),
        says="holds no artifact yet",
    )
    suite.expect(
        suite.case("source-is-not-there", chuggy=False), fails=True, says="NotFound"
    )
    suite.expect(
        suite.case("source-read-refused", refused=[SOURCES]), fails=True, says="Forbidden"
    )
    suite.expect(suite.case("runs-read-refused", refused=[RUNS]), fails=True, says="Forbidden")
    suite.expect(
        suite.case("create-refused", refused=["create"]), fails=True, says="Forbidden", creates=1
    )
    suite.expect(
        suite.case("revision-names-no-commit", chuggy=source("chuggy", CHUGGY_URL, revision="main@sha1:" + "a" * 39)),
        fails=True,
        says="names no full commit hash",
    )
    suite.expect(
        suite.case("revision-is-not-git's", chuggy=source("chuggy", CHUGGY_URL, revision="latest@sha256:" + "a" * 64)),
        fails=True,
        says="is not a branch and a commit",
    )
    suite.expect(
        suite.case("revision-names-no-hash", chuggy=source("chuggy", CHUGGY_URL, revision="main@sha1:" + "g" * 40)),
        fails=True,
        says="names no commit hash",
    )
    for case, sources in (
        ("address-would-rewrite", {"fabric": source("fabric-release", "https://example.invalid/a&b", commit=FABRIC_COMMIT)}),
        ("address-holds-a-placeholder", {"chuggy": source("chuggy", "https://example.invalid/@chuggy-commit@")}),
        ("digest-would-rewrite", {"fabric": source("fabric-release", FABRIC_URL, commit=FABRIC_COMMIT, digest=DIGEST[:-1] + "&")}),
    ):
        suite.expect(suite.case(case, **sources), fails=True, says="is not one this writes into a manifest")
    suite.expect(suite.case("keep-none", env={"KEEP_RUNS": "0"}), fails=True, says="would delete the run")
    suite.expect(suite.case("delay-is-no-count", env={"RETRY_DELAY_SECONDS": "5m"}), fails=True, says="are counts")

    beside = run("beside", 0, "new", OTHER_COMMIT)
    result = suite.expect(
        suite.case("another-started-in-the-same-moment", runs=[run("r1", 600, "succeeded", OTHER_COMMIT)], beside=beside),
        started=1,
        creates=1,
        says="beside had not finished either",
    )
    if [made["metadata"]["name"] for made in result["started"]] != ["beside"]:
        report("another-started-in-the-same-moment", f"left {result['started']}")
    result = suite.expect(
        suite.case(
            "another-pipeline-started-in-the-same-moment",
            runs=[run("r1", 600, "succeeded", OTHER_COMMIT)],
            beside=run("beside", 0, "new", pipeline="another"),
        ),
        started=2,
        creates=1,
    )

    keep = pod.keep
    finished = [run(f"old{index:02d}", 100000 - index * 100, "succeeded") for index in range(keep + 3)]
    suite.expect(
        suite.case("retention", runs=finished), deleted=["old00", "old01", "old02"], says="nothing is started"
    )
    suite.expect(suite.case("retention-at-the-count", runs=finished[3:]), says="nothing is started")
    by_time = [run(f"n{keep + 3 - index:02d}", 100000 - index * 100, "succeeded") for index in range(keep + 3)]
    suite.expect(
        suite.case("retention-is-by-time", runs=by_time),
        deleted=[f"n{keep + 3 - index:02d}" for index in range(3)],
    )
    unfinished = [run("stuck", 200000, "running")] + finished
    suite.expect(
        suite.case("retention-keeps-the-unfinished", runs=unfinished),
        deleted=["old00", "old01", "old02"],
        says="stuck has not finished",
    )
    others = [run(f"x{index:02d}", 300000 - index, "succeeded", pipeline="another") for index in range(keep + 3)]
    suite.expect(suite.case("retention-of-this-pipeline-only", runs=others + finished[3:]), says="nothing is started")
    for_others = [run(f"old{index:02d}", 100000 - index * 100, "succeeded", OTHER_COMMIT) for index in range(keep + 2)]
    suite.expect(
        suite.case("retention-counts-the-run-started", runs=for_others),
        started=1,
        deleted=["old00", "old01", "old02"],
    )
    suite.expect(
        suite.case(
            "retention-without-an-artifact",
            runs=finished,
            chuggy=source("chuggy", CHUGGY_URL, commit=None),
        ),
        deleted=["old00", "old01", "old02"],
        says="holds no artifact yet",
    )

    if FAILURES:
        raise SystemExit(f"release-trigger: {len(FAILURES)} failed: {', '.join(FAILURES)}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--as-kubectl"]:
        kubectl(sys.argv[2], sys.argv[3:])
    else:
        main()
