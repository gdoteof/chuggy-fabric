#!/usr/bin/env python3
"""Run the `fetch` and `build` steps as their pods are given them, against a
repository that is a directory and a registry that is a file.

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
with and writes the metadata file BuildKit writes.

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


class Suite:
    def __init__(self, rendered, busybox, work):
        documents = objects(Path(rendered).read_text())
        self.fetch = Step(documents, TASK, "fetch")
        self.build = Step(documents, TASK, "build")
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
    if len(sys.argv) != 4:
        refuse("usage: release-build.py RENDERED_BUILD_SYSTEM BUSYBOX_BIN WORK")
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

    if FAILURES:
        raise SystemExit(f"release-build: {len(FAILURES)} failed: {', '.join(FAILURES)}")


if __name__ == "__main__":
    main()
