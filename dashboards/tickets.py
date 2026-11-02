#!/usr/bin/env python3
"""Writes cluster/apps/tickets-dashboard.yaml: python3 dashboards/tickets.py > cluster/apps/tickets-dashboard.yaml"""

from grafana import Board, ME, colours, dashboard, link, manifest, query_variable, target, who

HEADER = """\
# How chuggy's tickets are going, on one page: how many were released, landed
# and revoked, how often a result sent one back and from where, how long one
# took to land, how long one stood escalated and what one cost, read from the
# series chuggy-metrics-plane-monitor.yaml has Prometheus scrape.
#
# THE DASHBOARD'S UID IS AN ADDRESS. `/d/chuggy-tickets` is the page, and a
# link handed to someone is not this file's to change: renaming the uid breaks
# every one already given out.
#
# NO TICKET IS A LABEL. The plane counts tickets and never names one, so the
# page shows how many and how long, and its header links to the console, where
# each ticket is.
#
# WHO IS A VIEW, NOT A BOUNDARY. Every selector matches `owner=~"$owner"`, a
# ticket's owner being the member who first wrote its draft, the same subject
# a run's `owner` names. Everyone is `.*`, and Me is `${__user.login}`, which
# Grafana fills with the signed-in person's login; monitoring.yaml's
# `login_attribute_path` makes that login the subject the plane cuts its
# `owner` label from. Every member signed in can query every series whatever
# this page shows.
#
# EVERY QUERY SUMS, AND ONLY BY ITS FAMILY'S OWN LABELS, so a release
# replacing the plane's pod draws no new line, and each ratio divides two sums
# grouped alike, as an alert rule would read them.
#
# A STAGE READS AS ITS CONFIGURATION NAMES IT. A configuration that names no
# stage leaves the plane its number, so one stage can read as a number on
# older tickets and a name on newer ones, and the descriptions say so.
#
# A RANGE COUNTS A SERIES FROM ITS FIRST VALUE, as on the usage page: the
# plane names when each series began, as its OpenMetrics `_created`, and
# Prometheus writes a zero at that time (cluster/apps/monitoring.yaml's
# created-timestamp-zero-ingestion).
#
# It is a plain ConfigMap for the reason release-dashboard.yaml's is: the
# sidecar finds it by label and nothing mounts it. dashboards/tickets.py writes
# this file whole; tests/tickets-dashboard.py holds it to that writer and to
# what its own header lists.
"""

S = 'tenant=~"$tenant", project=~"$project", owner=~"$owner"'
EVENTS = "chuggy_ticket_events_total"
RANGE = "[$__range]"
STEP = "[$__interval]"
DAY = "1d"

RELEASED = 'event="TicketCreated"'
LANDED = 'event="TicketFinalizationSucceeded"'
REVOKED = 'event="TicketRevoked"'
# A stage's results: passed, then sent back or failed past its retries.
PASSED = 'event=~"TicketEvaluationProgressed|TicketEvaluationPassed"'
JUDGED = 'event=~"TicketEvaluationProgressed|TicketEvaluationPassed|TicketEvaluationReworkStarted|TicketEvaluationFailureEscalated"'
# The events that leave a ticket escalated, as kasofsk/chuggy's metricsPlaneEscalatingEvents lists them.
ESCALATING = (
    'event=~"TicketWorkProcessFailed|TicketWorkExecutionUnavailable|TicketEvaluationFailureEscalated'
    '|TicketEvaluationBlocked|TicketFinalizationUnavailable"'
)
OPEN = 'phase!~"Done|Revoked"'
# The bucket of the landed tickets no result sent back: the plane's first rework bound, as Prometheus stores it.
FIRST_PASS = 'le="0.0"'

BARS = " Each bar is a day, drawn once it has ended, and the legend totals the bars."
DAILY = " Each point is a day, drawn once it has ended."
APPROXIMATE = " Approximate: interpolated within coarse buckets."
STAGES = " A stage reads as its configuration names it, or as its number where the configuration names none."
SETTLED = " A ticket's cost is counted a little after it ends."
ESTIMATE = " An estimate, at list price."
NONE_LANDED = "None landed"

board = Board()


def events(match, window, by=None):
    grouping = f" by ({by})" if by else ""
    return f"sum{grouping} (increase({EVENTS}{{{S}, {match}}}{window}))"


def some(expr):
    """`expr`, where it is above zero: a denominator that leaves a ratio no value rather than NaN."""
    return f"({expr} > 0)"


