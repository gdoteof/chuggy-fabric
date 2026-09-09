#!/usr/bin/env python3
"""Refuse a rendered cluster whose mirror sync moves something other than the
repositories a session is told to read.

kasofsk/chuggy#554 is what this gate is the record of: the in-cluster mirror
stood still while `kasofsk/chuggy`'s `main` moved, and every object involved
read correctly on its own. A job that fetches and pushes is easy; a job that
fetches and pushes THE RIGHT REPOSITORIES is the part nothing else here would
notice going wrong, because each pair is written once in this job, once in the
scheduler's mirrors map, once in its repositories map and once in the importer's
list, and a run against the wrong pair succeeds.

So nothing below is a URL literal. Every pair this job moves must BE an entry of
`CHUG_SCHEDULER_SESSION_POLICY`'s `mirrors` map -- the map that decides what a
session clones in place of its project's binding -- and every repository the
importer pins revisions from must be one of the sources. Those are the two
halves of the defect: what a lead reads, and what its tickets are pinned to.

ONE JOB OVER A LIST, SO EVERY ASSERTION IS PER ENTRY. A second CronJob with two
names changed would be a second schedule and a second policy, and this file
would have to be told about it; a list is checked by iterating it, and an entry
that is not in the site's maps is refused by the same code that refuses the
first.

A CREDENTIAL IS THREE OBJECTS AND EACH READS CORRECTLY ALONE. A URL carries a
username, a projected volume carries a file, and the entry names which file.
Get any one wrong and git prompts for a password on a terminal that does not
exist, which is a hung run and not a message. So the three are resolved against
each other, and each source's against the site's own maps as well: its username
against the repositories map, its file against the credential mount the
scheduler declares for that repository's credential.

THE SOURCE HELPER PRINTS NO LITERAL, and that is checked rather than assumed: it
prints the file the run names for the entry it is on, so a literal path in it
would be one repository's token served for every source.

THE TARGET'S CREDENTIAL IS THE MIRROR'S OWN AND THE MAPS CANNOT RESOLVE IT.
Pushing as the worker is what the first run of this job did, and the git
service's `pre-receive` hook refused it: `worker` may create an attempt-scoped
ticket branch and nothing else. So the class below is a fourth one, named here
because there is no site map that carries it -- and what IS resolved is that no
credential the scheduler mounts into a worker or session pod is this one, and
that the username a worker uses at these repositories is not this one. Those two
are the header's claim that the pod holds a credential nothing else in its
namespace holds, and they fail if either class is quietly given the other's.

THE DEADLINE IS A FUNCTION OF THE LIST'S LENGTH. Every remote a run cannot reach
costs the retry window in `head_of`, and a list long enough for those windows to
exceed the Job's `activeDeadlineSeconds` is a run killed mid-fetch -- which is a
mirror that stops moving and reports DeadlineExceeded rather than which remote
failed. So the window is read out of the script, multiplied by the two remotes
of every entry, and held under the deadline.

A POD IN `chuggy-work` THAT NO POLICY SELECTS IS ISOLATED IN NEITHER DIRECTION,
and one selected by two inherits the wider. Both are silent. So the policies are
resolved against this pod's own labels out of the render, exactly one must
select it, and the destinations it may reach are compared against the session's
arms reaching the same ports rather than written here -- the same relative
expectation `session-placement.py` makes, and for the same reason.

WHAT THIS GATE CANNOT SEE. It says nothing about which refs the hook admits the
mirror's credential to move, nor about whether a bare repository exists on the
service at all: that hook and those repositories are on a service this tree does
not declare, `deploy/rig/git/` in kasofsk/chuggy is where it is written, and a
run on the rig is what answers it. It says nothing about whether the Secrets
named below exist in the namespace yet. It says nothing about the schedule being
often enough. And two things are written here rather than resolved: the branch,
which the importer names inside a shell script, so there is nothing structural
to compare against, and the mirror's class, for the reason above.
"""

import json
import re
import sys
from urllib.parse import urlsplit, urlunsplit

