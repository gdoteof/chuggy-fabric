#!/usr/bin/env python3
"""Writes cluster/apps/ticket-timings-dashboard.yaml: python3 dashboards/ticket_timings.py > cluster/apps/ticket-timings-dashboard.yaml"""

from grafana import REPOSITORY, Board, ME, board_link, colours, dashboard, link, manifest, query_variable, target, who

HEADER = """\
# How long chuggy's tickets take, and where the time goes, on one page: how
# long work and evaluation cycles took, how a landed ticket's time divides
# between its phases, how long evaluation stages, the agent's runs and the
# wait for a runner took, and lead and run time, read from the series
# chuggy-metrics-plane-monitor.yaml has Prometheus scrape. It is the tickets
# page's deep dive on time, and each page's header links to the other.
#
# THE DASHBOARD'S UID IS AN ADDRESS. `/d/chuggy-ticket-timings` is the page,
# and a link handed to someone is not this file's to change: renaming the uid
# breaks every one already given out.
#
# A DISTRIBUTION IS A HISTOGRAM'S BUCKETS, COUNTED OVER THE SELECTED TIME, or
# over each day in a heatmap. Its query sums every bucket of one family by
# `le` alone and is read as a heatmap, so Grafana takes from each bucket the
# one below it and a bar or cell counts what fell in its bucket alone. A bar
# is named by its bound, the one named for five minutes counting what fell
# over the bound before it and up to five minutes.
#
# WHO AND REPOSITORY ARE VIEWS, NOT BOUNDARIES, as on the tickets page. Every
# selector matches `owner=~"$owner"` and `repository=~"$repository"`.
# Repository is the clone URL a ticket names, shown as owner and name; All is
# `.*`, which matches a ticket that names none too. Whoever signs in can
# query every series whatever this page shows.
#
# EVERY QUERY SUMS, AND ONLY BY ITS FAMILY'S OWN LABELS, so a release
# replacing the plane's pod draws no new line, and each ratio divides two sums
# grouped alike.
#
# A STAGE READS AS ITS CONFIGURATION NAMES IT, or as its number where the
# configuration names none, as on the tickets page.
#
# A RANGE COUNTS A SERIES FROM ITS FIRST VALUE, as on the usage page: the
# plane names when each series began, as its OpenMetrics `_created`, and
# Prometheus writes a zero at that time (cluster/apps/monitoring.yaml's
# created-timestamp-zero-ingestion).
#
# It is a plain ConfigMap for the reason release-dashboard.yaml's is: the
# sidecar finds it by label and nothing mounts it. dashboards/ticket_timings.py
# writes this file whole; tests/ticket-timings-dashboard.py holds it to that
# writer and to what its own header lists.
"""

S = 'tenant=~"$tenant", project=~"$project", repository=~"$repository", owner=~"$owner"'
RANGE = "[$__range]"
STEP = "[$__interval]"
DAY = "1d"

WORK_CYCLE = "chuggy_ticket_work_cycle_duration_seconds"
EVALUATION_CYCLE = "chuggy_ticket_evaluation_cycle_duration_seconds"
PHASE_TIME = "chuggy_ticket_phase_time_seconds"
WORK_CYCLES = "chuggy_ticket_work_cycles"
ATTEMPT = "chuggy_attempt_duration_seconds"
WAIT = "chuggy_attempt_wait_seconds"
LEAD = "chuggy_ticket_lead_time_seconds"
RUN = "chuggy_ticket_run_time_seconds"

# Each family's bounds, copied from kasofsk/chuggy's src/interpreter/metricsPlane.ts.
CYCLE_BOUNDS = (60, 120, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200, 10800, 14400, 28800)
WORK_CYCLE_BOUNDS = (1, 2, 3, 4, 5, 7, 10)
ATTEMPT_BOUNDS = (30, 60, 120, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200)
WAIT_BOUNDS = (10, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200, 14400)
TICKET_TIME_BOUNDS = (900, 1800, 3600, 7200, 14400, 28800, 86400, 172800, 345600, 604800, 1209600)

