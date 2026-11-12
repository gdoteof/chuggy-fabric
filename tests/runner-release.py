#!/usr/bin/env python3
"""Run the release step of `publish-runner-release` against a GitHub that is a
server of this file's own, and hold every call it makes.

usage: runner-release.py NODE RUNNER_RELEASE_MJS

contract-release.py's cases, for a runner package: what is held is what the
step does with the directory the prepare step wrote and with GitHub, call by
call:

- no `tag` in the directory is a run with nothing to release: success, and no
  call at all, not even a read;
- a release is a draft first, then its asset, then published, in that order
  and with the token on every call; the draft is made at the run's commit,
  titled with the tag, and its body is the `notes` the directory holds and
  then a line naming the commit and the tarball's hash; a draft an earlier
  run left for the same tag is deleted first, and a draft for another tag is
  left alone;
- a tag already released, as a published release, is success and creates
  nothing;
- a link in the directory, for the tag, the notes, the pack or its tarball, a
  pipe or directory for the tag or notes, and a size past the bound for the
  tag, notes or tarball or too many entries in the pack, is a failure, and the
  token it points at is in nothing the step prints;
- the listing is read to its last page; the asset is sent as
  `application/x-gtar` under the name `<package>-<version>.tgz`;
- a directory that is not exactly a runner tag, notes and this release's one
  tarball is a failure before any call that writes: a tag that is not `v` and
  a version, no notes or empty notes, a tarball of another package or
  version, two files, a link;
- a package that is not a name, a repository that is not the package's, a
  commit that is not a full hash, no token and an empty token are failures
  before any call;
- an upload address that is not GitHub's uploads address for the draft is a
  failure before the asset is sent, and an upload GitHub refuses leaves the
  draft unpublished.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

COMMIT = "a" * 40
PACKAGE = "chuggy-linux"
REPOSITORY = f"kasofsk/{PACKAGE}"
TAG = "v1.2.3"
NOTES = "The runner's core moves.\n\n- **A change.** What it does."
TARBALL = f"{PACKAGE}-1.2.3.tgz"
TOKEN = "installation-token-for-this-test"
FAILURES = []


def report(case, message):
    FAILURES.append(case)
    print(f"runner-release: {case}: {message}", file=sys.stderr)


class Github:
    """The few calls a release makes, answered from `state`, each recorded."""

    def __init__(self):
        self.calls = []
        self.state = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *arguments):
                pass

            def answer(self, status, body=None):
                payload = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def handle_any(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                outer.calls.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "type": self.headers.get("Content-Type"),
                        "body": body,
                    }
                )
                state = outer.state
                base = f"/repos/{REPOSITORY}"
                if state.get("redirect") and self.command == "GET" and self.path.startswith(f"{base}/releases"):
                    self.send_response(302)
                    self.send_header("Location", "/followed")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif self.command == "GET" and self.path.startswith(f"{base}/releases?per_page=100&page="):
                    page = int(self.path.rsplit("=", 1)[1])
                    self.answer(200, state.get("releases", [])[(page - 1) * 100 : page * 100])
                elif self.command == "DELETE" and self.path.startswith(f"{base}/releases/"):
                    self.answer(204)
                elif self.command == "POST" and self.path == f"{base}/releases":
                    self.answer(201, {"id": 77, "upload_url": state["upload_url"]})
                elif self.command == "POST" and self.path.startswith(f"{base}/releases/77/assets"):
                    self.answer(state.get("upload_status", 201), {})
                elif self.command == "PATCH" and self.path == f"{base}/releases/77":
                    self.answer(200, {})
                else:
                    self.answer(404, {"message": "not a call the test answers"})

            do_GET = do_POST = do_PATCH = do_DELETE = handle_any

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def run(node, script, github, name, tag=TAG, notes=None, files=(TARBALL,), commit=COMMIT, token=TOKEN, link=False, links=(), make=None, package=PACKAGE, repository=REPOSITORY, **state):
    github.calls.clear()
    github.state = {"upload_url": f"{github.address}/repos/{REPOSITORY}/releases/77/assets{{?name,label}}", **state}
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory) / "handoff"
        (out / "pack").mkdir(parents=True)
        if tag is not None:
            (out / "tag").write_text(tag + "\n")
        if tag is not None and notes != "":
            (out / "notes").write_text((NOTES if notes is None else notes) + "\n")
        for file in files:
            if link:
                (out / "pack" / file).symlink_to("/etc/passwd")
            else:
                (out / "pack" / file).write_bytes(b"tarball bytes")
        token_file = Path(directory) / "token"
        if token is not None:
            token_file.write_text(token + "\n")
        elsewhere = Path(directory) / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / TARBALL).write_bytes(b"tarball bytes")
        for name in links:
            if name == "pack":
                (out / "pack" / TARBALL).unlink()
                (out / "pack").rmdir()
                (out / "pack").symlink_to(elsewhere)
            elif name == "entry":
                (out / "pack" / TARBALL).unlink()
                (out / "pack" / TARBALL).symlink_to(elsewhere / TARBALL)
            elif name == "token-entry":
                (out / "pack" / TARBALL).unlink()
                (out / "pack" / TARBALL).symlink_to(token_file)
            else:
                # To a file that would pass every check but the link.
                (elsewhere / name).write_text((tag if name == "tag" else NOTES) + "\n")
                (out / name).unlink()
                (out / name).symlink_to(elsewhere / name)
        if make is not None:
            make(out)
        environment = {
            "PATH": os.environ["PATH"],
            "REPOSITORY": repository,
            "PACKAGE": package,
            "COMMIT": commit,
            "OUT": str(out),
            "TOKEN": str(token_file),
            "GITHUB_API": github.address,
            "GITHUB_UPLOADS": github.address,
        }
        try:
            done = subprocess.run([node, script], env=environment, text=True, capture_output=True, timeout=20)
        except subprocess.TimeoutExpired:
            report(name, "hung")
            done = subprocess.CompletedProcess([], 124, "", "")
    return done


def shape(github):
    return [(call["method"], call["path"].split("?")[0]) for call in github.calls]


def expect(name, done, github, fails, calls, says=None):
    if fails != (done.returncode != 0):
        report(name, f"exited {done.returncode}: {done.stdout.strip()} {done.stderr.strip()[-300:]}")
    if shape(github) != calls:
        report(name, f"called {shape(github)}, not {calls}")
    for call in github.calls:
        if call["authorization"] != f"Bearer {TOKEN}":
            report(name, f"{call['method']} {call['path']} was sent without the token")
    said = done.stderr if fails else done.stdout
    if says and says not in said:
        report(name, f"did not say `{says}`: {said.strip()[-300:]}")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: runner-release.py NODE RUNNER_RELEASE_MJS")
    node, script = sys.argv[1:]
    github = Github()
    base = f"/repos/{REPOSITORY}"
    listing = (("GET", f"{base}/releases"),)

    done = run(node, script, github, "nothing-packed", tag=None)
    expect("nothing-packed", done, github, False, [], says="nothing to release")

    stale = {"id": 5, "tag_name": TAG, "draft": True}
    others = [stale, {"id": 6, "tag_name": "v1.2.2", "draft": False}, {"id": 7, "tag_name": "v1.2.4", "draft": True}]
    done = run(node, script, github, "released", releases=others)
    expect(
        "released",
        done,
        github,
        False,
        [
            *listing,
            ("DELETE", f"{base}/releases/5"),
            ("POST", f"{base}/releases"),
            ("POST", f"{base}/releases/77/assets"),
            ("PATCH", f"{base}/releases/77"),
        ],
        says=f"released {TAG} of {PACKAGE} at {COMMIT}",
    )
    if len(github.calls) == 5:
        draft = json.loads(github.calls[2]["body"])
        sha = hashlib.sha256(b"tarball bytes").hexdigest()
        wanted = {"tag_name": TAG, "target_commitish": COMMIT, "name": TAG, "body": f"{NOTES}\n\nPacked at {COMMIT} (sha256 {sha}).", "draft": True}
        if draft != wanted:
            report("released", f"the draft is {draft}, not {wanted}")
        if github.calls[3]["path"] != f"{base}/releases/77/assets?name={TARBALL}" or github.calls[3]["body"] != b"tarball bytes":
            report("released", f"the asset is sent as {github.calls[3]['path']}")
        if github.calls[3]["type"] != "application/x-gtar":
            report("released", f"the asset is sent as {github.calls[3]['type']}")
        if json.loads(github.calls[4]["body"]) != {"draft": False}:
            report("released", f"the release is published with {github.calls[4]['body']}")

    filler = [{"id": 1000 + n, "tag_name": f"v0.0.{n}", "draft": False} for n in range(100)]
    done = run(node, script, github, "released-on-page-two", releases=[*filler, {"id": 9, "tag_name": TAG, "draft": False}])
    expect("released-on-page-two", done, github, False, [*listing, *listing], says="already released")
    done = run(node, script, github, "stale-draft-on-page-two", releases=[*filler, stale])
    if ("DELETE", f"{base}/releases/5") not in shape(github):
        report("stale-draft-on-page-two", f"called {shape(github)}")

    done = run(node, script, github, "already-released", releases=[{"id": 9, "tag_name": TAG, "draft": False}])
    expect("already-released", done, github, False, [*listing], says="already released")

    for name, arguments in {
        "tag-is-not-a-runner-tag": {"tag": "worker-contract-v1.2.3"},
        "tag-is-not-a-version": {"tag": "v1.2"},
        "tag-has-a-path": {"tag": f"../{TAG}"},
        "tag-has-two-lines": {"tag": f"{TAG}\nx"},
        "no-notes": {"notes": ""},
        "empty-notes": {"notes": "  \n "},
        "tarball-of-another-version": {"files": (f"{PACKAGE}-1.2.4.tgz",)},
        "tarball-of-another-package": {"files": ("chuggy-darwin-1.2.3.tgz",)},
        "two-files": {"files": (TARBALL, "second.tgz")},
        "no-file": {"files": ()},
        "not-a-tarball": {"files": ("notes.txt",)},
        "a-link": {"link": True},
        "tag-is-a-link": {"links": ("tag",)},
        "notes-is-a-link": {"links": ("notes",)},
        "pack-is-a-link": {"links": ("pack",)},
        "entry-is-a-link": {"links": ("entry",)},
        "entry-is-a-link-to-the-token": {"links": ("token-entry",)},
        "tag-is-a-pipe": {"make": lambda out: (out / "tag").unlink() or os.mkfifo(out / "tag")},
        "notes-is-a-pipe": {"make": lambda out: (out / "notes").unlink() or os.mkfifo(out / "notes")},
        "tag-is-a-directory": {"make": lambda out: (out / "tag").unlink() or (out / "tag").mkdir()},
        "tag-is-oversized": {"make": lambda out: (out / "tag").write_text(TAG + "\n" + "x" * 400)},
        "notes-is-oversized": {"make": lambda out: (out / "notes").write_text(NOTES + "\n" + "x" * (65 * 1024))},
        "tarball-is-oversized": {"make": lambda out: (out / "pack" / TARBALL).write_bytes(b"") or os.truncate(out / "pack" / TARBALL, 65 * 1024 * 1024)},
        "pack-is-oversized": {"make": lambda out: [(out / "pack" / f"{n}.tgz").write_bytes(b"x") for n in range(300)]},
        "package-is-not-a-name": {"package": "../chuggy-linux"},
        "repository-is-another-package": {"repository": "kasofsk/chuggy-darwin"},
        "repository-is-not-a-repository": {"repository": "chuggy-linux"},
        "short-commit": {"commit": "abc123"},
        "no-token": {"token": None},
        "empty-token": {"token": ""},
    }.items():
        done = run(node, script, github, name, **arguments)
        written = [call for call in shape(github) if call[0] != "GET"]
        if done.returncode == 0:
            report(name, f"exited 0: {done.stdout.strip()}")
        if written:
            report(name, f"wrote {written} before it refused")
        # Every case here is refused on what the run was given and the
        # directory holds, before the token is read: none asks GitHub anything,
        # so a refusal that came from GitHub's answer is not the step's.
        if github.calls:
            report(name, f"called {shape(github)} before it refused")
        if TOKEN in done.stdout + done.stderr:
            report(name, "the token value is in what it printed")

    done = run(node, script, github, "upload-address-elsewhere", upload_url="https://elsewhere.invalid/assets{?name}")
    expect(
        "upload-address-elsewhere",
        done,
        github,
        True,
        [*listing, ("POST", f"{base}/releases")],
        says="upload address",
    )
    done = run(node, script, github, "redirected", redirect=True)
    if done.returncode == 0 or any(call["path"] == "/followed" for call in github.calls):
        report("redirected", f"exited {done.returncode} and called {shape(github)}")
    done = run(node, script, github, "upload-refused", upload_status=422)
    expect(
        "upload-refused",
        done,
        github,
        True,
        [*listing, ("POST", f"{base}/releases"), ("POST", f"{base}/releases/77/assets")],
        says="answered 422",
    )

    if FAILURES:
        raise SystemExit(f"runner-release: {len(FAILURES)} failed: {', '.join(FAILURES)}")


if __name__ == "__main__":
    main()
