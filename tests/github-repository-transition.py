#!/usr/bin/env python3
"""Refuse a rendered cluster that does not carry every repository the site
declares, everywhere a repository has to appear.

`repositories.nix` is where the site says which repositories it carries; this is
what makes that declaration true of the cluster. A repository is named in the
credential lists, both copies of the scheduler's repositories map, its
credential mounts, its execution grants, the session policy's mirrors, the
mirror job's list and the importer's -- and every one of those reads correctly
while another is missing the entry, which is a control plane that resolves a
repository the sessions working in it cannot clone.

SO THE ROSTER IS THE LOOP AND NOT A LIST OF EXPECTED STRINGS. Adding a
repository is adding an entry to `repositories.nix`; this then fails, naming the
manifest, the variable and the value each place still needs. That is the whole
mechanism by which a third repository is configuration rather than a change to
any of the files below.

AND THE CLOSURE IS CHECKED IN BOTH DIRECTIONS. A GitHub repository named in any
of those places and absent from the roster is refused too: a repository that
half exists -- credentials but no mirror, or a mirror nothing imports -- is the
state this gate is for, and it arrives just as easily by editing a manifest as
by editing the roster.

WHAT DECIDES WHICH SECRET IS RIGHT. Nothing here spells a Secret name: each
comes from the roster entry, and what is held against the render is that the
file a process is told to read is projected from that Secret. A credential is a
path in a configuration, a projection in a pod, and a Secret the host mints, and
each of the three reads correctly while another is wrong.

WHAT THIS GATE CANNOT SEE. Whether the Secrets exist -- the host mints them from
the same roster, and a rebuild is what delivers them. Whether the bare
repository exists on the git service, which `deploy/rig/git/` in kasofsk/chuggy
creates by hand. And it does not hold the mirror job's own credentials or
network together: `tests/git-mirror.py` is where that lives.
"""

import json
import sys
from urllib.parse import urlsplit, urlunsplit

import yaml

CONTROL = "chuggy"
WORK = "chuggy-work"

# The workloads that carry a per-repository credential list, and which of the
# roster's Secrets each one's GitHub credential must come from. A control-plane
# component that grows such a list and is not added here is unchecked, and this
# file is where that is noticed or nowhere.
CREDENTIAL_SOURCES = (
    ("chuggy-api", "CHUG_API_REPOSITORY_CREDENTIAL_SOURCES", (), "readerSecret"),
    ("chuggy-ticket-service", "CHUG_TICKET_SERVICE_CONFIG", ("source", "sources"), "readerSecret"),
    ("chuggy-finalizer", "CHUG_FINALIZER_CREDENTIAL_SOURCES", (), "finalizerSecret"),
)

# Where the scheduler writes the site's map of the repositories that exist. Both
# copies, because a worker resolving a repository a session cannot is the defect
# the copy exists to risk.
REPOSITORY_MAPS = (
    "CHUG_SCHEDULER_WORKER_ENVIRONMENT",
    "CHUG_SCHEDULER_SESSION_ENVIRONMENT",
)
REPOSITORIES_VARIABLE = "CHUG_WORKER_REPOSITORIES"
CREDENTIAL_MOUNTS_VARIABLE = "CHUG_SCHEDULER_WORKER_CREDENTIAL_MOUNTS"
EXECUTION_POLICY_VARIABLE = "CHUG_SCHEDULER_EXECUTION_POLICY"
SESSION_POLICY_VARIABLE = "CHUG_SCHEDULER_SESSION_POLICY"
MIRROR_REPOSITORIES_VARIABLE = "CHUG_GIT_MIRROR_REPOSITORIES"
IMPORT_REPOSITORIES_VARIABLE = "CHUG_CONFIGURATION_IMPORT_REPOSITORIES"

FORGE = "https://github.com/"


def refuse(message):
    raise SystemExit(f"repositories: {message}")


def objects(path):
    with open(path, encoding="utf-8") as handle:
        return [document for document in yaml.safe_load_all(handle) if document]


