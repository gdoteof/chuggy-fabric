#!/usr/bin/env python3
"""Refuse a generated Flux manifest whose source is not what the host states.

THE MANIFEST IS PARSED, because k3s parses it and applies nothing from a file
it cannot. A key at the wrong depth is text a grep finds and is not a manifest.

THE SOURCE IS HELD WHOLE against the host's own options. The one thing stated
apart from them is the credential reference, so that a host is held to carrying
none -- the bootstrap, which runs before the namespace a Secret would live in
exists -- or to exactly the one named.
"""

import json
import sys
from pathlib import Path

import yaml

NAMESPACE = "flux-system"
NAME = "fabric"
SOURCE = "GitRepository"


def refuse(message):
    raise SystemExit(f"flux-wiring: {message}")


def shown(spec, key):
    return json.dumps(spec[key], sort_keys=True) if key in spec else "absent"


def hold(described, document, expected):
    spec = document.get("spec") or {}
    differing = [
        f"{key}: expected {shown(expected, key)}, generated {shown(spec, key)}"
        for key in sorted(expected.keys() | spec.keys())
        if shown(expected, key) != shown(spec, key)
    ]
    if differing:
        refuse(f"{described} is not the spec held here -- " + "; ".join(differing))


def one(documents, kind):
    found = [
        document
        for document in documents
        if document.get("kind") == kind
        and document["metadata"] == {"name": NAME, "namespace": NAMESPACE}
    ]
    if len(found) != 1:
        refuse(f"expected one {kind} named {NAME} in `{NAMESPACE}`, found {len(found)}")
    return found[0]


def main():
    if len(sys.argv) != 3:
        refuse("usage: flux-wiring.py MANIFEST EXPECTED_JSON")
    try:
        documents = [
            document
            for document in yaml.safe_load_all(Path(sys.argv[1]).read_text())
            if document
        ]
    except yaml.YAMLError as failure:
        refuse(f"the manifest is not YAML, so k3s applies none of it: {failure}")
    host = json.loads(Path(sys.argv[2]).read_text())

    source = {
        "interval": host["sourceInterval"],
        "url": host["repositoryUrl"],
        "ref": {"branch": host["branch"]},
    }
    if host["secretRef"] is not None:
        source["secretRef"] = {"name": host["secretRef"]}
    hold(f"the {SOURCE}", one(documents, SOURCE), source)


if __name__ == "__main__":
    main()
