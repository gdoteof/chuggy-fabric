#!/usr/bin/env python3
"""Run the `fetch` and `build` steps as their pods are given them, against a
repository that is a directory and a registry that is a file, and the `build`
and `index` steps of `build-two-platform-image` as worker-image-run.yaml's pod
is given them.

WHAT IS RENDERED AND WHAT IS THIS SUITE'S. Each script is the bytes of the
ConfigMap the rendered step mounts, run by that step's own `command` under a
BusyBox shell, which is what the step's image has. Its environment is the
step's, with each `$(params.…)` resolved as the rendered Pipeline passes it to
`build-api`, a path of the pod's put under the case's own directory, and
`TMPDIR` as the BuildKit image sets it, which has to be a directory the step
mounts because the root is read-only. `git` is the real one, against a
repository this suite commits to and serves from a directory. Two programs
are stood in for, because the build has neither: `wget`, which answers each
question about a tag in the form the image's BusyBox prints one, in the order
the case lists; and `buildctl-daemonless.sh`, which keeps what it was called
with and writes the metadata file BuildKit writes. A build of two platforms
stands in for `buildctl` as well, which writes the archive the Mac sends back,
and the two wait for each other, so a script that ran them one after the other
fails. `index` stands in for `regctl`, which answers each call the script
makes from the case and refuses any other.

A reference this does not know how to resolve is refused rather than skipped:
it is one the pod would have and this run would not.

`publish-release` fetches with the same file under the same three names, which
is held, so the fetch cases stand for both.

THE CASES, and the part of a script each is the only reader of.

fetch.sh:

- the tip of a branch and a commit that is no branch's tip are each checked
  out, alone, with no history behind them;
- a branch's name, a branch whose name is made of the digits of a hash, and a
  hash cut short are each refused before anything is fetched: the two tests of
  the parameter, the second of which is all that keeps the second of those a
  refusal by name;
- the hash of an annotated tag is fetched and is refused after the checkout,
  because what git checked out is the commit the tag names: the test of what
  git wrote;
- a hash the repository does not have, and a repository that is not there,
  fail, and nothing says the commit is in the directory.

build.sh:

- a tag the registry serves is the result and BuildKit is not run, whatever
  case the registry writes the header in, with or without a carriage return,
  and after a redirect;
- a tag it does not have is built, by one call that is held whole -- the
  output, the cache's own reference in and out, plain HTTP in all three, the
  platform, the context and the Dockerfile's directory -- and the result is the
  digest read back, with no newline after it;
- a registry that answers an error, or does not answer, is not one that lacks
  the tag: nothing is built and nothing is written;
- a tag served with no digest is refused rather than built;
- after a build, a registry that serves another digest under the tag, none, or
  an error, is refused, and so is a build that reports no digest or fails
  after it pushed;
- `target` is passed when the run names a stage and not otherwise;
- an image that is no registry and repository, a commit that is no full hash,
  a context or a Dockerfile the commit does not have, are each refused before
  the registry is asked or BuildKit is run.

build.sh, for two platforms:

- a tag the registry serves is left for `index` and neither half is built;
- a tag it does not have is built twice at once, each call held whole -- the
  amd64 half pushed by digest alone with the cache as one platform has it, the
  arm64 half sent to the run's daemon with the three files it is spoken to
  with and the daemon's address as the certificate's name, and written back
  as an archive -- and each half's digest is left for `index`, the result not
  written, each half's lines on either stream headed by its platform;
- `target` is passed to both when the run names a stage;
- either half failing, or reporting no digest, is refused, with no digest
  left;
- no daemon, a daemon that is not a tcp:// address with a port, and a missing
  file to speak to it with, are refused before the registry is asked.

index.sh:

- a served tag that is an index of linux/amd64 and linux/arm64, each entry
  one image of its platform, is the result, after the build above, and
  nothing is pushed; one that is one image, an index of other platforms, or
  one with an entry that is an index or an image of the other platform, is
  refused and nothing is pushed;
- after the build above, the archive is pushed under its half's digest, each
  half is held to being one image of its platform, the index of the two is
  pushed under the tag, and the result is the digest the registry serves
  under it, each call held whole;
- a half that is an index, or an image of the other platform, is refused
  before the tag is pushed;
- a registry that serves another index under the tag, or none, or one that
  lists other than the two halves, is refused, and so is a push that reports
  no digest;
- a half with no digest or one that is not a digest, and a missing archive,
  are refused before regctl is run, and a failed import before the tag is
  pushed.
"""

import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import yaml

TASK = "build-image"
TWO_PLATFORM_TASK = "build-two-platform-image"
PIPELINE = "chuggy-release"
PIPELINE_TASK = "build-api"
OTHER_FETCH = ("publish-release", "fetch")
# What `docker run --entrypoint env` prints for the image both steps run.
IMAGE_TMPDIR = "/home/user/.local/tmp"

