#!/usr/bin/env python3
"""Refuse a generated Flux manifest that is not the source and one root.

THE MANIFEST IS PARSED, because k3s parses it and applies nothing from a file
it cannot. A key at the wrong depth is text a grep finds and is not a manifest.

THE SOURCE IS HELD WHOLE against the host's own options. The one thing stated
apart from them is the credential reference, so that a host is held to carrying
none -- the bootstrap, which runs before the namespace a Secret would live in
exists -- or to exactly the one named.

THE SOURCE AND THE ROOT, AND NO LAYER. k3s applies this manifest on every start
and whenever a rebuild changes it, and the layers are declared under the path
the root applies. One generated here as well is a single object that k3s and
the root both reapply, each from its own text.

THE ROOT ORPHANS. k3s deletes an object that has left this manifest, and the
default deletion policy mirrors `prune`: a root deleted without
`deletionPolicy: Orphan` would delete every layer, and a layer deleted deletes
what it applied unless it orphans as well.

THE ROOT DOES NOT WAIT, because a root that waited would be unready whenever
any layer is; AND IT PRUNES, because a layer whose declaration was deleted
would otherwise go on applying a directory nothing in git names it for. The
rest of its spec is the host's options, and it is held whole like the source,
so a field nobody argued for is a refusal too.
"""

import json
import sys
from pathlib import Path

import yaml

NAMESPACE = "flux-system"
NAME = "fabric"
SOURCE = "GitRepository"
ROOT = "Kustomization"


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


def one(documents, api_version, kind):
    found = [
        document
        for document in documents
        if (document.get("apiVersion"), document.get("kind")) == (api_version, kind)
        and document["metadata"] == {"name": NAME, "namespace": NAMESPACE}
    ]
    if len(found) != 1:
        refuse(
            f"expected one {api_version} {kind} named {NAME} in `{NAMESPACE}`, found {len(found)}"
        )
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
    hold(f"the {SOURCE}", one(documents, "source.toolkit.fluxcd.io/v1", SOURCE), source)

    hold(
        f"the root {ROOT}",
        one(documents, "kustomize.toolkit.fluxcd.io/v1", ROOT),
        {
            "interval": host["interval"],
            "path": host["path"],
            "sourceRef": {"kind": SOURCE, "name": NAME},
            "prune": True,
            "wait": False,
            "deletionPolicy": "Orphan",
            "timeout": host["timeout"],
        },
    )

    if len(documents) != 2:
        held = sorted(
            f"{document.get('kind')}/{document['metadata'].get('name')}"
            for document in documents
        )
        refuse(
            f"the manifest holds {', '.join(held)}: more than the {SOURCE} and the "
            f"root, and a layer is declared under the path the root applies"
        )


if __name__ == "__main__":
    main()
