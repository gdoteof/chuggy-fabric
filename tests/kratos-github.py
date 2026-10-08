#!/usr/bin/env python3
"""Refuse a rendered cluster where signing in with GitHub would make an
identity, would stop Kratos from starting, or would sign nobody in.

Kratos's `oidc` method signs in whichever identity holds the GitHub account a
person arrives with, and an account no identity holds falls through to
registration. So what keeps this rig's identities the ones somebody made on
purpose is not in the method at all. It is `selfservice.flows.registration`
being closed, in another section of the same document, which reads correctly
on its own either way -- and Kratos's default for that key is open, so the key
deleted is the flow opened. With the method on and the flow open, an identity
is one press of a button away for every GitHub account there is.

WHAT THE PROCESS READS IS THE DOCUMENT AND THEN ITS ENVIRONMENT, and a variable
named for a key replaces that key: `SELFSERVICE_FLOWS_REGISTRATION_ENABLED` on
the container reopens the flow under a document that still says closed, and
`SELFSERVICE_METHODS_OIDC_ENABLED` turns the method on under one that says off.
So the container names one kind of `SELFSERVICE_` variable, the client secret
below, and no `envFrom`, whose names no render shows. That is held whether or
not the method is on, because it is what makes the document worth reading.

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
what chuggy-portal is. `github`, the type for an OAuth App, refuses a token
lacking a scope the provider names, and a GitHub App's token carries none; any
other type calls another host, or derives its subject some other way than from
the account's numeric id, which is what the stored credentials are.

NO POLICY ISOLATES KRATOS FOR EGRESS, AND ONE THAT DID IS REFUSED RATHER THAN
READ. Signing in calls github.com and api.github.com from this pod, and
ory-network-policy.yaml invites an egress rule later. A rule that forgot those
two would leave password sign-in working and every GitHub sign-in timing out,
which no other gate here would notice.

WHAT THIS GATE CANNOT SEE. Whether the Secret exists or holds the App's client
secret, whether the App lists the callback URL, and whether the App holds the
account permission Kratos's `github-app` provider needs: each is at GitHub or
on the node, and the README says what its absence looks like. Nor the mapper
the provider names, which Kratos evaluates only when it registers an identity
-- the flow this gate holds shut.
"""

import re
import sys
from pathlib import Path, PurePosixPath

import yaml

ORY = "ory"
DEPLOYMENT = "kratos"
SERVER = "kratos"

# The flag whose value names the file the server actually reads.
CONFIG_FLAG = "--config"

PROVIDER_ID = "github"
PROVIDER_TYPE = "github-app"

# What Kratos's own schema requires of a provider, the secret apart.
REQUIRED = ("id", "provider", "client_id", "mapper_url")
SECRET = "client_secret"

# Every key under `selfservice` is a variable beginning with this, and one field
# of one element of the provider list is spelled with the element's index in it.
SELFSERVICE = "SELFSERVICE_"
SECRET_VARIABLE = re.compile(
    r"SELFSERVICE_METHODS_OIDC_CONFIG_PROVIDERS_(0|[1-9][0-9]*)_CLIENT_SECRET"
)


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
    """The document `--config` names, through the mount and the generated
    ConfigMap, each step refused rather than guessed at -- as tests/ory-admin.py
    resolves the same file."""
    args = entry.get("args") or []
    if args.count(CONFIG_FLAG) != 1 or args.index(CONFIG_FLAG) + 1 >= len(args):
        refuse(f"the {entry['name']} container does not name one {CONFIG_FLAG} and its value")
    path = PurePosixPath(args[args.index(CONFIG_FLAG) + 1])
    mounts = [
        mount
        for mount in entry.get("volumeMounts") or []
        if mount.get("mountPath") == str(path.parent)
    ]
    if len(mounts) != 1:
        refuse(f"{len(mounts)} volumeMounts cover {path.parent}, which {CONFIG_FLAG} reads from")
    volumes = [
        volume
        for volume in deployment["spec"]["template"]["spec"].get("volumes") or []
        if volume["name"] == mounts[0]["name"]
    ]
    if len(volumes) != 1 or "configMap" not in volumes[0]:
        refuse(f"the volume {mounts[0]['name']!r} is not one ConfigMap this gate can open")
    data = one(documents, "ConfigMap", volumes[0]["configMap"]["name"], ORY).get("data") or {}
    if path.name not in data:
        refuse(f"the ConfigMap mounted at {path.parent} carries no {path.name}")
    try:
        document = yaml.safe_load(data[path.name])
    except yaml.YAMLError as failure:
        refuse(f"{path.name} is not YAML: {failure}")
    if not isinstance(document, dict):
        refuse(f"{path.name} is not a mapping")
    return path.name, document


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


def main():
    if len(sys.argv) != 2:
        refuse("usage: kratos-github.py RENDERED_MANIFEST")
    documents = objects(sys.argv[1])

    deployment = one(documents, "Deployment", DEPLOYMENT, ORY)
    entry = container(deployment, SERVER)
    name, document = config_document(documents, deployment, entry)

    # 1. The document is the whole of `selfservice` but for the client secret.
    if entry.get("envFrom"):
        refuse(
            f"the {SERVER} container takes variables by envFrom, whose names no render "
            f"shows, and one beginning {SELFSERVICE} replaces what {name} says"
        )
    supplied = {}
    for item in entry.get("env") or []:
        if not item["name"].startswith(SELFSERVICE):
            continue
        matched = SECRET_VARIABLE.fullmatch(item["name"])
        if not matched:
            refuse(
                f"the {SERVER} container sets {item['name']}, which replaces a key of "
                f"{name} that this gate reads from the document"
            )
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

    if oidc.get("enabled") is not True:
        return

    # 4. With the method on, an account no identity holds makes no identity.
    if within(document, "selfservice", "flows", "registration").get("enabled") is not False:
        refuse(
            f"{name} enables the oidc method without closing selfservice.flows.registration, "
            "so anyone with a GitHub account is given an identity by asking"
        )

    # 5. One provider, the one the callback URL and the stored credentials name.
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

    # 6. Nothing stands between this pod and GitHub that this gate has not read.
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


if __name__ == "__main__":
    main()
