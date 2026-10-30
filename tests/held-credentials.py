#!/usr/bin/env python3
"""Refuse a rendered cluster on whose roster of held credentials the worker
plane would not start, or which would serve a runner's job another Secret, under
another name or to another project, than this file names.

usage: held-credentials.py RENDERED

THE ROSTER IS READ AS CHUGGY READS IT, because the plane does not start on one
it refuses, and the plane it would have replaced keeps serving while the layer
waits. `CHUG_WORKER_PLANE_HELD_CREDENTIALS` is JSON: a list of at most 256
objects with exactly `credential`, `tenant`, `project`, `variable` and `file`,
each a non-empty string, `file` at most 4096 long and the rest at most 256. A
variable is upper case, ends `_FILE` and starts with none of `CHUG_`, `CLAUDE_`
and `GIT_`. No credential is held twice for one project. The rules are
`heldCredentialRoster`'s, in kasofsk/chuggy's
`src/interpreter/workerPlaneHeldCredentials.ts`, which no check here can run.

A `file` IS A FILE ITS POD HAS, OF A SECRET. The plane reads each one before it
starts and refuses to start on one it cannot read, so a path no mount serves is
a plane that never comes ready. It is where the one mount of the plane's
container that stands over it puts one key of a Secret volume, and not by a
`subPath`: the plane reads the file again on every request so that a rotated
Secret is served without a restart, and a subPath is a copy the kubelet never
brings up to date. Its mode is one the container's user reads, who owns no file
of a Secret volume.

WHICH SECRET LEAVES FOR WHICH PROJECT IS WRITTEN HERE TOO. A held credential is
served to a job outside this cluster, so an entry hands a Secret's bytes to one
project's runners. HELD names, for each credential and project, the variable it
is written under and the Secret and key it is read from, and the roster is
exactly those. Another Secret in `chuggy` with the same key mounts, reads and is
served, and nothing but this says it was the wrong one. The variable is what the
job finds the file by: kasofsk/chuggy's `ci.sh` reads its token from
`TRACK_RECORD_TOKEN_FILE`, and under any other name every gate on a runner runs
fresh and nothing fails.

AND A CREDENTIAL HELD IS ONE THE SCHEDULER GRANTS. The plane serves an attempt
only what the grant recorded for it names, and that grant is at most its arm's,
`Work` or `Evaluation`, in the scheduler's policy, so a credential neither arm
grants is held for no one.

WHAT THIS CANNOT SEE. Whether the Secret exists or holds a token, which nothing
here declares. Nor whether a project's configuration asks for the credential,
which is the project's.
"""

import json
import re
import sys
from pathlib import Path

import yaml

CONTROL = "chuggy"
PLANE = "chuggy-worker-plane"
ROSTER = "CHUG_WORKER_PLANE_HELD_CREDENTIALS"
SCHEDULER = "chuggy-scheduler"
EXECUTION_POLICY = "CHUG_SCHEDULER_EXECUTION_POLICY"
ARMS = ("Work", "Evaluation")

# Each credential the plane holds, by tenant, project and the name a grant gives
# it: the variable a job's environment names its file by, and the Secret and key
# that file is of.
HELD = {
    ("vteng", "chuggy", "track-record"): (
        "TRACK_RECORD_TOKEN_FILE",
        "track-record-chuggy-runners",
        "token",
    ),
}

# chuggy's rules for a roster.
ENTRY_FIELDS = {"credential", "tenant", "project", "variable", "file"}
HELD_MAX = 256
CHARS_MAX = {"credential": 256, "tenant": 256, "project": 256, "variable": 256, "file": 4_096}
VARIABLE = re.compile(r"[A-Z][A-Z0-9_]*_FILE")
VARIABLE_RESERVED = ("CHUG_", "CLAUDE_", "GIT_")
# What a Secret volume's files are when it names no mode.
DEFAULT_MODE = 0o644


def refuse(message):
    raise SystemExit(f"held-credentials: {message}")


