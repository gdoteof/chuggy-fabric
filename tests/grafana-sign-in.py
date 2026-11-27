#!/usr/bin/env python3
"""Refuse a Grafana that would let in a person it holds no account for.

Every chuggy member can reach Grafana's sign-in, and a person Grafana lets in
reads every series in Prometheus and every pod's log line in Loki, whatever
tenant. Four settings of the release's `grafana.ini` decide who that is, and
each reads correctly beside the other three. What this holds, of the values
the release in the rendered `apps` layer hands the chart:

- NO ACCOUNT IS MADE AT A SIGN-IN: `auth.generic_oauth.allow_sign_up` is
  false. Grafana's own default for it is true.
- NONE IS MADE AT THE FORM, AND NONE IS NEEDED: `users.allow_sign_up` and
  `auth.anonymous.enabled` are false.
- NONE IS FOUND BY AN ADDRESS: `auth.oauth_allow_insecure_email_lookup` is
  false. The address in a chuggy ID token is only the person's word, so a
  lookup by it signs a member in as whoever holds the address they give.
- NOTHING ELSE SETS THEM. A variable `GF_<SECTION>_<KEY>` sets a setting over
  `grafana.ini`, so none of the four is named in `env`, `envValueFrom` or
  `envRenderSecret`. `envFromSecret`, `envFromSecrets` and `envFromConfigMaps`
  give Grafana every key of what they name, and the release's `valuesFrom`
  and `postRenderers` change what the chart is handed or renders, so none of
  those is set.

Each of the four is said, and said `false`: one left out is Grafana's default.

WHAT THIS CANNOT SEE: the chart's render, and a Generic OAuth configuration
saved in Grafana's own Administration > Authentication page, which Grafana
stores in its database and puts over `grafana.ini`.
"""

import sys
from pathlib import Path

import yaml

NAMESPACE = "monitoring"
RELEASE = "kube-prometheus-stack"
# Each section and key of grafana.ini that makes, needs or finds an account.
SETTINGS = (
    ("auth.generic_oauth", "allow_sign_up"),
    ("users", "allow_sign_up"),
    ("auth.anonymous", "enabled"),
    ("auth", "oauth_allow_insecure_email_lookup"),
)
# The chart's arms that give Grafana a variable by name.
NAMED = ("env", "envValueFrom", "envRenderSecret")
# The chart's arms that give Grafana every key of a Secret or ConfigMap.
WHOLE = ("envFromSecret", "envFromSecrets", "envFromConfigMaps")
# What changes the values a HelmRelease hands its chart, or what it renders.
UNREAD = ("valuesFrom", "postRenderers")


def refuse(message):
    raise SystemExit(f"grafana-sign-in: {message}")


def variables(section, key):
    """The variables Grafana reads a setting from over grafana.ini, by value and by file."""
    name = "GF_" + f"{section}_{key}".upper().replace(".", "_").replace("-", "_")
    return (name, f"{name}__FILE")


def main():
    if len(sys.argv) != 2:
        refuse("usage: grafana-sign-in.py RENDERED_APPS")
    releases = [
        document
        for document in yaml.safe_load_all(Path(sys.argv[1]).read_text())
        if document
        and document.get("kind") == "HelmRelease"
        and document["metadata"]["name"] == RELEASE
        and document["metadata"].get("namespace") == NAMESPACE
    ]
    if len(releases) != 1:
        refuse(f"expected one HelmRelease {NAMESPACE}/{RELEASE}, found {len(releases)}")
    spec = releases[0]["spec"]
    for field in UNREAD:
        if spec.get(field):
            refuse(f"the release carries {field}, which can set Grafana's sign-in where this does not read")
    grafana = (spec.get("values") or {}).get("grafana") or {}
    ini = grafana.get("grafana.ini") or {}
    for section, key in SETTINGS:
        value = (ini.get(section) or {}).get(key)
        if value is not False:
            refuse(f"grafana.ini [{section}] {key} is {value!r}, not false")
    for arm in WHOLE:
        if grafana.get(arm):
            refuse(f"grafana.{arm} gives Grafana every key of what it names, which can set its sign-in where this does not read")
    named = {name for arm in NAMED for name in grafana.get(arm) or {}}
    for section, key in SETTINGS:
        for name in variables(section, key):
            if name in named:
                refuse(f"Grafana's environment sets {name}, which is grafana.ini [{section}] {key}")


if __name__ == "__main__":
    main()
