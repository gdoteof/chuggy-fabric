#!/usr/bin/env python3
"""Run the `publish` step as its pod is given it, over this tree's own release
directories, and hold what it would push.

WHAT IS RENDERED AND WHAT IS THIS SUITE'S. The script is the bytes of the
ConfigMap the rendered `publish` step mounts, run by that step's own
`command` under a BusyBox shell, which is what the step's image has. Its
environment is the step's, with each `$(params.…)` resolved the way the
rendered Pipeline resolves it: the image names are the Pipeline's own, so a
name there that the manifests do not use fails here. `kubectl` is the real
one. Three programs are stood in for, each because the build has no registry
and no clock to set: `wget`, which answers the tag list in the form BusyBox
prints it; `flux`, which keeps the directory it was told to push; and `date`,
so a tag can be made to tie with the version.

A reference this does not know how to resolve is refused rather than skipped:
it is one the pod would have and this run would not.

THE TWO TREES. `pinned` is cluster/chuggy-migrate and cluster/chuggy as this
commit carries them. `bare` is the same two with what a release writes taken
out -- the digests of the two images, the source-commit annotation, the
commit in the Job's name -- which is what git holds once the layers read the
artifact. Each case below says which it runs over.

WHAT A PUSH IS HELD TO is read off the directory `flux` was given, by a
second reading that shares nothing with the script's: each render is parsed,
objects are paired, and every path at which a pair differs has to be an image
of one of the two names, that annotation, or the Job's name. Then the render
with the overlay is the same bytes over both trees.

THE CASES, and the part of the script each is the only reader of:

- both trees publish, with every image line at the digest given, every
  Deployment, CronJob and Job annotated and the Job named for the commit;
- a commit whose first characters read as a number still annotates with a
  string, which only the quotes in the overlay stand behind;
- an overlay that also changes a field, drops an object, moves a third
  image or renames an object that is not the Job is refused: the comparison
  of the two renders;
- an overlay that selects by the annotation annotates nothing over `bare`,
  one that leaves the Job's name alone, and one that leaves an image out,
  are each refused: the reading of the render with the overlay alone;
- a tree that names an image where no overlay writes, alone on its line or
  after an image whose name it begins, that carries the annotation with
  another value on a pod, that has a Job in `chuggy` or none in
  `chuggy-migrate`, or that lacks a directory, is refused; one that names
  only an image whose name begins with one of the two is published;
- a parameter that is not what its name says is refused before anything is
  read: an image name nothing runs, one with no repository, one that is not
  a name, the two the same, a digest or a commit that is not one;
- the version is `<seconds>.0.0` and is pushed only when the first number of
  every tag that could be a version is below it, as a number: an equal one,
  a later one, one with more digits, one with a `v`, a pre-release of the
  same second are each refused, and tags that are no version are not;
- a tag list the registry did not give whole -- an error, another body,
  another repository's, a link to a next page -- is refused, and a
  repository that does not exist yet, or lists nothing, has no tags;
- nothing is pushed, tagged or written as a result by any run that was
  refused, and a push that reports no digest writes no result.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import yaml

TASK = "publish-release"
STEP = "publish"
PIPELINE = "chuggy-release"
PIPELINE_TASK = "publish"
ANNOTATION = "fabric.chuggy.dev/source-commit"
SEMVER = re.compile(r"[1-9][0-9]*\.0\.0")

CHUGGY_URL = "https://chuggy.example.invalid/chuggy.git"
MANIFESTS_URL = "https://fabric.example.invalid/fabric.git"
MANIFESTS_COMMIT = "c" * 40
COMMIT = "f22d1b8b70070de0cb53dc2b628335b7a069d5f3"
API_DIGEST = "sha256:" + "1" * 64
CONSOLE_DIGEST = "sha256:" + "2" * 64
PUSHED_DIGEST = "sha256:" + "a" * 64
# Where `flux push artifact` makes the archive it pushes: the image sets no
# TMPDIR, and its root is read-only.
IMAGE_TMPDIR = "/tmp"
NOW = 1791239106

FAILURES = []


def refuse(message):
    raise SystemExit(f"release-publish: {message}")


def report(case, message):
    FAILURES.append(case)
    print(f"release-publish: {case}: {message}", file=sys.stderr)


def objects(text):
    return [document for document in yaml.safe_load_all(text) if document]


def one(documents, kind, name):
    found = [
        document
        for document in documents
        if document["kind"] == kind and document["metadata"]["name"] == name
    ]
    if len(found) != 1:
        refuse(f"the render holds {len(found)} {kind} {name}, not one")
    return found[0]


class Step:
    """The rendered step: its script, and its environment as a pod has it."""

    def __init__(self, rendered):
        documents = objects(Path(rendered).read_text())
        task = one(documents, "Task", TASK)
        steps = [step for step in task["spec"]["steps"] if step["name"] == STEP]
        if len(steps) != 1:
            refuse(f"Task {TASK} has {len(steps)} steps named {STEP}")
        self.step = steps[0]
        command = self.step.get("command")
        if not command or command[0] != "/bin/sh" or len(command) != 2:
            refuse(f"step {STEP} runs {command}, not /bin/sh over one script")
        mounts = {
            mount["mountPath"]: mount["name"] for mount in self.step["volumeMounts"]
        }
        if IMAGE_TMPDIR not in mounts:
            refuse(f"step {STEP} mounts nothing at {IMAGE_TMPDIR}, where its image makes the archive it pushes")
        directory, _, name = command[1].rpartition("/")
        volume = [
            volume
            for volume in task["spec"]["volumes"]
            if volume["name"] == mounts.get(directory)
        ]
        if len(volume) != 1 or "configMap" not in volume[0]:
            refuse(f"{command[1]} is not a file of a ConfigMap the step mounts")
        config = one(documents, "ConfigMap", volume[0]["configMap"]["name"])
        if config["metadata"].get("namespace") != task["metadata"].get("namespace"):
            refuse(f"ConfigMap {config['metadata']['name']} is not in the Task's namespace")
        if name not in config["data"]:
            refuse(f"ConfigMap {config['metadata']['name']} holds no {name}")
        self.script = config["data"][name]

        pipeline = one(documents, "Pipeline", PIPELINE)
        tasks = [
            task for task in pipeline["spec"]["tasks"] if task["name"] == PIPELINE_TASK
        ]
        if len(tasks) != 1 or tasks[0]["taskRef"]["name"] != TASK:
            refuse(f"Pipeline {PIPELINE} has no task {PIPELINE_TASK} of {TASK}")
        self.passed = {param["name"]: param["value"] for param in tasks[0]["params"]}
        declared = {param["name"] for param in task["spec"]["params"]}
        if declared != self.passed.keys():
            refuse(
                f"Task {TASK} declares {sorted(declared)} and the Pipeline passes "
                f"{sorted(self.passed)}"
            )

    def environment(self, case, run):
        """What the pod's container has, with this case's paths for the pod's."""

        def from_pipeline(match):
            reference = match.group(1)
            if reference not in run:
                refuse(f"the Pipeline passes $({reference}), which this suite does not stand in for")
            return run[reference]

        params = {
            name: re.sub(r"\$\(([^)]+)\)", from_pipeline, value)
            for name, value in self.passed.items()
        }

        def from_task(match):
            kind, _, rest = match.group(1).partition(".")
            if kind == "params" and rest in params:
                return params[rest]
            if kind == "results" and rest.endswith(".path"):
                return str(case / "results" / rest[: -len(".path")])
            refuse(f"step {STEP} reads $({match.group(1)}), which this suite does not stand in for")

        environment = {}
        for entry in self.step["env"]:
            if set(entry) != {"name", "value"}:
                refuse(f"step {STEP} takes {entry['name']} from a source this suite does not stand in for")
            written = entry["value"]
            if written == "/tmp" or written.startswith("/workspace/"):
                value = str(case / written.lstrip("/"))
            elif written.startswith("/"):
                refuse(f"step {STEP} is given the path {written}, which this suite does not stand in for")
            else:
                value = re.sub(r"\$\(([^)]+)\)", from_task, written)
            environment[entry["name"]] = value
        return environment


def executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def stand_ins(case):
    """`wget`, `flux` and `date`, each answering from a file the case writes."""
    programs = case / "bin"
    programs.mkdir()
    executable(
        programs / "wget",
        f"""#!{sys.executable}
import json, sys
argv = sys.argv[1:]
if argv[:3] != ["-q", "-S", "-O"] or len(argv) != 5:
    sys.exit(f"stand-in wget: not the call this suite answers: {{argv}}")
answer = json.load(open({str(case / 'registry.json')!r}))
open({str(case / 'wget.log')!r}, "a").write(argv[4] + "\\n")
reason = {{200: "OK", 404: "Not Found", 500: "Internal Server Error"}}[answer["status"]]
if answer["status"] is None:
    sys.exit("wget: bad address")
sys.stderr.write(f"  HTTP/1.1 {{answer['status']}} {{reason}}\\n  Content-Type: application/json\\n")
for line in answer.get("headers", []):
    sys.stderr.write(f"  {{line}}\\n")
sys.stderr.write("  \\n")
if answer["status"] != 200:
    sys.exit(f"wget: server returned error: HTTP/1.1 {{answer['status']}} {{reason}}")
open(argv[3], "w").write(answer["body"])
""",
    )
    executable(
        programs / "flux",
        f"""#!{sys.executable}
import json, shutil, sys
argv = sys.argv[1:]
open({str(case / 'flux.log')!r}, "a").write(json.dumps(argv) + "\\n")
if argv[:2] == ["push", "artifact"]:
    shutil.copytree(argv[argv.index("--path") + 1], {str(case / 'pushed')!r})
    reference = argv[2]
    repository, _, tag = reference[len("oci://"):].rpartition(":")
    digest = open({str(case / 'reported')!r}).read()
    print(json.dumps({{"url": f"oci://{{repository}}@{{digest}}", "repository": repository, "tag": tag, "digest": digest}}, indent=2))
elif argv[:2] != ["tag", "artifact"]:
    sys.exit(f"stand-in flux: not a call this suite answers: {{argv}}")
""",
    )
    executable(
        programs / "date",
        f"""#!{sys.executable}
import sys
if sys.argv[1:] != ["+%s"]:
    sys.exit(f"stand-in date: not the call this suite answers: {{sys.argv[1:]}}")
print(open({str(case / 'now')!r}).read().strip())
""",
    )
    return programs


