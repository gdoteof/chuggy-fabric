#!/usr/bin/env python3
"""Refuse a rendered cluster whose metrics plane does not reach its database as
the one role it is given, labels owners under another issuer than the API's,
is scraped other than once and inside its own read bound, or can be reached by
anything but Prometheus.

ITS DATABASE IS HELD FROM THE URL OUTWARDS, as tests/access-plane.py holds the
access plane's and for the reasons its header gives: the URL signs in as
`chuggy_metrics_plane_login`, sets `chuggy_metrics_plane` and nothing else, and
lands on a port PostgreSQL's server declares; the password in it is one key of
`chuggy-postgres-credentials`, defined above it in the same container, and no
container of the pod is handed another key of any Secret; the pod carries the
client label `postgres-admits-labelled-clients` admits; and the readiness probe
asks `/health/ready`, the path that answers who the connection runs as.

THE ISSUER IS A COPY OF THE API'S. The plane cuts it off stored principals to
make an `owner` label, so a copy that differs labels every owner empty, and
every file still reads correctly. It is held to chuggy-api.yaml's as the string
it is.

ONE SCRAPE, AND IT ENDS AT THE PLANE. Exactly one ServiceMonitor selects the
plane's Service, carries the label this Prometheus selects monitors by, and
scrapes one endpoint: the Service's port, by its name, at `/metrics`, with an
interval and a timeout both written. A timeout above the interval is a monitor
the operator rejects, so nothing scrapes the plane. Its read timeout is written
too, and below that timeout, so a slow read is answered 503 by the plane rather
than cut off by Prometheus; chuggy-metrics-plane.yaml says why that matters.

ITS PORT ADMITS PROMETHEUS, AND NO OTHER SOURCE. Every path the plane serves
takes no token and `/metrics` costs the database a full aggregate, so every
policy that isolates the pod for ingress is read, and what they admit together
is that one source on the port the plane's Service lands on and no other. Its
egress is folded the same way and is the resolver and PostgreSQL's server,
exactly. And nothing publishes it: its Service is a cluster address, no Ingress
in `chuggy` routes to it, and no Traefik object names it.

WHAT THIS GATE CANNOT READ IT REFUSES rather than passes, in the shapes
tests/access-plane.py lists, and a duration or a timeout it cannot parse.

WHAT IT DOES NOT HOLD is that the Prometheus pod carries the label the
ingress policy names: that label is the operator's, and no render shows it.
Nor that either role exists, that the login is a member of the group, that the
key holds the password PostgreSQL accepts, or that a release's chuggy commit
carries the plane's root: those are the roles file's, the migration's and the
release's, on the rig.
"""

import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import yaml

CONTROL = "chuggy"

# (deployment, container)
API = ("chuggy-api", "api")
PLANE = ("chuggy-metrics-plane", "metrics-plane")

# The API's issuer and the plane's copy of it.
ISSUER = ("CHUG_API_OIDC_ISSUER", "CHUG_METRICS_PLANE_OIDC_ISSUER")

# How a value names another variable, which the kubelet replaces with that
# variable's value where the container defines it.
REFERENCE = "$("

DATABASE_URL = "CHUG_METRICS_PLANE_DATABASE_URL"
PASSWORD = "CHUG_METRICS_PLANE_PASSWORD"
LOGIN_ROLE = "chuggy_metrics_plane_login"
GROUP_ROLE = "chuggy_metrics_plane"
DATABASE = "chuggy"

# (Secret, key): what modules/chuggy-secrets.nix generates for that login role.
CREDENTIAL = ("chuggy-postgres-credentials", "metrics-plane-password")

POSTGRES_SERVICE = "postgres"
POSTGRES_POLICY = "postgres-admits-labelled-clients"
POSTGRES_CLIENT = ("chuggy.dev/postgres-client", "true")

PLANE_SERVICE = "chuggy-metrics-plane"
INGRESS_POLICY = "chuggy-metrics-plane-ingress"
EGRESS_POLICY = "chuggy-metrics-plane-egress"

# The one source the plane's port admits.
PROMETHEUS = "app.kubernetes.io/name=prometheus in monitoring"

# The resolver, which the egress reaches beside PostgreSQL.
RESOLVER = {
    ("k8s-app=kube-dns in kube-system", "UDP", 53),
    ("k8s-app=kube-dns in kube-system", "TCP", 53),
}

# The plane's read bound, in milliseconds; the process refuses a value that is
# not a positive whole number.
READ_TIMEOUT = "CHUG_METRICS_PLANE_READ_TIMEOUT_MS"

