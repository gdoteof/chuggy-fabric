#!/usr/bin/env python3
"""Refuse a rendered cluster whose agreement plane does not verify a token as
the API does, does not reach its database as the one role it is given, can be
reached by anything but Traefik or reach anything but its three arms, is not
what the console's host sends its prefix to, or records an agreement's address
without the header that carries the person's.

THE ISSUER, THE AUDIENCE AND THE ALGORITHMS ARE COPIES OF THE API'S, and each
is held to the original as the string it is, as tests/access-plane.py holds
that plane's and for the reason its header gives: the console reads this plane
with the token it reads the API with, so a plane holding a token to another
issuer, audience or algorithm refuses what the API accepts, and the console
signs out whoever is refused twice.

ITS DATABASE IS HELD FROM THE URL OUTWARDS, as tests/access-plane.py holds that
plane's: the URL signs in as `chuggy_agreement_plane_login`, sets
`chuggy_agreement_plane` and nothing else, and names PostgreSQL's Service and a
port that lands on one its server declares; the password in it is one key of
`chuggy-postgres-credentials`, defined above it in the same container, and no
container of the pod is handed another key of any Secret; the pod carries the
client label and `postgres-admits-labelled-clients` admits it on that port; and
an egress arm reaches that server there.

AND A ROLLOUT LEAVES THE OLD POD SERVING: the default strategy, and readiness a
probe of `/health/ready`, the path that answers who the connection runs as. The
`chuggy` layer waits on this Deployment, so a pod that read ready without its
role would be reported rolled.

ITS PORT ADMITS TRAEFIK, AND NO OTHER SOURCE. Policies add, so every one that
isolates the pod for ingress is read, and what they admit together is Traefik
on the port the plane's Service lands on and no other. Its egress is folded the
same way, and is the resolver, PostgreSQL's server and public HTTPS less the
ranges chuggy-api-egress excepts, exactly.

THE CONSOLE'S HOST SENDS THE PREFIX TO IT. On the host whose `/` is the
console's, the one arm under `/agreements/v1` is that prefix, and names the
plane's Service and a port that Service declares. A console told to ask this
plane and answered by anything else lets nobody past, so a port mistyped there
is everyone locked out, and the Ingress and the Service each read correctly
alone.

THE CLIENT ADDRESS HEADER IS NAMED, as a literal. Unset, every agreement records
the socket's peer, which is Traefik, and nothing else would say so.

WHAT THIS GATE CANNOT READ IT REFUSES rather than passes, in the shapes
tests/access-plane.py lists, and an Ingress arm whose backend is not a Service
by name and port.

WHAT IT DOES NOT HOLD is that the originals are right, that either role exists,
that the login is a member of the group, or that the key holds the password
PostgreSQL accepts: those are chuggy-api.yaml's, the roles file's and the
migration's. Nor that Traefik's pods carry the label they are named by, which
is k3s's, or that the header named is the one that carries the person's
address, which is the tunnel's: no render shows either.
"""

import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import yaml

CONTROL = "chuggy"

# (deployment, container)
API = ("chuggy-api", "api")
PLANE = ("chuggy-agreement-plane", "agreement-plane")

# (what a token is held to, the API's variable, the plane's copy of it)
HELD = (
    ("issuer", "CHUG_API_OIDC_ISSUER", "CHUG_AGREEMENT_PLANE_OIDC_ISSUER"),
    ("audience", "CHUG_API_OIDC_AUDIENCE", "CHUG_AGREEMENT_PLANE_OIDC_AUDIENCE"),
    ("list of algorithms", "CHUG_API_OIDC_ALGORITHMS", "CHUG_AGREEMENT_PLANE_OIDC_ALGORITHMS"),
)

# How a value names another variable, which the kubelet replaces with that
# variable's value where the container defines it.
REFERENCE = "$("

DATABASE_URL = "CHUG_AGREEMENT_PLANE_DATABASE_URL"
PASSWORD = "CHUG_AGREEMENT_PLANE_PASSWORD"
LOGIN_ROLE = "chuggy_agreement_plane_login"
GROUP_ROLE = "chuggy_agreement_plane"
DATABASE = "chuggy"

