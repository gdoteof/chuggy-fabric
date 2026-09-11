#!/usr/bin/env python3
"""Refuse a rendered cluster that tells a pod to mint from a GitHub App key the
pod does not carry, or to mint as an App whose key the host does not hold.

A pod that mints its own installation tokens needs three things to agree: an App
id, a file the process opens, and a projection that puts the App's private key
at exactly that path. Each of the three reads correctly while another is wrong,
and neither wrong one is visible until the pod is running -- a path nothing
projects is an `ENOENT` at the first mint, and an id belonging to the other App
is a JWT signed with the wrong key, which GitHub refuses and nothing here can.

THE ID IS HELD AGAINST THE HOST AND NOT AGAINST A LITERAL. `chuggy.githubAppTokens`
on the host is where an App's id and its key file are declared together, and the
Secret a pod mounts is made by hand from that key file. So the id written in a
manifest is a second copy of the host's, and this is what makes them one value.

WHAT THIS GATE CANNOT SEE. Which Secret the key comes from, because a hand-made
Secret has no second declaration to be held against: nothing but the manifest
and the README's prerequisite 5 names it, and a gate over the manifest's own
literal would agree with it however it changed. Nor whether that Secret exists
or holds the App's key, which is the operator's step and no render's business.
Nor whether the image reads either variable: that is the release's, and the
manifests carry both before the image that reads them is pinned.
"""

import json
import sys

import yaml

CONTROL = "chuggy"

# Every workload told to mint, and which App it mints as. A pod that grows a key
# mount and is not added here is unchecked, and this file is where that is
# noticed or nowhere.
MINTERS = (("chuggy-api", "portal", "CHUG_API_FORGE_APP_ID", "CHUG_API_FORGE_APP_KEY_FILE"),)


def refuse(message):
    raise SystemExit(f"forge app key: {message}")


def workload(documents, name):
    found = [
        document
        for document in documents
        if document.get("kind") == "Deployment"
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == CONTROL
    ]
    if len(found) != 1:
        refuse(f"the render carries {len(found)} Deployment/{name} in {CONTROL}, wanted one")
    pod = found[0]["spec"]["template"]["spec"]
    containers = pod["containers"]
    if len(containers) != 1:
        refuse(f"{name} declares {len(containers)} containers, wanted one")
    return pod, containers[0]


def variable(container, name, owner):
    found = [entry for entry in container.get("env", []) if entry["name"] == name]
    if len(found) != 1:
        refuse(f"{owner} declares {name} {len(found)} times, wanted once")
    value = found[0].get("value")
    if value is None:
        refuse(f"{owner} takes {name} from somewhere other than a literal")
    return value


def projected(pod, container, wanted, owner):
    """The (secret, key) a container serves at an absolute path, or a refusal."""
    mounts = [
        mount
        for mount in container.get("volumeMounts", [])
        if wanted.startswith(mount["mountPath"].rstrip("/") + "/")
    ]
    if len(mounts) != 1:
        refuse(f"{len(mounts)} of {owner}'s volume mounts stand over {wanted}, wanted one")
    mount = mounts[0]
    if not mount.get("readOnly"):
        refuse(f"{owner} mounts its App key writable at {mount['mountPath']}")
    relative = wanted[len(mount["mountPath"].rstrip("/")) + 1 :]
    volume = [entry for entry in pod.get("volumes", []) if entry["name"] == mount["name"]]
    if len(volume) != 1:
        refuse(f"{owner} mounts {mount['name']}, which the pod declares {len(volume)} times")
    projection = volume[0].get("projected")
    sources = projection["sources"] if projection else [{"secret": volume[0].get("secret", {})}]
    served = {}
    for source in sources:
        secret = source.get("secret")
        if secret is None:
            refuse(f"{owner}'s {mount['name']} volume projects something other than a Secret")
        # A whole Secret projected serves every key at its own name, so a Secret
        # that has lost the key mounts an empty directory and the pod starts
        # without it. Naming the key is what makes the absence a FailedMount.
        for item in secret.get("items") or []:
            served[item["path"]] = (secret.get("name") or secret.get("secretName"), item["key"])
    if relative not in served:
        refuse(f"{owner} reads its App key from {wanted}, which its pod projects from no Secret key")
    return served[relative]


def main():
    if len(sys.argv) != 3:
        refuse("usage: forge-app-key.py APPS RENDERED_MANIFEST")
    with open(sys.argv[1], encoding="utf-8") as handle:
        apps = json.load(handle)
    with open(sys.argv[2], encoding="utf-8") as handle:
        documents = [document for document in yaml.safe_load_all(handle) if document]

    for name, app, id_variable, file_variable in MINTERS:
        if app not in apps:
            refuse(f"{name} mints as the {app} App, which the host does not declare")
        pod, container = workload(documents, name)
        declared = variable(container, id_variable, name)
        if declared != apps[app]["appId"]:
            refuse(
                f"{name} mints as App {declared}; the host holds the {app} App's key under "
                f"{apps[app]['appId']}, so that JWT is signed with the wrong key"
            )
        projected(pod, container, variable(container, file_variable, name), name)


main()
