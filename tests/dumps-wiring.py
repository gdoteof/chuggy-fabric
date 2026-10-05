#!/usr/bin/env python3
"""Refuse a rendered cluster whose dumps claim is not over the host's dumps
directory.

The path is written twice and neither copy reads the other:
`chuggy.state.dumps.path`, which the machine layer creates a directory from and
sets the owner and mode of, and `local.path` on the PersistentVolume the claim
names. Where they differ the claim binds all the same, because binding consults
no filesystem, and a pod mounting it waits in `ContainerCreating` on a
directory that is not there -- or, where the other path happens to exist,
mounts one this host did not make for it.

READ FROM THE CLAIM, because the claim is what a pod mounts: the volume it
names is resolved and that volume's path is held to the host's. A claim that
names no volume and a volume that is not `local` are refused rather than
passed, since neither has a path this can compare.
"""

import sys
from pathlib import Path

import yaml

NAMESPACE = "chuggy"
CLAIM = "chuggy-dumps"


def refuse(message):
    raise SystemExit(f"dumps-wiring: {message}")


def named(documents, kind, name, namespace=None):
    found = [
        document
        for document in documents
        if document.get("kind") == kind
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == namespace
    ]
    if len(found) != 1:
        described = f"{namespace}/{name}" if namespace else name
        refuse(f"expected one {kind} {described}, found {len(found)}")
    return found[0]


def main():
    if len(sys.argv) != 3:
        refuse("usage: dumps-wiring.py RENDERED_MANIFEST HOST_PATH")
    documents = [
        document for document in yaml.safe_load_all(Path(sys.argv[1]).read_text()) if document
    ]
    host_path = sys.argv[2]

    volume_name = named(documents, "PersistentVolumeClaim", CLAIM, NAMESPACE)["spec"].get(
        "volumeName"
    )
    if not volume_name:
        refuse(f"claim {NAMESPACE}/{CLAIM} names no volume, so what it binds was not read")
    bound = (named(documents, "PersistentVolume", volume_name)["spec"].get("local") or {}).get(
        "path"
    )
    if bound is None:
        refuse(f"PersistentVolume {volume_name} is not a local volume and has no path to compare")
    if bound != host_path:
        refuse(
            f"claim {NAMESPACE}/{CLAIM} binds {bound} through PersistentVolume {volume_name}, "
            f"and the host creates {host_path}"
        )

    print(f"clean: {NAMESPACE}/{CLAIM} binds {bound}, which the host creates")


if __name__ == "__main__":
    main()