# (Secret, key): what modules/chuggy-secrets.nix generates for that login role.
CREDENTIAL = ("chuggy-postgres-credentials", "agreement-plane-password")

POSTGRES_SERVICE = "postgres"
POSTGRES_POLICY = "postgres-admits-labelled-clients"
POSTGRES_CLIENT = ("chuggy.dev/postgres-client", "true")

PLANE_SERVICE = "chuggy-agreement-plane"
INGRESS_POLICY = "chuggy-agreement-plane-ingress"
EGRESS_POLICY = "chuggy-agreement-plane-egress"

# The one source the plane's port admits.
TRAEFIK = "app.kubernetes.io/name=traefik in kube-system"

# The ranges the public arm excepts, which chuggy-api-egress argues.
PRIVATE = (
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
)

# Where the plane's pod goes beside PostgreSQL's server: the resolver, and
# public HTTPS for its issuer's discovery document and key set.
BESIDE = {
    ("k8s-app=kube-dns in kube-system", "UDP", 53),
    ("k8s-app=kube-dns in kube-system", "TCP", 53),
    ("0.0.0.0/0 except " + ", ".join(sorted(PRIVATE)), "TCP", 443),
}

READY = "/health/ready"

# The console's Service, whose `/` names the host the console is served on, and
# the prefix the plane serves a browser under there.
CONSOLE = "chuggy-ui"
PREFIX = "/agreements/v1"

CLIENT_ADDRESS_HEADER = "CHUG_AGREEMENT_PLANE_CLIENT_ADDRESS_HEADER"

CLUSTER_SUFFIX = ".svc.cluster.local"

# The label a namespace is named by, which is the only namespaceSelector this
# gate resolves: the API server sets it, so it names one namespace.
NAMESPACE_LABEL = "kubernetes.io/metadata.name"

WORKLOADS = ("Pod", "Deployment", "ReplicaSet", "StatefulSet", "DaemonSet", "Job", "CronJob")

PEERS = {"egress": "to", "ingress": "from"}


def refuse(message):
    raise SystemExit(f"agreement plane: {message}")


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


def container(documents, workload):
    """One container of one Deployment in the control namespace."""
    deployment, box = workload
    boxes = [
        entry
        for entry in one(documents, "Deployment", deployment, CONTROL)["spec"]["template"]["spec"].get(
            "containers"
        )
        or []
        if entry["name"] == box
    ]
    if len(boxes) != 1:
        refuse(f"{deployment} has {len(boxes)} containers named {box}")
    return boxes[0]


def literal(env, workload, variable):
    """One variable's value, where the manifest states it and nothing else does."""
    entries = [item for item in env if item.get("name") == variable]
    if len(entries) != 1:
        refuse(f"{workload[0]} names {variable} {len(entries)} times, and this gate reads one")
    value = entries[0].get("value")
    if "valueFrom" in entries[0] or not isinstance(value, str) or not value:
        refuse(
            f"{workload[0]} does not give {variable} as a literal value, so what its "
            "process reads is not something this gate read"
        )
    if REFERENCE in value:
        refuse(
            f"{workload[0]} gives {variable} as {value!r}, which names another variable: "
            "the kubelet writes that one's value over it, and this gate reads the manifest"
        )
    return value


def selects(selector, labels, described):
    """Whether a selector matches one object's labels. Only the two shapes this
    tree uses are evaluated, and an empty selector is every pod in its
    namespace."""
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
    if document["kind"] == "Pod":
        return document["metadata"].get("labels") or {}
    spec = document["spec"]
    if document["kind"] == "CronJob":
        spec = spec["jobTemplate"]["spec"]
    return spec["template"]["metadata"].get("labels") or {}


def written(labels):
    return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))


