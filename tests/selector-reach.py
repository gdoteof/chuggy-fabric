#!/usr/bin/env python3
"""Refuse a rendered cluster where the selector's configuration and its egress disagree.

The selector is the one workload here whose destinations are written twice: once
as URLs inside `CHUG_SELECTOR_CONFIG`, and once as peers and ports on
`chuggy-selector-egress`. Nothing but a reader has ever held the two together,
and at zero replicas nothing had to -- the retired configuration named a policy
host on port 8080 that no arm permitted and no Service resolved, and that stood
in the file for as long as the number below it was zero. A running replica is
what turns that class of mistake into a process that reaches for something and
is dropped, so this is the gate that arrives with the one.

BOTH DIRECTIONS, BECAUSE EACH HALF IS SILENT ON ITS OWN. A URL with no arm is a
connection refused by the pod's own policy; an arm with no URL is a permission
granted to nothing, which is how a retirement leaves a hole behind that reads
like a rule somebody meant. So every URL the configuration names must be
permitted, and every arm but DNS must be claimed by a URL.

THE PORT IS THE POD'S AND THE URL'S IS THE SERVICE'S. A NetworkPolicy is matched
against the destination pod after the ClusterIP has been translated away, so an
arm is checked against the container port the Service's `targetPort` resolves to
-- by name where it is a name -- and never against the number in the URL. Two of
the three targets here are named ports, so an arm copied from a URL would be
wrong for both.

WHAT THIS GATE CANNOT RESOLVE IT REFUSES rather than passes: a host that is not
a cluster-local Service name, a `targetPort` that no selected container
publishes, a namespaceSelector on a label other than `kubernetes.io/metadata.name`,
and a podSelector by matchExpressions alone are each legal and each outside what
is evaluated here, so each is a finding to answer instead of a silence to trust.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

CONTROL = "chuggy"
DEPLOYMENT = "chuggy-selector"
CONTAINER = "selector"
CONFIGURATION_VARIABLE = "CHUG_SELECTOR_CONFIG"
EGRESS = "chuggy-selector-egress"

# The retired trusted policy protocol, by the two names it was written under.
# Neither may appear anywhere in the selector's rendered pod, in any field: a
# `policy` block refuses the process outright once the schema drops it, and a
# `secretKeyRef` on the bearer token mounts a key nothing reads.
RETIRED_CONFIGURATION_KEY = "policy"
RETIRED_SECRET_KEY = "policy-bearer-token"

# The suffix a cluster-local Service name carries. A host without it is either
# outside the cluster or a short name whose namespace depends on the pod's own
# search path, and neither is resolvable here.
CLUSTER_SUFFIX = ".svc.cluster.local"

# DNS is the one arm no URL names: every host below is a name, so resolving them
# is a precondition of reaching any of them rather than a destination of its own.
# Its peers are held against the sibling arm on the same ports elsewhere in the
# render, so where CoreDNS is stays one statement in this tree.
DNS_PORTS = frozenset({("UDP", 53), ("TCP", 53)})

POD_TEMPLATE_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet")

INTERPOLATION = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")


def refuse(message):
    raise SystemExit(f"selector reach: {message}")


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


def configuration(entry):
    """The configuration document as the process reads it, `$(VAR)` resolved.

    The kubelet substitutes a `$(VAR)` naming another variable on the same
    container and leaves one that names nothing standing as literal text. A
    deleted variable that something still interpolates is therefore not an
    error anywhere: the process is handed `$(CHUG_SELECTOR_POLICY_TOKEN)` as a
    value, which is a string of exactly the right type and no use at all. So a
    reference this container does not declare is refused here.
    """
    declared = {item["name"] for item in entry.get("env", [])}
    for item in entry.get("env", []):
        if item["name"] != CONFIGURATION_VARIABLE:
            continue
        if "value" not in item:
            refuse(f"{CONFIGURATION_VARIABLE} is not a literal value")
        text = item["value"]
        missing = {name for name in INTERPOLATION.findall(text) if name not in declared}
        if missing:
            refuse(
                f"{CONFIGURATION_VARIABLE} interpolates {sorted(missing)}, which this "
                "container does not declare, so the process is handed the literal text"
            )
        resolved = INTERPOLATION.sub(lambda match: f"resolved-{match.group(1)}", text)
        try:
            return json.loads(resolved)
        except json.JSONDecodeError as failure:
            refuse(f"{CONFIGURATION_VARIABLE} is not JSON once interpolated: {failure}")
    refuse(f"the selector names no {CONFIGURATION_VARIABLE}")


def urls(value):
    """Every URL string anywhere in the configuration document."""
    if isinstance(value, str):
        return [value] if "://" in value else []
    if isinstance(value, dict):
        return [found for item in value.values() for found in urls(item)]
    if isinstance(value, list):
        return [found for item in value for found in urls(item)]
    return []


def destinations(document):
    """The (namespace, service, port) each URL in the configuration reaches.

    NOT EVERY URL IN THIS DOCUMENT IS A PLACE. The audience the token must carry
    and the issuer the principal is derived from are both written as URLs and
    neither is ever opened; a gate that treated them as destinations would
    demand an egress arm for an identifier. What tells them apart is the port: a
    reach in this document names one explicitly, an identifier never does. So a
    host with no port is read as a name, and a host with a port that this
    directory cannot resolve to a Service is refused rather than skipped.

    That leaves one residual, and it is the reverse check below that covers it:
    a destination moved outside the cluster stops being resolvable here, and
    what catches it is the arm it leaves behind with nothing naming it.
    """
    found = set()
    for url in urls(document):
        parts = urlsplit(url)
        if parts.hostname is None or parts.port is None:
            continue
        if not parts.hostname.endswith(CLUSTER_SUFFIX):
            refuse(
                f"the configuration reaches {parts.hostname}:{parts.port}, which is not a "
                "cluster-local Service name and cannot be resolved to a pod here"
            )
        labels = parts.hostname[: -len(CLUSTER_SUFFIX)].split(".")
        if len(labels) != 2:
            refuse(f"the configuration names {parts.hostname}, which is not <service>.<namespace>")
        found.add((labels[1], labels[0], parts.port))
    return found


def pod_templates(documents):
    """Every pod this directory declares, as (namespace, labels, containers)."""
    found = []
    for document in documents:
        if document.get("kind") in POD_TEMPLATE_KINDS:
            template = document["spec"]["template"]
            found.append(
                (
                    document["metadata"].get("namespace"),
                    template["metadata"].get("labels", {}),
                    template["spec"].get("containers", []),
                )
            )
        elif document.get("kind") == "Pod":
            metadata = document["metadata"]
            found.append(
                (
                    metadata.get("namespace"),
                    metadata.get("labels", {}),
                    document["spec"].get("containers", []),
                )
            )
    return found


def selected(templates, namespace, selector):
    if not selector:
        return []
    return [
        (labels, containers)
        for space, labels, containers in templates
        if space == namespace
        and all(labels.get(key) == value for key, value in selector.items())
    ]


def pod_port(service, pods):
    """The container port a Service's published port resolves to.

    `targetPort` is a name in two of the three cases here, and a name is the
    pod's: it is looked up on the containers of the pods the Service selects,
    and a name no selected container publishes is refused rather than passed
    through as a string.
    """
    published = [entry for entry in service["spec"].get("ports", [])]
    if len(published) != 1:
        refuse(
            f"Service {service['metadata']['namespace']}/{service['metadata']['name']} "
            f"publishes {len(published)} ports, and this gate resolves one"
        )
    port = published[0]
    target = port.get("targetPort", port["port"])
    if isinstance(target, int):
        return port["port"], target
    names = {
        declared["containerPort"]
        for _, containers in pods
        for entry in containers
        for declared in entry.get("ports", [])
        if declared.get("name") == target
    }
    if len(names) != 1:
        refuse(
            f"Service {service['metadata']['namespace']}/{service['metadata']['name']} "
            f"targets the named port {target!r}, which its pods publish {len(names)} "
            "numbers for"
        )
    return port["port"], names.pop()


def ports(rule):
    return {(port.get("protocol", "TCP"), port["port"]) for port in rule.get("ports", [])}


def peer_pods(peer, own, templates, described):
    """The pods one `to` peer selects, refusing every shape this gate cannot resolve."""
    if "ipBlock" in peer:
        refuse(f"{described} reaches an address range; the selector reaches named Services")
    namespaces = peer.get("namespaceSelector")
    namespace = own
    if namespaces is not None:
        namespace = namespaces.get("matchLabels", {}).get("kubernetes.io/metadata.name")
        if namespace is None:
            refuse(
                f"{described} names a namespaceSelector on something other than "
                "kubernetes.io/metadata.name, which this gate cannot resolve"
            )
    pods = peer.get("podSelector") or {}
    chosen = pods.get("matchLabels") or {}
    if not chosen and pods.get("matchExpressions"):
        refuse(f"{described} selects pods by matchExpressions alone, which this gate cannot resolve")
    if not chosen:
        refuse(f"{described} names no pod labels, so it selects every pod in {namespace}")
    return namespace, selected(templates, namespace, chosen)


def main():
    if len(sys.argv) != 2:
        refuse("usage: selector-reach.py RENDERED_MANIFEST")
    documents = objects(sys.argv[1])

    selector = one(documents, "Deployment", DEPLOYMENT, CONTROL)

    # 1. The workload runs. Everything below is a statement about a process that
    #    connects to things, and at zero replicas none of it is load-bearing --
    #    which is exactly the state the retired policy host survived in.
    if selector["spec"].get("replicas", 1) < 1:
        refuse("the selector runs no replica, so nothing it is configured to reach is reached")

    entry = container(selector, CONTAINER)
    document = configuration(entry)

    # 2. The retired protocol is gone from the rendered pod, in both the places
    #    it was written. A `policy` block is refused by the schema the process
    #    parses this with, and a bearer-token mount is a credential nothing reads.
    if RETIRED_CONFIGURATION_KEY in document:
        refuse(
            f"the configuration still carries a {RETIRED_CONFIGURATION_KEY!r} block; this "
            "manifest is written for the image that retires the trusted policy protocol, "
            "and that image's schema names no such block"
        )
    for item in entry.get("env", []):
        key = item.get("valueFrom", {}).get("secretKeyRef", {}).get("key")
        if key == RETIRED_SECRET_KEY:
            refuse(f"{item['name']} still mounts {RETIRED_SECRET_KEY}, which nothing reads")

    # 3. Every destination the configuration names is permitted, on the port the
    #    pod listens on rather than the one the URL publishes.
    templates = pod_templates(documents)
    egress = one(documents, "NetworkPolicy", EGRESS, CONTROL)
    arms = egress["spec"].get("egress", [])
    for rule in arms:
        if not rule.get("ports"):
            refuse(f"a {EGRESS} arm names no port, so it admits every port")
        if not rule.get("to"):
            refuse(f"a {EGRESS} arm names no destination, so it reaches everything")

    claimed = []
    for namespace, name, published in sorted(destinations(document)):
        service = one(documents, "Service", name, namespace)
        pods = selected(templates, namespace, service["spec"].get("selector", {}))
        if not pods:
            refuse(f"Service {namespace}/{name} selects no pod this directory declares")
        service_port, container_port = pod_port(service, pods)
        if service_port != published:
            refuse(
                f"the configuration reaches {name}.{namespace} on {published}, and that "
                f"Service publishes {service_port}"
            )
        wanted = [labels for labels, _ in pods]
        matched = [
            rule
            for rule in arms
            if ("TCP", container_port) in ports(rule)
            and [
                found
                for peer in rule["to"]
                for found in [
                    labels
                    for labels, _ in peer_pods(
                        peer, CONTROL, templates, f"the {EGRESS} arm for {sorted(ports(rule))}"
                    )[1]
                ]
            ]
            == wanted
        ]
        if len(matched) != 1:
            refuse(
                f"the configuration reaches {name}.{namespace}, whose pods listen on "
                f"{container_port}, and {len(matched)} {EGRESS} arms permit exactly those "
                "pods on that port"
            )
        claimed.append(matched[0])

    # 4. And no arm permits what nothing reaches. A retirement that takes a URL
    #    out and leaves its arm standing grants a permission to nobody, which
    #    reads like a rule somebody meant and is the harder half to notice.
    for rule in arms:
        if any(rule is held for held in claimed):
            continue
        opened = ports(rule)
        if opened != DNS_PORTS:
            refuse(
                f"the {EGRESS} arm for {sorted(opened)} permits a destination the "
                "configuration does not name"
            )
        siblings = [
            arm.get("to")
            for other in documents
            if other.get("kind") == "NetworkPolicy"
            and other["metadata"]["name"] != EGRESS
            for arm in other["spec"].get("egress", []) or []
            if ports(arm) == opened
        ]
        if not siblings:
            refuse(
                f"the {EGRESS} arm for {sorted(opened)} is the only statement in this "
                "directory of where the resolver is, so nothing holds it"
            )
        if rule["to"] not in siblings:
            refuse(
                f"the {EGRESS} arm for {sorted(opened)} names a resolver no other policy "
                "on the same ports names"
            )


if __name__ == "__main__":
    main()
