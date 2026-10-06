#!/usr/bin/env python3
"""Refuse a tree in which a report of an action would be answered 404, or the
API would not start, with nothing here saying why.

usage: action-reporters.py RENDERED_CLUSTER RENDERED_BUILD_SYSTEM GENERATE SYNC

A report is proved by a secret that two pods read, each from a file its own
manifest puts there out of a Secret the host makes. Every link of that is a
name written in two places, and a broken one is quiet: chuggy answers an
unproved report as it answers an address it does not serve, and a release
that reported nothing is a release. So each link is resolved here, over what
`kubectl kustomize` renders and over the two scripts the host's secrets
module builds.

THE ROSTER IS READ AS CHUGGY READS IT, because the API does not start on one
it refuses, and the pod it would have replaced keeps serving while the layer
waits. `CHUG_API_ACTION_REPORTERS` is JSON: a list, bounded, of objects with
exactly `reporter`, `scheme`, `secretFile`, `tenant`, `project` and `actions`.
The four texts are non-empty, bounded, and hold no NUL and no half of a
surrogate pair. A scheme is `BearerSecret` or `FluxSignature`. An action is
ASCII letters and digits, with `.`, `_` and `-` only between them, bounded,
and a reporter's are a bounded list. A `FluxSignature` reporter is named for
one action, since a signed event carries no action's name. No action of a
project is named twice. And the file of a `FluxSignature` reporter is no
other reporter's, since whoever holds a key can sign with it.

A `secretFile` IS A FILE ITS POD HAS, OF A SECRET THE HOST MAKES. It is where
one mount of that container puts one key of a Secret volume, exactly. The
mount is read-only and not by a `subPath`, which is a copy the kubelet never
brings up to date. The volume is optional: a required one whose Secret is not
there yet holds the pod, and with it the layer. Its file is one the pod's user
reads, who owns no file of a Secret volume. And the Secret and the key are
ones the host generates and synchronises into that pod's namespace, read out
of the built `chuggy-secrets-generate` and `chuggy-secrets-sync` rather than
restated, so a name changed in modules/chuggy-secrets.nix is a name changed
here.

WHO PRESENTS A BEARER READS THE SECRET ITS REPORTER IS VERIFIED BY. The file
the release pipeline's `report` step is told to read is held as a
`secretFile` is, to the Task's own namespace. One reporter of the roster is
verified by that Secret and that key, by `BearerSecret`, for the tenant and
the project the step posts to.

WHAT A RUN REPORTS IS WHAT ITS REPORTER MAY, AND WHERE THE API ANSWERS. The
actions the step is told of are exactly that reporter's: one the roster lacks
is a 404 at every run, and one the run lacks is an action nothing reports.
Each is a task of the pipeline, since a task's name is what its action is
reported under. The address is `https`, the path is where chuggy answers a
project's actions, and an Ingress sends that path at that host to the pod
that reads the roster.
"""

import json
import re
import shlex
import sys
import urllib.parse
from pathlib import Path

import yaml

ROSTER = "CHUG_API_ACTION_REPORTERS"
PIPELINE = "chuggy-release"
REPORT = "report"
# What tells the `report` step where its bearer is.
BEARER = "BEARER"

# chuggy's rules for a roster.
ENTRY_FIELDS = {"reporter", "scheme", "secretFile", "tenant", "project", "actions"}
SCHEMES = ("BearerSecret", "FluxSignature")
REPORTERS_MAX = 64
ACTIONS_MAX = 100
CHARS_MAX = {"reporter": 128, "secretFile": 4_096, "tenant": 256, "project": 256}
ACTION = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
ACTION_CHARS_MAX = 128
# Where chuggy answers a project's actions. A report is posted to
# `/<action>/reports` below it.
ACTIONS_OF = re.compile(r"/api/v1/tenants/([^/]+)/projects/([^/]+)/actions")