def secrets_handed(pod):
    """Every Secret key the pod's containers are handed, as (container,
    variable, Secret, key), and a refusal where one arrives in a way this gate
    does not read a key from."""
    found = []
    for entry in (pod.get("initContainers") or []) + (pod.get("containers") or []):
        if entry.get("envFrom"):
            refuse(
                f"the {entry['name']} container takes variables with envFrom, which hands "
                "it every key of what it names, and this gate reads one key at a time"
            )
        for item in entry.get("env") or []:
            reference = (item.get("valueFrom") or {}).get("secretKeyRef")
            if reference is not None:
                if reference.get("optional"):
                    refuse(
                        f"{item['name']} is optional, so where its key is absent the pod "
                        "starts with the variable unset and whatever names it reads as "
                        "the text it was written as"
                    )
                found.append(
                    (entry["name"], item["name"], reference.get("name"), reference.get("key"))
                )
    for volume in pod.get("volumes") or []:
        if "secret" in volume or "projected" in volume:
            refuse(
                f"the plane's pod mounts the volume {volume['name']!r}, which is a Secret "
                "or may project one, and its database password is the one it has a use for"
            )
    return found


def database_url(env):
    """The plane's URL held to its two roles and to PostgreSQL's Service, and
    the port it names there."""
    entries = [item for item in env if item.get("name") == DATABASE_URL]
    if len(entries) != 1:
        refuse(f"{PLANE[0]} names {DATABASE_URL} {len(entries)} times, and this gate reads one")
    value = entries[0].get("value")
    if "valueFrom" in entries[0] or not isinstance(value, str) or not value:
        refuse(
            f"{PLANE[0]} does not give {DATABASE_URL} as a literal value, so which role "
            "it connects as is not something this gate read"
        )
    # Nothing below prints the URL whole: a password typed into it where the
    # reference belongs would be printed with it.
    parts = urlsplit(value)
    if parts.scheme != "postgres":
        refuse(f"{DATABASE_URL} is a {parts.scheme!r} URL and not a postgres one")
    if parts.username != LOGIN_ROLE:
        refuse(
            f"{DATABASE_URL} signs in as {parts.username!r} and not as {LOGIN_ROLE}: "
            "that is another service's login, and what its password opens is not the "
            "plane's to hold"
        )
    if parts.password != f"{REFERENCE}{PASSWORD})":
        refuse(
            f"{DATABASE_URL} does not take its password from {REFERENCE}{PASSWORD}), "
            "which is the one variable this gate holds to a Secret key"
        )
    parameters = parse_qsl(parts.query, keep_blank_values=True)
    named = sorted(name for name, _ in parameters)
    if named != ["options"] or parts.fragment:
        refuse(
            f"{DATABASE_URL} carries the parameters {named}"
            f"{' and a fragment' if parts.fragment else ''} and not `options` once and "
            "alone, which is where the connection's one role is set"
        )
    if parameters[0][1] != f"-c role={GROUP_ROLE}":
        refuse(
            f"{DATABASE_URL} sets {parameters[0][1]!r} and not '-c role={GROUP_ROLE}': the "
            f"connection runs as {GROUP_ROLE} and no other role, and with any other "
            "`current_user` the plane is never ready"
        )
    if parts.path != f"/{DATABASE}":
        refuse(f"{DATABASE_URL} names the database {parts.path!r} and not /{DATABASE}")
    host = (parts.hostname or "").rstrip(".")
    if host != f"{POSTGRES_SERVICE}.{CONTROL}{CLUSTER_SUFFIX}":
        refuse(
            f"{DATABASE_URL} names the host {host!r}, which is not the Service "
            f"{POSTGRES_SERVICE} in `{CONTROL}`"
        )
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None:
        refuse(f"{DATABASE_URL} names no port this gate can read")
    return port


