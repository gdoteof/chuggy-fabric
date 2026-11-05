#!/usr/bin/env python3
"""Refuse a host whose contract publish token is not the one the Task mounts.

usage: contract-publish-token.py HOST_APPS_AND_TOKENS RENDERED_BUILD_SYSTEM

The token is minted on the host and read by a pod, with a name between them
that is written twice. A Secret the host names one way and the Task another is
a Task that starts, finds nothing mounted, and fails the one run in a hundred
that has a contract to release -- which is the day a ticket waits on it.

WHAT IS HELD, OF THE ENTRY THE HOST DECLARES:

- there is one, and it is the only entry that delivers to `chuggy-build`: a
  second Secret the host minted there would be one more a build pod could
  mount, and the policy in contract-publish.yaml holds one name;
- it delivers the name the Task's volume reads, into the namespace the Task
  runs in and no other;
- it is a token for the repository the Task's run releases on, and `write`,
  which a release needs and a read token cannot make;
- it is minted as the portal App and from that App's key file, by the id and
  the path the host declares for it, and not by the worker App, which agent-
  executed pods mint from and which the rulesets keep off `main`.

WHAT THIS CANNOT SEE. Whether the App is installed on the repository, whether
`installationId` is its installation, and what the ruleset does to a tag
created by it: GitHub holds all three.
"""

import json
import sys

import yaml

TOKEN = "contract-publish"
TASK = "publish-worker-contract"
RUN_CONFIG = "contract-publish-run.yaml"
BUILD = "chuggy-build"
APP = "portal"


def refuse(message):
    raise SystemExit(f"contract-publish-token: {message}")


def main():
    if len(sys.argv) != 3:
        refuse("usage: contract-publish-token.py HOST_APPS_AND_TOKENS RENDERED_BUILD_SYSTEM")
    host = json.load(open(sys.argv[1], encoding="utf-8"))
    apps, tokens = host["apps"], host["tokens"]
    with open(sys.argv[2], encoding="utf-8") as handle:
        documents = [document for document in yaml.safe_load_all(handle) if document]

    token = tokens.get(TOKEN)
    if token is None:
        refuse(f"the host declares no token {TOKEN}, and the Task {TASK} mounts one")
    delivering = sorted(name for name, other in tokens.items() if BUILD in other["namespaces"])
    if delivering != [TOKEN]:
        refuse(f"the host delivers tokens {delivering} into {BUILD}, and the policy holds one Secret there")

    (task,) = [d for d in documents if d["kind"] == "Task" and d["metadata"]["name"] == TASK]
    secrets = [volume["secret"] for volume in task["spec"]["volumes"] if "secret" in volume]
    if [secret["secretName"] for secret in secrets] != [token["secretName"]]:
        refuse(f"the Task reads {[secret['secretName'] for secret in secrets]} and the host mints {token['secretName']}")
    if token["namespaces"] != [task["metadata"]["namespace"]]:
        refuse(f"the host delivers into {token['namespaces']}, and the Task runs in {task['metadata']['namespace']}")
    if token["permission"] != "write":
        refuse(f"the token is {token['permission']}, and a release is made with a write")

    (config,) = [d for d in documents if d["kind"] == "ConfigMap" and RUN_CONFIG in d.get("data", {})]
    (run,) = [d for d in yaml.safe_load_all(config["data"][RUN_CONFIG]) if d]
    repository = {param["name"]: param["value"] for param in run["spec"]["params"]}["repository"]
    if repository.partition("/")[2] != token["repository"]:
        refuse(f"the token is for {token['repository']} and the run releases on {repository}")

    portal = apps[APP]
    if token["appId"] != portal["appId"] or token["privateKeyFile"] != portal["privateKeyFile"]:
        refuse(f"the token is not minted as the {APP} App from its key file")


if __name__ == "__main__":
    main()
