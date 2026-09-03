#!/usr/bin/env python3
"""Refuse a rendered cluster whose session pods are mislabelled or misadmitted.

Every assertion here is made against the rendered objects and against the labels
the scheduler is configured to place, never against the source files: the same
label is written in one manifest and selected in three others, and each of those
reads correctly on its own while the pod is unisolated.

BOTH ENDS OF EVERY REACH, AND THE PORT IS THE EASY HALF. A policy's ports can be
exactly right while each selector beside them names a pod that does not exist --
a container name, a Service name, a rename that landed on one side. That failure
is silent in the direction that matters: the pod is Running, the placement
succeeded, the far end admits what it should, and the packets are simply dropped.
So every egress arm is resolved, by whichever of two rules its destination
admits, and neither expectation is a label literal:

  * A destination this directory DECLARES A POD FOR -- the worker plane, the API
    -- is resolved twice over: the arm's selector must pick a real pod template
    out of the render, and the pods it picks must be exactly the pods the policy
    standing over that workload protects. The two ends of one reach then cannot
    drift apart while each reads correctly alone.
  * A destination this directory declares NO POD FOR -- `kube-system`'s CoreDNS,
    and the public internet, neither of which is ours -- has nothing to resolve
    against, so the arm's whole peer list must EQUAL the `chuggy-workers` arm
    reaching the same place on the same ports. That is the one other statement in
    this tree of where those are, and comparing against it keeps a literal out of
    this file. It is a relative expectation and worth reading as one: an edit that
    changes both arms together widens both, and the two hunks are adjacent.

AN ABSENT FIELD IS THE WIDEST THING AN ARM CAN SAY, in both halves and in the
same way. `ports` absent admits every port; `to` absent reaches every
destination; a `podSelector` absent inside a peer selects every pod in the
namespace. Each of those is refused by name rather than iterated over zero times,
because a loop that finds nothing to check reads exactly like a loop that checked
and was satisfied.

WHAT THIS GATE CANNOT RESOLVE IT REFUSES rather than passes. A namespaceSelector
on a label other than `kubernetes.io/metadata.name`, and a podSelector with
matchExpressions alone, are both legal Kubernetes and both outside what is
evaluated here; each gets a refusal saying so, so an unsupported shape is a
finding to answer instead of a silence to trust.

A REACH IS ALSO WRITTEN AS A URL AND AS A GRANT, and those halves fail the same
silent way. Two more pairings are held here for that reason, and neither is a
literal either:

  * The origin the session's tools reach the API at is resolved through the
    Service it addresses -- its selector, and its port through the container port
    that Service's targetPort names -- and the pods it lands on must be exactly
    the pods one egress arm permits on exactly that port. An origin naming a
    destination no arm permits is a tool that hangs, and NetworkPolicy is matched
    after the ClusterIP is translated away, so an arm copied from the URL's own
    number is wrong for a Service that renames its port.
  * A checkout takes a reach, a credential and a repository map, and this file
    already holds the reach. So the map a session resolves against must be the
    map a worker resolves against -- one site, one statement of which
    repositories exist -- every credential the session policy grants must be one
    the credential mounts carry, or the placement is denied, and at least one
    repository in that map must have its credential granted, or the arm above is
    a permission for a clone that cannot authenticate. A mirror is that same
    pairing once more: it is what a session clones in place of the binding, so
    it must be in that map and its credential must be granted.

THE IMAGE A SESSION RUNS ON IS WRITTEN TWICE and held nowhere else. It is
admitted in `CHUG_SCHEDULER_ADMITTED_IMAGES` and pinned in
`CHUG_SCHEDULER_SESSION_POLICY`, and every other check over these two is a
`grep -F` for one digest, which answers whether a string is in a file and never
how many times or where -- so either site could carry a digest the other does
not while that line stayed green. Held here, over the parsed render, in the
direction a release moves them: the pinned image is admitted, and it is the
newest admission.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

WORK = "chuggy-work"
CONTROL = "chuggy"
SESSION_LABELS_VARIABLE = "CHUG_SCHEDULER_SESSION_LABELS"
SESSION_API_URL_VARIABLE = "CHUG_SCHEDULER_SESSION_API_URL"
SESSION_ENVIRONMENT_VARIABLE = "CHUG_SCHEDULER_SESSION_ENVIRONMENT"
SESSION_POLICY_VARIABLE = "CHUG_SCHEDULER_SESSION_POLICY"
ADMITTED_IMAGES_VARIABLE = "CHUG_SCHEDULER_ADMITTED_IMAGES"
WORKER_ENVIRONMENT_VARIABLE = "CHUG_SCHEDULER_WORKER_ENVIRONMENT"
CREDENTIAL_MOUNTS_VARIABLE = "CHUG_SCHEDULER_WORKER_CREDENTIAL_MOUNTS"
REPOSITORIES_VARIABLE = "CHUG_WORKER_REPOSITORIES"

# Where a session pod may go, as (protocol, port). A session takes its turns and
# writes its transcript over the worker plane, reaches the API as an ordinary
# client, clones its project's repository from the in-cluster git service,
# resolves names, and talks to the model over public HTTPS. PostgreSQL is absent
# because a session makes no scratch database -- and this set is exact, so
# gaining one is a finding rather than a silent widening.
SESSION_EGRESS = {
    ("UDP", 53),
    ("TCP", 53),
    ("TCP", 3001),
    ("TCP", 3000),
    ("TCP", 443),
    ("TCP", 8080),
}

# The two destinations a session's egress names by label, each paired with the
# policy that stands in front of that same workload. The pairing is what makes
# the port assertion mean something: a port set can be exactly right while every
# selector beside it names a pod that does not exist, and an egress arm selecting
# nothing is denied traffic silently -- the pod is Running, the placement
# succeeded, and the far end is fine. So each arm is resolved twice, against the
# pod templates this directory declares and against the policy protecting them,
# and neither expectation is a literal label written here.
SESSION_EGRESS_TARGETS = {
    frozenset({("TCP", 3001)}): "chuggy-worker-plane-ingress",
    frozenset({("TCP", 3000)}): "chuggy-api-admits-traefik-and-the-selector",
}

POD_TEMPLATE_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet")


def refuse(message):
    raise SystemExit(f"session placement: {message}")


def objects(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


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


def container(deployment, name):
    for entry in deployment["spec"]["template"]["spec"]["containers"]:
        if entry["name"] == name:
            return entry
    refuse(f"{deployment['metadata']['name']} has no container {name}")


def variable(entry, name):
    for item in entry.get("env", []):
        if item["name"] == name:
            if "value" not in item:
                refuse(f"{name} is not a literal value")
            return item["value"]
    return None


def ports(rule):
    return {(port.get("protocol", "TCP"), port["port"]) for port in rule.get("ports", [])}


def peer_admits(peer, namespace, labels):
    """Whether one `from`/`to` peer selects a pod in `namespace` carrying `labels`.

    A peer's namespaceSelector and podSelector are ANDed, and an absent
    namespaceSelector means the policy's own namespace -- which is the reading
    that made a `chuggy-work` pod carrying `chuggy.dev/api-client` reachable by
    nothing at all.
    """
    if "ipBlock" in peer:
        return False
    namespaces = peer.get("namespaceSelector")
    if namespaces is None:
        if namespace != peer["__policyNamespace"]:
            return False
    else:
        wanted = namespaces.get("matchLabels", {}).get("kubernetes.io/metadata.name")
        if wanted != namespace:
            return False
    pods = peer.get("podSelector")
    if pods is None:
        return True
    selected = pods.get("matchLabels", {})
    return all(labels.get(key) == value for key, value in selected.items())


def admits(policy, direction, namespace, labels, protocol, port):
    for rule in policy["spec"].get(direction, []) or []:
        peers = rule.get("from" if direction == "ingress" else "to", [])
        for peer in peers:
            peer = {**peer, "__policyNamespace": policy["metadata"]["namespace"]}
            if peer_admits(peer, namespace, labels) and (protocol, port) in ports(rule):
                return True
    return False


def pod_templates(documents):
    """Every pod this directory declares, as (namespace, labels).

    This is the universe a destination selector can be resolved against. A
    namespace absent from it declares no pod here -- `kube-system`, whose CoreDNS
    is the cluster's, and `chuggy-work`, whose pods the scheduler places at
    runtime -- and a selector aimed there is checked another way.
    """
    found = []
    for document in documents:
        if document.get("kind") in POD_TEMPLATE_KINDS:
            template = document["spec"]["template"]["metadata"]
            found.append((document["metadata"].get("namespace"), template.get("labels", {})))
        elif document.get("kind") == "Pod":
            metadata = document["metadata"]
            found.append((metadata.get("namespace"), metadata.get("labels", {})))
    return found


def peer_namespace(peer, own):
    """The namespace a peer names, or the policy's own where it names none."""
    namespaces = peer.get("namespaceSelector")
    if namespaces is None:
        return own
    return namespaces.get("matchLabels", {}).get("kubernetes.io/metadata.name")