def landing(documents, port):
    """Where a connection to PostgreSQL's Service on `port` lands: the labels
    its selector names, and the port on the pod so labelled. A headless
    Service translates nothing, which tests/access-plane.py argues."""
    service = one(documents, "Service", POSTGRES_SERVICE, CONTROL)
    chosen = service["spec"].get("selector") or {}
    servers = [
        document
        for document in documents
        if document.get("kind") in WORKLOADS
        and document["metadata"].get("namespace") == CONTROL
        and chosen
        and all(pod_labels(document).get(key) == value for key, value in chosen.items())
    ]
    if len(servers) != 1:
        refuse(
            f"Service {POSTGRES_SERVICE} selects {len(servers)} workloads in `{CONTROL}`, "
            "and this gate resolves the one that answers it"
        )
    declared = [
        entry
        for box in servers[0]["spec"]["template"]["spec"]["containers"]
        for entry in box.get("ports") or []
    ]
    listening = sorted({entry["containerPort"] for entry in declared})
    if service["spec"].get("clusterIP") == "None":
        if port not in listening:
            refuse(
                f"{DATABASE_URL} names port {port}, and Service {POSTGRES_SERVICE} is "
                f"headless, so the connection lands on {port}, where the server's "
                f"containers declare {listening}"
            )
        return chosen, port
    published = service["spec"].get("ports") or []
    if len(published) != 1 or published[0]["port"] != port:
        refuse(
            f"{DATABASE_URL} reaches port {port}, and Service {POSTGRES_SERVICE} does not "
            "publish that one port alone"
        )
    target = published[0].get("targetPort", published[0]["port"])
    if not isinstance(target, int):
        numbers = {entry["containerPort"] for entry in declared if entry.get("name") == target}
        if len(numbers) != 1:
            refuse(
                f"Service {POSTGRES_SERVICE} targets the named port {target!r}, which its "
                f"pod publishes {len(numbers)} numbers for"
            )
        target = numbers.pop()
    if target not in listening:
        refuse(
            f"Service {POSTGRES_SERVICE} lands port {port} on {target}, where the server's "
            f"containers declare {listening}"
        )
    return chosen, target


def isolating(documents, labels, direction):
    """Every policy in the control namespace that isolates a pod so labelled in
    one direction. `policyTypes` is authoritative when present; absent, the API
    server reads every policy as one for Ingress, and as one for Egress where it
    carries an `egress` section."""
    found = []
    for document in documents:
        if document.get("kind") != "NetworkPolicy" or document["metadata"].get("namespace") != CONTROL:
            continue
        types = document["spec"].get("policyTypes")
        if types is None:
            isolates = direction == "ingress" or "egress" in document["spec"]
        else:
            isolates = direction.capitalize() in types
        name = document["metadata"]["name"]
        if isolates and selects(document["spec"].get("podSelector") or {}, labels, name):
            found.append(document)
    return found


def whom(peer, policy, way):
    """One peer in words: the pods it selects and the namespace they are in, or
    an address block and what it excepts."""
    if set(peer) == {"ipBlock"} and set(peer["ipBlock"]) <= {"cidr", "except"}:
        block = peer["ipBlock"]
        excepted = sorted(block.get("except") or [])
        return block["cidr"] + (" except " + ", ".join(excepted) if excepted else "")
    namespace = CONTROL
    if "namespaceSelector" in peer:
        named = peer["namespaceSelector"] or {}
        chosen = named.get("matchLabels") or {}
        if set(named) != {"matchLabels"} or set(chosen) != {NAMESPACE_LABEL}:
            refuse(
                f"an {way} peer on {policy} names namespaces by something other than "
                f"{NAMESPACE_LABEL} alone, and this gate cannot say which it names"
            )
        namespace = chosen[NAMESPACE_LABEL]
    selector = peer.get("podSelector")
    if (
        set(peer) - {"namespaceSelector", "podSelector"}
        or not selector
        or set(selector) != {"matchLabels"}
        or not selector["matchLabels"]
    ):
        refuse(
            f"an {way} peer on {policy} is neither an address block nor pods named by "
            "their labels, and this gate cannot say what it names: a peer naming no "
            "label is every pod in its namespace"
        )
    return f"{written(selector['matchLabels'])} in {namespace}"


def reach(policy, way):
    """Everything one policy admits in one direction, as (who, protocol, port)."""
    name = policy["metadata"]["name"]
    found = set()
    for arm in policy["spec"].get(way) or []:
        peers = arm.get(PEERS[way]) or []
        ports = arm.get("ports") or []
        if not peers or not ports:
            refuse(
                f"an {way} arm on {name} names no peer or no port, so it admits every "
                "one of whichever it leaves out"
            )
        for port in ports:
            number = port.get("port")
            if "endPort" in port or isinstance(number, bool) or not isinstance(number, int):
                refuse(
                    f"an {way} arm on {name} names the port {number!r} or a range from "
                    "it, and this gate reads one number at a time"
                )
            for peer in peers:
                found.add((whom(peer, name, way), port.get("protocol", "TCP"), number))
    return found


