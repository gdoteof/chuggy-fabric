#!/usr/bin/env python3
"""Refuse a cluster whose runners dashboard would come up empty, show more or
less than it says, read one runner two ways, or lose a runner without a word:
what tests/dashboard.py holds every dashboard to, over the families the pool
plane serves of each runner whose report it holds, and rules of this page's
own.

- The families and each one's labels are copied below from kasofsk/chuggy's
  `src/interpreter/workerPoolReports.ts`. Every one carries the runner's
  labels, `owner` among them, so every selector is narrowed by Who.
- Who opens on Me. The page is each member's view of their own runners, and
  one opening on Everyone shows them every runner first.
- Every table takes a query from the last report seen over its window. The
  plane stops serving a runner a little after its last report, so a table
  keyed only on what is served now drops a runner that stops, and nothing on
  the page says it was there.
- A table's Status is the age of the last report seen, `time()` less its
  latest `last_over_time`, and reads Live up to the age of a report the plane
  holds, copied below from kasofsk/chuggy's `workerPoolReportAgeMsMax`, and
  Offline beyond it. A bound of its own reads a runner the plane dropped as
  Live, or one it holds as Offline.
- Every query of a table keys its rows by the same runner labels. Its merge
  joins rows on the labels they share, so a query keyed otherwise adds rows
  of its own rather than columns of the others'.
- The Live and Offline stats count the Runners table's Status query against
  that bound, so the stats and the table cannot read one runner two ways.
- Every runner is a member's own. `workerPoolReportLabels` reports its
  `project` and `pool` empty, which Prometheus stores as no label, so neither
  is among the labels copied below, and a matcher or grouping on either is
  refused as one on a label its family does not carry.
- A legend names no label its query drops: a legend naming an absent label
  prints the label's name.
- A legend tells its series apart. A query keeping every runner label names
  those that tell one member's runner from another, `owner` and `host`, and
  any other query names every label it keeps.

usage: runners-dashboard.py <rendered apps.yaml> <cluster/apps/runners-dashboard.yaml>
"""

import re
import sys

import runners
from dashboard import ME, Check, Expression, custom_current, documents_of, panels_of, refuse, run, shown, written

RUNNER = {"tenant", "owner", "personal_runner", "host"}
REPORTED = "chuggy_runner_last_report_timestamp_seconds"
# kasofsk/chuggy's workerPoolReportAgeMsMax, in src/interpreter/workerPoolReports.ts.
REPORT_AGE_MS_MAX = 180_000
BOUND = REPORT_AGE_MS_MAX // 1000
# Each status, the comparison of a report's age with BOUND it reads, and the range mapping that reads it.
STATUSES = (("Live", "<=", (None, BOUND)), ("Offline", ">", (BOUND, None)))
# The labels that tell one member's runner from another.
IDENTIFIED = {"owner", "host"}
# A Status: now less the latest report seen of each runner, or each machine.
AGE = re.compile(rf"time\(\) - max by \([^()]*\) \(last_over_time\({REPORTED}\{{[^{{}}]*\}}\[\$__range\]\)\)")
LEGEND = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
FAMILIES = {
    "chuggy_runner_uptime_seconds": ("gauge", RUNNER),
    "chuggy_runner_jobs_running": ("gauge", RUNNER),
    "chuggy_runner_jobs_max": ("gauge", RUNNER),
    "chuggy_runner_sessions_running": ("gauge", RUNNER),
    "chuggy_runner_sessions_max": ("gauge", RUNNER),
    "chuggy_runner_disk_free_bytes": ("gauge", RUNNER),
    "chuggy_runner_disk_floor_bytes": ("gauge", RUNNER),
    "chuggy_runner_machine_cpus": ("gauge", RUNNER),
    "chuggy_runner_machine_load1": ("gauge", RUNNER),
    "chuggy_runner_machine_memory_total_bytes": ("gauge", RUNNER),
    "chuggy_runner_machine_memory_available_bytes": ("gauge", RUNNER),
    "chuggy_runner_polls_total": ("counter", RUNNER),
    "chuggy_runner_polls_failed_total": ("counter", RUNNER),
    "chuggy_runner_settlements_total": ("counter", RUNNER | {"outcome"}),
    "chuggy_runner_refusals_total": ("counter", RUNNER | {"fault"}),
    "chuggy_runner_jobs_ended_total": ("counter", RUNNER | {"end"}),
    "chuggy_runner_sessions_ended_total": ("counter", RUNNER | {"end"}),
    "chuggy_runner_image_pull_seconds": ("histogram", RUNNER),
    "chuggy_runner_run_seconds": ("histogram", RUNNER | {"kind"}),
    "chuggy_runner_info": ("gauge", RUNNER | {"package", "version"}),
    "chuggy_runner_last_poll_timestamp_seconds": ("gauge", RUNNER),
    REPORTED: ("gauge", RUNNER),
    "chuggy_runner_memory_room_bytes": ("gauge", RUNNER),
    "chuggy_runner_memory_ceiling_bytes": ("gauge", RUNNER),
}


