#!/usr/bin/env python3
"""Refuse a tree whose committed build results are not the results of the
requests it carries.

`results/` exists so that `scripts/render-image-promotion` can be run from any
checkout: it takes one checksummed record and never reaches the host that made
it. That makes the records deployment inputs sitting in Git, and the way they go
wrong is not corruption -- the recorder's checksum would catch that -- but
identity. A record filed under the wrong commit, or under a request nothing
declares, verifies against itself perfectly and promotes the wrong image.

SO NOTHING BELOW READS A RECORD ALONE. Every result names a request:
`results/<repository-id>/<source-commit>/<request-digest>/<attempt>.json` is
`builds/<repository-id>/<source-commit>/<request-digest>.yaml` with the attempt
added, and that manifest is where the identities come from. What the record
claims about its repository, commit, target image, renderer, controller and
profile is compared against the request rather than against a constant here, and
`scripts/verify-build-provenance` -- the same command `retry-build-request` and
`retire-build-request` gate on -- is what does the comparing. This gate supplies
the record and the identities; it decides nothing about provenance itself.

THE ATTEMPT PAIR IS THE FILE'S, NOT THE MANIFEST'S. A retried request has one
live attempt in `builds/` and every attempt's record in `results/`, so holding a
record against the manifest's ordinal would refuse exactly the history this
directory exists to keep. The attempt name and ordinal come from the file name,
and the verifier is what holds them to the request digest.

A RESULT WHOSE REQUEST IS GONE IS A FINDING, and that is the one thing this gate
asks of the retirement flow: `scripts/retire-build-request` removes a
declaration from `builds/`, and doing that to a request whose result is
committed leaves this gate with a result it cannot resolve. Retirement of a
published request is not supported yet, and the runbook says so where the
ordered commands are.

WHAT THIS GATE CANNOT SEE. Whether the record is the one the cluster actually
produced -- the recorder's checksum covers the bytes, and nothing here can ask
Shipwright what it built. Whether a request that has no result here failed,
is still running, or was never applied. And whether the registry still serves
the digest a successful record names, which is `render-image-promotion`'s own
check at the moment of promotion and deliberately not a property of the tree.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

DIGEST = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
REPOSITORY_ID = re.compile(r"[a-z0-9](?:[-a-z0-9.]{0,61}[a-z0-9])?")
ATTEMPT = re.compile(r"(?P<name>[a-z0-9][-a-z0-9.]*)-a(?P<ordinal>[1-9][0-9]*)")
KEEPFILE = ".gitkeep"
RECORD = ".json"
CHECKSUM = ".json.sha256"


def refuse(message):
    raise SystemExit(f"build results: {message}")


def checksum_of(path):
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def located(results):
    """Every record under `results/`, as (relative path, repository, commit,
    request, attempt). A file that is not a record or its checksum, or one at a
    depth the layout does not have, is refused here rather than skipped: a
    result nothing reads is a result nothing checks."""
    records = []
    checksums = set()
    for path in sorted(results.rglob("*")):
        relative = path.relative_to(results)
        if path.is_symlink():
            refuse(f"{relative} is a symbolic link")
        if path.is_dir():
            continue
        if relative.as_posix() == KEEPFILE:
            continue
        if len(relative.parts) != 4:
            refuse(
                f"{relative} is not "
                "<repository-id>/<source-commit>/<request-digest>/<attempt>.json"
            )
        repository, commit, request, filename = relative.parts
        if filename.endswith(CHECKSUM):
            checksums.add(relative)
            continue
        if not filename.endswith(RECORD):
            refuse(f"{relative} is neither a record nor a record's checksum")
        if REPOSITORY_ID.fullmatch(repository) is None:
            refuse(f"{relative} is filed under {repository!r}, which is not a repository id")
        if COMMIT.fullmatch(commit) is None:
            refuse(f"{relative} is filed under {commit!r}, which is not a full source commit")
        if DIGEST.fullmatch(request) is None:
            refuse(f"{relative} is filed under {request!r}, which is not a request digest")
        attempt = ATTEMPT.fullmatch(filename[: -len(RECORD)])
        if attempt is None:
            refuse(f"{relative} is not an attempt of that request")
        records.append((relative, repository, commit, request, attempt))
    orphans = sorted(
        checksum.as_posix()
        for checksum in checksums
        if checksum.with_name(checksum.name[: -len(CHECKSUM)] + RECORD)
        not in {record[0] for record in records}
    )
    if orphans:
        refuse(f"{orphans[0]} checksums a record this tree does not carry")
    return records


def main():
    if len(sys.argv) != 3:
        refuse("usage: build-results.py ROOT SCRIPTS")
    root = Path(sys.argv[1])
    scripts = Path(sys.argv[2])
    # Run against a checkout rather than the store copy and the import below
    # would leave a __pycache__ in scripts/, which is a build artifact in a
    # directory this repository tracks by hand.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(scripts))
    from build_provenance import manifest_identities, verify_record

    results = root / "results"
    if not results.is_dir():
        refuse("results/ is not a directory, and AGENTS.md says this tree records provenance")

    for relative, repository, commit, request, attempt in located(results):
        record = results / relative
        checksum = record.with_name(record.name[: -len(RECORD)] + CHECKSUM)
        if not checksum.is_file():
            refuse(f"{relative} has no checksum beside it")
        stored = checksum.read_text().strip()
        if stored != checksum_of(record):
            refuse(f"{relative} does not match the checksum beside it")

        manifest = root / "builds" / repository / commit / f"{request}.yaml"
        if not manifest.is_file():
            refuse(f"{relative} answers {manifest.relative_to(root)}, which this tree does not carry")
        identities = dict(manifest_identities(manifest.read_text())[1])
        if identities["request"] != f"sha256:{request}":
            refuse(f"{manifest.relative_to(root)} declares another request digest")
        if identities["repository"] != repository or identities["source_commit"] != commit:
            refuse(f"{manifest.relative_to(root)} declares another repository or source commit")

        carried = json.loads(record.read_text())
        if carried.get("result", {}).get("requestDigest") != f"sha256:{request}":
            refuse(f"{relative} records another request digest")

        identities["attempt"] = attempt.group()
        identities["ordinal"] = int(attempt.group("ordinal"))
        verify_record(record, identities)


main()
