#!/usr/bin/env python3
"""Refuse a cluster whose release dashboard would come up empty with nothing
reporting why.

A link from the dashboard to its data breaks silently. The ones held here:

- A monitor Prometheus does not select is an object nothing reads, and so is
  one whose selector or port matches nothing. The two this page stands on are
  resolved against what the tree declares for Flux and for Tekton; every
  monitor in the layer is held to the label.
- A Flux kind kube-state-metrics is told to read and not allowed to list is a
  line in one pod's log. A selector that names a kind by `customresource_kind`
  and reads a series or a label the configuration does not produce for that
  kind draws "No data".
- A dashboard the sidecar does not deliver, a document Grafana cannot parse and
  a panel naming a datasource Grafana is not given are each an empty page.
- A link that is not to the address Grafana answers at, to this dashboard's
  uid or by a variable it has opens on something else or on nothing. The one a
  release run gives chuggy for itself is held to all three.

No other series is known by name here, and nothing a query means is read.
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
# The variable a link opens the page for one run by, and the one that does.
VARIABLE = "run"
PIPELINE = "chuggy-release"
REPORT = "report"
RUN_NAME = "$(context.pipelineRun.name)"
# The datasource the chart provisions for its own Prometheus.
CHART_DATASOURCE = "prometheus"
# What kube-state-metrics labels every custom resource series with.
OF_EVERY_KIND = {"customresource_group", "customresource_kind", "customresource_version"}
SELECTOR = re.compile(r"(\w+)\{([^}]*)\}")
MATCHER = re.compile(r'(\w+)\s*(?:=~|!~|!=|=)\s*"([^"]*)"')


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


def pods(documents):
    """Each Deployment's pods, as a monitor sees them."""
    for document in documents:
        if document.get("kind") != "Deployment":
            continue
        template = document["spec"]["template"]
        ports = {
            port.get("name")
            for container in template["spec"]["containers"]
            for port in container.get("ports") or []
        }
        yield document["metadata"], template["metadata"].get("labels") or {}, ports


def services(documents):
    for document in documents:
        if document.get("kind") != "Service":
            continue
        ports = {port.get("name") for port in document["spec"]["ports"]}
        yield document["metadata"], document["metadata"].get("labels") or {}, ports


def selects(selector, labels):
    for expression in selector.get("matchExpressions") or []:
        if expression["operator"] != "In":
            refuse(f"a monitor selects by {expression['operator']}, which this check does not read")
        if labels.get(expression["key"]) not in expression["values"]:
            return False
    return all(labels.get(key) == value for key, value in (selector.get("matchLabels") or {}).items())


def monitor_reaches(documents, kind, name, endpoints, targets):
    """The monitor selects something, and each thing it selects names each port it scrapes."""
    spec = named(documents, kind, name)["spec"]
    namespaces = spec["namespaceSelector"]["matchNames"]
    reached = [
        (metadata["name"], ports)
        for metadata, labels, ports in targets
        if metadata.get("namespace") in namespaces and selects(spec["selector"], labels)
    ]
    if not reached:
        refuse(f"{kind} {name} selects nothing in {namespaces}")
    for endpoint in spec[endpoints]:
        for target, ports in reached:
            if endpoint["port"] not in ports:
                refuse(f"{kind} {name} scrapes the port {endpoint['port']}, which {target} does not name")


def flux_series(documents):
    """The series kube-state-metrics is told to produce from Flux's objects,
    as {series: {kind: labels}}, each kind one it may also list."""
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
    series = {}
    for resource in custom["config"]["spec"]["resources"]:
        gvk = resource["groupVersionKind"]
        if (gvk["group"], plural(gvk["kind"])) not in listable:
            refuse(f"kube-state-metrics reads {gvk['kind']} and no rule lets it list and watch {plural(gvk['kind'])}")
        for metric in resource["metrics"]:
            labels = OF_EVERY_KIND | set(metric.get("labelsFromPath") or {})
            labels |= set(metric["each"]["info"].get("labelsFromPath") or {})
            series.setdefault(f"{resource['metricNamePrefix']}_{metric['name']}", {})[gvk["kind"]] = labels
    return series


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


def panels_of(holder):
    """Every panel that queries, those inside a collapsed row among them."""
    for panel in holder.get("panels") or []:
        if panel.get("targets"):
            yield panel
        yield from panels_of(panel)


def columns_of(panel):
    for transformation in panel.get("transformations") or []:
        if transformation["id"] == "filterFieldsByName":
            yield from transformation["options"]["include"]["names"]


def reads_what_is_produced(panel, series):
    """A selector that names a Flux kind reads a series and labels that kind is given."""
    title = panel["title"]
    for target in panel["targets"]:
        for name, inside in SELECTOR.findall(target.get("expr", "")):
            matchers = dict(MATCHER.findall(inside))
            if "customresource_kind" not in matchers:
                continue
            for kind in matchers["customresource_kind"].split("|"):
                produced = series.get(name, {}).get(kind)
                if produced is None:
                    refuse(f"panel {title!r} reads {name} of {kind}, which kube-state-metrics is not told to produce")
                for label in [*matchers, *columns_of(panel)]:
                    if label not in produced:
                        refuse(f"panel {title!r} reads the label {label} of {kind}, which {name} is not given")


def dashboard_reads_what_exists(documents, series):
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
    for panel in panels_of(dashboard):
        for holder in [panel, *panel["targets"]]:
            uid = (holder.get("datasource") or {}).get("uid")
            if uid not in known:
                refuse(f"panel {panel['title']!r} reads datasource {uid!r}, and Grafana is given {sorted(known)}")
        reads_what_is_produced(panel, series)
    return dashboard


def run_links_to_its_page(apps, build, dashboard):
    values = named(apps, "HelmRelease", RELEASE)["spec"]["values"]
    root = values["grafana"]["grafana.ini"]["server"]["root_url"].rstrip("/")
    if VARIABLE not in [variable["name"] for variable in dashboard["templating"]["list"]]:
        refuse(f"the dashboard has no variable {VARIABLE!r}, which a link opens it for one run by")
    (pipeline,) = [
        document
        for document in build
        if document.get("kind") == "Pipeline" and document["metadata"]["name"] == PIPELINE
    ]
    links = [
        param["value"]
        for entry in pipeline["spec"].get("finally") or []
        if entry["name"] == REPORT
        for param in entry["params"]
        if param["name"] == "link"
    ]
    expected = [f"{root}/d/{UID}?var-{VARIABLE}={RUN_NAME}"]
    if links != expected:
        refuse(f"a release run gives chuggy the link {links}, and its page on this dashboard is {expected}")


def main():
    apps, flux, build = (objects(path) for path in sys.argv[1:4])
    monitors_are_selected(apps)
    monitor_reaches(apps, "PodMonitor", "flux-controllers", "podMetricsEndpoints", list(pods(flux)))
    monitor_reaches(apps, "ServiceMonitor", "tekton-pipelines-controller", "endpoints", list(services(build)))
    dashboard = dashboard_reads_what_exists(apps, flux_series(apps))
    run_links_to_its_page(apps, build, dashboard)


main()
