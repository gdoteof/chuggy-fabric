#!/usr/bin/env python3
"""Run the site pipeline's `publish` step as its pod is given it, over this
tree's own site layer, and hold what it would push.

THE RELEASE PUBLISH SUITE OVER ONE DIRECTORY AND ONE IMAGE. What is rendered
and what is this suite's is as release-publish.py has it: the script is the
bytes of the ConfigMap the rendered step mounts, run by the step's own
`command` under a BusyBox shell, with the step's environment and each
`$(params.…)` resolved the way the rendered Pipeline resolves it; `kubectl`
is the real one; `wget`, `flux` and `date` are stood in for, each answering
from a file the case writes.

THE TWO TREES. `git` is cluster/chug-gy as this commit carries it, which
names no release: its image line carries the digest of sixty-four zeroes and
its Deployment has no `annotations` key. `pinned` is the same with a release
written in by hand, another digest on the image line and the source-commit
annotation, which the overlay overrides without a word.

WHAT A PUSH IS HELD TO is read off the directory `flux` was given by a second
reading that shares nothing with the script's: the two renders are parsed,
objects are paired, and every path at which a pair differs has to be the
image line at the digest given or that annotation. Then the render with the
overlay is the same bytes over both trees.

THE CASES, and the part of the script each is the only reader of:

- both trees publish, with the image line at the digest given and the
  Deployment annotated with the commit's first eight characters, quoted;
- an overlay that also changes a field or drops an object is refused: the
  comparison of the two renders; one that selects by the annotation
  annotates nothing, and one that leaves the image out, are refused: the
  reading of the render with the overlay alone;
- a tree that names the image where no overlay writes, that carries the
  annotation with another value on a pod, or that lacks the layer, is
  refused; one that names only an image whose name begins with it is
  published;
- a parameter that is not what its name says is refused before anything is
  read: an image nothing runs, one with no repository, one that is not a
  name, a layer that is not a directory's name, a digest or a commit that
  is not one;
- the version is `<seconds>.0.0` and is pushed only above every tag that
  could be a version, read from a tag list given whole; and nothing is
  pushed, tagged or written as a result by a run that was refused.
"""

import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import yaml

TASK = "publish-site"
STEP = "publish"
PIPELINE = "chug-gy-site"
PIPELINE_TASK = "publish"
LAYER = "chug-gy"
ANNOTATION = "fabric.chuggy.dev/source-commit"
SEMVER = re.compile(r"[1-9][0-9]*\.0\.0")

SITE_URL = "https://site.example.invalid/site.git"
MANIFESTS_URL = "https://fabric.example.invalid/fabric.git"
MANIFESTS_COMMIT = "c" * 40
COMMIT = "f22d1b8b70070de0cb53dc2b628335b7a069d5f3"
DIGEST = "sha256:" + "1" * 64
PUSHED_DIGEST = "sha256:" + "a" * 64
STALE_DIGEST = "sha256:" + "9" * 64
STALE_LABEL = "0ld0ld0l"
IMAGE_TMPDIR = "/tmp"
NOW = 1791239106

FAILURES = []


def refuse(message):
    raise SystemExit(f"site-publish: {message}")


def report(case, message):
    FAILURES.append(case)
    print(f"site-publish: {case}: {message}", file=sys.stderr)


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
        mounts = {mount["mountPath"]: mount["name"] for mount in self.step["volumeMounts"]}
        if IMAGE_TMPDIR not in mounts:
            refuse(f"step {STEP} mounts nothing at {IMAGE_TMPDIR}, where its image makes the archive it pushes")
        directory, _, name = command[1].rpartition("/")
        volume = [volume for volume in task["spec"]["volumes"] if volume["name"] == mounts.get(directory)]
        if len(volume) != 1 or "configMap" not in volume[0]:
            refuse(f"{command[1]} is not a file of a ConfigMap the step mounts")
        config = one(documents, "ConfigMap", volume[0]["configMap"]["name"])
        if config["metadata"].get("namespace") != task["metadata"].get("namespace"):
            refuse(f"ConfigMap {config['metadata']['name']} is not in the Task's namespace")
        if name not in config["data"]:
            refuse(f"ConfigMap {config['metadata']['name']} holds no {name}")
        self.script = config["data"][name]

        pipeline = one(documents, "Pipeline", PIPELINE)
        tasks = [task for task in pipeline["spec"]["tasks"] if task["name"] == PIPELINE_TASK]
        if len(tasks) != 1 or tasks[0]["taskRef"]["name"] != TASK:
            refuse(f"Pipeline {PIPELINE} has no task {PIPELINE_TASK} of {TASK}")
        self.passed = {param["name"]: param["value"] for param in tasks[0]["params"]}
        declared = {param["name"] for param in task["spec"]["params"]}
        if declared != self.passed.keys():
            refuse(f"Task {TASK} declares {sorted(declared)} and the Pipeline passes {sorted(self.passed)}")
        if self.passed.get("layer") != LAYER:
            refuse(f"the Pipeline publishes the layer {self.passed.get('layer')!r}, and this suite runs over cluster/{LAYER}")

    def environment(self, case, run):
        def from_pipeline(match):
            reference = match.group(1)
            if reference not in run:
                refuse(f"the Pipeline passes $({reference}), which this suite does not stand in for")
            return run[reference]

        params = {name: re.sub(r"\$\(([^)]+)\)", from_pipeline, value) for name, value in self.passed.items()}

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


