#!/usr/bin/env python3
"""Refuse a rendered cluster where the registry's public front could write or
serve without authorization.

The front is a second Distribution over the volume `registry` writes. What
keeps it safe is spread over objects that each read correctly while another is
wrong: the Ingress's middleware annotation, the pod labels the internal Service
must not select, the configuration the pod reads, and its storage mount. So
every pod an Ingress in the namespace reaches is found through the Services it
routes to, and held to all of them. What this cannot resolve it refuses rather
than passes.
"""

import sys
from pathlib import Path, PurePosixPath

import yaml

NAMESPACE = "chuggy-registry"
HOST = "chuggy-registry.vteng.io"
INTERNAL_SERVICE = "registry"

MIDDLEWARES = "traefik.ingress.kubernetes.io/router.middlewares"
PROVIDER = "@kubernetescrd"
AUTHORIZE = "http://chuggy-pool-plane.chuggy.svc.cluster.local:3002/registry/authorize"

TEMPLATED = ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job")
# Distribution reads REGISTRY_<SECTION>_<KEY> over the file it is given.
OVERRIDE_PREFIX = "REGISTRY_"


def refuse(message):
    raise SystemExit(f"registry-public: {message}")


def objects(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def named(documents, kind, name):
    found = [
        document
        for document in documents
        if document.get("kind") == kind
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == NAMESPACE
    ]
    if len(found) != 1:
        refuse(f"expected one {kind} {NAMESPACE}/{name}, found {len(found)}")
    return found[0]


def pods(documents):
    """(description, labels, pod spec) for every pod the namespace declares."""
    found = []
    for document in documents:
        if document["metadata"].get("namespace") != NAMESPACE:
            continue
        kind = document.get("kind")
        if kind == "Pod":
            template = document
        elif kind in TEMPLATED:
            template = document["spec"]["template"]
        elif kind == "CronJob":
            template = document["spec"]["jobTemplate"]["spec"]["template"]
        else:
            continue
        found.append(
            (
                f"{kind} {document['metadata']['name']}",
                template["metadata"].get("labels") or {},
                template["spec"],
            )
        )
    return found


def selects(selector, labels):
    return bool(selector) and all(labels.get(key) == value for key, value in selector.items())


def backends(ingress):
    spec = ingress["spec"]
    found = [spec["defaultBackend"]] if "defaultBackend" in spec else []
    for rule in spec.get("rules") or []:
        found.extend(path["backend"] for path in (rule.get("http") or {}).get("paths") or [])
    for backend in found:
        if "service" not in backend:
            refuse(f"Ingress {ingress['metadata']['name']} has a backend that is not a Service")
    return [backend["service"]["name"] for backend in found]


def authorized(documents, ingress):
    """The Ingress names a forwardAuth Middleware that asks the pool plane."""
    name = ingress["metadata"]["name"]
    value = (ingress["metadata"].get("annotations") or {}).get(MIDDLEWARES)
    if not value:
        refuse(f"Ingress {name} carries no {MIDDLEWARES}, so it serves the registry to anyone")
    middlewares = {}
    for document in documents:
        if document.get("kind") == "Middleware":
            metadata = document["metadata"]
            middlewares[f"{metadata.get('namespace')}-{metadata['name']}{PROVIDER}"] = document
    for reference in (entry.strip() for entry in value.split(",")):
        forward = (middlewares.get(reference, {}).get("spec") or {}).get("forwardAuth") or {}
        # Trusting the client's X-Forwarded-Uri would let it name a path the
        # plane allows while requesting another.
        if forward.get("address") == AUTHORIZE and forward.get("trustForwardHeader") is not True:
            return
    refuse(
        f"Ingress {name}'s {MIDDLEWARES} names no Middleware that forwards to {AUTHORIZE} "
        "without trusting the client's forwarded headers"
    )


def configuration(documents, described, entry, spec):
    """The Distribution configuration the container reads, parsed."""
    if "command" in entry:
        refuse(f"{described} replaces the image's entrypoint, which this gate cannot follow")
    args = entry.get("args") or []
    if len(args) != 1 or PurePosixPath(args[0]).suffix not in (".yml", ".yaml"):
        refuse(f"{described} does not name one configuration file as its only argument")
    path = PurePosixPath(args[0])
    if entry.get("envFrom") or any(
        variable["name"].startswith(OVERRIDE_PREFIX) for variable in entry.get("env") or []
    ):
        refuse(f"{described} sets {OVERRIDE_PREFIX}* or envFrom, which can override {path}")

    keys = []
    for mount in entry.get("volumeMounts") or []:
        if mount.get("mountPath") == str(path) and mount.get("subPath"):
            keys.append((mount["name"], mount["subPath"]))
        elif mount.get("mountPath") == str(path.parent) and not mount.get("subPath"):
            keys.append((mount["name"], path.name))
    if len(keys) != 1:
        refuse(f"{described} has {len(keys)} volumeMounts providing {path}")
    volume_name, key = keys[0]
    volumes = [volume for volume in spec.get("volumes") or [] if volume["name"] == volume_name]
    if len(volumes) != 1 or "configMap" not in volumes[0]:
        refuse(f"{described} reads {path} from something other than one ConfigMap")
    data = named(documents, "ConfigMap", volumes[0]["configMap"]["name"]).get("data") or {}
    if key not in data:
        refuse(f"the ConfigMap {described} reads {path} from has no {key}")
    try:
        return yaml.safe_load(data[key]) or {}
    except yaml.YAMLError as failure:
        refuse(f"{path} in {described} is not YAML: {failure}")


def read_only(documents, described, spec):
    if spec.get("initContainers") or len(spec.get("containers") or []) != 1:
        refuse(f"{described} is not a pod of one container, which is what this gate reads")
    entry = spec["containers"][0]

    storage = configuration(documents, described, entry, spec).get("storage") or {}
    if ((storage.get("maintenance") or {}).get("readonly") or {}).get("enabled") is not True:
        refuse(f"{described} is reachable through the public Ingress and is not read-only")
    if (storage.get("delete") or {}).get("enabled") is not False:
        refuse(f"{described} is reachable through the public Ingress and does not disable delete")

    claims = []
    for volume in spec.get("volumes") or []:
        if "persistentVolumeClaim" in volume:
            claims.append(volume["name"])
            if volume["persistentVolumeClaim"].get("readOnly") is not True:
                refuse(f"{described} claims {volume['name']!r} writable")
        elif "configMap" not in volume:
            refuse(f"{described} has the volume {volume['name']!r}, which this gate cannot read")
    if not claims:
        refuse(f"{described} mounts no PersistentVolumeClaim, so its storage was not read")
    for mount in entry.get("volumeMounts") or []:
        if mount["name"] in claims and mount.get("readOnly") is not True:
            refuse(f"{described} mounts {mount['name']!r} at {mount['mountPath']} writable")


def main():
    if len(sys.argv) != 2:
        refuse("usage: registry-public.py RENDERED_MANIFEST")
    documents = objects(sys.argv[1])
    declared = pods(documents)

    ingresses = [
        document
        for document in documents
        if document.get("kind") == "Ingress" and document["metadata"].get("namespace") == NAMESPACE
    ]
    hosts = {
        rule.get("host") for ingress in ingresses for rule in ingress["spec"].get("rules") or []
    }
    if HOST not in hosts:
        refuse(f"no Ingress in {NAMESPACE} routes {HOST}")

    reached = {}
    for ingress in ingresses:
        authorized(documents, ingress)
        for service_name in backends(ingress):
            selector = named(documents, "Service", service_name)["spec"].get("selector") or {}
            selected = [pod for pod in declared if selects(selector, pod[1])]
            if not selected:
                refuse(f"Service {service_name} selects no pod this gate can read")
            reached.update((pod[0], pod) for pod in selected)

    internal = named(documents, "Service", INTERNAL_SERVICE)["spec"].get("selector") or {}
    for described, labels, spec in reached.values():
        if selects(internal, labels):
            refuse(
                f"{described} is reachable through the public Ingress and Service "
                f"{INTERNAL_SERVICE} selects it, so internal pushes would land on it"
            )
        read_only(documents, described, spec)

    print(f"clean: {', '.join(sorted(reached))} behind {HOST} is read-only and authorized")


if __name__ == "__main__":
    main()
