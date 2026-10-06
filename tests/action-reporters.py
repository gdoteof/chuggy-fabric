#!/usr/bin/env python3
"""Refuse a tree in which a report of an action would be answered 404, or the
API would not start, with nothing here saying why.

usage: action-reporters.py RENDERED RENDERED_BUILD_SYSTEM GENERATE SYNC LAYERS INSTALL

A report is proved by a secret that two pods read, each from a file its own
manifest puts there out of a Secret the host makes. Every link of that is a
name written in two places, and a broken one is quiet: chuggy answers an
unproved report as it answers an address it does not serve, and a release
that reported nothing is a release. So each link is resolved here, over what
`kubectl kustomize` renders of the cluster's directories and of the root's
layers, over the Flux install the host applies, and over the two scripts the
host's secrets module builds.

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

WHO SIGNS AN EVENT SIGNS WITH THE KEY ITS REPORTER IS VERIFIED BY. Flux's
notification-controller keys its digest with the `token` of the Secret a
Provider names, read in the Provider's own namespace. One `generic-hmac`
Provider is rendered. One `FluxSignature` reporter is verified by that key of
that Secret, in that namespace, and the address is where chuggy answers a
report of that reporter's one action, with nothing after it: a slash there is
answered as a request with no bearer is. The Provider says nothing else,
since `suspend` and a proxy are each a report that is never sent.

THE ADDRESS IS A SERVICE OF THE API, ON A ROAD BOTH ENDS ADMIT. It is plain
http to the cluster-local name of a Service that selects the pod that reads
the roster. The port of that pod the Service sends it to is one the policies
on the API admit notification-controller's pod to, by its namespace and its
labels as the install writes them, and admit no other pod of the install to.
And no policy on that pod keeps it from the API's. A policy is matched
against a pod and not a Service, so the port held is the container's. A peer
named by address, or a namespace selected by a label that is not its name, is
refused and not read.

ONLY WHAT A ROLLOUT CAME TO IS A REPORT, AND ONLY FLUX SAYS OF WHICH COMMIT.
An Alert to the Provider selects one layer the root renders, by one severity
and by nothing else, since `suspend` and a list of messages each drop events
without a word. One Alert is at `info`, and its layer's success is the
action's. That layer reads an OCIRepository, the one kind of source whose
events carry the `originRevision` chuggy reads the commit from, and it waits,
or its success says applied and not rolled out. Every other layer that reads
the same source is selected at `error` by one Alert, and is one the first
depends on: selected at `info` it would report a release rolled out while the
last layer was failing, and selected by nothing its failure is reported by
nobody. No Alert adds `revision` or `originRevision` to an event, and no
layer selected carries either as an `event.toolkit.fluxcd.io/` annotation:
Flux writes both into an event wherever the controller has not, and chuggy
believes them there. A `link` is one chuggy keeps, since it drops one it
refuses and says nothing; where the link opens is tests/release-dashboard.py's.

AND `apps` APPLIES THEM. A release applies its own objects last of all, so
one that failed before then would be reported by an Alert that is not there.

AND THE CONTROLLER READS ACROSS NAMESPACES. The Provider is where its Secret
is and a layer is where Flux is, so notification-controller has to read an
Alert outside its own namespace and give it the events of another. Each is an
argument of the install's. Told to watch its own namespace alone it drops
every event these select, and all it says is a line of its log that no Alert
matched.
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
REPORTS_OF = re.compile(ACTIONS_OF.pattern + r"/([^/]+)/reports")
# chuggy's rule for a link, less what only its own URL parser refuses.
LINK_VISIBLE = re.compile(r"[!-~]+")
LINK_WRITTEN = re.compile(r"https://[^/\\?#@]+(?:[/?#]|$)")
LINK_CHARS_MAX = 2_048

# Flux's notification API, and the type of Provider that signs what it posts.
NOTIFICATION = "notification.toolkit.fluxcd.io/"
SIGNING = "generic-hmac"
# The key of a Provider's Secret that notification-controller signs with.
SIGNING_KEY = "token"
# The Deployment of the install whose pod posts an event.
NOTIFIER = "notification-controller"
# The rendered directory that is no part of a release.
STANDING = "apps"
# What of an event's metadata is Flux's alone to say, and the prefix under
# which an object's annotations are written into its events.
OF_FLUX = ("revision", "originRevision")
OF_THE_OBJECT = "event.toolkit.fluxcd.io/"
LAYER = "kustomize.toolkit.fluxcd.io/"
SOURCE_WITH_AN_ORIGIN = "OCIRepository"
# The arguments notification-controller reads across namespaces by: what each
# has to be, which is what it is where the install does not give it, and what
# the controller does otherwise.
ACROSS_NAMESPACES = {
    "watch-all-namespaces": ("true", "reads no Alert outside its own namespace"),
    "no-cross-namespace-refs": ("false", "gives an Alert no event of another namespace"),
}
CLUSTER_SUFFIX = ".svc.cluster.local"
NAMESPACE_NAME = "kubernetes.io/metadata.name"

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


def selects(selector, labels):
    """Whether a label selector selects these labels."""
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions") or []:
        key, values = expression["key"], expression.get("values") or []
        held = {
            "In": labels.get(key) in values,
            "NotIn": labels.get(key) not in values,
            "Exists": key in labels,
            "DoesNotExist": key not in labels,
        }
        if not held[expression["operator"]]:
            return False
    return True


def peer_selects(policy, peer, pod):
    """Whether one peer of a policy's rule is this pod, given as its namespace
    and its labels."""
    name = f"NetworkPolicy {policy['metadata']['name']}"
    if "ipBlock" in peer:
        refuse(f"{name} names a peer by address, which this cannot resolve to a pod")
    namespace, labels = pod
    spaces = peer.get("namespaceSelector")
    if spaces is None:
        if namespace != policy["metadata"]["namespace"]:
            return False
    else:
        read = {*(spaces.get("matchLabels") or {}), *(e["key"] for e in spaces.get("matchExpressions") or [])}
        if read - {NAMESPACE_NAME}:
            refuse(f"{name} selects a namespace by {sorted(read - {NAMESPACE_NAME})}, which this does not read")
        if not selects(spaces, {NAMESPACE_NAME: namespace}):
            return False
    return selects(peer.get("podSelector") or {}, labels)


def port_admitted(rule, port):
    """Whether a rule covers a TCP port of the pod a connection ends at, given
    as its number and its name."""
    number, name = port
    if not rule.get("ports"):
        return True
    for entry in rule["ports"]:
        if entry.get("protocol", "TCP") != "TCP":
            continue
        value = entry.get("port")
        if value is None or value == name:
            return True
        if isinstance(value, int) and value <= number <= entry.get("endPort", value):
            return True
    return False


def admitted(documents, direction, pod, other, port):
    """Whether the policies selecting `pod` let it accept a connection from
    `other` on a port of its own (`Ingress`), or open one to a port of
    `other` (`Egress`). A pod no policy selects in a direction is open in it."""
    rules, peers = ("ingress", "from") if direction == "Ingress" else ("egress", "to")
    namespace, labels = pod
    selecting = [
        d
        for d in documents
        if d["kind"] == "NetworkPolicy"
        and d["metadata"].get("namespace") == namespace
        and direction in (d["spec"].get("policyTypes") or ["Ingress", *(["Egress"] if "egress" in d["spec"] else [])])
        and selects(d["spec"].get("podSelector") or {}, labels)
    ]
    if not selecting:
        return True
    for policy in selecting:
        for rule in policy["spec"].get(rules) or []:
            if not port_admitted(rule, port):
                continue
            if not rule.get(peers) or any(peer_selects(policy, peer, other) for peer in rule[peers]):
                return True
    return False


def the_port(cluster, subject, address, namespace, pod, container):
    """The port of the API's container that an address of one of its Services
    reaches, as its number and its name."""
    host = address.hostname or ""
    names = host[: -len(CLUSTER_SUFFIX)].split(".") if host.endswith(CLUSTER_SUFFIX) else []
    services = [
        d
        for d in cluster
        if d["kind"] == "Service" and [d["metadata"]["name"], d["metadata"].get("namespace")] == names
    ]
    if len(services) != 1:
        refuse(f"{subject} posts to {host}, which is the cluster-local name of {len(services)} rendered Services")
    selector = services[0]["spec"].get("selector") or {}
    if names[1] != namespace or not selector or not selector.items() <= (pod["metadata"].get("labels") or {}).items():
        refuse(f"{subject} posts to the Service {host}, which does not select the pod that reads {ROSTER}")
    served = address.port or 80
    for entry in services[0]["spec"]["ports"]:
        if entry["port"] != served or entry.get("protocol", "TCP") != "TCP":
            continue
        target = entry.get("targetPort", entry["port"])
        for port in container.get("ports") or []:
            if target in (port["containerPort"], port.get("name")):
                return port["containerPort"], port.get("name")
    refuse(f"{subject} posts to port {served} of the Service {host}, which sends it to no port of the container that reads {ROSTER}")


def notifying(document, kind):
    return document["kind"] == kind and document.get("apiVersion", "").startswith(NOTIFICATION)


def the_signer(cluster, verified, namespace):
    """The one Provider that signs what it posts, the reporter it signs as,
    and its address."""
    providers = [d for d in cluster if notifying(d, "Provider") and d["spec"].get("type") == SIGNING]
    if len(providers) != 1:
        refuse(f"{len(providers)} {SIGNING} Providers are rendered, and one signs what Flux reports")
    provider = providers[0]
    name, spec = f"Provider {provider['metadata']['name']}", provider["spec"]
    if set(spec) != {"type", "address", "secretRef"} or set(spec["secretRef"]) != {"name"}:
        refuse(f"{name} is not exactly a type, an address and a Secret's name, and this reads nothing else of one")
    if provider["metadata"].get("namespace") != namespace:
        refuse(f"{name} reads its Secret in {provider['metadata'].get('namespace')}, and the API reads the roster's in {namespace}")
    signed_with = (spec["secretRef"]["name"], SIGNING_KEY)
    reporters = [
        entry
        for entry, secret, key in verified
        if entry["scheme"] == "FluxSignature" and (secret, key) == signed_with
    ]
    if len(reporters) != 1:
        refuse(
            f"{len(reporters)} FluxSignature reporters are verified by the key {SIGNING_KEY} of the Secret "
            f"{signed_with[0]}, which is what {name} signs with"
        )
    address = urllib.parse.urlsplit(spec["address"])
    if address.scheme != "http" or address.username or address.password or address.query or address.fragment:
        refuse(f"{name} posts to {spec['address']}, which is not a plain http address")
    route = REPORTS_OF.fullmatch(address.path)
    if not route:
        refuse(f"{name} posts to {spec['address']}, which is not where chuggy answers a report")
    reporter = reporters[0]
    if route.groups() != (reporter["tenant"], reporter["project"], reporter["actions"][0]):
        refuse(
            f"{name} reports {'/'.join(route.groups())}, and the reporter {reporter['reporter']} is named for "
            f"{reporter['tenant']}/{reporter['project']}/{reporter['actions'][0]}"
        )
    return provider, name, address


def the_road(cluster, install, name, address, api, document, pod, container):
    """Hold the Provider's address to a port of the API that the pod posting
    to it is admitted to, alone of the install's."""
    namespace = document["metadata"]["namespace"]
    port = the_port(cluster, name, address, namespace, pod, container)
    reader = (namespace, pod["metadata"].get("labels") or {})
    controllers = {
        d["metadata"]["name"]: (d["metadata"].get("namespace"), pod_of(d)["metadata"].get("labels") or {})
        for d in install
        if d["kind"] == "Deployment" and pod_of(d)
    }
    if NOTIFIER not in controllers:
        refuse(f"the install has no Deployment {NOTIFIER}, so who posts an event is not known")
    policies = [*install, *cluster]
    if not admitted(policies, "Egress", controllers[NOTIFIER], reader, port):
        refuse(f"a policy on the pod of {NOTIFIER} keeps it from port {port[0]} of {api}, where {name} posts")
    for controller, poster in controllers.items():
        reaches_it = admitted(policies, "Ingress", reader, poster, port)
        if controller == NOTIFIER and not reaches_it:
            refuse(f"no policy admits the pod of {NOTIFIER} to port {port[0]} of {api}, where {name} posts")
        if controller != NOTIFIER and reaches_it:
            refuse(f"{api} admits the pod of {controller} on port {port[0]}, and it reports nothing")


