#!/usr/bin/env python3
"""Refuse a rendered cluster where Keto's two ports are not bounded as declared.

Keto's write port grants permission and authenticates nobody: one PUT on it
makes any subject an administrator of any project. What holds it to callers
inside `ory` is a list of label values on one NetworkPolicy, and the way that
goes wrong is silent -- a pod whose `app` is not in the list is selected by no
policy in the namespace, which is not a denial but the whole pod network on
every port it listens on, with every file still reading correctly on its own.

NETWORKPOLICIES ARE ADDITIVE, so the question is what the namespace admits and
not what one object says. Reachability below is folded over every policy in
`ory` that selects this pod and isolates it for ingress: a second policy with a
bare podSelector opening the write port would leave the first reading exactly
as it does now, and a second policy is what ory-network-policy.yaml tells the
next author to admit a scrape with.

THE PORT IS WRITTEN FOUR TIMES AND EACH COPY DECIDES SOMETHING DIFFERENT. A
NetworkPolicy names the pod's port, which is what the kernel matches; a Service
names its own and targets the container's by name; the container declares it,
which resolves those names and nothing else; and the config document says what
the process binds. So every assertion below resolves a Service's `targetPort`
against the containers that Service selects and checks the policy against that
number rather than against the number in the Service or in a URL -- and the
config document is held equal to it, because a port reasoned about in three
objects that the process does not serve on is a rule about nothing.

THE PROBE IS THE OTHER HALF OF THE SAME QUESTION. A kubelet probe arrives from
the node and matches no podSelector, so a probe on a namespace-local port is
answered only by k3s's node-local ACCEPT -- and ory-network-policy.yaml states
that nothing there depends on that CNI behaviour. A probe moved to the write
port would make this pod's liveness a property of the CNI and would break no
test that reads the manifests one at a time.

THE MIGRATION SHARES THE POD, so it is admitted to PostgreSQL by the same
label. A pod template that loses the label leaves a Deployment whose
initContainer cannot reach the database it exists to migrate, which under
`wait: true` stalls the reconcile rather than one workload.

WHAT THIS GATE CANNOT RESOLVE IT REFUSES rather than passes: an ingress element
whose `from` is neither absent nor a bare podSelector, an element naming
`endPort` -- a range this reads one port at a time, so a range that reached the
write port would read here as the number it starts at -- an element whose port
is a name or is absent rather than a number, a podSelector this cannot
evaluate, a Service publishing other than one port, and a probe that is not an
httpGet are each legal and each outside what is evaluated here.
"""

import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml

ORY = "ory"
CONTROL = "chuggy"

DEPLOYMENT = "keto"
SERVER = "keto"
MIGRATE = "migrate"

READ_SERVICE = "keto-read"
WRITE_SERVICE = "keto-write"

POSTGRES_POLICY = "postgres-admits-labelled-clients"
POSTGRES_CLIENT = ("chuggy.dev/postgres-client", "true")

# The API is told where the read port is, and that URL is a second copy of the
# Service's own number. The selector holds a copy of its own, and
# tests/selector-reach.py resolves that one against this Service and against the
# selector's egress arm; this gate reads the API's, and the arm the API's own
# policy has to carry for that URL to be openable at all.
API_DEPLOYMENT = "chuggy-api"
API_CONTAINER = "api"
API_VARIABLE = "CHUG_API_KETO_READ_URL"
API_EGRESS = "chuggy-api-egress"

CLUSTER_SUFFIX = ".svc.cluster.local"

# The flag whose value names the file the server actually reads, and the keys
# inside that file that decide what it binds.
CONFIG_FLAG = "--config"
SERVE = "serve"
SERVED = {"read": READ_SERVICE, "write": WRITE_SERVICE}


def refuse(message):
    raise SystemExit(f"keto: {message}")


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
    template = deployment["spec"]["template"]["spec"]
    for entry in template.get("initContainers", []) + template.get("containers", []):
        if entry["name"] == name:
            return entry
    refuse(f"{deployment['metadata']['name']} has no container {name}")


