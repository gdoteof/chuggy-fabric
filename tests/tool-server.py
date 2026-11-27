#!/usr/bin/env python3
"""Refuse a rendered cluster whose tool server does not ask for the API's
audience under the API's issuer and algorithms, answers a client the README
does not create, is probed on anything but its two health routes, is reached
by anything but Traefik or reaches anything but its three arms, or is served
on a host gtr's tunnel does not forward.

THE AUDIENCE, THE ISSUER AND THE ALGORITHMS ARE COPIES OF THE API'S, each held
to chuggy-api.yaml's as the string it is. The server asks Hydra for the API's
audience beside its own resource and calls the API with the token it gets, so
a copy that differs is an authorization whose every call the API refuses, and
both files read correctly alone.

THE CLIENT IT ANSWERS IS THE ONE THE README CREATES. `/authorize` answers only
the clients `CHUG_TOOL_SERVER_CLIENTS` names, and the README's
`hydra create oauth2-client` under "Claude's MCP connector" is what makes one.
They are held to one id, and that command to the two audiences the server
needs Hydra to grant and to having no `--skip-consent`.

BOTH PROBES ASK A HEALTH ROUTE: liveness `/health/live` and readiness
`/health/ready`, each on the port the Service lands on.

ITS PORT ADMITS TRAEFIK, AND NO OTHER SOURCE, and its egress is the resolver,
the API's pods on the API's port and public HTTPS less the ranges
chuggy-api-egress excepts, exactly: no PostgreSQL. Every policy that isolates
the pod in a direction is folded, because policies add. The API's ingress
policy admits the server's pods on that port, or the arm reaches nothing.

ITS HOST IS PUBLISHED. The Ingress naming the server's Service serves
`mcp.vteng.io`, the host of its public origin, on a port that Service
declares, and that host is in gtr's `chuggy.tunnel.hostnames`.

WHAT THIS GATE CANNOT READ IT REFUSES rather than passes: a variable that is
not a literal or names another, a peer it cannot name, a port range.

WHAT IT DOES NOT HOLD is that the client exists in Hydra, that its lifespans
are set, that the CNAME is routed, or that Traefik's pods carry the label they
are named by: those are an operator's and k3s's, and no render shows them.
"""

import json
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

CONTROL = "chuggy"

# (deployment, container)
API = ("chuggy-api", "api")
SERVER = ("chuggy-tool-server", "tool-server")

# (what is held, the API's variable, the server's copy of it)
HELD = (
    ("audience", "CHUG_API_OIDC_AUDIENCE", "CHUG_TOOL_SERVER_API_AUDIENCE"),
    ("issuer", "CHUG_API_OIDC_ISSUER", "CHUG_TOOL_SERVER_OIDC_ISSUER"),
    ("list of algorithms", "CHUG_API_OIDC_ALGORITHMS", "CHUG_TOOL_SERVER_OIDC_ALGORITHMS"),
)

ORIGIN = "CHUG_TOOL_SERVER_PUBLIC_ORIGIN"
CLIENTS = "CHUG_TOOL_SERVER_CLIENTS"
HOST = "mcp.vteng.io"

SERVICE = "chuggy-tool-server"
API_SERVICE = "chuggy-api"
INGRESS_POLICY = "chuggy-tool-server-ingress"
EGRESS_POLICY = "chuggy-tool-server-egress"
API_INGRESS_POLICY = "chuggy-api-ingress"

PROBES = {"livenessProbe": "/health/live", "readinessProbe": "/health/ready"}

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

# Where the server goes beside the API: the resolver, and public HTTPS for the
# issuer and for GitHub.
BESIDE = {
    ("k8s-app=kube-dns in kube-system", "UDP", 53),
    ("k8s-app=kube-dns in kube-system", "TCP", 53),
    ("0.0.0.0/0 except " + ", ".join(sorted(PRIVATE)), "TCP", 443),
}

# The README's section holding the client's command.
SECTION = "### Claude's MCP connector"

NAMESPACE_LABEL = "kubernetes.io/metadata.name"
PEERS = {"egress": "to", "ingress": "from"}