def keeps_the_stopped(panel):
    """Whether a query of the panel reads the last report seen over its window."""
    return any(reads_the_last_report(target) for target in panel["targets"])


def reads_the_last_report(target):
    return any(
        selector.metric == REPORTED and ("function", "last_over_time") in selector.enclosing
        for selector in Expression(target["expr"]).selectors
    )


def status_of(table):
    """The query a table's Status column shows, or None where it has none;
    refused where its mapping is not Live and Offline either side of BOUND."""
    where = f"table {table.get('title')!r}"
    renamed = {}
    for step in table.get("transformations") or []:
        if step.get("id") == "organize":
            renamed |= (step.get("options") or {}).get("renameByName") or {}
    shown = [field for field, name in renamed.items() if name == "Status"]
    if not shown:
        return None
    sources = [target for target in table["targets"] if [f"Value #{target.get('refId')}"] == shown]
    if len(sources) != 1:
        refuse(f"{where} names Status other than one query's values")
    (source,) = sources
    if not AGE.fullmatch(source["expr"]):
        refuse(f"{where}'s Status is not the age of the last report seen, time() less the max of last_over_time({REPORTED}), so it does not read a runner that stops as Offline")
    mappings = [
        prop["value"]
        for override in (table.get("fieldConfig") or {}).get("overrides") or []
        if override.get("matcher") == {"id": "byName", "options": "Status"}
        for prop in override.get("properties") or []
        if prop.get("id") == "mappings"
    ]
    read = [
        ((mapping["options"].get("from"), mapping["options"].get("to")), mapping["options"]["result"].get("text"))
        for found in mappings
        for mapping in found
        if mapping.get("type") == "range"
    ]
    if read != [(bounds, text) for text, _, bounds in STATUSES]:
        refuse(f"{where}'s Status maps {read}, where it reads Live up to {BOUND}s and Offline beyond, as the plane holds a report")
    return source["expr"]


def one_key(table, labels):
    """Refused where a table's queries key their rows by different runner labels."""
    keys = {ref: (found or frozenset()) & RUNNER for ref, found in labels.items()}
    (first, key), *rest = keys.items()
    for ref, other in rest:
        if other != key:
            refuse(f"table {table.get('title')!r} keys query {first} by {shown(key)} and query {ref} by {shown(other)}, so its merge adds rows rather than joining them")


def legend_tells_apart(target, labels, where):
    """Refused where a legend names a label its query drops, or leaves unnamed
    one that tells two of its series apart."""
    named = set(LEGEND.findall(target["legendFormat"]))
    kept = labels or frozenset()
    if named - kept:
        refuse(f"{where} names {sorted(named - kept)} in its legend, which its query does not keep, so the legend prints the label's name")
    unnamed = (IDENTIFIED if RUNNER <= kept else kept) - named
    if unnamed:
        refuse(f"{where} leaves {sorted(unnamed)} out of its legend, so two of its series can read alike")


def main():
    rendered, source = sys.argv[1:3]
    check = Check("chuggy-runners-dashboard", "chuggy-runners", FAMILIES)
    dashboard = check.held_dashboard(documents_of(rendered))
    (owner,) = [variable for variable in dashboard["templating"]["list"] if variable["name"] == "owner"]
    if custom_current(owner) != ME:
        refuse(f"Who opens on {custom_current(owner)!r}, and the page opens on {ME}, the signed-in member's own runners")
    statuses = {}
    for panel in panels_of(dashboard):
        labels = {}
        for target in panel.get("targets") or []:
            where = f"panel {panel.get('title')!r} query {target.get('refId')}"
            labels[target.get("refId")] = Expression(target["expr"], lambda selector: check.resolved(selector, where)[1]).labels
            if target.get("legendFormat") not in (None, "", "__auto"):
                legend_tells_apart(target, labels[target.get("refId")], where)
        if panel.get("type") == "table" and not keeps_the_stopped(panel):
            refuse(f"table {panel.get('title')!r} has no query reading last_over_time of {REPORTED}, so a runner that stops leaves it")
        if panel.get("type") == "table":
            statuses[panel.get("title")] = status_of(panel)
            one_key(panel, labels)
    if statuses.get("Runners") is None:
        refuse("the page has no Runners table with a Status, whose Status the stats count")
    stats = {panel.get("title"): panel for panel in panels_of(dashboard) if panel.get("type") == "stat"}
    for text, comparison, _ in STATUSES:
        counted = f"count(({statuses['Runners']}) {comparison} {BOUND})"
        exprs = [target.get("expr") for target in (stats.get(text) or {}).get("targets") or []]
        if exprs != [counted]:
            refuse(f"the {text} stat reads {exprs}, where it counts the Runners table's Status {comparison} {BOUND}: {counted}")
    written(source, runners.MANIFEST, "cluster/apps/runners-dashboard.yaml", "dashboards/runners.py")


run("runners-dashboard", main)
