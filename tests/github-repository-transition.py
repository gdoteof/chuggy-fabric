#!/usr/bin/env python3
"""Refuse a rendered cluster carrying a per-repository token at all.

IT IS A NEGATIVE, because everything a repository used to need from this site
is gone: the api, the ticket service, the finalizer and the importer mint
their own credentials from the App key each mounts, and a work pod's is minted
by the plane. A per-repository token projected by any workload is that
subtraction coming back one manifest at a time, so no Secret named like one the
site used to mint may reach a pod in either namespace.

WHAT THIS GATE CANNOT SEE. Whether the App key a pod mounts is the App the pod
names: `tests/forge-app-key.py` is where that lives.
"""

import sys

import yaml

CONTROL = "chuggy"
WORK = "chuggy-work"

# What the site minted per repository before every pod that needed a credential
# minted its own. A projection of one is the defect this half of the gate is
# for, whatever workload grows it.
RETIRED_TOKEN_SUFFIXES = (
    "-github-reader-token",
    "-github-worker-token",
    "-github-finalizer-token",
)


def refuse(message):
    raise SystemExit(f"repositories: {message}")


def documents_in(path):
    with open(path, encoding="utf-8") as handle:
        return [document for document in yaml.safe_load_all(handle) if document]


def pod_of(document):
    """The pod template of a workload, or None for an object that has none."""
    if document.get("kind") == "CronJob":
        return document["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    if document.get("kind") in ("Deployment", "Job", "StatefulSet", "DaemonSet"):
        return document["spec"]["template"]["spec"]
    return None


def secrets_reaching(pod):
    """Every Secret this pod puts in a container, by whichever route.

    A volume, a projection, an env value and an envFrom are four ways to carry
    the same token, and a gate that read one of them would name the other three
    as the way to get a credential back in."""
    for volume in pod.get("volumes", []):
        secret = volume.get("secret")
        if secret is not None:
            yield secret.get("secretName") or secret.get("name")
        for source in (volume.get("projected") or {}).get("sources", []):
            if "secret" in source:
                yield source["secret"].get("name") or source["secret"].get("secretName")
    for container in pod.get("containers", []) + pod.get("initContainers", []):
        for entry in container.get("env", []):
            reference = (entry.get("valueFrom") or {}).get("secretKeyRef")
            if reference is not None:
                yield reference.get("name")
        for source in container.get("envFrom", []):
            if "secretRef" in source:
                yield source["secretRef"].get("name")


def check_no_repository_tokens(documents):
    for document in documents:
        if document["metadata"].get("namespace") not in (CONTROL, WORK):
            continue
        pod = pod_of(document)
        if pod is None:
            continue
        for name in secrets_reaching(pod):
            if name is None:
                continue
            if any(name.endswith(suffix) for suffix in RETIRED_TOKEN_SUFFIXES):
                refuse(
                    f"{document['kind']}/{document['metadata']['name']} carries {name}; a pod "
                    "that needs a repository's credential mints it from the App key it mounts, "
                    "and the site mints no per-repository token for a pod"
                )


def main():
    if len(sys.argv) != 2:
        refuse("usage: github-repository-transition.py RENDERED_MANIFEST")
    check_no_repository_tokens(documents_in(sys.argv[1]))


main()