def pods_selected(templates, namespace, selector):
    return [
        labels
        for space, labels in templates
        if space == namespace
        and all(labels.get(key) == value for key, value in selector.items())
    ]


def json_variable(entry, name):
    """One env value parsed as JSON, refused rather than skipped where it is absent."""
    raw = variable(entry, name)
    if raw is None:
        refuse(f"the scheduler names no {name}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        refuse(f"{name} is not JSON: {error}")


def cluster_service(url, name):
    """The (namespace, service) a cluster-local origin addresses.

    Only `<service>.<namespace>.svc.cluster.local` is resolvable here, with or
    without the root's trailing dot. Anything else -- an IP, an external name, a
    bare Service name relying on the pod's search path -- is refused rather than
    guessed at, because a destination this file cannot resolve is one it cannot
    hold an egress arm against.
    """
    host = (url.hostname or "").rstrip(".")
    suffix = ".svc.cluster.local"
    if not host.endswith(suffix):
        refuse(f"{name} names {host}, which is not a <service>.<namespace>{suffix} address")
    parts = host[: -len(suffix)].split(".")
    if len(parts) != 2:
        refuse(f"{name} names {host}, which is not a <service>.<namespace>{suffix} address")
    return parts[1], parts[0]


def service_pod_port(documents, templates, service, wanted, name):
    """The container port behind a Service port, and the pods that publish it.

    A NetworkPolicy is evaluated against the destination pod after the ClusterIP
    is translated away, so the port an egress arm must permit is this one and not
    the Service's. A named targetPort is resolved on the containers of the pods
    the Service selects, which is what a rename on either side fails.
    """
    selector = service["spec"].get("selector")
    if not selector:
        refuse(f"the Service {name} addresses selects no pod by label")
    namespace = service["metadata"].get("namespace")
    selected = pods_selected(templates, namespace, selector)
    if not selected:
        refuse(f"the Service {name} addresses selects {selector} in {namespace}, which no declared pod carries")
    entries = [port for port in service["spec"].get("ports", []) if port.get("port") == wanted]
    if len(entries) != 1:
        refuse(f"the Service {name} addresses publishes no single port {wanted}")
    target = entries[0].get("targetPort", wanted)
    if isinstance(target, int):
        return target, selected
    published = {
        port.get("name"): port.get("containerPort")
        for document in documents
        if document.get("kind") in POD_TEMPLATE_KINDS
        and document["metadata"].get("namespace") == namespace
        and all(
            document["spec"]["template"]["metadata"].get("labels", {}).get(key) == value
            for key, value in selector.items()
        )
        for container in document["spec"]["template"]["spec"]["containers"]
        for port in container.get("ports", [])
    }
    if target not in published:
        refuse(f"the Service {name} addresses names targetPort {target}, which its pods do not publish")
    return published[target], selected


def protects(policy):
    """The (namespace, selector) pair naming the workload a policy stands over."""
    return (
        policy["metadata"].get("namespace"),
        policy["spec"]["podSelector"].get("matchLabels", {}),
    )


def main():
    if len(sys.argv) != 2:
        refuse("usage: session-placement.py RENDERED_MANIFEST")
    documents = objects(sys.argv[1])

    scheduler = one(documents, "Deployment", "chuggy-scheduler", CONTROL)
    raw = variable(container(scheduler, "scheduler"), SESSION_LABELS_VARIABLE)
    if raw is None:
        refuse(f"the scheduler names no {SESSION_LABELS_VARIABLE}")
    labels = json.loads(raw)
    if not isinstance(labels, dict) or not labels:
        refuse(f"{SESSION_LABELS_VARIABLE} is not a non-empty object")

    # 1. A session pod is selected by its own policy, and that policy is the one
    #    that grants it nothing inbound.
    sessions = one(documents, "NetworkPolicy", "chuggy-sessions", WORK)
    selector = sessions["spec"]["podSelector"].get("matchLabels", {})
    if not selector:
        refuse("chuggy-sessions selects every pod in the namespace")
    missing = {key for key, value in selector.items() if labels.get(key) != value}
    if missing:
        refuse(f"placed session pods do not carry {sorted(missing)}, so no policy selects them")
    if set(sessions["spec"].get("policyTypes", [])) != {"Ingress", "Egress"}:
        refuse("chuggy-sessions does not isolate both directions")
    if sessions["spec"].get("ingress") != []:
        refuse("chuggy-sessions admits ingress; a session is never connected to")

    # 2. Where it may go: every arm held to an exact set of
    #    ports AND an exact set of destinations. Both halves are load-bearing and
    #    an absent one is the widest thing the object can say: an arm with no
    #    `ports` admits every port, and an arm with no `to` reaches every
    #    destination. Neither expectation below is a literal written here.
    templates = pod_templates(documents)
    workers = one(documents, "NetworkPolicy", "chuggy-workers", WORK)
    reached = set()
    for rule in sessions["spec"].get("egress", []):
        if not rule.get("ports"):
            refuse("a chuggy-sessions egress arm names no port, so it admits every port")
        if not rule.get("to"):
            refuse("a chuggy-sessions egress arm names no destination, so it reaches everything")
        opened = ports(rule)
        reached |= opened
        for peer in rule["to"]:
            # An ipBlock is the honest exception: the model is on the public
            # internet and no object in this cluster stands for it. The arm
            # carrying one is still held to an exact peer set below.
            if "ipBlock" in peer:
                continue
            namespace = peer_namespace(peer, WORK)
            if namespace is None:
                refuse(
                    f"a chuggy-sessions arm for {sorted(opened)} names a namespaceSelector "
                    "on something other than kubernetes.io/metadata.name, which this gate "
                    "cannot resolve to a namespace"
                )
            pods = peer.get("podSelector") or {}
            chosen = pods.get("matchLabels") or {}
            if not chosen and pods.get("matchExpressions"):
                refuse(
                    f"a chuggy-sessions arm for {sorted(opened)} selects pods in {namespace} "
                    "by matchExpressions alone, which this gate cannot resolve"
                )
            if not chosen:
                # An absent podSelector, an empty one and an empty `matchLabels`
                # are one shape to the cluster and get one message.
                refuse(
                    f"a chuggy-sessions arm for {sorted(opened)} names no pod labels, "
                    f"so it selects every pod in {namespace}"
                )
            # A namespace this directory declares pods in: the selector must
            # actually pick one out. This is what an arm pointed at a container
            # name, a Service name or a rename fails.
            if any(space == namespace for space, _ in templates) and not pods_selected(
                templates, namespace, chosen
            ):
                refuse(
                    f"a chuggy-sessions arm for {sorted(opened)} selects "
                    f"{chosen} in {namespace}, which no declared pod carries"
                )
        target = SESSION_EGRESS_TARGETS.get(frozenset(opened))
        if target is None:
            # CoreDNS and the public internet are not this directory's to declare,
            # so the exact peer set for those arms is taken from the sibling arm in
            # `chuggy-workers` reaching the same place on the same ports -- the one
            # other statement in this tree of where that destination is.
            siblings = [
                arm.get("to")
                for arm in workers["spec"].get("egress", [])
                if ports(arm) == opened
            ]
            if rule["to"] not in siblings:
                refuse(
                    f"the chuggy-sessions arm for {sorted(opened)} names a destination set "
                    "no chuggy-workers arm on the same ports names"
                )
            continue
        # The workload it names is the one the far-end policy stands over, so the
        # two ends of a reach cannot drift apart while each reads right alone.
        if any("ipBlock" in peer for peer in rule["to"]):
            refuse(
                f"the chuggy-sessions arm for {sorted(opened)} reaches an address range "
                f"as well as the pods {target} stands over"
            )
        space, guarded = protects(one(documents, "NetworkPolicy", target, CONTROL))
        here = [
            selected
            for peer in rule["to"]
            for selected in pods_selected(
                templates,
                peer_namespace(peer, WORK),
                peer["podSelector"]["matchLabels"],
            )
        ]
        if here != pods_selected(templates, space, guarded):
            refuse(
                f"the chuggy-sessions arm for {sorted(opened)} does not select exactly the "
                f"pods {target} stands over"
            )
    if reached != SESSION_EGRESS:
        refuse(f"chuggy-sessions egress is {sorted(reached)}, expected {sorted(SESSION_EGRESS)}")

    # 3. No OTHER policy in the namespace selects a session. NetworkPolicies are
    #    additive, so naming `chuggy-workers` alone would leave a third policy
    #    added later free to widen a session silently. A policy carrying no rule
    #    widens nothing -- a namespace default-deny is exactly that shape -- but
    #    it is still a second object deciding what selects a session, and this
    #    gate is where that is recorded, so it is refused too and told apart.
    for document in documents:
        if document.get("kind") != "NetworkPolicy":
            continue
        if document["metadata"].get("namespace") != WORK:
            continue
        name = document["metadata"]["name"]
        if name == "chuggy-sessions":
            continue
        other = document["spec"]["podSelector"].get("matchLabels", {})
        if not all(labels.get(key) == value for key, value in other.items()):
            continue
        if document["spec"].get("ingress") or document["spec"].get("egress"):
            refuse(f"a session pod is also selected by {name} and inherits what it permits")
        refuse(
            f"a session pod is also selected by {name}, which permits nothing; a baseline "
            "deny over a session is a deliberate change and this gate is its record"
        )

    # 4. Both reaches a session's egress permits are admitted at the other end.
    plane = one(documents, "NetworkPolicy", "chuggy-worker-plane-ingress", CONTROL)
    if not admits(plane, "ingress", WORK, labels, "TCP", 3001):
        refuse("the worker plane admits no session pod, so no turn is ever claimed")
    api = one(
        documents, "NetworkPolicy", "chuggy-api-admits-traefik-and-the-selector", CONTROL
    )
    if not admits(api, "ingress", WORK, labels, "TCP", 3000):
        refuse("the API admits no session pod, so its egress arm for 3000 reaches nothing")

    # 5. And the one reach it does not permit is refused at the other end too,
    #    so the absence is a boundary rather than a value nobody set.
    postgres = one(documents, "NetworkPolicy", "postgres-admits-labelled-clients", CONTROL)
    if admits(postgres, "ingress", WORK, labels, "TCP", 5432):
        refuse("PostgreSQL admits a session pod, which makes no scratch database")

    # 6. The origin a session's tools reach the API at is a destination its
    #    egress permits, resolved the whole way: URL to Service, Service port to
    #    the container port its pods publish, and that port to the one arm whose
    #    peers select exactly those pods. Written as a URL in one variable and as
    #    a peer in another file, this is the pairing that reads right on each
    #    side while every tool call hangs.
    scheduled = container(scheduler, "scheduler")
    origin = variable(scheduled, SESSION_API_URL_VARIABLE)
    if origin is None:
        refuse(f"the scheduler names no {SESSION_API_URL_VARIABLE}, which the launcher requires")
    url = urlsplit(origin)
    if url.scheme not in ("http", "https"):
        refuse(f"{SESSION_API_URL_VARIABLE} is not an http or https origin")
    if url.username or url.password:
        refuse(f"{SESSION_API_URL_VARIABLE} carries credentials")
    if url.path not in ("", "/") or url.query or url.fragment:
        refuse(
            f"{SESSION_API_URL_VARIABLE} is not an origin; the pod's client builds the "
            "versioned path onto it"
        )
    space, named = cluster_service(url, SESSION_API_URL_VARIABLE)
    served = url.port or (443 if url.scheme == "https" else 80)
    port, behind = service_pod_port(
        documents,
        templates,
        one(documents, "Service", named, space),
        served,
        SESSION_API_URL_VARIABLE,
    )
    permitted = [
        rule
        for rule in sessions["spec"].get("egress", [])
        if ("TCP", port) in ports(rule)
        and [
            selected
            for peer in rule["to"]
            if "ipBlock" not in peer
            for selected in pods_selected(
                templates, peer_namespace(peer, WORK), peer["podSelector"]["matchLabels"]
            )
        ]
        == behind
    ]
    if len(permitted) != 1:
        refuse(
            f"{SESSION_API_URL_VARIABLE} resolves to {named}.{space} on pod port {port}, which "
            f"{len(permitted)} chuggy-sessions arms permit; exactly one must"
        )

    # 7. A checkout is a reach, a credential and a map, and step 2 holds only the
    #    reach. The map is the worker's -- one site, one statement of which
    #    repositories exist here -- every credential granted is one the mounts
    #    carry, since the launcher denies a slot they do not, and something in
    #    that map is clonable, or the git arm above permits a clone that cannot
    #    authenticate.
    policy = json_variable(scheduled, SESSION_POLICY_VARIABLE)
    granted = set(policy.get("grant", {}).get("credentials", []))
    mounts = set(json_variable(scheduled, CREDENTIAL_MOUNTS_VARIABLE))
    ungrantable = granted - mounts
    if ungrantable:
        refuse(
            f"{SESSION_POLICY_VARIABLE} grants {sorted(ungrantable)}, which "
            f"{CREDENTIAL_MOUNTS_VARIABLE} does not mount, so every placement is denied"
        )
    sessions_map = json_variable(scheduled, SESSION_ENVIRONMENT_VARIABLE).get(REPOSITORIES_VARIABLE)
    workers_map = json_variable(scheduled, WORKER_ENVIRONMENT_VARIABLE).get(REPOSITORIES_VARIABLE)
    if sessions_map is None:
        refuse(
            f"{SESSION_ENVIRONMENT_VARIABLE} carries no {REPOSITORIES_VARIABLE}, so a session "
            "placed with a repository refuses to resolve it"
        )
    if workers_map is None:
        refuse(f"{WORKER_ENVIRONMENT_VARIABLE} carries no {REPOSITORIES_VARIABLE}")
    # Parsed rather than compared as text: the two are JSON documents inside JSON
    # strings, and a difference in their whitespace is not a difference in what
    # they say.
    repositories = json.loads(sessions_map)
    if repositories != json.loads(workers_map):
        refuse(
            f"the session's {REPOSITORIES_VARIABLE} is not the worker's, so the two kinds of pod "
            "answer differently which repositories exist on this site"
        )
    if not any(entry.get("credential") in granted for entry in repositories.values()):
        refuse(
            f"{SESSION_POLICY_VARIABLE} grants the credential of no repository in "
            f"{REPOSITORIES_VARIABLE}, so no checkout can authenticate"
        )

    # 8. A mirror is the third half of the same reach: what a session clones is
    #    the binding put through this map, so a value the map above does not
    #    carry is a session placed against a remote the image cannot resolve, and
    #    a value whose credential is ungranted is one it can resolve and cannot
    #    authenticate. The keys are project bindings, and no project is declared
    #    here, so nothing is asserted about them.
    for bound, mirror in (policy.get("mirrors") or {}).items():
        entry = repositories.get(mirror)
        if entry is None:
            refuse(
                f"{SESSION_POLICY_VARIABLE} mirrors {bound} at {mirror}, which "
                f"{REPOSITORIES_VARIABLE} does not carry, so the session cannot resolve it"
            )
        if entry.get("credential") not in granted:
            refuse(
                f"{SESSION_POLICY_VARIABLE} mirrors {bound} at {mirror}, whose credential "
                f"{entry.get('credential')!r} it does not grant, so that clone cannot authenticate"
            )

    # 9. The image a session is placed on is one the scheduler admits, and it is
    #    the newest admission. Both halves are written in this one file and
    #    nothing in either repository held them together: `tests/development-worker`
    #    greps each digest, and a `grep -F` answers whether a string is in a file
    #    and never how many times or where, so either site alone could carry a
    #    digest the other does not while that line stayed satisfied. Newest and
    #    not merely present, because admission order is release order: a policy
    #    on an older admitted image is a release that moved one site and not the
    #    other.
    admitted = json_variable(scheduled, ADMITTED_IMAGES_VARIABLE)
    images = [entry.get("image") for entry in admitted]
    if policy.get("image") not in images:
        refuse(
            f"{SESSION_POLICY_VARIABLE} places sessions on an image "
            f"{ADMITTED_IMAGES_VARIABLE} does not admit, so every placement is denied"
        )
    if policy.get("image") != images[-1]:
        refuse(
            f"{SESSION_POLICY_VARIABLE} places sessions on an image older than the newest "
            f"{ADMITTED_IMAGES_VARIABLE} entry, so one of the two was repinned without the other"
        )


if __name__ == "__main__":
    main()
