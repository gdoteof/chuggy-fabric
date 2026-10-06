#!/usr/bin/env python3
"""Refuse a rendered layer directory that is not the layers and the sources
this file names.

Every assertion is made against `kubectl kustomize` output, which is what the
root Kustomization applies, never against the files: a layer file left out of
`resources` reads correctly and is not a layer.

ONLY KUSTOMIZATIONS AND THE TWO SOURCES OF A RELEASE. The root
`modules/flux.nix` generates sets `wait: false`: a Kustomization reports its
own health, and a source reports its own readiness to whatever reads it. Any
other object here would be applied and health-checked by nothing.

THE ROSTER AND EVERY SPEC ARE HELD EXACTLY, so a change to a layer is a change
to this file as well, and that is the point of it. The root prunes, so a layer
that drops out of the render is deleted from the cluster, and one deleted
without `deletionPolicy: Orphan` deletes everything it applied. A `dependsOn`
that drops out has a layer applied before the one its CRDs come from, or the
services of a release applied before its migration has run. `force` dropping
out of `chuggy-migrate` leaves that layer failed on the first edit to a Job
whose name did not change. The BuildRun expressions are what read a run that
succeeded on another commit, or with no digest, as failed. Each of those still
renders, and no other check reads the render.

A SOURCE'S SPEC IS HELD THE SAME WAY, for what would still render: `chuggy` on
another branch has the trigger release commits that are not `main`'s;
`chuggy-release` without `insecure` never reads a registry that is plain HTTP,
and with a `tag` or a `digest` beside its range holds the cluster at one
release without saying so.

BOTH RELEASE LAYERS READ GIT. `chuggy-migrate` and `chuggy` name the `fabric`
source and a path under `./cluster`, as every layer does, though
`chuggy-release` is declared beside them. Moving them to it is a change to
`LAYERS` below.

NOTHING APPLIES `./results`, which is provenance and holds no manifest.
tests/flux-wiring.nix argues it for the path the host generates; a layer is the
other thing that names one. Held apart from the roster because a layer added on
purpose is added to the roster with it.
"""

import json
import re
import sys
from pathlib import Path

import yaml

API_VERSION = "kustomize.toolkit.fluxcd.io/v1"
KIND = "Kustomization"
NAMESPACE = "flux-system"


def folded(expression):
    return " ".join(expression.split())


BUILD_RUN_HEALTH = {
    "apiVersion": "shipwright.io/v1beta1",
    "kind": "BuildRun",
    "inProgress": folded(
        """
        !has(status.conditions) ||
        status.conditions.filter(e, e.type == 'Succeeded').all(e, e.status == 'Unknown')
        """
    ),
    "failed": folded(
        """
        has(status.conditions) &&
        (status.conditions.filter(e, e.type == 'Succeeded').exists(e, e.status == 'False') ||
        (status.conditions.filter(e, e.type == 'Succeeded').exists(e, e.status == 'True') &&
        (!has(status.source) || !has(status.source.git) ||
        status.source.git.commitSha != metadata.annotations['fabric.chuggy.dev/source-commit'] ||
        !has(status.output) || !has(status.output.digest) ||
        !status.output.digest.matches('^sha256:[0-9a-f]{64}$'))))
        """
    ),
    "current": folded(
        """
        has(status.conditions) &&
        status.conditions.filter(e, e.type == 'Succeeded').exists(e, e.status == 'True') &&
        has(status.source) && has(status.source.git) &&
        status.source.git.commitSha == metadata.annotations['fabric.chuggy.dev/source-commit'] &&
        has(status.output) && has(status.output.digest) &&
        status.output.digest.matches('^sha256:[0-9a-f]{64}$')
        """
    ),
}


def layer(path, timeout="3m", **rest):
    return {
        "interval": "5m",
        "path": path,
        "sourceRef": {"kind": "GitRepository", "name": "fabric"},
        "prune": True,
        "wait": True,
        "timeout": timeout,
        **rest,
    }


