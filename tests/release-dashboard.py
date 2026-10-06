#!/usr/bin/env python3
"""Refuse a rendered cluster whose release dashboard would come up empty with
nothing reporting why.

Every link from the dashboard to its data fails silently: a monitor Prometheus
does not select is an object nothing reads; a Flux kind kube-state-metrics is
told to read and not allowed to list is a line in one pod's log; a panel naming
a datasource Grafana does not have draws "No data"; and a document that is not
JSON is skipped by Grafana after the sidecar has delivered it. So each link is
held here, on the rendered manifests.
"""

import json
import re
import sys
from pathlib import Path

import yaml

NAMESPACE = "monitoring"
RELEASE = "kube-prometheus-stack"
DASHBOARD = "chuggy-releases-dashboard"
UID = "chuggy-releases"
# The datasource the chart provisions for its own Prometheus.
CHART_DATASOURCE = "prometheus"
KIND_MATCHER = re.compile(r'customresource_kind=~?"([^"]+)"')


def refuse(message):
    raise SystemExit(f"release-dashboard: {message}")


def objects(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def named(documents, kind, name):
    found = [
        document
        for document in documents
        if document.get("kind") == kind
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == NAMESPACE
    ]
    if len(found) != 1:
        refuse(f"expected one {kind} {NAMESPACE}/{name}, found {len(found)}")
    return found[0]


def plural(kind):
    lower = kind.lower()
    return lower[:-1] + "ies" if lower.endswith("y") else lower + "s"


def monitors_are_selected(documents):
    for document in documents:
        if document.get("kind") not in ("PodMonitor", "ServiceMonitor"):
            continue
        name = f"{document['kind']} {document['metadata']['name']}"
        if (document["metadata"].get("labels") or {}).get("release") != RELEASE:
            refuse(f"{name} lacks the label release={RELEASE}, so Prometheus does not select it")


def flux_kinds(documents):
    """The Flux kinds kube-state-metrics reads, each one it may also list."""
    values = named(documents, "HelmRelease", RELEASE)["spec"]["values"]
    state = values.get("kube-state-metrics") or {}
    if state.get("collectors") == [] or any(
        "custom-resource-state-only" in argument for argument in state.get("extraArgs") or []
    ):
        refuse("kube-state-metrics is told to read custom resources only, which drops every kube_* series")
    listable = {
        (group, resource)
        for rule in (state.get("rbac") or {}).get("extraRules") or []
        if {"list", "watch"} <= set(rule.get("verbs") or [])
        for group in rule.get("apiGroups") or []
        for resource in rule.get("resources") or []
    }
    custom = state.get("customResourceState") or {}
    if custom.get("enabled") is not True:
        refuse("kube-state-metrics does not read Flux's objects: customResourceState is not enabled")
    kinds = set()
    for resource in custom["config"]["spec"]["resources"]:
        gvk = resource["groupVersionKind"]
        if (gvk["group"], plural(gvk["kind"])) not in listable:
            refuse(f"kube-state-metrics reads {gvk['kind']} and no rule lets it list {plural(gvk['kind'])}")
        kinds.add(gvk["kind"])
    return kinds


def datasources(documents):
    found = {CHART_DATASOURCE}
    for document in documents:
        if document.get("kind") != "ConfigMap":
            continue
        if (document["metadata"].get("labels") or {}).get("grafana_datasource") != "1":
            continue
        for text in document["data"].values():
            found.update(source["uid"] for source in yaml.safe_load(text)["datasources"])
    return found


def dashboard_reads_what_exists(documents, kinds):
    config = named(documents, "ConfigMap", DASHBOARD)
    if (config["metadata"].get("labels") or {}).get("grafana_dashboard") != "1":
        refuse(f"{DASHBOARD} lacks the label grafana_dashboard=1, so the sidecar does not deliver it")
    if len(config["data"]) != 1:
        refuse(f"{DASHBOARD} holds {len(config['data'])} documents; one dashboard is one document")
    (text,) = config["data"].values()
    try:
        dashboard = json.loads(text)
    except json.JSONDecodeError as error:
        refuse(f"{DASHBOARD} is not JSON: {error}")
    if dashboard.get("uid") != UID:
        refuse(f"the dashboard's uid is {dashboard.get('uid')!r}, and links are written to {UID!r}")
    known = datasources(documents)
    for panel in dashboard["panels"]:
        for holder in [panel, *panel.get("targets", [])]:
            uid = (holder.get("datasource") or {}).get("uid")
            if uid not in known:
                refuse(f"panel {panel['title']!r} reads datasource {uid!r}, and Grafana is given {sorted(known)}")
        for target in panel.get("targets", []):
            for alternatives in KIND_MATCHER.findall(target.get("expr", "")):
                for kind in alternatives.split("|"):
                    if kind not in kinds:
                        refuse(f"panel {panel['title']!r} reads Flux kind {kind}, which kube-state-metrics is not told to read")


def main():
    documents = objects(sys.argv[1])
    monitors_are_selected(documents)
    dashboard_reads_what_exists(documents, flux_kinds(documents))


main()
