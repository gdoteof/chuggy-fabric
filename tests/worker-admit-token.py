#!/usr/bin/env python3
"""Refuse a host whose worker admission token is not the one the CronJob mounts.

usage: worker-admit-token.py HOST_APPS_AND_TOKENS RENDERED_BUILD_SYSTEM

The token is minted on the host and read by a pod, with a name between them
that is written twice. A Secret named one way by the host and another by the
CronJob is a run that has a release to admit, finds nothing mounted, and fails
in its last step.

WHAT IS HELD, OF THE ENTRY THE HOST DECLARES:

- there is one, and it is the only entry that delivers to the CronJob's
  namespace;
- it delivers the name the CronJob's volume reads, into the namespace the
  CronJob runs in and no other;
- it is a token for the repository the CronJob's steps publish to, with
  `write` on contents and `pull_requests: write`, which opening and merging a
  pull request need, and nothing else;
- it is minted as the admit App from that App's key file, and not as the portal
  App, which the ruleset lets update `main`, nor the worker App.

WHAT THIS CANNOT SEE. Whether the App is installed on the repository, whether
`installationId` is its installation, and what the ruleset does to a merge
made by it: GitHub holds all three.
"""

import json
import sys

import yaml

TOKEN = "worker-admit"
CRONJOB = "worker-admit"
APP = "admit"


def refuse(message):
    raise SystemExit(f"worker-admit-token: {message}")


def main():
    if len(sys.argv) != 3:
        refuse("usage: worker-admit-token.py HOST_APPS_AND_TOKENS RENDERED_BUILD_SYSTEM")
    host = json.load(open(sys.argv[1], encoding="utf-8"))
    apps, tokens = host["apps"], host["tokens"]
    with open(sys.argv[2], encoding="utf-8") as handle:
        documents = [document for document in yaml.safe_load_all(handle) if document]

    token = tokens.get(TOKEN)
    if token is None:
        refuse(f"the host declares no token {TOKEN}, and the CronJob {CRONJOB} mounts one")
    (cronjob,) = [d for d in documents if d["kind"] == "CronJob" and d["metadata"]["name"] == CRONJOB]
    namespace = cronjob["metadata"]["namespace"]
    delivering = sorted(name for name, other in tokens.items() if namespace in other["namespaces"])
    if delivering != [TOKEN]:
        refuse(f"the host delivers tokens {delivering} into {namespace}, and the policy holds one Secret there")

    pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    secrets = [volume["secret"] for volume in pod["volumes"] if "secret" in volume]
    if [secret["secretName"] for secret in secrets] != [token["secretName"]]:
        refuse(f"the CronJob reads {[secret['secretName'] for secret in secrets]} and the host mints {token['secretName']}")
    if [secret["items"][0]["key"] for secret in secrets] != ["token"] or token["secretFormat"] != "token":
        refuse("the CronJob reads a key the host does not write")
    if token["namespaces"] != [namespace]:
        refuse(f"the host delivers into {token['namespaces']}, and the CronJob runs in {namespace}")
    if token["permission"] != "write" or token["extraPermissions"] != {"pull_requests": "write"}:
        refuse(f"the token is {token['permission']} with {token['extraPermissions']}, and a merged pull request needs contents and pull_requests, write")

    env = {e["name"]: e.get("value") for step in [*pod["initContainers"], *pod["containers"]] for e in step.get("env", [])}
    if env["REPOSITORY"].partition("/")[2] != token["repository"]:
        refuse(f"the token is for {token['repository']} and the CronJob publishes to {env['REPOSITORY']}")

    admit = apps[APP]
    if token["appId"] != admit["appId"] or token["privateKeyFile"] != admit["privateKeyFile"]:
        refuse(f"the token is not minted as the {APP} App from its key file")
    if len({app["appId"] for app in apps.values()}) != len(apps):
        refuse("two Apps share an id")


if __name__ == "__main__":
    main()