def render(directory):
    return subprocess.run(["kubectl", "kustomize", str(directory)], check=True, text=True, stdout=subprocess.PIPE).stdout


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


def held(name, pushed, image, digest, label):
    """The pushed directory, read without the script. Returns the render with
    the overlay."""
    without = objects(render(pushed / "cluster" / LAYER))
    text = render(pushed / "release" / LAYER)
    with_overlay = objects(text)
    if len(without) != len(with_overlay):
        report(name, f"release/{LAYER} renders {len(with_overlay)} objects from {len(without)}")
        return text

    def identity(document):
        return (document["kind"], document["metadata"].get("namespace"), document["metadata"]["name"])

    before = {identity(document): document for document in without}
    lines = deployments = 0
    for document in with_overlay:
        original = before.get(identity(document))
        if original is None:
            report(name, f"release/{LAYER} renders {identity(document)}, which cluster/{LAYER} does not")
            continue
        metadata = document["metadata"]
        if document["kind"] == "Deployment":
            deployments += 1
            if metadata.get("annotations", {}).get(ANNOTATION) != label:
                report(name, f"Deployment {metadata['name']} is annotated {metadata.get('annotations')}")
        for path in differing(original, document):
            if path in (("metadata", "annotations"), ("metadata", "annotations", ANNOTATION)):
                continue
            if len(path) > 3 and path[-1] == "image" and path[-3] in ("containers", "initContainers"):
                value = document
                for key in path:
                    value = value[key]
                if value == f"{image}@{digest}":
                    lines += 1
                    continue
            report(name, f"{document['kind']} {metadata['name']} differs at {path}")
    if not deployments:
        report(name, f"release/{LAYER} renders no Deployment to annotate")
    if not lines:
        report(name, f"no image line was written for {image}")
    for line in text.splitlines():
        if re.search(rf"{re.escape(image)}(?![A-Za-z0-9._/-])", line) and not re.fullmatch(
            rf"\s+(- )?image: {re.escape(image)}@{digest}", line
        ):
            report(name, f"release/{LAYER} is left with {line.strip()}")
    return text


def pinned(image):
    """Write a release into the layer by hand: another digest on the image
    line, and the annotation on the Deployment."""

    def change(manifests):
        written = {"digest": 0, "annotation": 0}
        for path in sorted((manifests / LAYER).rglob("*.yaml")):
            text = path.read_text()
            text, digests = re.subn(
                rf"^(\s+(?:- )?image: {re.escape(image)})@sha256:0{{64}}$", rf"\1@{STALE_DIGEST}", text, flags=re.MULTILINE
            )
            text, annotations = re.subn(
                r"^(kind: Deployment\nmetadata:\n)", rf"\1  annotations:\n    {ANNOTATION}: {STALE_LABEL}\n", text, flags=re.MULTILINE
            )
            written["digest"] += digests
            written["annotation"] += annotations
            path.write_text(text)
        if not all(written.values()):
            refuse(f"the pinned tree was made by writing {written}, so it does not name a release")

    return change


def documents_changed(mutate):
    """A change to the layer made over its parsed documents, written back."""

    def change(manifests):
        for path in sorted((manifests / LAYER).rglob("*.yaml")):
            if path.name == "kustomization.yaml":
                continue
            documents = objects(path.read_text())
            mutate(documents)
            path.write_text("---\n".join(yaml.safe_dump(document, sort_keys=False) for document in documents))

    return change


def edited(relative, old, new):
    def change(manifests):
        path = manifests / relative
        text = path.read_text()
        if text.count(old) < 1:
            refuse(f"{relative} does not hold `{old}`, so the case is not one")
        path.write_text(text.replace(old, new, 1))

    return change