def spoken(triples):
    return "; ".join(f"{who} on {protocol} {port}" for who, protocol, port in sorted(triples))


def folded(documents, labels, direction, named):
    """What every policy isolating the plane's pod in one direction admits
    together, once the one named for it is among them."""
    policies = isolating(documents, labels, direction)
    if named not in [document["metadata"]["name"] for document in policies]:
        refuse(
            f"{named} does not isolate the plane's pod for {direction}: its policyTypes "
            f"leave {direction.capitalize()} out or its podSelector selects another pod, "
            "so what it names bounds nothing here"
        )
    admitted = set()
    for document in policies:
        admitted |= reach(document, direction)
    return admitted


def surges(bound):
    """Whether a rolling update's `maxSurge` starts a pod beside the old one.
    The controller rounds a percentage of the replicas up, so every percentage
    above nought is a pod. What is neither a number of pods nor a percentage is
    not read as one."""
    if isinstance(bound, bool):
        return False
    if isinstance(bound, int):
        return bound > 0
    if isinstance(bound, str) and re.fullmatch(r"[0-9]+%", bound):
        return int(bound[:-1]) > 0
    return False


def database(documents, plane, env):
    """The URL, the password, the Secret keys and the server's admission, and
    where the connection lands."""
    pod = plane["spec"]["template"]["spec"]
    labels = plane["spec"]["template"]["metadata"].get("labels") or {}

    # The URL, and no second one beside it.
    port = database_url(env)
    for entry in (pod.get("initContainers") or []) + (pod.get("containers") or []):
        for item in entry.get("env") or []:
            value = item.get("value")
            if (
                item["name"] != DATABASE_URL
                and isinstance(value, str)
                and ("postgres://" in value or "postgresql://" in value)
            ):
                refuse(
                    f"{item['name']} names a database too: the plane has one connection, "
                    f"{DATABASE_URL}, and this gate holds that one to its roles"
                )

    # The password, defined above the URL in the URL's own container, and the
    # one Secret key the pod is handed.
    names = [item["name"] for item in env]
    if names.count(PASSWORD) != 1 or names.index(PASSWORD) > names.index(DATABASE_URL):
        refuse(
            f"{PASSWORD} is not defined once and above {DATABASE_URL}, so the kubelet "
            "leaves the reference to it in the URL as the text it is written as"
        )
    given = env[names.index(PASSWORD)]
    source = given.get("valueFrom") or {}
    reference = source.get("secretKeyRef") or {}
    if (
        "value" in given
        or set(source) != {"secretKeyRef"}
        or (reference.get("name"), reference.get("key")) != CREDENTIAL
    ):
        refuse(
            f"{PASSWORD} is not the key {CREDENTIAL[1]} of the Secret {CREDENTIAL[0]}, "
            "which is the password the host generates for the plane's login role"
        )
    wanted = (PLANE[1], PASSWORD, *CREDENTIAL)
    others = sorted(
        f"{secret}/{key} as {name} in the {box} container"
        for box, name, secret, key in secrets_handed(pod)
        if (box, name, secret, key) != wanted
    )
    if others:
        refuse(
            f"the plane's pod is also handed {', '.join(others)}: its database password, "
            f"in the {PLANE[1]} container, is the one Secret key it has a use for"
        )

    # The server's end admits a pod so labelled on the port the URL lands on.
    key, value = POSTGRES_CLIENT
    if labels.get(key) != value:
        refuse(
            f"the plane's pod does not carry {key}={value}, so {POSTGRES_POLICY} refuses "
            "it the database and the plane is never ready"
        )
    chosen, landed = landing(documents, port)
    admission = one(documents, "NetworkPolicy", POSTGRES_POLICY, CONTROL)
    admitted = any(
        any(
            entry.get("port") == landed and entry.get("protocol", "TCP") == "TCP"
            for entry in element.get("ports") or []
        )
        and any(
            set(peer) == {"podSelector"}
            and selects(peer["podSelector"] or {}, labels, POSTGRES_POLICY)
            for peer in element.get("from") or []
        )
        for element in admission["spec"].get("ingress") or []
    )
    if not admitted:
        refuse(
            f"{POSTGRES_POLICY} admits no pod of `{CONTROL}` labelled {written(labels)} on "
            f"TCP {landed}, which is where {DATABASE_URL} lands"
        )
    return (f"{written(chosen)} in {CONTROL}", "TCP", landed)


