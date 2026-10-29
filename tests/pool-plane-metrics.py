#!/usr/bin/env python3
"""Refuse a rendered cluster in which the pool plane's runners' reports are
reached by a public route or by anything but Prometheus, or are not scraped by
one monitor more often than a runner reports.

The reports' page takes no token and names every runner by its tenant,
project, pool, owner and machine. Two public routes reach the plane: the
Ingress for `chuggy-pool.vteng.io`, and the forwardAuth middleware the
registry's public front puts every pull through. Both name the plane's Service,
so chuggy-pool-plane.yaml gives the reports a listener and a Service of their
own, and what keeps them there is spread over objects that each read correctly
while another is wrong.

THE LISTENER IS WHERE THE MANIFEST SAYS. Its port is a literal, apart from the
plane's own, and declared once by the container under a name. Its host is
every address: the process opens it on the loopback otherwise, where
Prometheus reaches nothing. And the pod binds no port of a node, by sharing its
network or by a hostPort, either of which serves the port at the node's own
address and not at the pod's alone.

NO PUBLIC ROUTE LANDS ON IT. The reports' Service is the one Service that
selects the plane's pod and lands on the reports' port: a cluster address with
that one port and no external address. No Ingress, no Traefik object and no
ExternalName Service names it. Every other Service selecting the pod, the
plane's Service among them, lands elsewhere, so a route naming one of those
reaches the plane's own port or nothing. A headless Service is a pod's every
port, since a client connects past it on whichever it names.

THE REPORTS' PORT ADMITS PROMETHEUS, AND NO OTHER SOURCE. Policies add, so every
one that isolates the plane's pod for ingress is read, and what they admit
together is Prometheus on the reports' port, Traefik on the port the plane's
Service lands on, and nothing else: either source on the other's port, or a
third source, is a finding.

ONE SCRAPE, BY NAME, OFTENER THAN A RUNNER REPORTS. Exactly one ServiceMonitor
selects the reports' Service, carries the label this Prometheus selects
monitors by, and scrapes one endpoint: that Service's port by its name, at
`/metrics` over plain HTTP, with an interval and a timeout written. A timeout
above the interval is a monitor the operator rejects. An interval as long as a
runner's period reads a report or skips it as the two clocks drift.

WHAT THIS GATE CANNOT READ IT REFUSES rather than passes: a variable named
twice or not as a literal, a selector, peer or port in a shape it does not
resolve, and a duration it cannot parse.

WHAT IT DOES NOT HOLD is that cloudflared forwards to Traefik alone, which is
modules/cloudflare-tunnel.nix's; that the Prometheus and Traefik pods carry the
labels the policy names them by, which are the operator's and k3s's and no
render shows; that a selectorless Service's endpoints name the pod; or that a
runner reports at the period written below, which is kasofsk/chuggy-common's
`runnerReportIntervalMs`.
"""

import re
import sys
from pathlib import Path

import yaml

CONTROL = "chuggy"

# (deployment, container)
PLANE = ("chuggy-pool-plane", "pool-plane")

PLANE_SERVICE = "chuggy-pool-plane"
REPORTS_SERVICE = "chuggy-pool-plane-metrics"
INGRESS_POLICY = "chuggy-pool-plane-ingress"

PLANE_PORT = "CHUG_POOL_PLANE_PORT"
REPORTS_HOST = "CHUG_POOL_PLANE_METRICS_HOST"
REPORTS_PORT = "CHUG_POOL_PLANE_METRICS_PORT"
EVERY_ADDRESS = "0.0.0.0"

# How a value names another variable, which the kubelet replaces with that
# variable's value where the container defines it.
REFERENCE = "$("

# The two sources the plane's pod admits.
PROMETHEUS = "app.kubernetes.io/name=prometheus in monitoring"
TRAEFIK = "app.kubernetes.io/name=traefik in kube-system"

# The label this Prometheus selects monitors by, and the path the reports are
# served at.
RELEASE = ("release", "kube-prometheus-stack")
METRICS = "/metrics"

# How often a runner reports.
REPORT_PERIOD_MS = 60_000

# The label a namespace is named by, which is the only namespaceSelector this
# gate resolves: the API server sets it, so it names one namespace.
NAMESPACE_LABEL = "kubernetes.io/metadata.name"