def refuse(message):
    raise SystemExit(f"tool server: {message}")


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
    deployment, box = workload
    spec = one(documents, "Deployment", deployment, CONTROL)["spec"]["template"]["spec"]
    boxes = [entry for entry in spec.get("containers") or [] if entry["name"] == box]
    if len(boxes) != 1:
        refuse(f"{deployment} has {len(boxes)} containers named {box}")
    return boxes[0]


def labels_of(documents, deployment):
    return one(documents, "Deployment", deployment, CONTROL)["spec"]["template"]["metadata"].get(
        "labels"
    ) or {}


def literal(env, workload, variable):
    entries = [item for item in env if item.get("name") == variable]
    if len(entries) != 1:
        refuse(f"{workload[0]} names {variable} {len(entries)} times, and this gate reads one")
    value = entries[0].get("value")
    if "valueFrom" in entries[0] or not isinstance(value, str) or not value:
        refuse(f"{workload[0]} does not give {variable} as a literal value")
    if "$(" in value:
        refuse(f"{workload[0]} gives {variable} as {value!r}, which names another variable")
    return value


def selects(selector, labels, described):
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions") or []:
        if expression["operator"] != "In":
            refuse(f"{described} selects by {expression['operator']!r}, which this gate cannot evaluate")
        if labels.get(expression["key"]) not in expression["values"]:
            return False
    return True


def written(labels):
    return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))


def whom(peer, policy, way):
    if set(peer) == {"ipBlock"} and set(peer["ipBlock"]) <= {"cidr", "except"}:
        block = peer["ipBlock"]
        excepted = sorted(block.get("except") or [])
        return block["cidr"] + (" except " + ", ".join(excepted) if excepted else "")
    namespace = CONTROL
    if "namespaceSelector" in peer:
        named = peer["namespaceSelector"] or {}
        chosen = named.get("matchLabels") or {}
        if set(named) != {"matchLabels"} or set(chosen) != {NAMESPACE_LABEL}:
            refuse(f"an {way} peer on {policy} names namespaces by something other than {NAMESPACE_LABEL}")
        namespace = chosen[NAMESPACE_LABEL]
    selector = peer.get("podSelector")
    if (
        set(peer) - {"namespaceSelector", "podSelector"}
        or not selector
        or set(selector) != {"matchLabels"}
        or not selector["matchLabels"]
    ):
        refuse(f"an {way} peer on {policy} is neither an address block nor pods named by their labels")
    return f"{written(selector['matchLabels'])} in {namespace}"


def reach(policy, way):
    name = policy["metadata"]["name"]
    found = set()
    for arm in policy["spec"].get(way) or []:
        peers = arm.get(PEERS[way]) or []
        ports = arm.get("ports") or []
        if not peers or not ports:
            refuse(f"an {way} arm on {name} names no peer or no port, so it admits every one")
        for port in ports:
            number = port.get("port")
            if "endPort" in port or isinstance(number, bool) or not isinstance(number, int):
                refuse(f"an {way} arm on {name} names the port {number!r} or a range from it")
            for peer in peers:
                found.add((whom(peer, name, way), port.get("protocol", "TCP"), number))
    return found


def folded(documents, labels, direction, named):
    """What every policy isolating the server's pod in one direction admits."""
    policies = []
    for document in documents:
        if document.get("kind") != "NetworkPolicy" or document["metadata"].get("namespace") != CONTROL:
            continue
        types = document["spec"].get("policyTypes")
        if types is None:
            isolates = direction == "ingress" or "egress" in document["spec"]
        else:
            isolates = direction.capitalize() in types
        if isolates and selects(document["spec"].get("podSelector") or {}, labels, document["metadata"]["name"]):
            policies.append(document)
    if named not in [document["metadata"]["name"] for document in policies]:
        refuse(f"{named} does not isolate the server's pod for {direction}")
    admitted = set()
    for document in policies:
        admitted |= reach(document, direction)
    return admitted


