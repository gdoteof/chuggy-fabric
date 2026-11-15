#!/usr/bin/env python3
"""Run the prepare step of `publish-worker-contract`, and the `gh` it gives the
publish script, against fakes of git, npm and the script itself.

usage: contract-prepare.py NODE SCRIPTS_DIR

The step runs a commit's code and then decides, from what the script printed,
whether the next step has a release to make. So what is held is that decision:

- the release is the minor after the newest `worker-contract-v<release>` tag
  the remote holds, by number and not by text, whatever the commit's source
  says; tags of another form are not counted, a tag listed with its commit is
  read at the commit, and a remote with no such tag is a failure;
- the newest release tagged at the run's commit is success, writes nothing,
  installs nothing and fetches nothing;
- a `src/contract` that is the tree at the newest release's commit is success,
  writes nothing and installs nothing; a release's commit that cannot be
  fetched, and either commit without the tree, is a failure;
- a remote that cannot be asked for its tags, in the step and in the gh,
  is a failure that writes nothing and echoes nothing it said, and not an
  absent tag;
- a tree not at the run's commit is a failure before `npm ci`;
- `npm ci` runs without lifecycle scripts, and the script runs with --dry-run,
  the chosen release and a gh of ours first on the PATH;
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
RELEASE = "1.10.0"
TAG = f"worker-contract-v{RELEASE}"
RELEASED = "1.9.4"
RELEASED_AT = "a" * 40
NAME = "@chuggy/worker-contract"
TARBALL = f"chuggy-worker-contract-{RELEASE}.tgz"


def listed(*tags):
    return "".join(f"{commit}\trefs/tags/{tag}\n" for tag, commit in tags)


REMOTE = listed(("worker-contract-v1.2.0", "e" * 40), (f"worker-contract-v{RELEASED}", RELEASED_AT))
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
  ls-remote) if [ -n "$FAKE_LS_FAIL" ]; then echo "fatal: secret-looking remote output" >&2; exit 128; fi; printf '%s' "$FAKE_REMOTE" ;;
  fetch) [ -z "$FAKE_FETCH_FAIL" ] || exit 128 ;;
  rev-parse)
    case $* in
      *HEAD:src/contract) [ -n "$FAKE_TREE_HERE" ] || exit 1; echo "$FAKE_TREE_HERE" ;;
      *:src/contract) [ -n "$FAKE_TREE_RELEASED" ] || exit 1; echo "$FAKE_TREE_RELEASED" ;;
      *) echo "$FAKE_HEAD" ;;
    esac ;;
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


def printed(out, tarball=TARBALL, tag=TAG, commit=COMMIT, packed=True):
    first = f"Packed {SHA}  {out}/pack/{tarball}\n" if packed else ""
    return first + f"would release and tag {tag} at {commit}\n"


def prepare(node, scripts, name, remote=REMOTE, fail_remote=False, head=COMMIT, manifest=None, say=None, tarball=TARBALL, here="1" * 40, released="2" * 40, fail_fetch=False):
    with tempfile.TemporaryDirectory() as root:
        directory = Path(root)
        bin, node = tools(directory, node)
        source, out, gh = directory / "source", directory / "out", directory / "gh"
        (source / "src/contract").mkdir(parents=True)
        (source / "src/contract/workerContract.ts").write_text('export const workerContractRelease = "7.7.7";\n')
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
            "FAKE_LS_FAIL": "1" if fail_remote else "",
            "FAKE_HEAD": head,
            "FAKE_TREE_HERE": here,
            "FAKE_TREE_RELEASED": released,
            "FAKE_FETCH_FAIL": "1" if fail_fetch else "",
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


def gh(node, scripts, name, arguments, remote="", fail_remote=False):
    with tempfile.TemporaryDirectory() as root:
        directory = Path(root)
        bin, node = tools(directory, node)
        environment = {
            "PATH": f"{bin}:{os.environ['PATH']}",
            "LOG": str(directory / "log"),
            "REPOSITORY": "owner/repo",
            "FAKE_REMOTE": remote,
            "FAKE_LS_FAIL": "1" if fail_remote else "",
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
    if "git ls-remote --tags https://github.com/owner/repo.git refs/tags/worker-contract-v*" not in log:
        report("golden", f"asked the remote for its releases as {log}")
    if f"git fetch --quiet --depth 1 https://github.com/owner/repo.git {RELEASED_AT}" not in log:
        report("golden", f"fetched the newest release's commit as {log}")
    if "npm ci --ignore-scripts --no-audit --no-fund" not in log:
        report("golden", f"installed with {log}")
    dry = [line for line in log if line.startswith("node ")]
    if len(dry) != 1 or "--dry-run" not in dry[0] or f"--release {RELEASE} " not in dry[0] or "scripts/publish-worker-contract.ts" not in dry[0]:
        report("golden", f"ran the script as {dry}")

    for name, arguments in {
        "released-at-this-commit": {"remote": listed((f"worker-contract-v{RELEASED}", COMMIT))},
        "contract-as-released": {"here": "3" * 40, "released": "3" * 40},
    }.items():
        done, log, written, title, tag, installed = prepare(node, scripts, name, **arguments)
        if done.returncode != 0 or written or installed or any(line.startswith(("npm", "node")) for line in log):
            report(name, f"exited {done.returncode}, wrote {written}, installed {installed}, ran {log}")
        if name == "released-at-this-commit" and any(line.startswith("git fetch") for line in log):
            report(name, f"fetched {log}")

    for name, remote, at in (
        ("newest-by-number", listed(("worker-contract-v1.9.0", "e" * 40), ("worker-contract-v1.10.0", "f" * 40), ("worker-contract-v1.2.9", "e" * 40)), "f" * 40),
        ("other-forms-not-counted", listed((f"worker-contract-v{RELEASED}", RELEASED_AT), ("worker-contract-v2.0.0-rc", "e" * 40), ("worker-contract-v3", "e" * 40), ("worker-contract-v01.99.0", "e" * 40)), RELEASED_AT),
        ("tag-with-its-commit", listed((f"worker-contract-v{RELEASED}", "e" * 40), (f"worker-contract-v{RELEASED}^{{}}", RELEASED_AT)), RELEASED_AT),
    ):
        wanted = "1.11.0" if name == "newest-by-number" else RELEASE
        say = lambda out, wanted=wanted: printed(out, tarball=f"chuggy-worker-contract-{wanted}.tgz", tag=f"worker-contract-v{wanted}")
        done, log, written, title, tag, _ = prepare(node, scripts, name, remote=remote, say=say, tarball=f"chuggy-worker-contract-{wanted}.tgz")
        if done.returncode != 0 or tag != f"worker-contract-v{wanted}\n" or title != f"{NAME} {wanted}\n":
            report(name, f"exited {done.returncode} with tag {tag!r}, title {title!r}: {done.stderr.strip()}")
        if not any(line.startswith("git fetch") and line.endswith(at) for line in log):
            report(name, f"fetched {log}, not {at}")

    for name, arguments in {
        "no-release-to-number-from": {"remote": ""},
        "only-other-forms": {"remote": listed(("worker-contract-v2.0.0-rc", "e" * 40))},
        "release-commit-not-fetched": {"fail_fetch": True},
        "release-commit-without-the-tree": {"released": ""},
        "commit-without-the-tree": {"here": ""},
    }.items():
        log = refused(node, scripts, name, **arguments)
        if any(line.startswith(("npm", "node")) for line in log):
            report(name, f"ran {log}")

    log = refused(node, scripts, "remote-cannot-be-asked", fail_remote=True)
    if any(line.startswith(("npm", "node")) for line in log):
        report("remote-cannot-be-asked", f"ran {log}")
    done, *_ = prepare(node, scripts, "remote-output-echoed", fail_remote=True)
    if "secret-looking" in done.stdout + done.stderr:
        report("remote-output-echoed", "the remote's own output was printed")
    done, log = gh(node, scripts, "gh-remote-cannot-be-asked", ["release", "view", TAG], fail_remote=True)
    if done.returncode != 2 or "secret-looking" in done.stderr:
        report("gh-remote-cannot-be-asked", f"exited {done.returncode}: {done.stderr.strip()}")

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
        "other-tag": lambda out: printed(out, tag="worker-contract-v1.10.1"),
        "other-commit": lambda out: printed(out, commit="d" * 40),
        "handshake-with-trailing-text": lambda out: printed(out).rstrip("\n") + " and more\n",
        "released-for-real": lambda out: f"Packed {SHA}  {out}/pack/{TARBALL}\nreleased and tagged {TAG} at {COMMIT}\n",
    }.items():
        refused(node, scripts, name, say=say, tarball="sub/x.tgz" if name == "tarball-in-a-subdirectory" else TARBALL)
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