def egress(documents, labels, server):
    """The resolver, PostgreSQL's server and public HTTPS, exactly."""
    reached = folded(documents, labels, "egress", EGRESS_POLICY)
    if server not in reached:
        refuse(
            f"no egress arm reaches {spoken({server})}, which is where {DATABASE_URL} "
            "lands, so the plane's pod is refused its database and is never ready"
        )
    expected = BESIDE | {server}
    wider, lost = reached - expected, expected - reached
    if wider:
        refuse(
            f"the plane's pod may also reach {spoken(wider)}: the resolver, PostgreSQL's "
            "server and public HTTPS are the whole of where it goes"
        )
    if lost:
        refuse(
            f"the plane's pod does not reach {spoken(lost)}: it resolves its issuer's name "
            "and discovers it over public HTTPS before it listens, and exits where it cannot"
        )


def rollout(documents, plane):
    """The default strategy, and readiness the path that asks the database."""
    strategy = plane["spec"].get("strategy") or {}
    rolling = strategy.get("rollingUpdate") or {}
    surge = rolling.get("maxSurge")
    if (
        strategy.get("type", "RollingUpdate") != "RollingUpdate"
        or rolling.get("maxUnavailable") not in (None, 0)
        or (surge is not None and not surges(surge))
    ):
        refuse(
            f"{PLANE[0]} is rolled by {strategy!r}, which may remove the old pod before "
            "the new one is ready: a plane that cannot reach its database yet would then "
            "serve nothing, where the default strategy leaves the old pod serving"
        )
    probe = container(documents, PLANE).get("readinessProbe") or {}
    if (probe.get("httpGet") or {}).get("path") != READY:
        refuse(
            f"the {PLANE[1]} container's readiness is not a probe of {READY}, the path "
            "that asks the database who the plane is connected as: a plane that cannot "
            "sign in would then be a ready pod, and the `chuggy` layer would report it rolled"
        )


def served(documents, labels):
    """The plane's Service, its one port, and the port on the pod it lands on."""
    service = one(documents, "Service", PLANE_SERVICE, CONTROL)
    chosen = service["spec"].get("selector") or {}
    if not chosen or any(labels.get(key) != value for key, value in chosen.items()):
        refuse(
            f"Service {PLANE_SERVICE} selects {written(chosen)!r}, which the plane's pod "
            "does not carry, so the port it lands on is not one this gate can read"
        )
    published = service["spec"].get("ports") or []
    if len(published) != 1 or published[0].get("protocol", "TCP") != "TCP":
        refuse(f"Service {PLANE_SERVICE} does not publish one TCP port, and this gate resolves one")
    target = published[0].get("targetPort", published[0]["port"])
    if not isinstance(target, int):
        numbers = {
            entry["containerPort"]
            for entry in container(documents, PLANE).get("ports") or []
            if entry.get("name") == target
        }
        if len(numbers) != 1:
            refuse(
                f"Service {PLANE_SERVICE} targets the named port {target!r}, which the "
                f"{PLANE[1]} container publishes {len(numbers)} numbers for"
            )
        target = numbers.pop()
    return published[0], target


def ingress(documents, labels, port):
    """Traefik on the port the plane's Service lands on, and nothing else."""
    admitted = folded(documents, labels, "ingress", INGRESS_POLICY)
    wanted = (TRAEFIK, "TCP", port)
    if admitted != {wanted}:
        refuse(
            f"the plane's pod admits {spoken(admitted) or 'nothing'}: its probes take no "
            f"token, and {spoken({wanted})}, where Service {PLANE_SERVICE} lands, is the "
            "whole of who reaches it"
        )


