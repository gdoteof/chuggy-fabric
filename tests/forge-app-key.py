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

AND THE SECRET IS THE APP'S, NOT MERELY A SECRET. The two keys arrive in two
Secrets, one an App, and a volume that names the other one projects a key that
reads and signs and is refused by GitHub -- the failure at the top of this file
again, reached from the mount rather than from the id. So `keySecret` sits
beside `appId` on the host, the same second declaration that makes an id a copy
rather than a literal, and a minter's volume must name the Secret of the App
whose id it writes.

AND ONE REMOTE IS NOT MINTED FOR AT ALL, WHICH IS THE SAME DEFECT INVERTED. The
finalizer promotes to `rig.git` on this cluster's own git service, which no App
key covers, so that one credential is a file the operator made and a path this
pod opens -- the shape above with a hand-made Secret in place of a key. It is
held here because a manifest that lost it renders, starts, mints for every forge
repository as designed, and fails every promotion to the tree Flux reconciles
this cluster from, which is the quietest failure in this file. The api and the
ticket service can be told to authenticate from a file the same way and today
are not, so what is held of them is that same rule over however many entries
there are: none is the shape they are in, and an entry that appears is an
in-cluster remote at a path something projects, or it is a credential nobody
can account for. The importer's list is held at empty by its own gate, which is
where the reason it stays a present key is written.

AND A MINTER THAT CANNOT REACH THE FORGE CANNOT MINT, which is the last of the
three things a mint needs and the only one that is not in the pod. A key, an id
and a route: the pod's egress policy is the route, and every defect in it is one
this file's subject already owns -- an arm on port 80 refuses every mint, an arm
with no `ports` admits every port on the internet, and an arm on `0.0.0.0/1` is
half of it, the half GitHub is not addressed in. So the arm is READ here rather
than counted: a grep over the manifest can say a range occurs somewhere in it
and cannot say what any one arm admits.

WHAT THIS GATE CANNOT SEE. Whether a named Secret exists or holds the App's
key, which is the operator's prerequisite 5 and no render's business: what is
held here is that the manifest, the host and the App agree on which Secret that
is. Nor whether the image reads either variable: that is the release's, and the
manifests carry both before the image that reads them is pinned.
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


# Where a pod is told to find a credential no App mints, and how many such
# credentials it is to have. One row a workload, naming a variable or a field
# of one as MINTERS does: the list is the whole of what a pod authenticates as
# without minting, and an entry is added to it only for a host the App keys
# above do not cover.
#
# A COUNT IS HELD ONLY WHERE THE CREDENTIAL IS LOAD-BEARING. The finalizer's
# one entry is the promotion path this cluster is reconciled from and its loss
# is silent, so that row is held at exactly one. The other two mint everything
# they present; `None` is what says so, and it permits an absent variable and
# an empty list alike -- adding a static credential to one of these is a
# decision, not a defect, and what this refuses is an entry nobody can account
# for rather than the entry itself.
SOURCES = (
    ("chuggy-finalizer", "CHUG_FINALIZER_CREDENTIAL_SOURCES", 1),
    ("chuggy-api", "CHUG_API_REPOSITORY_CREDENTIAL_SOURCES", None),
    (
        "chuggy-ticket-service",
        ("CHUG_TICKET_SERVICE_CONFIG", ("source", "sources")),
        None,
    ),
)

# A host the worker plane and these pods mint for is a forge, and everything
# else on this site is addressed inside the cluster. So an in-cluster address is
# what a static credential is admissible for, and a public one in that list is a
# token that does not expire standing where a mint belongs.
IN_CLUSTER = ".svc.cluster.local"

# The arm every minter above reaches the forge through. A mint is an HTTPS
# request to `api.github.com`, and a NetworkPolicy matches addresses rather than
# names, so the narrowest arm expressible is public HTTPS with this site's own
# ranges taken back out of it --
# cluster/apps/chuggy-control-plane-network-policy.yaml argues that at length
# over the finalizer's rule and every arm here is that one's shape.
PUBLIC = "0.0.0.0/0"
PUBLIC_PORT = 443

