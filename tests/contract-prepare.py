#!/usr/bin/env python3
"""Run the prepare step of `publish-worker-contract`, and the `gh` it gives the
publish script, against fakes of git, npm and the script itself.

usage: contract-prepare.py NODE SCRIPTS_DIR

The step runs a commit's code and then decides, from what the script printed,
whether the next step has a release to make. So what is held is that decision:

- the release is read from its one declaration; a declaration that is absent,
  not a version, or written twice is a failure and writes nothing;
- a tag the remote holds is success, writes nothing and installs nothing;
- a tree not at the run's commit is a failure before `npm ci`;
- `npm ci` runs without lifecycle scripts, and the script runs with --dry-run
  and a gh of ours first on the PATH;
- the script's output as it prints it (`Packed <sha>  <tarball>` and `would
  release and tag <tag> at <commit>`) is a release: `title` and then `tag`
  are written, and the title is the manifest's name and the release;
- a tarball outside the pack directory or not named `.tgz`, no tarball line,
  and a script that would release another tag or at another commit are each a
  failure that writes nothing;
- the gh answers `release view <tag>` from the remote's tags: 0 for a tag it
  holds, 1 and `release not found` for one it does not, and 2 for any other
  call, without asking the remote.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

COMMIT = "b" * 40
SHA = "c" * 64
RELEASE = "1.2.3"
TAG = f"worker-contract-v{RELEASE}"
NAME = "@chuggy/worker-contract"
DECLARATION = f'export const workerContractRelease = "{RELEASE}";\n'
FAKE_NODE = """#!/bin/sh
if [ "$1" = -e ]; then exec "$REAL_NODE" "$@"; fi
echo "node $*" >> "$LOG"
mkdir -p "$OUT/pack"
if [ -n "$FAKE_TARBALL" ]; then mkdir -p "$(dirname "$FAKE_TARBALL")"; : > "$FAKE_TARBALL"; fi
printf '%s' "$FAKE_PRINTED"
"""
FAKE_GIT = """#!/bin/sh
echo "git $*" >> "$LOG"
case $1 in
  ls-remote) printf '%s' "$FAKE_REMOTE" ;;
  rev-parse) echo "$FAKE_HEAD" ;;
