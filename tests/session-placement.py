#!/usr/bin/env python3
"""Refuse a rendered cluster whose session pods are mislabelled or misadmitted.

Every assertion here is made against the rendered objects and against the labels
the scheduler is configured to place, never against the source files: the same
label is written in one manifest and selected in three others, and each of those
reads correctly on its own while the pod is unisolated.

BOTH ENDS OF EVERY REACH, AND THE PORT IS THE EASY HALF. A policy's ports can be
exactly right while each selector beside them names a pod that does not exist --
a container name, a Service name, a rename that landed on one side. That failure
is silent in the direction that matters: the pod is Running, the placement
succeeded, the far end admits what it should, and the packets are simply dropped.
So each egress arm is resolved against the pod templates this directory declares
AND against the policy standing over that same workload, and no expectation here
is a label literal.
"""

import json
import sys
from pathlib import Path

import yaml

WORK = "chuggy-work"
CONTROL = "chuggy"
SESSION_LABELS_VARIABLE = "CHUG_SCHEDULER_SESSION_LABELS"

# Where a session pod may go, as (protocol, port). A session takes its turns and
# writes its transcript over the worker plane, reaches the API as an ordinary
# client, resolves names, and talks to the model over public HTTPS. PostgreSQL
# and the git service are absent because a slice-1 session makes no scratch
# database and takes no checkout -- and this set is exact, so gaining one is a
# finding rather than a silent widening.
SESSION_EGRESS = {("UDP", 53), ("TCP", 53), ("TCP", 3001), ("TCP", 3000), ("TCP", 443)}

# The two destinations a session's egress names by label, each paired with the
# policy that stands in front of that same workload. The pairing is what makes
# the port assertion mean something: a port set can be exactly right while every
# selector beside it names a pod that does not exist, and an egress arm selecting
# nothing is denied traffic silently -- the pod is Running, the placement
# succeeded, and the far end is fine. So each arm is resolved twice, against the
# pod templates this directory declares and against the policy protecting them,
# and neither expectation is a literal label written here.
SESSION_EGRESS_TARGETS = {
    ("TCP", 3001): "chuggy-worker-plane-ingress",
    ("TCP", 3000): "chuggy-api-admits-traefik-and-the-selector",
}

POD_TEMPLATE_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet")


def refuse(message):
    raise SystemExit(f"session placement: {message}")


