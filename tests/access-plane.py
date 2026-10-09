#!/usr/bin/env python3
"""Refuse a rendered cluster whose access plane does not verify a token as the
API does, or does not reach its database as the one role it is given.

The console reads both with one token. Answered 401, it renews that token once
and signs the person out where the fresh one is refused too -- kasofsk/chuggy's
`ui/chuggy-ui/app/browser/api.ts`. So a plane holding a token to another
issuer, audience or list of algorithms than the API's refuses what the API
accepts, and a page that reads it signs its reader out of the whole console.

EACH OF THE THREE IS WRITTEN TWICE, in chuggy-api.yaml and in
chuggy-access-plane.yaml, and each file reads correctly alone. The API's is the
original, argued where it is written; the plane's is a copy, and this holds the
copy to it as the string it is. A list of algorithms in another order is
refused with the rest: what is held is that nothing was typed twice
differently, and not what either process makes of what it reads.

ITS DATABASE IS HELD FROM THE URL OUTWARDS. The plane keeps invite links in
PostgreSQL and nothing else, as one login role that sets one group role, and
what makes that so is a URL, a Secret key, a label and an egress arm, each
correct on its own page. A URL naming another service's login or group is well
formed and connects as that service. A second key is a second credential in a
pod with a use for one. A pod without the label, or a policy without the arm,
is refused the server at its first connection, and the plane is never ready.
So:

  - the URL signs in as `chuggy_access_plane_login`, sets `chuggy_access_plane`
    and nothing else, and addresses PostgreSQL's Service on the port it
    publishes, and the container names no second database;
  - the password in it is the variable defined above it, which is one key of
    `chuggy-postgres-credentials`, and the pod is handed no other key of any
    Secret;
  - the pod carries the client label, and `postgres-admits-labelled-clients`
    admits a pod so labelled on the port the URL lands on;
  - the pod's egress reaches the pods that Service selects on that port, and
    beyond them exactly what it reached before the plane had a database, so an
    arm gained or widened is a finding rather than a silent change.

AND A ROLLOUT LEAVES THE OLD POD SERVING. chuggy-access-plane.yaml says a plane
whose login role does not exist yet is never ready while the pod before it
keeps serving. That is the default strategy's doing, and the `Recreate` that
workloads beside it carry would remove the old pod first.

WHAT THIS GATE CANNOT READ IT REFUSES rather than passes: a variable either
container names twice or not at all, one that is empty, one whose value comes
from a Secret or a ConfigMap where a literal is held, one the kubelet would
rewrite before the process read it, an environment taken whole with `envFrom`,
a Secret mounted as a volume, and an egress peer or port in a shape it does not
resolve.

WHAT IT DOES NOT HOLD is that the original is right: that the issuer is the one
Hydra signs as, and the audience the one chuggy-ui.yaml has the console ask
for. Nor that either role exists, that the login is a member of the group, or
that the key holds the password PostgreSQL accepts: those are the roles file's
and the migration's, on the rig.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import yaml

CONTROL = "chuggy"

# (deployment, container)
API = ("chuggy-api", "api")
PLANE = ("chuggy-access-plane", "access-plane")

# (what a token is held to, the API's variable, the plane's copy of it)
HELD = (
    ("issuer", "CHUG_API_OIDC_ISSUER", "CHUG_ACCESS_PLANE_OIDC_ISSUER"),
    ("audience", "CHUG_API_OIDC_AUDIENCE", "CHUG_ACCESS_PLANE_OIDC_AUDIENCE"),
    ("list of algorithms", "CHUG_API_OIDC_ALGORITHMS", "CHUG_ACCESS_PLANE_OIDC_ALGORITHMS"),
)

# How a value names another variable, which the kubelet replaces with that
# variable's value where the container defines it.
REFERENCE = "$("

# The plane's connection. The login role is who authenticates and the group
# role is what `current_user` reads once the URL's one option has set it, which
# is what the process holds its readiness to.
DATABASE_URL = "CHUG_ACCESS_PLANE_DATABASE_URL"
PASSWORD = "CHUG_ACCESS_PLANE_PASSWORD"
LOGIN_ROLE = "chuggy_access_plane_login"
GROUP_ROLE = "chuggy_access_plane"
DATABASE = "chuggy"

# (Secret, key): what modules/chuggy-secrets.nix generates for that login role.
CREDENTIAL = ("chuggy-postgres-credentials", "access-plane-password")

POSTGRES_SERVICE = "postgres"
POSTGRES_POLICY = "postgres-admits-labelled-clients"
POSTGRES_CLIENT = ("chuggy.dev/postgres-client", "true")
EGRESS_POLICY = "chuggy-access-plane-egress"

CLUSTER_SUFFIX = ".svc.cluster.local"

# The label a namespace is named by, which is the only namespaceSelector this
# gate resolves: the API server sets it, so it names one namespace.
NAMESPACE_LABEL = "kubernetes.io/metadata.name"

# What a pod is rendered from, and so what a Service's selector is read against.
WORKLOADS = ("Pod", "Deployment", "ReplicaSet", "StatefulSet", "DaemonSet", "Job", "CronJob")

# The ranges the public arm excepts, which chuggy-api-egress argues.
PRIVATE = (
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
)

# Where the plane's pod went before it had a database, as (who, protocol,
# port): the resolver, Keto's read and write ports, Kratos's admin port and
# public HTTPS. chuggy-access-plane.yaml argues each, and tests/keto.py and
# tests/ory-admin.py resolve the Keto and Kratos arms against the pods they
# name. This is the record of the whole, and it is exact.
BEFORE = {
    ("k8s-app=kube-dns in kube-system", "UDP", 53),
    ("k8s-app=kube-dns in kube-system", "TCP", 53),
    ("app=keto in ory", "TCP", 4466),
    ("app=keto in ory", "TCP", 4467),
    ("app=kratos in ory", "TCP", 4434),
    ("0.0.0.0/0 except " + ", ".join(sorted(PRIVATE)), "TCP", 443),
}


def refuse(message):
    raise SystemExit(f"access plane: {message}")


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


def environment(documents, workload):
    """The `env` of one container of one Deployment in the control namespace."""
    deployment, box = workload
    found = [
        document
        for document in documents
        if document.get("kind") == "Deployment"
        and document["metadata"]["name"] == deployment
        and document["metadata"].get("namespace") == CONTROL
    ]
    if len(found) != 1:
        refuse(f"expected one Deployment {CONTROL}/{deployment}, found {len(found)}")
    boxes = [
        entry
        for entry in found[0]["spec"]["template"]["spec"].get("containers") or []
        if entry["name"] == box
    ]
    if len(boxes) != 1:
        refuse(f"{deployment} has {len(boxes)} containers named {box}")
    return boxes[0].get("env") or []


def literal(env, workload, variable):
    """One variable's value, where the manifest states it and nothing else does."""
    entries = [item for item in env if item.get("name") == variable]
    if len(entries) != 1:
        refuse(f"{workload[0]} names {variable} {len(entries)} times, and this gate reads one")
    value = entries[0].get("value")
    if "valueFrom" in entries[0] or not isinstance(value, str) or not value:
        refuse(
            f"{workload[0]} does not give {variable} as a literal value, so what its "
            "process verifies a token against is not something this gate read"
        )
    if REFERENCE in value:
        refuse(
            f"{workload[0]} gives {variable} as {value!r}, which names another variable: "
            "the kubelet writes that one's value over it, and this gate reads the manifest"
        )
    return value


