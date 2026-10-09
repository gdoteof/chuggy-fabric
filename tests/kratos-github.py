#!/usr/bin/env python3
"""Refuse a rendered cluster where Kratos would make an identity the access
plane's gate did not admit, would not start, or would sign nobody in with
GitHub.

Kratos's `oidc` method signs in whichever identity holds the GitHub account a
person arrives with, and an account no identity holds falls through to
registration. So what keeps this rig's identities the ones somebody meant to
make is not in the method at all. It is `selfservice.flows.registration`, in
another section of the same document: closed, or open behind a hook that asks
the access plane whether the person's browser holds an open invite link. Each
section reads correctly on its own either way -- and Kratos's default for the
flow is open with no hook, so the section deleted is an identity one press of a
button away for every GitHub account there is.

AN OPEN FLOW IS HELD TO ITS GATE, METHOD BY METHOD. Kratos reads the hooks that
run before an identity is stored from the registering method's own list and
from nowhere else, so a method that is on with no list of its own registers
whoever asks. `password`, `oidc`, `code`, `webauthn` and `passkey` can
register. Each is either off or carries exactly two hooks: a `web_hook` to the
plane's gate, which Kratos sends before it stores the identity, and `session`.
The `oidc` hook sends the gate the invite cookie. Every other method's sends an
empty token, which the gate always refuses, because a link admits a GitHub
account and an identity made any other way holds none. Off is what the
document says and not what Kratos defaults to: `enabled: false`, and for
`code` no `passwordless_enabled: true` beside it, which turns the method on
over an `enabled` that says off. A method this gate does not know is refused
rather than read as one that cannot register. All of it is held whether or not
the `oidc` method is on, because the others register without it.

THE HOOK IS HELD KEY BY KEY, BECAUSE EACH KEY IS A WAY IT STOPS DECIDING.
Without `response.parse` Kratos sends it once the identity is stored. With
`response.ignore` it does not wait for the answer, and with the two together
it does not start. Its `url` is made here from the rendered Service -- its
name, its namespace, the port it publishes -- and the gate's path, so a
Service renamed or republished is a finding here and not a registration that
fails on the rig. The path is `accessRegistrationGatePath` in kasofsk/chuggy's
`src/contract/accessPlane.ts` and has a copy below. A key this gate does not
read, a header or a credential, is refused.

AND THE PLANE HAS TO ADMIT THE CALL. kratos.yaml is applied by a merge and the
plane's ingress policy by a release, and Kratos fails a registration whose
hook is not answered. So where a policy isolates the pod that Service selects,
one of them admits this pod's labels from `ory` on the port the Service lands
on, and a document that opens the flow does not render without it.
tests/access-plane.py holds who else that policy admits.

THE TWO BODIES ARE HELD WHOLE, AS TEXT. Kratos skips a hook whose body fails
with an error whose text contains `RUNTIME ERROR: cancel`, and goes on to
store the identity as if the hook were not there. It tests the text and not
the statement that raised it, so a body that hands a cookie to anything that
can fail and echo it is a gate whoever set the cookie removes. The gate's body
is therefore one field read and no call, and it is that short on purpose: the
text of each body is below, a mounted one that differs is refused, and neither
is edited without editing this. Each is then evaluated against a request
carrying the cookie, carrying none, carrying it among others, and carrying it
with that very text for a value, which has to come back as the token like any
other.

THE MAPPER IS EVALUATED TOO, BECAUSE A REGISTRATION EVALUATES IT. One that
fails ends a registration on the error page, and one that maps an identity
without the address the schema requires ends it on a form the console's page
does not draw: both before the gate is asked, and the person a link invited is
given no identity. So it is run against the claims Kratos's `github-app`
provider makes -- an address GitHub verified, one it did not, and none -- and
the whole of what it maps is compared.

A REFUSED PERSON IS SENT OFF THE HOST KRATOS SERVES. `registration.ui_url` is
where Kratos sends whoever the gate refuses, with the flow's id. The stock
registration page on Kratos's own host draws a form for a flow it is handed,
so a `ui_url` there, or none, is refused.

WHAT THE PROCESS READS IS THE DOCUMENT AND THEN ITS ENVIRONMENT, and a variable
named for a key replaces that key: `SELFSERVICE_FLOWS_REGISTRATION_ENABLED` on
the container reopens the flow under a document that still says closed, and
`SELFSERVICE_METHODS_OIDC_ENABLED` turns the method on under one that says off.
Kratos reads a variable's name in any letter case and takes a dot for an
underscore, so a name is judged as Kratos reads it and not as it is spelled.
So the container names one variable under `selfservice`, the client secret
below, none under `ciphers`, and no `envFrom`, whose names no render shows. And
it is started on the one document and nothing more. A second config flag, a
`command` carrying its own, or a comma in the flag's value names another
document Kratos reads with this one; a mount over the file, or a ConfigMap
volume that renames its keys, puts another document where this one is read
from. Both are held whether or not the method is on, because they are what
makes the document worth reading.

THE CLIENT SECRET IS ONE FIELD OF ONE ELEMENT OF A LIST, DELIVERED BY POSITION.
The document leaves it out because the document is public, and the variable
that supplies it carries the provider's index in its name. Kratos validates what
the two make together and exits on a provider missing a field it requires,
whether or not the method is enabled. A provider with no variable is that, and
so is a variable at an index the list does not have, which makes a provider of
one field. So the providers the document lists and the indices the variables
name are one set, a provider carries every other required field itself, and
none carries the secret, which would be a credential in Git.

AND THE VARIABLE IS A REQUIRED REFERENCE TO A SECRET. A literal is the same
credential in Git by another road. `optional` starts nothing the required form
would not -- the provider is as incomplete either way -- and turns an event
naming the Secret that is missing into a crash loop on a schema error.

ONE PROVIDER, WHOSE ID IS `github` AND WHOSE TYPE IS `github-app`. The id is
the last segment of the callback URL registered on the GitHub App and the
prefix of the credential every linked identity stores, so it has a copy at
GitHub and a copy in the database, and a rename here strands both. The type is
what chuggy-portal is, and the one Ory's documentation names for a GitHub App.
`github`, the type for an OAuth App, refuses a token lacking a scope the
provider names, and a GitHub App's token carries none, so it signs a person in
only for as long as the provider names no scope; any other type calls another
host, or derives its subject some other way than from the account's numeric
id, which is what the stored credentials are.

NO POLICY ISOLATES KRATOS FOR EGRESS, AND ONE THAT DID IS REFUSED RATHER THAN
READ. Signing in calls github.com and api.github.com from this pod, a
registration calls the plane's gate, and ory-network-policy.yaml invites an
egress rule later. A rule that forgot GitHub would leave password sign-in
working and every GitHub sign-in timing out, which no other gate here would
notice.

WHAT AN ACCOUNT LEAVES IS ENCRYPTED ONLY WHERE THE DOCUMENT NAMES A CIPHER.
Kratos keeps the GitHub tokens of a person who registers with an account or
links one, and its default for `ciphers.algorithm` is `noop`, which stores
them hex-encoded for whoever reads the database. The key in `secrets-cipher`
encrypts nothing by being there. So with the method on, the document names one
of the two ciphers Kratos has.

WHAT THIS GATE CANNOT SEE. Whether the Secret exists or holds the App's client
secret, whether the App lists the callback URL, and whether the App holds the
account permission Kratos's `github-app` provider needs: each is at GitHub or
on the node, and the README says what its absence looks like. Nor what the
plane answers at the gate's path, or whether it serves it: that is the
product's, and a plane that does not serve it fails every registration and
admits none. Nor that the cookie the body reads is the one the console sets.
Nor that the Jsonnet Kratos embeds evaluates these files as the one this gate
runs does; tests/kratos-github.nix says which that is.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml

ORY = "ory"
DEPLOYMENT = "kratos"
SERVER = "kratos"

# The access plane, whose Service the gate is called at.
CONTROL = "chuggy"
PLANE_SERVICE = "chuggy-access-plane"
CLUSTER_SUFFIX = ".svc.cluster.local"

# `accessRegistrationGatePath` in kasofsk/chuggy's `src/contract/accessPlane.ts`,
# which this is a copy of.
GATE_PATH = "/hooks/v1/registration"

# The label a namespace is named by, which the API server sets.
NAMESPACE_LABEL = "kubernetes.io/metadata.name"

# The methods under `selfservice.methods` that can register an identity, and
# the ones this gate knows cannot. A name in neither is refused.
REGISTERING = ("password", "oidc", "code", "webauthn", "passkey")
INERT = ("profile", "link", "totp", "lookup_secret")

# The one method the gate admits through, and so the one whose hook sends the
# cookie.
ADMITTING = "oidc"

# The two bodies, whole. `chuggy_invite` is the console's name for the cookie
# its page for an invite link sets, and this is a copy of it.
GATE_BODY = (
    "function(ctx) { token: ({ chuggy_invite: '' } + ctx.request_cookies).chuggy_invite }\n"
)
REFUSAL_BODY = "function(ctx) { token: '' }\n"

# What the two hooks and `session` are, as the document has to give them. The
# keys of a `web_hook`'s config this gate reads; any other is refused.
HOOK_KEYS = {"url", "method", "body", "response"}
SESSION = {"hook": "session"}

# The text Kratos looks for in a body's failure before it skips the hook.
CANCEL = "RUNTIME ERROR: cancel"

# The requests a body is evaluated against, as (what the request carries, its
# cookies, the token the gate's body sends). The refusal's sends none for any.
COOKIE = "chuggy_invite"
REQUESTS = (
    ("the cookie", {COOKIE: "a-link-token"}, "a-link-token"),
    ("no cookie", {}, ""),
    (
        "the cookie among others",
        {"csrf_token": "first", COOKIE: "a-link-token", "ory_kratos_session": "last"},
        "a-link-token",
    ),
    (f"the cookie with the value {CANCEL!r}", {COOKIE: CANCEL}, CANCEL),
)

# The claims the mapper is evaluated against, as (what GitHub said of the
# account's address, the claims beside the account's own, the identity mapped).
# Kratos leaves `email_verified` out where GitHub's answer is false, and
# `email` out for an account that lists no address.
ACCOUNT = {
    "iss": "https://github.com/login/oauth/access_token",
    "sub": "583231",
    "nickname": "octocat",
}
ADDRESS = "octocat@example.com"
NO_REPLY = "583231+octocat@users.noreply.github.com"
HANDLE = {"github_login": "octocat", "github_id": "583231"}
CLAIMS = (
    (
        "an address GitHub verified",
        {"email": ADDRESS, "email_verified": True},
        {"traits": {"email": ADDRESS}, "metadata_admin": {**HANDLE, "github_email": ADDRESS}},
    ),
    (
        "an address GitHub did not verify",
        {"email": ADDRESS},
        {"traits": {"email": NO_REPLY}, "metadata_admin": HANDLE},
    ),
    (
        "no address",
        {},
        {"traits": {"email": NO_REPLY}, "metadata_admin": HANDLE},
    ),
)

# The flag whose value names the file the server actually reads.
CONFIG_FLAG = "--config"

PROVIDER_ID = "github"
PROVIDER_TYPE = "github-app"

# What Kratos's own schema requires of a provider, the secret apart.
REQUIRED = ("id", "provider", "client_id", "mapper_url")
SECRET = "client_secret"

# The sections of the document this gate reads, which no variable may replace.
# Kratos lower-cases a variable's name and reads its underscores as dots before
# it looks the key up, so that is the form a name is judged in. One field of one
# element of the provider list is spelled with the element's index in it.
SELFSERVICE = "selfservice"
CIPHERS = "ciphers"
SECRET_VARIABLE = re.compile(
    r"SELFSERVICE_METHODS_OIDC_CONFIG_PROVIDERS_(0|[1-9][0-9]*)_CLIENT_SECRET"
)

# The values of `ciphers.algorithm` under which Kratos encrypts.
ENCRYPTING = ("xchacha20-poly1305", "aes")

# A value of the config flag that names one file. Kratos splits the value on a
# comma, so one holding a comma names two.
ONE_FILE = re.compile(r"/[A-Za-z0-9._/-]+")


def refuse(message):
    raise SystemExit(f"kratos github: {message}")


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
    for entry in deployment["spec"]["template"]["spec"].get("containers", []):
        if entry["name"] == name:
            return entry
    refuse(f"{deployment['metadata']['name']} has no container {name}")


def under(variable, section):
    """Whether Kratos reads the variable as the section or a key beneath it."""
    key = variable.lower().replace("_", ".")
    return key == section or key.startswith(section + ".")


def selects(selector, labels, described):
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


def config_document(documents, deployment, entry):
    """The one document the server is started on, through the mount and the
    generated ConfigMap, each step refused rather than guessed at: where it is
    mounted, every file mounted beside it, and the document itself."""
    args = entry.get("args") or []
    if (
        "command" in entry
        or len(args) != 3
        or args[:2] != ["serve", CONFIG_FLAG]
        or not ONE_FILE.fullmatch(str(args[2]))
    ):
        refuse(
            f"the {entry['name']} container is not started as `serve {CONFIG_FLAG} FILE` "
            "and nothing more, and a second file or a command of its own is "
            "configuration this gate does not read"
        )
    path = PurePosixPath(args[2])
    directory = str(path.parent)
    mounts = [
        mount
        for mount in entry.get("volumeMounts") or []
        if (mount["mountPath"] + "/").startswith(directory + "/")
    ]
    if (
        len(mounts) != 1
        or mounts[0]["mountPath"] != directory
        or "subPath" in mounts[0]
        or "subPathExpr" in mounts[0]
    ):
        refuse(
            f"{directory}, which {CONFIG_FLAG} reads from, is not one whole volume mounted "
            "there with nothing mounted beneath it"
        )
    volumes = [
        volume
        for volume in deployment["spec"]["template"]["spec"].get("volumes") or []
        if volume["name"] == mounts[0]["name"]
    ]
    source = volumes[0].get("configMap") if len(volumes) == 1 else None
    if not source or "items" in source:
        refuse(f"the volume {mounts[0]['name']!r} is not one whole ConfigMap this gate can open")
    data = one(documents, "ConfigMap", source["name"], ORY).get("data") or {}
    if path.name not in data:
        refuse(f"the ConfigMap mounted at {path.parent} carries no {path.name}")
    try:
        document = yaml.safe_load(data[path.name])
    except yaml.YAMLError as failure:
        refuse(f"{path.name} is not YAML: {failure}")
    if not isinstance(document, dict):
        refuse(f"{path.name} is not a mapping")
    return path, data, document


def within(document, *keys):
    """A nested mapping, an absent one read as empty and any other shape
    refused: a section that is a list or a string is not one this gate reads."""
    for depth, key in enumerate(keys):
        document = document.get(key)
        if document is None:
            return {}
        if not isinstance(document, dict):
            refuse(f"{'.'.join(keys[: depth + 1])} is not a mapping")
    return document


def written(labels):
    return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))


def mounted(reference, path, data, described):
    """The file of the mounted ConfigMap that the document names by a
    `file://` URL, as (its name, its text)."""
    prefix = f"file://{path.parent}/"
    named = isinstance(reference, str) and reference.startswith(prefix)
    key = reference[len(prefix) :] if named else ""
    if not key or "/" in key or key not in data:
        refuse(
            f"{described} is {reference!r}, which is not a file of the ConfigMap mounted at "
            f"{path.parent}: Kratos reads it when a registration is tried and not when it "
            "starts, and fails every one"
        )
    return key, data[key]


def evaluated(text, flag, variable, value, described):
    """What one Jsonnet file makes of one input, which reaches it as Kratos
    hands it: a mapper's claims as an external variable, a body's request as
    the argument of the function the body is."""
    binary = shutil.which("jsonnet")
    if binary is None:
        refuse("there is no `jsonnet` to evaluate the mapper and the hook bodies with")
    with tempfile.TemporaryDirectory() as scratch:
        snippet = Path(scratch, "snippet.jsonnet")
        snippet.write_text(text)
        given = Path(scratch, "given.json")
        given.write_text(json.dumps(value))
        ran = subprocess.run(
            [binary, flag, f"{variable}={given}", str(snippet)],
            capture_output=True,
            text=True,
            check=False,
        )
    if ran.returncode != 0:
        failure = (ran.stderr.strip().splitlines() or ["with no message"])[0]
        refuse(f"{described} does not evaluate: {failure}")
    try:
        return json.loads(ran.stdout)
    except ValueError:
        refuse(f"{described} does not evaluate to JSON")


def off(method, section):
    """Whether the document turns a method off, as Kratos reads the document
    and not as it defaults what the document leaves out. `passwordless_enabled`
    turns `code` on over an `enabled` that says off."""
    if section.get("enabled") is not False:
        return False
    return method != "code" or section.get("passwordless_enabled") in (None, False)


def gate(documents):
    """The plane's gate as Kratos has to call it, and where the call lands: the
    URL, the labels of the pod that answers it, and the port on that pod."""
    service = one(documents, "Service", PLANE_SERVICE, CONTROL)
    spec = service["spec"]
    published = spec.get("ports") or []
    if (
        spec.get("clusterIP") == "None"
        or spec.get("type", "ClusterIP") == "ExternalName"
        or len(published) != 1
        or published[0].get("protocol", "TCP") != "TCP"
    ):
        refuse(
            f"Service {PLANE_SERVICE} is not one TCP port behind a cluster address, and "
            "this gate makes the gate's URL from the one port it publishes"
        )
    chosen = spec.get("selector") or {}
    answering = [
        document
        for document in documents
        if document.get("kind") == "Deployment"
        and document["metadata"].get("namespace") == CONTROL
        and chosen
        and all(
            (document["spec"]["template"]["metadata"].get("labels") or {}).get(key) == value
            for key, value in chosen.items()
        )
    ]
    if len(answering) != 1:
        refuse(
            f"Service {PLANE_SERVICE} selects {len(answering)} Deployments in `{CONTROL}`, "
            "and this gate resolves the one that answers the gate"
        )
    template = answering[0]["spec"]["template"]
    target = published[0].get("targetPort", published[0]["port"])
    if not isinstance(target, int):
        numbers = {
            port["containerPort"]
            for box in template["spec"].get("containers") or []
            for port in box.get("ports") or []
            if port.get("name") == target
        }
        if len(numbers) != 1:
            refuse(
                f"Service {PLANE_SERVICE} targets the named port {target!r}, which its pod "
                f"publishes {len(numbers)} numbers for"
            )
        target = numbers.pop()
    url = f"http://{PLANE_SERVICE}.{CONTROL}{CLUSTER_SUFFIX}:{published[0]['port']}{GATE_PATH}"
    return url, template["metadata"].get("labels") or {}, target


def admitted(documents, labels, port, caller):
    """Whether the plane's pod admits the calling pod on the port the gate is
    served on. Policies add, so every one that isolates the pod for ingress is
    read; a pod none isolates admits every source, and tests/access-plane.py is
    what refuses that. A peer or port in a shape this does not resolve admits
    nothing here."""
    isolating = []
    for policy in documents:
        if policy.get("kind") != "NetworkPolicy" or policy["metadata"].get("namespace") != CONTROL:
            continue
        # Unstated, a policy's types include Ingress.
        types = policy["spec"].get("policyTypes")
        if (types is None or "Ingress" in types) and selects(
            policy["spec"].get("podSelector") or {}, labels, policy["metadata"]["name"]
        ):
            isolating.append(policy)
    if not isolating:
        return True
    for policy in isolating:
        for arm in policy["spec"].get("ingress") or []:
            ports = arm.get("ports") or []
            if ports and not any(
                entry.get("port") == port
                and entry.get("protocol", "TCP") == "TCP"
                and "endPort" not in entry
                for entry in ports
            ):
                continue
            peers = arm.get("from") or []
            if not peers:
                return True
            for peer in peers:
                # A peer naming no namespace is this policy's own, where
                # Kratos is not; an address block names no pod.
                if "ipBlock" in peer or "namespaceSelector" not in peer:
                    continue
                named = peer["namespaceSelector"] or {}
                if named and named != {"matchLabels": {NAMESPACE_LABEL: ORY}}:
                    continue
                if selects(peer.get("podSelector") or {}, caller, policy["metadata"]["name"]):
                    return True
    return False


def hooked(hooks, method, url, path, data):
    """One registering method's own hooks, held to the gate and `session` and
    nothing else, and the mounted file the gate's body is."""
    name = path.name
    where = f"selfservice.flows.registration.after.{method}.hooks"
    cost = (
        "an identity is made for every GitHub account that asks"
        if method == ADMITTING
        else "this method makes an identity for whoever asks"
    )
    if not isinstance(hooks, list) or not all(isinstance(hook, dict) for hook in hooks):
        hooks = []
    if [hook.get("hook") for hook in hooks] != ["web_hook", "session"]:
        refuse(
            f"{name} leaves the {method} method able to register and gives {where} as "
            f"{[hook.get('hook') for hook in hooks]}, not one web_hook to the plane's gate "
            "and then session: Kratos reads the hooks that run before it stores an identity "
            f"from the method's own list alone, so {cost}"
        )
    asked, session = hooks
    if session != SESSION or set(asked) != {"hook", "config"}:
        refuse(
            f"a hook under {where} in {name} carries more than this gate reads of it: "
            "`session` takes nothing, and a web_hook takes its config"
        )
    config = asked["config"] if isinstance(asked["config"], dict) else {}
    response = config.get("response")
    if not isinstance(response, dict):
        response = {}
    if response.get("ignore") not in (None, False):
        refuse(
            f"the web_hook under {where} in {name} sets response.ignore: beside "
            "response.parse that is a document Kratos does not start on, and without it "
            f"Kratos does not wait for the gate's answer and {cost}"
        )
    if response.get("parse") is not True:
        refuse(
            f"the web_hook under {where} in {name} does not set response.parse, so Kratos "
            "sends it once the identity is stored, when no answer unmakes one, and "
            f"{cost}"
        )
    extra = sorted((set(config) - HOOK_KEYS) | (set(response) - {"parse", "ignore"}))
    if extra:
        refuse(
            f"the web_hook under {where} in {name} also carries {', '.join(extra)}, which "
            "this gate does not read: a hook is the gate's URL, POST, a body and "
            "response.parse, and nothing that changes what is sent or when"
        )
    if config.get("method") != "POST":
        refuse(
            f"the web_hook under {where} in {name} is sent by {config.get('method')!r}, and "
            "the gate answers a POST"
        )
    if config.get("url") != url:
        refuse(
            f"the web_hook under {where} in {name} is sent to {config.get('url')!r} and not "
            f"to {url}, which is Service {PLANE_SERVICE} in `{CONTROL}`, the port it "
            "publishes and the gate's path: Kratos fails a registration whose hook is not "
            "answered by the gate"
        )
    key, text = mounted(config.get("body"), path, data, f"the body of the web_hook under {where}")
    if method != ADMITTING and text == GATE_BODY:
        refuse(
            f"the web_hook under {where} in {name} sends the gate's body, {key}, which "
            "reads the invite cookie: a link admits a GitHub account, and with it this "
            "method makes an identity that holds none for whoever holds a link"
        )
    wanted = GATE_BODY if method == ADMITTING else REFUSAL_BODY
    if text != wanted:
        refuse(
            f"{key}, the body of the web_hook under {where} in {name}, is {text!r} and "
            f"not {wanted!r}: the text of each body is held whole in "
            "tests/kratos-github.py, whose header says why it is that short"
        )
    return key, text


