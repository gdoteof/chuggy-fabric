#!/usr/bin/env python3
"""Refuse a rendered cluster that tells a pod to mint from a GitHub App key the
pod does not carry, or to mint as an App whose key the host does not hold.

A pod that mints its own installation tokens needs three things to agree: an App
id, a file the process opens, and a projection that puts the App's private key
at exactly that path. Each of the three reads correctly while another is wrong,
and neither wrong one is visible until the pod is running -- a path nothing
projects is an `ENOENT` at the first mint, and an id belonging to the other App
is a JWT signed with the wrong key, which GitHub refuses and nothing here can.

AND THE PROJECTION ITSELF IS THREE MORE OF THE SAME. Read-only, required, and a
mode the container's own uid can open: a Secret volume's files are written owned
by uid 0 and only an `fsGroup` moves their group, so a mode with no world read
bit is a key the process it is for cannot read -- `0400` looks like the careful
value for a private key and is the one that fails. `optional: true` is the other:
it turns a missing key from a pod that never starts into a pod that starts and
cannot mint, which is the opposite of what a required credential is for.

THE ID IS HELD AGAINST THE HOST AND NOT AGAINST A LITERAL. `chuggy.githubAppTokens`
on the host is where an App's id and its key file are declared together, and the
Secret a pod mounts is made by hand from that key file. So the id written in a
manifest is a second copy of the host's, and this is what makes them one value.

AND TWO APPS IN ONE POD MUST NOT READ ONE PROJECTION. A workload holding two
Apps' keys can name one App's id beside the other App's key file and everything
above still passes: the path resolves to a mount, the mount and its volume are
sound, and each id is the host's. What that pod would sign is a JWT claiming one
App under the other App's key -- the failure at the top of this file, reached
from the other side, and one the process itself cannot catch, because reading a
key file proves only that it is a key. So two rows of one workload naming
different Apps must resolve to different (Secret, key) projections.

AND ONE REMOTE IS NOT MINTED FOR AT ALL, WHICH IS THE SAME DEFECT INVERTED. The
finalizer promotes to `rig.git` on this cluster's own git service, which no App
key covers, so that one credential is a file the operator made and a path this
pod opens -- the shape above with a hand-made Secret in place of a key. It is
held here because a manifest that lost it renders, starts, mints for every forge
repository as designed, and fails every promotion to the tree Flux reconciles
this cluster from, which is the quietest failure in this file.

WHAT THIS GATE CANNOT SEE. Which Secret the key comes from, because a hand-made
Secret has no second declaration to be held against: nothing but the manifest
and the README's prerequisite 5 names it, and a gate over the manifest's own
literal would agree with it however it changed. The rule above closes part of
that where a workload carries two rows -- a volume that borrowed the other App's
`secretName` puts both rows on one projection, which the render alone decides --
and a workload with a single row is blind to its `secretName` as before. Nor
whether that Secret exists or holds the App's key, which is the operator's step
and no render's business. Nor whether the image reads either variable: that is
the release's, and the manifests carry both before the image that reads them is
pinned.
"""

import json
import sys
from urllib.parse import urlsplit

import yaml

CONTROL = "chuggy"

# Every (workload, App) pair a manifest names a key for; a workload holding two
# Apps' keys is two rows. A pod that grows a key mount and is not added here is
# unchecked, and this file is where that is noticed or nowhere.
#
# AN ID AND A FILE ARE EACH A VARIABLE OR A FIELD OF ONE. Three of these
# commands read a whole configuration document out of one variable, so a row
# names either the variable or the variable and the path to the value inside it;
# what is held of the value is the same either way.
MINTERS = (
    ("chuggy-api", "portal", "CHUG_API_FORGE_APP_ID", "CHUG_API_FORGE_APP_KEY_FILE"),
    (
        "chuggy-api",
        "worker",
        "CHUG_API_FORGE_WORKER_APP_ID",
        "CHUG_API_FORGE_WORKER_APP_KEY_FILE",
    ),
    (
        "chuggy-worker-plane",
        "worker",
        "CHUG_WORKER_PLANE_FORGE_APP_ID",
        "CHUG_WORKER_PLANE_FORGE_APP_KEY_FILE",
    ),
    (
        "chuggy-finalizer",
        "portal",
        "CHUG_FINALIZER_FORGE_APP_ID",
        "CHUG_FINALIZER_FORGE_APP_KEY_FILE",
    ),
    (
        "chuggy-ticket-service",
        "portal",
        ("CHUG_TICKET_SERVICE_CONFIG", ("forge", "appId")),
        ("CHUG_TICKET_SERVICE_CONFIG", ("forge", "keyFile")),
    ),
    (
        "chuggy-configuration-importer",
        "portal",
        ("CHUG_CONFIGURATION_IMPORT_CONFIG", ("forge", "appId")),
        ("CHUG_CONFIGURATION_IMPORT_CONFIG", ("forge", "keyFile")),
    ),
)