def workload(documents, kind, name, namespace):
    found = [
        document
        for document in documents
        if document.get("kind") == kind
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == namespace
    ]
    if len(found) != 1:
        refuse(f"the render carries {len(found)} {kind}/{name} in {namespace}, wanted one")
    return found[0]


def pod_of(document):
    if document["kind"] == "CronJob":
        return document["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    return document["spec"]["template"]["spec"]


def sole_container(document):
    pod = pod_of(document)
    containers = pod["containers"]
    if len(containers) != 1:
        name = document["metadata"]["name"]
        refuse(f"{name} declares {len(containers)} containers, wanted one")
    return pod, containers[0]


def variable(container, name, owner):
    found = [entry for entry in container.get("env", []) if entry["name"] == name]
    if len(found) != 1:
        refuse(f"{owner} declares {name} {len(found)} times, wanted once")
    value = found[0].get("value")
    if value is None:
        refuse(f"{owner} takes {name} from somewhere other than a literal")
    return value


def rows(value, columns, owner):
    """The non-empty lines of a configured list, split into the named columns."""
    parsed = []
    for line in value.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) != len(columns):
            refuse(f"{owner} carries {line.strip()!r}, which is not {', '.join(columns)}")
        parsed.append(dict(zip(columns, fields)))
    if not parsed:
        refuse(f"{owner} carries no entries")
    return parsed


