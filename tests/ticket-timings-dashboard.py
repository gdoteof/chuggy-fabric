#!/usr/bin/env python3
"""Refuse a cluster whose ticket timings dashboard would come up empty, or show
more or less than it says, or name a bar other than by its bucket, with nothing
reporting why: what tests/dashboard.py holds every dashboard to, over the
families the metrics plane serves, and a rule of this page's own.

- The families and each one's labels are copied below from kasofsk/chuggy's
  `src/interpreter/metricsPlane.ts`, as are the bounds of each family the page
  draws a distribution of. Every family carries `owner`, so every selector is
  narrowed by Who, and every one but a session's carries `repository`, so
  every selector here is narrowed by Repository.
- A grouping by a label a family carries is bounded by the plane, which labels
  nothing by ticket, execution, attempt or session.
- A distribution's bar gauge names every bucket of its family and no other,
  each by its bound as Prometheus stores it as `le`: Go's shortest %g, which writes an
  exponent from a million, and `.0` added where it has neither. A bucket it
  does not name reads as its raw bound, and a name written to a bound
  Prometheus does not store, `le="1209600.0"` for `1.2096e+06`, names nothing.

That the plane is scraped is tests/metrics-plane.py's to hold.

usage: ticket-timings-dashboard.py <rendered apps.yaml> <cluster/apps/ticket-timings-dashboard.yaml>
"""

import sys

import ticket_timings
from dashboard import Check, Expression, documents_of, panels_of, refuse, run, written

TASK = {"tenant", "project", "repository", "owner", "phase", "stage", "runner", "workload", "placement"}
SESSION = {"tenant", "project", "owner", "session"}
TICKET = {"tenant", "project", "repository", "owner"}
FAMILIES = {
    "chuggy_attempts_ended_total": ("counter", TASK | {"state"}),
    "chuggy_attempt_duration_seconds": ("histogram", TASK),
    "chuggy_attempt_wait_seconds": ("histogram", {"tenant", "project", "repository", "owner", "phase", "placement"}),
    "chuggy_run_turns_total": ("counter", TASK),
    "chuggy_run_duration_seconds_total": ("counter", TASK),
    "chuggy_run_api_duration_seconds_total": ("counter", TASK),
    "chuggy_run_tokens_total": ("counter", TASK | {"model", "type"}),
    "chuggy_run_cost_usd_total": ("counter", TASK | {"model"}),
    "chuggy_session_turns_ended_total": ("counter", SESSION | {"state"}),
    "chuggy_session_turn_tokens_total": ("counter", SESSION | {"model"}),
    "chuggy_session_turn_cost_usd_total": ("counter", SESSION | {"model"}),
    "chuggy_session_turn_duration_seconds": ("histogram", SESSION),
    "chuggy_tickets": ("gauge", TICKET | {"phase", "escalation"}),
    "chuggy_ticket_events_total": ("counter", TICKET | {"event", "stage"}),
    "chuggy_ticket_lead_time_seconds": ("histogram", TICKET),
    "chuggy_ticket_run_time_seconds": ("histogram", TICKET),
    "chuggy_ticket_reworks": ("histogram", TICKET),
    "chuggy_ticket_cost_usd": ("histogram", TICKET | {"end"}),
    "chuggy_ticket_escalation_duration_seconds": ("histogram", TICKET | {"event", "by"}),
    "chuggy_ticket_work_cycle_duration_seconds": ("histogram", TICKET | {"began", "ended"}),
    "chuggy_ticket_evaluation_cycle_duration_seconds": ("histogram", TICKET | {"began", "ended"}),
    "chuggy_ticket_phase_time_seconds": ("histogram", TICKET | {"phase"}),
    "chuggy_ticket_work_cycles": ("histogram", TICKET),
}
CYCLE = ("60.0", "120.0", "300.0", "600.0", "900.0", "1200.0", "1800.0", "2700.0", "3600.0", "5400.0", "7200.0", "10800.0", "14400.0", "28800.0")
TICKET_TIME = ("900.0", "1800.0", "3600.0", "7200.0", "14400.0", "28800.0", "86400.0", "172800.0", "345600.0", "604800.0", "1.2096e+06")
BOUNDS = {
    "chuggy_ticket_work_cycle_duration_seconds": CYCLE,
    "chuggy_ticket_evaluation_cycle_duration_seconds": CYCLE,
    "chuggy_ticket_work_cycles": ("1.0", "2.0", "3.0", "4.0", "5.0", "7.0", "10.0"),
    "chuggy_attempt_duration_seconds": ("30.0", "60.0", "120.0", "300.0", "600.0", "900.0", "1200.0", "1800.0", "2700.0", "3600.0", "5400.0", "7200.0"),
    "chuggy_attempt_wait_seconds": ("10.0", "30.0", "60.0", "120.0", "300.0", "600.0", "1200.0", "1800.0", "3600.0", "7200.0", "14400.0"),
    "chuggy_ticket_lead_time_seconds": TICKET_TIME,
    "chuggy_ticket_run_time_seconds": TICKET_TIME,
}


def names_every_bucket(panel):
    """Refused where a distribution's bars are named other than by every bucket of its family."""
    where = f"distribution {panel.get('title')!r}"
    named = {
        override["matcher"]["options"]
        for override in panel["fieldConfig"]["overrides"]
        if override["matcher"]["id"] == "byName"
        and any(prop["id"] == "displayName" for prop in override["properties"])
    }
    for target in panel["targets"]:
        (selector,) = Expression(target["expr"]).selectors
        family = selector.metric.removesuffix("_bucket")
        if family not in BOUNDS:
            refuse(f"{where} draws {family}, whose bounds this check does not copy")
        buckets = set(BOUNDS[family]) | {"+Inf"}
        faults = []
        if buckets - named:
            faults.append(f"leaves {sorted(buckets - named)} unnamed, so each reads as its bound")
        if named - buckets:
            faults.append(f"names {sorted(named - buckets)}, which {family} does not store")
        if faults:
            refuse(f"{where} {', and '.join(faults)}")


def main():
    rendered, source = sys.argv[1:3]
    check = Check("chuggy-ticket-timings-dashboard", "chuggy-ticket-timings", FAMILIES)
    dashboard = check.held_dashboard(documents_of(rendered))
    for panel in panels_of(dashboard):
        if panel.get("type") == "bargauge" and any(target.get("format") == "heatmap" for target in panel.get("targets") or []):
            names_every_bucket(panel)
    written(source, ticket_timings.MANIFEST, "cluster/apps/ticket-timings-dashboard.yaml", "dashboards/ticket_timings.py")


run("ticket-timings-dashboard", main)