esac
"""
FAKE_NPM = """#!/bin/sh
echo "npm $*" >> "$LOG"
"""
failed = []


def report(name, why):
    failed.append(name)
    print(f"contract-prepare: {name}: {why}", file=sys.stderr)


def tools(directory, node):
    bin = directory / "bin"
    bin.mkdir()
    for name, text in {"node": FAKE_NODE, "git": FAKE_GIT, "npm": FAKE_NPM}.items():
        (bin / name).write_text(text)
        (bin / name).chmod(0o755)
    return bin, node


def printed(out, tarball="chuggy-worker-contract-1.2.3.tgz", tag=TAG, commit=COMMIT, packed=True):
    first = f"Packed {SHA}  {out}/pack/{tarball}\n" if packed else ""
    return first + f"would release and tag {tag} at {commit}\n"


def prepare(node, scripts, name, declaration=DECLARATION, remote="", head=COMMIT, manifest=None, say=None, tarball="chuggy-worker-contract-1.2.3.tgz"):
    with tempfile.TemporaryDirectory() as root:
        directory = Path(root)
        bin, node = tools(directory, node)
        source, out, gh = directory / "source", directory / "out", directory / "gh"
        (source / "src/contract").mkdir(parents=True)
        (source / "src/contract/workerContract.ts").write_text("// x\n" + declaration + "export const other = 1;\n")
        (source / "src/contract/package.json").write_text(manifest or f'{{"name": "{NAME}", "private": true}}')
        out.mkdir()
        say = printed(out) if say is None else say(out)
        environment = {
            "PATH": f"{bin}:{os.environ['PATH']}",
            "REAL_NODE": node,
            "LOG": str(directory / "log"),
            "HOME": str(directory / "home"),
            "SOURCE": str(source),
            "OUT": str(out),
            "GH": str(gh),
            "REPOSITORY": "owner/repo",
            "COMMIT": COMMIT,
            "SCRIPTS": str(scripts),
            "FAKE_REMOTE": remote,
            "FAKE_HEAD": head,
            "FAKE_PRINTED": say,
            "FAKE_TARBALL": str(out / "pack" / tarball) if tarball else "",
        }
        done = subprocess.run(["/bin/sh", str(scripts / "contract-prepare.sh")], env=environment, text=True, capture_output=True)
        log = (directory / "log").read_text().splitlines() if (directory / "log").exists() else []
        written = sorted(path.name for path in out.iterdir() if path.is_file())
        title = (out / "title").read_text() if (out / "title").exists() else None
        tag = (out / "tag").read_text() if (out / "tag").exists() else None
        installed = (gh / "gh").exists()
    return done, log, written, title, tag, installed


def gh(node, scripts, name, arguments, remote=""):
    with tempfile.TemporaryDirectory() as root:
        directory = Path(root)
        bin, node = tools(directory, node)
        environment = {
            "PATH": f"{bin}:{os.environ['PATH']}",
            "LOG": str(directory / "log"),
            "REPOSITORY": "owner/repo",
            "FAKE_REMOTE": remote,
        }
        done = subprocess.run(["/bin/sh", str(scripts / "contract-gh.sh"), *arguments], env=environment, text=True, capture_output=True)
        log = (directory / "log").read_text().splitlines() if (directory / "log").exists() else []
    return done, log


def refused(node, scripts, name, **arguments):
    done, log, written, title, tag, _ = prepare(node, scripts, name, **arguments)
    if done.returncode != 1:
        report(name, f"exited {done.returncode}, not 1: {done.stdout.strip()} {done.stderr.strip()}")
    if written:
        report(name, f"wrote {written} before it refused")
    return log


def main():
    node, scripts = sys.argv[1], Path(sys.argv[2])

    done, log, written, title, tag, installed = prepare(node, scripts, "golden")
    if done.returncode != 0:
        report("golden", f"exited {done.returncode}: {done.stdout.strip()} {done.stderr.strip()}")
    if (title, tag) != (f"{NAME} {RELEASE}\n", f"{TAG}\n") or written != ["tag", "title"]:
        report("golden", f"wrote {written}: title {title!r}, tag {tag!r}")
    if not installed:
        report("golden", "installed no gh")
    if not any(line.startswith("git ls-remote --tags https://github.com/owner/repo.git refs/tags/" + TAG) for line in log):
        report("golden", f"asked the remote for {TAG} as {log}")
    if "npm ci --ignore-scripts --no-audit --no-fund" not in log:
        report("golden", f"installed with {log}")
    dry = [line for line in log if line.startswith("node ")]
    if len(dry) != 1 or "--dry-run" not in dry[0] or "scripts/publish-worker-contract.ts" not in dry[0]:
        report("golden", f"ran the script as {dry}")

    done, log, written, title, tag, installed = prepare(node, scripts, "tag-held", remote=f"{COMMIT}\trefs/tags/{TAG}\n")
    if done.returncode != 0 or written or installed or any(line.startswith(("npm", "node")) for line in log):
        report("tag-held", f"exited {done.returncode}, wrote {written}, installed {installed}, ran {log}")

    for name, declaration in {
        "no-declaration": "",
        "declaration-not-a-version": 'export const workerContractRelease = "1.2";\n',
        "declaration-twice": DECLARATION + DECLARATION.replace(RELEASE, "1.2.4"),
        "declaration-indented": " " + DECLARATION,
    }.items():
        log = refused(node, scripts, name, declaration=declaration)
        if any(line.startswith(("npm", "node")) for line in log):
            report(name, f"ran {log}")

    log = refused(node, scripts, "head-elsewhere", head="d" * 40)
    if any(line.startswith(("npm", "node")) for line in log):
        report("head-elsewhere", f"ran {log}")
    refused(node, scripts, "no-package-name", manifest="{}")
    for name, package in {"at-in-the-middle": "a@b", "two-ats": "@@a", "at-alone": "@", "slash-only-scope-gap": "@a b"}.items():
        refused(node, scripts, name, manifest=f'{{"name": "{package}"}}')
    done, log, written, title, tag, _ = prepare(node, scripts, "scoped-name", manifest='{"name": "plain.pkg_1/x-y"}')
    if title != f"plain.pkg_1/x-y {RELEASE}\n":
        report("scoped-name", f"titled {title!r}")
    refused(node, scripts, "package-name-with-space", manifest='{"name": "a b"}')

    for name, say in {
        "tarball-elsewhere": lambda out: f"Packed {SHA}  /tmp/x.tgz\nwould release and tag {TAG} at {COMMIT}\n",
        "tarball-a-file-elsewhere": lambda out: f"Packed {SHA}  /bin/sh\nwould release and tag {TAG} at {COMMIT}\n",
        "tarball-in-a-subdirectory": lambda out: f"Packed {SHA}  {out}/pack/sub/x.tgz\nwould release and tag {TAG} at {COMMIT}\n",
        "tarball-not-tgz": lambda out: f"Packed {SHA}  {out}/pack/x.zip\nwould release and tag {TAG} at {COMMIT}\n",
        "short-sha": lambda out: f"Packed abc  {out}/pack/x.tgz\nwould release and tag {TAG} at {COMMIT}\n",
        "no-packed-line": lambda out: printed(out, packed=False),
        "other-tag": lambda out: printed(out, tag="worker-contract-v1.2.4"),
        "other-commit": lambda out: printed(out, commit="d" * 40),
        "handshake-with-trailing-text": lambda out: printed(out).rstrip("\n") + " and more\n",
        "released-for-real": lambda out: f"Packed {SHA}  {out}/pack/chuggy-worker-contract-1.2.3.tgz\nreleased and tagged {TAG} at {COMMIT}\n",
    }.items():
        refused(node, scripts, name, say=say, tarball="sub/x.tgz" if name == "tarball-in-a-subdirectory" else "chuggy-worker-contract-1.2.3.tgz")
    refused(node, scripts, "tarball-not-made", tarball="")

    for name, arguments, remote, code, says in (
        ("gh-tag-held", ["release", "view", TAG], f"{COMMIT}\trefs/tags/{TAG}\n", 0, ""),
        ("gh-tag-absent", ["release", "view", TAG], "", 1, "release not found"),
        ("gh-create", ["release", "create", TAG], "", 2, "answers"),
        ("gh-view-no-tag", ["release", "view"], "", 2, "answers"),
        ("gh-view-two-tags", ["release", "view", TAG, "x"], "", 2, "answers"),
        ("gh-pr", ["pr", "view", "1"], "", 2, "answers"),
        ("gh-no-arguments", [], "", 2, "answers"),
    ):
        done, log = gh(node, scripts, name, arguments, remote)
        if done.returncode != code or says not in done.stderr:
            report(name, f"exited {done.returncode}: {done.stderr.strip()}")
        if code == 2 and log:
            report(name, f"asked the remote after refusing: {log}")
        if code != 2 and log != [f"git ls-remote --tags https://github.com/owner/repo.git refs/tags/{TAG}"]:
            report(name, f"asked {log}")

    if failed:
        print(f"contract-prepare: {len(failed)} failed: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
