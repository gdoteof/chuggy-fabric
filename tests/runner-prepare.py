#!/usr/bin/env python3
"""Run the fetch and prepare steps of `publish-runner-release` against a real
git history and a fake of npm.

usage: runner-prepare.py SCRIPTS_DIR

The step runs a commit's code and then decides, from the manifest and the
history, whether the next step has a release to make and what its notes are.
Git is real: each case builds a repository, the GitHub address the step asks
is rewritten to it by `url.<base>.insteadOf` in git's command-line
configuration, and fetch.sh fetches the run's commit first, one commit deep,
as the Task's first step does. So what is held is the decision, over the
history as the step really reads it:

- a tag the remote holds is success, writes nothing and installs nothing; a
  remote that cannot be asked is a failure that writes nothing;
- a manifest naming another package, or a version that is not three numbers,
  is a failure that writes nothing;
- the release commit is found behind the run's commit, past a merge and past
  later commits that changed the manifest but not its version, which the
  fetch left out of the history; its body less its trailers is the notes;
  with no body, or only trailers, its summary is;
- a release commit with neither, and a version moved by a commit whose
  subject is not `release: <version>`, are failures that write nothing;
- a tree not at the run's commit is a failure before `npm ci`;
- `npm ci` and `npm pack` run without lifecycle scripts, the pack into the
  pack directory; a pack that leaves no `<package>-<version>.tgz`, or leaves
  another file beside it, is a failure that writes no tag;
- `notes` and `tag` are written, and nothing else outside the pack; a run
  refused after the notes are read leaves neither, nor the notes it set aside.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE = "chuggy-linux"
REPOSITORY = f"kasofsk/{PACKAGE}"
ADDRESS = f"https://github.com/{REPOSITORY}.git"
FAKE_NPM = """#!/bin/sh
echo "npm $*" >> "$LOG"
if [ "$1" = pack ]; then
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --pack-destination ]; then destination=$2; fi
    shift
  done
  if [ -n "$FAKE_PACKED" ]; then for file in $FAKE_PACKED; do : > "$destination/$file"; done; fi
fi
"""
TRAILERS = "Co-Authored-By: Someone <someone@example.com>"
failed = []


def report(case, message):
    failed.append(case)
    print(f"runner-prepare: {case}: {message}", file=sys.stderr)


def git(directory, *arguments, env=None):
    return subprocess.run(
        ["git", "-C", str(directory), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


class Remote:
    """A repository commits are made in, served to the step as the package's
    GitHub address."""

    def __init__(self, root):
        self.path = root / "remote"
        self.env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "a",
            "GIT_AUTHOR_EMAIL": "a@example.com",
            "GIT_COMMITTER_NAME": "a",
            "GIT_COMMITTER_EMAIL": "a@example.com",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        subprocess.run(["git", "init", "--quiet", "-b", "main", str(self.path)], check=True, env=self.env)
        git(self.path, "config", "uploadpack.allowAnySHA1InWant", "true", env=self.env)

    def at(self, seconds):
        """Commit as of `seconds` past an epoch of this file's own, so that
        which of two commits is newer is the test's to say."""
        stamp = f"{1700000000 + seconds} +0000"
        self.env = {**self.env, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}

    def commit(self, message, name=PACKAGE, version=None, extra=None):
        manifest = self.path / "package.json"
        lines = ["{", f'  "name": "{name}",']
        if version is not None:
            lines.append(f'  "version": "{version}",')
        if extra is not None:
            lines.append(f'  "description": "{extra}",')
        lines.append('  "private": true')
        lines.append("}")
        manifest.write_text("\n".join(lines) + "\n")
        git(self.path, "add", "package.json", env=self.env)
        git(self.path, "commit", "--quiet", "--allow-empty", "-m", message, env=self.env)
        return git(self.path, "rev-parse", "HEAD", env=self.env)

    def touch(self, file, message):
        (self.path / file).write_text(message + "\n")
        git(self.path, "add", file, env=self.env)
        git(self.path, "commit", "--quiet", "-m", message, env=self.env)

    def merge(self, branch, message):
        git(self.path, "merge", "--quiet", "--no-ff", "-m", message, branch, env=self.env)
        return git(self.path, "rev-parse", "HEAD", env=self.env)

    def tag(self, name):
        git(self.path, "tag", name, env=self.env)