def without_userinfo(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def at(value, path, owner):
    for key in path:
        if not isinstance(value, dict) or key not in value:
            refuse(f"{owner} carries no {'.'.join(path)}")
        value = value[key]
    return value


def projected(pod, container, wanted, owner):
    """The (secret, key) a container serves at an absolute path, or a refusal.
    A process told to read a file its pod does not project asks git for a
    password on a terminal that does not exist, which hangs rather than says."""
    mounts = [
        mount
        for mount in container.get("volumeMounts", [])
        if wanted.startswith(mount["mountPath"].rstrip("/") + "/")
    ]
    if len(mounts) != 1:
        refuse(f"{len(mounts)} of {owner}'s volume mounts stand over {wanted}, wanted one")
    mount = mounts[0]
    if not mount.get("readOnly"):
        refuse(f"{owner} mounts its credentials writable at {mount['mountPath']}")
    relative = wanted[len(mount["mountPath"].rstrip("/")) + 1 :]
    volume = [entry for entry in pod.get("volumes", []) if entry["name"] == mount["name"]]
    if len(volume) != 1:
        refuse(f"{owner} mounts {mount['name']}, which the pod declares {len(volume)} times")
    projection = volume[0].get("projected")
    sources = projection["sources"] if projection else [{"secret": volume[0].get("secret", {})}]
    served = {}
    for source in sources:
        secret = source.get("secret")
        if secret is None:
            refuse(f"{owner}'s {mount['name']} volume projects something other than a Secret")
        name = secret.get("name") or secret.get("secretName")
        items = secret.get("items")
        if items is None:
            # A whole Secret projected serves every key at its own name, which
            # is how the operator's hand-made credential arrives; a key added to
            # it arrives in this pod without anything saying so, and that is the
            # trade chuggy-finalizer.yaml records rather than one to relitigate.
            continue
        for item in items:
            served[item["path"]] = (name, item["key"])
    if relative not in served:
        return None
    return served[relative]


def check_credential_lists(documents, roster):
    for name, name_of_variable, path, secret_field in CREDENTIAL_SOURCES:
        document = workload(documents, "Deployment", name, CONTROL)
        pod, container = sole_container(document)
        value = json.loads(variable(container, name_of_variable, name))
        sources = at(value, path, f"{name}'s {name_of_variable}") if path else value
        declared = {source["repository"]: source["path"] for source in sources}

        strangers = sorted(
            repository
            for repository in declared
            if repository.startswith(FORGE)
            and repository not in {entry["github"] for entry in roster.values()}
        )
        if strangers:
            refuse(f"{name} carries credentials for {strangers}, which the site does not declare")

        service_paths = set()
        for key, entry in roster.items():
            if entry["github"] not in declared:
                refuse(
                    f"{name}'s {name_of_variable} has no credential for {key}: it needs "
                    f'{{"repository": "{entry["github"]}", "path": ...}}'
                )
            if entry["mirror"] not in declared:
                refuse(
                    f"{name}'s {name_of_variable} has no credential for {key}'s mirror: it "
                    f'needs {{"repository": "{entry["mirror"]}", "path": ...}}'
                )
            service_paths.add(declared[entry["mirror"]])

            wanted = declared[entry["github"]]
            if not wanted.endswith("/" + entry["credentialFile"]):
                refuse(
                    f"{name} reads {key}'s token from {wanted}; the site names that file "
                    f"{entry['credentialFile']}"
                )
            served = projected(pod, container, wanted, name)
            if served != (entry["tokens"][secret_field], "token"):
                refuse(
                    f"{name} reads {key}'s token from {wanted}, which its pod fills from "
                    f"{served}; the site mints it as {entry['tokens'][secret_field]}"
                )

        # The git service is one service with one credential class, so every
        # repository on it is read with one file. Two would mean a second class
        # nothing in this tree mints.
        if len(service_paths) != 1:
            refuse(f"{name} reads the git service with {sorted(service_paths)}, wanted one file")


def check_scheduler(documents, roster):
    scheduler = workload(documents, "Deployment", "chuggy-scheduler", CONTROL)
    _, container = sole_container(scheduler)
    forge = {entry["github"] for entry in roster.values()}

    for name_of_variable in REPOSITORY_MAPS:
        environment = json.loads(variable(container, name_of_variable, "the scheduler"))
        if REPOSITORIES_VARIABLE not in environment:
            refuse(f"{name_of_variable} carries no {REPOSITORIES_VARIABLE}")
        repositories = json.loads(environment[REPOSITORIES_VARIABLE])
        strangers = sorted(
            url for url in repositories if url.startswith(FORGE) and url not in forge
        )
        if strangers:
            refuse(f"{name_of_variable} carries {strangers}, which the site does not declare")
        for key, entry in roster.items():
            for url in (entry["github"], entry["mirror"]):
                if url not in repositories:
                    refuse(f"{name_of_variable}'s {REPOSITORIES_VARIABLE} does not carry {url}")
                if repositories[url]["url"] != url:
                    refuse(f"{name_of_variable} keys {url} to {repositories[url]['url']}")
            if repositories[entry["github"]]["credential"] != entry["workerCredential"]:
                refuse(
                    f"{name_of_variable} gives {key} the credential "
                    f"{repositories[entry['github']]['credential']}; the site names it "
                    f"{entry['workerCredential']}"
                )

    mounts = json.loads(variable(container, CREDENTIAL_MOUNTS_VARIABLE, "the scheduler"))
    policy = json.loads(variable(container, EXECUTION_POLICY_VARIABLE, "the scheduler"))
    mirrors = json.loads(variable(container, SESSION_POLICY_VARIABLE, "the scheduler"))["mirrors"]
    for key, entry in roster.items():
        credential = entry["workerCredential"]
        mount = mounts.get(credential)
        if mount is None:
            refuse(f"{CREDENTIAL_MOUNTS_VARIABLE} has no mount for {key}'s {credential}")
        if (mount["secretName"], mount["key"]) != (entry["tokens"]["workerSecret"], "token"):
            refuse(
                f"{credential} is mounted from {mount['secretName']}/{mount['key']}; the site "
                f"mints {key}'s worker token as {entry['tokens']['workerSecret']}"
            )
        for pass_name, arm in policy.items():
            if credential not in arm["grant"]["credentials"]:
                refuse(
                    f"the {pass_name} grant does not name {credential}, so an attempt in {key} "
                    "is placed without a credential for its forge"
                )
        if mirrors.get(entry["github"]) != entry["mirror"]:
            refuse(
                f"the session policy mirrors {key} at {mirrors.get(entry['github'])}; the site "
                f"names its mirror {entry['mirror']}"
            )


def check_mirror(documents, roster):
    job = workload(documents, "CronJob", "chuggy-git-mirror", WORK)
    pod, container = sole_container(job)
    entries = {
        without_userinfo(row["source"]): row
        for row in rows(
            variable(container, MIRROR_REPOSITORIES_VARIABLE, "the mirror job"),
            ("source", "target", "credential"),
            MIRROR_REPOSITORIES_VARIABLE,
        )
    }
    strangers = sorted(set(entries) - {entry["github"] for entry in roster.values()})
    if strangers:
        refuse(f"the mirror job follows {strangers}, which the site does not declare")
    for key, entry in roster.items():
        row = entries.get(entry["github"])
        if row is None:
            refuse(f"the mirror job does not follow {key} at {entry['github']}")
        if without_userinfo(row["target"]) != entry["mirror"]:
            refuse(
                f"the mirror job keeps {without_userinfo(row['target'])} equal to {key}; the "
                f"site names its mirror {entry['mirror']}"
            )
        if row["credential"] != entry["workerCredential"]:
            refuse(
                f"the mirror job follows {key} with {row['credential']}; the site names that "
                f"credential {entry['workerCredential']}"
            )
        wanted = "/var/run/chuggy/credentials/" + row["credential"]
        served = projected(pod, container, wanted, "chuggy-git-mirror")
        if served != (entry["tokens"]["workerSecret"], "token"):
            refuse(
                f"chuggy-git-mirror reads {key}'s token from {wanted}, which its pod fills from "
                f"{served}; the site mints it as {entry['tokens']['workerSecret']}"
            )


def check_importer(documents, roster):
    job = workload(documents, "CronJob", "chuggy-configuration-importer", CONTROL)
    pod, container = sole_container(job)
    entries = {
        row["repository"]: row
        for row in rows(
            variable(container, IMPORT_REPOSITORIES_VARIABLE, "the importer"),
            ("repository", "credential"),
            IMPORT_REPOSITORIES_VARIABLE,
        )
    }
    wanted = {entry["github"] for entry in roster.values() if entry["imported"]}
    if set(entries) != wanted:
        refuse(
            f"the importer imports {sorted(entries)}; the site declares {sorted(wanted)} "
            "imported, and a repository whose configurations are never read is one whose "
            "tickets can never be authored"
        )
    for key, entry in roster.items():
        if not entry["imported"]:
            continue
        row = entries[entry["github"]]
        if row["credential"] != entry["credentialFile"]:
            refuse(
                f"the importer reads {key} with {row['credential']}; the site names that file "
                f"{entry['credentialFile']}"
            )
        served = projected(pod, container, "/var/run/chuggy/repository-credentials/"
                           + row["credential"], "the importer")
        if served != (entry["tokens"]["readerSecret"], "token"):
            refuse(
                f"the importer reads {key}'s token from a file its pod fills from {served}; "
                f"the site mints it as {entry['tokens']['readerSecret']}"
            )


def check_roster(roster):
    """The key is the repository's name on both forges, which is what lets one
    entry name a repository in every place without repeating the name."""
    for key, entry in roster.items():
        for field in ("github", "mirror"):
            if not entry[field].endswith(f"/{key}.git"):
                refuse(f"{key}'s {field} is {entry[field]}, which does not name {key}.git")


def main():
    if len(sys.argv) != 3:
        refuse("usage: github-repository-transition.py ROSTER RENDERED_MANIFEST")
    with open(sys.argv[1], encoding="utf-8") as handle:
        roster = json.load(handle)
    if not roster:
        refuse("the site declares no repositories")
    documents = objects(sys.argv[2])
    check_roster(roster)
    check_credential_lists(documents, roster)
    check_scheduler(documents, roster)
    check_mirror(documents, roster)
    check_importer(documents, roster)


main()
