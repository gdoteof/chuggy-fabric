#!/usr/bin/env python3
"""Refuse a cluster whose Track Record dashboard would come up empty, or count
less than it says, with nothing reporting why.

- A dashboard the sidecar does not deliver, a document Grafana cannot parse, a
  uid other than the one links are written to, and a panel, a query or a
  variable naming a datasource other than the chart's Prometheus are each an
  empty page or a page at another address.
- A selector naming a series Track Record does not serve draws "No data". The
  series and each one's labels are copied below from kasofsk/track-record's
  `internal/server/metrics.go`; a series the server renames, or a label it
  drops, is not seen here until the copy is changed with it.
- A matcher on a label its series does not carry matches nothing, and a
  grouping by one is one series with that label empty: a miss names no
  command. `namespace` is the scrape's, the pod's namespace, and never the
  store's, which is `record_namespace`, so it is refused outright.
- A selector of a series that carries `record_namespace` without the
  `$namespace` matcher is a panel Namespace does not narrow, and nothing on the
  page says so.
- A stat or a table shows one value for the selected time and a time series
  one for each step, so the one reads an instant query over `[$__range]` and
  the other a range query over `[$__interval]` or `[$__rate_interval]`. A kind
  of panel not named here is refused rather than read.
- A variable a query names that the page does not define reaches Prometheus as
  text.

WHAT THIS CANNOT READ IT REFUSES rather than passes: a selector with no
metric name before it, `without`, `offset`, `@` and a subquery.

It does not read what a query means, or that the server is scraped:
cluster/apps/track-record-monitor.yaml and the policy beside the server are
what that rests on.
"""

import json
import re
import sys
from pathlib import Path

import yaml

NAMESPACE = "monitoring"
CONFIGMAP = "track-record-dashboard"
UID = "track-record"
DATASOURCE = {"type": "prometheus", "uid": "prometheus"}
# The job Prometheus files the server's series under: the operator names it
# after the Service the monitor selects.
JOB = "track-record"

# Each series the server serves, and its labels, from metrics.go.
STORE = {"record_namespace", "name"}
SERIES = {
    "track_record_hits_total": STORE,
    "track_record_misses_total": {"record_namespace"},
    "track_record_saved_seconds_total": STORE,
    "track_record_passes_total": STORE,
    "track_record_pass_seconds_total": STORE,
    "track_record_swept_records_total": set(),
    "track_record_swept_logs_total": set(),
    "track_record_http_request_duration_seconds_bucket": {"route", "code", "le"},
    "track_record_http_request_duration_seconds_count": {"route", "code"},
    "track_record_http_request_duration_seconds_sum": {"route", "code"},
    "process_resident_memory_bytes": set(),
}
# What the scrape adds that a query may match.
SCRAPED = {"job"}
FUNCTIONS = {"sum", "increase", "rate", "histogram_quantile", "by"}
WINDOWS = {
    "stat": ({"$__range"}, True),
    "table": ({"$__range"}, True),
    "timeseries": ({"$__interval", "$__rate_interval"}, False),
}
BUILTIN = {"$__range", "$__interval", "$__rate_interval"}

SELECTOR = re.compile(r"([A-Za-z_:][\w:]*)\s*(\{[^}]*\})?")
MATCHER = re.compile(r'(\w+)\s*(=~|!~|!=|=)\s*"([^"]*)"')
GROUPING = re.compile(r"\bby\s*\(([^)]*)\)")
WINDOW = re.compile(r"\[([^\]]*)\]")
VARIABLE = re.compile(r"\$\w+")


def refuse(message):
    raise SystemExit(f"track-record-dashboard: {message}")


def dashboard(path):
    found = [
        document
        for document in yaml.safe_load_all(Path(path).read_text())
        if document
        and document.get("kind") == "ConfigMap"
        and document["metadata"]["name"] == CONFIGMAP
        and document["metadata"].get("namespace") == NAMESPACE
    ]
    if len(found) != 1:
        refuse(f"expected one ConfigMap {NAMESPACE}/{CONFIGMAP}, found {len(found)}")
    configmap = found[0]
    if (configmap["metadata"].get("labels") or {}).get("grafana_dashboard") != "1":
        refuse(f"{CONFIGMAP} lacks the label grafana_dashboard=1, so the sidecar does not deliver it")
    documents = list(configmap["data"].values())
    if len(documents) != 1:
        refuse(f"{CONFIGMAP} holds {len(documents)} documents, not one")
    try:
        page = json.loads(documents[0])
    except json.JSONDecodeError as error:
        refuse(f"{CONFIGMAP} is not JSON Grafana can parse: {error}")
    if page.get("uid") != UID:
        refuse(f"the dashboard's uid is {page.get('uid')!r}, not {UID!r}, the address links are written to")
    return page