# Where a pod is told to find a credential no App mints, and the remote that
# credential is for. One row a workload: the list is the whole of what a pod
# authenticates as without minting, and an entry is added to it only for a host
# the App keys above do not cover.
SOURCES = (("chuggy-finalizer", "CHUG_FINALIZER_CREDENTIAL_SOURCES"),)

# A host the worker plane and these pods mint for is a forge, and everything
# else on this site is addressed inside the cluster. So an in-cluster address is
# what a static credential is admissible for, and a public one in that list is a
# token that does not expire standing where a mint belongs.
IN_CLUSTER = ".svc.cluster.local"


def refuse(message):
    raise SystemExit(f"forge app key: {message}")


def workload(documents, name):
    """The pod and container of a workload in the control namespace.

    A CronJob is one of these as much as a Deployment is: the importer mints
    from the same key on a schedule, and a pod that never runs until 02:00 is
    the one whose broken mount is discovered latest."""
    found = [
        document
        for document in documents
        if document.get("kind") in ("Deployment", "CronJob")
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == CONTROL
    ]
    if len(found) != 1:
        refuse(f"the render carries {len(found)} workloads named {name} in {CONTROL}, wanted one")
    document = found[0]
    pod = (
        document["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        if document["kind"] == "CronJob"
        else document["spec"]["template"]["spec"]
    )
    containers = pod["containers"]
    if len(containers) != 1:
        refuse(f"{name} declares {len(containers)} containers, wanted one")
    return pod, containers[0]


def variable(container, name, owner):
    found = [entry for entry in container.get("env", []) if entry["name"] == name]
    if len(found) != 1:
        refuse(f"{owner} declares {name} {len(found)} times, wanted once")
    value = found[0].get("value")
    if value is None:
        refuse(f"{owner} takes {name} from somewhere other than a literal")
    # `EnvVar.value` is a string, and an App id is all digits, so dropping its
    # quotes renders a YAML number that kustomize is happy to emit and the API
    # server refuses: `cannot unmarshal number into Go struct field
    # EnvVar.value of type string`.
    if not isinstance(value, str):
        refuse(
            f"{owner} writes {name} unquoted, so it renders as a YAML "
            f"{type(value).__name__} rather than the string `EnvVar.value` takes, and the "
            "API server refuses the manifest"
        )
    return value


def spelled(spec):
    """How a row names a value, for a refusal to print."""
    return spec if isinstance(spec, str) else f"{spec[0]}'s {'.'.join(spec[1])}"


def field(container, spec, owner):
    """The value a row names: a whole variable, or one field inside the JSON
    document a variable carries.

    A configuration document is a literal like any other, so what is wrong with
    it is wrong in the same two ways -- an id that is not the host's, and a path
    nothing projects -- and the refusals below are the ones written for a bare
    variable, reached through the document."""
    if isinstance(spec, str):
        return variable(container, spec, owner)
    name, path = spec
    document = variable(container, name, owner)
    try:
        value = json.loads(document)
    except json.JSONDecodeError as error:
        refuse(f"{owner} writes {name}, which is not JSON: {error}")
    for step in path:
        if not isinstance(value, dict) or step not in value:
            refuse(f"{owner}'s {name} names no {'.'.join(path)}")
        value = value[step]
    # The same defect as an unquoted `EnvVar.value`, one level in: an App id
    # written as a JSON number is a number the command reads as a string or
    # refuses, and either way it is not the host's id spelled the host's way.
    if not isinstance(value, str):
        refuse(
            f"{owner} writes {name}'s {'.'.join(path)} as a JSON "
            f"{type(value).__name__} rather than a string"
        )
    return value


def readable(pod, mode, wanted, owner, subject):
    """The kubelet writes a Secret volume's files owned by uid 0 and applies
    `fsGroup` to the group and nothing else, so without one a mode with no world
    read bit is a file the container's own uid cannot open. Unset is the
    kubelet's own 0644 and is readable."""
    if mode is None or mode & 0o004:
        return
    if pod.get("securityContext", {}).get("fsGroup") is not None:
        return
    refuse(
        f"{owner} projects {subject} at {wanted} with mode {mode:04o} and declares no "
        "`fsGroup`, so the file is uid 0's alone and the process it is for cannot open it"
    )


def standing_over(container, wanted, owner, subject):
    """The one mount a container serves an absolute path from, or a refusal."""
    # The path itself as well as a directory over it: mounting one key as a file
    # is a shape a manifest can take, and a gate that saw only the directory
    # would tell its author to add a mount that is already there.
    mounts = [
        mount
        for mount in container.get("volumeMounts", [])
        if mount["mountPath"].rstrip("/") == wanted
        or wanted.startswith(mount["mountPath"].rstrip("/") + "/")
    ]
    if len(mounts) != 1:
        refuse(f"{len(mounts)} of {owner}'s volume mounts stand over {wanted}, wanted one")
    mount = mounts[0]
    if not mount.get("readOnly"):
        refuse(f"{owner} mounts {subject} writable at {mount['mountPath']}")
    # A subPath is resolved once when the container is created and never
    # afterwards, so a rotated Secret does not reach a pod through one --
    # hosts/gtr already says rotating this key is two places, and this would
    # make it three. It is also where a mount can name a path inside the volume
    # that holds nothing, which no prefix match below would see.
    if mount.get("subPath") or mount.get("subPathExpr"):
        refuse(
            f"{owner} mounts {subject} at {mount['mountPath']} through a subPath, which is "
            "resolved once and never follows the Secret afterwards"
        )
    return mount


def volume_of(pod, mount, owner):
    volume = [entry for entry in pod.get("volumes", []) if entry["name"] == mount["name"]]
    if len(volume) != 1:
        refuse(f"{owner} mounts {mount['name']}, which the pod declares {len(volume)} times")
    return volume[0]


def secret_sources(volume, mount, owner):
    projection = volume.get("projected")
    sources = projection["sources"] if projection else [{"secret": volume.get("secret", {})}]
    for source in sources:
        if source.get("secret") is None:
            refuse(f"{owner}'s {mount['name']} volume projects something other than a Secret")
    return projection, sources


def carried(pod, container, wanted, owner):
    """The Secret a container serves a hand-made credential file from.

    Unlike an App key this file does not require the key to be named: the
    credential is one the operator creates by hand, a whole Secret projected
    serves every key it has at its own name, and naming the keys here would be
    this gate agreeing with a manifest it copied. What is held is that the path
    the process opens stands under a mount, that the mount serves a Secret and
    that the file is readable -- a path under no mount is an `ENOENT` on the
    first push, and that is the failure this catches."""
    mount = standing_over(container, wanted, owner, "a credential")
    relative = wanted[len(mount["mountPath"].rstrip("/")) + 1 :]
    volume = volume_of(pod, mount, owner)
    projection, sources = secret_sources(volume, mount, owner)
    for source in sources:
        secret = source["secret"]
        items = secret.get("items")
        if items is not None and not any(item["path"] == relative for item in items):
            continue
        if secret.get("optional"):
            refuse(
                f"{owner} projects the Secret behind {wanted} optionally, so a pod without it "
                "starts and cannot authenticate rather than not starting"
            )
        mode = next(
            (item.get("mode") for item in items or [] if item["path"] == relative),
            None,
        )
        if mode is None:
            mode = (projection or secret).get("defaultMode")
        readable(pod, mode, wanted, owner, "a credential")
        return secret.get("name") or secret.get("secretName")
    refuse(f"{owner} reads {wanted}, which no Secret its pod projects serves")


def projected(pod, container, wanted, owner):
    """The (secret, key) a container serves at an absolute path, or a refusal."""
    mount = standing_over(container, wanted, owner, "its App key")
    relative = wanted[len(mount["mountPath"].rstrip("/")) + 1 :]
    volume = volume_of(pod, mount, owner)
    projection, sources = secret_sources(volume, mount, owner)
    served = {}
    for source in sources:
        secret = source["secret"]
        # A whole Secret projected serves every key at its own name, so a Secret
        # that has lost the key mounts an empty directory and the pod starts
        # without it. Naming the key is what makes the absence a FailedMount.
        for item in secret.get("items") or []:
            served[item["path"]] = (
                secret.get("name") or secret.get("secretName"),
                item["key"],
                bool(secret.get("optional")),
                item.get("mode"),
            )
    if relative not in served:
        refuse(f"{owner} reads its App key from {wanted}, which its pod projects from no Secret key")
    name, key, optional, mode = served[relative]
    # An item's own mode overrides the volume's default for that file alone, so
    # it is the one place this key's mode is decided -- and the place a `0400`
    # gets written while the `0444` beside it goes on looking right.
    if mode is None:
        mode = (projection or volume.get("secret", {})).get("defaultMode")
    readable(pod, mode, wanted, owner, "its App key")
    if optional:
        refuse(
            f"{owner} projects {name}/{key} optionally, so a pod with no App key starts and "
            "cannot mint rather than not starting"
        )
    return name, key


def main():
    if len(sys.argv) != 3:
        refuse("usage: forge-app-key.py APPS RENDERED_MANIFEST")
    with open(sys.argv[1], encoding="utf-8") as handle:
        apps = json.load(handle)
    with open(sys.argv[2], encoding="utf-8") as handle:
        documents = [document for document in yaml.safe_load_all(handle) if document]

    # Which App each (workload, projection) is read as, so that a second row
    # landing on the first's Secret and key is the collision below.
    read_as = {}
    for name, app, id_variable, file_variable in MINTERS:
        if app not in apps:
            refuse(f"{name} mints as the {app} App, which the host does not declare")
        pod, container = workload(documents, name)
        declared = field(container, id_variable, name)
        if declared != apps[app]["appId"]:
            refuse(
                f"{name} mints as App {declared}; the host holds the {app} App's key under "
                f"{apps[app]['appId']}, so that JWT is signed with the wrong key"
            )
        source = projected(pod, container, field(container, file_variable, name), name)
        held_app, held_variable = read_as.setdefault((name, source), (app, file_variable))
        if held_app != app:
            refuse(
                f"{name} reads the {held_app} App's key and the {app} App's from one "
                f"projection: {spelled(held_variable)} and {spelled(file_variable)} both "
                f"resolve to {source[0]}/{source[1]}, so one of the two signs its JWT as an "
                "App whose key that is not"
            )

    for name, variable_name in SOURCES:
        pod, container = workload(documents, name)
        raw = variable(container, variable_name, name)
        try:
            sources = json.loads(raw)
        except json.JSONDecodeError as error:
            refuse(f"{name} writes {variable_name}, which is not JSON: {error}")
        if not isinstance(sources, list) or len(sources) != 1:
            refuse(
                f"{name} names {variable_name} as something other than one credential; the one "
                "remote no App key mints for is this cluster's own git service, and a second "
                "entry is a credential that does not expire where a mint belongs"
            )
        for source in sources:
            remote = source.get("repository")
            path = source.get("path")
            if not isinstance(remote, str) or not isinstance(path, str):
                refuse(f"{name}'s {variable_name} entry names no repository and path")
            host = (urlsplit(remote).hostname or "").rstrip(".")
            if not host.endswith(IN_CLUSTER):
                refuse(
                    f"{name} authenticates to {remote} from a file; a repository on a forge is "
                    "minted for per act from the App key this pod mounts"
                )
            carried(pod, container, path, name)


main()
