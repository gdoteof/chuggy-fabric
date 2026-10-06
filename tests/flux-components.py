#!/usr/bin/env python3
"""Hold what the checked-in Flux install has that an export of Flux does not.

A rule that keeps another namespace from the event intake, and an argument
that keeps k3s from owning what a layer applies. Each is this repository's and
not the export's, so each goes back after every export.

THE FAILURE. notification-controller delivers an event posted to its intake to
every Provider an Alert routes it to, signed with the Provider's key where it
has one. The intake asks its caller for nothing, so that signature says only
that notification-controller forwarded the event: a pod that reaches the intake
has Flux say, under Flux's signature, that any object reconciled at any commit.
Who reaches it is decided by the install's NetworkPolicies and nothing else.

THE EXPORT IS THE DEFECT. Before v2.9.4 (fluxcd/flux2#6028) `flux install
--export` writes `allow-webhooks` admitting every namespace to the pod with no
`ports`, and a rule with no `ports` admits on every port: the intake's as well
as the webhook receiver's the policy is named for. The checked-in install is
an older export with `ports` added to that one rule, so an older export
vendored over it takes them away and no line of this repository has changed
its mind. The policy is therefore held whole, as tests/flux-wiring.py holds
the sources -- every namespace, on the receiver's port, which is what a later
export writes unaided -- and a field nobody argued for is a refusal too.

EVERY POLICY IS READ, NOT THAT ONE. Policies add up: an export that kept this
one and widened another, or brought a new one, opens the intake as surely. For
each policy of the namespace that selects the pod, a rule admitting anything
but the namespace's own pods names its ports, and none of them is the
intake's. The namespace's own pods are admitted on every port by
`allow-egress` and have to be: the other controllers post their events there.

THE TWO PORTS ARE FOUND, NOT STATED. The intake is where the other controllers
are told to post: the Service their `--events-addr` names, followed through
its `targetPort` to the pod it selects. The receiver is what the Service
`webhook-receiver` reaches the same way. A release that moved either would
otherwise leave a number here guarding a port nothing listens on.

WHAT THIS CANNOT SEE. That the binary listens where its pod declares, and that
the cluster enforces a NetworkPolicy at all. And two callers no policy stops:
k3s's enforcer accepts whatever the pod's own node sends before it reads any
policy, which is every process on that host and every pod on its network.

A FIELD TAKEN OUT OF A LAYER STAYS ON THE CLUSTER WHERE K3S ONCE APPLIED THE
OBJECT. k3s applies what a host links into its manifests directory as the
field manager `deploy@` and the node's name, and goes on owning those fields
after the object is declared somewhere else. kustomize-controller applying
that object from cluster/flux/ is then one owner of two: it drops a field the
declaration no longer has, the other owner still holds it, the value stays and
the apply says `unchanged`. So kustomize-controller is started with
`--override-manager=deploy@`, which has it take for itself, on every object it
applies, what a manager of that prefix holds. That acts on what
kustomize-controller applies and nothing else, so what k3s still applies --
the install, the two sources and the root -- stays k3s's. An object declared
to both would be taken from k3s at each apply of its layer, and this does not
look for one.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

EVENTS = "--events-addr="
APPLIER = "kustomize-controller"
OVERRIDE = "--override-manager"
K3S = "deploy@"
RECEIVER = "webhook-receiver"
POLICY = "allow-webhooks"


def refuse(message):
    raise SystemExit(f"flux-components: {message}")


def shown(value):
    return json.dumps(value, sort_keys=True)


def tcp(entry):
    return entry.get("protocol", "TCP") == "TCP"


def of(documents, kind, namespace):
    return [
        document
        for document in documents
        if document.get("kind") == kind
        and document["metadata"].get("namespace") == namespace
    ]


def one(documents, kind, namespace, name):
    found = [
        document
        for document in of(documents, kind, namespace)
        if document["metadata"]["name"] == name
    ]
    if len(found) != 1:
        refuse(f"expected one {kind} `{name}` in `{namespace}`, found {len(found)}")
    return found[0]


def posted_to(documents):
    """The one address the install's controllers post their events to."""
    addresses = sorted(
        {
            argument[len(EVENTS) :]
            for document in documents
            if document.get("kind") == "Deployment"
            for container in document["spec"]["template"]["spec"]["containers"]
            for argument in container.get("args") or []
            if argument.startswith(EVENTS)
        }
    )
    if len(addresses) != 1:
        refuse(
            f"the controllers post their events to {shown(addresses)}, and the "
            f"intake is found as the one address they all name"
        )
    address = urlsplit(addresses[0])
    labels = (address.hostname or "").split(".")
    if address.scheme != "http" or len(labels) < 2:
        refuse(f"`{EVENTS}{addresses[0]}` does not name a Service by `http://NAME.NAMESPACE`")
    return labels[0], labels[1], address.port or 80


def reached(service, declared, port):
    """The number of the pod's port that a Service's port forwards to."""
    described = f"the Service `{service['metadata']['name']}`"
    ports = [
        entry
        for entry in service["spec"]["ports"]
        if tcp(entry) and port in (None, entry["port"])
    ]
    if len(ports) != 1:
        refuse(f"{described} has {len(ports)} TCP ports where one was looked for")
    target = ports[0].get("targetPort", ports[0]["port"])
    number = declared.get(target) if isinstance(target, str) else target
    if number is None:
        refuse(f"{described} forwards to `{target}`, which its pod does not declare")
    return number