# The ranges that come out, each because this site addresses something of its
# own inside it: an arm that reached one of them would be reaching a neighbour
# on the strength of a rule written for the internet.
EXCEPTED = {
    "10.0.0.0/8",  # RFC 1918, and the pod and service networks are inside it
    "100.64.0.0/10",  # carrier-grade NAT
    "127.0.0.0/8",  # loopback
    "169.254.0.0/16",  # link-local, and the metadata address inside it
    "172.16.0.0/12",  # RFC 1918
    "192.168.0.0/16",  # RFC 1918, and this site's own LAN
}


def refuse(message):
    raise SystemExit(f"forge app key: {message}")


def workload(documents, name):
    """The pod labels, pod and container of a workload in the control namespace.

    A CronJob is one of these as much as a Deployment is: the importer mints
    from the same key on a schedule, and a pod that never runs until 02:00 is
    the one whose broken mount is discovered latest.

    The labels come back with the rest because a NetworkPolicy is matched
    against them and against nothing else: the workload's name is not what any
    policy below names."""
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
    template = (
        document["spec"]["jobTemplate"]["spec"]["template"]
        if document["kind"] == "CronJob"
        else document["spec"]["template"]
    )
    pod = template["spec"]
    containers = pod["containers"]
    if len(containers) != 1:
        refuse(f"{name} declares {len(containers)} containers, wanted one")
    return template["metadata"].get("labels", {}), pod, containers[0]


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


def listed(container, spec, owner):
    """The static credentials a row names, or None when the manifest names none.

    Absence is the whole difference from `field` above: a row of MINTERS names
    a value a pod cannot work without, and a row here names one three of these
    four are correct to leave out. So a variable that is not declared and a
    field the configuration document does not carry are both None, and every
    rule below is over the entries there are."""
    if isinstance(spec, str):
        if not any(entry["name"] == spec for entry in container.get("env", [])):
            return None
        document = variable(container, spec, owner)
        name, path = spec, ()
    else:
        name, path = spec
        document = variable(container, name, owner)
    try:
        value = json.loads(document)
    except json.JSONDecodeError as error:
        refuse(f"{owner} writes {name}, which is not JSON: {error}")
    for step in path:
        if not isinstance(value, dict) or step not in value:
            return None
        value = value[step]
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


def selects(selector, labels, described):
    """Whether a podSelector matches one pod's labels.

    Only `matchLabels` is evaluated, which is what every egress policy in the
    control namespace selects a workload by; an expression is refused rather
    than guessed at, because a selector this gate misread would report an arm
    as another workload's."""
    if selector.get("matchExpressions"):
        refuse(f"{described} selects by matchExpressions, which this gate cannot evaluate")
    matched = selector.get("matchLabels") or {}
    return all(labels.get(key) == value for key, value in matched.items())