def quantile(q, family, window, match="", by="le"):
    bucket = f"{family}_bucket{{{S}{match}}}{window}"
    return f"histogram_quantile({q}, sum by ({by}) (increase({bucket})))"


def summed(series, window, match=""):
    return f"sum(increase({series}{{{S}{match}}}{window}))"


def first_pass(window):
    landed = summed("chuggy_ticket_reworks_bucket", window, f", {FIRST_PASS}")
    return f"{landed} / {some(summed('chuggy_ticket_reworks_count', window))}"


def reworks(window):
    return f"{summed('chuggy_ticket_reworks_sum', window)} / {some(summed('chuggy_ticket_reworks_count', window))}"


def spent_per_landed(window):
    ended = summed(f"{COST}_sum", window)
    return f"{ended} / {some(summed(f'{COST}_count', window, DONE))}"


LEAD = "chuggy_ticket_lead_time_seconds"
RUN = "chuggy_ticket_run_time_seconds"
COST = "chuggy_ticket_cost_usd"
ESCALATION = "chuggy_ticket_escalation_duration_seconds"
DONE = ', end="Done"'


def times(window, instant):
    return [
        target("A", quantile("0.5", LEAD, window), "Lead time, median", instant=instant),
        target("B", quantile("0.9", LEAD, window), "Lead time, 90th percentile", instant=instant),
        target("C", quantile("0.5", RUN, window), "Run time, median", instant=instant),
        target("D", quantile("0.9", RUN, window), "Run time, 90th percentile", instant=instant),
    ]


def column(name, *properties):
    return {"matcher": {"id": "byName", "options": name}, "properties": list(properties)}


PHASE_COLOURS = colours([
    ("Pending", "yellow"), ("Work", "blue"), ("Evaluation", "purple"), ("Finalization", "light-green"),
    ("Escalated", "red"),
])
RED_FROM_ONE = [{"color": "green", "value": None}, {"color": "red", "value": 1}]

# At a glance: what the selected time added up to, and where tickets stand now.
board.row("At a glance", 0)
board.stat(
    "Released",
    "Tickets released over the selected time.",
    [target("A", events(RELEASED, RANGE), instant=True)],
    0, 1, 6, 4, "short", decimals=0,
)
board.stat(
    "Landed",
    "Tickets landed over the selected time.",
    [target("A", events(LANDED, RANGE), instant=True)],
    6, 1, 6, 4, "short", decimals=0,
)
board.stat(
    "Revoked",
    "Tickets revoked over the selected time, before or after their work began.",
    [target("A", events(REVOKED, RANGE), instant=True)],
    12, 1, 6, 4, "short", decimals=0,
)
board.stat(
    "Open now",
    "Tickets neither landed nor revoked, now: waiting, in work, in evaluation, landing or escalated.",
    [target("A", f"sum(chuggy_tickets{{{S}, {OPEN}}})", instant=True)],
    18, 1, 6, 4, "short", decimals=0,
)
board.stat(
    "Escalated now",
    "Tickets standing escalated now, each waiting to be resumed or revoked.",
    [target("A", f'sum(chuggy_tickets{{{S}, phase="Escalated"}})', instant=True)],
    0, 5, 6, 4, "short", decimals=0, thresholds=RED_FROM_ONE,
)
board.stat(
    "Escalations",
    "Times a ticket was escalated over the selected time, whatever escalated it.",
    [target("A", events(ESCALATING, RANGE), instant=True)],
    6, 5, 6, 4, "short", decimals=0,
)
board.stat(
    "First-pass rate",
    "Of the tickets landed over the selected time, the share no result sent back to work.",
    [target("A", first_pass(RANGE), instant=True)],
    12, 5, 6, 4, "percentunit", decimals=0, none=NONE_LANDED,
)
board.stat(
    "Reworks per landed ticket",
    "How many times a ticket landed over the selected time was sent back to work, on average: by a stage, by landing, or resumed to work after failing evaluation past its retries.",
    [target("A", reworks(RANGE), instant=True)],
    18, 5, 6, 4, "short", decimals=1, none=NONE_LANDED,
)
board.stat(
    "Median lead time",
    "Half the tickets landed over the selected time took longer than this from release to landing." + APPROXIMATE,
    [target("A", quantile("0.5", LEAD, RANGE), instant=True)],
    0, 9, 6, 4, "s", none=NONE_LANDED,
)
board.stat(
    "Mean wait before dispatch",
    "How long a ticket landed over the selected time waited from its release to its first dispatch, on average.",
    [target("A", f"({summed(LEAD + '_sum', RANGE)} - {summed(RUN + '_sum', RANGE)}) / {some(summed(LEAD + '_count', RANGE))}", instant=True)],
    6, 9, 6, 4, "s", none=NONE_LANDED,
)
board.stat(
    "Median landed ticket cost",
    "Half the tickets landed over the selected time cost more than this in runs." + SETTLED + APPROXIMATE + ESTIMATE,
    [target("A", quantile("0.5", COST, RANGE, DONE), instant=True)],
    12, 9, 6, 4, "currencyUSD", decimals=2, none=NONE_LANDED,
)
board.stat(
    "Spent per landed ticket",
    "What the tickets that ended over the selected time cost, landed and revoked alike, over the tickets landed in it: reworks and revoked tickets are in it, work still open is not."
    + SETTLED + ESTIMATE,
    [target("A", spent_per_landed(RANGE), instant=True)],
    18, 9, 6, 4, "currencyUSD", decimals=2, none=NONE_LANDED,
)

