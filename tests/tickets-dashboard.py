#!/usr/bin/env python3
"""Refuse a cluster whose tickets dashboard would come up empty, or show more
or less than it says, with nothing reporting why: what tests/dashboard.py holds
every dashboard to, over the families the metrics plane serves, and a rule of
this page's own.

- The families and each one's labels are copied below from kasofsk/chuggy's
  `src/interpreter/metricsPlane.ts`. Every one carries `owner`, so every
  selector is narrowed by Who.
- A grouping by a label a family carries is bounded by the plane, which labels
  nothing by ticket, execution, attempt or session.
- The one bucket read outside histogram_quantile is the first-pass rate's: the
  landed tickets no result sent back, the rework histogram's first bound, which
  is zero. Prometheus stores a bound as it writes a float, so `le="0"` reads no
  bucket and the rate reads None landed whatever landed.

That the plane is scraped is tests/metrics-plane.py's to hold.

usage: tickets-dashboard.py <rendered apps.yaml> <cluster/apps/tickets-dashboard.yaml>
"""

import sys

import tickets
from dashboard import Check, Expression, documents_of, panels_of, refuse, run, written

TASK = {"tenant", "project", "owner", "phase", "stage", "runner", "workload", "placement"}
SESSION = {"tenant", "project", "owner", "session"}
TICKET = {"tenant", "project", "owner"}
FAMILIES = {
    "chuggy_attempts_ended_total": ("counter", TASK | {"state"}),
    "chuggy_attempt_duration_seconds": ("histogram", TASK),
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
}
# The first of kasofsk/chuggy's metricsPlaneTicketReworkBounds, as Prometheus stores it.
FIRST_PASS = ("chuggy_ticket_reworks_bucket", "0.0")


def main():
    rendered, source = sys.argv[1:3]
    check = Check("chuggy-tickets-dashboard", "chuggy-tickets", FAMILIES)
    dashboard = check.held_dashboard(documents_of(rendered))
    for panel in panels_of(dashboard):
        for target in panel.get("targets") or []:
            where = f"panel {panel.get('title')!r} query {target.get('refId')}"
            for selector in Expression(target["expr"]).selectors:
                bounds = [value for label, _, value in selector.matchers if label == "le"]
                if bounds and (selector.metric, bounds) != (FIRST_PASS[0], [FIRST_PASS[1]]):
                    refuse(f'{where} reads {selector.metric} at le="{bounds[0]}", and the one bucket the page reads is {FIRST_PASS[0]} at le="{FIRST_PASS[1]}"')
    written(source, tickets.MANIFEST, "cluster/apps/tickets-dashboard.yaml", "dashboards/tickets.py")


run("tickets-dashboard", main)