def public_https(documents, name, labels):
    """The one arm a minter reaches the forge through, held against what it admits.

    A minter whose egress cannot reach public HTTPS cannot mint: every App key
    above buys its tokens from `api.github.com` and nothing else does. So the
    arm is parsed here rather than grepped for. What the arm is FOUND by is its
    shape -- a `to` that is one `ipBlock` -- and what is then held of it is
    every term that decides its reach, so that a port, a cidr or a missing
    exception is a refusal here rather than a rule that reads correctly and
    lands a pod on the wrong half of the internet.

    NETWORKPOLICIES ARE ADDITIVE, so the arms are folded across every policy in
    the namespace that selects this pod for egress rather than read off one
    object: a second policy carrying a wider ipBlock would leave the first
    reading exactly as it does now."""
    policies = [
        document
        for document in documents
        if document.get("kind") == "NetworkPolicy"
        and document["metadata"].get("namespace") == CONTROL
        and "Egress" in (document["spec"].get("policyTypes") or [])
        and selects(document["spec"]["podSelector"], labels, document["metadata"]["name"])
    ]
    if not policies:
        refuse(
            f"no NetworkPolicy in {CONTROL} isolates the {name} pod for egress, so nothing "
            "states where a pod holding an App key may go"
        )
    named = ", ".join(sorted(document["metadata"]["name"] for document in policies))

    arms = [
        (document["metadata"]["name"], arm)
        for document in policies
        for arm in document["spec"].get("egress") or []
        if len(arm.get("to") or []) == 1 and "ipBlock" in arm["to"][0]
    ]
    if len(arms) != 1:
        refuse(
            f"{named} carries {len(arms)} arms reaching an ipBlock, wanted one: {name} mints "
            f"from {PUBLIC}:{PUBLIC_PORT} and an arm nothing here resolved is a reach nothing "
            "here bounds"
        )
    policy, arm = arms[0]

    block = arm["to"][0]["ipBlock"]
    if block.get("cidr") != PUBLIC:
        refuse(
            f"the public arm of {policy} names cidr {block.get('cidr')!r} rather than {PUBLIC}, "
            f"so the addresses {name} mints from are half the internet at most"
        )
    if set(block.get("except") or []) != EXCEPTED:
        refuse(
            f"the public arm of {policy} excepts {sorted(block.get('except') or [])} rather "
            f"than {sorted(EXCEPTED)}, so {name} reaches this site's own addresses on a rule "
            "written for the internet, or is refused a forge it is not"
        )
    # An absent `ports` admits every port, so the list is compared whole rather
    # than searched for the one that should be in it; and an entry carrying
    # endPort admits a range that starts at the number read here, so it is
    # refused before that number is.
    for port in arm.get("ports") or []:
        if "endPort" in port:
            refuse(
                f"the public arm of {policy} names endPort, which admits a range: this "
                f"gate reads one port and would see only the number the range starts at"
            )
    admitted = [
        (port.get("protocol", "TCP"), port.get("port"))
        for port in arm.get("ports") or []
    ]
    if admitted != [("TCP", PUBLIC_PORT)]:
        refuse(
            f"the public arm of {policy} admits {admitted} rather than TCP {PUBLIC_PORT} "
            f"alone, so {name} either cannot open HTTPS to the forge it mints from or may "
            "open every port on the internet"
        )


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
        _, pod, container = workload(documents, name)
        declared = field(container, id_variable, name)
        if declared != apps[app]["appId"]:
            refuse(
                f"{name} mints as App {declared}; the host holds the {app} App's key under "
                f"{apps[app]['appId']}, so that JWT is signed with the wrong key"
            )
        source = projected(pod, container, field(container, file_variable, name), name)
        if source[0] != apps[app]["keySecret"]:
            refuse(
                f"{name} mints as the {app} App and reads its key from {source[0]}; the host "
                f"hands that App's key over in {apps[app]['keySecret']}, so what this pod signs "
                "with is another App's key"
            )
        held_app, held_variable = read_as.setdefault((name, source), (app, file_variable))
        if held_app != app:
            refuse(
                f"{name} reads the {held_app} App's key and the {app} App's from one "
                f"projection: {spelled(held_variable)} and {spelled(file_variable)} both "
                f"resolve to {source[0]}/{source[1]}, so one of the two signs its JWT as an "
                "App whose key that is not"
            )

    # And every one of those workloads can reach the forge it mints from. One
    # visit a pod rather than one a row: the API holds two Apps' keys and has
    # one egress policy, and the arm is the pod's.
    for name in dict.fromkeys(row[0] for row in MINTERS):
        labels, _, _ = workload(documents, name)
        public_https(documents, name, labels)

    for name, spec, wanted_rows in SOURCES:
        _, pod, container = workload(documents, name)
        sources = listed(container, spec, name)
        if sources is None:
            sources = []
        if not isinstance(sources, list):
            refuse(f"{name} names {spelled(spec)} as something other than a list of credentials")
        if wanted_rows is not None and len(sources) != wanted_rows:
            refuse(
                f"{name} names {spelled(spec)} as something other than one credential; the one "
                "remote no App key mints for is this cluster's own git service, and a second "
                "entry is a credential that does not expire where a mint belongs"
            )
        for source in sources:
            remote = source.get("repository") if isinstance(source, dict) else None
            path = source.get("path") if isinstance(source, dict) else None
            if not isinstance(remote, str) or not isinstance(path, str):
                refuse(f"{name}'s {spelled(spec)} entry names no repository and path")
            host = (urlsplit(remote).hostname or "").rstrip(".")
            if not host.endswith(IN_CLUSTER):
                refuse(
                    f"{name} authenticates to {remote} from a file; a repository on a forge is "
                    "minted for per act from the App key this pod mounts"
                )
            carried(pod, container, path, name)


main()
