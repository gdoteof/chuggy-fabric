#!/usr/bin/env python3
"""Refuse a rendered cluster where Hydra's or Kratos's admin port is not bounded
as declared.

Both authenticate nobody. Hydra's registers OAuth2 clients, accepts logins and
consents, and reads every grant; Kratos's creates identities and mints sessions
for them. Each is admitted from inside `ory` and from its declared callers
outside it, and nothing else: the chuggy API on Hydra's, where it registers a
pool's client, and nobody on Kratos's, because the API creates no identity.
A caller is held from both ends -- admitted by the port, its URL naming the
admin Service on the number it publishes, and its own egress reaching the pod
on the container port.

tests/keto.py holds Keto's write port to the same shape, and its header argues
the fold over every policy selecting the pod, the port resolved through the
Service onto the container and held equal to the config document, and reading
a caller from another namespace as the rendered workloads it selects; each
holds here unchanged. Only the admin ports are held here.

WHAT THIS GATE CANNOT RESOLVE IT REFUSES rather than passes, as keto.py does: on
an element admitting an admin port, a peer of another shape, `endPort`, a port
that is a name or absent, a podSelector operator other than `In`, and a Service
publishing other than one port.
"""

import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml

ORY = "ory"
CONTROL = "chuggy"

# (deployment and container, admin Service, what the port does, callers from
# outside `ory`). A caller is (deployment, container, variable, egress policy),
# as keto.py's are.
SERVERS = (
    (
        "hydra",
        "hydra-admin",
        "registers any client and accepts any login",
        (("chuggy-api", "api", "CHUG_API_HYDRA_ADMIN_URL", "chuggy-api-egress"),),
    ),
    ("kratos", "kratos-admin", "creates any identity and mints it a session", ()),
)

# `serve.admin.port` in the config document the server is told to read.
CONFIG_FLAG = "--config"
SERVE = "serve"
ADMIN = "admin"

CLUSTER_SUFFIX = ".svc.cluster.local"
NAMESPACE_LABEL = "kubernetes.io/metadata.name"
WORKLOADS = ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob")


def refuse(message):
    raise SystemExit(f"ory admin: {message}")


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
    for entry in deployment["spec"]["template"]["spec"].get("containers", []):
        if entry["name"] == name:
            return entry
    refuse(f"{deployment['metadata']['name']} has no container {name}")


def selects(selector, labels, described):
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


def pod_labels(document):
    spec = document["spec"]
    if document["kind"] == "CronJob":
        spec = spec["jobTemplate"]["spec"]
    return spec["template"]["metadata"].get("labels") or {}


def resolved_port(service, deployment):
    """The (published, container) pair a Service's single port resolves to."""
    published = service["spec"].get("ports", [])
    if len(published) != 1:
        refuse(
            f"Service {service['metadata']['name']} publishes {len(published)} ports, "
            "and this gate resolves one"
        )
    port = published[0]
    chosen = service["spec"].get("selector", {})
    if not chosen or not selects({"matchLabels": chosen}, pod_labels(deployment), "a Service"):
        refuse(
            f"Service {service['metadata']['name']} does not select the "
            f"{deployment['metadata']['name']} pod"
        )
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


def served_admin_port(documents, deployment, entry):
    """`serve.admin.port` out of the config document `--config` names, through
    the mount and the generated ConfigMap, each step refused rather than
    guessed at."""
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
    port = ((document or {}).get(SERVE) or {}).get(ADMIN, {}).get("port")
    if isinstance(port, bool) or not isinstance(port, int):
        refuse(f"{path.name} does not give {SERVE}.{ADMIN}.port as a number")
    return port


def peer_reach(documents, peer, described):
    """'namespace' for pods in `ory`, and each rendered workload a peer selects
    in another namespace as (namespace, name)."""
    if set(peer) == {"podSelector"}:
        return {"namespace"}
    namespaces = peer.get("namespaceSelector") or {}
    named = namespaces.get("matchLabels") or {}
    if (
        set(peer) != {"namespaceSelector", "podSelector"}
        or set(namespaces) != {"matchLabels"}
        or set(named) != {NAMESPACE_LABEL}
    ):
        refuse(
            f"an ingress peer on {described} is neither a bare podSelector nor a podSelector "
            f"in one namespace named by {NAMESPACE_LABEL}, and this gate cannot resolve its reach"
        )
    if named[NAMESPACE_LABEL] == ORY:
        return {"namespace"}
    return {
        (named[NAMESPACE_LABEL], document["metadata"]["name"])
        for document in documents
        if document.get("kind") in WORKLOADS
        and document["metadata"].get("namespace") == named[NAMESPACE_LABEL]
        and selects(peer["podSelector"], pod_labels(document), described)
    }