STATUS_LINE = re.compile(r"(\S+) \$\(tasks\.(\S+)\.status\)")
# The lines of the host's two scripts that name a Secret: one key generated,
# a namespace's block opened, and one Secret synchronised with its keys.
ENSURE = re.compile(r'ensure "[^"]*/([^/"]+)/([^/"]+)" "[^"]+"')
PRESENT = re.compile(r"\s*if present (.+); then")
SYNC_SECRET = re.compile(r"\s*sync_secret (.+)")
# What a Secret volume's files are when it names no mode.
DEFAULT_MODE = 0o644


def refuse(message):
    raise SystemExit(f"action-reporters: {message}")


def objects(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def pod_of(document):
    """The pod an object runs, or nothing."""
    spec = document.get("spec") or {}
    if document["kind"] == "CronJob":
        spec = spec["jobTemplate"]["spec"]
    template = spec.get("template")
    return template if isinstance(template, dict) and "spec" in template else None


def bounded_text(value, chars_max):
    if not isinstance(value, str) or not value or "\0" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return len(value) <= chars_max


def roster_of(text):
    """The roster, or the reason chuggy refuses it."""
    try:
        entries = json.loads(text)
    except ValueError as error:
        refuse(f"{ROSTER} is not JSON: {error}")
    if not isinstance(entries, list) or len(entries) > REPORTERS_MAX:
        refuse(f"{ROSTER} is not a list of at most {REPORTERS_MAX} reporters")
    reported = set()
    keyed = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            refuse(f"{ROSTER} holds an entry that is not exactly {sorted(ENTRY_FIELDS)}: {entry!r}")
        for field, chars_max in CHARS_MAX.items():
            if not bounded_text(entry[field], chars_max):
                refuse(f"{ROSTER} holds an entry whose {field} is {entry[field]!r}, which is not bounded text")
        name = entry["reporter"]
        if entry["scheme"] not in SCHEMES:
            refuse(f"{ROSTER} gives the reporter {name} the scheme {entry['scheme']!r}, and chuggy verifies by {SCHEMES}")
        actions = entry["actions"]
        if not isinstance(actions, list) or len(actions) > ACTIONS_MAX:
            refuse(f"{ROSTER} does not name the reporter {name} for a list of at most {ACTIONS_MAX} actions")
        for action in actions:
            if not isinstance(action, str) or len(action) > ACTION_CHARS_MAX or not ACTION.fullmatch(action):
                refuse(f"{ROSTER} names the reporter {name} for {action!r}, which is not an action's name")
            identity = (entry["tenant"], entry["project"], action)
            if identity in reported:
                refuse(f"{ROSTER} names the action {action} of {entry['tenant']}/{entry['project']} twice")
            reported.add(identity)
        if entry["scheme"] == "FluxSignature" and len(actions) != 1:
            refuse(f"{ROSTER} names the FluxSignature reporter {name} for other than one action")
        sharing = keyed.setdefault(entry["secretFile"], entry)
        if sharing is not entry and "FluxSignature" in (sharing["scheme"], entry["scheme"]):
            refuse(f"{ROSTER} names one secret file for the reporters {sharing['reporter']} and {name}, and one of them signs with it")
    return entries


def the_file(subject, pod, container, path):
    """The Secret and the key a container has at `path`, held to what makes it
    a file the container can read and the kubelet keeps."""
    volumes = {volume["name"]: volume for volume in pod["spec"].get("volumes") or []}
    found = []
    for mount in container.get("volumeMounts") or []:
        secret = (volumes.get(mount["name"]) or {}).get("secret")
        if secret is None:
            continue
        directory = mount["mountPath"].rstrip("/")
        if "subPath" in mount or "subPathExpr" in mount:
            if path == directory:
                refuse(f"{subject} is given {path} by a subPath, which the kubelet does not bring up to date")
            continue
        if not path.startswith(directory + "/"):
            continue
        rest = path[len(directory) + 1:]
        # A volume that names no key holds every key, each under its own name.
        items = secret.get("items", [{"key": rest, "path": rest}] if "/" not in rest else [])
        found.extend((secret, item, mount) for item in items if item["path"] == rest)
    if len(found) != 1:
        refuse(f"{subject} is told to read {path}, and {len(found)} keys of the Secrets it mounts are put there")
    ((secret, item, mount),) = found
    name = secret["secretName"]
    if mount.get("readOnly") is not True:
        refuse(f"{subject} mounts the Secret {name} writable at {mount['mountPath']}")
    if secret.get("optional") is not True:
        refuse(f"{subject} requires the Secret {name}, and a pod is not started without one it requires")
    mode = item.get("mode", secret.get("defaultMode", DEFAULT_MODE))
    of_the_pod = pod["spec"].get("securityContext") or {}
    user = (container.get("securityContext") or {}).get("runAsUser", of_the_pod.get("runAsUser"))
    if not (mode & 0o004 or ("fsGroup" in of_the_pod and mode & 0o040) or user == 0):
        refuse(f"{subject} is given {path} with the mode {mode:04o}, which its user {user} does not read")
    return name, item["key"]


def made_by_the_host(generate, sync):
    """What the built scripts say: each Secret and key generated, and each
    synchronised, by namespace."""
    generated = set(ENSURE.findall(Path(generate).read_text()))
    synchronised = {}
    namespace = None
    for line in Path(sync).read_text().splitlines():
        present, call = PRESENT.fullmatch(line), SYNC_SECRET.fullmatch(line)
        if present:
            (namespace,) = shlex.split(present.group(1))
        elif line.strip() == "fi":
            namespace = None
        elif call and namespace is not None:
            secret, *keys = shlex.split(call.group(1))
            synchronised.setdefault(namespace, {})[secret] = set(keys)
    if not generated or not synchronised:
        refuse("the host's scripts name no Secret this can read, so what they make is not known")
    return generated, synchronised


def is_made(subject, made, namespace, secret, key):
    generated, synchronised = made
    if (secret, key) not in generated:
        refuse(f"{subject} reads the key {key} of the Secret {secret}, which the host does not generate")
    if key not in synchronised.get(namespace, {}).get(secret, set()):
        refuse(f"{subject} reads the key {key} of the Secret {secret}, which the host does not synchronise into {namespace}")


def the_api(cluster):
    """The one container that is given the roster, with the object and the pod
    it is of."""
    found = []
    for document in cluster:
        pod = pod_of(document)
        if pod is None:
            continue
        for container in [*pod["spec"].get("initContainers", []), *pod["spec"]["containers"]]:
            for entry in container.get("env") or []:
                if entry["name"] == ROSTER:
                    found.append((document, pod, container, entry))
    if len(found) != 1:
        refuse(f"{len(found)} containers are given {ROSTER}, and one API reads it")
    document, pod, container, entry = found[0]
    if not isinstance(entry.get("value"), str):
        refuse(f"{ROSTER} is not a value written in the manifest, so this cannot read it")
    return document, pod, container, entry["value"]


def the_report(build):
    """What the pipeline's `report` task is: the pipeline's tasks, the
    parameters it passes, and the Task and its one step."""
    pipelines = [d for d in build if d["kind"] == "Pipeline" and d["metadata"]["name"] == PIPELINE]
    if len(pipelines) != 1:
        refuse(f"the build system renders {len(pipelines)} Pipeline {PIPELINE}")
    spec = pipelines[0]["spec"]
    entries = [entry for entry in spec.get("finally") or [] if entry["name"] == REPORT]
    if len(entries) != 1:
        refuse(f"Pipeline {PIPELINE} has {len(entries)} `finally` task {REPORT}")
    tasks = [
        d
        for d in build
        if d["kind"] == "Task"
        and d["metadata"]["name"] == entries[0]["taskRef"]["name"]
        and d["metadata"].get("namespace") == pipelines[0]["metadata"].get("namespace")
    ]
    if len(tasks) != 1 or len(tasks[0]["spec"]["steps"]) != 1:
        refuse(f"`{REPORT}` is not of one rendered Task of one step")
    passed = {param["name"]: param["value"] for param in entries[0]["params"]}
    return [task["name"] for task in spec["tasks"]], passed, tasks[0]


def reaches(cluster, document, pod, host, path):
    """Whether an Ingress sends `path` at `host` to a Service of this pod."""
    namespace = document["metadata"]["namespace"]
    labels = pod["metadata"].get("labels") or {}
    services = {
        d["metadata"]["name"]
        for d in cluster
        if d["kind"] == "Service"
        and d["metadata"].get("namespace") == namespace
        and (d["spec"].get("selector") or None) is not None
        and d["spec"]["selector"].items() <= labels.items()
    }
    sent = []
    for ingress in cluster:
        if ingress["kind"] != "Ingress" or ingress["metadata"].get("namespace") != namespace:
            continue
        for rule in ingress["spec"].get("rules") or []:
            if rule.get("host") != host:
                continue
            for route in rule["http"]["paths"]:
                prefix = route["path"].rstrip("/")
                if route.get("pathType") == "Prefix" and (path == prefix or path.startswith(prefix + "/")):
                    sent.append((len(prefix), route["backend"]["service"]["name"]))
    return bool(sent) and max(sent)[1] in services


def main():
    if len(sys.argv) != 5:
        refuse("usage: action-reporters.py RENDERED_CLUSTER RENDERED_BUILD_SYSTEM GENERATE SYNC")
    cluster, build = objects(sys.argv[1]), objects(sys.argv[2])
    made = made_by_the_host(sys.argv[3], sys.argv[4])

    document, pod, container, text = the_api(cluster)
    api = f"{document['kind']} {document['metadata']['name']} container {container['name']}"
    namespace = document["metadata"]["namespace"]
    verified_by = {}
    for entry in roster_of(text):
        secret, key = the_file(f"{api}, for the reporter {entry['reporter']},", pod, container, entry["secretFile"])
        is_made(f"{api}, for the reporter {entry['reporter']},", made, namespace, secret, key)
        verified_by[entry["reporter"]] = (entry, secret, key)

    tasks, passed, task = the_report(build)
    (step,) = task["spec"]["steps"]
    step_name = f"Task {task['metadata']['name']} step {step['name']}"
    told = [entry.get("value") for entry in step.get("env") or [] if entry["name"] == BEARER]
    if len(told) != 1 or not isinstance(told[0], str):
        refuse(f"{step_name} is not told where its bearer is by one {BEARER} written in the manifest")
    presented = the_file(step_name, {"spec": task["spec"]}, step, told[0])
    is_made(step_name, made, task["metadata"]["namespace"], *presented)

    address = urllib.parse.urlsplit(passed["actions"])
    if address.scheme != "https" or address.port is not None or address.query or address.fragment:
        refuse(f"`{REPORT}` posts under {passed['actions']}, which is not a plain https address")
    route = ACTIONS_OF.fullmatch(address.path)
    if not route:
        refuse(f"`{REPORT}` posts under {passed['actions']}, which is not where chuggy answers a project's actions")
    if not reaches(cluster, document, pod, address.hostname, address.path):
        refuse(f"`{REPORT}` posts under {passed['actions']}, which no Ingress sends to {api}")
    under = route.groups()

    reporters = [
        entry
        for entry, secret, key in verified_by.values()
        if (secret, key) == presented
        and entry["scheme"] == "BearerSecret"
        and (entry["tenant"], entry["project"]) == under
    ]
    if len(reporters) != 1:
        refuse(
            f"{len(reporters)} BearerSecret reporters of {'/'.join(under)} are verified by the key {presented[1]} of the Secret "
            f"{presented[0]}, which is what `{REPORT}` presents"
        )
    lines = [STATUS_LINE.fullmatch(line) for line in passed["statuses"].splitlines()]
    if not all(lines):
        refuse(f"`{REPORT}` is told {passed['statuses']!r}, which is not an action and a task's status a line")
    actions = [line.group(1) for line in lines]
    if sorted(actions) != sorted(reporters[0]["actions"]):
        refuse(f"`{REPORT}` reports {sorted(actions)}, and the reporter {reporters[0]['reporter']} is named for {sorted(reporters[0]['actions'])}")
    for action in actions:
        if action not in tasks:
            refuse(f"`{REPORT}` reports {action}, which is no task of Pipeline {PIPELINE}")


main()
