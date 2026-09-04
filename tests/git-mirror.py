#!/usr/bin/env python3
"""Refuse a rendered cluster whose mirror sync moves something other than the
repository a session is told to read.

kasofsk/chuggy#554 is what this gate is the record of: the in-cluster mirror
stood still while `kasofsk/chuggy`'s `main` moved, and every object involved
read correctly on its own. A job that fetches and pushes is easy; a job that
fetches and pushes THE RIGHT TWO REPOSITORIES is the part nothing else here
would notice going wrong, because the URLs are written once in this job, once in
the scheduler's mirrors map, once in its repositories map and once in the
importer's script, and a run against the wrong pair succeeds.

So nothing below is a URL literal. The pair this job moves must BE an entry of
`CHUG_SCHEDULER_SESSION_POLICY`'s `mirrors` map -- the map that decides what a
session clones in place of its project's binding -- and the source must also be
the repository the configuration importer pins a revision from. Those are the
two halves of the defect: what a lead reads, and what its tickets are pinned to.

A CREDENTIAL IS THREE OBJECTS AND EACH READS CORRECTLY ALONE. A URL carries a
username, a projected volume carries a file, and an askpass helper cats a path.
Get any one wrong and git prompts for a password on a terminal that does not
exist, which is a hung run and not a message. So the three are resolved against
each other, and the source's against the site's maps as well: its username
against the repositories map, its secret and key against the credential mounts
the scheduler declares.

THE TARGET'S CREDENTIAL IS THE MIRROR'S OWN AND THE MAPS CANNOT RESOLVE IT.
Pushing as the worker is what the first run of this job did, and the git
service's `pre-receive` hook refused it: `worker` may create an attempt-scoped
ticket branch and nothing else. So the class below is a fourth one, named here
because there is no site map that carries it -- and what IS resolved is that no
credential the scheduler mounts into a worker or session pod is this one, and
that the username a worker uses at this repository is not this one. Those two
are the header's claim that the pod holds a credential nothing else in its
namespace holds, and they fail if either class is quietly given the other's.

A POD IN `chuggy-work` THAT NO POLICY SELECTS IS ISOLATED IN NEITHER DIRECTION,
and one selected by two inherits the wider. Both are silent. So the policies are
resolved against this pod's own labels out of the render, exactly one must
select it, and the destinations it may reach are compared against the session's
arms reaching the same ports rather than written here -- the same relative
expectation `session-placement.py` makes, and for the same reason.

WHAT THIS GATE CANNOT SEE. It says nothing about which refs the hook admits the
mirror's credential to move: that hook is on a repository this tree does not
declare, `deploy/rig/git/` in kasofsk/chuggy is where it is written, and a run
on the rig is what answers it. It says nothing about whether the Secret named
below exists in the namespace yet. It says nothing about the schedule being
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
IMPORT_REPOSITORY_VARIABLE = "CHUG_CONFIGURATION_IMPORT_REPOSITORY"

SOURCE_VARIABLE = "CHUG_GIT_MIRROR_SOURCE"
TARGET_VARIABLE = "CHUG_GIT_MIRROR_TARGET"
BRANCH_VARIABLE = "CHUG_GIT_MIRROR_BRANCH"

CREDENTIAL_ROOT = "/var/run/chuggy/credentials"
CREDENTIAL_PATH = re.compile(r"/var/run/chuggy/credentials/[A-Za-z0-9._-]+")

# The mirror's own credential class, which is written here because no map in the
# render carries it: the git service's `git-mirror` user, copied into this
# namespace as a Secret of the same shape the worker's credentials have.
MIRROR_USERNAME = "mirror"
MIRROR_SECRET = ("chuggy-git-mirror", "password")

# Where this pod may go, as (protocol, port): the resolver, the git service that
# carries the mirror, and public HTTPS for the source. The set is exact, so
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


def credential_file(script, helper):
    found = CREDENTIAL_PATH.findall(script)
    if len(found) != 1:
        refuse(f"{helper} names {len(found)} credential files, wanted one")
    return found[0]


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

    # 4. The pair it moves is a pair the scheduler tells a session to read.
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

    source_user, source = split_userinfo(
        variable(container, SOURCE_VARIABLE, JOB), SOURCE_VARIABLE
    )
    target_user, target = split_userinfo(
        variable(container, TARGET_VARIABLE, JOB), TARGET_VARIABLE
    )
    if mirrors.get(source) != target:
        refuse(
            f"this job keeps {target} equal to {source}; the session policy mirrors "
            f"{json.dumps(mirrors)}, and a mirror nothing moves is #554"
        )

    # 5. The source is the repository a project's configuration is pinned from.
    #    A mirror kept equal to some other tree is the same defect with a
    #    different URL in it.
    importer = one(documents, "CronJob", IMPORTER, CONTROL)
    importing = sole_container(
        importer["spec"]["jobTemplate"]["spec"]["template"]["spec"], IMPORTER
    )
    imported = variable(importing, IMPORT_REPOSITORY_VARIABLE, "the importer")
    if imported != source:
        refuse(f"this job follows {source}; the importer pins revisions from {imported}")

    # 6. The branch. The importer resolves it inside a shell script, so this one
    #    assertion is a text comparison: there is nothing structural to hold it
    #    against, and what it buys is that the two cannot name different branches.
    branch = variable(container, BRANCH_VARIABLE, JOB)
    import_script = one(documents, "ConfigMap", IMPORTER, CONTROL)["data"]["import.sh"]
    if f"refs/heads/{branch}" not in import_script:
        refuse(f"this job keeps {branch} equal; the importer's script resolves another branch")

    # 7. The source's username, secret and file, which are three objects that
    #    each read correctly alone, resolved against the site's own maps.
    volumes = pod.get("volumes", [])
    scripts = one(documents, "ConfigMap", JOB, WORK)["data"]

    def helper_serves(role):
        """The (secret, key) the role's askpass helper actually prints."""
        helper = f"{role}-askpass.sh"
        if helper not in scripts:
            refuse(f"the sync ConfigMap carries no {helper}")
        wanted = credential_file(scripts[helper], helper)
        if not wanted.startswith(CREDENTIAL_ROOT + "/"):
            refuse(f"{helper} reads {wanted}, which is outside {CREDENTIAL_ROOT}")
        return helper, wanted, projected_path(container, volumes, wanted, JOB)

    entry = repositories.get(source)
    if entry is None:
        refuse(f"the source {source} is not a repository the site's map carries")
    if source_user != entry["credentialUsername"]:
        refuse(
            f"the source URL authenticates as {source_user!r}; the site's map says "
            f"{entry['credentialUsername']!r}"
        )
    mount = mounts.get(entry["credential"])
    if mount is None:
        refuse(f"the source's credential {entry['credential']} has no mount to take it from")
    helper, wanted, served = helper_serves("source")
    if served != (mount["secretName"], mount["key"]):
        refuse(
            f"{helper} reads {wanted}, which this pod fills from {served}; the site's "
            f"map says {entry['credential']} is {mount['secretName']}/{mount['key']}"
        )

    # 8. The target's three, which are the mirror's own class. The site's maps
    #    bind this repository to the worker, and the worker is exactly who the
    #    hook refuses on `main` -- so here the maps say what this must NOT be.
    binding = repositories.get(target)
    if binding is None:
        refuse(f"the target {target} is not a repository the site's map carries")
    if target_user != MIRROR_USERNAME:
        refuse(
            f"the target URL authenticates as {target_user!r}; this job pushes as "
            f"{MIRROR_USERNAME!r}, which is the class the git service's hook admits to `main`"
        )
    if target_user == binding["credentialUsername"]:
        refuse(
            f"the site's map gives a session {target_user!r} at {target}, so the mirror's "
            "class and the worker's have become one credential"
        )
    helper, wanted, served = helper_serves("target")
    if served != MIRROR_SECRET:
        refuse(
            f"{helper} reads {wanted}, which this pod fills from {served}; the mirror pushes "
            f"with {MIRROR_SECRET[0]}/{MIRROR_SECRET[1]} and nothing else"
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


main()