# Flow: what came in, what ended, and what stands open.
board.row("Flow", 13)
board.bars(
    "Released per day",
    "Tickets released each day." + BARS,
    [target("A", events(RELEASED, STEP), "Released")],
    0, 14, 12, 8, "short", DAY, decimals=0,
)
board.bars(
    "Landed and revoked per day",
    "Tickets that ended each day, by how." + BARS,
    [
        target("A", events(LANDED, STEP), "Landed"),
        target("B", events(REVOKED, STEP), "Revoked"),
    ],
    12, 14, 12, 8, "short", DAY, decimals=0,
    overrides=colours([("Landed", "green"), ("Revoked", "text")]),
)
board.lines(
    "Open tickets by phase",
    "Tickets standing in each open phase: the work in progress. The legend gives each phase's count now.",
    [target("A", f"sum by (phase) (chuggy_tickets{{{S}, {OPEN}}})", "{{phase}}")],
    0, 22, 12, 8, "short", decimals=0, overrides=PHASE_COLOURS,
)
board.bargauge(
    "Escalated now, by kind",
    "Tickets standing escalated now, by what escalated them.",
    [target("A", f'sum by (escalation) (chuggy_tickets{{{S}, phase="Escalated"}})', "{{escalation}}", instant=True)],
    12, 22, 12, 8, "short", none="None", tallest=32, named=True,
)

# Quality: how often a result sent a ticket back, and from where.
board.row("Quality", 30)
board.bars(
    "Sent back, by where",
    "Times a result sent a ticket back to work each day: by the evaluation stage that sent it, or by landing."
    + STAGES + BARS,
    [
        target("A", events('event="TicketEvaluationReworkStarted"', STEP, "stage"), "{{stage}}"),
        target("B", events('event="TicketFinalizationNeedsWork"', STEP), "Landing"),
    ],
    0, 31, 12, 8, "short", DAY, decimals=0,
)
board.bargauge(
    "Pass rate by stage",
    "Of each stage's results over the selected time, the share that passed it. Sent back and failed past its retries count against it; blocked counts neither way."
    + STAGES,
    [target("A", f"{events(PASSED, RANGE, 'stage')} / {some(events(JUDGED, RANGE, 'stage'))}", "{{stage}}", instant=True)],
    12, 31, 12, 8, "percentunit", none="No results", tallest=32, most=1, named=True,
)
board.lines(
    "First-pass rate per day",
    "Of the tickets landed each day, the share no result sent back to work." + DAILY,
    [target("A", first_pass(STEP), "First-pass rate")],
    0, 39, 12, 8, "percentunit", decimals=0, interval=DAY, most=1,
)
board.lines(
    "Reworks per landed ticket per day",
    "How many times a ticket landed each day was sent back to work, on average." + DAILY,
    [target("A", reworks(STEP), "Reworks per landed ticket")],
    12, 39, 12, 8, "short", decimals=1, interval=DAY,
)

# Time: how long a landed ticket took.
board.row("Time", 47)
board.bargauge(
    "Lead time and run time",
    "How long the tickets landed over the selected time took: lead time from release to landing, run time from first dispatch to landing, the median and the 90th percentile of each."
    + APPROXIMATE,
    times(RANGE, True),
    0, 48, 12, 8, "s", none=NONE_LANDED, tallest=32,
)
board.lines(
    "Lead time and run time per day",
    "How long the tickets landed each day took, the median and the 90th percentile of each." + APPROXIMATE + DAILY,
    times(STEP, False),
    12, 48, 12, 8, "s", interval=DAY,
)