FIRST = 'began="TicketDispatched"'
LATER = 'began!="TicketDispatched"'
EVALUATION = 'phase="Evaluation"'
WORK = 'phase="Work"'
PHASES = ("Pending", "Work", "Evaluation", "Finalization", "Escalated")

BARS = " Each bar is a day, drawn once it has ended, and the legend totals the bars."
DAILY = " Each point is a day, drawn once it has ended."
APPROXIMATE = " Approximate: interpolated within coarse buckets."
STAGES = " A stage reads as its configuration names it, or as its number where the configuration names none."
BUCKETS = " Each bar counts those over the bound of the bar before and up to its own."
NONE_LANDED = "None landed"
NONE = "No data"

PHASE_COLOURS = colours([
    ("Pending", "yellow"), ("Work", "blue"), ("Evaluation", "purple"), ("Finalization", "light-green"),
    ("Escalated", "red"),
])
ENDED_COLOURS = colours([
    ("TicketWorkResultAccepted", "green"), ("TicketWorkProcessFailed", "red"),
    ("TicketWorkExecutionUnavailable", "orange"), ("TicketRevoked", "text"),
])

board = Board()


def selector(series, match=""):
    return f"{series}{{{S}{match}}}"


def some(expr):
    """`expr`, where it is above zero: a denominator that leaves a ratio no value rather than NaN."""
    return f"({expr} > 0)"


def summed(series, window, match="", by=None):
    grouping = f" by ({by})" if by else ""
    return f"sum{grouping} (increase({selector(series, match)}{window}))"


def mean(family, window, match="", by=None):
    return f"{summed(family + '_sum', window, match, by)} / {some(summed(family + '_count', window, match, by))}"


def quantile(q, family, window, match="", by=None):
    grouping = "le" + (f", {by}" if by else "")
    return f"histogram_quantile({q}, {summed(family + '_bucket', window, match, grouping)})"


def stored(bound):
    """A whole bound as Prometheus stores it as `le`: Go's shortest %g, which writes an
    exponent from a million, and `.0` added where that leaves neither point nor exponent."""
    digits = str(bound)
    if len(digits) <= 6:
        return f"{digits}.0"
    significant = digits.rstrip("0")
    point = f".{significant[1:]}" if len(significant) > 1 else ""
    return f"{significant[0]}{point}e+{len(digits) - 1:02d}"


def lasting(seconds):
    for unit, length in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % length == 0:
            return f"{seconds // length}{unit}"
    return f"{seconds}s"


def durations(bounds):
    """Each bucket's bound, as Prometheus stores it, and the name its bar reads."""
    return [(stored(bound), f"≤ {lasting(bound)}") for bound in bounds] + [("+Inf", f"> {lasting(bounds[-1])}")]


def counts(bounds):
    """Each bucket's bound, as Prometheus stores it, and the name its bar reads: the whole
    counts over the bound before and up to its own."""
    named, below = [], 0
    for bound in bounds:
        named.append((stored(bound), str(bound) if bound == below + 1 else f"{below + 1}–{bound}"))
        below = bound
    return named + [("+Inf", f"> {below}")]


def distribution(family, match=""):
    return [target("A", summed(family + "_bucket", RANGE, match, "le"), "{{le}}", instant=True, heatmap=True)]


def over_time(family, match=""):
    return [target("A", summed(family + "_bucket", STEP, match, "le"), "{{le}}", heatmap=True)]


def column(name, *properties):
    return {"matcher": {"id": "byName", "options": name}, "properties": list(properties)}


def ended_and_times(family, by, match=""):
    """A table's three queries: how many ended over the selected time, and the median and 90th percentile, by `by`."""
    return [
        target("A", f"{summed(family + '_count', RANGE, match, by)} > 0", instant=True, table=True),
        target("B", f"{quantile('0.5', family, RANGE, match, by)} >= 0", instant=True, table=True),
        target("C", f"{quantile('0.9', family, RANGE, match, by)} >= 0", instant=True, table=True),
    ]


