#!/usr/bin/env python3
"""Refuse a rendered cluster whose self-service UI runs an image one of its
views was not read against, or mounts one where that image does not read it.

A VIEW IS RULES OVER ANOTHER PROGRAM'S MARKUP, and the image is one line of
`cluster/apps/ory-ui.yaml` that nothing else here reads. Under an image that
draws a card otherwise the tree evaluates as it does now.

`cluster/apps/ory/ui/login.hbs` closes the password form and leaves the GitHub
button by where the image draws each. An image that drew the two in one form
would have the view hide both: the card a person new here meets would offer the
link to a password and nothing else.

ITS SCRIPT PRESSES THE GITHUB BUTTON AND NOTHING ELSE. For a browser that
came from an invite link `login.hbs` presses the card's one answer, which is the
button that posts `provider=github`. So the view carries one script, the script
one press, and that press is a `click()` on what was read by
`button[name="provider"][value="github"]` and by nothing else; a script that
submits a form, dispatches an event or leaves the page another way is refused.
Whether the cookie it reads is the gate's is held by tests/kratos-github.py.

`cluster/apps/ory/ui/consent.hbs` ticks the permissions a client asked for and
hides the tick boxes the image draws them as. Under an image that drew a
permission as anything else it would tick nothing and hide nothing, and a
person would meet that image's card. Under one that drew something new beside
the tick boxes it could hide that as well.

`cluster/apps/ory/ui/logout.hbs` presses the Yes the image draws on its sign-out card, by
its id, after ending the identity's session. Under an image that drew it otherwise nothing
would be pressed and a person would meet that image's card, whose Yes ends only Hydra's
session.

`cluster/apps/ory/ui/standard_headers.hbs` and `ory_branding.hbs` replace two of
the image's partials, which its layouts include in every page but the welcome
one: the head, with the sheets a card is drawn in, and the line under a card.
Under an image whose layouts drew a page otherwise, its head could lack a sheet
it needs, and Ory's name could be drawn under the card again.

`cluster/apps/ory/ui/chuggy.css` and `favicon.svg` are added to the `public/`
the image serves at the host's root. The sheet sets the properties that image's
cards read their colours from; under one that read others, the cards would be
Ory's own light ones on chuggy's page.

So each view names the digest it was read against, and the Deployment is held
to it. The partials and the files added to `public/` are held as views are,
and are called views below. A refusal is not a defect in either file: it says the page has to be
looked at under the new image before the view names it.

AND TO THE PATH THE IMAGE READS THE VIEW FROM. A view mounted at any other
stops nothing: the pod starts, is ready, and draws the page from whatever is
at that path, which is the image's own view unless another is mounted there.
For the allow page that is the card whose Allow grants nothing pressed alone,
which `consent.hbs` is there to replace. The path is a fact about the image,
as the digest is, so it is written beside each view below.

READ FROM THE DEPLOYMENT, because the pod is what serves a view: the image is
that of the container which mounts it, and the text is the ConfigMap's which
that mount's volume names, under whatever name the render gave it.

AND EVERY FILE MOUNTED FROM THE VIEWS' ConfigMap IS ONE OF THEM, `welcome.hbs`
apart. A file mounted beside the views and not named below would be held to
nothing, and the image under it could change without this gate saying so.

WHAT THIS GATE CANNOT SEE. Whether a view is right for the image it names,
which takes a browser, or whether the path beside it is where that image reads
it, which takes the image. Nothing in this tree drives the one or opens the
other.
"""

import re
import sys
from typing import NamedTuple

import yaml

NAMESPACE = "ory"
DEPLOYMENT = "ory-ui"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


# The one button login.hbs's script may press, and the ways a script presses
# or leaves a page other than a click on it.
GITHUB_BUTTON = 'button[name="provider"][value="github"]'
SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
CLICK = re.compile(r"\b([A-Za-z_$][\w$]*)\s*(?:\?\.|\.)\s*click\s*\(")
OTHER_PRESS = re.compile(
    r"\b(?:click|submit|requestSubmit|dispatchEvent|fetch|XMLHttpRequest|sendBeacon|"
    r"assign|replace|open|eval|Function|setTimeout|setInterval)\b"
    r"|\blocation\s*(?:\.\s*href\s*)?=(?!=)"
)