def served_ports(documents, deployment, entry):
    """`serve.<name>.port` out of the config document the server is told to read.

    The chain is the kubelet's: the `--config` value names a path, a volumeMount
    covers the directory it is in, that mount names a volume, the volume names a
    ConfigMap -- the generated one, whose name carries a hash of its content and
    is therefore not something this file could hardcode -- and one key of that
    ConfigMap is the file. Every step is refused rather than guessed at.
    """
    args = entry.get("args") or []
    if args.count(CONFIG_FLAG) != 1 or args.index(CONFIG_FLAG) + 1 >= len(args):
        refuse(f"the {entry['name']} container does not name one {CONFIG_FLAG} and its value")
    path = PurePosixPath(args[args.index(CONFIG_FLAG) + 1])

    mounts = [
        mount
        for mount in entry.get("volumeMounts") or []
        if mount.get("mountPath") == str(path.parent)
    ]
    if len(mounts) != 1:
        refuse(f"{len(mounts)} volumeMounts cover {path.parent}, which {CONFIG_FLAG} reads from")
    volumes = [
        volume
        for volume in deployment["spec"]["template"]["spec"].get("volumes") or []
        if volume["name"] == mounts[0]["name"]
    ]
    if len(volumes) != 1 or "configMap" not in volumes[0]:
        refuse(f"the volume {mounts[0]['name']!r} is not one ConfigMap this gate can open")

    data = one(documents, "ConfigMap", volumes[0]["configMap"]["name"], ORY).get("data") or {}
    if path.name not in data:
        refuse(f"the ConfigMap mounted at {path.parent} carries no {path.name}")
    try:
        document = yaml.safe_load(data[path.name])
    except yaml.YAMLError as failure:
        refuse(f"{path.name} is not YAML: {failure}")

    found = {}
    for name in SERVED:
        port = ((document or {}).get(SERVE) or {}).get(name, {}).get("port")
        if isinstance(port, bool) or not isinstance(port, int):
            refuse(
                f"{path.name} does not give {SERVE}.{name}.port as a number, so what the "
                "server binds is not something this gate read"
            )
        found[name] = port
    return found


def selects(selector, labels, described):
    """Whether a podSelector matches one pod's labels.

    Only the two shapes this directory uses are evaluated. `In` is what the ory
    policy names its workloads with, and it is the operator whose value list is
    the thing a new workload has to be added to.
    """
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions") or []:
        if expression["operator"] != "In":
            refuse(
                f"{described} selects by {expression['operator']!r}, which this gate "
                "cannot evaluate"
            )
        if labels.get(expression["key"]) not in expression["values"]:
            return False
    return True


def resolved_port(service, deployment):
    """The container port a Service's single published port resolves to.

    `targetPort` is a name here, and a name is the pod's: it is looked up on the
    containers of the pods the Service selects, and a name no selected container
    publishes is refused rather than passed through as a string.
    """
    published = service["spec"].get("ports", [])
    if len(published) != 1:
        refuse(
            f"Service {service['metadata']['name']} publishes {len(published)} ports, "
            "and this gate resolves one"
        )
    port = published[0]
    labels = deployment["spec"]["template"]["metadata"].get("labels", {})
    chosen = service["spec"].get("selector", {})
    if not chosen or not all(labels.get(key) == value for key, value in chosen.items()):
        refuse(f"Service {service['metadata']['name']} does not select the {DEPLOYMENT} pod")
    target = port.get("targetPort", port["port"])
    if isinstance(target, int):
        return port["port"], target
    numbers = {
        declared["containerPort"]
        for entry in deployment["spec"]["template"]["spec"]["containers"]
        for declared in entry.get("ports", [])
        if declared.get("name") == target
    }
    if len(numbers) != 1:
        refuse(
            f"Service {service['metadata']['name']} targets the named port {target!r}, "
            f"which its pod publishes {len(numbers)} numbers for"
        )
    return port["port"], numbers.pop()


