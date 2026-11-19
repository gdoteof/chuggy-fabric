#!/usr/bin/env python3
"""Refuse a host whose admission token is not the one the admission CronJobs
mount.

usage: worker-admit-token.py HOST_APPS_AND_TOKENS RENDERED_BUILD_SYSTEM

The token is minted on the host and read by the pods of two CronJobs, the
worker's admission and the site's, with a name between them that is written
in each. A Secret named one way by the host and another by a CronJob is a run
that has something to admit, finds nothing mounted, and fails in its last
step.

WHAT IS HELD, OF THE ENTRY THE HOST DECLARES, AGAINST EACH CRONJOB:

- there is one, and it is the only entry that delivers to the CronJobs'
  namespace, which is one;
- it delivers the name each CronJob's volume reads, into the namespace the
  CronJobs run in and no other;
- it is a token for the repository each CronJob's steps publish to, with
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
CRONJOBS = ("worker-admit", "chug-gy-admit")
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
        refuse(f"the host declares no token {TOKEN}, and the CronJobs {list(CRONJOBS)} mount one")
    cronjobs = [d for d in documents if d["kind"] == "CronJob" and d["metadata"]["name"] in CRONJOBS]
    if sorted(d["metadata"]["name"] for d in cronjobs) != sorted(CRONJOBS):
        refuse(f"the build system renders CronJobs {[d['metadata']['name'] for d in cronjobs]}, not {list(CRONJOBS)}")
    namespaces = sorted({d["metadata"]["namespace"] for d in cronjobs})
    if len(namespaces) != 1:
        refuse(f"the admissions run in {namespaces}, and the token is delivered into one namespace")
    (namespace,) = namespaces
    delivering = sorted(name for name, other in tokens.items() if namespace in other["namespaces"])
    if delivering != [TOKEN]:
        refuse(f"the host delivers tokens {delivering} into {namespace}, and the policy holds one Secret there")
    if token["namespaces"] != [namespace]:
        refuse(f"the host delivers into {token['namespaces']}, and the CronJobs run in {namespace}")
    for cronjob in cronjobs:
        cronjob_is_held(cronjob, token)

    admit = apps[APP]
    if token["appId"] != admit["appId"] or token["privateKeyFile"] != admit["privateKeyFile"]:
        refuse(f"the token is not minted as the {APP} App from its key file")
    if len({app["appId"] for app in apps.values()}) != len(apps):
        refuse("two Apps share an id")


def cronjob_is_held(cronjob, token):
    name = cronjob["metadata"]["name"]
    pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    secrets = [volume["secret"] for volume in pod["volumes"] if "secret" in volume]
    if [secret["secretName"] for secret in secrets] != [token["secretName"]]:
        refuse(f"CronJob {name} reads {[secret['secretName'] for secret in secrets]} and the host mints {token['secretName']}")
    if [secret["items"][0]["key"] for secret in secrets] != ["token"] or token["secretFormat"] != "token":
        refuse(f"CronJob {name} reads a key the host does not write")
    if token["permission"] != "write" or token["extraPermissions"] != {"pull_requests": "write"}:
        refuse(f"the token is {token['permission']} with {token['extraPermissions']}, and a merged pull request needs contents and pull_requests, write")

    env = {e["name"]: e.get("value") for step in [*pod["initContainers"], *pod["containers"]] for e in step.get("env", [])}
    if env["REPOSITORY"].partition("/")[2] != token["repository"]:
        refuse(f"the token is for {token['repository']} and CronJob {name} publishes to {env['REPOSITORY']}")


if __name__ == "__main__":
    main()