def run(scripts, root, remote, commit, fetched=None, packed=None, package=PACKAGE, address=ADDRESS):
    """Fetch `fetched` (the run's commit unless named) as the Task's first step
    does, then prepare `commit` over it. Returns the step, what it left and
    what npm was asked."""
    case = Path(tempfile.mkdtemp(dir=root))
    source, out, home, fakes = case / "source", case / "handoff", case / "home", case / "bin"
    out.mkdir()
    fakes.mkdir()
    (fakes / "npm").write_text(FAKE_NPM)
    (fakes / "npm").chmod(0o755)
    log = case / "log"
    log.write_text("")
    git_config = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(source),
        "GIT_CONFIG_KEY_1": f"url.file://{remote.path}.insteadOf",
        "GIT_CONFIG_VALUE_1": ADDRESS,
    }
    base = {"PATH": f"{fakes}:{os.environ['PATH']}", "HOME": str(home), **git_config}
    fetch = subprocess.run(
        ["/bin/sh", str(Path(scripts) / "fetch.sh")],
        env={**base, "URL": address, "COMMIT": fetched or commit, "DIRECTORY": str(source)},
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        raise SystemExit(f"runner-prepare: the fetch step failed: {fetch.stderr}")
    done = subprocess.run(
        ["/bin/sh", str(Path(scripts) / "runner-prepare.sh")],
        env={
            **base,
            "SOURCE": str(source),
            "OUT": str(out),
            "URL": address,
            "COMMIT": commit,
            "PACKAGE": package,
            "REPOSITORY": REPOSITORY,
            "LOG": str(log),
            "FAKE_PACKED": f"{PACKAGE}-1.2.3.tgz" if packed is None else packed,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    left = sorted(str(path.relative_to(out)) for path in out.rglob("*"))
    files = {name: (out / name).read_text() for name in ("tag", "notes", "notes.part") if (out / name).is_file()}
    return done, left, files, log.read_text().splitlines()


def expect_refused(case, outcome, says):
    done, left, files, npm = outcome
    if done.returncode == 0:
        report(case, f"exited 0: {done.stdout.strip()}")
    if files:
        report(case, f"wrote {sorted(files)}")
    if says not in done.stderr:
        report(case, f"did not say `{says}`: {done.stderr.strip()[-300:]}")
    return npm


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: runner-prepare.py SCRIPTS_DIR")
    scripts = sys.argv[1]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        def fresh():
            return Remote(Path(tempfile.mkdtemp(dir=root)))

        # A release behind a merge and a later commit that left the version as
        # it was, its body noted and its trailers left out.
        remote = fresh()
        remote.commit("the first", version="1.2.2")
        git(remote.path, "checkout", "--quiet", "-b", "ticket", env=remote.env)
        release = remote.commit(
            f"release: 1.2.3, a summary\n\nThe runner's core moves.\n\n- **A change.** What it does.\n\n{TRAILERS}",
            version="1.2.3",
        )
        git(remote.path, "checkout", "--quiet", "main", env=remote.env)
        remote.touch("README.md", "unrelated on main")
        remote.merge("ticket", "Merge pull request #1")
        later = remote.commit("a later change to the manifest", version="1.2.3", extra="later")
        done, left, files, npm = run(scripts, root, remote, later)
        if done.returncode != 0:
            report("released", f"exited {done.returncode}: {done.stderr.strip()[-300:]}")
        if files.get("tag") != "v1.2.3\n":
            report("released", f"wrote the tag {files.get('tag')!r}")
        if files.get("notes") != "The runner's core moves.\n\n- **A change.** What it does.\n":
            report("released", f"wrote the notes {files.get('notes')!r}")
        if left != ["notes", "pack", f"pack/{PACKAGE}-1.2.3.tgz", "tag"]:
            report("released", f"left {left}")
        if not npm or npm[0] != "npm ci --ignore-scripts --no-audit --no-fund" or not npm[1].startswith("npm pack --ignore-scripts --pack-destination "):
            report("released", f"asked npm {npm}")
        if release not in done.stdout:
            report("released", f"did not name the release commit {release}: {done.stdout.strip()}")

        # The summary, where the body is empty or only trailers.
        for case, message in {
            "noted-by-summary": "release: 1.2.3, a summary",
            "noted-by-summary-past-trailers": f"release: 1.2.3, a summary\n\n{TRAILERS}",
        }.items():
            remote = fresh()
            remote.commit("the first", version="1.2.2")
            head = remote.commit(message, version="1.2.3")
            done, _, files, _ = run(scripts, root, remote, head)
            if done.returncode != 0 or files.get("notes") != "a summary\n":
                report(case, f"exited {done.returncode} and wrote the notes {files.get('notes')!r}: {done.stderr.strip()[-300:]}")

        # Two release branches, the older release landed last: its merge with
        # main settled the version back to its own, and the newest commit to
        # change the version line is the other release's.
        remote = fresh()
        remote.at(0)
        remote.commit("the first", version="1.0.0")
        git(remote.path, "checkout", "--quiet", "-b", "second", env=remote.env)
        remote.at(10)
        second = remote.commit("release: 1.2.0, the second", version="1.2.0")
        git(remote.path, "checkout", "--quiet", "main", env=remote.env)
        git(remote.path, "checkout", "--quiet", "-b", "first", env=remote.env)
        remote.at(20)
        remote.commit("release: 1.1.0, the first", version="1.1.0", extra="first")
        git(remote.path, "checkout", "--quiet", "main", env=remote.env)
        remote.at(30)
        remote.merge("first", "Merge pull request #1")
        git(remote.path, "checkout", "--quiet", "second", env=remote.env)
        remote.at(40)
        subprocess.run(["git", "-C", str(remote.path), "merge", "--quiet", "main"], env=remote.env, capture_output=True)
        (remote.path / "package.json").write_text(
            f'{{\n  "name": "{PACKAGE}",\n  "version": "1.2.0",\n  "description": "first",\n  "private": true\n}}\n'
        )
        git(remote.path, "add", "package.json", env=remote.env)
        git(remote.path, "commit", "--quiet", "--no-edit", env=remote.env)
        git(remote.path, "checkout", "--quiet", "main", env=remote.env)
        remote.at(50)
        head = remote.merge("second", "Merge pull request #2")
        done, _, files, _ = run(scripts, root, remote, head, packed=f"{PACKAGE}-1.2.0.tgz")
        if done.returncode != 0 or files.get("tag") != "v1.2.0\n" or files.get("notes") != "the second\n" or second not in done.stdout:
            report("released-past-a-settled-conflict", f"exited {done.returncode} and wrote {files}: {done.stderr.strip()[-300:]}")

        # A tag the remote holds: nothing to do, and npm is never asked.
        remote = fresh()
        head = remote.commit("release: 1.2.3, a summary", version="1.2.3")
        remote.tag("v1.2.3")
        done, left, files, npm = run(scripts, root, remote, head)
        if done.returncode != 0 or files or npm or left:
            report("already-tagged", f"exited {done.returncode}, wrote {sorted(files)}, left {left}, asked npm {npm}")

        # Refused, writing nothing.
        remote = fresh()
        remote.commit("the first", version="1.2.2")
        head = remote.commit("release: 1.2.3", version="1.2.3")
        npm = expect_refused("no-notes", run(scripts, root, remote, head), "says nothing a release could be noted with")
        if npm:
            report("no-notes", f"asked npm {npm} before it refused")

        remote = fresh()
        remote.commit("the first", version="1.2.2")
        head = remote.commit("bump the version", version="1.2.3")
        expect_refused("not-a-release-commit", run(scripts, root, remote, head), "does not say it is release 1.2.3")

        remote = fresh()
        remote.commit("the first", version="1.2.2")
        head = remote.commit("release: 1.2.4, another release", version="1.2.3")
        expect_refused("release-commit-of-another-version", run(scripts, root, remote, head), "does not say it is release 1.2.3")

        remote = fresh()
        head = remote.commit("release: 1.2.3, a summary", name="chuggy-darwin", version="1.2.3")
        npm = expect_refused("another-package", run(scripts, root, remote, head), "names the package 'chuggy-darwin'")
        if npm:
            report("another-package", f"asked npm {npm}")

        for case, version in {"two-numbers": "1.2", "a-prerelease": "1.2.3-rc.1", "no-version": None}.items():
            remote = fresh()
            head = remote.commit("release: 1.2.3, a summary", version=version)
            expect_refused(case, run(scripts, root, remote, head), "is not three numbers")

        remote = fresh()
        first = remote.commit("the first", version="1.2.2")
        head = remote.commit("release: 1.2.3, a summary", version="1.2.3")
        npm = expect_refused("tree-elsewhere", run(scripts, root, remote, head, fetched=first), "is not at")
        if npm:
            report("tree-elsewhere", f"asked npm {npm}")

        for case, packed in {
            "pack-of-another-name": f"{PACKAGE}-1.2.4.tgz",
            "pack-of-nothing": "",
            "pack-beside-another": f"{PACKAGE}-1.2.3.tgz other.tgz",
        }.items():
            remote = fresh()
            remote.commit("the first", version="1.2.2")
            head = remote.commit("release: 1.2.3, a summary", version="1.2.3")
            expect_refused(case, run(scripts, root, remote, head, packed=packed), "npm pack left")

        # A remote that cannot be asked about the tag: the address resolves to
        # nothing the rewrite serves.
        remote = fresh()
        head = remote.commit("release: 1.2.3, a summary", version="1.2.3")
        (remote.path / ".git").rename(remote.path / "gone")
        case = Path(tempfile.mkdtemp(dir=root))
        done = subprocess.run(
            ["/bin/sh", str(Path(scripts) / "runner-prepare.sh")],
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(case),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": f"url.file://{remote.path}.insteadOf",
                "GIT_CONFIG_VALUE_0": ADDRESS,
                "SOURCE": str(remote.path),
                "OUT": str(case),
                "URL": ADDRESS,
                "COMMIT": head,
                "PACKAGE": PACKAGE,
                "REPOSITORY": REPOSITORY,
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        if done.returncode == 0 or (case / "tag").exists() or "could not ask" not in done.stderr:
            report("remote-unreachable", f"exited {done.returncode}: {done.stderr.strip()[-300:]}")

    if failed:
        raise SystemExit(f"runner-prepare: {len(failed)} failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