# A Prometheus duration, unit by unit in the order it is written.
DURATION = re.compile(
    r"(?:(\d+)y)?(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+)s)?(?:(\d+)ms)?"
)
DURATION_MS = (365 * 86_400_000, 7 * 86_400_000, 86_400_000, 3_600_000, 60_000, 1_000, 1)


def refuse(message):
    raise SystemExit(f"pool plane metrics: {message}")


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


def described(document):
    metadata = document["metadata"]
    return f"{document.get('kind')} {metadata.get('namespace')}/{metadata['name']}"


def literal(env, variable):
    """One variable's value, where the manifest states it and nothing else does."""
    entries = [item for item in env if item.get("name") == variable]
    if len(entries) != 1:
        refuse(f"{PLANE[0]} names {variable} {len(entries)} times, and this gate reads one")
    value = entries[0].get("value")
    if "valueFrom" in entries[0] or not isinstance(value, str) or not value:
        refuse(
            f"{PLANE[0]} does not give {variable} as a literal value, so where its "
            "process listens is not something this gate read"
        )
    if REFERENCE in value:
        refuse(
            f"{PLANE[0]} gives {variable} as {value!r}, which names another variable: "
            "the kubelet writes that one's value over it, and this gate reads the manifest"
        )
    return value


def port_number(env, variable):
    value = literal(env, variable)
    if not re.fullmatch(r"[1-9][0-9]*", value) or int(value) > 65_535:
        refuse(f"{variable} is {value!r}, which the process refuses as not a port number")
    return int(value)


def selects(selector, labels, named):
    """Whether a label selector matches one object's labels. Only the two
    shapes this tree uses are evaluated, and an empty selector is every object
    in its namespace."""
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions") or []:
        if expression["operator"] != "In":
            refuse(f"{named} selects by {expression['operator']!r}, which this gate cannot evaluate")
        if labels.get(expression["key"]) not in expression["values"]:
            return False
    return True


def written(labels):
    return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))


def listening(plane):
    """The plane's own port and the reports', each where the manifest puts it."""
    pod = plane["spec"]["template"]["spec"]
    boxes = [entry for entry in pod.get("containers") or [] if entry["name"] == PLANE[1]]
    if len(boxes) != 1:
        refuse(f"{PLANE[0]} has {len(boxes)} containers named {PLANE[1]}")
    env = boxes[0].get("env") or []

    host = literal(env, REPORTS_HOST)
    if host != EVERY_ADDRESS:
        refuse(
            f"{REPORTS_HOST} is {host!r} and not {EVERY_ADDRESS}: the reports are served "
            "on that address alone, and Prometheus reaches the pod on another"
        )
    own, reports = port_number(env, PLANE_PORT), port_number(env, REPORTS_PORT)
    if own == reports:
        refuse(
            f"{REPORTS_PORT} is {PLANE_PORT}, {own}: the reports would be served where "
            "every public route to the plane lands"
        )
    declared = [entry for entry in boxes[0].get("ports") or [] if entry.get("containerPort") == reports]
    if (
        len(declared) != 1
        or not declared[0].get("name")
        or declared[0].get("protocol", "TCP") != "TCP"
    ):
        refuse(
            f"the {PLANE[1]} container does not declare TCP {reports} once and by a name, "
            "which is how the reports' Service reaches it"
        )

    if pod.get("hostNetwork"):
        refuse(
            "the plane's pod shares its node's network, so the reports are served at "
            "the node's own address, past every Service and policy this gate reads"
        )
    for entry in (pod.get("initContainers") or []) + (pod.get("containers") or []):
        for published in entry.get("ports") or []:
            if "hostPort" in published:
                refuse(
                    f"the {entry['name']} container binds the node's port "
                    f"{published['hostPort']}, which serves the pod at the node's own address"
                )
    return boxes[0], reports


def lands(service, box):
    """Each port a Service selecting the plane's pod publishes, with the ports
    on the pod a connection to it lands on."""
    if service["spec"].get("clusterIP") == "None":
        everything = {entry["containerPort"] for entry in box.get("ports") or []}
        return [(published, everything) for published in service["spec"].get("ports") or [{}]]
    found = []
    for published in service["spec"].get("ports") or []:
        target = published.get("targetPort", published["port"])
        if not isinstance(target, int):
            numbers = {
                entry["containerPort"]
                for entry in box.get("ports") or []
                if entry.get("name") == target
            }
            if len(numbers) != 1:
                refuse(
                    f"{described(service)} targets the named port {target!r}, which the "
                    f"{PLANE[1]} container declares {len(numbers)} numbers for"
                )
            target = numbers.pop()
        found.append((published, {target}))
    return found