def pressing(text):
    """Refuse a login view whose script presses anything but the GitHub button."""
    scripts = SCRIPT.findall(text)
    if len(scripts) != 1:
        refuse(
            f"login.hbs carries {len(scripts)} scripts, and is read as carrying one, which "
            "presses the GitHub button for a browser that came from an invite link"
        )
    script = scripts[0]
    clicks = CLICK.findall(script)
    if len(clicks) != 1:
        refuse(f"the script in login.hbs presses {len(clicks)} things, and presses one")
    pressed = clicks[0]
    bound = re.findall(
        rf"\b(?:const|let|var)\s+{re.escape(pressed)}\s*=\s*[\w$.]+\s*\.\s*querySelector\(\s*"
        rf"'{re.escape(GITHUB_BUTTON)}'\s*\)\s*;",
        script,
    )
    assigned = re.findall(rf"(?<![\w$.]){re.escape(pressed)}\s*=(?!=)", script)
    if len(bound) != 1 or len(assigned) != 1:
        refuse(
            f"the script in login.hbs presses {pressed}, which is not read once by "
            f"querySelector('{GITHUB_BUTTON}') and never assigned again: what it presses "
            "is the card's GitHub button alone"
        )
    rest = CLICK.sub("", script, count=1)
    other = sorted({found.group(0) for found in OTHER_PRESS.finditer(rest)})
    if other:
        refuse(
            f"the script in login.hbs also uses {', '.join(other)}: it presses the GitHub "
            "button by a click and does nothing else to the page"
        )


class View(NamedTuple):
    """What is held of one view: the path the image reads it from, what a
    person meets while it is mounted at another, and what there is to look at
    under another image before the view names it."""

    path: str
    elsewhere: str
    look: str


# `welcome.hbs` is mounted beside these and is not one of them: it replaces a
# layout whole and reads nothing the image draws.
UNHELD = {"welcome.hbs"}