def bare(tree):
    """Take out of a copy of the two directories what a release writes."""
    taken = {"digest": 0, "annotation": 0, "name": 0}
    for path in sorted(tree.rglob("*.yaml")):
        kept = []
        for line in path.read_text().splitlines():
            if re.fullmatch(rf"\s+{re.escape(ANNOTATION)}: \S+", line):
                taken["annotation"] += 1
                if kept and re.fullmatch(r"\s+annotations:", kept[-1]):
                    kept.pop()
                continue
            line, digests = re.subn(
                r"^(\s+(?:- )?image: registry\.chuggy\.internal/chuggy/(?:api|web))@sha256:[0-9a-f]{64}$",
                r"\1",
                line,
            )
            taken["digest"] += digests
            line, names = re.subn(
                r"^(  name: chuggy-migrate)-[0-9a-f]+-registry$", r"\1", line
            )
            taken["name"] += names
            kept.append(line)
        path.write_text("\n".join(kept) + "\n")
    if not all(taken.values()):
        refuse(f"the bare tree was made by taking out {taken}, so it is not bare")


def render(directory):
    return subprocess.run(
        ["kubectl", "kustomize", str(directory)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout


def differing(left, right, path=()):
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(left.keys() | right.keys()):
            if key not in left or key not in right:
                yield path + (key,)
            else:
                yield from differing(left[key], right[key], path + (key,))
    elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        for index, (one_left, one_right) in enumerate(zip(left, right)):
            yield from differing(one_left, one_right, path + (index,))
    elif left != right:
        yield path


def held(case, name, pushed, images, label):
    """The pushed directory, read without the script: what its overlays change
    and what they leave. Returns the render with the overlay, both directories."""
    whole = ""
    lines = {image: 0 for image in images}
    for directory in ("chuggy-migrate", "chuggy"):
        without = objects(render(pushed / "cluster" / directory))
        text = render(pushed / "release" / directory)
        whole += text
        with_overlay = objects(text)
        if len(without) != len(with_overlay):
            report(name, f"release/{directory} renders {len(with_overlay)} objects from {len(without)}")
            continue

        def identity(document):
            named = "" if document["kind"] == "Job" else document["metadata"]["name"]
            return (document["kind"], document["metadata"].get("namespace"), named)

        before = {identity(document): document for document in without}
        workloads = 0
        for document in with_overlay:
            original = before.get(identity(document))
            if original is None:
                report(name, f"release/{directory} renders {identity(document)}, which cluster/{directory} does not")
                continue
            metadata = document["metadata"]
            if document["kind"] in ("Deployment", "CronJob", "Job"):
                workloads += 1
                if metadata.get("annotations", {}).get(ANNOTATION) != label:
                    report(name, f"{document['kind']} {metadata['name']} is annotated {metadata.get('annotations')}")
            if document["kind"] == "Job" and metadata["name"] != f"chuggy-migrate-{label}-registry":
                report(name, f"the Job is named {metadata['name']}")
            for path in differing(original, document):
                if path in (
                    ("metadata", "annotations"),
                    ("metadata", "annotations", ANNOTATION),
                ):
                    continue
                if document["kind"] == "Job" and path == ("metadata", "name"):
                    continue
                if len(path) > 3 and path[-1] == "image" and path[-3] in ("containers", "initContainers"):
                    value = document
                    for key in path:
                        value = value[key]
                    image, _, digest = value.partition("@")
                    if images.get(image) == digest:
                        lines[image] += 1
                        continue
                report(name, f"{document['kind']} {metadata['name']} differs at {path}")
        if not workloads:
            report(name, f"release/{directory} renders nothing a release annotates")
        for image, digest in images.items():
            for line in text.splitlines():
                if re.search(rf"{re.escape(image)}(?![A-Za-z0-9._/-])", line) and not re.fullmatch(
                    rf"\s+(- )?image: {re.escape(image)}@{digest}", line
                ):
                    report(name, f"release/{directory} is left with {line.strip()}")
    for image, count in lines.items():
        if not count:
            report(name, f"no image line was written for {image}")
    return whole


class Suite:
    def __init__(self, rendered, cluster, busybox, work):
        self.step = Step(rendered)
        self.cluster = Path(cluster)
        self.busybox = Path(busybox)
        self.work = Path(work)
        self.kubectl = Path(shutil.which("kubectl")).parent

    def case(self, name, tree="pinned", commit=COMMIT, tags=None, registry=None, now=NOW, script=None, change=None, run=None, reported=PUSHED_DIGEST):
        """Lay one case out and run the step in it."""
        case = self.work / name
        (case / "results").mkdir(parents=True)
        (case / "tmp").mkdir()
        manifests = case / "workspace" / "manifests" / "cluster"
        manifests.mkdir(parents=True)
        for directory in ("chuggy-migrate", "chuggy"):
            shutil.copytree(self.cluster / directory, manifests / directory)
        for path in manifests.rglob("*"):
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        if tree == "bare":
            bare(manifests)
        if change:
            change(manifests)
        if registry is None:
            registry = (
                {"status": 404, "body": ""}
                if tags is None
                else {
                    "status": 200,
                    "body": json.dumps({"name": "chuggy/release", "tags": tags}) + "\n",
                }
            )
        (case / "registry.json").write_text(json.dumps(registry))
        (case / "now").write_text(str(now))
        (case / "reported").write_text(reported)
        programs = stand_ins(case)
        (case / "script").write_text(script or self.step.script)
        values = {
            "params.chuggy-url": CHUGGY_URL,
            "params.chuggy-commit": commit,
            "params.manifests-url": MANIFESTS_URL,
            "params.manifests-commit": MANIFESTS_COMMIT,
            "tasks.build-api.results.digest": API_DIGEST,
            "tasks.build-console.results.digest": CONSOLE_DIGEST,
            **(run or {}),
        }
        environment = self.step.environment(case, values)
        environment["PATH"] = f"{programs}:{self.busybox}:{self.kubectl}"
        completed = subprocess.run(
            [str(self.busybox / "sh"), str(case / "script")],
            env=environment,
            text=True,
            capture_output=True,
        )
        log = case / "flux.log"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return case, completed, calls, environment

    def published(self, name, **arguments):
        commit = arguments.get("commit", COMMIT)
        case, completed, calls, environment = self.case(name, **arguments)
        if completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
            return None
        version = f"{arguments.get('now', NOW)}.0.0"
        if not SEMVER.fullmatch(version):
            refuse(f"{version} is not a version the source selects by")
        release = environment["RELEASE"]
        expected = [
            [
                "push", "artifact", f"oci://{release}:{version}",
                "--path", str(case / "workspace" / "release" / "artifact"),
                "--source", CHUGGY_URL,
                "--revision", f"main@sha1:{commit}",
                "--reproducible", "--insecure-registry", "--output", "json",
            ],
            ["tag", "artifact", f"oci://{release}:{version}", "--tag", commit],
        ]
        if calls != expected:
            report(name, f"flux was called with {calls}, not {expected}")
            return None
        asked = (case / "wget.log").read_text().split()
        registry, _, repository = release.partition("/")
        if asked != [f"http://{registry}/v2/{repository}/tags/list"]:
            report(name, f"the tags were asked of {asked}")
        results = {path.name: path.read_text() for path in (case / "results").iterdir()}
        if results != {"version": version, "digest": PUSHED_DIGEST}:
            report(name, f"the results are {results}")
        images = {
            environment["API_IMAGE"]: API_DIGEST,
            environment["CONSOLE_IMAGE"]: CONSOLE_DIGEST,
        }
        return held(case, name, case / "pushed", images, commit[:8])

    def refused(self, name, said, **arguments):
        case, completed, calls, _ = self.case(name, **arguments)
        if completed.returncode == 0:
            report(name, "published, and it is a release this must refuse")
        elif said not in completed.stderr:
            report(name, f"was refused without saying `{said}`: {completed.stderr.strip()}")
        if calls:
            report(name, f"was refused after flux was called with {calls}")
        if any((case / "results").iterdir()):
            report(name, "was refused and wrote a result")

    def variant(self, old, new):
        """The script with one part of its overlay changed, to show that what
        reads the renders refuses what the overlay would then be."""
        if self.step.script.count(old) != 1:
            refuse(f"the script does not hold `{old}` once, so the variant is not one")
        return self.step.script.replace(old, new)


def edited(relative, old, new):
    def change(manifests):
        path = manifests / relative
        text = path.read_text()
        if text.count(old) < 1:
            refuse(f"{relative} does not hold `{old}`, so the case is not one")
        path.write_text(text.replace(old, new, 1))

    return change


def main():
    if len(sys.argv) != 5:
        refuse("usage: release-publish.py RENDERED_BUILD_SYSTEM CLUSTER BUSYBOX_BIN WORK")
    suite = Suite(*sys.argv[1:])

    pinned = suite.published("pinned")
    over_bare = suite.published("bare", tree="bare")
    if pinned is not None and over_bare is not None and pinned != over_bare:
        report("bare", "the release rendered from the bare tree is not the one rendered from the pinned tree")
    suite.published("tags-below", tags=[f"{NOW - 1}.0.0", "1.2.3", "9.0.0", "a" * 40, "latest", "2026.10.05"])
    suite.published("no-tags", registry={"status": 200, "body": '{"name":"chuggy/release","tags":null}\n'})
    suite.published("no-tags-as-a-list", registry={"status": 200, "body": '{"name":"chuggy/release","tags":[]}\n'})
    for commit in ("12345678" + "a" * 32, "1234e567" + "a" * 32, "00000000" + "a" * 32):
        suite.published(f"numeric-{commit[:8]}", tree="bare", commit=commit)

    annotation_patch = '  - target:\n      kind: (Deployment|CronJob|Job)\n'
    suite.refused(
        "overlay-changes-a-field",
        "the overlay changes more of cluster/chuggy than",
        script=suite.variant(
            annotation_patch,
            "  - target:\n      kind: Deployment\n      name: chuggy-ui\n"
            "    patch: |-\n      - op: add\n        path: /spec/revisionHistoryLimit\n        value: 7\n"
            + annotation_patch,
        ),
    )
    suite.refused(
        "overlay-drops-an-object",
        "the overlay changes more of cluster/chuggy than",
        script=suite.variant(
            annotation_patch,
            "  - target:\n      kind: Ingress\n      name: chuggy\n"
            "    patch: |-\n      \\$patch: delete\n      apiVersion: networking.k8s.io/v1\n"
            "      kind: Ingress\n      metadata:\n        name: chuggy\n"
            + annotation_patch,
        ),
    )
    suite.refused(
        "overlay-changes-another-image",
        "the overlay changes more of cluster/chuggy-migrate than",
        script=suite.variant("images:\n", 'images:\n  - name: postgres\n    newTag: "0"\n'),
    )
    # A NetworkPolicy, because nothing refers to one by name: kustomize rewrites
    # a reference to a renamed object, and the reference would then be what
    # the comparison saw. To a name that sorts where the old one did, because
    # kustomize orders a render by name and the object's new place would be.
    suite.refused(
        "overlay-renames-another-object",
        "the overlay changes more of cluster/chuggy than",
        script=suite.variant(
            annotation_patch,
            "  - target:\n      kind: NetworkPolicy\n      name: chuggy-pool-plane-egress\n"
            "    patch: |-\n      - op: replace\n        path: /metadata/name\n        value: chuggy-pool-plane-egress-renamed\n"
            + annotation_patch,
        ),
    )
    suite.refused(
        "overlay-selects-by-annotation",
        "carry 0 source-commit annotations",
        tree="bare",
        script=suite.variant(
            "      kind: (Deployment|CronJob|Job)\n",
            f"      annotationSelector: {ANNOTATION}\n",
        ),
    )
    suite.refused(
        "overlay-leaves-the-job-name",
        "its Job is named",
        script=suite.variant("        value: $job\n", "        value: chuggy-migrate\n"),
    )
    suite.refused(
        "overlay-leaves-an-image",
        "and is not an image line at",
        script=suite.variant("  - name: $CONSOLE_IMAGE\n    digest: $CONSOLE_DIGEST\n", ""),
    )

    passed = dict(suite.step.passed)
    stale = "registry.chuggy.internal/chuggy/api@sha256:" + "9" * 64
    suite.refused(
        "tree-names-the-image-in-a-value",
        "and is not an image line at",
        change=edited(
            "chuggy/chuggy-api.yaml",
            "          env:\n",
            f"          env:\n            - name: OWN_IMAGE\n              value: {stale}\n",
        ),
    )
    suite.refused(
        "tree-names-the-image-after-a-longer-name",
        "and is not an image line at",
        change=edited(
            "chuggy/chuggy-api.yaml",
            "          env:\n",
            f"          env:\n            - name: OWN_IMAGES\n              value: {passed['api-image']}-old {passed['api-image']}:latest\n",
        ),
    )
    suite.published(
        "tree-names-a-longer-named-image",
        change=edited(
            "chuggy/chuggy-api.yaml",
            "          env:\n",
            f"          env:\n            - name: ANOTHER_IMAGE\n              value: {passed['api-image']}-old:1\n",
        ),
    )
    suite.refused(
        "tree-annotates-a-pod",
        "an object is annotated",
        change=edited(
            "chuggy/chuggy-ui.yaml",
            "      labels: { app: chuggy-ui }\n    spec:",
            f"      labels: {{ app: chuggy-ui }}\n      annotations:\n        {ANNOTATION}: 0ld0ld0l\n    spec:",
        ),
    )
    suite.refused(
        "tree-has-a-job-in-chuggy",
        "it renders a Job this overlay does not name",
        change=edited(
            "chuggy/chuggy-ui.yaml",
            "---\n",
            "---\napiVersion: batch/v1\nkind: Job\nmetadata:\n  name: another\n  namespace: chuggy\n"
            "spec:\n  template:\n    spec:\n      restartPolicy: Never\n      containers:\n"
            "        - name: another\n          image: busybox\n---\n",
        ),
    )

    suite.refused(
        "tree-has-no-migration",
        "it renders 0 Jobs, not the one migration",
        change=edited("chuggy-migrate/chuggy-migrate.yaml", "kind: Job\n", "kind: CronJob\n"),
    )

    def without_migration(manifests):
        shutil.rmtree(manifests / "chuggy-migrate")

    suite.refused(
        "tree-lacks-a-directory",
        "carries no cluster/chuggy-migrate/kustomization.yaml",
        change=without_migration,
    )

    for case, given, said in (
        ("api-image-nothing-runs", {"api-image": passed["api-image"] + "-renamed"}, "nothing in the release runs"),
        ("console-image-nothing-runs", {"console-image": passed["console-image"] + "-renamed"}, "nothing in the release runs"),
        ("image-is-no-repository", {"console-image": "web"}, "web names no repository under a registry"),
        ("image-is-not-a-name", {"api-image": passed["api-image"] + " "}, "is not a registry and a repository"),
        ("images-are-one", {"console-image": passed["api-image"]}, "the two images have one name"),
        ("release-is-no-repository", {"release": "release"}, "release names no repository under a registry"),
    ):
        suite.step.passed = {**passed, **given}
        suite.refused(case, said)
    suite.step.passed = passed
    for case, digest in (
        ("digest-is-short", "sha256:" + "1" * 63),
        ("digest-is-not-hex", "sha256:" + "g" * 64),
        ("digest-has-no-algorithm", "1" * 64),
    ):
        suite.refused(case, "is not an image digest", run={"tasks.build-console.results.digest": digest})
    suite.refused("commit-is-not-whole", "is not a full commit hash", commit=COMMIT[:39])
    suite.refused("commit-is-not-a-hash", "is not a commit hash", commit="g" * 40)

    above = "is not above every version"
    suite.refused("version-tied", above, tags=[f"{NOW}.0.0"])
    suite.refused("version-behind", above, tags=["1.0.0", f"{NOW + 3600}.0.0", "a" * 40])
    suite.refused("version-tied-with-a-v", above, tags=[f"v{NOW}.0.0"])
    suite.refused("version-tied-with-a-prerelease", above, tags=[f"{NOW}.0.0-rc.1"])
    suite.refused("version-below-a-minor", above, tags=[f"{NOW}.1.0"])
    suite.refused("version-far-behind", above, tags=["1000000000000000.0.0"])
    suite.refused("registry-fails", "did not list the tags", registry={"status": 500, "body": ""})
    suite.refused("registry-unreachable", "did not list the tags", registry={"status": None, "body": ""})
    suite.refused(
        "registry-answers-something-else",
        "answered the tag list",
        registry={"status": 200, "body": '{"errors":[]}\n'},
    )
    suite.refused(
        "registry-lists-another-repository",
        "answered the tag list",
        registry={"status": 200, "body": json.dumps({"name": "chuggy/api", "tags": [f"{NOW + 9}.0.0"]})},
    )
    suite.refused(
        "registry-lists-a-page",
        "a link to the rest",
        registry={
            "status": 200,
            "headers": ['Link: </v2/chuggy/release/tags/list?last=x&n=1>; rel="next"'],
            "body": json.dumps({"name": "chuggy/release", "tags": ["1.0.0"]}),
        },
    )

    case, completed, calls, _ = suite.case("flux-reports-no-digest", reported="")
    if completed.returncode == 0 or "reported no digest" not in completed.stderr:
        report("flux-reports-no-digest", f"exited {completed.returncode}: {completed.stderr.strip()}")
    if [call[:2] for call in calls] != [["push", "artifact"]] or any((case / "results").iterdir()):
        report("flux-reports-no-digest", f"went on after a push with no digest: {calls}")

    if FAILURES:
        raise SystemExit(f"release-publish: {len(FAILURES)} failed: {', '.join(FAILURES)}")


if __name__ == "__main__":
    main()