def unpublished(documents, labels, box, reports):
    """The reports' Service, the one that lands on their port, and its port;
    and the port the plane's Service lands on, which Traefik is admitted to."""
    selecting = [
        document
        for document in documents
        if document.get("kind") == "Service"
        and document["metadata"].get("namespace") == CONTROL
        and document["spec"].get("selector")
        and all(labels.get(key) == value for key, value in document["spec"]["selector"].items())
    ]
    names = [document["metadata"]["name"] for document in selecting]
    for name in (PLANE_SERVICE, REPORTS_SERVICE):
        if names.count(name) != 1:
            refuse(
                f"{names.count(name)} Services {CONTROL}/{name} select the plane's pod "
                f"({written(labels)}), and this gate resolves one"
            )
    for service in selecting:
        if service["metadata"]["name"] == REPORTS_SERVICE:
            continue
        if any(reports in landed for _, landed in lands(service, box)):
            refuse(
                f"{described(service)} lands on {reports}, the reports' port: a route to it "
                f"reaches every runner's report, and {REPORTS_SERVICE} is the one Service "
                "for them"
            )

    service = selecting[names.index(REPORTS_SERVICE)]
    kind = service["spec"].get("type", "ClusterIP")
    if kind != "ClusterIP" or service["spec"].get("externalIPs"):
        refuse(
            f"{described(service)} is a {kind} Service"
            f"{' with external addresses' if service['spec'].get('externalIPs') else ''}, "
            "which publishes the reports past the pod network: they are served to a "
            "cluster address alone"
        )
    published = lands(service, box)
    if (
        len(published) != 1
        or published[0][1] != {reports}
        or published[0][0].get("protocol", "TCP") != "TCP"
    ):
        refuse(
            f"{described(service)} does not publish one TCP port that lands on {reports} "
            "and nowhere else"
        )

    plane = selecting[names.index(PLANE_SERVICE)]
    landed = {port for _, ports in lands(plane, box) for port in ports}
    if len(landed) != 1:
        refuse(
            f"{described(plane)} lands on {sorted(landed)}, and this gate resolves the one "
            "port the plane's public routes reach"
        )

    for document in documents:
        kind = document.get("kind")
        spec = document.get("spec") or {}
        if kind == "Ingress":
            read = [spec, document["metadata"].get("annotations") or {}]
        elif str(document.get("apiVersion", "")).startswith("traefik."):
            read = [spec]
        elif kind == "Service" and spec.get("type") == "ExternalName":
            read = [spec.get("externalName")]
        else:
            continue
        if any(REPORTS_SERVICE in yaml.safe_dump(part) for part in read):
            refuse(
                f"{described(document)} names {REPORTS_SERVICE}, and Traefik routes what "
                "it names: the reports reach Prometheus and nothing outside the cluster"
            )
    return service, published[0][0], landed.pop()


def whom(peer, policy):
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
                f"an ingress peer on {policy} names namespaces by something other than "
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
            f"an ingress peer on {policy} is neither an address block nor pods named by "
            "their labels, and this gate cannot say what it names: a peer naming no "
            "label is every pod in its namespace"
        )
    return f"{written(selector['matchLabels'])} in {namespace}"


def reach(policy):
    """Everything one policy admits, as (who, protocol, port)."""
    name = policy["metadata"]["name"]
    found = set()
    for arm in policy["spec"].get("ingress") or []:
        peers = arm.get("from") or []
        ports = arm.get("ports") or []
        if not peers or not ports:
            refuse(
                f"an ingress arm on {name} names no peer or no port, so it admits every "
                "one of whichever it leaves out"
            )
        for port in ports:
            number = port.get("port")
            if "endPort" in port or isinstance(number, bool) or not isinstance(number, int):
                refuse(
                    f"an ingress arm on {name} names the port {number!r} or a range from "
                    "it, and this gate reads one number at a time"
                )
            for peer in peers:
                found.add((whom(peer, name), port.get("protocol", "TCP"), number))
    return found


def spoken(triples):
    return "; ".join(f"{who} on {protocol} {port}" for who, protocol, port in sorted(triples))


