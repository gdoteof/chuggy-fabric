#!/usr/bin/env python3
"""Refuse a rendered cluster in which a release does not roll out in order:
the dump, then the migration, then the services.

`cluster/flux/` declares three layers over one source -- `apps`, then
`chuggy-migrate`, then `chuggy` -- and `tests/flux-layers.py` holds that each
waits on the one before. That orders the LAYERS. What orders a RELEASE is which
objects are in which, and nothing but a reader holds that: a Deployment that
runs a release image and is listed in `cluster/apps` is rolled before the
migration has run, and every layer still reads as declared.

SO THE THREE RENDERS ARE READ AS THREE, never as one stream. An object is held
to the layer that renders it, and a release image is read off the pod that
runs it rather than off the name of the file it came from.

THEN THE POD THAT MIGRATES IS HELD TO THE ORDER INSIDE IT, since the dump and
the migration are one pod and the layers cannot see into it. `dump` is an
initContainer, so it has exited 0 before `migrate` is created; an initContainer
that restarts is a sidecar and gates nothing, and is refused as one. It runs
after `wait-for-postgres`, for the reason chuggy-migrate.yaml measures: a new
pod's first connection is refused until its address is admitted, and a dump
that connected first would fail a release on it.

AND THE DUMP IS HELD TO WHAT IT STANDS ON, each of which reads correctly while
the other half is wrong:

- the claim it mounts is `chuggy-dumps`, which `apps` applies, and the
  directory its script is told to write is where that claim is mounted;
- the uid it runs as is the owner of the host directory under the claim --
  `chuggy.state.dumps.user`, handed over by the host rather than restated --
  and the pod sets no `fsGroup`, which would have the kubelet regroup that
  directory and widen its mode;
- the superuser's password reaches the PostgreSQL server and `dump` and no
  other container in the cluster, and `dump` reads the key the server sets it
  from;
- its image is the server's, because `pg_dump` refuses a server newer than
  itself.

WHAT THIS CANNOT SEE. Whether the dump works: `tests/dump-script.nix` runs the
script the Job mounts against a PostgreSQL. Whether kustomize-controller holds
a dependent back as its documentation says: that is Flux's, and the pin on its
version is in `tests/build-platform.nix`. Whether the host directory exists,
which a host rebuild delivers.
"""

import sys
from pathlib import Path

import yaml

LAYERS = ("apps", "chuggy-migrate", "chuggy")
MIGRATION_LAYER = "chuggy-migrate"
SERVICE_LAYER = "chuggy"

# What a release moves: the images this site builds from chuggy. The roster in
# `scripts/check-release-consistency` names the manifests; this is the prefix
# its image pattern is written over.
RELEASE_IMAGES = "registry.chuggy.internal/chuggy/"

TEMPLATED = ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "ReplicationController", "Job")

NAMESPACE = "chuggy"
WAIT = "wait-for-postgres"
DUMP = "dump"
CLAIM = "chuggy-dumps"
DIRECTORY_VARIABLE = "CHUG_DUMP_DIR"
PASSWORD_VARIABLE = "PGPASSWORD"
SUPERUSER_SECRET = "postgres-superuser"
SERVER = ("StatefulSet", NAMESPACE, "postgres")
SERVER_CONTAINER = "postgres"
SERVER_PASSWORD_VARIABLE = "POSTGRES_PASSWORD"


def refuse(message):
    raise SystemExit(f"rollout-order: {message}")