class Suite:
    def __init__(self, rendered, cluster, busybox, work):
        self.step = Step(rendered)
        self.cluster = Path(cluster)
        self.busybox = Path(busybox)
        self.work = Path(work)
        self.kubectl = Path(shutil.which("kubectl")).parent

    def case(self, name, commit=COMMIT, tags=None, registry=None, now=NOW, script=None, change=None, run=None, reported=PUSHED_DIGEST):
        case = self.work / name
        (case / "results").mkdir(parents=True)
        (case / "tmp").mkdir()
        manifests = case / "workspace" / "manifests" / "cluster"
        manifests.mkdir(parents=True)
        shutil.copytree(self.cluster / LAYER, manifests / LAYER)
        for path in manifests.rglob("*"):
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        if change:
            change(manifests)
        if registry is None:
            registry = (
                {"status": 404, "body": ""}
                if tags is None
                else {"status": 200, "body": json.dumps({"name": "chug-gy/release", "tags": tags}) + "\n"}
            )
        (case / "registry.json").write_text(json.dumps(registry))
        (case / "now").write_text(str(now))
        (case / "reported").write_text(reported)
        programs = stand_ins(case)
        (case / "script").write_text(script or self.step.script)
        values = {
            "params.site-url": SITE_URL,
            "params.site-commit": commit,
            "params.manifests-url": MANIFESTS_URL,
            "params.manifests-commit": MANIFESTS_COMMIT,
            "tasks.build.results.digest": DIGEST,
            **(run or {}),
        }
        environment = self.step.environment(case, values)
        environment["PATH"] = f"{programs}:{self.busybox}:{self.kubectl}"
        completed = subprocess.run([str(self.busybox / "sh"), str(case / "script")], env=environment, text=True, capture_output=True)
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
                "--source", SITE_URL,
                "--revision", f"main@sha1:{commit}",
                "--reproducible", "--output", "json",
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
        return held(name, case / "pushed", environment["IMAGE"], environment["DIGEST"], commit[:8])

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
        if self.step.script.count(old) != 1:
            refuse(f"the script does not hold `{old}` once, so the variant is not one")
        return self.step.script.replace(old, new)