LAYERS = {
    "apps": layer("./cluster/apps", deletionPolicy="Orphan"),
    "build-prerequisites": layer("./cluster/build-prerequisites"),
    "build-system": layer(
        "./cluster/build-system", dependsOn=[{"name": "build-prerequisites"}]
    ),
    "builds": layer(
        "./builds",
        timeout="75m",
        dependsOn=[{"name": "build-system"}],
        healthCheckExprs=[BUILD_RUN_HEALTH],
    ),
    "chuggy-migrate": layer(
        "./cluster/chuggy-migrate",
        timeout="30m",
        dependsOn=[{"name": "apps"}],
        force=True,
    ),
    "chuggy": layer(
        "./cluster/chuggy", timeout="15m", dependsOn=[{"name": "chuggy-migrate"}]
    ),
}


SOURCES = {
    ("source.toolkit.fluxcd.io/v1", "GitRepository", "chuggy"): {
        "interval": "1m",
        "url": "https://github.com/kasofsk/chuggy.git",
        "ref": {"branch": "main"},
    },
    ("source.toolkit.fluxcd.io/v1", "OCIRepository", "chuggy-release"): {
        "interval": "1m",
        "url": "oci://registry.chuggy-registry.svc.cluster.local:5000/chuggy/release",
        "insecure": True,
        "ref": {"semver": "*"},
    },
}


def refuse(message):
    raise SystemExit(f"flux-layers: {message}")


def shown(spec, key):
    return json.dumps(spec[key], sort_keys=True) if key in spec else "absent"


def main():
    if len(sys.argv) != 2:
        refuse("usage: flux-layers.py RENDERED_MANIFEST")
    documents = [
        document
        for document in yaml.safe_load_all(Path(sys.argv[1]).read_text())
        if document
    ]

    rendered, sources = {}, {}
    for document in documents:
        kind, name = document.get("kind"), document["metadata"].get("name")
        source = (document.get("apiVersion"), kind, name)
        if (document.get("apiVersion"), kind) != (API_VERSION, KIND) and source not in SOURCES:
            refuse(
                f"the render holds {kind} {name}, and the root applying it waits "
                "on nothing: what is neither a Flux Kustomization nor a source "
                "held here is health-checked by nothing"
            )
        if document["metadata"] != {"name": name, "namespace": NAMESPACE}:
            refuse(
                f"{kind} {name} carries metadata {json.dumps(document['metadata'])}, "
                f"not a name in `{NAMESPACE}` and nothing else"
            )
        held = sources if source in SOURCES else rendered
        key = source if source in SOURCES else name
        if key in held:
            refuse(f"{kind} {name} is rendered more than once")
        held[key] = document.get("spec") or {}

    for name, spec in rendered.items():
        if re.fullmatch(r"(\./)?results(/.*)?", str(spec.get("path"))):
            refuse(f"layer {name} applies {spec['path']}, where nothing is a manifest")

    for name in sorted(LAYERS.keys() - rendered.keys()):
        refuse(f"layer {name} is not rendered, and the root prunes what it stops applying")
    for name in sorted(rendered.keys() - LAYERS.keys()):
        refuse(f"layer {name} is rendered and is not one this check holds a spec for")

    for kind, name in sorted((kind, name) for _, kind, name in SOURCES.keys() - sources.keys()):
        refuse(f"{kind} {name} is not rendered, and the root prunes what it stops applying")

    held = [(f"layer {name}", expected, rendered[name]) for name, expected in LAYERS.items()]
    held += [(f"{kind} {name}", expected, sources[_, kind, name]) for (_, kind, name), expected in SOURCES.items()]
    for subject, expected, spec in held:
        differing = [
            f"{key}: expected {shown(expected, key)}, rendered {shown(spec, key)}"
            for key in sorted(expected.keys() | spec.keys())
            if shown(expected, key) != shown(spec, key)
        ]
        if differing:
            refuse(f"{subject} is not the spec held here -- " + "; ".join(differing))


if __name__ == "__main__":
    main()