def registration(documents, deployment, path, data, document):
    """An open registration flow, held to the plane's gate."""
    name = path.name
    methods = within(document, "selfservice", "methods")
    unknown = sorted(set(methods) - set(REGISTERING) - set(INERT))
    if unknown:
        refuse(
            f"{name} names the method {', '.join(unknown)} while registration is open, "
            "and this gate does not know whether it registers an identity: one that does, "
            "with no hook of its own, registers whoever asks"
        )
    flow = within(document, "selfservice", "flows", "registration")
    url, labels, port = gate(documents)

    # Every method that can register and is not off, to the gate or the refusal.
    bodies = {}
    for method in REGISTERING:
        if off(method, within(methods, method)):
            continue
        hooks = within(flow, "after", method).get("hooks")
        key, text = hooked(hooks, method, url, path, data)
        bodies[key] = (text, method == ADMITTING)

    # Each body as Kratos evaluates it, a failure on any request refused.
    for key, (text, admitting) in sorted(bodies.items()):
        for carried, cookies, token in REQUESTS:
            request = {
                "request_method": "GET",
                "request_url": "https://kratos.example/self-service/methods/oidc/callback/github",
                "request_headers": {},
                "request_cookies": cookies,
            }
            described = f"{key} against a request with {carried}"
            sent = evaluated(text, "--tla-code-file", "ctx", request, described)
            wanted = {"token": token if admitting else ""}
            if sent != wanted:
                refuse(f"{described} sends {sent!r} and not {wanted!r}")

    # Where the refused are sent.
    base = within(document, "serve", "public").get("base_url")
    host = urlsplit(base).hostname if isinstance(base, str) else None
    if not host:
        refuse(f"{name} gives no serve.public.base_url this gate can read Kratos's host from")
    page = flow.get("ui_url")
    landing = urlsplit(page).hostname if isinstance(page, str) else None
    if not landing or landing == host or landing.endswith("." + host):
        refuse(
            f"{name} sends a refused registration to {page!r}: unnamed, that is a page of "
            f"Ory's, and on {host}, where Kratos is served, the registration page draws a "
            "form for the flow it is handed"
        )

    # And the call is admitted.
    caller = deployment["spec"]["template"]["metadata"].get("labels") or {}
    if not admitted(documents, labels, port, caller):
        refuse(
            f"no policy that isolates the access plane's pod for ingress admits a pod "
            f"labelled {written(caller)} in `{ORY}` on TCP {port}, where Service "
            f"{PLANE_SERVICE} lands: Kratos's call to the gate is refused, and every "
            "registration fails"
        )