def selects(selector, labels, described):
    """Whether a podSelector matches one pod's labels.

    Only the two shapes this directory uses are evaluated, and an empty
    selector is every pod in its namespace.
    """
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


def isolates_for_egress(policy):
    """Whether a policy confines the pods it selects for egress. `policyTypes`
    is authoritative when present; absent, the API server adds Egress to an
    object that carries an `egress` section."""
    types = policy["spec"].get("policyTypes")
    if types is None:
        return "egress" in policy["spec"]
    return "Egress" in types


def written(labels):
    return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))


def secrets_handed(pod):
    """Every Secret key the pod's containers are handed, as (variable, Secret,
    key), and a refusal where one arrives in a way this gate does not read a
    key from."""
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
                found.append((item["name"], reference.get("name"), reference.get("key")))
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
    its selector names and the container port, resolved as the kernel does."""
    service = one(documents, "Service", POSTGRES_SERVICE, CONTROL)
    published = service["spec"].get("ports") or []
    if len(published) != 1:
        refuse(
            f"Service {POSTGRES_SERVICE} publishes {len(published)} ports, and this gate "
            "resolves one"
        )
    if published[0]["port"] != port:
        refuse(
            f"{DATABASE_URL} reaches port {port}, and Service {POSTGRES_SERVICE} publishes "
            f"{published[0]['port']}"
        )
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
    target = published[0].get("targetPort", published[0]["port"])
    if isinstance(target, int):
        return chosen, target
    numbers = {
        declared["containerPort"]
        for entry in servers[0]["spec"]["template"]["spec"]["containers"]
        for declared in entry.get("ports", [])
        if declared.get("name") == target
    }
    if len(numbers) != 1:
        refuse(
            f"Service {POSTGRES_SERVICE} targets the named port {target!r}, which its pod "
            f"publishes {len(numbers)} numbers for"
        )
    return chosen, numbers.pop()


def destination(peer, policy):
    """One egress peer in words: the pods it selects and the namespace they are
    in, or an address block and what it excepts."""
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
                f"an egress peer on {policy} names namespaces by something other than "
                f"{NAMESPACE_LABEL} alone, and this gate cannot say which it reaches"
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
            f"an egress peer on {policy} is neither an address block nor pods named by "
            "their labels, and this gate cannot say what it reaches: a peer naming no "
            "label reaches every pod in its namespace"
        )
    return f"{written(selector['matchLabels'])} in {namespace}"


def reach(policy):
    """Everything one policy's egress admits, as (who, protocol, port)."""
    name = policy["metadata"]["name"]
    found = set()
    for arm in policy["spec"].get("egress") or []:
        peers = arm.get("to") or []
        ports = arm.get("ports") or []
        if not peers or not ports:
            refuse(
                f"an egress arm on {name} names no destination or no port, so it admits "
                "every one of whichever it leaves out"
            )
        for port in ports:
            number = port.get("port")
            if "endPort" in port or isinstance(number, bool) or not isinstance(number, int):
                refuse(
                    f"an egress arm on {name} names the port {number!r} or a range from "
                    "it, and this gate reads one number at a time"
                )
            for peer in peers:
                found.add((destination(peer, name), port.get("protocol", "TCP"), number))
    return found