VIEWS = {
    "login.hbs": View(
        path="/usr/src/app/views/login.hbs",
        elsewhere=(
            "At another path it does not draw the login page, which is then the image's own "
            "unless something else is mounted over that: the password form drawn open, for a "
            "person new here who has no password."
        ),
        look=(
            "The view hides parts of the login card by where that image draws them, so drive "
            "the card under the new image first -- as it arrives, after `Use a password`, after "
            "a refused password, after an expired flow, after a Cancel at GitHub -- and see the "
            "GitHub button on every one."
        ),
    ),
    "consent.hbs": View(
        path="/usr/src/app/views/consent.hbs",
        elsewhere=(
            "At another path it does not draw the allow page, which is then the image's own "
            "unless something else is mounted over that: a tick box for each permission, "
            "unticked, and an Allow that pressed alone grants none of them."
        ),
        look=(
            "The view ticks the permissions a client asked for and hides the tick boxes that "
            "image draws them as, so drive the allow page under the new image first -- press "
            "Allow and read the token answer for every permission that was asked, and open the "
            "page in a browser that runs no script to see everything that image draws and this "
            "card hides."
        ),
    ),
    "logout.hbs": View(
        path="/usr/src/app/views/logout.hbs",
        elsewhere=(
            "At another path it does not draw the sign-out page, which is then the image's own "
            "unless something else is mounted over that: a question whose Yes ends Hydra's "
            "session and leaves the identity's, so the next sign-in offers no choice of method."
        ),
        look=(
            "The view presses the card's Yes by the id that image draws it with, so drive a "
            "sign-out from the console under the new image first and sign in again to see the "
            "login page."
        ),
    ),
    "standard_headers.hbs": View(
        path="/usr/src/app/views/partials/standard_headers.hbs",
        elsewhere=(
            "At another path the image's layouts include their own head: Ory's favicon, a "
            "title that does not name chuggy, and no `chuggy.css`, so every page is Ory's light "
            "one."
        ),
        look=(
            "The partial links that image's sheets by the paths it serves them from, so open "
            "the login, consent, logout and error pages under the new image first, in light and "
            "dark, and see each card drawn whole in chuggy's colours."
        ),
    ),
    "ory_branding.hbs": View(
        path="/usr/src/app/views/partials/ory_branding.hbs",
        elsewhere=(
            "At another path the image's layout includes its own, and `Protected by` and Ory's "
            "mark are drawn under every card."
        ),
        look=(
            "The partial is empty because that image's layout draws Ory's name through it "
            "alone, so open a page under the new image first and see no `Protected by` under "
            "its card."
        ),
    ),
    "chuggy.css": View(
        path="/usr/src/app/public/chuggy.css",
        elsewhere=(
            "At another path it is not served at `/chuggy.css`, which `standard_headers.hbs` "
            "and `welcome.hbs` link, and every page is drawn in Ory's light theme."
        ),
        look=(
            "The sheet sets the `--ory-theme-*` properties that image's cards read, so open the "
            "login, consent and logout pages under the new image first, in light and dark, and "
            "see no colour of Ory's left on a card."
        ),
    ),
    "favicon.svg": View(
        path="/usr/src/app/public/favicon.svg",
        elsewhere=(
            "At another path it is not served at `/favicon.svg`, which `standard_headers.hbs` "
            "and `welcome.hbs` name, and a sign-in page's tab shows the browser's blank mark."
        ),
        look=(
            "The image is what serves `public/` at the host's root, so open `/favicon.svg` under "
            "the new image first and see chuggy's mark."
        ),
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


def hold(documents, pod, name, view):
    container, mount = only(
        [
            (container, mount)
            for container in pod["containers"] + pod.get("initContainers", [])
            for mount in container.get("volumeMounts", [])
            if mount.get("subPath") == name
        ],
        f"mount of {name} in Deployment {NAMESPACE}/{DEPLOYMENT}",
    )
    if mount.get("mountPath") != view.path:
        refuse(
            f"{name} is mounted at {mount.get('mountPath')} and the image reads it from "
            f"{view.path}. {view.elsewhere}"
        )
    volume = only(
        [volume for volume in pod.get("volumes", []) if volume["name"] == mount["name"]],
        f"volume named {mount['name']}",
    )
    if "configMap" not in volume:
        refuse(f"{name} is mounted from volume {volume['name']}, which is not a ConfigMap")
    text = in_namespace(documents, "ConfigMap", volume["configMap"]["name"])["data"].get(name)
    if text is None:
        refuse(f"ConfigMap {volume['configMap']['name']} carries no {name}")

    served = DIGEST.findall(container["image"])
    if len(served) != 1:
        refuse(
            f"container {container['name']} runs {container['image']}, "
            "which is not pinned by one digest"
        )
    read = sorted(set(DIGEST.findall(text)))
    if len(read) != 1:
        refuse(
            f"{name} names {len(read)} image digests and has to name the one it was read against"
        )
    if served != read:
        refuse(
            f"Deployment {NAMESPACE}/{DEPLOYMENT} runs {container['image']} and {name} was "
            f"read against {read[0]}. {view.look} Then name the new digest in the view."
        )
    if name == "login.hbs":
        pressing(text)


def unheld(pod):
    """The files mounted from a volume a view is mounted from, which this gate
    holds to nothing."""
    volumes = {
        mount["name"]
        for container in pod["containers"] + pod.get("initContainers", [])
        for mount in container.get("volumeMounts", [])
        if mount.get("subPath") in VIEWS
    }
    return sorted(
        {
            mount.get("subPath", f"the whole of volume {mount['name']}")
            for container in pod["containers"] + pod.get("initContainers", [])
            for mount in container.get("volumeMounts", [])
            if mount["name"] in volumes
            and mount.get("subPath") not in VIEWS
            and mount.get("subPath") not in UNHELD
        }
    )


def main():
    if len(sys.argv) != 2:
        refuse("usage: ory-ui-view.py RENDERED_MANIFEST")
    documents = documents_in(sys.argv[1])
    pod = in_namespace(documents, "Deployment", DEPLOYMENT)["spec"]["template"]["spec"]
    refused = [
        f"{name} is mounted beside the views and this gate holds it to no image and no path. "
        "Name it in VIEWS, with the path the image reads it from, and the digest in the file."
        for name in unheld(pod)
    ]
    for name, view in VIEWS.items():
        try:
            hold(documents, pod, name, view)
        except Refused as refusal:
            refused.append(str(refusal))
    if refused:
        refuse("\nory-ui-view: ".join(refused))


try:
    main()
except Refused as refusal:
    raise SystemExit(f"ory-ui-view: {refusal}") from None
