#!/usr/bin/env python3
"""Refuse a cluster whose usage dashboard would come up empty, or show more or
less than it says, with nothing reporting why: what tests/dashboard.py holds
every dashboard to, over the families the metrics plane serves.

- The families and each one's labels are copied below from kasofsk/chuggy's
  `src/interpreter/metricsPlane.ts`.
- `owner` on chuggy_tickets, which carries none, is every ticket under
  Everyone and none under Me.
- A grouping by a label a family carries is bounded by the plane, which labels
  nothing by ticket, execution, attempt or session: its `session` is the kind
  of session.

That the plane is scraped is tests/metrics-plane.py's to hold.

usage: usage-dashboard.py <rendered apps.yaml> <cluster/apps/usage-dashboard.yaml>
"""

import sys

import usage
from dashboard import Check, documents_of, run, written

TASK = {"tenant", "project", "owner", "phase", "stage", "runner", "workload", "placement"}
SESSION = {"tenant", "project", "owner", "session"}
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
    "chuggy_tickets": ("gauge", {"tenant", "project", "phase"}),
}


def main():
    rendered, source = sys.argv[1:3]
    Check("chuggy-usage-dashboard", "chuggy-usage", FAMILIES).held_dashboard(documents_of(rendered))
    written(source, usage.MANIFEST, "cluster/apps/usage-dashboard.yaml", "dashboards/usage.py")


run("usage-dashboard", main)