def spoken(triples):
    return "; ".join(f"{who} on {protocol} {port}" for who, protocol, port in sorted(triples))


def landed(documents, name, labels, box):
    """A Service's one port, and the container port it lands on."""
    service = one(documents, "Service", name, CONTROL)
    chosen = service["spec"].get("selector") or {}
    if not chosen or any(labels.get(key) != value for key, value in chosen.items()):
        refuse(f"Service {name} selects {written(chosen)!r}, which its pod does not carry")
    published = service["spec"].get("ports") or []
    if len(published) != 1 or published[0].get("protocol", "TCP") != "TCP":
        refuse(f"Service {name} does not publish one TCP port, and this gate resolves one")
    target = published[0].get("targetPort", published[0]["port"])
    declared = box.get("ports") or []
    if not isinstance(target, int):
        numbers = {entry["containerPort"] for entry in declared if entry.get("name") == target}
        if len(numbers) != 1:
            refuse(f"Service {name} targets the named port {target!r}, which its container publishes {len(numbers)} numbers for")
        target = numbers.pop()
    if target not in {entry["containerPort"] for entry in declared}:
        refuse(f"Service {name} lands on {target}, which its container does not declare")
    return published[0], target


def probes(box, port):
    for kind, path in PROBES.items():
        sent = (box.get(kind) or {}).get("httpGet") or {}
        if sent.get("path") != path:
            refuse(f"the server's {kind} asks {sent.get('path')!r} and not {path}")
        named = sent.get("port")
        numbers = {
            entry["containerPort"]
            for entry in box.get("ports") or []
            if named in (entry.get("name"), entry["containerPort"])
        }
        if numbers != {port}:
            refuse(f"the server's {kind} asks port {named!r}, which is not {port}, where it listens")


def routed(documents, published, hostnames):
    """The one Ingress arm naming the server's Service, on its origin's host."""
    found = [
        (ingress, rule, arm)
        for ingress in documents
        if ingress.get("kind") == "Ingress"
        for rule in (ingress.get("spec") or {}).get("rules") or []
        for arm in (rule.get("http") or {}).get("paths") or []
        if ((arm.get("backend") or {}).get("service") or {}).get("name") == SERVICE
    ]
    if len(found) != 1:
        refuse(f"{len(found)} Ingress arms name Service {SERVICE}, and this gate reads one")
    ingress, rule, arm = found[0]
    if ingress["metadata"].get("namespace") != CONTROL:
        refuse(f"the Ingress naming {SERVICE} is not in `{CONTROL}`, so it names another Service")
    if rule.get("host") != HOST:
        refuse(f"the Ingress serves the server on {rule.get('host')!r} and not {HOST}")
    if arm.get("path") != "/" or arm.get("pathType") != "Prefix":
        refuse(f"the Ingress sends {arm.get('path')!r} as {arm.get('pathType')!r}, and not `/` as a Prefix")
    port = arm["backend"]["service"].get("port") or {}
    if port != {"number": published["port"]} and port != {"name": published.get("name")}:
        refuse(f"the Ingress sends {HOST} to port {port!r} of {SERVICE}, which declares {published['port']}")
    if HOST not in hostnames:
        refuse(f"{HOST} is not in gtr's chuggy.tunnel.hostnames, so cloudflared answers it 404")


def command(readme):
    """The README's `hydra create oauth2-client` under the connector's section,
    as the arguments it passes."""
    text = Path(readme).read_text()
    if text.count(SECTION) != 1:
        refuse(f"the README has {text.count(SECTION)} sections {SECTION!r}, and this gate reads one")
    section = text.split(SECTION, 1)[1].split("\n#", 1)[0]
    commands = [
        shlex.split(block.replace("\\\n", " "))
        for block in re.findall(r"^    kubectl .*?(?:\\\n.*?)*$", section, re.M)
        if "hydra create oauth2-client" in block
    ]
    if len(commands) != 1:
        refuse(f"{SECTION!r} holds {len(commands)} `hydra create oauth2-client` commands, and this gate reads one")
    words = commands[0]
    given = {}
    for index, word in enumerate(words):
        if word.startswith("--"):
            following = words[index + 1] if index + 1 < len(words) else None
            value = None if following is None or following.startswith("--") else following
            given.setdefault(word, []).append(value)
    return given