def admission(policies):
    """Every ingress element as ('anywhere' | 'namespace', the TCP ports it admits).

    Across all of them, because NetworkPolicies are additive: a port is
    reachable from wherever ANY policy selecting the pod admits it, and a
    second object admitting the write port would leave the first one reading
    exactly as it does now.

    An element with no `from` admits every pod on the network; the one this
    directory uses to mean "inside `ory`" is a single bare podSelector, which
    NetworkPolicy scopes to the policy's own namespace. Anything else is a
    shape whose reach this gate would have to guess at.
    """
    found = []
    for policy in policies:
        name = policy["metadata"]["name"]
        for element in policy["spec"].get("ingress") or []:
            peers = element.get("from")
            if peers is None:
                reach = "anywhere"
            elif peers == [{"podSelector": {}}]:
                reach = "namespace"
            else:
                refuse(
                    f"an ingress element on {name} names a `from` that is neither absent nor "
                    "a bare podSelector, and this gate cannot resolve its reach"
                )
            ports = set()
            for port in element.get("ports") or []:
                if "endPort" in port:
                    refuse(
                        f"an ingress element on {name} names endPort, which admits a range: "
                        "this gate reads a port at a time and would see only the number the "
                        "range starts at"
                    )
                number = port.get("port")
                if isinstance(number, bool) or not isinstance(number, int):
                    refuse(
                        f"an ingress element on {name} names the port {number!r}, which is not "
                        "a number: a name is resolved against the selected pod's own containers "
                        "and an absent port admits every one of them, and this gate reads "
                        "neither"
                    )
                if port.get("protocol", "TCP") == "TCP":
                    ports.add(number)
            if not ports:
                refuse(
                    f"an ingress element on {name} names no TCP port, so it admits every "
                    "port on every pod it selects"
                )
            found.append((reach, ports))
    return found


def admitted_by(elements, port):
    return {reach for reach, ports in elements if port in ports}


def probe_ports(entry):
    """The container port numbers the probes on one container use."""
    declared = {port["name"]: port["containerPort"] for port in entry.get("ports", [])}
    found = set()
    for kind in ("readinessProbe", "livenessProbe", "startupProbe"):
        probe = entry.get(kind)
        if probe is None:
            continue
        target = probe.get("httpGet")
        if target is None:
            refuse(f"the {kind} on {entry['name']} is not an httpGet, which this gate reads")
        port = target["port"]
        if isinstance(port, int):
            found.add(port)
        elif port in declared:
            found.add(declared[port])
        else:
            refuse(f"the {kind} on {entry['name']} names port {port!r}, which it does not declare")
    if not found:
        refuse(f"{entry['name']} declares no probe, so nothing reports it unhealthy")
    return found