def layer_of(layers, alert):
    """The one layer of the root an Alert selects, held to everything an Alert
    may say."""
    name, spec = f"Alert {alert['metadata']['name']}", alert["spec"]
    sources = spec.get("eventSources")
    if (
        set(spec) - {"providerRef", "eventSeverity", "eventSources", "eventMetadata"}
        or set(spec["providerRef"]) != {"name"}
        or not isinstance(sources, list)
        or len(sources) != 1
        or set(sources[0]) - {"kind", "name", "namespace"}
    ):
        refuse(f"{name} is not exactly a Provider's name, a severity, one source by its name and metadata, and this reads nothing else of one")
    source = sources[0]
    space = source.get("namespace", alert["metadata"].get("namespace"))
    selected = [
        d
        for d in layers
        if d["kind"] == source.get("kind") == "Kustomization"
        and d.get("apiVersion", "").startswith(LAYER)
        and (d["metadata"]["name"], d["metadata"].get("namespace")) == (source.get("name"), space)
    ]
    if len(selected) != 1:
        refuse(f"{name} selects {source.get('kind')} {space}/{source.get('name')}, which is {len(selected)} layers of the root")
    added = spec.get("eventMetadata") or {}
    carried = selected[0]["metadata"].get("annotations") or {}
    for key in OF_FLUX:
        if key in added:
            refuse(f"{name} adds {key} to an event, and chuggy reads that as Flux's own word")
        if OF_THE_OBJECT + key in carried:
            refuse(f"the layer {source['name']} carries {OF_THE_OBJECT}{key}, and chuggy reads that as Flux's own word")
    link = added.get("link")
    if "link" in added and not (
        isinstance(link, str) and len(link) <= LINK_CHARS_MAX and LINK_VISIBLE.fullmatch(link) and LINK_WRITTEN.match(link)
    ):
        refuse(f"{name} adds the link {link!r}, which chuggy drops from its report")
    return selected[0]


