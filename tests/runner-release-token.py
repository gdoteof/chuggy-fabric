#!/usr/bin/env python3
"""Refuse a host whose runner release tokens are not the ones the Task mounts.

usage: runner-release-token.py HOST_APPS_AND_TOKENS RENDERED_BUILD_SYSTEM

contract-publish-token.py's argument, for the Task that releases the runner
packages: the name between the host's Secret and the Task's volume is written
twice, and a Secret named one way and read another is a release run that
starts, finds nothing mounted, and fails on the day a package is released.

WHAT IS HELD, OF THE ENTRIES THE HOST DECLARES:

- there is one for each package a run file releases, `runner-release-<package>`,
  and no other entry of that prefix;
- each delivers the name the Task's volume reads once `$(params.package)` is
  that package, into the namespace the Task runs in and no other, and that
  name is one the token policy in runner-release.yaml holds;
- each is a token for that package's repository and `write`, which a release
  needs;
- each is minted as the portal App and from that App's key file, as the
  contract publish's is, and not by the worker App.

That these and the contract publish's are the only entries delivering into
`chuggy-build` is contract-publish-token.py's to hold.

WHAT THIS CANNOT SEE. Whether the App is installed on each repository, and
whether `installationId` is that installation: GitHub holds both.
"""

import json
import sys

import yaml

PREFIX = "runner-release-"
TASK = "publish-runner-release"
TOKEN_POLICY = "runner-release-token-has-one-reader"
RUNS = ("runner-release-chuggy-linux-run.yaml", "runner-release-chuggy-darwin-run.yaml")
APP = "portal"


def refuse(message):
    raise SystemExit(f"runner-release-token: {message}")


def main():
    if len(sys.argv) != 3:
        refuse("usage: runner-release-token.py HOST_APPS_AND_TOKENS RENDERED_BUILD_SYSTEM")
    host = json.load(open(sys.argv[1], encoding="utf-8"))
    apps, tokens = host["apps"], host["tokens"]
    with open(sys.argv[2], encoding="utf-8") as handle:
        documents = [document for document in yaml.safe_load_all(handle) if document]

    packages = []
    for file in RUNS:
        (config,) = [d for d in documents if d["kind"] == "ConfigMap" and file in d.get("data", {})]
        (run,) = [d for d in yaml.safe_load_all(config["data"][file]) if d]
        packages.append({param["name"]: param["value"] for param in run["spec"]["params"]}["package"])
    declared = sorted(name for name in tokens if name.startswith(PREFIX))
    if declared != sorted(PREFIX + package for package in packages):
        refuse(f"the host declares {declared}, and the run files release {packages}")

    (task,) = [d for d in documents if d["kind"] == "Task" and d["metadata"]["name"] == TASK]
    (secret,) = [volume["secret"] for volume in task["spec"]["volumes"] if "secret" in volume]
    (policy,) = [d for d in documents if d["kind"] == "ValidatingAdmissionPolicy" and d["metadata"]["name"] == TOKEN_POLICY]
    reaches = next(variable["expression"] for variable in policy["spec"]["variables"] if variable["name"] == "reaches")
    portal = apps[APP]
    for package in packages:
        token = tokens[PREFIX + package]
        read = secret["secretName"].replace("$(params.package)", package)
        if token["secretName"] != read:
            refuse(f"the Task reads {read} for {package} and the host mints {token['secretName']}")
        if json.dumps(read) not in reaches:
            refuse(f"the policy {TOKEN_POLICY} does not name {read}, and a pod mounting it is then held to nothing")
        if token["namespaces"] != [task["metadata"]["namespace"]]:
            refuse(f"the host delivers {package}'s into {token['namespaces']}, and the Task runs in {task['metadata']['namespace']}")
        if token["repository"] != package:
            refuse(f"the token for {package} is for {token['repository']}")
        if token["permission"] != "write":
            refuse(f"the token for {package} is {token['permission']}, and a release is made with a write")
        if token["appId"] != portal["appId"] or token["privateKeyFile"] != portal["privateKeyFile"]:
            refuse(f"the token for {package} is not minted as the {APP} App from its key file")


if __name__ == "__main__":
    main()
