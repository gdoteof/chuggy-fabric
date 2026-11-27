#!/usr/bin/env python3
"""Refuse a Headlamp that would see more than `view`, a binding that would give
anything to a member it does not name, an API server that would trust more
than Headlamp's id_tokens, or a sign-in whose halves disagree.

Headlamp is written in four places that do not read each other: the HelmRelease
and the binding under cluster/headlamp/, the authenticator gtr hands its API
server, and gtr's tunnel hostnames. Each reads correctly alone. What this holds,
each against the render or the host's built configuration and never a file:

- THE SERVICEACCOUNT HOLDS NOTHING. The chart binds its ServiceAccount to
  `cluster-admin` unless `clusterRoleBinding.create` is false, and
  `unsafeUseServiceAccountToken` sends every person's request as it; the first
  must be said false and the second must not be said true. No binding in the
  rendered cluster names a ServiceAccount of `headlamp`, and Helm management
  stays off.
- A PERSON IS `view` BY NAME, OR NOTHING. A person is a subject under
  `chuggy:`. One ClusterRoleBinding of ClusterRole `view` names people, each
  subject of it a User `chuggy:<Kratos identity id>`, and no other binding
  names one.
- NO BINDING NAMES EVERY MEMBER: not `chuggy:members`, which every person
  signed in is given, nor `system:authenticated` or `system:unauthenticated`,
  which take in every member and more. Every binding under cluster/ is read:
  the rendered cluster, the build system's render, Tekton's vendored release
  among it, and Flux's components, which are applied as written; cluster/flux/
  renders layers and sources alone, which tests/flux-layers.py holds. The one
  exception is Tekton's `tekton-pipelines-info`, held to what it gives every
  authenticated caller: `get` of one ConfigMap, which holds Tekton's version
  and nothing else.
- THE AUTHENTICATOR IS HEADLAMP'S ALONE. One JWT authenticator, whose issuer
  is the issuer Headlamp is configured with and whose audiences are exactly
  Headlamp's client id: an audience dropped or widened lets another client's
  tokens in. The username is `sub` under `chuggy:`, and the groups expression is
  the constant [`chuggy:members`], which no binding names. The file is the one
  the flag names, and a change to it restarts k3s.
- A HOST THAT NAMES NO AUTHENTICATOR GETS NO FLAG AND NO FILE.
- THE SIGN-IN'S HALVES AGREE. Every `-oidc-*` argument the chart builds is
  built from a variable this release sets, the client secret from
  `headlamp-oidc`'s `OIDC_CLIENT_SECRET` and nothing else from a Secret; the
  callback is on the Ingress's host, and that host is in gtr's tunnel
  hostnames.

WHAT THIS CANNOT SEE: the chart's own render. The flags are the chart's, from
templates/deployment.yaml at the pinned version, and the variables they read
are held here; a chart bumped without that template read again is a version
this check refuses rather than believes.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

NAMESPACE = "headlamp"
RELEASE = "headlamp"
CHART = ("headlamp", "0.46.0")
GROUP = "chuggy:members"
USERNAME_PREFIX = "chuggy:"
SECRET = ("headlamp-oidc", "OIDC_CLIENT_SECRET")
CALLBACK_PATH = "/oidc-callback"
CONFIG_PATH = "/etc/rancher/k3s/authentication-config.yaml"
FLAG = f"--kube-apiserver-arg=authentication-config={CONFIG_PATH}"
FLAG_PREFIX = "--kube-apiserver-arg=authentication-config="

# The variables templates/deployment.yaml at CHART's version turns into an
# `-oidc-*` argument from its `env` arm, each by `$(NAME)`.
VARIABLES = (
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_ISSUER_URL",
    "OIDC_SCOPES",
    "OIDC_CALLBACK_URL",
    "OIDC_USE_PKCE",
    "OIDC_AUTO_LOGIN",
)
BINDINGS = ("ClusterRoleBinding", "RoleBinding")
RBAC = "rbac.authorization.k8s.io"
VIEW = {"apiGroup": RBAC, "kind": "ClusterRole", "name": "view"}
# A Kratos identity id, which is what follows the prefix in a person's name.
PERSON = re.compile(re.escape(USERNAME_PREFIX) + r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# The groups that take in every member signed in.
EVERY_MEMBER = (GROUP, "system:authenticated", "system:unauthenticated")
# Tekton's binding of every authenticated caller, and the version it reads.
TEKTON_INFO = ("tekton-pipelines", "tekton-pipelines-info")
TEKTON_VERSION = "pipelines-info"


def refuse(message):
    raise SystemExit(f"headlamp: {message}")


def documents_in(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def one(documents, kind, name, namespace=None):
    found = [
        document
        for document in documents
        if document.get("kind") == kind
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == namespace
    ]
    if len(found) != 1:
        refuse(f"expected one {kind} {namespace or ''}/{name}, found {len(found)}")
    return found[0]


def flags_of(extra):
    return extra if isinstance(extra, list) else extra.split()


def release_values(layer):
    release = one(layer, "HelmRelease", RELEASE, NAMESPACE)
    chart = release["spec"]["chart"]["spec"]
    if (chart.get("chart"), str(chart.get("version"))) != CHART:
        refuse(
            f"the release is chart {chart.get('chart')} {chart.get('version')}, not "
            f"{CHART[0]} {CHART[1]}: read that chart's templates/deployment.yaml and "
            "clusterrolebinding.yaml against these values, then move CHART here"
        )
    retries = ((release["spec"].get("install") or {}).get("remediation") or {}).get("retries")
    if not isinstance(retries, int) or retries >= 0:
        refuse(
            f"install.remediation.retries is {retries!r}, not negative: the first install "
            "fails until headlamp-oidc is made by hand, and with a bounded count the "
            "release is left Stalled after the Secret exists"
        )
    values = release["spec"].get("values") or {}

    if (values.get("clusterRoleBinding") or {}).get("create") is not False:
        refuse(
            "clusterRoleBinding.create is not false, and the chart's default binds "
            "Headlamp's ServiceAccount to cluster-admin"
        )
    config = values.get("config") or {}
    if config.get("unsafeUseServiceAccountToken") not in (None, False):
        refuse("config.unsafeUseServiceAccountToken is on: every person would act as the ServiceAccount")
    if config.get("enableHelm") not in (None, False):
        refuse("config.enableHelm is on")
    oidc = config.get("oidc") or {}
    if (oidc.get("secret") or {}).get("create") is not False:
        refuse("config.oidc.secret.create is not false, so the chart makes an OIDC Secret of its own")
    if (oidc.get("externalSecret") or {}).get("enabled"):
        refuse(
            "config.oidc.externalSecret is enabled, whose arm passes $(OIDC_*) literally "
            "for a key its Secret lacks"
        )
    if not re.search(r"@sha256:[0-9a-f]{64}$", str((values.get("image") or {}).get("tag", ""))):
        refuse("the image is not pinned by digest")
    return values


def environment(values):
    env = {}
    for entry in values.get("env") or []:
        if entry["name"] in env:
            refuse(f"env sets {entry['name']} twice")
        env[entry["name"]] = entry
    for name in VARIABLES:
        if name not in env:
            refuse(f"env does not set {name}, which an -oidc-* argument names")
    for name, entry in env.items():
        if name == SECRET[1]:
            continue
        if "valueFrom" in entry or not isinstance(entry.get("value"), str):
            refuse(f"env {name} is not a plain value; only {SECRET[1]} comes from a Secret")
    reference = (env[SECRET[1]].get("valueFrom") or {}).get("secretKeyRef") or {}
    if (reference.get("name"), reference.get("key")) != SECRET or reference.get("optional"):
        refuse(f"env {SECRET[1]} is not the required key {SECRET[1]} of Secret {SECRET[0]}")
    for flag in ("OIDC_USE_PKCE", "OIDC_AUTO_LOGIN"):
        if env[flag]["value"] != "true":
            refuse(f"env {flag} is not \"true\"")
    return {name: entry.get("value") for name, entry in env.items()}


def tekton_info_holds(objects, document, name):
    """Tekton's binding of every authenticated caller gives it Tekton's version alone."""
    namespace, role = TEKTON_INFO
    if document["roleRef"] != {"apiGroup": RBAC, "kind": "Role", "name": role} or document["subjects"] != [
        {"apiGroup": RBAC, "kind": "Group", "name": "system:authenticated"}
    ]:
        refuse(
            f"{name} binds {json.dumps(document['subjects'])} to {json.dumps(document['roleRef'])}, "
            f"not every authenticated caller to Role {role}"
        )
    rules = one(objects, "Role", role, namespace).get("rules")
    if rules != [{"apiGroups": [""], "resources": ["configmaps"], "resourceNames": [TEKTON_VERSION], "verbs": ["get"]}]:
        refuse(f"Role {namespace}/{role} gives every authenticated caller {json.dumps(rules)}, not `get` of ConfigMap {TEKTON_VERSION}")
    version = one(objects, "ConfigMap", TEKTON_VERSION, namespace)
    if set(version.get("data") or {}) != {"version"} or version.get("binaryData"):
        refuse(f"ConfigMap {namespace}/{TEKTON_VERSION} holds more than Tekton's version, and every authenticated caller reads it")


def bindings_hold(objects):
    people = []
    for document in objects:
        if document.get("kind") not in BINDINGS:
            continue
        metadata = document["metadata"]
        name = f"{document['kind']} {metadata.get('namespace') or ''}/{metadata['name']}"
        subjects = document.get("subjects") or []
        for subject in subjects:
            if subject.get("kind") == "ServiceAccount" and subject.get("namespace") == NAMESPACE:
                refuse(f"{name} binds ServiceAccount {NAMESPACE}/{subject.get('name')}, which holds nothing")
        everyone = [s["name"] for s in subjects if s.get("kind") == "Group" and s.get("name") in EVERY_MEMBER]
        if everyone and (document["kind"], metadata.get("namespace"), metadata["name"]) == ("RoleBinding", *TEKTON_INFO):
            tekton_info_holds(objects, document, name)
        elif everyone:
            refuse(f"{name} binds group {everyone[0]}, which takes in every member signed in")
        if any(str(s.get("name", "")).startswith(USERNAME_PREFIX) for s in subjects):
            people.append((document, name))
    if len(people) != 1:
        refuse(f"{len(people)} bindings name a person {USERNAME_PREFIX}<sub>, not the one of ClusterRole view")
    document, name = people[0]
    if document["kind"] != "ClusterRoleBinding" or document["roleRef"] != VIEW:
        refuse(f"{name} binds a person to {json.dumps(document['roleRef'])}, and only a ClusterRoleBinding of ClusterRole view may")
    for subject in document["subjects"]:
        if (subject.get("apiGroup"), subject.get("kind")) != (RBAC, "User") or not PERSON.fullmatch(str(subject.get("name", ""))):
            refuse(f"{name} binds {json.dumps(subject)}, and each subject of it is a User {USERNAME_PREFIX}<Kratos identity id>")


def authenticator_holds(host, env):
    if FLAG not in flags_of(host["flags"]):
        refuse(f"gtr's k3s is not started with {FLAG}")
    if host["file"] is None:
        refuse(f"gtr writes no {CONFIG_PATH}")
    if host["file"] not in host["restartTriggers"]:
        refuse(f"{CONFIG_PATH} is not among k3s's restart triggers, so a change to it waits for a reboot")

    config = yaml.safe_load(Path(host["file"]).read_text())
    if (config.get("apiVersion"), config.get("kind")) != (
        "apiserver.config.k8s.io/v1beta1",
        "AuthenticationConfiguration",
    ):
        refuse(f"{CONFIG_PATH} is {config.get('apiVersion')} {config.get('kind')}")
    authenticators = config.get("jwt") or []
    if len(authenticators) != 1:
        refuse(f"{CONFIG_PATH} declares {len(authenticators)} JWT authenticators, not Headlamp's one")
    issuer = authenticators[0].get("issuer") or {}
    if issuer.get("url") != env["OIDC_ISSUER_URL"]:
        refuse(f"the API server trusts issuer {issuer.get('url')!r}, Headlamp signs in at {env['OIDC_ISSUER_URL']!r}")
    if issuer.get("url", "").endswith("/"):
        refuse("the issuer ends in `/`, and Hydra's discovery `issuer` does not")
    if issuer.get("audiences") != [env["OIDC_CLIENT_ID"]]:
        refuse(
            f"the authenticator's audiences are {issuer.get('audiences')}, not exactly "
            f"[{env['OIDC_CLIENT_ID']}]: any other lets another client's tokens in"
        )
    if "discoveryURL" in issuer or "audienceMatchPolicy" in issuer:
        refuse("the issuer carries a discoveryURL or audienceMatchPolicy this check does not hold")
    mappings = authenticators[0].get("claimMappings") or {}
    if mappings.get("username") != {"claim": "sub", "prefix": USERNAME_PREFIX}:
        refuse(f"the username mapping is {mappings.get('username')}, not `sub` under {USERNAME_PREFIX!r}")
    groups = mappings.get("groups") or {}
    try:
        constant = json.loads(groups.get("expression", ""))
    except ValueError:
        constant = None
    if set(groups) != {"expression"} or constant != [GROUP]:
        refuse(f"the groups mapping is {groups}, not the constant [{GROUP!r}]")
    rest = set(authenticators[0]) - {"issuer", "claimMappings"}
    if rest or set(mappings) - {"username", "groups"}:
        refuse(f"the authenticator carries {sorted(rest | (set(mappings) - {'username', 'groups'}))}, which this check does not hold")


def unauthenticated_holds(host):
    if any(flag.startswith(FLAG_PREFIX) for flag in flags_of(host["flags"])):
        refuse("a host that names no authenticator is started with an authentication-config flag")
    if host["file"] is not None:
        refuse(f"a host that names no authenticator writes {CONFIG_PATH}")


def ingress_holds(layer, hostnames, env):
    callback = urlsplit(env["OIDC_CALLBACK_URL"])
    if (callback.scheme, callback.path, callback.query) != ("https", CALLBACK_PATH, ""):
        refuse(f"the callback {env['OIDC_CALLBACK_URL']} is not https://<host>{CALLBACK_PATH}")
    hosts = set()
    for ingress in (d for d in layer if d.get("kind") == "Ingress"):
        for rule in ingress["spec"].get("rules") or []:
            hosts.add(rule.get("host"))
            for path in rule["http"]["paths"]:
                service = path["backend"]["service"]
                if service["name"] != RELEASE or service["port"] != {"name": "http"}:
                    refuse(f"the Ingress routes {rule.get('host')} to {service}, not the chart's Service")
    for host in sorted(hosts - set(hostnames), key=str):
        refuse(f"the Ingress serves {host}, which is not in gtr's chuggy.tunnel.hostnames")
    if callback.hostname not in hosts:
        refuse(f"the callback's host {callback.hostname} is not one the Ingress serves")


def namespace_holds(layer):
    labels = one(layer, "Namespace", NAMESPACE)["metadata"].get("labels") or {}
    for mode in ("enforce", "audit", "warn"):
        if labels.get(f"pod-security.kubernetes.io/{mode}") != "restricted":
            refuse(f"namespace {NAMESPACE} does not {mode} pod security `restricted`")


def main():
    if len(sys.argv) != 6:
        refuse("usage: headlamp.py RENDERED_DIRECTORY BUILD_SYSTEM FLUX_COMPONENTS GTR_JSON UNAUTHENTICATED_HOST_JSON")
    rendered = Path(sys.argv[1])
    layer = documents_in(rendered / "headlamp.yaml")
    everything = documents_in(rendered / "cluster.yaml") + documents_in(sys.argv[2]) + documents_in(sys.argv[3])
    gtr = json.loads(Path(sys.argv[4]).read_text())
    bare = json.loads(Path(sys.argv[5]).read_text())

    namespace_holds(layer)
    env = environment(release_values(layer))
    bindings_hold(everything)
    authenticator_holds(gtr, env)
    unauthenticated_holds(bare)
    ingress_holds(layer, gtr["hostnames"], env)


if __name__ == "__main__":
    main()