def main():
    if len(sys.argv) != 2:
        refuse("usage: keto.py RENDERED_MANIFEST")
    documents = objects(sys.argv[1])

    deployment = one(documents, "Deployment", DEPLOYMENT, ORY)
    template = deployment["spec"]["template"]
    labels = template["metadata"].get("labels", {})

    # 1. Some policy in `ory` isolates the pod for ingress at all. Everything
    #    below is a statement about which of Keto's ports are admitted from
    #    where, and a pod no such policy selects is admitted everything from
    #    everywhere.
    policies = [
        document
        for document in documents
        if document.get("kind") == "NetworkPolicy"
        and document["metadata"].get("namespace") == ORY
        and "Ingress" in (document["spec"].get("policyTypes") or ["Ingress"])
        and selects(document["spec"]["podSelector"], labels, document["metadata"]["name"])
    ]
    if not policies:
        refuse(
            f"no NetworkPolicy in {ORY} isolates the {DEPLOYMENT} pod for ingress, so every "
            "port it listens on is open to the whole cluster"
        )
    named = ", ".join(sorted(policy["metadata"]["name"] for policy in policies))

    # 2. The two ports, resolved the way the kernel resolves them: through each
    #    Service's `targetPort` onto the container port, never off the number
    #    the Service or a URL publishes.
    read_published, read_port = resolved_port(one(documents, "Service", READ_SERVICE, ORY), deployment)
    _, write_port = resolved_port(one(documents, "Service", WRITE_SERVICE, ORY), deployment)
    resolved = {"read": read_port, "write": write_port}

    # 2b. And what the process binds, which is none of those. `containerPort`
    #     resolves a named `targetPort` and a named probe port and decides
    #     nothing else, so an edit to the config document alone moves an API
    #     onto another port while every object above still reads correctly.
    bound = served_ports(documents, deployment, container(deployment, SERVER))
    for name, service in SERVED.items():
        if bound[name] != resolved[name]:
            refuse(
                f"the config document binds {SERVE}.{name}.port to {bound[name]} while "
                f"{service} lands on container port {resolved[name]}: what the process serves "
                "there is not what the elements below are reasoned about"
            )

    elements = admission(policies)

    # 3. The write port grants permission, so it is admitted from inside `ory`
    #    and from nowhere else.
    reach = admitted_by(elements, write_port)
    if reach != {"namespace"}:
        refuse(
            f"{WRITE_SERVICE} lands on container port {write_port}, which {named} admits "
            f"from {sorted(reach) or ['nowhere']} rather than from `{ORY}` alone -- that port "
            "makes any subject an administrator of any project"
        )

    # 4. The read port answers checks and grants nothing, and it carries the
    #    health endpoints, so it is admitted from anywhere on the pod network.
    if "anywhere" not in admitted_by(elements, read_port):
        refuse(
            f"{READ_SERVICE} lands on container port {read_port}, which {named} does not "
            "admit from anywhere on the pod network"
        )

    # 5. And the probes are on such a port. A kubelet probe matches no
    #    podSelector, so one on a namespace-local port is answered only by the
    #    node-local ACCEPT that ory-network-policy.yaml declines to rely on.
    for probed in sorted(probe_ports(container(deployment, SERVER))):
        if "anywhere" not in admitted_by(elements, probed):
            refuse(
                f"the {SERVER} container probes port {probed}, which {named} does not admit "
                "from anywhere, so the kubelet reaches it only through the CNI exemption"
            )

    # 6. Both containers hold a database role, and they share one pod, so one
    #    label admits both to PostgreSQL. Without it the initContainer cannot
    #    reach the database it exists to migrate.
    for name in (MIGRATE, SERVER):
        entry = container(deployment, name)
        if not any(item["name"] == "DSN" for item in entry.get("env", [])):
            refuse(f"the {name} container names no DSN, and this gate is about what reaches PostgreSQL")
    key, value = POSTGRES_CLIENT
    if labels.get(key) != value:
        refuse(
            f"the {DEPLOYMENT} pod does not carry {key}={value}, so "
            f"{POSTGRES_POLICY} refuses both of its containers the database"
        )
    admits = one(documents, "NetworkPolicy", POSTGRES_POLICY, CONTROL)
    arms = [
        peer
        for element in admits["spec"].get("ingress", [])
        for peer in element.get("from", [])
        if (peer.get("namespaceSelector") or {}).get("matchLabels", {}).get(
            "kubernetes.io/metadata.name"
        )
        == ORY
    ]
    if not arms:
        refuse(f"{POSTGRES_POLICY} has no arm for `{ORY}`, so the label above admits nothing")
    if not any(selects(peer.get("podSelector") or {}, labels, POSTGRES_POLICY) for peer in arms):
        refuse(f"no `{ORY}` arm of {POSTGRES_POLICY} selects the {DEPLOYMENT} pod")

    # 7. And the API's copy of the read port agrees with the Service it names.
    #    The URL is a second copy of a number, and a Service that renumbered
    #    would leave the API reaching for the old one.
    api = one(documents, "Deployment", API_DEPLOYMENT, CONTROL)
    values = [
        item.get("value")
        for item in container(api, API_CONTAINER).get("env", [])
        if item["name"] == API_VARIABLE
    ]
    if len(values) != 1 or not values[0]:
        refuse(f"the {API_CONTAINER} container does not name {API_VARIABLE} as a literal value")
    parts = urlsplit(values[0])
    if parts.hostname != f"{READ_SERVICE}.{ORY}{CLUSTER_SUFFIX}":
        refuse(f"{API_VARIABLE} names {parts.hostname}, which is not {READ_SERVICE} in `{ORY}`")
    if parts.port != read_published:
        refuse(f"{API_VARIABLE} reaches port {parts.port}, and {READ_SERVICE} publishes {read_published}")

    # 8. And the API's own egress admits that pod on the port the kernel
    #    matches, which is the container's and not the one the URL publishes.
    #    That policy isolates the API for egress, so a destination it does not
    #    admit is refused however correctly the URL above reads.
    egress = one(documents, "NetworkPolicy", API_EGRESS, CONTROL)
    reaching = any(
        any(
            port["port"] == read_port and port.get("protocol", "TCP") == "TCP"
            for port in arm.get("ports") or []
        )
        and any(
            (peer.get("namespaceSelector") or {}).get("matchLabels", {}).get(
                "kubernetes.io/metadata.name"
            )
            == ORY
            and selects(peer.get("podSelector") or {}, labels, API_EGRESS)
            for peer in arm.get("to") or []
        )
        for arm in egress["spec"].get("egress") or []
    )
    if not reaching:
        refuse(
            f"{API_EGRESS} has no arm reaching the {DEPLOYMENT} pod in `{ORY}` on container "
            f"port {read_port}, so {API_VARIABLE} names a destination this pod is refused"
        )


if __name__ == "__main__":
    main()