def main():
    if len(sys.argv) != 2:
        refuse("usage: kratos-github.py RENDERED_MANIFEST")
    documents = objects(sys.argv[1])

    deployment = one(documents, "Deployment", DEPLOYMENT, ORY)
    entry = container(deployment, SERVER)
    path, data, document = config_document(documents, deployment, entry)
    name = path.name

    # 1. The document is the whole of `selfservice` but for the client secret.
    if entry.get("envFrom"):
        refuse(
            f"the {SERVER} container takes variables by envFrom, whose names no render "
            f"shows, and one named for a key under {SELFSERVICE} replaces what {name} says"
        )
    supplied = {}
    for item in entry.get("env") or []:
        if not under(item["name"], SELFSERVICE) and not under(item["name"], CIPHERS):
            continue
        matched = SECRET_VARIABLE.fullmatch(item["name"])
        if not matched:
            refuse(
                f"the {SERVER} container sets {item['name']}, which replaces a key of "
                f"{name} that this gate reads from the document"
            )
        if int(matched.group(1)) in supplied:
            refuse(f"the {SERVER} container sets {item['name']} twice")
        supplied[int(matched.group(1))] = item

    # 2. Each variable is a required reference to a Secret, and never a literal.
    for item in supplied.values():
        reference = (item.get("valueFrom") or {}).get("secretKeyRef") or {}
        if "value" in item or not reference.get("name") or not reference.get("key"):
            refuse(f"{item['name']} is not a reference to one key of one Secret")
        if reference.get("optional"):
            refuse(
                f"{item['name']} is an optional reference, so a pod without the Secret "
                "starts Kratos on a provider with no client secret, which exits"
            )

    # 3. What the document and the variables make together is a list of whole
    #    providers, none of whose secrets is in the document.
    oidc = within(document, "selfservice", "methods", "oidc")
    providers = within(oidc, "config").get("providers") or []
    if not isinstance(providers, list) or not all(isinstance(each, dict) for each in providers):
        refuse(f"selfservice.methods.oidc.config.providers in {name} is not a list of mappings")
    for index, provider in enumerate(providers):
        if SECRET in provider:
            refuse(f"provider {index} in {name} carries {SECRET}, which is a credential in Git")
        missing = [
            key for key in REQUIRED if not isinstance(provider.get(key), str) or not provider[key]
        ]
        if missing:
            refuse(
                f"provider {index} in {name} does not give {', '.join(missing)}, and Kratos "
                "exits on it"
            )
    if set(supplied) != set(range(len(providers))):
        refuse(
            f"{name} lists the providers {sorted(range(len(providers)))} and the {SERVER} "
            f"container supplies a client secret for {sorted(supplied)}: a provider with none, "
            "or a secret for a provider that is not there, is a document Kratos exits on"
        )

    # 4. Registration is closed, or every method that can register asks the
    #    plane's gate first. Kratos's default for the flow is open.
    opened = within(document, "selfservice", "flows", "registration").get("enabled") is not False
    if opened:
        registration(documents, deployment, path, data, document)

    if oidc.get("enabled") is not True:
        return

    # 5. With the method on, what a registered or linked account leaves is
    #    stored encrypted.
    if within(document, CIPHERS).get("algorithm") not in ENCRYPTING:
        refuse(
            f"{name} enables the oidc method without naming a cipher in ciphers.algorithm, "
            "and Kratos's default stores a registered or linked account's GitHub tokens "
            "for anyone who reads the database"
        )

    # 6. One provider, the one the callback URL and the stored credentials name.
    if len(providers) != 1:
        refuse(f"{name} lists {len(providers)} providers, and one is what is registered at GitHub")
    provider = providers[0]
    if provider["id"] != PROVIDER_ID:
        refuse(
            f"the provider in {name} is named {provider['id']!r}: {PROVIDER_ID!r} is in the "
            "callback URL registered at GitHub and in every stored credential"
        )
    if provider["provider"] != PROVIDER_TYPE:
        refuse(
            f"the provider in {name} is of type {provider['provider']!r}, and the App it "
            f"signs in with is a {PROVIDER_TYPE}"
        )

    # 7. Nothing stands between this pod and GitHub that this gate has not read.
    labels = deployment["spec"]["template"]["metadata"].get("labels") or {}
    for policy in documents:
        if policy.get("kind") != "NetworkPolicy" or policy["metadata"].get("namespace") != ORY:
            continue
        spec = policy["spec"]
        # Unstated, the types are Ingress, and Egress where the policy has arms for it.
        types = spec.get("policyTypes") or (["Egress"] if "egress" in spec else [])
        if "Egress" in types and selects(spec["podSelector"], labels, policy["metadata"]["name"]):
            refuse(
                f"{policy['metadata']['name']} isolates the {SERVER} pod for egress, and this "
                "gate cannot read whether it admits github.com and api.github.com, which "
                "every GitHub sign-in calls"
            )

    # 8. Where the flow is open, the mapper a registration evaluates maps what
    #    it is meant to, for each account's address as GitHub describes it.
    if not opened:
        return
    key, text = mounted(provider["mapper_url"], path, data, f"the mapper of the provider in {name}")
    for said, claims, identity in CLAIMS:
        described = f"{key} against an account with {said}"
        mapped = evaluated(text, "--ext-code-file", "claims", {**ACCOUNT, **claims}, described)
        if mapped != {"identity": identity}:
            refuse(f"{described} maps {mapped!r} and not {{'identity': {identity!r}}}")


if __name__ == "__main__":
    main()