def spoken(triples):
    return "; ".join(f"{who} on {protocol} {port}" for who, protocol, port in sorted(triples))


def database(documents):
    plane = one(documents, "Deployment", PLANE[0], CONTROL)
    pod = plane["spec"]["template"]["spec"]
    labels = plane["spec"]["template"]["metadata"].get("labels") or {}
    env = environment(documents, PLANE)

    # 1. The URL: one login, one group role set by one option, PostgreSQL's
    #    Service and its database -- and no second URL beside it, which would
    #    be a second connection this gate held to nothing.
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

    # 2. The password. The kubelet expands `$(NAME)` only from a variable
    #    defined above the one naming it, so a password defined below the URL
    #    leaves the reference in it as text, which authenticates as nothing.
    names = [item["name"] for item in env]
    if names.count(PASSWORD) != 1 or names.index(PASSWORD) > names.index(DATABASE_URL):
        refuse(
            f"{PASSWORD} is not defined once and above {DATABASE_URL}, so the kubelet "
            "leaves the reference to it in the URL as the text it is written as"
        )
    handed = secrets_handed(pod)
    wanted = (PASSWORD, *CREDENTIAL)
    if wanted not in handed:
        refuse(
            f"{PASSWORD} is not the key {CREDENTIAL[1]} of the Secret {CREDENTIAL[0]}, "
            "which is the password the host generates for the plane's login role"
        )
    others = sorted(
        f"{secret}/{key} as {name}" for name, secret, key in handed if (name, secret, key) != wanted
    )
    if others:
        refuse(
            f"the plane's pod is also handed {', '.join(others)}: its database password "
            "is the one Secret key it has a use for"
        )

    # 3. Admission at the server's end: the label, and then that the policy
    #    asking for it admits a pod so labelled on the port the kernel matches.
    #    A bare podSelector there is scoped to `chuggy`, where this pod is.
    key, value = POSTGRES_CLIENT
    if labels.get(key) != value:
        refuse(
            f"the plane's pod does not carry {key}={value}, so {POSTGRES_POLICY} refuses "
            "it the database: every connection is refused, the plane is never ready, and "
            "nothing anywhere says the label is why"
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
            f"TCP {landed}, which is where {DATABASE_URL} lands, so the label above "
            "admits nothing"
        )

    # 4. And at this end. Policies are additive, so what bounds the pod is
    #    every one that isolates it for egress and not the one named for it:
    #    `policyTypes` is authoritative when present, and a podSelector naming
    #    another workload confines that one and leaves this one unbounded.
    isolating = [
        document
        for document in documents
        if document.get("kind") == "NetworkPolicy"
        and document["metadata"].get("namespace") == CONTROL
        and isolates_for_egress(document)
        and selects(document["spec"].get("podSelector") or {}, labels, document["metadata"]["name"])
    ]
    if EGRESS_POLICY not in [document["metadata"]["name"] for document in isolating]:
        refuse(
            f"{EGRESS_POLICY} does not isolate the plane's pod for egress: it names no "
            "Egress in its policyTypes or its podSelector selects another pod, so its "
            "arms bound nothing here"
        )
    reached = set()
    for document in isolating:
        reached |= reach(document)
    server = (f"{written(chosen)} in {CONTROL}", "TCP", landed)
    if server not in reached:
        refuse(
            f"no egress arm reaches {spoken({server})}, which is where {DATABASE_URL} "
            "lands, so the plane's pod is refused its database and is never ready"
        )
    wider = reached - BEFORE - {server}
    if wider:
        refuse(
            f"the plane's pod may also reach {spoken(wider)}: what it reached before it "
            "had a database and PostgreSQL beside that are the whole of where it goes, "
            "and this gate is the record of it"
        )
    lost = BEFORE - reached
    if lost:
        refuse(
            f"the plane's pod no longer reaches {spoken(lost)}, which it reached before "
            "it had a database, and this gate is the record of where it goes"
        )

    # 5. A rollout starts the new pod beside the old one and removes the old
    #    one only when the new one is ready, which the API server's defaults
    #    give at any number of replicas. `Recreate`, or a rolling update told
    #    it may take a pod away first, serves nothing while a new pod waits on
    #    a login role that does not exist yet.
    strategy = plane["spec"].get("strategy") or {}
    unavailable = (strategy.get("rollingUpdate") or {}).get("maxUnavailable")
    if strategy.get("type", "RollingUpdate") != "RollingUpdate" or unavailable not in (None, 0):
        refuse(
            f"{PLANE[0]} is rolled by {strategy!r}, which may remove the old pod before "
            "the new one is ready: a plane that cannot reach its database yet would then "
            "serve nothing, where the default strategy leaves the old pod serving"
        )


def main():
    if len(sys.argv) != 2:
        refuse("usage: access-plane.py RENDERED_MANIFEST")
    documents = [
        document for document in yaml.safe_load_all(Path(sys.argv[1]).read_text()) if document
    ]
    api = environment(documents, API)
    plane = environment(documents, PLANE)

    for held, original, copy in HELD:
        wanted = literal(api, API, original)
        given = literal(plane, PLANE, copy)
        if given != wanted:
            refuse(
                f"{copy} is {given!r} and {original} is {wanted!r}: the plane holds a "
                f"token to another {held} than the API does, so it answers 401 to a token "
                "the API accepts and the console signs that person out"
            )

    database(documents)


if __name__ == "__main__":
    main()