# Escalations: how many, and how long they held, apart by who ended them.
board.row("Escalations", 56)
board.bars(
    "Escalations per day, by kind",
    "Times a ticket was escalated each day, by the event that escalated it." + BARS,
    [target("A", events(ESCALATING, STEP, "event"), "{{event}}")],
    0, 57, 12, 8, "short", DAY, decimals=0,
)
board.table(
    "How long escalations held",
    "Escalations that ended over the selected time, by the event that escalated the ticket and by who ended it: Member is a person, ExecutionScheduler an automatic resume. Each held from its escalation to the ticket's next entry."
    + APPROXIMATE,
    [
        target("A", f"sum by (event, by) (increase({ESCALATION}_count{{{S}}}{RANGE})) > 0", instant=True, table=True),
        target("B", f"{quantile('0.5', ESCALATION, RANGE, by='le, event, by')} >= 0", instant=True, table=True),
        target("C", f"{quantile('0.9', ESCALATION, RANGE, by='le, event, by')} >= 0", instant=True, table=True),
    ],
    12, 57, 12, 8,
    columns=[
        ("event", "Escalated by"), ("by", "Ended by"), ("Value #A", "Ended"),
        ("Value #B", "Median"), ("Value #C", "90th percentile"),
    ],
    hidden=["Time"],
    overrides=[
        column("Ended", {"id": "decimals", "value": 0}),
        *(column(name, {"id": "unit", "value": "s"}) for name in ("Median", "90th percentile")),
    ],
)

# Cost: what a landed ticket cost, and what the tickets that ended cost per ticket landed.
board.row("Cost", 65)
board.stat(
    "Cost of a landed ticket",
    "What the runs of a ticket landed over the selected time cost: the median and the 90th percentile."
    + SETTLED + APPROXIMATE + ESTIMATE,
    [
        target("A", quantile("0.5", COST, RANGE, DONE), "Median", instant=True),
        target("B", quantile("0.9", COST, RANGE, DONE), "90th percentile", instant=True),
    ],
    0, 66, 12, 4, "currencyUSD", decimals=2, none=NONE_LANDED,
)
board.stat(
    "Spent on revoked tickets",
    "What the runs of the tickets revoked over the selected time cost." + SETTLED + ESTIMATE,
    [target("A", summed(f"{COST}_sum", RANGE, ', end="Revoked"'), instant=True)],
    0, 70, 6, 4, "currencyUSD", decimals=2,
)
board.stat(
    "Spent on ticket work",
    "What all ticket work cost over the selected time, in work and in evaluation." + ESTIMATE,
    [target("A", summed("chuggy_run_cost_usd_total", RANGE), instant=True)],
    6, 70, 6, 4, "currencyUSD", decimals=2,
)
board.lines(
    "Cost per landed ticket per day",
    "Each day: what the tickets that ended that day cost, landed and revoked alike, over the tickets landed that day, and the median cost of a ticket landed that day."
    + SETTLED + ESTIMATE + DAILY,
    [
        target("A", spent_per_landed(STEP), "Ended tickets, per landed ticket"),
        target("B", quantile("0.5", COST, STEP, DONE), "A landed ticket, median"),
    ],
    12, 66, 12, 8, "currencyUSD", decimals=2, interval=DAY,
)

TICKETS = dashboard(
    "chuggy-tickets",
    "Chuggy tickets",
    "How chuggy's tickets are going: released, landed and revoked, how often a result sent one back and from where, how long one took, how long one stood escalated and what one cost, from the metrics plane. Costs are estimates at list price. Who narrows the page to the tickets the signed-in person created; it is a view, not a boundary.",
    "now-7d",
    "5m",
    [
        query_variable(
            "tenant", "Tenant",
            "label_values(chuggy_tickets, tenant)",
            "The tenants whose tickets the plane has counted.",
        ),
        query_variable(
            "project", "Project",
            'label_values(chuggy_tickets{tenant=~"$tenant"}, project)',
            "The selected tenants' projects.",
        ),
        who(
            "Everyone's tickets, or only those the signed-in person created.",
            [("Everyone", ".*"), ("Me", ME)],
            "Everyone",
        ),
    ],
    board.panels,
    links=[
        link(
            "Tickets in the console",
            "https://chuggy.vteng.io/",
            "Each ticket, in chuggy's console, which opens on the project last open there.",
        ),
    ],
)

MANIFEST = manifest(HEADER, "chuggy-tickets-dashboard", "chuggy-tickets.json", TICKETS)

if __name__ == "__main__":
    print(MANIFEST, end="")