def main():
    if len(sys.argv) != 5:
        refuse("usage: site-publish.py RENDERED_BUILD_SYSTEM CLUSTER BUSYBOX_BIN WORK")
    suite = Suite(*sys.argv[1:])
    passed = dict(suite.step.passed)
    image = passed["image"]

    over_git = suite.published("git")
    over_pinned = suite.published("pinned", change=pinned(image))
    if over_git is not None and over_pinned is not None and over_git != over_pinned:
        report("pinned", "the release rendered from a tree that names one is not the one rendered from git's")
    suite.published("tags-below", tags=[f"{NOW - 1}.0.0", "1.2.3", "9.0.0", "a" * 40, "latest", "2026.10.05"])
    suite.published("no-tags", registry={"status": 200, "body": '{"name":"chug-gy/release","tags":null}\n'})
    suite.published("no-tags-as-a-list", registry={"status": 200, "body": '{"name":"chug-gy/release","tags":[]}\n'})
    for commit in ("12345678" + "a" * 32, "1234e567" + "a" * 32, "00000000" + "a" * 32):
        suite.published(f"numeric-{commit[:8]}", commit=commit)

    annotation_patch = "  - target:\n      kind: Deployment\n"
    suite.refused(
        "overlay-changes-a-field",
        f"the overlay changes more of cluster/{LAYER} than",
        script=suite.variant(
            annotation_patch,
            "  - target:\n      kind: Deployment\n"
            "    patch: |-\n      - op: add\n        path: /spec/revisionHistoryLimit\n        value: 7\n"
            + annotation_patch,
        ),
    )
    suite.refused(
        "overlay-drops-an-object",
        f"the overlay changes more of cluster/{LAYER} than",
        script=suite.variant(
            annotation_patch,
            "  - target:\n      kind: Ingress\n"
            "    patch: |-\n      \\$patch: delete\n      apiVersion: networking.k8s.io/v1\n"
            "      kind: Ingress\n      metadata:\n        name: chug-gy\n"
            + annotation_patch,
        ),
    )
    suite.refused(
        "overlay-selects-by-annotation",
        "carry 0 source-commit annotations",
        script=suite.variant("      kind: Deployment\n", f"      annotationSelector: {ANNOTATION}\n"),
    )
    suite.refused(
        "overlay-leaves-the-image",
        "and is not an image line at",
        script=suite.variant("images:\n  - name: $IMAGE\n    digest: $DIGEST\n", ""),
    )

    def naming(value):
        def mutate(documents):
            for document in documents:
                if document["kind"] == "Deployment":
                    container = document["spec"]["template"]["spec"]["containers"][0]
                    container.setdefault("env", []).append({"name": "ANOTHER", "value": value})

        return documents_changed(mutate)

    suite.refused("tree-names-the-image-in-a-value", "and is not an image line at", change=naming(f"{image}@{STALE_DIGEST}"))
    suite.refused("tree-names-the-image-after-a-longer-name", "and is not an image line at", change=naming(f"{image}-old {image}:latest"))
    suite.published("tree-names-a-longer-named-image", change=naming(f"{image}-old:1"))

    def annotating_the_pod(documents):
        for document in documents:
            if document["kind"] == "Deployment":
                document["spec"]["template"]["metadata"].setdefault("annotations", {})[ANNOTATION] = STALE_LABEL

    suite.refused("tree-annotates-a-pod", "an object is annotated", change=documents_changed(annotating_the_pod))

    def without_layer(manifests):
        shutil.rmtree(manifests / LAYER)

    suite.refused("tree-lacks-the-layer", f"carries no cluster/{LAYER}/kustomization.yaml", change=without_layer)

    for case, given, said in (
        ("image-nothing-runs", {"image": image + "-renamed"}, f"nothing in cluster/{LAYER} runs"),
        ("image-is-no-repository", {"image": "web"}, "web names no repository under a registry"),
        ("image-is-not-a-name", {"image": image + " "}, "is not a registry and a repository"),
        ("release-is-no-repository", {"release": "release"}, "release names no repository under a registry"),
        ("layer-is-not-a-name", {"layer": "Chug Gy"}, "is not the name of a directory"),
        ("layer-is-another-directory", {"layer": "nowhere"}, "carries no cluster/nowhere/kustomization.yaml"),
    ):
        suite.step.passed = {**passed, **given}
        suite.refused(case, said)
    suite.step.passed = passed
    for case, digest in (
        ("digest-is-short", "sha256:" + "1" * 63),
        ("digest-is-not-hex", "sha256:" + "g" * 64),
        ("digest-has-no-algorithm", "1" * 64),
    ):
        suite.refused(case, "is not an image digest", run={"tasks.build.results.digest": digest})
    suite.refused("commit-is-not-whole", "is not a full commit hash", commit=COMMIT[:39])
    suite.refused("commit-is-not-a-hash", "is not a commit hash", commit="g" * 40)

    above = "is not above every version"
    suite.refused("version-tied", above, tags=[f"{NOW}.0.0"])
    suite.refused("version-behind", above, tags=["1.0.0", f"{NOW + 3600}.0.0", "a" * 40])
    suite.refused("version-tied-with-a-v", above, tags=[f"v{NOW}.0.0"])
    suite.refused("version-tied-with-a-prerelease", above, tags=[f"{NOW}.0.0-rc.1"])
    suite.refused("registry-fails", "did not list the tags", registry={"status": 500, "body": ""})
    suite.refused("registry-unreachable", "did not list the tags", registry={"status": None, "body": ""})
    suite.refused("registry-answers-something-else", "answered the tag list", registry={"status": 200, "body": '{"errors":[]}\n'})
    suite.refused(
        "registry-lists-another-repository",
        "answered the tag list",
        registry={"status": 200, "body": json.dumps({"name": "chuggy/release", "tags": [f"{NOW + 9}.0.0"]})},
    )
    suite.refused(
        "registry-lists-a-page",
        "a link to the rest",
        registry={
            "status": 200,
            "headers": ['Link: </v2/chug-gy/release/tags/list?last=x&n=1>; rel="next"'],
            "body": json.dumps({"name": "chug-gy/release", "tags": ["1.0.0"]}),
        },
    )

    case, completed, calls, _ = suite.case("flux-reports-no-digest", reported="")
    if completed.returncode == 0 or "reported no digest" not in completed.stderr:
        report("flux-reports-no-digest", f"exited {completed.returncode}: {completed.stderr.strip()}")
    if [call[:2] for call in calls] != [["push", "artifact"]] or any((case / "results").iterdir()):
        report("flux-reports-no-digest", f"went on after a push with no digest: {calls}")

    if FAILURES:
        raise SystemExit(f"site-publish: {len(FAILURES)} failed: {', '.join(FAILURES)}")


if __name__ == "__main__":
    main()