def documents_in(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def identity(document):
    metadata = document["metadata"]
    return (document.get("kind"), metadata.get("namespace"), metadata["name"])


def described(document):
    kind, namespace, name = identity(document)
    return f"{kind} {namespace}/{name}" if namespace else f"{kind} {name}"


def pod_of(document):
    """The pod a workload runs, or None for an object that runs nothing."""
    kind = document.get("kind")
    if kind == "Pod":
        return document["spec"]
    if kind == "CronJob":
        return document["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    if kind in TEMPLATED:
        return document["spec"]["template"]["spec"]
    return None


def containers_of(pod):
    """(group, container) for everything the pod runs, in the order it is
    written."""
    for group in ("initContainers", "containers", "ephemeralContainers"):
        for container in pod.get(group) or []:
            yield group, container


def releases(pod):
    return [
        container["name"]
        for _, container in containers_of(pod)
        if str(container.get("image", "")).startswith(RELEASE_IMAGES)
    ]


def secret_key(container, variable):
    """The (Secret, key) an environment variable is read from, or None."""
    for entry in container.get("env") or []:
        if entry.get("name") == variable:
            reference = (entry.get("valueFrom") or {}).get("secretKeyRef") or {}
            if reference:
                return (reference.get("name"), reference.get("key"))
    return None


def reached_by(pod, secret):
    """Every place in a pod the named Secret is put, by whichever route. A
    volume is reported as itself rather than through the containers that mount
    it: neither holder of this Secret takes it as a file, so one that appears
    is refused whoever mounts it."""
    for _, container in containers_of(pod):
        routes = [
            (entry.get("valueFrom") or {}).get("secretKeyRef") or {}
            for entry in container.get("env") or []
        ] + [source.get("secretRef") or {} for source in container.get("envFrom") or []]
        if any(route.get("name") == secret for route in routes):
            yield container["name"]
    for volume in pod.get("volumes") or []:
        sources = [volume.get("secret") or {}] + [
            source.get("secret") or {}
            for source in (volume.get("projected") or {}).get("sources") or []
        ]
        if any(secret in (source.get("secretName"), source.get("name")) for source in sources):
            yield f"volume {volume['name']}"


def main():
    if len(sys.argv) != 3:
        refuse("usage: rollout-order.py RENDERED_DIRECTORY DUMPS_DIRECTORY_OWNER")
    rendered = {
        layer: documents_in(Path(sys.argv[1]) / f"{layer}.yaml") for layer in LAYERS
    }
    owner = int(sys.argv[2])

    workloads = [
        (layer, document, pod_of(document))
        for layer in LAYERS
        for document in rendered[layer]
        if pod_of(document) is not None
    ]

    # The migration is the Job that runs a release image, wherever it is
    # rendered: found by what it is, so that one moved into another layer is
    # found there and refused rather than not found.
    migrations = [
        (layer, document, pod)
        for layer, document, pod in workloads
        if document.get("kind") == "Job" and releases(pod)
    ]
    if len(migrations) != 1:
        refuse(
            f"expected one Job running a release image, found {len(migrations)}: "
            + ", ".join(f"{described(document)} in {layer}" for layer, document, _ in migrations)
        )
    layer, migration, pod = migrations[0]
    if layer != MIGRATION_LAYER:
        refuse(
            f"{described(migration)} is rendered by cluster/{layer}, and only "
            f"`{MIGRATION_LAYER}` is the layer the services wait on"
        )

    for layer, document, other in workloads:
        if document is migration:
            continue
        if layer == MIGRATION_LAYER:
            refuse(
                f"{described(document)} is rendered by cluster/{MIGRATION_LAYER}, which "
                "applies the migration and no other workload"
            )
        if layer != SERVICE_LAYER and releases(other):
            refuse(
                f"{described(document)} runs a release image in {', '.join(releases(other))} "
                f"and is rendered by cluster/{layer}, which is applied before the "
                "migration has run"
            )
    services = [
        document
        for layer, document, other in workloads
        if layer == SERVICE_LAYER and releases(other)
    ]
    if not services:
        refuse(
            f"cluster/{SERVICE_LAYER} renders no workload running an image under "
            f"{RELEASE_IMAGES}, so what this holds out of the other layers is nothing"
        )

    # Inside the pod. `initContainers` run one at a time and in order, and
    # `containers` start only after the last of them exited 0.
    order = [(group, container["name"]) for group, container in containers_of(pod)]
    dumps = [container for group, container in containers_of(pod) if container["name"] == DUMP]
    if ("initContainers", DUMP) not in order or len(dumps) != 1:
        refuse(
            f"{described(migration)} has no initContainer `{DUMP}`, so nothing is dumped "
            "before the migration runs: " + ", ".join(f"{group}/{name}" for group, name in order)
        )
    dump = dumps[0]
    if "restartPolicy" in dump:
        refuse(
            f"`{DUMP}` sets restartPolicy {dump['restartPolicy']}, and an initContainer that "
            "restarts is a sidecar the next container does not wait for"
        )
    position = order.index(("initContainers", DUMP))
    if ("initContainers", WAIT) not in order[:position]:
        refuse(
            f"`{DUMP}` does not run after initContainer `{WAIT}`, so its first connection "
            "is made before the pod's address is admitted to PostgreSQL"
        )
    early = [
        name
        for group, name in order[:position]
        if name in releases(pod)
    ]
    if early:
        refuse(
            f"{', '.join(early)} runs a release image in {described(migration)} before "
            f"`{DUMP}` has run"
        )

    # The claim, and the directory the script is told to write.
    volumes = {volume["name"]: volume for volume in pod.get("volumes") or []}
    mounts = [
        mount
        for mount in dump.get("volumeMounts") or []
        if (volumes.get(mount["name"], {}).get("persistentVolumeClaim") or {}).get("claimName")
        == CLAIM
    ]
    if len(mounts) != 1 or mounts[0].get("readOnly"):
        refuse(
            f"`{DUMP}` does not mount claim {CLAIM} writable exactly once, so what it "
            "writes is not on the volume kept for it"
        )
    directory = next(
        (
            entry.get("value")
            for entry in dump.get("env") or []
            if entry.get("name") == DIRECTORY_VARIABLE
        ),
        None,
    )
    if directory != mounts[0]["mountPath"]:
        refuse(
            f"`{DUMP}` is told to write {directory} by {DIRECTORY_VARIABLE} and mounts "
            f"claim {CLAIM} at {mounts[0]['mountPath']}"
        )
    namespace = migration["metadata"].get("namespace")
    claims = [
        document
        for document in rendered["apps"]
        if identity(document) == ("PersistentVolumeClaim", namespace, CLAIM)
    ]
    if len(claims) != 1:
        refuse(
            f"cluster/apps renders {len(claims)} claims {namespace}/{CLAIM}, and `apps` is "
            f"the layer `{MIGRATION_LAYER}` waits on for it"
        )

    # Who the pod is to the directory under that claim.
    security = pod.get("securityContext") or {}
    if "fsGroup" in security:
        refuse(
            f"{described(migration)} sets fsGroup {security['fsGroup']}, with which the "
            "kubelet regroups the dumps directory and widens the mode the host set on it"
        )
    uid = (dump.get("securityContext") or {}).get("runAsUser", security.get("runAsUser"))
    if uid != owner:
        refuse(
            f"`{DUMP}` runs as uid {uid} and the host's dumps directory is owned by "
            f"{owner}, which is chuggy.state.dumps.user"
        )

    # Who holds the superuser's password, across everything rendered.
    holders = {
        (*identity(document), place)
        for _, document, other in workloads
        for place in reached_by(other, SUPERUSER_SECRET)
    }
    expected = {(*SERVER, SERVER_CONTAINER), (*identity(migration), DUMP)}
    for holder in sorted(holders - expected, key=str):
        kind, holder_namespace, name, place = holder
        refuse(
            f"Secret {SUPERUSER_SECRET} reaches {place} of {kind} {holder_namespace}/{name}: "
            f"the superuser's password is the server's and `{DUMP}`'s and no other "
            "container's"
        )
    for holder in sorted(expected - holders, key=str):
        kind, holder_namespace, name, place = holder
        refuse(
            f"Secret {SUPERUSER_SECRET} does not reach {place} of {kind} "
            f"{holder_namespace}/{name}, so who holds it was not read"
        )
    servers = [document for document in rendered["apps"] if identity(document) == SERVER]
    server = next(
        container
        for _, container in containers_of(pod_of(servers[0]))
        if container["name"] == SERVER_CONTAINER
    )
    set_from = secret_key(server, SERVER_PASSWORD_VARIABLE)
    read_from = secret_key(dump, PASSWORD_VARIABLE)
    if read_from is None or read_from != set_from:
        refuse(
            f"`{DUMP}` reads {PASSWORD_VARIABLE} from {read_from} and the server sets the "
            f"superuser's password from {set_from}"
        )
    if dump.get("image") != server.get("image"):
        refuse(
            f"`{DUMP}` runs {dump.get('image')} and the server runs {server.get('image')}: "
            "pg_dump refuses a server newer than itself"
        )

    print(
        f"clean: {described(migration)} is the only workload in cluster/{MIGRATION_LAYER}, "
        f"`{DUMP}` runs before any release image in it, and {len(services)} workloads "
        f"running release images are all in cluster/{SERVICE_LAYER}"
    )


if __name__ == "__main__":
    main()
