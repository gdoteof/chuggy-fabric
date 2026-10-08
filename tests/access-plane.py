#!/usr/bin/env python3
"""Refuse a rendered cluster whose access plane does not verify a token as the
API does.

The console reads both with one token. Answered 401, it renews that token once
and signs the person out where the fresh one is refused too -- kasofsk/chuggy's
`ui/chuggy-ui/app/browser/api.ts`. So a plane holding a token to another
issuer, audience or list of algorithms than the API's refuses what the API
accepts, and a page that reads it signs its reader out of the whole console.

EACH OF THE THREE IS WRITTEN TWICE, in chuggy-api.yaml and in
chuggy-access-plane.yaml, and each file reads correctly alone. The API's is the
original, argued where it is written; the plane's is a copy, and this holds the
copy to it as the string it is. A list of algorithms in another order is
refused with the rest: what is held is that nothing was typed twice
differently, and not what either process makes of what it reads.

WHAT THIS GATE CANNOT READ IT REFUSES rather than passes: a variable either
container names twice or not at all, one that is empty, one whose value comes
from a Secret or a ConfigMap, and one the kubelet would rewrite before the
process read it.

WHAT IT DOES NOT HOLD is that the original is right: that the issuer is the one
Hydra signs as, and the audience the one chuggy-ui.yaml has the console ask
for.
"""

import sys
from pathlib import Path

import yaml

CONTROL = "chuggy"

# (deployment, container)
API = ("chuggy-api", "api")
PLANE = ("chuggy-access-plane", "access-plane")

# (what a token is held to, the API's variable, the plane's copy of it)
HELD = (
    ("issuer", "CHUG_API_OIDC_ISSUER", "CHUG_ACCESS_PLANE_OIDC_ISSUER"),
    ("audience", "CHUG_API_OIDC_AUDIENCE", "CHUG_ACCESS_PLANE_OIDC_AUDIENCE"),
    ("list of algorithms", "CHUG_API_OIDC_ALGORITHMS", "CHUG_ACCESS_PLANE_OIDC_ALGORITHMS"),
)

# How a value names another variable, which the kubelet replaces with that
# variable's value where the container defines it.
REFERENCE = "$("


def refuse(message):
    raise SystemExit(f"access plane: {message}")


def environment(documents, workload):
    """The `env` of one container of one Deployment in the control namespace."""
    deployment, box = workload
    found = [
        document
        for document in documents
        if document.get("kind") == "Deployment"
        and document["metadata"]["name"] == deployment
        and document["metadata"].get("namespace") == CONTROL
    ]
    if len(found) != 1:
        refuse(f"expected one Deployment {CONTROL}/{deployment}, found {len(found)}")
    boxes = [
        entry
        for entry in found[0]["spec"]["template"]["spec"].get("containers") or []
        if entry["name"] == box
    ]
    if len(boxes) != 1:
        refuse(f"{deployment} has {len(boxes)} containers named {box}")
    return boxes[0].get("env") or []


def literal(env, workload, variable):
    """One variable's value, where the manifest states it and nothing else does."""
    entries = [item for item in env if item.get("name") == variable]
    if len(entries) != 1:
        refuse(f"{workload[0]} names {variable} {len(entries)} times, and this gate reads one")
    value = entries[0].get("value")
    if "valueFrom" in entries[0] or not isinstance(value, str) or not value:
        refuse(
            f"{workload[0]} does not give {variable} as a literal value, so what its "
            "process verifies a token against is not something this gate read"
        )
    if REFERENCE in value:
        refuse(
            f"{workload[0]} gives {variable} as {value!r}, which names another variable: "
            "the kubelet writes that one's value over it, and this gate reads the manifest"
        )
    return value


def main():
    if len(sys.argv) != 2:
        refuse("usage: access-plane.py RENDERED_MANIFEST")
    documents = [
        document for document in yaml.safe_load_all(Path(sys.argv[1]).read_text()) if document
    ]
    api = environment(documents, API)
    plane = environment(documents, PLANE)

    for held, original, copy in HELD:
        wanted = literal(api, API, original)
        given = literal(plane, PLANE, copy)
        if given != wanted:
            refuse(
                f"{copy} is {given!r} and {original} is {wanted!r}: the plane holds a "
                f"token to another {held} than the API does, so it answers 401 to a token "
                "the API accepts and the console signs that person out"
            )


if __name__ == "__main__":
    main()
