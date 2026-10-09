#!/usr/bin/env python3
"""Refuse a rendered cluster whose self-service UI runs an image its login view
was not read against.

THE VIEW IS RULES OVER ANOTHER PROGRAM'S MARKUP. `cluster/apps/ory/ui/login.hbs`
closes the password form and leaves the GitHub button by where the image draws
each, and the image is one line of `cluster/apps/ory-ui.yaml` that nothing else
here reads. An image that drew the two in one form would have the view hide
both: the card a person new here meets would offer the link to a password and
nothing else, and the tree would evaluate as it does now.

So the view names the digest it was read against, and the Deployment is held to
it. A refusal is not a defect in either file: it says the card has to be looked
at under the new image before the view names it.

READ FROM THE DEPLOYMENT, because the pod is what serves the view: the image is
that of the container which mounts it, and the text is the ConfigMap's which
that mount's volume names, under whatever name the render gave it.

WHAT THIS GATE CANNOT SEE. Whether the view is right for the image it names.
That takes a browser, and nothing in this tree drives one.
"""

import re
import sys

import yaml

NAMESPACE = "ory"
DEPLOYMENT = "ory-ui"
VIEW = "login.hbs"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def refuse(message):
    raise SystemExit(f"ory-ui-view: {message}")


def documents_in(path):
    with open(path, encoding="utf-8") as handle:
        return [document for document in yaml.safe_load_all(handle) if document]


def only(found, what):
    if len(found) != 1:
        refuse(f"expected one {what} and found {len(found)}")
    return found[0]


def in_namespace(documents, kind, name):
    return only(
        [
            document
            for document in documents
            if document.get("kind") == kind
            and document["metadata"].get("namespace") == NAMESPACE
            and document["metadata"]["name"] == name
        ],
        f"{kind} {NAMESPACE}/{name}",
    )


def main():
    if len(sys.argv) != 2:
        refuse("usage: ory-ui-view.py RENDERED_MANIFEST")
    documents = documents_in(sys.argv[1])
    pod = in_namespace(documents, "Deployment", DEPLOYMENT)["spec"]["template"]["spec"]

    container, mount = only(
        [
            (container, mount)
            for container in pod["containers"] + pod.get("initContainers", [])
            for mount in container.get("volumeMounts", [])
            if mount.get("subPath") == VIEW
        ],
        f"mount of {VIEW} in Deployment {NAMESPACE}/{DEPLOYMENT}",
    )
    volume = only(
        [volume for volume in pod.get("volumes", []) if volume["name"] == mount["name"]],
        f"volume named {mount['name']}",
    )
    if "configMap" not in volume:
        refuse(f"{VIEW} is mounted from volume {volume['name']}, which is not a ConfigMap")
    view = in_namespace(documents, "ConfigMap", volume["configMap"]["name"])["data"].get(VIEW)
    if view is None:
        refuse(f"ConfigMap {volume['configMap']['name']} carries no {VIEW}")

    served = DIGEST.findall(container["image"])
    if len(served) != 1:
        refuse(
            f"container {container['name']} runs {container['image']}, "
            "which is not pinned by one digest"
        )
    read = sorted(set(DIGEST.findall(view)))
    if len(read) != 1:
        refuse(
            f"{VIEW} names {len(read)} image digests and has to name the one it was read against"
        )
    if served != read:
        refuse(
            f"Deployment {NAMESPACE}/{DEPLOYMENT} runs {container['image']} and {VIEW} was "
            f"read against {read[0]}. The view hides parts of the login card by where that "
            "image draws them, so drive the card under the new image first -- as it arrives, "
            "after `Use a password`, after a refused password, after an expired flow, after a "
            "Cancel at GitHub -- and see the GitHub button on every one. Then name the new "
            "digest in the view."
        )


main()