def source_of(layer):
    reference = layer["spec"]["sourceRef"]
    return reference["kind"], reference["name"], reference.get("namespace", layer["metadata"].get("namespace"))


def waits_on(layers, layer, seen=()):
    """The names of the layers a layer depends on, through any number of them."""
    names = set()
    space = layer["metadata"].get("namespace")
    for dependency in layer["spec"].get("dependsOn") or []:
        name = dependency["name"]
        if name in seen or dependency.get("namespace", space) != space:
            continue
        names.add(name)
        for other in layers:
            if other["kind"] == "Kustomization" and (other["metadata"]["name"], other["metadata"].get("namespace")) == (name, space):
                names |= waits_on(layers, other, (*seen, name))
    return names


def the_rollout(layers, provider, name, cluster, standing):
    """Hold the Alerts to the Provider to one layer whose success is the
    action's and to every other layer of the same release, at its failure."""
    alerts = [
        d
        for d in cluster
        if notifying(d, "Alert")
        and d["metadata"].get("namespace") == provider["metadata"]["namespace"]
        and (d["spec"].get("providerRef") or {}).get("name") == provider["metadata"]["name"]
    ]
    for applied in [provider, *alerts]:
        if applied not in standing:
            refuse(f"{applied['kind']} {applied['metadata']['name']} is applied by a release, and one that fails before it applies it is reported by nothing")
    selected = {"info": [], "error": []}
    for alert in alerts:
        severity = alert["spec"].get("eventSeverity", "info")
        if severity not in selected:
            refuse(f"Alert {alert['metadata']['name']} selects by the severity {severity!r}, and Flux sends by info or by error")
        selected[severity].append(layer_of(layers, alert))
    if len(selected["info"]) != 1:
        refuse(f"{len(selected['info'])} Alerts to {name} are at info, and one layer's success is the action's")
    (last,) = selected["info"]
    reported = last["metadata"]["name"]
    if source_of(last)[0] != SOURCE_WITH_AN_ORIGIN:
        refuse(f"the layer {reported} reads a {source_of(last)[0]}, whose events carry no originRevision for chuggy to read a commit from")
    if last["spec"].get("wait") is not True:
        refuse(f"the layer {reported} does not wait, so its success says applied and not rolled out")
    before = sorted(
        d["metadata"]["name"]
        for d in layers
        if d["kind"] == "Kustomization" and d is not last and d.get("apiVersion", "").startswith(LAYER) and source_of(d) == source_of(last)
    )
    failing = sorted(d["metadata"]["name"] for d in selected["error"])
    if failing != before:
        refuse(f"the Alerts to {name} select {failing} at error, and the other layers that read what {reported} reads are {before}")
    unwaited = sorted(set(before) - waits_on(layers, last))
    if unwaited:
        refuse(f"the layer {reported} is selected at info and does not depend on {unwaited}, so its success is not theirs")


