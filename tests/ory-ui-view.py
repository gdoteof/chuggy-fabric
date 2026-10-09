#!/usr/bin/env python3
"""Refuse a rendered cluster whose self-service UI runs an image one of its
views was not read against.

A VIEW IS RULES OVER ANOTHER PROGRAM'S MARKUP, and the image is one line of
`cluster/apps/ory-ui.yaml` that nothing else here reads. Under an image that
draws a card otherwise the tree evaluates as it does now.

`cluster/apps/ory/ui/login.hbs` closes the password form and leaves the GitHub
button by where the image draws each. An image that drew the two in one form
would have the view hide both: the card a person new here meets would offer the
link to a password and nothing else.

`cluster/apps/ory/ui/consent.hbs` ticks the permissions a client asked for and
hides the tick boxes the image draws them as. An image that drew a permission
as anything else would leave nothing ticked and nothing unticked to see: the
card would offer Deny and Allow, and Allow would grant nothing.

So each view names the digest it was read against, and the Deployment is held
to it. A refusal is not a defect in either file: it says the page has to be
looked at under the new image before the view names it.

READ FROM THE DEPLOYMENT, because the pod is what serves a view: the image is
that of the container which mounts it, and the text is the ConfigMap's which
that mount's volume names, under whatever name the render gave it.

WHAT THIS GATE CANNOT SEE. Whether a view is right for the image it names.
That takes a browser, and nothing in this tree drives one. Nor where a mount
puts its view: moved to a path the image does not read, it passes here while
the image serves its own page.
"""

import re
import sys

import yaml

NAMESPACE = "ory"
DEPLOYMENT = "ory-ui"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

# Each view held, with what there is to look at under another image before the
# view names it. `welcome.hbs` is mounted beside them and is not one: it
# replaces a layout whole and reads nothing the image draws.
VIEWS = {
    "login.hbs": (
        "The view hides parts of the login card by where that image draws them, so drive "
        "the card under the new image first -- as it arrives, after `Use a password`, after "
        "a refused password, after an expired flow, after a Cancel at GitHub -- and see the "
        "GitHub button on every one."
    ),
    "consent.hbs": (
        "The view ticks the permissions a client asked for and hides the tick boxes that "
        "image draws them as, so drive the allow page under the new image first -- press "
        "Allow and read the token answer for every permission that was asked, and open the "
        "page in a browser that runs no script to see the image's boxes."
    ),
}


class Refused(Exception):
    """A refusal. One raised over a view is kept, and the next view is read."""


def refuse(message):
    raise Refused(message)


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


def hold(documents, pod, view, look):
    container, mount = only(
        [
            (container, mount)
            for container in pod["containers"] + pod.get("initContainers", [])
            for mount in container.get("volumeMounts", [])
            if mount.get("subPath") == view
        ],
        f"mount of {view} in Deployment {NAMESPACE}/{DEPLOYMENT}",
    )
    volume = only(
        [volume for volume in pod.get("volumes", []) if volume["name"] == mount["name"]],
        f"volume named {mount['name']}",
    )
    if "configMap" not in volume:
        refuse(f"{view} is mounted from volume {volume['name']}, which is not a ConfigMap")
    text = in_namespace(documents, "ConfigMap", volume["configMap"]["name"])["data"].get(view)
    if text is None:
        refuse(f"ConfigMap {volume['configMap']['name']} carries no {view}")

    served = DIGEST.findall(container["image"])
    if len(served) != 1:
        refuse(
            f"container {container['name']} runs {container['image']}, "
            "which is not pinned by one digest"
        )
    read = sorted(set(DIGEST.findall(text)))
    if len(read) != 1:
        refuse(
            f"{view} names {len(read)} image digests and has to name the one it was read against"
        )
    if served != read:
        refuse(
            f"Deployment {NAMESPACE}/{DEPLOYMENT} runs {container['image']} and {view} was "
            f"read against {read[0]}. {look} Then name the new digest in the view."
        )


def main():
    if len(sys.argv) != 2:
        refuse("usage: ory-ui-view.py RENDERED_MANIFEST")
    documents = documents_in(sys.argv[1])
    pod = in_namespace(documents, "Deployment", DEPLOYMENT)["spec"]["template"]["spec"]
    refused = []
    for view, look in VIEWS.items():
        try:
            hold(documents, pod, view, look)
        except Refused as refusal:
            refused.append(str(refusal))
    if refused:
        refuse("\nory-ui-view: ".join(refused))


try:
    main()
except Refused as refusal:
    raise SystemExit(f"ory-ui-view: {refusal}") from None