def times_table(title, description, family, labels, counted, x, y, w, h, match=""):
    """A row for each combination of `labels`, each a label and its column's name: how many ended, the median and the 90th percentile."""
    by = ", ".join(label for label, _ in labels)
    board.table(
        title, description, ended_and_times(family, by, match), x, y, w, h,
        columns=[*labels, ("Value #A", counted), ("Value #B", "Median"), ("Value #C", "90th percentile")],
        hidden=["Time"],
        overrides=[
            column(counted, {"id": "decimals", "value": 0}),
            *(column(name, {"id": "unit", "value": "s"}) for name in ("Median", "90th percentile")),
        ],
    )


def medians_per_day(family, match, legend, ref="A", by=None):
    """The median and the 90th percentile per day, legends `legend` followed by which."""
    second = chr(ord(ref) + 1)
    return [
        target(ref, quantile("0.5", family, STEP, match, by), f"{legend}, median"),
        target(second, quantile("0.9", family, STEP, match, by), f"{legend}, 90th percentile"),
    ]


# At a glance: the medians of the selected time.
board.row("At a glance", 0)
board.stat(
    "Median work cycle",
    "Half the work cycles that ended over the selected time took longer than this, from the entry that put the ticket in work to its next entry."
    + APPROXIMATE,
    [target("A", quantile("0.5", WORK_CYCLE, RANGE), instant=True)],
    0, 1, 8, 4, "s", none=NONE,
)
board.stat(
    "Median evaluation cycle",
    "Half the evaluation cycles that ended over the selected time took longer than this, from the work's acceptance or a resume to the entry that took the ticket out of evaluation."
    + APPROXIMATE,
    [target("A", quantile("0.5", EVALUATION_CYCLE, RANGE), instant=True)],
    8, 1, 8, 4, "s", none=NONE,
)
board.stat(
    "Median lead time",
    "Half the tickets landed over the selected time took longer than this from release to landing." + APPROXIMATE,
    [target("A", quantile("0.5", LEAD, RANGE), instant=True)],
    16, 1, 8, 4, "s", none=NONE_LANDED,
)
board.stat(
    "Median run time",
    "Half the tickets landed over the selected time took longer than this from first dispatch to landing." + APPROXIMATE,
    [target("A", quantile("0.5", RUN, RANGE), instant=True)],
    0, 5, 8, 4, "s", none=NONE_LANDED,
)
board.stat(
    "Work cycles per landed ticket",
    "How many work cycles a ticket landed over the selected time went through, on average: its first, and one more each time it went back to work.",
    [target("A", mean(WORK_CYCLES, RANGE), instant=True)],
    8, 5, 8, 4, "short", decimals=1, none=NONE,
)
board.stat(
    "Median runner wait",
    "Half the attempts counted over the selected time waited longer than this from their opening to a runner's claim, in work and evaluation alike. Only an attempt a runner claimed is counted."
    + APPROXIMATE,
    [target("A", quantile("0.5", WAIT, RANGE), instant=True)],
    16, 5, 8, 4, "s", none=NONE,
)

# Where a landed ticket's time goes: its phases, which add up to its lead time.
board.row("Where a landed ticket's time goes", 9)
board.bargauge(
    "Mean time in each phase",
    "How long a ticket landed over the selected time spent in each phase, on average, a phase it never stood in counted as none. The five add up to the mean lead time.",
    [target(chr(ord("A") + at), mean(PHASE_TIME, RANGE, f', phase="{phase}"'), phase, instant=True) for at, phase in enumerate(PHASES)],
    0, 10, 12, 8, "s", overrides=PHASE_COLOURS, tallest=32,
)
times_table(
    "Time in each phase",
    "How long the tickets landed over the selected time spent in each phase: the median and the 90th percentile, a phase a ticket never stood in counted as none."
    + APPROXIMATE,
    PHASE_TIME, [("phase", "Phase")], "Landed",
    12, 10, 12, 8,
)
board.bars(
    "Mean time in each phase per day",
    "How long a ticket landed each day spent in each phase, on average, so each day's stack is that day's mean lead time. Each bar is a day, drawn once it has ended.",
    [target(chr(ord("A") + at), mean(PHASE_TIME, STEP, f', phase="{phase}"'), phase) for at, phase in enumerate(PHASES)],
    0, 18, 24, 8, "s", DAY, overrides=PHASE_COLOURS, totalled=False,
)

