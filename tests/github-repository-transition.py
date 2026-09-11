#!/usr/bin/env python3
"""Refuse a build request the site declares no repository for, and a rendered
cluster carrying a per-repository token at all.

`repositories.nix` is where the site says which repositories it builds images
for, and the only thing it still produces per repository is the Git basic-auth
Secret Shipwright clones with. A build request names that Secret and that source
URL by hand -- `builds/` is immutable and generated, so nothing derives one from
the other -- and each reads correctly while the other is wrong: a request
cloning one repository with another's Secret is a build authenticated as the
wrong installation, and one naming a Secret this host does not mint is a build
that never starts.

SO THE BUILD REQUESTS ARE THE LOOP AND THE ROSTER IS WHAT THEY ARE HELD TO, in
that direction only. A repository is declared before the first request that
clones it and never after, so an entry with no request is admissible here and a
request with no entry is not.

AND THE OTHER HALF IS A NEGATIVE, because everything else a repository used to
need is gone: the api, the ticket service, the finalizer and the importer mint
their own credentials from the App key each mounts, and a work pod's is minted
by the plane. A per-repository token projected by any workload is that
subtraction coming back one manifest at a time, so no Secret named like one the
site used to mint may reach a pod in either namespace.

WHAT THIS GATE CANNOT SEE. Whether the Secrets exist -- the host mints them from
the same roster, and a rebuild is what delivers them. Whether the App key a pod
mounts is the App the pod names: `tests/forge-app-key.py` is where that lives.
"""

import json
import sys
from pathlib import Path

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


def check_build_requests(root, roster):
    requests = sorted(Path(root, "builds").glob("*/*/*.yaml"))
    if not requests:
        refuse("the tree carries no build request, so nothing holds the roster to anything")
    for path in requests:
        for document in documents_in(path):
            if document.get("kind") != "Build":
                continue
            owner = path.relative_to(root)
            git = document["spec"]["source"]["git"]
            entry = next(
                (entry for entry in roster.values() if entry["github"] == git["url"]), None
            )
            if entry is None:
                refuse(
                    f"{owner} builds {git['url']}, which the site does not declare; a "
                    "repository is added to repositories.nix before a request that clones it"
                )
            wanted = entry["tokens"]["buildReaderSecret"]
            if git.get("cloneSecret") != wanted:
                refuse(
                    f"{owner} clones {git['url']} with {git.get('cloneSecret')}; the site mints "
                    f"that repository's clone credential as {wanted}"
                )


def check_roster(roster):
    """The key is the repository's name on GitHub, which is what lets one entry
    name it in the URL a request clones and in the Secret it clones with."""
    for key, entry in roster.items():
        if not entry["github"].endswith(f"/{key}.git"):
            refuse(f"{key}'s github is {entry['github']}, which does not name {key}.git")
        if not entry["tokens"]["buildReaderSecret"].startswith(f"{key}-"):
            refuse(
                f"{key}'s clone credential is {entry['tokens']['buildReaderSecret']}, which is "
                f"not {key}'s"
            )


def main():
    if len(sys.argv) != 4:
        refuse("usage: github-repository-transition.py ROSTER RENDERED_MANIFEST ROOT")
    with open(sys.argv[1], encoding="utf-8") as handle:
        roster = json.load(handle)
    if not roster:
        refuse("the site declares no repositories")
    check_roster(roster)
    check_no_repository_tokens(documents_in(sys.argv[2]))
    check_build_requests(sys.argv[3], roster)


main()