def panels(holder):
    for panel in holder.get("panels") or []:
        yield panel
        yield from panels(panel)


def selectors(expr, where):
    """Each series an expression names, with its matchers."""
    if "offset" in expr or "@" in expr or "without" in expr or re.search(r"\[[^\]]*:", expr):
        refuse(f"{where} uses PromQL this check does not read")
    stripped = re.sub(r'"[^"]*"', '""', expr)
    stripped = GROUPING.sub("", stripped)
    stripped = WINDOW.sub("", stripped)
    stripped = re.sub(r"\b\d+(\.\d+)?\b", "", stripped)
    for match in SELECTOR.finditer(stripped):
        name = match.group(1)
        if name in FUNCTIONS:
            continue
        if name not in SERIES:
            refuse(f"{where} names {name}, which Track Record does not serve")
    if re.search(r"(^|[^\w:])\{", stripped):
        refuse(f"{where} has a selector with no series name before it")
    for match in SELECTOR.finditer(re.sub(r"\[[^\]]*\]", "", expr)):
        name = match.group(1)
        if name in SERIES:
            yield name, MATCHER.findall(match.group(2) or "")


def check_target(panel, target, defined):
    where = f"{panel['title']!r} {target['refId']}"
    if target.get("datasource") != DATASOURCE:
        refuse(f"{where} names the datasource {target.get('datasource')}, not the chart's Prometheus")
    expr = target["expr"]
    named = list(selectors(expr, where))
    if not named:
        refuse(f"{where} names no series")
    for name, matchers in named:
        carried = SERIES[name]
        for label, operator, value in matchers:
            if label == "namespace":
                refuse(f"{where} matches namespace, which is the pod's; the store's is record_namespace")
            if label not in carried | SCRAPED:
                refuse(f"{where} matches {label} on {name}, which does not carry it")
            if label == "job" and (operator, value) != ("=", JOB):
                refuse(f"{where} matches job{operator}{value!r}; the server's series are under job={JOB!r}")
        if "record_namespace" in carried and ("record_namespace", "=~", "$namespace") not in matchers:
            refuse(f'{where} reads {name} without record_namespace=~"$namespace", so Namespace does not narrow it')
    for grouping in GROUPING.findall(expr):
        for label in filter(None, (part.strip() for part in grouping.split(","))):
            for name, _ in named:
                if label not in SERIES[name] | SCRAPED:
                    refuse(f"{where} groups by {label}, which {name} does not carry")
    kind = panel["type"]
    if kind not in WINDOWS:
        refuse(f"{where} is a {kind} panel, which this check does not read")
    windows, instant = WINDOWS[kind]
    if bool(target.get("instant")) != instant:
        refuse(f"{where} is {'not ' if instant else ''}an instant query in a {kind} panel")
    for window in WINDOW.findall(expr):
        if window not in windows:
            refuse(f"{where} counts over [{window}] in a {kind} panel, which reads {' or '.join(sorted(windows))}")
    for variable in VARIABLE.findall(expr):
        if variable not in BUILTIN and variable[1:] not in defined:
            refuse(f"{where} names {variable}, which the page does not define")


def check_variables(page):
    defined = {}
    for variable in page["templating"]["list"]:
        defined[variable["name"]] = variable
        if variable["type"] != "query":
            continue
        if variable.get("datasource") != DATASOURCE:
            refuse(f"the variable {variable['name']} reads a datasource other than the chart's Prometheus")
        match = re.fullmatch(r'label_values\(\{__name__=~"([^"]*)"\},\s*(\w+)\)', variable["query"])
        if not match:
            refuse(f"the variable {variable['name']} is a query this check does not read")
        names, label = match.groups()
        alternation = re.fullmatch(r"(\w*)\(([\w|]+)\)(\w*)", names)
        if not alternation:
            refuse(f"the variable {variable['name']} names series by a pattern this check does not read")
        prefix, middle, suffix = alternation.groups()
        for part in middle.split("|"):
            name = prefix + part + suffix
            if label not in SERIES.get(name, set()):
                refuse(f"the variable {variable['name']} reads {label} off {name}, which does not carry it")
    return defined


page = dashboard(sys.argv[1])
defined = check_variables(page)
for panel in panels(page):
    if panel["type"] == "row":
        continue
    if not panel.get("targets"):
        refuse(f"{panel['title']!r} has no query")
    if panel.get("datasource") != DATASOURCE:
        refuse(f"{panel['title']!r} names the datasource {panel.get('datasource')}, not the chart's Prometheus")
    for target in panel["targets"]:
        check_target(panel, target, defined)
print("track-record-dashboard: clean")