def objects(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def deployment(documents, name):
    found = [
        document
        for document in documents
        if document.get("kind") == "Deployment"
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == CONTROL
    ]
    if len(found) != 1:
        refuse(f"the render carries {len(found)} Deployments {CONTROL}/{name}, wanted one")
    pod = found[0]["spec"]["template"]
    containers = pod["spec"]["containers"]
    if len(containers) != 1:
        refuse(f"{name} declares {len(containers)} containers, wanted one")
    return pod, containers[0]


def literal(container, name, owner):
    found = [entry for entry in container.get("env") or [] if entry["name"] == name]
    if len(found) != 1:
        refuse(f"{owner} declares {name} {len(found)} times, wanted once")
    value = found[0].get("value")
    if not isinstance(value, str):
        refuse(f"{owner} takes {name} from somewhere other than a literal, so this cannot read it")
    return value


def chars(text):
    """A string's length as JavaScript counts it, which is in UTF-16 units."""
    return len(text.encode("utf-16-le")) // 2


def roster_of(text):
    """The roster's entries, or the reason chuggy refuses it."""
    try:
        entries = json.loads(text)
    except ValueError as error:
        refuse(f"{ROSTER} is not JSON: {error}")
    if not isinstance(entries, list) or len(entries) > HELD_MAX:
        refuse(f"{ROSTER} is not a list of at most {HELD_MAX} held credentials")
    keys = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            refuse(f"{ROSTER} holds an entry that is not exactly {sorted(ENTRY_FIELDS)}: {entry!r}")
        for field, chars_max in CHARS_MAX.items():
            value = entry[field]
            if not isinstance(value, str) or not value or chars(value) > chars_max:
                refuse(f"{ROSTER} holds an entry whose {field} is {value!r}, which is not a string of 1 to {chars_max}")
        variable = entry["variable"]
        if not VARIABLE.fullmatch(variable) or variable.startswith(VARIABLE_RESERVED):
            refuse(
                f"{ROSTER} names {variable}, which is not a variable ending _FILE outside "
                f"{', '.join(VARIABLE_RESERVED)}"
            )
        key = (entry["tenant"], entry["project"], entry["credential"])
        if key in keys:
            refuse(f"{ROSTER} holds {key[2]} for {key[0]}/{key[1]} twice")
        keys.add(key)
    return entries


def the_file(pod, container, path):
    """The Secret and the key the plane's container has at `path`, held to what
    makes it a file the plane reads and the kubelet keeps."""
    if not path.startswith("/"):
        refuse(f"{ROSTER} names {path!r}, which is not an absolute path")
    # The path itself as well as a directory over it, since a subPath mounts one
    # file at exactly the path it is read from.
    mounts = [
        mount
        for mount in container.get("volumeMounts") or []
        if path == mount["mountPath"].rstrip("/")
        or path.startswith(mount["mountPath"].rstrip("/") + "/")
    ]
    if len(mounts) != 1:
        refuse(f"{len(mounts)} of {PLANE}'s volume mounts stand over {path}, wanted one")
    (mount,) = mounts
    if "subPath" in mount or "subPathExpr" in mount:
        refuse(
            f"{PLANE} mounts {mount['mountPath']} by a subPath, which the kubelet does not "
            "bring up to date, so a rotated Secret is never served"
        )
    volumes = [volume for volume in pod["spec"].get("volumes") or [] if volume["name"] == mount["name"]]
    if len(volumes) != 1:
        refuse(f"{PLANE} mounts {mount['name']}, which its pod declares {len(volumes)} times")
    secret = volumes[0].get("secret")
    if secret is None:
        refuse(f"{PLANE} reads {path} from the volume {mount['name']}, which is not a Secret")
    rest = path[len(mount["mountPath"].rstrip("/")) + 1:]
    # A volume that names no key holds every key, each under its own name.
    items = secret.get("items", [{"key": rest, "path": rest}] if "/" not in rest else [])
    found = [item for item in items if item["path"] == rest]
    if len(found) != 1:
        refuse(f"{PLANE} is told to read {path}, and {len(found)} keys of {secret['secretName']} are put there")
    (item,) = found
    mode = item.get("mode", secret.get("defaultMode", DEFAULT_MODE))
    of_the_pod = pod["spec"].get("securityContext") or {}
    user = (container.get("securityContext") or {}).get("runAsUser", of_the_pod.get("runAsUser"))
    if not (mode & 0o004 or ("fsGroup" in of_the_pod and mode & 0o040) or user == 0):
        refuse(
            f"{PLANE} is given {path} with the mode {mode:04o}, which its user {user} does not "
            "read, so the plane does not start"
        )
    return secret["secretName"], item["key"]


def granted(documents):
    """Every credential a grant of the scheduler's attempt arms names."""
    _, container = deployment(documents, SCHEDULER)
    try:
        policy = json.loads(literal(container, EXECUTION_POLICY, SCHEDULER))
    except ValueError as error:
        refuse(f"{EXECUTION_POLICY} is not JSON: {error}")
    return {
        credential
        for arm in ARMS
        for credential in ((policy.get(arm) or {}).get("grant") or {}).get("credentials") or []
    }


def main():
    if len(sys.argv) != 2:
        refuse("usage: held-credentials.py RENDERED")
    documents = objects(sys.argv[1])
    pod, container = deployment(documents, PLANE)
    held = {}
    for entry in roster_of(literal(container, ROSTER, PLANE)):
        secret, key = the_file(pod, container, entry["file"])
        held[(entry["tenant"], entry["project"], entry["credential"])] = (entry["variable"], secret, key)

    for identity in sorted(held.keys() | HELD.keys()):
        tenant, project, credential = identity
        if identity not in HELD:
            refuse(f"{ROSTER} holds {credential} for {tenant}/{project}, which HELD does not name")
        if identity not in held:
            refuse(f"HELD names {credential} for {tenant}/{project}, which {ROSTER} does not hold")
        if held[identity] != HELD[identity]:
            refuse(
                f"{ROSTER} holds {credential} for {tenant}/{project} as {held[identity][0]} from "
                f"{held[identity][1]}/{held[identity][2]}, and HELD names {HELD[identity][0]} from "
                f"{HELD[identity][1]}/{HELD[identity][2]}"
            )

    arms = granted(documents)
    for tenant, project, credential in sorted(held):
        if credential not in arms:
            refuse(
                f"{ROSTER} holds {credential} for {tenant}/{project}, and neither of "
                f"{SCHEDULER}'s {' and '.join(ARMS)} arms grants it, so it is served to no attempt"
            )


main()
