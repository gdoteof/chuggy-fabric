#!/usr/bin/env python3
"""Refuse a rendered cluster whose session pods are mislabelled or misadmitted.

Every assertion here is made against the rendered objects and against the labels
the scheduler is configured to place, never against the source files: the same
label is written in one manifest and selected in three others, and each of those
reads correctly on its own while the pod is unisolated.
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

    # 2. Where it may go is exactly the four destinations, and no more.
    reached = set()
    for rule in sessions["spec"].get("egress", []):
        if not rule.get("ports"):
            refuse("a chuggy-sessions egress arm names no port, so it admits every port")
        reached |= ports(rule)
    if reached != SESSION_EGRESS:
        refuse(f"chuggy-sessions egress is {sorted(reached)}, expected {sorted(SESSION_EGRESS)}")

    # 3. The worker's policy does not select a session, which is what keeps the
    #    two egress budgets from being one.
    workers = one(documents, "NetworkPolicy", "chuggy-workers", WORK)
    worker_selector = workers["spec"]["podSelector"].get("matchLabels", {})
    if all(labels.get(key) == value for key, value in worker_selector.items()):
        refuse("a session pod is also selected by chuggy-workers and inherits its egress")

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