# Work cycles: each the span from the entry that put a ticket in work to its next.
board.row("Work cycles", 26)
board.distribution(
    "Work cycle durations",
    "Work cycles that ended over the selected time, by how long each took, from the entry that put the ticket in work to its next entry."
    + BUCKETS,
    distribution(WORK_CYCLE),
    0, 27, 12, 9, durations(CYCLE_BOUNDS),
)
board.heatmap(
    "Work cycle durations per day",
    "Work cycles that ended each day, by how long each took: a cell for each bucket, shaded by how many fell in it, the axis giving its bound."
    + " Each column is a day, drawn once it has ended.",
    over_time(WORK_CYCLE),
    12, 27, 12, 9, "s", DAY,
)
board.lines(
    "Work cycles per day",
    "How long the work cycles that ended each day took, the median and the 90th percentile: a ticket's first cycle, from its dispatch, apart from those that followed a rework, a resume or an invalidation."
    + APPROXIMATE + DAILY,
    medians_per_day(WORK_CYCLE, f", {FIRST}", "First") + medians_per_day(WORK_CYCLE, f", {LATER}", "Later", ref="C"),
    0, 36, 12, 8, "s", interval=DAY,
)
board.bars(
    "Work cycles ended per day, by how",
    "Work cycles that ended each day, by the entry that ended them: the work accepted, the process failed, no execution available, or the ticket revoked."
    + BARS,
    [target("A", summed(WORK_CYCLE + "_count", STEP, by="ended"), "{{ended}}")],
    12, 36, 12, 8, "short", DAY, decimals=0, overrides=ENDED_COLOURS,
)
times_table(
    "Work cycles by how they began and ended",
    "Work cycles that ended over the selected time, by the entry that began each and the one that ended it: how many, and the median and the 90th percentile of how long they took."
    + APPROXIMATE,
    WORK_CYCLE, [("began", "Began by"), ("ended", "Ended by")], "Cycles",
    0, 44, 12, 8,
)
board.distribution(
    "Work cycles per landed ticket",
    "Tickets landed over the selected time, by how many work cycles each went through." + BUCKETS,
    distribution(WORK_CYCLES),
    12, 44, 12, 8, counts(WORK_CYCLE_BOUNDS),
)

# Evaluation cycles: each the span from the work's acceptance, or a resume, to the entry that ended evaluation.
board.row("Evaluation cycles", 52)
board.distribution(
    "Evaluation cycle durations",
    "Evaluation cycles that ended over the selected time, by how long each took, from the work's acceptance or a resume to the entry that took the ticket out of evaluation."
    + BUCKETS,
    distribution(EVALUATION_CYCLE),
    0, 53, 12, 9, durations(CYCLE_BOUNDS),
)
board.heatmap(
    "Evaluation cycle durations per day",
    "Evaluation cycles that ended each day, by how long each took: a cell for each bucket, shaded by how many fell in it, the axis giving its bound."
    + " Each column is a day, drawn once it has ended.",
    over_time(EVALUATION_CYCLE),
    12, 53, 12, 9, "s", DAY,
)
board.lines(
    "Evaluation cycles per day",
    "How long the evaluation cycles that ended each day took, the median and the 90th percentile." + APPROXIMATE + DAILY,
    medians_per_day(EVALUATION_CYCLE, "", "Evaluation cycle"),
    0, 62, 12, 8, "s", interval=DAY,
)
times_table(
    "Evaluation cycles by how they began and ended",
    "Evaluation cycles that ended over the selected time, by the entry that began each and the one that took the ticket out of evaluation: how many, and the median and the 90th percentile of how long they took."
    + APPROXIMATE,
    EVALUATION_CYCLE, [("began", "Began by"), ("ended", "Ended by")], "Cycles",
    12, 62, 12, 8,
)
times_table(
    "Evaluation stages",
    "Evaluation attempts that ended over the selected time, by stage: how many, and the median and the 90th percentile of how long each ran, from a runner's claim, or its opening where no runner claimed it, to its end."
    + STAGES + APPROXIMATE,
    ATTEMPT, [("stage", "Stage")], "Attempts",
    0, 70, 12, 8, match=f", {EVALUATION}",
)
board.lines(
    "Evaluation stages per day",
    "How long the evaluation attempts that ended each day ran, the median of each stage." + STAGES + APPROXIMATE + DAILY,
    [target("A", quantile("0.5", ATTEMPT, STEP, f", {EVALUATION}", "stage"), "{{stage}}")],
    12, 70, 12, 8, "s", interval=DAY,
)