def reads_across(install):
    """Hold the install's notification-controller to reading an Alert outside
    its own namespace, and to giving one the events of another."""
    (controller,) = [d for d in install if d["kind"] == "Deployment" and d["metadata"]["name"] == NOTIFIER]
    told = {}
    for container in pod_of(controller)["spec"]["containers"]:
        for argument in container.get("args") or []:
            flag, _, value = argument.lstrip("-").partition("=")
            told[flag] = value or "true"
    for flag, (needed, otherwise) in ACROSS_NAMESPACES.items():
        if told.get(flag, needed) != needed:
            refuse(f"the install tells {NOTIFIER} --{flag}={told[flag]}, and it then {otherwise}")


def main():
    if len(sys.argv) != 7:
        refuse("usage: action-reporters.py RENDERED RENDERED_BUILD_SYSTEM GENERATE SYNC LAYERS INSTALL")
    cluster, build = objects(Path(sys.argv[1]) / "cluster.yaml"), objects(sys.argv[2])
    standing = objects(Path(sys.argv[1]) / f"{STANDING}.yaml")
    made = made_by_the_host(sys.argv[3], sys.argv[4])
    layers, install = objects(sys.argv[5]), objects(sys.argv[6])

    document, pod, container, text = the_api(cluster)
    api = f"{document['kind']} {document['metadata']['name']} container {container['name']}"
    namespace = document["metadata"]["namespace"]
    verified = []
    for entry in roster_of(text):
        secret, key = the_file(f"{api}, for the reporter {entry['reporter']},", pod, container, entry["secretFile"])
        is_made(f"{api}, for the reporter {entry['reporter']},", made, namespace, secret, key)
        verified.append((entry, secret, key))

    provider, name, posted = the_signer(cluster, verified, namespace)
    the_road(cluster, install, name, posted, api, document, pod, container)
    the_rollout(layers, provider, name, cluster, standing)
    reads_across(install)

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
        for entry, secret, key in verified
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