import yaml

WORK = "chuggy-work"
CONTROL = "chuggy"
JOB = "chuggy-git-mirror"
IMPORTER = "chuggy-configuration-importer"

SESSION_POLICY_VARIABLE = "CHUG_SCHEDULER_SESSION_POLICY"
SESSION_ENVIRONMENT_VARIABLE = "CHUG_SCHEDULER_SESSION_ENVIRONMENT"
CREDENTIAL_MOUNTS_VARIABLE = "CHUG_SCHEDULER_WORKER_CREDENTIAL_MOUNTS"
REPOSITORIES_VARIABLE = "CHUG_WORKER_REPOSITORIES"
IMPORT_REPOSITORIES_VARIABLE = "CHUG_CONFIGURATION_IMPORT_REPOSITORIES"

MIRROR_REPOSITORIES_VARIABLE = "CHUG_GIT_MIRROR_REPOSITORIES"
BRANCH_VARIABLE = "CHUG_GIT_MIRROR_BRANCH"
SOURCE_CREDENTIAL_VARIABLE = "CHUG_GIT_MIRROR_SOURCE_CREDENTIAL"

CREDENTIAL_ROOT = "/var/run/chuggy/credentials"
CREDENTIAL_PATH = re.compile(r"/var/run/chuggy/credentials/[A-Za-z0-9._-]+")

# The mirror's own credential class, which is written here because no map in the
# render carries it: the git service's `git-mirror` user, copied into this
# namespace as a Secret of the same shape the worker's credentials have.
MIRROR_USERNAME = "mirror"
MIRROR_SECRET = ("chuggy-git-mirror", "password")

# Where this pod may go, as (protocol, port): the resolver, the git service that
# carries the mirrors, and public HTTPS for the sources. The set is exact, so
# gaining a destination is a finding rather than a silent widening -- and what
# it must NOT gain is the rest of what its namespace permits its neighbours,
# which is PostgreSQL, the worker plane and the API.
EGRESS = {("UDP", 53), ("TCP", 53), ("TCP", 8080), ("TCP", 443)}


def refuse(message):
    raise SystemExit(f"git mirror: {message}")


def objects(path):
    with open(path, encoding="utf-8") as handle:
        return [document for document in yaml.safe_load_all(handle) if document]


def one(documents, kind, name, namespace):
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


def sole_container(spec, name):
    containers = spec["containers"]
    if len(containers) != 1:
        refuse(f"{name} declares {len(containers)} containers, wanted one")
    return containers[0]


def variable(container, name, owner):
    found = [entry for entry in container.get("env", []) if entry["name"] == name]
    if len(found) != 1:
        refuse(f"{owner} declares {name} {len(found)} times, wanted once")
    value = found[0].get("value")
    if value is None:
        refuse(f"{owner} takes {name} from somewhere other than a literal")
    return value


def rows(value, columns, owner):
    """The non-empty lines of a configured list, each split into exactly the
    columns named. A line of another shape is one the run itself reports and
    fails on, so a render carrying one is refused here instead."""
    parsed = []
    for line in value.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) != len(columns):
            refuse(f"{owner} carries {line.strip()!r}, which is not {', '.join(columns)}")
        parsed.append(dict(zip(columns, fields)))
    if not parsed:
        refuse(f"{owner} carries no entries, so nothing is followed")
    return parsed


def ports(rule, owner):
    if "ports" not in rule:
        refuse(f"a {owner} rule names no ports, which admits every port")
    return {(port.get("protocol", "TCP"), port["port"]) for port in rule["ports"]}


def peers(rule, owner):
    if "to" not in rule:
        refuse(f"a {owner} egress rule names no destination, which reaches everything")
    return rule["to"]


def split_userinfo(url, owner):
    """A URL's username, and the URL without it. A credential's username is part
    of the address here and not of the secret, so the two halves are separated
    once and compared apart."""
    parts = urlsplit(url)
    if parts.hostname is None:
        refuse(f"{owner} is not a URL with a host: {url}")
    if parts.password is not None:
        refuse(f"{owner} carries a password in its URL, which is a secret in a manifest")
    host = parts.hostname
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return parts.username, urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def only_number(pattern, script, description):
    found = re.findall(pattern, script)
    if len(found) != 1:
        refuse(f"sync.sh states {description} {len(found)} times, wanted once")
    return int(found[0])