# The label this Prometheus selects monitors by, and the path the plane serves.
RELEASE = ("release", "kube-prometheus-stack")
METRICS = "/metrics"

READY = "/health/ready"

CLUSTER_SUFFIX = ".svc.cluster.local"

# The label a namespace is named by, which is the only namespaceSelector this
# gate resolves: the API server sets it, so it names one namespace.
NAMESPACE_LABEL = "kubernetes.io/metadata.name"

WORKLOADS = ("Pod", "Deployment", "ReplicaSet", "StatefulSet", "DaemonSet", "Job", "CronJob")

PEERS = {"egress": "to", "ingress": "from"}

# A Prometheus duration, unit by unit in the order it is written.
DURATION = re.compile(
    r"(?:(\d+)y)?(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+)s)?(?:(\d+)ms)?"
)
DURATION_MS = (365 * 86_400_000, 7 * 86_400_000, 86_400_000, 3_600_000, 60_000, 1_000, 1)


def refuse(message):
    raise SystemExit(f"metrics plane: {message}")


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
    value = url_value(env)
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


def url_value(env):
    """The URL as the manifest states it, the one value here a reference is expected in."""
    entries = [item for item in env if item.get("name") == DATABASE_URL]
    if len(entries) != 1:
        refuse(f"{PLANE[0]} names {DATABASE_URL} {len(entries)} times, and this gate reads one")
    value = entries[0].get("value")
    if "valueFrom" in entries[0] or not isinstance(value, str) or not value:
        refuse(
            f"{PLANE[0]} does not give {DATABASE_URL} as a literal value, so which role "
            "it connects as is not something this gate read"
        )
    return value


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


def milliseconds(duration, described):
    match = DURATION.fullmatch(duration) if isinstance(duration, str) and duration else None
    if not match or not any(match.groups()):
        refuse(f"{described} is {duration!r}, which is not a duration this gate reads")
    return sum(int(count) * unit for count, unit in zip(match.groups(), DURATION_MS) if count)