COMMIT = "f22d1b8b70070de0cb53dc2b628335b7a069d5f3"
SERVED = "sha256:" + "3" * 64
BUILT = "sha256:2c6e48db34e5db3148f0bf2646be91e02416d7a8829820e7fe672d9216b58c77"
OTHER = "sha256:" + "4" * 64
ACCEPT = (
    "Accept: application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)

# The file BuildKit v0.26.2 wrote for a build this repository's pipeline made
# of a two-line Dockerfile, with nothing changed but the image's name. It
# carries four digests and the image's is one of them.
METADATA = """{
  "cache.manifest": "{\\"mediaType\\":\\"application/vnd.oci.image.manifest.v1+json\\",\\"digest\\":\\"sha256:b16856b152213ebe38812fbe57fca35f1506cd65de449d13f0e2b50ebc1aade1\\",\\"size\\":1232}",
  "containerimage.config.digest": "sha256:62ef512471055f54add464082f04d22d6f495a265b5ce71d284f5d65f4c434e9",
  "containerimage.descriptor": {
    "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
    "digest": "sha256:2c6e48db34e5db3148f0bf2646be91e02416d7a8829820e7fe672d9216b58c77",
    "size": 890,
    "platform": {
      "architecture": "amd64",
      "os": "linux"
    }
  },
  "containerimage.digest": "sha256:2c6e48db34e5db3148f0bf2646be91e02416d7a8829820e7fe672d9216b58c77",
  "image.name": "registry.example.invalid:5000/chuggy/api:f22d1b8b70070de0cb53dc2b628335b7a069d5f3"
}"""

AMD64 = "sha256:" + "a" * 64
ARM64 = "sha256:" + "b" * 64
INDEXED = "sha256:" + "c" * 64
# What index.sh asks regctl, by `--format`: a manifest's media type, an
# image's platform, an index's entries, and the digest of an index it pushed.
KIND = "{{ .GetDescriptor.MediaType }}"
CONFIG = "{{ .OS }}/{{ .Architecture }}"
LISTING = "{{ range .Manifests }}{{ .Platform.OS }}/{{ .Platform.Architecture }} {{ .Digest }}{{ println }}{{ end }}"
PUSHED = "{{ .Manifest.GetDescriptor.Digest }}"
OCI_IMAGE = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
# How long a half waits for the other to start before it says they were not
# run at once: a bound on a hang, not on a build.
RENDEZVOUS_SECONDS = 60

FAILURES = []


def refuse(message):
    raise SystemExit(f"release-build: {message}")


def report(case, message):
    FAILURES.append(case)
    print(f"release-build: {case}: {message}", file=sys.stderr)


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
    """One rendered step: its script, and its environment as a pod has it."""

    def __init__(self, documents, task_name, step_name):
        self.name = f"Task {task_name} step {step_name}"
        self.task = one(documents, "Task", task_name)
        steps = [step for step in self.task["spec"]["steps"] if step["name"] == step_name]
        if len(steps) != 1:
            refuse(f"Task {task_name} has {len(steps)} steps named {step_name}")
        self.step = steps[0]
        command = self.step.get("command")
        if not command or command[0] != "/bin/sh" or len(command) != 2:
            refuse(f"{self.name} runs {command}, not /bin/sh over one script")
        self.mounts = {mount["mountPath"]: mount["name"] for mount in self.step["volumeMounts"]}
        directory, _, self.file = command[1].rpartition("/")
        volume = [
            volume
            for volume in self.task["spec"]["volumes"]
            if volume["name"] == self.mounts.get(directory)
        ]
        if len(volume) != 1 or "configMap" not in volume[0]:
            refuse(f"{command[1]} is not a file of a ConfigMap {self.name} mounts")
        config = one(documents, "ConfigMap", volume[0]["configMap"]["name"])
        if config["metadata"].get("namespace") != self.task["metadata"].get("namespace"):
            refuse(f"ConfigMap {config['metadata']['name']} is not in the Task's namespace")
        if self.file not in config["data"]:
            refuse(f"ConfigMap {config['metadata']['name']} holds no {self.file}")
        self.config = config["metadata"]["name"]
        self.script = config["data"][self.file]

    def environment(self, root, params):
        """What the pod's container has, with each of the pod's paths under
        `root`."""

        def resolved(match):
            kind, _, rest = match.group(1).partition(".")
            if kind == "params" and rest in params:
                return params[rest]
            if kind == "results" and rest.endswith(".path"):
                return f"/tekton/results/{rest[: -len('.path')]}"
            refuse(f"{self.name} reads $({match.group(1)}), which this suite does not stand in for")

        environment = {}
        for entry in self.step["env"]:
            if set(entry) != {"name", "value"}:
                refuse(f"{self.name} takes {entry['name']} from a source this suite does not stand in for")
            value = re.sub(r"\$\(([^)]+)\)", resolved, entry["value"])
            environment[entry["name"]] = str(root / value.lstrip("/")) if value.startswith("/") else value
        return environment


def executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def answer(status, headers=()):
    return {"status": status, "headers": list(headers)}


def has(digest, name="Docker-Content-Digest", end=""):
    """A 200 in the lines the image's BusyBox printed for a tag the registry
    serves, with the digest's header written as the case says."""
    return answer(
        200,
        [
            "Content-Length: 890" + end,
            "Content-Type: application/vnd.docker.distribution.manifest.v2+json" + end,
            f"{name}: {digest}{end}",
            "Docker-Distribution-Api-Version: registry/2.0" + end,
            f'Etag: "{digest}"{end}',
            "Connection: close" + end,
        ],
    )


ABSENT = answer(404)
REDIRECT = answer(307, ["Location: http://registry.example.invalid:5000/elsewhere"])


def stand_ins(case):
    """`wget` and `buildctl-daemonless.sh`, each answering from a file the case
    writes and keeping what it was asked."""
    programs = case / "bin"
    programs.mkdir()
    wget(programs, case)
    executable(
        programs / "buildctl-daemonless.sh",
        f"""#!{sys.executable}
import json, sys
argv = sys.argv[1:]
open({str(case / 'buildctl.log')!r}, "a").write(json.dumps(argv) + "\\n")
build = json.load(open({str(case / 'build.json')!r}))
if build["metadata"] is not None and "--metadata-file" in argv:
    open(argv[argv.index("--metadata-file") + 1], "w").write(build["metadata"])
sys.exit(build["exit"])
""",
    )
    return programs


def wget(programs, case):
    executable(
        programs / "wget",
        f"""#!{sys.executable}
import json, sys
argv = sys.argv[1:]
if argv[:4] != ["-q", "-S", "--spider", "--header"] or len(argv) != 6:
    sys.exit(f"stand-in wget: not the call this suite answers: {{argv}}")
log = {str(case / 'wget.log')!r}
open(log, "a").write(json.dumps(argv[4:]) + "\\n")
asked = len(open(log).read().splitlines())
answers = json.load(open({str(case / 'registry.json')!r}))
if asked > len(answers):
    sys.exit("stand-in wget: asked once more than this case answers")
reasons = {{200: "OK", 307: "Temporary Redirect", 404: "Not Found", 500: "Internal Server Error"}}
for reply in answers[asked - 1]:
    if reply["status"] is None:
        sys.exit("wget: can't connect to remote host (10.43.0.1): Connection refused")
    line = f"HTTP/1.1 {{reply['status']}} {{reasons[reply['status']]}}"
    sys.stderr.write(f"  {{line}}\\n")
    if reply["status"] >= 400:
        sys.exit(f"wget: server returned error: {{line}}")
    for header in reply["headers"]:
        sys.stderr.write(f"  {{header}}\\n")
    sys.stderr.write("  \\n")
""",
    )


def two_platform_stand_ins(case):
    """`buildctl-daemonless.sh` and `buildctl`, which meet before either
    answers, and `regctl`, each answering from a file the case writes and
    keeping what it was asked."""
    programs = case / "bin"
    programs.mkdir()
    wget(programs, case)
    for program, platform in (("buildctl-daemonless.sh", "amd64"), ("buildctl", "arm64")):
        other = "arm64" if platform == "amd64" else "amd64"
        executable(
            programs / program,
            f"""#!{sys.executable}
import json, os, sys, time
argv = sys.argv[1:]
open({str(case / (platform + '.log'))!r}, "a").write(json.dumps(argv) + "\\n")
open({str(case / (platform + '.started'))!r}, "w").close()
deadline = time.monotonic() + {RENDEZVOUS_SECONDS}
while not os.path.exists({str(case / (other + '.started'))!r}):
    if time.monotonic() > deadline:
        sys.exit("stand-in {program}: the linux/{other} half was not run at once with this one")
    time.sleep(0.05)
half = json.load(open({str(case / 'halves.json')!r}))[{platform!r}]
print("a line of the {platform} build")
print("a line of the {platform} build's progress", file=sys.stderr)
if half["metadata"] is not None and "--metadata-file" in argv:
    open(argv[argv.index("--metadata-file") + 1], "w").write(half["metadata"])
outputs = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--output"]
for output in outputs:
    fields = dict(field.split("=", 1) for field in output.split(","))
    if fields.get("type") == "oci":
        open(fields["dest"], "w").write("an archive of the {platform} half")
sys.exit(half["exit"])
""",
        )
    executable(
        programs / "regctl",
        f"""#!{sys.executable}
import json, sys
argv = sys.argv[1:]
open({str(case / 'regctl.log')!r}, "a").write(json.dumps(argv) + "\\n")
registry = json.load(open({str(case / 'regctl.json')!r}))
if argv[:2] != ["--host", registry["host"]]:
    sys.exit(f"stand-in regctl: not told the registry serves no TLS: {{argv}}")
call = tuple(argv[2:4])
if call == ("image", "import"):
    sys.exit(registry["import"])
if call == ("index", "create"):
    sys.stdout.write(registry["pushed"])
elif call == ("manifest", "head"):
    if registry["served"] is None:
        sys.exit("failed to request manifest head: not found")
    sys.stdout.write(registry["served"])
elif call in (("manifest", "get"), ("image", "config")) and argv[-2] == "--format":
    answers = registry["answers"].get(" ".join(call) + " " + argv[-1], {{}})
    if argv[4] not in answers:
        sys.exit(f"failed to get {{argv[4]}}: not found")
    sys.stdout.write(answers[argv[4]])
else:
    sys.exit(f"stand-in regctl: not a call this suite answers: {{argv}}")
""",
    )
    return programs


def half(digest):
    return {"exit": 0, "metadata": METADATA.replace(BUILT, digest)}


class Suite:
    def __init__(self, rendered, busybox, work, run):
        documents = objects(Path(rendered).read_text())
        self.fetch = Step(documents, TASK, "fetch")
        self.build = Step(documents, TASK, "build")
        self.two = Step(documents, TWO_PLATFORM_TASK, "build")
        self.index = Step(documents, TWO_PLATFORM_TASK, "index")
        if self.two.script != self.build.script:
            refuse(f"{self.two.name} runs another build.sh than {self.build.name}")
        # The run as an operator creates it, with the commit written in.
        manifest = yaml.safe_load(Path(run).read_text().replace("@chuggy-commit@", COMMIT))
        if manifest["spec"]["taskRef"]["name"] != TWO_PLATFORM_TASK:
            refuse(f"{run} is not a run of {TWO_PLATFORM_TASK}")
        self.two_passed = {
            **{param["name"]: param["default"] for param in self.two.task["spec"]["params"] if "default" in param},
            **{param["name"]: param["value"] for param in manifest["spec"]["params"]},
        }
        other = Step(documents, *OTHER_FETCH)
        mine = (self.fetch.config, self.fetch.file, sorted(entry["name"] for entry in self.fetch.step["env"]))
        theirs = (other.config, other.file, sorted(entry["name"] for entry in other.step["env"]))
        if mine != theirs:
            refuse(f"{other.name} fetches with {theirs} and {self.fetch.name} with {mine}, so these cases are not both's")
        if IMAGE_TMPDIR not in self.build.mounts:
            refuse(f"{self.build.name} mounts nothing at {IMAGE_TMPDIR}, where its image makes its temporary files")

        pipeline = one(documents, "Pipeline", PIPELINE)
        tasks = [task for task in pipeline["spec"]["tasks"] if task["name"] == PIPELINE_TASK]
        if len(tasks) != 1 or tasks[0]["taskRef"]["name"] != TASK:
            refuse(f"Pipeline {PIPELINE} has no task {PIPELINE_TASK} of {TASK}")
        self.passed = {param["name"]: param["value"] for param in tasks[0]["params"]}
        self.defaults = {
            param["name"]: param["default"]
            for param in self.build.task["spec"]["params"]
            if "default" in param
        }
        self.busybox = Path(busybox)
        self.work = Path(work)
        self.git = Path(shutil.which("git")).parent
        self.repository = self.work / "repository"
        self.commits = self.committed()

    def git_in(self, directory, *arguments):
        return subprocess.run(
            ["git", "-C", str(directory), "-c", "user.name=suite", "-c", "user.email=suite@example.invalid", *arguments],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            env={"PATH": str(self.git), "HOME": str(self.work), "GIT_CONFIG_NOSYSTEM": "1"},
        ).stdout.strip()

    def committed(self):
        """A repository with a commit behind its branch's tip, a second branch
        named in the digits of a hash, and an annotated tag."""
        self.repository.mkdir(parents=True)
        self.git_in(self.repository, "init", "--quiet", "--initial-branch=main")
        # What a host that serves any commit by its hash allows, as the one
        # the pipeline fetches from does.
        self.git_in(self.repository, "config", "uploadpack.allowAnySHA1InWant", "true")
        commits = {}
        for name in ("earlier", "tip"):
            (self.repository / "which").write_text(name + "\n")
            self.git_in(self.repository, "add", "which")
            self.git_in(self.repository, "commit", "--quiet", "--message", name)
            commits[name] = self.git_in(self.repository, "rev-parse", "HEAD")
        self.git_in(self.repository, "branch", "deadbeef", commits["earlier"])
        self.git_in(self.repository, "tag", "--annotate", "--message", "a tag", "v1", commits["tip"])
        commits["tag"] = self.git_in(self.repository, "rev-parse", "refs/tags/v1")
        if commits["tag"] == commits["tip"]:
            refuse("the annotated tag has its commit's hash, so it is not a second object")
        return commits

    def run(self, step, case, params, path):
        root = case / "root"
        environment = step.environment(root, params)
        environment["TMPDIR"] = str(root / IMAGE_TMPDIR.lstrip("/"))
        for mount in step.mounts:
            (root / mount.lstrip("/")).mkdir(parents=True, exist_ok=True)
        (root / "workspace").mkdir(exist_ok=True)
        (root / "tekton" / "results").mkdir(parents=True, exist_ok=True)
        environment["PATH"] = path
        (case / "script").write_text(step.script)
        completed = subprocess.run(
            [str(self.busybox / "sh"), str(case / "script")],
            env=environment,
            text=True,
            capture_output=True,
        )
        return root, completed, environment

    # fetch.sh

    def fetched(self, name, commit, url=None):
        case = self.work / name
        case.mkdir()
        params = {"url": url or f"file://{self.repository}", "commit": commit}
        root, completed, environment = self.run(self.fetch, case, params, f"{self.busybox}:{self.git}")
        return Path(environment["DIRECTORY"]), completed

    def checked_out(self, name, which):
        commit = self.commits[which]
        directory, completed = self.fetched(name, commit)
        if completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
            return
        if f" at {commit} is in " not in completed.stdout:
            report(name, f"did not say the commit is there: {completed.stdout.strip()}")
        head = self.git_in(directory, "rev-parse", "HEAD")
        holds = (directory / "which").read_text().strip()
        history = self.git_in(directory, "rev-list", "--count", "HEAD")
        if (head, holds, history) != (commit, which, "1"):
            report(name, f"checked out {head} holding `{holds}` with {history} commits, not {commit} alone")

    def not_fetched(self, name, commit, said=None, url=None, after_fetching=False):
        directory, completed = self.fetched(name, commit, url)
        if completed.returncode == 0:
            report(name, "fetched, and it is a fetch this must refuse")
        elif said is not None and said not in completed.stderr:
            report(name, f"was refused without saying `{said}`: {completed.stderr.strip()}")
        if " is in " in completed.stdout:
            report(name, f"failed and said the commit is there: {completed.stdout.strip()}")
        if (directory / ".git").exists() != after_fetching:
            report(name, f"was refused {'before' if after_fetching else 'after'} the repository was asked")

    # build.sh

    def built(self, name, registry, build=None, params=None):
        """Lay one case out and run the build step in it."""
        case = self.work / name
        case.mkdir()
        (case / "registry.json").write_text(json.dumps(registry))
        (case / "build.json").write_text(json.dumps(build or {"exit": 0, "metadata": METADATA}))
        programs = stand_ins(case)
        values = {"params.chuggy-url": "https://chuggy.example.invalid/chuggy.git", "params.chuggy-commit": COMMIT}

        def from_pipeline(match):
            if match.group(1) not in values:
                refuse(f"the Pipeline passes $({match.group(1)}), which this suite does not stand in for")
            return values[match.group(1)]

        resolved = {
            **self.defaults,
            **{key: re.sub(r"\$\(([^)]+)\)", from_pipeline, value) for key, value in self.passed.items()},
            **(params or {}),
        }
        dockerfile = case / "root" / "workspace" / "source" / self.passed["dockerfile"]
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text("FROM scratch\n")
        root, completed, environment = self.run(self.build, case, resolved, f"{programs}:{self.busybox}")

        def logged(file):
            path = case / file
            return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

        results = {path.name: path.read_text() for path in (root / "tekton" / "results").iterdir()}
        return completed, logged("wget.log"), logged("buildctl.log"), results, environment, resolved

    def asked_of(self, resolved):
        registry, _, repository = resolved["image"].partition("/")
        return [ACCEPT, f"http://{registry}/v2/{repository}/manifests/{resolved['commit']}"]

    def reused(self, name, registry):
        completed, asked, builds, results, _, resolved = self.built(name, registry)
        if builds:
            report(name, f"BuildKit was run for a commit the registry has an image of: {builds}")
            return
        if completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
            return
        if asked != [self.asked_of(resolved)]:
            report(name, f"the registry was asked {asked}")
        if results != {"digest": SERVED}:
            report(name, f"the results are {results}")

    def builds(self, name, target=None):
        params = {} if target is None else {"target": target}
        completed, asked, builds, results, environment, resolved = self.built(name, [[ABSENT], [has(BUILT)]], params=params)
        if completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
            return
        image, commit, source = resolved["image"], resolved["commit"], environment["SOURCE"]
        dockerfile = Path(resolved["dockerfile"])
        expected = [
            "build",
            "--frontend=dockerfile.v0",
            "--opt", f"filename={dockerfile.name}",
            "--opt", "platform=linux/amd64",
            "--local", f"context={source}/{resolved['context']}",
            "--local", f"dockerfile={source}/{dockerfile.parent}",
            "--output", f"type=image,name={image}:{commit},push=true,registry.insecure=true",
            "--import-cache", f"type=registry,ref={image}:buildcache,registry.insecure=true",
            "--export-cache", f"type=registry,ref={image}:buildcache,mode=max,registry.insecure=true",
            "--metadata-file", None,
            "--progress=plain",
        ] + ([] if target is None else ["--opt", f"target={target}"])
        if len(builds) != 1 or len(builds[0]) != len(expected):
            report(name, f"BuildKit was called with {builds}, not once with {expected}")
            return
        where = expected.index(None)
        if not builds[0][where].startswith(environment["TMPDIR"] + "/"):
            report(name, f"the metadata file is {builds[0][where]}, which is not under the image's TMPDIR")
        expected[where] = builds[0][where]
        if builds[0] != expected:
            report(name, f"BuildKit was called with {builds[0]}, not {expected}")
        if asked != [self.asked_of(resolved)] * 2:
            report(name, f"the registry was asked {asked}")
        if results != {"digest": BUILT}:
            report(name, f"the results are {results}")

    # build.sh and index.sh, for two platforms

    def two_built(self, name, registry, halves=None, params=None, files=("ca.crt", "tls.crt", "tls.key")):
        """Lay one case out and run the two-platform build step in it."""
        case = self.work / name
        case.mkdir()
        (case / "registry.json").write_text(json.dumps(registry))
        (case / "halves.json").write_text(json.dumps(halves or {"amd64": half(AMD64), "arm64": half(ARM64)}))
        programs = two_platform_stand_ins(case)
        resolved = {**self.two_passed, **(params or {})}
        dockerfile = case / "root" / "workspace" / "source" / resolved["dockerfile"]
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text("FROM scratch\n")
        tls = Path(self.two.environment(case / "root", resolved)["ARM64_BUILDER_TLS"])
        tls.mkdir(parents=True)
        for file in files:
            (tls / file).write_text(f"a stand-in for {file}, not one\n")
        root, completed, environment = self.run(self.two, case, resolved, f"{programs}:{self.busybox}")

        def logged(file):
            path = case / file
            return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

        results = {path.name: path.read_text() for path in (root / "tekton" / "results").iterdir()}
        left = {
            name: (Path(environment["INDEX"]) / name).read_text()
            for name in ("amd64", "arm64", "served")
            if (Path(environment["INDEX"]) / name).exists()
        }
        builds = {platform: logged(platform + ".log") for platform in ("amd64", "arm64")}
        return case, completed, logged("wget.log"), builds, results, left, environment, resolved

    def two_reused(self, name):
        """A served tag left for `index`, and nothing built. Returns the case."""
        case, completed, asked, builds, results, left, _, resolved = self.two_built(name, [[has(SERVED)]])
        if completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
            return None
        if builds != {"amd64": [], "arm64": []}:
            report(name, f"a half was built for a commit the registry has an image of: {builds}")
        if asked != [self.asked_of(resolved)]:
            report(name, f"the registry was asked {asked}")
        if results or left != {"served": SERVED}:
            report(name, f"the results are {results} and the build left {left}")
        return case

    def two_builds(self, name, target=None):
        """The halves built at once, each call held whole. Returns the case."""
        params = {} if target is None else {"target": target}
        case, completed, asked, builds, results, left, environment, resolved = self.two_built(name, [[ABSENT]], params=params)
        if completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
            return None
        image, source, index, tls = resolved["image"], environment["SOURCE"], environment["INDEX"], environment["ARM64_BUILDER_TLS"]
        address = re.fullmatch(r"tcp://(.+):\d+", resolved["arm64-builder"]).group(1)
        dockerfile = Path(resolved["dockerfile"])
        common = [
            "--frontend=dockerfile.v0",
            "--opt", f"filename={dockerfile.name}",
            "--local", f"context={source}/{resolved['context']}",
            "--local", f"dockerfile={source}/{dockerfile.parent}",
            "--progress=plain",
        ] + ([] if target is None else ["--opt", f"target={target}"])
        expected = {
            "amd64": [
                ["build", *common,
                 "--opt", "platform=linux/amd64",
                 "--output", f"type=image,name={image},push-by-digest=true,oci-mediatypes=true,push=true,registry.insecure=true",
                 "--import-cache", f"type=registry,ref={image}:buildcache,registry.insecure=true",
                 "--export-cache", f"type=registry,ref={image}:buildcache,mode=max,registry.insecure=true",
                 "--metadata-file", f"{index}/amd64.json"],
            ],
            "arm64": [
                ["--addr", resolved["arm64-builder"],
                 "--tlsservername", address,
                 "--tlscacert", f"{tls}/ca.crt", "--tlscert", f"{tls}/tls.crt", "--tlskey", f"{tls}/tls.key",
                 "build", *common,
                 "--opt", "platform=linux/arm64",
                 "--output", f"type=oci,dest={index}/arm64.tar",
                 "--metadata-file", f"{index}/arm64.json"],
            ],
        }
        if builds != expected:
            report(name, f"BuildKit was called with {builds}, not {expected}")
        if asked != [self.asked_of(resolved)]:
            report(name, f"the registry was asked {asked}")
        if results or left != {"amd64": AMD64, "arm64": ARM64}:
            report(name, f"the results are {results} and the halves left {left}")
        for platform in ("amd64", "arm64"):
            for line in (f"a line of the {platform} build", f"a line of the {platform} build's progress"):
                if f"linux/{platform}: {line}" not in completed.stdout.splitlines():
                    report(name, f"`{line}` is not headed by its platform: {completed.stdout.strip()}")
        return case

    def two_not_built(self, name, said, registry, asked, ran, **arguments):
        """A run that must fail saying `said`, having asked the registry
        `asked` times, run each half `ran` times, and left nothing."""
        _, completed, questions, builds, results, left, _, _ = self.two_built(name, registry, **arguments)
        if completed.returncode == 0:
            report(name, "ended well, and it is a build this must refuse")
        elif said not in completed.stderr:
            report(name, f"was refused without saying `{said}`: {completed.stderr.strip()}")
        if len(questions) != asked:
            report(name, f"asked the registry {len(questions)} times, not {asked}")
        if {platform: len(calls) for platform, calls in builds.items()} != {"amd64": ran, "arm64": ran}:
            report(name, f"built the halves {builds}, not each {ran} times")
        if results or left:
            report(name, f"was refused and wrote {results} and left {left}")

    def indexed(self, name, case, regctl):
        """Run the index step in `case`'s pod, after its build step. Returns
        what it did."""
        root = case / "root"
        image = self.two_passed["image"]
        (case / "regctl.json").write_text(json.dumps({"host": f"reg={image.partition('/')[0]},tls=disabled", **regctl}))
        _, completed, environment = self.run(self.index, case, self.two_passed, f"{case / 'bin'}:{self.busybox}")
        path = case / "regctl.log"
        calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        results = {path.name: path.read_text() for path in (root / "tekton" / "results").iterdir()}
        return completed, [call[2:] for call in calls], results, environment

    def regctl_answers(self, served=INDEXED, listed=None, imported=0, pushed=INDEXED, kinds=None, configs=None, served_listed=None):
        """What the stand-in regctl answers: by default, of the two halves
        build left, of the index of them, and of SERVED as such an index."""
        image = self.two_passed["image"]
        halves = f"linux/amd64 {AMD64}\nlinux/arm64 {ARM64}\n"
        listed = halves if listed is None else listed
        return {
            "import": imported,
            "pushed": pushed,
            "served": served,
            "answers": {
                f"manifest get {KIND}": {
                    f"{image}@{digest}": kind
                    for digest, kind in {AMD64: OCI_IMAGE, ARM64: OCI_IMAGE, SERVED: OCI_INDEX, **(kinds or {})}.items()
                },
                f"image config {CONFIG}": {
                    f"{image}@{digest}": platform
                    for digest, platform in {AMD64: "linux/amd64", ARM64: "linux/arm64", **(configs or {})}.items()
                },
                f"manifest get {LISTING}": {
                    f"{image}@{served}": listed,
                    f"{image}@{SERVED}": halves if served_listed is None else served_listed,
                },
            },
        }

    def index_pushes(self, name):
        case = self.two_builds(name)
        if case is None:
            return
        completed, calls, results, environment = self.indexed(name, case, self.regctl_answers())
        if completed.returncode != 0:
            report(name, f"index exited {completed.returncode}: {completed.stderr.strip()}")
            return
        image, commit = self.two_passed["image"], self.two_passed["commit"]
        expected = [
            ["image", "import", f"{image}@{ARM64}", f"{environment['INDEX']}/arm64.tar"],
            ["manifest", "get", f"{image}@{AMD64}", "--format", KIND],
            ["image", "config", f"{image}@{AMD64}", "--format", CONFIG],
            ["manifest", "get", f"{image}@{ARM64}", "--format", KIND],
            ["image", "config", f"{image}@{ARM64}", "--format", CONFIG],
            ["index", "create", f"{image}:{commit}", "--ref", f"{image}@{AMD64}", "--ref", f"{image}@{ARM64}", "--format", PUSHED],
            ["manifest", "head", f"{image}:{commit}"],
            ["manifest", "get", f"{image}@{INDEXED}", "--format", LISTING],
        ]
        if calls != expected:
            report(name, f"regctl was called with {calls}, not {expected}")
        if results != {"digest": INDEXED}:
            report(name, f"the results are {results}")

    def index_served(self, name):
        """After a build that found the tag served, the tag is the result as
        an index of the two, and nothing is pushed."""
        case = self.two_reused(name)
        if case is None:
            return
        completed, calls, results, _ = self.indexed(name, case, self.regctl_answers())
        if completed.returncode != 0:
            report(name, f"index exited {completed.returncode}: {completed.stderr.strip()}")
            return
        image = self.two_passed["image"]
        expected = [
            ["manifest", "get", f"{image}@{SERVED}", "--format", KIND],
            ["manifest", "get", f"{image}@{SERVED}", "--format", LISTING],
            ["manifest", "get", f"{image}@{AMD64}", "--format", KIND],
            ["image", "config", f"{image}@{AMD64}", "--format", CONFIG],
            ["manifest", "get", f"{image}@{ARM64}", "--format", KIND],
            ["image", "config", f"{image}@{ARM64}", "--format", CONFIG],
        ]
        if calls != expected:
            report(name, f"regctl was called with {calls}, not {expected}")
        if results != {"digest": SERVED}:
            report(name, f"the results are {results}")

    def index_refused(self, name, said, regctl=None, left=None, archive=True, called=0, pushed=False):
        """An index step that must fail saying `said`, having made `called`
        calls of regctl and written no result. The tag's push is among them
        only when `pushed`: a refusal before it pushes nothing under the tag."""
        case = self.work / name
        index = case / "root" / "workspace" / "index"
        index.mkdir(parents=True)
        (case / "root" / "tekton" / "results").mkdir(parents=True)
        two_platform_stand_ins(case)
        for file, digest in (left if left is not None else {"amd64": AMD64, "arm64": ARM64}).items():
            (index / file).write_text(digest)
        if archive:
            (index / "arm64.tar").write_text("an archive of the arm64 half")
        completed, calls, results, _ = self.indexed(name, case, regctl or self.regctl_answers())
        if completed.returncode == 0:
            report(name, "ended well, and it is an index this must refuse")
        elif said not in completed.stderr:
            report(name, f"was refused without saying `{said}`: {completed.stderr.strip()}")
        if len(calls) != called:
            report(name, f"called regctl {len(calls)} times, not {called}: {calls}")
        creates = [call for call in calls if call[:2] == ["index", "create"]]
        if len(creates) != (1 if pushed else 0):
            report(name, f"pushed the tag {len(creates)} times, not {1 if pushed else 0}: {calls}")
        if results:
            report(name, f"was refused and wrote {results}")

    def not_built(self, name, said, registry, ran=0, asked=None, **arguments):
        """A run that must fail saying `said`, having run BuildKit `ran` times
        and written no result."""
        completed, questions, builds, results, _, resolved = self.built(name, registry, **arguments)
        if completed.returncode == 0:
            report(name, "gave a digest, and it is a build this must refuse")
        elif said is not None and said not in completed.stderr:
            report(name, f"was refused without saying `{said}`: {completed.stderr.strip()}")
        if len(builds) != ran:
            report(name, f"ran BuildKit {len(builds)} times, not {ran}")
        if asked is not None and len(questions) != asked:
            report(name, f"asked the registry {len(questions)} times, not {asked}")
        if results:
            report(name, f"was refused and wrote {results}")


def main():
    if len(sys.argv) != 5:
        refuse("usage: release-build.py RENDERED_BUILD_SYSTEM BUSYBOX_BIN WORK TWO_PLATFORM_RUN")
    suite = Suite(*sys.argv[1:])

    suite.checked_out("fetch-tip", "tip")
    suite.checked_out("fetch-behind-the-tip", "earlier")
    suite.not_fetched("fetch-branch", "main", "main is not a commit hash")
    suite.not_fetched("fetch-branch-named-in-hex", "deadbeef", "deadbeef is not a full commit hash")
    short = suite.commits["tip"][:12]
    suite.not_fetched("fetch-short-hash", short, f"{short} is not a full commit hash")
    suite.not_fetched(
        "fetch-hash-of-a-tag",
        suite.commits["tag"],
        f"for {suite.commits['tag']} and checked out {suite.commits['tip']}",
        after_fetching=True,
    )
    suite.not_fetched("fetch-absent-hash", "0" * 39 + "1", after_fetching=True)
    suite.not_fetched(
        "fetch-absent-repository", suite.commits["tip"], url=f"file://{suite.work}/nowhere", after_fetching=True
    )

    suite.reused("served", [[has(SERVED)]])
    suite.reused("served-header-in-lower-case", [[has(SERVED, name="docker-content-digest")]])
    suite.reused("served-with-carriage-returns", [[has(SERVED, end="\r")]])
    suite.reused("served-after-a-redirect", [[REDIRECT, has(SERVED)]])
    suite.builds("absent")
    suite.builds("absent-with-a-target", target="worker")

    could_not_ask = "the registry did not say whether it has"
    suite.not_built("registry-fails", could_not_ask, [[answer(500)]], asked=1)
    suite.not_built("registry-unreachable", could_not_ask, [[answer(None)]], asked=1)
    suite.not_built(
        "served-with-no-digest",
        "names no digest for it",
        [[answer(200, ["Content-Length: 890", "Connection: close"])]],
        asked=1,
    )
    suite.not_built("pushed-and-another-is-served", f"as {BUILT} and the registry serves '{OTHER}' under it", [[ABSENT], [has(OTHER)]], ran=1)
    suite.not_built("pushed-and-none-is-served", f"as {BUILT} and the registry serves '' under it", [[ABSENT], [ABSENT]], ran=1)
    suite.not_built("pushed-and-the-registry-fails", could_not_ask, [[ABSENT], [answer(500)]], ran=1, asked=2)
    suite.not_built(
        "build-reports-no-digest",
        "BuildKit reported no digest",
        [[ABSENT], [has(BUILT)]],
        ran=1,
        asked=1,
        build={"exit": 0, "metadata": METADATA.replace('"containerimage.digest"', '"containerimage.other"')},
    )
    suite.not_built(
        "build-fails-after-pushing",
        None,
        [[ABSENT], [has(BUILT)]],
        ran=1,
        asked=1,
        build={"exit": 7, "metadata": METADATA},
    )

    unasked = {"registry": [[has(SERVED)]], "asked": 0}
    suite.not_built("image-with-no-repository", "names no repository under a registry", params={"image": "api"}, **unasked)
    suite.not_built(
        "image-that-is-a-reference",
        "is not a registry and a repository",
        params={"image": "registry.example.invalid:5000/chuggy/api@sha256:" + "5" * 64},
        **unasked,
    )
    suite.not_built("commit-that-is-a-branch", "main is not a commit hash", params={"commit": "main"}, **unasked)
    suite.not_built("commit-cut-short", "is not a full commit hash", params={"commit": COMMIT[:39]}, **unasked)
    suite.not_built("commit-with-one-more", "is not a full commit hash", params={"commit": COMMIT + "0"}, **unasked)
    suite.not_built(
        "context-not-in-the-commit",
        "elsewhere is not a directory of the commit",
        [[ABSENT]],
        params={"context": "elsewhere"},
    )
    suite.not_built(
        "dockerfile-not-in-the-commit",
        "images/api/Elsewhere is not a file of the commit",
        [[ABSENT]],
        params={"dockerfile": "images/api/Elsewhere"},
    )

    suite.two_builds("two-absent")
    suite.two_builds("two-absent-with-a-target", target="runtime")
    for platform in ("amd64", "arm64"):
        other = "arm64" if platform == "amd64" else "amd64"
        digests = {"amd64": AMD64, "arm64": ARM64}
        suite.two_not_built(
            f"two-{platform}-fails",
            f"the linux/{platform} half of {suite.two_passed['image']}:{COMMIT} ended 7",
            [[ABSENT]],
            asked=1,
            ran=1,
            halves={platform: {**half(digests[platform]), "exit": 7}, other: half(digests[other])},
        )
        suite.two_not_built(
            f"two-{platform}-reports-no-digest",
            f"BuildKit reported no digest for the linux/{platform} half",
            [[ABSENT]],
            asked=1,
            ran=1,
            halves={
                platform: {"exit": 0, "metadata": METADATA.replace('"containerimage.digest"', '"containerimage.other"')},
                other: half(digests[other]),
            },
        )
    unasked = {"registry": [[has(SERVED)]], "asked": 0, "ran": 0}
    suite.two_not_built("two-builder-none", "names no daemon", params={"arm64-builder": ""}, **unasked)
    addresses = (
        "192.168.0.175:1234",
        "tcp://",
        "tcp://192.168.0.175:1234/x",
        "unix:///run/buildkit.sock",
        "tcp://192.168.0.175",
        "tcp://192.168.0.175:",
        "tcp://192.168.0.175:12a4",
        "tcp://:1234",
    )
    for number, address in enumerate(addresses):
        suite.two_not_built(
            f"two-builder-that-is-not-{number}",
            "is not a daemon's address",
            params={"arm64-builder": address},
            **unasked,
        )
    for missing in ("ca.crt", "tls.crt", "tls.key"):
        suite.two_not_built(
            f"two-without-{missing}",
            f"holds no {missing}",
            files=[file for file in ("ca.crt", "tls.crt", "tls.key") if file != missing],
            **unasked,
        )

    suite.index_served("index-after-two-served")
    tag = f"the registry has {suite.two_passed['image']}:{COMMIT} at {SERVED} as"
    suite.index_refused(
        "index-served-one-image",
        f"{tag} one image, not an index of linux/amd64 and linux/arm64",
        regctl=suite.regctl_answers(kinds={SERVED: OCI_IMAGE}),
        left={"served": SERVED},
        archive=False,
        called=1,
    )
    for number, listed in enumerate(
        (
            f"linux/amd64 {AMD64}\n",
            f"linux/arm64 {ARM64}\nlinux/amd64 {AMD64}\n",
            f"linux/amd64 {AMD64}\nlinux/arm64 {ARM64}\nunknown/unknown {OTHER}\n",
            f"linux/amd64 {AMD64}\nlinux/arm64 not-a-digest\n",
            f"linux/amd64 {AMD64}\nlinux/arm64 \n",
            f"linux/amd64 \nlinux/arm64 {ARM64}\n",
        )
    ):
        suite.index_refused(
            f"index-served-another-index-{number}",
            f"{tag} an index listing '",
            regctl=suite.regctl_answers(served_listed=listed),
            left={"served": SERVED},
            archive=False,
            called=2,
        )
    in_the_served = f", in the index the registry has under {suite.two_passed['image']}:{COMMIT} at {SERVED}; a commit's image"
    suite.index_refused(
        "index-served-entry-of-the-other-platform",
        f"the linux/arm64 half at {ARM64} is an image for 'linux/amd64'{in_the_served}",
        regctl=suite.regctl_answers(configs={ARM64: "linux/amd64"}),
        left={"served": SERVED},
        archive=False,
        called=6,
    )
    suite.index_refused(
        "index-served-amd64-entry-of-the-other-platform",
        f"the linux/amd64 half at {AMD64} is an image for 'linux/arm64'{in_the_served}",
        regctl=suite.regctl_answers(configs={AMD64: "linux/arm64"}),
        left={"served": SERVED},
        archive=False,
        called=4,
    )
    suite.index_refused(
        "index-served-entry-that-is-an-index",
        f"the linux/arm64 half at {ARM64} is an index, not one image{in_the_served}",
        regctl=suite.regctl_answers(kinds={ARM64: OCI_INDEX}),
        left={"served": SERVED},
        archive=False,
        called=5,
    )
    suite.index_pushes("index-after-two-absent")
    suite.index_refused(
        "index-half-of-the-other-platform",
        f"the linux/arm64 half at {ARM64} is an image for 'linux/amd64'",
        regctl=suite.regctl_answers(configs={ARM64: "linux/amd64"}),
        called=5,
    )
    suite.index_refused(
        "index-half-that-is-an-index",
        f"the linux/amd64 half at {AMD64} is an index, not one image",
        regctl=suite.regctl_answers(kinds={AMD64: OCI_INDEX}),
        called=2,
    )
    after_the_push = {"called": 7, "pushed": True}
    suite.index_refused(
        "index-another-served",
        f"as {INDEXED} and the registry serves '{OTHER}'",
        regctl=suite.regctl_answers(served=OTHER),
        **after_the_push,
    )
    suite.index_refused(
        "index-none-served",
        f"as {INDEXED} and the registry serves nothing under it",
        regctl=suite.regctl_answers(served=None),
        **after_the_push,
    )
    suite.index_refused(
        "index-pushed-with-no-digest",
        "reported no digest",
        regctl=suite.regctl_answers(pushed=""),
        called=6,
        pushed=True,
    )
    for number, listed in enumerate(
        (
            f"linux/amd64 {AMD64}\n",
            f"linux/amd64 {ARM64}\nlinux/arm64 {AMD64}\n",
            f"linux/amd64 {AMD64}\nlinux/arm64 {ARM64}\nlinux/riscv64 {OTHER}\n",
        )
    ):
        suite.index_refused(
            f"index-lists-other-than-the-halves-{number}",
            "lists 'linux/amd64",
            regctl=suite.regctl_answers(listed=listed),
            called=8,
            pushed=True,
        )
    suite.index_refused("index-no-arm64-digest", "left no digest of the linux/arm64 half", left={"amd64": AMD64})
    suite.index_refused("index-no-amd64-digest", "left no digest of the linux/amd64 half", left={"arm64": ARM64})
    suite.index_refused("index-not-a-digest", "which is not a digest", left={"amd64": AMD64[:-1], "arm64": ARM64})
    suite.index_refused("index-no-archive", "left no linux/arm64 archive", archive=False)
    suite.index_refused("index-import-fails", "", regctl=suite.regctl_answers(imported=3), called=1)

    if FAILURES:
        raise SystemExit(f"release-build: {len(FAILURES)} failed: {', '.join(FAILURES)}")


if __name__ == "__main__":
    main()