def projected_path(container, volumes, wanted, owner):
    """The (secret, key) a container serves at an absolute path, or a refusal.

    The failure this resolves is a helper reading a file the volume does not
    project: git then asks for a password, there is no terminal, and the run
    hangs until its deadline rather than saying anything.
    """
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
    volume = [entry for entry in volumes if entry["name"] == mount["name"]]
    if len(volume) != 1:
        refuse(f"{owner} mounts {mount['name']}, which the pod declares {len(volume)} times")
    sources = volume[0].get("projected", {}).get("sources")
    if sources is None:
        refuse(f"{owner}'s {mount['name']} volume is not a projection of Secrets")
    served = {}
    for source in sources:
        secret = source.get("secret")
        if secret is None:
            refuse(f"{owner}'s {mount['name']} volume projects something other than a Secret")
        items = secret.get("items")
        if items is None:
            refuse(
                f"{owner} projects every key of {secret['name']}, so a key added to that "
                "Secret arrives in this pod without anything saying so"
            )
        for item in items:
            served[item["path"]] = (secret["name"], item["key"])
    if relative not in served:
        refuse(f"{owner} reads {wanted}, which its credential volume does not project")
    return served[relative]


def main():
    if len(sys.argv) != 2:
        refuse("usage: git-mirror.py RENDERED_MANIFEST")
    documents = objects(sys.argv[1])

    job = one(documents, "CronJob", JOB, WORK)
    template = job["spec"]["jobTemplate"]["spec"]["template"]
    labels = template["metadata"].get("labels", {})
    if not labels:
        refuse("the sync pod carries no labels, so no policy in chuggy-work selects it")
    pod = template["spec"]
    container = sole_container(pod, JOB)

    # 1. The image is pinned by digest. A tag on a public image is a different
    #    binary tomorrow, and this one runs with a credential that moves a branch.
    if "@sha256:" not in container["image"]:
        refuse(f"the sync container runs {container['image']}, which is not pinned by digest")

    # 2. Exactly one NetworkPolicy in the namespace selects this pod. Policies
    #    are additive: a second would widen it silently, and none at all would
    #    leave it isolated in neither direction, which is the worse of the two.
    selecting = [
        document
        for document in documents
        if document.get("kind") == "NetworkPolicy"
        and document["metadata"].get("namespace") == WORK
        and all(
            labels.get(key) == value
            for key, value in document["spec"]["podSelector"].get("matchLabels", {}).items()
        )
    ]
    if len(selecting) != 1:
        names = sorted(document["metadata"]["name"] for document in selecting)
        refuse(f"{len(names)} policies in {WORK} select the sync pod ({names}), wanted one")
    policy = selecting[0]
    if set(policy["spec"].get("policyTypes", [])) != {"Ingress", "Egress"}:
        refuse("the sync pod's policy does not isolate it in both directions")
    if policy["spec"].get("ingress") != []:
        refuse("the sync pod's policy admits something; nothing opens a connection to a Job")

    # 3. Where it may go, exactly, and each arm's destination compared against
    #    the session's arm reaching the same place rather than written here.
    sessions = one(documents, "NetworkPolicy", "chuggy-sessions", WORK)
    session_arms = {
        frozenset(ports(rule, "chuggy-sessions")): peers(rule, "chuggy-sessions")
        for rule in sessions["spec"]["egress"]
    }
    reached = set()
    for rule in policy["spec"]["egress"]:
        opened = ports(rule, "the sync pod")
        reached |= opened
        counterpart = session_arms.get(frozenset(opened))
        if counterpart is None:
            refuse(f"the sync pod reaches {sorted(opened)}, which no session arm reaches")
        if peers(rule, "the sync pod") != counterpart:
            refuse(
                f"the sync pod's arm for {sorted(opened)} names a different destination than "
                "the session arm on the same ports"
            )
    if reached != EGRESS:
        refuse(f"the sync pod reaches {sorted(reached)}, expected {sorted(EGRESS)}")

    # 4. What the site says exists, and what a session is told to clone.
    scheduler = one(documents, "Deployment", "chuggy-scheduler", CONTROL)
    scheduling = sole_container(scheduler["spec"]["template"]["spec"], "chuggy-scheduler")
    session_policy = json.loads(variable(scheduling, SESSION_POLICY_VARIABLE, "the scheduler"))
    mirrors = session_policy.get("mirrors")
    if not mirrors:
        refuse("the session policy names no mirrors, so no session reads one")
    repositories = json.loads(
        json.loads(variable(scheduling, SESSION_ENVIRONMENT_VARIABLE, "the scheduler"))[
            REPOSITORIES_VARIABLE
        ]
    )
    mounts = json.loads(variable(scheduling, CREDENTIAL_MOUNTS_VARIABLE, "the scheduler"))

    volumes = pod.get("volumes", [])
    scripts = one(documents, "ConfigMap", JOB, WORK)["data"]

    # 5. The source helper prints the run's file and no literal, so one entry's
    #    token cannot be served for every source.
    helper = "source-askpass.sh"
    if helper not in scripts:
        refuse(f"the sync ConfigMap carries no {helper}")
    literal = CREDENTIAL_PATH.findall(scripts[helper])
    if literal:
        refuse(f"{helper} prints {literal[0]}, so every source is served one entry's credential")
    if f"${SOURCE_CREDENTIAL_VARIABLE}" not in scripts[helper]:
        refuse(f"{helper} does not print the file {SOURCE_CREDENTIAL_VARIABLE} names")
    sync = scripts.get("sync.sh")
    if sync is None:
        refuse("the sync ConfigMap carries no sync.sh")
    if f'{SOURCE_CREDENTIAL_VARIABLE}="$credentials/$3"' not in sync:
        refuse(f"sync.sh does not set {SOURCE_CREDENTIAL_VARIABLE} from the entry's own column")
    if f"credentials={CREDENTIAL_ROOT}\n" not in sync:
        refuse(f"sync.sh reads its credentials from somewhere other than {CREDENTIAL_ROOT}")

    # 6. Every pair this job moves is a pair the scheduler tells a session to
    #    read, and each source's three credential objects agree with the site's
    #    own maps.
    entries = rows(
        variable(container, MIRROR_REPOSITORIES_VARIABLE, JOB),
        ("source", "target", "credential"),
        MIRROR_REPOSITORIES_VARIABLE,
    )
    followed = set()
    for entry in entries:
        source_user, source = split_userinfo(entry["source"], "a mirror source")
        target_user, target = split_userinfo(entry["target"], "a mirror target")
        followed.add(source)
        if mirrors.get(source) != target:
            refuse(
                f"this job keeps {target} equal to {source}; the session policy mirrors "
                f"{json.dumps(mirrors)}, and a mirror nothing moves is #554"
            )

        binding = repositories.get(source)
        if binding is None:
            refuse(f"the source {source} is not a repository the site's map carries")
        if source_user != binding["credentialUsername"]:
            refuse(
                f"the source URL for {source} authenticates as {source_user!r}; the site's "
                f"map says {binding['credentialUsername']!r}"
            )
        mount = mounts.get(binding["credential"])
        if mount is None:
            refuse(
                f"the credential {binding['credential']} the site's map gives {source} has "
                "no mount to take it from"
            )
        wanted = f"{CREDENTIAL_ROOT}/{entry['credential']}"
        served = projected_path(container, volumes, wanted, JOB)
        if served != (mount["secretName"], mount["key"]):
            refuse(
                f"{source} is followed with {wanted}, which this pod fills from {served}; "
                f"the site's map says {binding['credential']} is "
                f"{mount['secretName']}/{mount['key']}"
            )

        # 7. The target's, which are the mirror's own class. The site's maps
        #    bind this repository to the worker, and the worker is exactly who
        #    the hook refuses on `main` -- so here the maps say what this must
        #    NOT be.
        mirrored = repositories.get(target)
        if mirrored is None:
            refuse(f"the target {target} is not a repository the site's map carries")
        if target_user != MIRROR_USERNAME:
            refuse(
                f"the target URL for {target} authenticates as {target_user!r}; this job "
                f"pushes as {MIRROR_USERNAME!r}, which is the class the git service's hook "
                "admits to `main`"
            )
        if target_user == mirrored["credentialUsername"]:
            refuse(
                f"the site's map gives a session {target_user!r} at {target}, so the mirror's "
                "class and the worker's have become one credential"
            )

    # 8. The target helper is one file for every entry, and it is the mirror's.
    helper = "target-askpass.sh"
    if helper not in scripts:
        refuse(f"the sync ConfigMap carries no {helper}")
    literal = CREDENTIAL_PATH.findall(scripts[helper])
    if len(literal) != 1:
        refuse(f"{helper} names {len(literal)} credential files, wanted one")
    served = projected_path(container, volumes, literal[0], JOB)
    if served != MIRROR_SECRET:
        refuse(
            f"{helper} reads {literal[0]}, which this pod fills from {served}; the mirror "
            f"pushes with {MIRROR_SECRET[0]}/{MIRROR_SECRET[1]} and nothing else"
        )
    # Every credential a worker or session pod can hold is a mount the scheduler
    # declares, so this is the whole of "no other pod in this namespace holds
    # it" -- and it is that, rather than the name, which makes the extra
    # credential in this pod arguable.
    for name, declared in mounts.items():
        if (declared["secretName"], declared["key"]) == MIRROR_SECRET:
            refuse(
                f"the scheduler mounts {MIRROR_SECRET[0]}/{MIRROR_SECRET[1]} as {name}, so every "
                "worker and session pod holds the mirror's credential too"
            )

    # 9. Every repository a project's configuration is pinned from is one this
    #    job follows. A mirror kept equal to some other tree is #554 with a
    #    different URL in it; a repository imported and not followed is #554
    #    itself.
    importer = one(documents, "CronJob", IMPORTER, CONTROL)
    importing = sole_container(
        importer["spec"]["jobTemplate"]["spec"]["template"]["spec"], IMPORTER
    )
    imported = {
        row["repository"]
        for row in rows(
            variable(importing, IMPORT_REPOSITORIES_VARIABLE, "the importer"),
            ("repository", "credential"),
            IMPORT_REPOSITORIES_VARIABLE,
        )
    }
    missing = sorted(imported - followed)
    if missing:
        refuse(f"the importer pins revisions from {missing}, which this job does not follow")

    # 10. The branch. The importer resolves it inside a shell script, so this
    #     one assertion is a text comparison: there is nothing structural to
    #     hold it against, and what it buys is that the two cannot name
    #     different branches.
    branch = variable(container, BRANCH_VARIABLE, JOB)
    import_script = one(documents, "ConfigMap", IMPORTER, CONTROL)["data"]["import.sh"]
    if f"refs/heads/{branch}" not in import_script:
        refuse(f"this job keeps {branch} equal; the importer's script resolves another branch")

    # 11. The deadline covers every entry's two remotes refusing to answer,
    #     read out of the retry window this script actually declares.
    attempts = only_number(r'"\$attempt" -ge ([0-9]+)', sync, "its attempt ceiling")
    timeout = only_number(r"timeout ([0-9]+)s", sync, "its per-attempt timeout")
    backoff = only_number(r"sleep ([0-9]+)", sync, "its backoff")
    window = attempts * timeout + (attempts - 1) * backoff
    deadline = job["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"]
    if deadline <= 2 * len(entries) * window:
        refuse(
            f"{len(entries)} repositories are followed and each remote's window is {window}s, "
            f"so a run reaching none of them outlives activeDeadlineSeconds: {deadline}"
        )


main()