def ingress(documents, labels, public, reports):
    """Prometheus on the reports' port, Traefik on the plane's, and nothing
    else, from every policy that isolates the plane's pod for ingress.
    `policyTypes` is authoritative when present; absent, the API server reads
    every policy as one for Ingress."""
    policies = [
        document
        for document in documents
        if document.get("kind") == "NetworkPolicy"
        and document["metadata"].get("namespace") == CONTROL
        and (document["spec"].get("policyTypes") is None or "Ingress" in document["spec"]["policyTypes"])
        and selects(document["spec"].get("podSelector") or {}, labels, document["metadata"]["name"])
    ]
    if INGRESS_POLICY not in [document["metadata"]["name"] for document in policies]:
        refuse(
            f"{INGRESS_POLICY} does not isolate the plane's pod for ingress: its "
            "policyTypes leave Ingress out or its podSelector selects another pod, so "
            "the pod network reaches every port the pod declares"
        )
    admitted = set()
    for document in policies:
        admitted |= reach(document)
    wanted = {(PROMETHEUS, "TCP", reports), (TRAEFIK, "TCP", public)}
    if admitted != wanted:
        wider, lost = admitted - wanted, wanted - admitted
        refuse(
            "the plane's pod "
            + "; and ".join(
                part
                for part in (
                    f"also admits {spoken(wider)}" if wider else "",
                    f"does not admit {spoken(lost)}" if lost else "",
                )
                if part
            )
            + f": the reports' page takes no token, and {spoken(wanted)} are the whole of "
            "who reaches the pod"
        )


def milliseconds(duration, named):
    match = DURATION.fullmatch(duration) if isinstance(duration, str) and duration else None
    if not match or not any(match.groups()):
        refuse(f"{named} is {duration!r}, which is not a duration this gate reads")
    return sum(int(count) * unit for count, unit in zip(match.groups(), DURATION_MS) if count)


def scraped(documents, service, published):
    """The one monitor of the reports' Service, and its one endpoint."""
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
        # An empty selector is every Service in those namespaces.
        if selects(spec.get("selector") or {}, labels, described(document)):
            monitors.append(document)
    if len(monitors) != 1:
        refuse(
            f"{len(monitors)} ServiceMonitors select Service {REPORTS_SERVICE}: one scrape is "
            "what its interval is argued for, and with none no report is read"
        )
    monitor = monitors[0]
    name = described(monitor)
    key, value = RELEASE
    if (monitor["metadata"].get("labels") or {}).get(key) != value:
        refuse(f"{name} lacks the label {key}={value}, so Prometheus does not select it")

    endpoints = monitor["spec"].get("endpoints") or []
    if len(endpoints) != 1:
        refuse(f"{name} has {len(endpoints)} endpoints, and the reports are one page")
    endpoint = endpoints[0]
    if "targetPort" in endpoint:
        refuse(f"{name} names a targetPort, which is read in place of the Service's port by name")
    if endpoint.get("port") != published.get("name"):
        refuse(
            f"{name} scrapes {endpoint.get('port')!r} and not the port Service "
            f"{REPORTS_SERVICE} publishes by the name {published.get('name')!r}, so it reaches nothing"
        )
    if endpoint.get("path", METRICS) != METRICS or endpoint.get("scheme", "http") != "http":
        refuse(f"{name} does not ask for {METRICS} over plain HTTP, which is what the reports are")

    interval = milliseconds(endpoint.get("interval"), f"{name}'s interval")
    timeout = milliseconds(endpoint.get("scrapeTimeout"), f"{name}'s scrape timeout")
    if timeout > interval:
        refuse(f"{name}'s scrape timeout is above its interval: the operator rejects it, and nothing scrapes the plane")
    if interval >= REPORT_PERIOD_MS:
        refuse(
            f"{name} scrapes every {interval} ms, and a runner reports every "
            f"{REPORT_PERIOD_MS} ms: a scrape as seldom as that reads each report or skips "
            "it as the two clocks drift"
        )


def main():
    if len(sys.argv) != 2:
        refuse("usage: pool-plane-metrics.py RENDERED_MANIFEST")
    documents = [
        document for document in yaml.safe_load_all(Path(sys.argv[1]).read_text()) if document
    ]
    plane = one(documents, "Deployment", PLANE[0], CONTROL)
    labels = plane["spec"]["template"]["metadata"].get("labels") or {}
    box, reports = listening(plane)
    service, published, public = unpublished(documents, labels, box, reports)
    ingress(documents, labels, public, reports)
    scraped(documents, service, published)


if __name__ == "__main__":
    main()