# Runs and runners: the agent's own run, and the wait before a runner claims an attempt.
board.row("Runs and runners", 78)
board.distribution(
    "Work attempt durations",
    "Work attempts that ended over the selected time, by how long each ran, from a runner's claim, or its opening where no runner claimed it, to its end: the agent's own run, which a work cycle holds with the time around it."
    + BUCKETS,
    distribution(ATTEMPT, f", {WORK}"),
    0, 79, 12, 9, durations(ATTEMPT_BOUNDS),
)
board.distribution(
    "Runner wait",
    "Attempts counted over the selected time, in work and evaluation alike, by how long each waited from its opening to a runner's claim. Only an attempt a runner claimed is counted, which leaves out most on the cluster."
    + BUCKETS,
    distribution(WAIT),
    12, 79, 12, 9, durations(WAIT_BOUNDS),
)
board.lines(
    "Runner wait per day, by placement",
    "How long the attempts counted each day waited for a runner's claim, by where they were placed, the median and the 90th percentile."
    + APPROXIMATE + DAILY,
    medians_per_day(WAIT, "", "{{placement}}", by="placement"),
    0, 88, 12, 8, "s", interval=DAY,
)
times_table(
    "Runner wait by phase and placement",
    "Attempts counted over the selected time, by phase and by where they were placed: how many, and the median and the 90th percentile of how long they waited for a runner's claim."
    + APPROXIMATE,
    WAIT, [("phase", "Phase"), ("placement", "Placement")], "Attempts",
    12, 88, 12, 8,
)

# Lead and run time: how long a landed ticket took, whole.
board.row("Lead and run time", 96)
board.distribution(
    "Lead time",
    "Tickets landed over the selected time, by how long each took from release to landing." + BUCKETS,
    distribution(LEAD),
    0, 97, 12, 9, durations(TICKET_TIME_BOUNDS),
)
board.distribution(
    "Run time",
    "Tickets landed over the selected time, by how long each took from first dispatch to landing." + BUCKETS,
    distribution(RUN),
    12, 97, 12, 9, durations(TICKET_TIME_BOUNDS),
)

TIMINGS = dashboard(
    "chuggy-ticket-timings",
    "Chuggy ticket timings",
    "How long chuggy's tickets take and where the time goes: work and evaluation cycles, a landed ticket's phases, evaluation stages, the agent's runs, the wait for a runner, and lead and run time, from the metrics plane. Who narrows the page to the tickets the signed-in person created, and Repository to those of a repository; each is a view, not a boundary.",
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
        query_variable(
            "repository", "Repository",
            'label_values(chuggy_tickets{tenant=~"$tenant", project=~"$project"}, repository)',
            "The repositories the selected projects' tickets name. All includes a ticket that names none.",
            regex=REPOSITORY,
        ),
        who(
            "Everyone's tickets, or only those the signed-in person created.",
            [("Everyone", ".*"), ("Me", ME)],
            "Everyone",
        ),
    ],
    board.panels,
    links=[
        board_link("Chuggy tickets", "chuggy-tickets", "How many tickets were released, landed and revoked, sent back, escalated, and what they cost."),
        link(
            "Tickets in the console",
            "https://chuggy.vteng.io/",
            "Each ticket, in chuggy's console, which opens on the project last open there.",
        ),
    ],
)

MANIFEST = manifest(HEADER, "chuggy-ticket-timings-dashboard", "chuggy-ticket-timings.json", TIMINGS)

if __name__ == "__main__":
    print(MANIFEST, end="")