def objects(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def one(documents, kind, name, namespace):
    found = [
        document
        for document in documents
        if document.get("kind") == kind
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == namespace
    ]
    if len(found) != 1:
        refuse(f"expected one {kind} {namespace}/{name}, found {len(found)}")
    return found[0]


def container(deployment, name):
    for entry in deployment["spec"]["template"]["spec"]["containers"]:
        if entry["name"] == name:
            return entry
    refuse(f"{deployment['metadata']['name']} has no container {name}")


def variable(entry, name):
    for item in entry.get("env", []):
        if item["name"] == name:
            if "value" not in item:
                refuse(f"{name} is not a literal value")
            return item["value"]
    return None


def ports(rule):
    return {(port.get("protocol", "TCP"), port["port"]) for port in rule.get("ports", [])}


def peer_admits(peer, namespace, labels):
    """Whether one `from`/`to` peer selects a pod in `namespace` carrying `labels`.

    A peer's namespaceSelector and podSelector are ANDed, and an absent
    namespaceSelector means the policy's own namespace -- which is the reading
    that made a `chuggy-work` pod carrying `chuggy.dev/api-client` reachable by
    nothing at all.
    """
    if "ipBlock" in peer:
        return False
    namespaces = peer.get("namespaceSelector")
    if namespaces is None:
        if namespace != peer["__policyNamespace"]:
            return False
    else:
        wanted = namespaces.get("matchLabels", {}).get("kubernetes.io/metadata.name")
        if wanted != namespace:
            return False
    pods = peer.get("podSelector")
    if pods is None:
        return True
    selected = pods.get("matchLabels", {})
    return all(labels.get(key) == value for key, value in selected.items())


def admits(policy, direction, namespace, labels, protocol, port):
    for rule in policy["spec"].get(direction, []) or []:
        peers = rule.get("from" if direction == "ingress" else "to", [])
        for peer in peers:
            peer = {**peer, "__policyNamespace": policy["metadata"]["namespace"]}
            if peer_admits(peer, namespace, labels) and (protocol, port) in ports(rule):
                return True
    return False


def pod_templates(documents):
    """Every pod this directory declares, as (namespace, labels).

    This is the universe a destination selector can be resolved against. A
    namespace absent from it declares no pod here -- `kube-system`, whose CoreDNS
    is the cluster's, and `chuggy-work`, whose pods the scheduler places at
    runtime -- and a selector aimed there is checked another way.
    """
    found = []
    for document in documents:
        if document.get("kind") in POD_TEMPLATE_KINDS:
            template = document["spec"]["template"]["metadata"]
            found.append((document["metadata"].get("namespace"), template.get("labels", {})))
        elif document.get("kind") == "Pod":
            metadata = document["metadata"]
            found.append((metadata.get("namespace"), metadata.get("labels", {})))
    return found


def peer_namespace(peer, own):
    """The namespace a peer names, or the policy's own where it names none."""
    namespaces = peer.get("namespaceSelector")
    if namespaces is None:
        return own
    return namespaces.get("matchLabels", {}).get("kubernetes.io/metadata.name")


def pods_selected(templates, namespace, selector):
    return [
        labels
        for space, labels in templates
        if space == namespace
        and all(labels.get(key) == value for key, value in selector.items())
    ]


def protects(policy):
    """The (namespace, selector) pair naming the workload a policy stands over."""
    return (
        policy["metadata"].get("namespace"),
        policy["spec"]["podSelector"].get("matchLabels", {}),
    )


def main():
    if len(sys.argv) != 2:
        refuse("usage: session-placement.py RENDERED_MANIFEST")
    documents = objects(sys.argv[1])

    scheduler = one(documents, "Deployment", "chuggy-scheduler", CONTROL)
    raw = variable(container(scheduler, "scheduler"), SESSION_LABELS_VARIABLE)
    if raw is None:
        refuse(f"the scheduler names no {SESSION_LABELS_VARIABLE}")
    labels = json.loads(raw)
    if not isinstance(labels, dict) or not labels:
        refuse(f"{SESSION_LABELS_VARIABLE} is not a non-empty object")

    # 1. A session pod is selected by its own policy, and that policy is the one
    #    that grants it nothing inbound.
    sessions = one(documents, "NetworkPolicy", "chuggy-sessions", WORK)
    selector = sessions["spec"]["podSelector"].get("matchLabels", {})
    if not selector:
        refuse("chuggy-sessions selects every pod in the namespace")
    missing = {key for key, value in selector.items() if labels.get(key) != value}
    if missing:
        refuse(f"placed session pods do not carry {sorted(missing)}, so no policy selects them")
    if set(sessions["spec"].get("policyTypes", [])) != {"Ingress", "Egress"}:
        refuse("chuggy-sessions does not isolate both directions")
    if sessions["spec"].get("ingress") != []:
        refuse("chuggy-sessions admits ingress; a session is never connected to")

    # 2. Where it may go is exactly the four destinations, and no more -- both
    #    the ports and the pods each arm names.
    templates = pod_templates(documents)
    workers = one(documents, "NetworkPolicy", "chuggy-workers", WORK)
    reached = set()
    for rule in sessions["spec"].get("egress", []):
        if not rule.get("ports"):
            refuse("a chuggy-sessions egress arm names no port, so it admits every port")
        opened = ports(rule)
        reached |= opened
        for peer in rule.get("to", []):
            # An ipBlock is the honest exception: the model is on the public
            # internet and no object in this cluster stands for it.
            if "ipBlock" in peer:
                continue
            namespace = peer_namespace(peer, WORK)
            selector = peer.get("podSelector", {}).get("matchLabels", {})
            if not selector:
                refuse(f"a chuggy-sessions arm for {sorted(opened)} selects a whole namespace")
            if any(space == namespace for space, _ in templates):
                # A namespace this directory declares pods in: the selector must
                # actually pick one out. This is what an arm pointed at a
                # container name, a Service name or a typo fails.
                if not pods_selected(templates, namespace, selector):
                    refuse(
                        f"a chuggy-sessions arm for {sorted(opened)} selects "
                        f"{selector} in {namespace}, which no declared pod carries"
                    )
            else:
                # `kube-system`'s CoreDNS is not ours to declare, so the
                # expectation is taken from the sibling policy in this same file
                # that reaches the same resolver rather than from a literal here.
                sibling = [
                    other
                    for arm in workers["spec"].get("egress", [])
                    if ports(arm) == opened
                    for other in arm.get("to", [])
                ]
                if peer not in sibling:
                    refuse(
                        f"a chuggy-sessions arm for {sorted(opened)} selects {selector} in "
                        f"{namespace}, which this directory declares no pod in and "
                        "chuggy-workers does not reach the same way"
                    )
        # And the workload it names is the one the far-end policy stands over,
        # so the two ends of a reach cannot drift apart while each reads right.
        for key, name in SESSION_EGRESS_TARGETS.items():
            if key not in opened:
                continue
            space, guarded = protects(one(documents, "NetworkPolicy", name, CONTROL))
            here = [
                labels
                for peer in rule.get("to", [])
                if "ipBlock" not in peer
                for labels in pods_selected(
                    templates,
                    peer_namespace(peer, WORK),
                    peer.get("podSelector", {}).get("matchLabels", {}),
                )
            ]
            if here != pods_selected(templates, space, guarded):
                refuse(
                    f"the chuggy-sessions arm for {key} does not select the pods "
                    f"{name} stands over"
                )
    if reached != SESSION_EGRESS:
        refuse(f"chuggy-sessions egress is {sorted(reached)}, expected {sorted(SESSION_EGRESS)}")

    # 3. No OTHER policy in the namespace selects a session, which is what keeps
    #    a session's egress budget its own. NetworkPolicies are additive, so
    #    naming `chuggy-workers` alone would leave a future third policy free to
    #    widen a session silently.
    for document in documents:
        if document.get("kind") != "NetworkPolicy":
            continue
        if document["metadata"].get("namespace") != WORK:
            continue
        name = document["metadata"]["name"]
        if name == "chuggy-sessions":
            continue
        other = document["spec"]["podSelector"].get("matchLabels", {})
        if all(labels.get(key) == value for key, value in other.items()):
            refuse(f"a session pod is also selected by {name} and inherits what it permits")

    # 4. Both reaches a session's egress permits are admitted at the other end.
    plane = one(documents, "NetworkPolicy", "chuggy-worker-plane-ingress", CONTROL)
    if not admits(plane, "ingress", WORK, labels, "TCP", 3001):
        refuse("the worker plane admits no session pod, so no turn is ever claimed")
    api = one(
        documents, "NetworkPolicy", "chuggy-api-admits-traefik-and-the-selector", CONTROL
    )
    if not admits(api, "ingress", WORK, labels, "TCP", 3000):
        refuse("the API admits no session pod, so its egress arm for 3000 reaches nothing")

    # 5. And the one reach it does not permit is refused at the other end too,
    #    so the absence is a boundary rather than a value nobody set.
    postgres = one(documents, "NetworkPolicy", "postgres-admits-labelled-clients", CONTROL)
    if admits(postgres, "ingress", WORK, labels, "TCP", 5432):
        refuse("PostgreSQL admits a session pod, which makes no scratch database")


if __name__ == "__main__":
    main()