def database(documents, plane):
    pod = plane["spec"]["template"]["spec"]
    labels = plane["spec"]["template"]["metadata"].get("labels") or {}
    env = container(documents, PLANE).get("env") or []

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

    # And this end: the resolver and that server, exactly.
    reached = folded(documents, labels, "egress", EGRESS_POLICY)
    expected = RESOLVER | {(f"{written(chosen)} in {CONTROL}", "TCP", landed)}
    if reached != expected:
        wider, lost = reached - expected, expected - reached
        refuse(
            "the plane's pod "
            + "; and ".join(
                part
                for part in (
                    f"may also reach {spoken(wider)}" if wider else "",
                    f"does not reach {spoken(lost)}" if lost else "",
                )
                if part
            )
            + ": the resolver and PostgreSQL's server are the whole of where it goes"
        )

    # "Never ready" is the answer of the path that asks who it connected as.
    probe = container(documents, PLANE).get("readinessProbe") or {}
    if (probe.get("httpGet") or {}).get("path") != READY:
        refuse(
            f"the {PLANE[1]} container's readiness is not a probe of {READY}: a plane "
            "that cannot sign in as its role would be a ready pod"
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
    if service["spec"].get("type", "ClusterIP") != "ClusterIP":
        refuse(
            f"Service {PLANE_SERVICE} is of type {service['spec']['type']}, which publishes "
            "the plane beyond the pod network, and nothing outside the cluster reads it"
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
    return service, published[0], target


def ingress(documents, labels, port):
    """Prometheus on the port the plane's Service lands on, and nothing else."""
    admitted = folded(documents, labels, "ingress", INGRESS_POLICY)
    wanted = (PROMETHEUS, "TCP", port)
    if admitted != {wanted}:
        refuse(
            f"the plane's pod admits {spoken(admitted) or 'nothing'}: its paths take no "
            f"token, and {spoken({wanted})}, where Service {PLANE_SERVICE} lands, is the "
            "whole of who reaches them"
        )


def unpublished(documents):
    """No Ingress in the control namespace routes to the plane's Service, and no
    Traefik object anywhere names it."""
    for document in documents:
        kind, metadata = document.get("kind"), document["metadata"]
        described = f"{kind} {metadata.get('namespace')}/{metadata['name']}"
        if kind == "Ingress" and metadata.get("namespace") == CONTROL:
            spec = document.get("spec") or {}
            backends = [spec.get("defaultBackend") or {}] + [
                path.get("backend") or {}
                for rule in spec.get("rules") or []
                for path in (rule.get("http") or {}).get("paths") or []
            ]
            if any((backend.get("service") or {}).get("name") == PLANE_SERVICE for backend in backends):
                refuse(f"{described} routes to Service {PLANE_SERVICE}, and nothing outside the cluster reads it")
        if str(document.get("apiVersion", "")).startswith("traefik.") and PLANE_SERVICE in yaml.safe_dump(
            document.get("spec")
        ):
            refuse(f"{described} names {PLANE_SERVICE}, and nothing outside the cluster reads it")


def scraped(documents, service, published, plane_env):
    """The one monitor, its one endpoint, and the plane's read bound inside it."""
    labels = service["metadata"].get("labels") or {}
    monitors = []
    for document in documents:
        if document.get("kind") != "ServiceMonitor":
            continue
        spec = document["spec"]
        within = spec.get("namespaceSelector") or {}
        if within.get("any"):
            namespaces = None
        else:
            namespaces = within.get("matchNames") or [document["metadata"].get("namespace")]
        if namespaces is not None and CONTROL not in namespaces:
            continue
        name = f"ServiceMonitor {document['metadata'].get('namespace')}/{document['metadata']['name']}"
        # An empty selector is every Service in those namespaces.
        if not selects(spec.get("selector") or {}, labels, name):
            continue
        monitors.append((name, document))
    if len(monitors) != 1:
        refuse(
            f"{len(monitors)} ServiceMonitors select Service {PLANE_SERVICE}: one scrape is "
            "what its interval is argued for, and with none the plane is never read"
        )
    name, monitor = monitors[0]
    key, value = RELEASE
    if (monitor["metadata"].get("labels") or {}).get(key) != value:
        refuse(f"{name} lacks the label {key}={value}, so Prometheus does not select it")

    endpoints = monitor["spec"].get("endpoints") or []
    if len(endpoints) != 1:
        refuse(f"{name} has {len(endpoints)} endpoints, and the plane serves one")
    endpoint = endpoints[0]
    if "targetPort" in endpoint:
        refuse(f"{name} names a targetPort, which is read in place of the Service's port by name")
    if endpoint.get("port") != published.get("name"):
        refuse(
            f"{name} scrapes {endpoint.get('port')!r} and not the port Service "
            f"{PLANE_SERVICE} publishes by the name {published.get('name')!r}, so it reaches nothing"
        )
    if endpoint.get("path", METRICS) != METRICS or endpoint.get("scheme", "http") != "http":
        refuse(f"{name} does not ask for {METRICS} over plain HTTP, which is what the plane serves")

    interval = milliseconds(endpoint.get("interval"), f"{name}'s interval")
    timeout = milliseconds(endpoint.get("scrapeTimeout"), f"{name}'s scrape timeout")
    if timeout > interval:
        refuse(f"{name}'s scrape timeout is above its interval: the operator rejects it, and nothing scrapes the plane")

    bound = literal(plane_env, PLANE, READ_TIMEOUT)
    if not re.fullmatch(r"[1-9][0-9]*", bound):
        refuse(f"{READ_TIMEOUT} is {bound!r}, which the process refuses as not a positive whole number")
    if int(bound) >= timeout:
        refuse(
            f"{READ_TIMEOUT} is {bound} and {name} gives up after {timeout} ms: a slow read is "
            "then cut off by Prometheus, which says only that it timed out, rather than "
            "answered 503 by the plane, which says why"
        )


def main():
    if len(sys.argv) != 2:
        refuse("usage: metrics-plane.py RENDERED_MANIFEST")
    documents = [
        document for document in yaml.safe_load_all(Path(sys.argv[1]).read_text()) if document
    ]
    api = container(documents, API).get("env") or []
    plane_env = container(documents, PLANE).get("env") or []

    original, copy = ISSUER
    wanted = literal(api, API, original)
    given = literal(plane_env, PLANE, copy)
    if given != wanted:
        refuse(
            f"{copy} is {given!r} and {original} is {wanted!r}: the plane labels an owner "
            "only under its own issuer, so every owner it serves is empty"
        )

    plane = one(documents, "Deployment", PLANE[0], CONTROL)
    labels = plane["spec"]["template"]["metadata"].get("labels") or {}
    database(documents, plane)
    service, published, port = served(documents, labels)
    ingress(documents, labels, port)
    unpublished(documents)
    scraped(documents, service, published, plane_env)


if __name__ == "__main__":
    main()