def selects(policy, labels):
    selector = policy["spec"].get("podSelector") or {}
    if set(selector) - {"matchLabels"}:
        refuse(
            f"the NetworkPolicy `{policy['metadata']['name']}` selects its pods "
            f"by other than `matchLabels`, which this does not read"
        )
    return all(
        labels.get(key) == value
        for key, value in (selector.get("matchLabels") or {}).items()
    )


def outsiders(rule):
    """Whether a rule admits anything but pods of the policy's own namespace."""
    peers = rule.get("from")
    return not peers or any(set(peer) != {"podSelector"} for peer in peers)


def admits(rule, number, declared):
    """Whether a rule admits TCP to the numbered port of the pod."""
    entries = rule.get("ports")
    if not entries:
        return True
    for entry in entries:
        if not tcp(entry):
            continue
        port = entry.get("port")
        if port is None:
            return True
        if isinstance(port, str):
            if declared.get(port) == number:
                return True
        elif port <= number <= entry.get("endPort", port):
            return True
    return False


def main():
    if len(sys.argv) != 2:
        refuse("usage: flux-components.py MANIFEST")
    try:
        documents = [
            document
            for document in yaml.safe_load_all(Path(sys.argv[1]).read_text())
            if document
        ]
    except yaml.YAMLError as failure:
        refuse(f"the manifest is not YAML, so k3s applies none of it: {failure}")

    name, namespace, port = posted_to(documents)
    intake_service = one(documents, "Service", namespace, name)
    receiver_service = one(documents, "Service", namespace, RECEIVER)
    selector = intake_service["spec"]["selector"]
    if receiver_service["spec"]["selector"] != selector:
        refuse(
            f"the Services `{name}` and `{RECEIVER}` no longer select the same "
            f"pods, and what is held here was argued for one pod with both ports"
        )
    pods = [
        document["spec"]["template"]
        for document in of(documents, "Deployment", namespace)
        if all(
            document["spec"]["template"]["metadata"]["labels"].get(key) == value
            for key, value in selector.items()
        )
    ]
    if len(pods) != 1:
        refuse(f"the Service `{name}` selects the pods of {len(pods)} Deployments")
    labels = pods[0]["metadata"]["labels"]
    declared = {
        entry["name"]: entry["containerPort"]
        for container in pods[0]["spec"]["containers"]
        for entry in container.get("ports") or []
        if tcp(entry) and "name" in entry
    }
    intake = reached(intake_service, declared, port)
    receiver = reached(receiver_service, declared, None)
    if intake == receiver:
        refuse(
            f"the event intake and the webhook receiver are both port {intake}, "
            f"and no policy admits a caller to one and not the other"
        )

    policy = one(documents, "NetworkPolicy", namespace, POLICY)
    held = {
        "ingress": [
            {
                "from": [{"namespaceSelector": {}}],
                "ports": [{"port": receiver, "protocol": "TCP"}],
            }
        ],
        "podSelector": {"matchLabels": selector},
        "policyTypes": ["Ingress"],
    }
    differing = [
        f"{key}: expected {shown(held.get(key))}, found {shown(policy['spec'].get(key))}"
        for key in sorted(held.keys() | policy["spec"].keys())
        if held.get(key) != policy["spec"].get(key)
    ]
    if differing:
        refuse(
            f"the NetworkPolicy `{POLICY}` is not the one held here -- "
            + "; ".join(differing)
            + f". Flux before v2.9.4 exports it with no `ports`, which admits "
            f"every namespace to the event intake on {intake} as well: until "
            f"the install is that or later the `ports` are this repository's, "
            f"and go back after every export"
        )

    for policy in of(documents, "NetworkPolicy", namespace):
        spec = policy["spec"]
        if "Ingress" not in spec.get("policyTypes", ["Ingress"]):
            continue
        if not selects(policy, labels):
            continue
        for rule in spec.get("ingress") or []:
            if outsiders(rule) and admits(rule, intake, declared):
                refuse(
                    f"the NetworkPolicy `{policy['metadata']['name']}` admits "
                    f"more than the pods of `{namespace}` to port {intake} of "
                    f"the pod the Service `{name}` selects, which is the event "
                    f"intake: {shown(rule)}"
                )

    overridden = [
        argument
        for container in one(documents, "Deployment", namespace, APPLIER)["spec"][
            "template"
        ]["spec"]["containers"]
        for argument in container.get("args") or []
        if argument.split("=")[0] == OVERRIDE
    ]
    if overridden != [f"{OVERRIDE}={K3S}"]:
        refuse(
            f"`{APPLIER}` is started with {shown(overridden)} where "
            f"{shown([f'{OVERRIDE}={K3S}'])} is held. Without it a field taken "
            f"out of a layer k3s once applied stays on the cluster; the export "
            f"does not write it, so it goes back after every export"
        )

    print(
        f"flux-components: `{POLICY}` admits every namespace to the webhook "
        f"receiver on {receiver}, no policy admits one to the event intake on "
        f"{intake}, and `{APPLIER}` overrides the manager `{K3S}`"
    )


if __name__ == "__main__":
    main()