def main():
    if len(sys.argv) != 4:
        refuse("usage: tool-server.py RENDERED_MANIFEST HOST_JSON README")
    documents = [
        document for document in yaml.safe_load_all(Path(sys.argv[1]).read_text()) if document
    ]
    hostnames = json.loads(Path(sys.argv[2]).read_text())["hostnames"]
    flags = command(sys.argv[3])

    api = container(documents, API).get("env") or []
    box = container(documents, SERVER)
    env = box.get("env") or []
    for held, original, copy in HELD:
        wanted = literal(api, API, original)
        given = literal(env, SERVER, copy)
        if given != wanted:
            refuse(
                f"{copy} is {given!r} and {original} is {wanted!r}: the server asks for a "
                f"token under another {held} than the API verifies, and the API refuses it"
            )
    audience = literal(api, API, "CHUG_API_OIDC_AUDIENCE")

    origin = literal(env, SERVER, ORIGIN)
    if origin != f"https://{HOST}":
        refuse(f"{ORIGIN} is {origin!r} and not https://{HOST}, the host its Ingress serves")
    resource = f"{origin}/mcp"

    clients = [client.strip() for client in literal(env, SERVER, CLIENTS).split(",")]
    ids = flags.get("--id") or []
    if len(ids) != 1 or clients != ids:
        refuse(
            f"{CLIENTS} names {clients} and the README's command creates {ids}: `/authorize` "
            "answers a client Hydra does not have, or refuses the one it has"
        )
    if sorted(flags.get("--audience") or []) != sorted([resource, audience]):
        refuse(
            f"the README's client is registered for the audiences {flags.get('--audience')} and "
            f"not {resource} and {audience}, which the server asks Hydra to grant"
        )
    if "--skip-consent" in flags:
        refuse("the README's client skips consent, so nobody is asked before Claude acts as them")
    if flags.get("--token-endpoint-auth-method") != ["none"]:
        refuse("the README's client is not a public one, and a client secret would then be a credential to keep")

    labels = labels_of(documents, SERVER[0])
    published, port = landed(documents, SERVICE, labels, box)
    probes(box, port)

    admitted = folded(documents, labels, "ingress", INGRESS_POLICY)
    if admitted != {(TRAEFIK, "TCP", port)}:
        refuse(f"the server's pod admits {spoken(admitted) or 'nothing'}, and Traefik on {port} is the whole of who reaches it")

    # The API's pods as its Service selects them, on the port it lands on.
    api_labels = labels_of(documents, API[0])
    _, api_port = landed(documents, API_SERVICE, api_labels, container(documents, API))
    api_selector = one(documents, "Service", API_SERVICE, CONTROL)["spec"]["selector"]
    api_arm = (f"{written(api_selector)} in {CONTROL}", "TCP", api_port)
    reached = folded(documents, labels, "egress", EGRESS_POLICY)
    expected = BESIDE | {api_arm}
    wider, lost = reached - expected, expected - reached
    if wider:
        refuse(f"the server's pod may also reach {spoken(wider)}: the resolver, the API and public HTTPS are the whole of where it goes")
    if lost:
        refuse(f"the server's pod does not reach {spoken(lost)}")

    api_admits = reach(one(documents, "NetworkPolicy", API_INGRESS_POLICY, CONTROL), "ingress")
    if not any(
        protocol == "TCP"
        and number == api_port
        and who.endswith(f" in {CONTROL}")
        and all(
            labels.get(key) == value
            for key, value in (pair.split("=", 1) for pair in who[: -len(f" in {CONTROL}")].split(","))
        )
        for who, protocol, number in api_admits
        if "=" in who
    ):
        refuse(f"{API_INGRESS_POLICY} admits no pod labelled {written(labels)} on {api_port}, so every tool call is refused")

    routed(documents, published, hostnames)


if __name__ == "__main__":
    main()