def spoken(reach):
    return sorted(
        who if who == "anywhere" else f"`{ORY}`" if who == "namespace" else "/".join(who)
        for who in reach
    ) or ["nowhere"]


def reach_of(documents, policies, port):
    """Who is admitted to one TCP port, folded across every policy selecting
    the pod, because NetworkPolicies are additive."""
    found = set()
    for policy in policies:
        name = policy["metadata"]["name"]
        for element in policy["spec"].get("ingress") or []:
            numbers = set()
            for entry in element.get("ports") or []:
                if "endPort" in entry:
                    refuse(f"an ingress element on {name} names endPort, which admits a range")
                number = entry.get("port")
                if isinstance(number, bool) or not isinstance(number, int):
                    refuse(f"an ingress element on {name} names the port {number!r}, not a number")
                if entry.get("protocol", "TCP") == "TCP":
                    numbers.add(number)
            if not numbers:
                refuse(
                    f"an ingress element on {name} names no TCP port, so it admits every "
                    "port on every pod it selects"
                )
            if port not in numbers:
                continue
            peers = element.get("from")
            if not peers:
                found.add("anywhere")
                continue
            for peer in peers:
                found |= peer_reach(documents, peer, name)
    return found


def main():
    if len(sys.argv) != 2:
        refuse("usage: ory-admin.py RENDERED_MANIFEST")
    documents = objects(sys.argv[1])

    for server, service, grants, callers in SERVERS:
        deployment = one(documents, "Deployment", server, ORY)
        labels = pod_labels(deployment)

        # 1. Some policy in `ory` isolates the pod for ingress at all.
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
                f"no NetworkPolicy in {ORY} isolates the {server} pod for ingress, so every "
                "port it listens on is open to the whole cluster"
            )
        named = ", ".join(sorted(policy["metadata"]["name"] for policy in policies))

        # 2. The admin port as the kernel matches it, and as the process binds it.
        published, port = resolved_port(one(documents, "Service", service, ORY), deployment)
        bound = served_admin_port(documents, deployment, container(deployment, server))
        if bound != port:
            refuse(
                f"{server}'s config document binds {SERVE}.{ADMIN}.port to {bound} while "
                f"{service} lands on container port {port}"
            )

        # 3. Admitted from inside `ory` and from each caller, and from nowhere else.
        reach = reach_of(documents, policies, port)
        wanted = {"namespace"} | {(CONTROL, caller) for caller, _, _, _ in callers}
        if reach != wanted:
            refuse(
                f"{service} lands on container port {port}, which {named} admits from "
                f"{spoken(reach)} rather than from {spoken(wanted)} alone -- that port "
                f"{grants}"
            )

        for caller, box, variable, policy in callers:
            # 4. The caller's URL names the Service on the number it publishes.
            workload = one(documents, "Deployment", caller, CONTROL)
            values = [
                item.get("value")
                for item in container(workload, box).get("env", [])
                if item["name"] == variable
            ]
            if len(values) != 1 or not values[0]:
                refuse(f"the {box} container does not name {variable} as a literal value")
            parts = urlsplit(values[0])
            if parts.hostname != f"{service}.{ORY}{CLUSTER_SUFFIX}":
                refuse(f"{variable} names {parts.hostname}, which is not {service} in `{ORY}`")
            if parts.port != published:
                refuse(f"{variable} reaches port {parts.port}, and {service} publishes {published}")

            # 5. And the caller's own egress isolates it and reaches the pod on
            #    the container port.
            egress = one(documents, "NetworkPolicy", policy, CONTROL)
            if "Egress" not in (egress["spec"].get("policyTypes") or []):
                refuse(f"{policy} does not name Egress in its policyTypes, so it bounds nothing")
            if not selects(egress["spec"]["podSelector"], pod_labels(workload), policy):
                refuse(f"the podSelector on {policy} does not select the {caller} pod")
            reaching = any(
                any(
                    entry["port"] == port and entry.get("protocol", "TCP") == "TCP"
                    for entry in arm.get("ports") or []
                )
                and any(
                    (peer.get("namespaceSelector") or {}).get("matchLabels", {}).get(
                        NAMESPACE_LABEL
                    )
                    == ORY
                    and selects(peer.get("podSelector") or {}, labels, policy)
                    for peer in arm.get("to") or []
                )
                for arm in egress["spec"].get("egress") or []
            )
            if not reaching:
                refuse(
                    f"{policy} has no arm reaching the {server} pod in `{ORY}` on container "
                    f"port {port}, so {variable} names a destination this pod is refused"
                )


if __name__ == "__main__":
    main()
