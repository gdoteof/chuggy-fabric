#!/usr/bin/env python3
"""Run the release step of `publish-worker-contract` against a GitHub that is a
server of this file's own, and hold every call it makes.

usage: contract-release.py NODE CONTRACT_RELEASE_MJS

The step is the only one with a token, and it reads a directory the step before
it wrote from a commit's code. So what is held is what it does with that
directory and with GitHub, call by call:

- no `tag` in the directory is a run with nothing to release: success, and no
  call at all, not even a read;
- a release is a draft first, then its asset, then published, in that order
  and with the token on every call; the draft is made at the run's commit, and
  titled with the `title` the directory holds, and noted with the commit and
  the tarball's hash; a draft an earlier run left for the
  same tag is deleted first, and a draft for another tag is left alone;
- a tag already released, as a published release, is success and creates
  nothing;
- a directory that is not exactly a worker contract tag and one regular
  tarball is a failure before any call that writes: a tag that is not of the
  one pattern, no title, a title that is not a package name and the tag's
  release, two files, a link, a name with a path in it;
- a commit that is not a full hash, no token and an empty token are failures
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
REPOSITORY = "owner/repo"
TAG = "worker-contract-v1.2.3"
TITLE = "@chuggy/worker-contract 1.2.3"
TARBALL = "chuggy-worker-contract-1.2.3.tgz"
TOKEN = "installation-token-for-this-test"
FAILURES = []


def report(case, message):
    FAILURES.append(case)
    print(f"contract-release: {case}: {message}", file=sys.stderr)


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
                if self.command == "GET" and self.path == f"{base}/releases?per_page=100":
                    self.answer(200, state.get("releases", []))
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


def run(node, script, github, name, tag=TAG, title=None, files=(TARBALL,), commit=COMMIT, token=TOKEN, link=False, **state):
    github.calls.clear()
    github.state = {"upload_url": f"{github.address}/repos/{REPOSITORY}/releases/77/assets{{?name,label}}", **state}
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory) / "handoff"
        (out / "pack").mkdir(parents=True)
        if tag is not None:
            (out / "tag").write_text(tag + "\n")
        if tag is not None and title != "":
            (out / "title").write_text((TITLE if title is None else title) + "\n")
        for file in files:
            if link:
                (out / "pack" / file).symlink_to("/etc/passwd")
            else:
                (out / "pack" / file).write_bytes(b"tarball bytes")
        token_file = Path(directory) / "token"
        if token is not None:
            token_file.write_text(token + "\n")
        environment = {
            "PATH": os.environ["PATH"],
            "REPOSITORY": REPOSITORY,
            "COMMIT": commit,
            "OUT": str(out),
            "TOKEN": str(token_file),
            "GITHUB_API": github.address,
            "GITHUB_UPLOADS": github.address,
        }
        done = subprocess.run([node, script], env=environment, text=True, capture_output=True)
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
        raise SystemExit("usage: contract-release.py NODE CONTRACT_RELEASE_MJS")
    node, script = sys.argv[1:]
    github = Github()
    base = f"/repos/{REPOSITORY}"
    listing = (("GET", f"{base}/releases"),)

    done = run(node, script, github, "nothing-packed", tag=None)
    expect("nothing-packed", done, github, False, [], says="nothing to release")

    stale = {"id": 5, "tag_name": TAG, "draft": True}
    others = [stale, {"id": 6, "tag_name": "worker-contract-v1.2.2", "draft": False}, {"id": 7, "tag_name": "worker-contract-v1.2.4", "draft": True}]
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
        says=f"released {TAG} at {COMMIT}",
    )
    if len(github.calls) == 5:
        draft = json.loads(github.calls[2]["body"])
        sha = hashlib.sha256(b"tarball bytes").hexdigest()
        wanted = {"tag_name": TAG, "target_commitish": COMMIT, "name": TITLE, "body": f"Packed at {COMMIT} (sha256 {sha}).", "draft": True}
        if draft != wanted:
            report("released", f"the draft is {draft}, not {wanted}")
        if github.calls[3]["path"] != f"{base}/releases/77/assets?name={TARBALL}" or github.calls[3]["body"] != b"tarball bytes":
            report("released", f"the asset is sent as {github.calls[3]['path']}")
        if github.calls[3]["type"] != "application/gzip":
            report("released", f"the asset is sent as {github.calls[3]['type']}")
        if json.loads(github.calls[4]["body"]) != {"draft": False}:
            report("released", f"the release is published with {github.calls[4]['body']}")

    done = run(node, script, github, "already-released", releases=[{"id": 9, "tag_name": TAG, "draft": False}])
    expect("already-released", done, github, False, [*listing], says="already released")

    for name, arguments in {
        "tag-is-not-a-contract-tag": {"tag": "v1.2.3"},
        "tag-has-a-path": {"tag": f"../{TAG}"},
        "tag-has-two-lines": {"tag": f"{TAG}\nx"},
        "no-title": {"title": ""},
        "title-of-another-release": {"title": "@chuggy/worker-contract 1.2.4"},
        "title-has-two-lines": {"title": f"{TITLE}\nx"},
        "title-is-not-a-name": {"title": "evil; rm 1.2.3"},
        "two-files": {"files": (TARBALL, "second.tgz")},
        "no-file": {"files": ()},
        "not-a-tarball": {"files": ("notes.txt",)},
        "a-link": {"link": True},
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

    done = run(node, script, github, "upload-address-elsewhere", upload_url="https://elsewhere.invalid/assets{?name}")
    expect(
        "upload-address-elsewhere",
        done,
        github,
        True,
        [*listing, ("POST", f"{base}/releases")],
        says="upload address",
    )
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
        raise SystemExit(f"contract-release: {len(FAILURES)} failed: {', '.join(FAILURES)}")


if __name__ == "__main__":
    main()