def routed(documents, published):
    """The one arm under the plane's prefix on the console's host, naming the
    plane's Service and a port that Service declares."""
    rules = [
        (ingress, rule)
        for ingress in documents
        if ingress.get("kind") == "Ingress"
        for rule in (ingress.get("spec") or {}).get("rules") or []
    ]

    def arms(rule):
        return (rule.get("http") or {}).get("paths") or []

    def backend(arm):
        sent = arm.get("backend") or {}
        if set(sent) != {"service"} or set(sent["service"]) != {"name", "port"}:
            refuse(
                f"an Ingress arm for {arm.get('path')!r} has the backend {sent!r}, which is "
                "not a Service named by its name and a port, and this gate reads one"
            )
        return sent["service"]

    hosts = {
        rule.get("host")
        for ingress, rule in rules
        if ingress["metadata"].get("namespace") == CONTROL
        for arm in arms(rule)
        if arm.get("path") == "/" and backend(arm)["name"] == CONSOLE
    }
    if len(hosts) != 1 or None in hosts:
        refuse(
            f"the hosts {sorted(map(str, hosts))} send `/` to Service {CONSOLE}, and this "
            "gate reads the plane's arm on the one host the console is served on"
        )
    host = hosts.pop()

    found = [
        (ingress, arm)
        for ingress, rule in rules
        if rule.get("host") == host
        for arm in arms(rule)
        if str(arm.get("path", "")).startswith(PREFIX)
    ]
    if len(found) != 1:
        refuse(
            f"{host} has {len(found)} arms under {PREFIX}, and the console asks the plane "
            "there: with none it is answered by its own index and lets nobody past, and "
            "of two or more this gate cannot say which Traefik sends each route to"
        )
    ingress, arm = found[0]
    described = f"Ingress {ingress['metadata'].get('namespace')}/{ingress['metadata']['name']}"
    if arm.get("path") != PREFIX or arm.get("pathType") != "Prefix":
        refuse(
            f"{described} sends {arm.get('path')!r} as {arm.get('pathType')!r} on {host}, "
            f"and not {PREFIX} as a Prefix, so the plane's routes under it fall to the console"
        )
    service = backend(arm)
    if ingress["metadata"].get("namespace") != CONTROL or service["name"] != PLANE_SERVICE:
        refuse(
            f"{described} sends {PREFIX} on {host} to Service {service['name']!r} and not to "
            f"{PLANE_SERVICE} in `{CONTROL}`: the console asks the plane there, and answered "
            "by anything else it lets nobody past"
        )
    port = service["port"] or {}
    if set(port) == {"number"}:
        declared = port["number"] == published["port"]
    elif set(port) == {"name"}:
        declared = port["name"] == published.get("name")
    else:
        refuse(f"{described} names the port {port!r} of {PLANE_SERVICE}, which this gate does not read")
    if not declared:
        refuse(
            f"{described} sends {PREFIX} on {host} to port {port!r} of Service {PLANE_SERVICE}, "
            f"which declares {published['port']} named {published.get('name')!r}: Traefik has "
            "nowhere to send it, and the console lets nobody past"
        )


def client_address(env):
    """The header an agreement's address is taken from, named as a literal."""
    if not any(item.get("name") == CLIENT_ADDRESS_HEADER for item in env):
        refuse(
            f"{PLANE[0]} does not name {CLIENT_ADDRESS_HEADER}, so every agreement records "
            "the socket's peer, which is Traefik, and nothing else would say so"
        )
    literal(env, PLANE, CLIENT_ADDRESS_HEADER)


def main():
    if len(sys.argv) != 2:
        refuse("usage: agreement-plane.py RENDERED_MANIFEST")
    documents = [
        document for document in yaml.safe_load_all(Path(sys.argv[1]).read_text()) if document
    ]
    api = container(documents, API).get("env") or []
    env = container(documents, PLANE).get("env") or []

    for held, original, copy in HELD:
        wanted = literal(api, API, original)
        given = literal(env, PLANE, copy)
        if given != wanted:
            refuse(
                f"{copy} is {given!r} and {original} is {wanted!r}: the plane holds a "
                f"token to another {held} than the API does, so it refuses a token the API "
                "accepts and the console signs that person out"
            )

    plane = one(documents, "Deployment", PLANE[0], CONTROL)
    labels = plane["spec"]["template"]["metadata"].get("labels") or {}
    server = database(documents, plane, env)
    egress(documents, labels, server)
    rollout(documents, plane)
    published, port = served(documents, labels)
    ingress(documents, labels, port)
    routed(documents, published)
    client_address(env)


if __name__ == "__main__":
    main()
