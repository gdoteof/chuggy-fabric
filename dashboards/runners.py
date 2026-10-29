#!/usr/bin/env python3
"""Writes cluster/apps/runners-dashboard.yaml: python3 dashboards/runners.py > cluster/apps/runners-dashboard.yaml"""

from grafana import Board, ME, colours, dashboard, manifest, query_variable, target, who

HEADER = """\
# Each runner reporting to chuggy's pool plane, on one page: what it is,
# whether its machine is healthy, what it is doing and how long its image
# pulls and runs take, read from the `chuggy_runner_*` series the pool plane
# serves of each runner whose report it holds.
#
# THE DASHBOARD'S UID IS AN ADDRESS. `/d/chuggy-runners` is the page, and a
# link handed to someone is not this file's to change: renaming the uid breaks
# every one already given out.
#
# WHO OPENS ON ME, AND IS A VIEW, NOT A BOUNDARY. Every selector matches
# `owner=~"$owner"`, and Who opens on Me, `${__user.login}`, which
# monitoring.yaml's `login_attribute_path` makes the subject the plane cuts a
# personal runner's `owner` from. A project's pool carries no owner and a
# personal runner no project, so Everyone with a Project is that project's
# pools, and Everyone alone is every runner. Every member signed in can query
# every series whatever this page shows.
#
# A RUNNER THAT STOPS REPORTING READS AS OFFLINE: Offline here is no report,
# not no poll. The plane serves a runner's series only while it holds a report
# younger than kasofsk/chuggy's `workerPoolReportAgeMsMax`, so a runner that
# stops reporting leaves the scrape rather than reading zero. Each table keys
# its rows on the last report seen in the selected time, so that runner keeps
# its row, with what is measured now left blank. Live and Offline are that
# report's age against the same bound, in the tables and the stats alike, and
# the Jobs and Sessions stats count the Live runners' latest reports: the plane
# keeps its reports in memory, so a runner it lost in a release reads Live
# until its report is older than the bound, not Offline or idle until it
# reports again.
#
# EVERY QUERY AGGREGATES BY THE RUNNER'S OWN LABELS, or by `host` where it
# reads the machine every runner on it measures alike, so a label Prometheus
# adds at the scrape draws no second line. Two machines reporting one host
# name read as one. A counter is read only through `increase`: a runner's
# counts start again when it does, and `increase` takes the fall for a
# restart. What a runner counted before its first report is in no range.
#
# A POOL-PLANE RELEASE CAN DROP A REPORT PERIOD OF COUNTS. Its ServiceMonitor
# keeps `pod` and `instance`, so a new pod's series are new series, and
# `increase` counts nothing between the old pod's last scraped report and the
# new pod's first: a report period's counts of each runner, two where the old
# pod's last report went unscraped. The plane serves no `_created`, so
# created timestamps do not recover them. The metrics plane's remedy,
# `labeldrop` with a `Recreate` rollout, would cut every runner's polls at each
# release of the one replica they all poll, so each total says it can fall
# short instead.
#
# It is a plain ConfigMap for the reason release-dashboard.yaml's is: the
# sidecar finds it by label and nothing mounts it. dashboards/runners.py writes
# this file whole; tests/runners-dashboard.py holds it to that writer and to
# what its own header lists.
"""

# Every family the plane serves of a runner carries all three.
S = 'tenant=~"$tenant", project=~"$project", owner=~"$owner"'
# The labels that tell one runner from another.
RUNNER = "tenant, project, pool, owner, personal_runner, host"
RANGE = "[$__range]"
STEP = "[$__interval]"
# kasofsk/chuggy's workerPoolReportAgeMsMax, in seconds: how long the plane holds a report.
HELD_SECS = 180
HELD = f"{HELD_SECS // 60} minutes"
# A project's pools, named by the key a pool is registered under, and members'
# own runners, by whose and where. Prometheus drops an empty label, and a
# legend naming an absent one prints the label's name, so each kind is queried
# apart under a legend of the labels it carries.
KINDS = (
    ('pool!=""', "{{tenant}}/{{project}} pool {{pool}}"),
    ('pool=""', "{{tenant}}/{{owner}} on {{host}}"),
)
# What a total that a pool-plane release can drop counts from says of it.
SHORT = " A pool-plane release can drop a report period of counts."


def now(family, by=RUNNER, only=""):
    """A gauge of each runner whose report the plane holds."""
    return f"max by ({by}) ({family}{{{S}{only}}})"


def seen(family, by=RUNNER):
    """A gauge's last value of each runner seen in the selected time."""
    return f"max by ({by}) (last_over_time({family}{{{S}}}{RANGE}))"


def counted(family, by, window, only=""):
    return f"sum by ({by}) (increase({family}{{{S}{only}}}{window}))"


def per_runner(refs, query, bound=""):
    """A line of `query(only)` for each runner, one target a kind. A bound's
    name leads its legend, which a legend too long for the panel cuts from the end."""
    return [
        target(ref, query(f", {only}"), f"{bound} {legend}" if bound else legend)
        for ref, (only, legend) in zip(refs, KINDS)
    ]


def quantile(ref, q, family, only, legend):
    bucket = f"{family}_bucket{{{S}{only}}}{RANGE}"
    return target(ref, f"histogram_quantile({q}, sum by (le) (increase({bucket})))", legend, instant=True)


REPORTED = "chuggy_runner_last_report_timestamp_seconds"
AGE = f"time() - {seen(REPORTED)}"
LIVE = f"count(({AGE}) <= {HELD_SECS})"
OFFLINE = f"count(({AGE}) > {HELD_SECS})"
MACHINE_AGE = f"time() - {seen(REPORTED, 'host')}"


def live(family):
    """A gauge's latest value of each Live runner, read from each pool-plane pod
    whose last report of that runner is at most the bound old: not an earlier
    pod's last value, which `seen` can read, and not nothing between a release
    and the runner's next report, which `now` reads."""
    fresh = f"(time() - last_over_time({REPORTED}{{{S}}}{RANGE})) <= {HELD_SECS}"
    return f"max by ({RUNNER}) (last_over_time({family}{{{S}}}{RANGE}) and {fresh})"


def machine(family):
    """A gauge of each machine a runner the plane holds measures it on."""
    return now(family, "host")


DASHED = [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}]


def dashed(pattern):
    """Dashed lines for the series whose legend `pattern` matches."""
    return {"matcher": {"id": "byRegexp", "options": pattern}, "properties": DASHED}


def column(name, *properties):
    return {"matcher": {"id": "byName", "options": name}, "properties": list(properties)}


def unit(value):
    return {"id": "unit", "value": value}


STATUS = column(
    "Status",
    {"id": "mappings", "value": [
        {"type": "range", "options": {"to": HELD_SECS, "result": {"text": "Live", "color": "green", "index": 0}}},
        {"type": "range", "options": {"from": HELD_SECS, "result": {"text": "Offline", "color": "red", "index": 1}}},
    ]},
    {"id": "custom.cellOptions", "value": {"type": "color-text"}},
)
RED_FROM_ONE = [{"color": "green", "value": None}, {"color": "red", "value": 1}]

board = Board()

# What each runner is, and whether it is reporting.
board.row("At a glance", 0)
board.stat(
    "Live",
    f"Runners whose last report is at most {HELD} old.",
    [target("A", LIVE, instant=True)],
    0, 1, 4, 4, "short", decimals=0,
)
board.stat(
    "Offline",
    f"Runners seen in the selected time whose last report is over {HELD} old.",
    [target("A", OFFLINE, instant=True)],
    4, 1, 4, 4, "short", decimals=0, thresholds=RED_FROM_ONE,
)
board.stat(
    "Jobs",
    "Jobs the Live runners run, as each last reported, and the most they take at once.",
    [
        target("A", f"sum({live('chuggy_runner_jobs_running')})", "Running", instant=True),
        target("B", f"sum({live('chuggy_runner_jobs_max')})", "Most", instant=True),
    ],
    8, 1, 4, 4, "short", decimals=0,
)
board.stat(
    "Sessions",
    "Sessions the Live runners run, as each last reported, and the most they take at once.",
    [
        target("A", f"sum({live('chuggy_runner_sessions_running')})", "Running", instant=True),
        target("B", f"sum({live('chuggy_runner_sessions_max')})", "Most", instant=True),
    ],
    12, 1, 4, 4, "short", decimals=0,
)
board.stat(
    "Failed polls",
    "Polls that never reached the plane over the selected time." + SHORT,
    [target("A", f"sum(increase(chuggy_runner_polls_failed_total{{{S}}}{RANGE}))", instant=True)],
    16, 1, 4, 4, "short", decimals=0, thresholds=RED_FROM_ONE,
)
board.stat(
    "Refusals",
    "Assignments the runners refused over the selected time." + SHORT,
    [target("A", f"sum(increase(chuggy_runner_refusals_total{{{S}}}{RANGE}))", instant=True)],
    20, 1, 4, 4, "short", decimals=0, thresholds=RED_FROM_ONE,
)
board.table(
    "Runners",
    f"Every runner seen in the selected time; Offline has not reported in over {HELD}.",
    [
        target("A", AGE, instant=True, table=True),
        target("B", f"{seen(REPORTED)} * 1000", instant=True, table=True),
        target("C", f"{seen('chuggy_runner_last_poll_timestamp_seconds')} * 1000", instant=True, table=True),
        target("D", now("chuggy_runner_uptime_seconds"), instant=True, table=True),
        target("E", f"max by ({RUNNER}, package, version) (chuggy_runner_info{{{S}}})", instant=True, table=True),
    ],
    0, 5, 24, 12,
    columns=[
        ("host", "Machine"), ("Value #A", "Status"), ("Value #B", "Last report"), ("Value #C", "Last poll"),
        ("Value #D", "Uptime"), ("package", "Runner"), ("version", "Version"),
        ("tenant", "Tenant"), ("project", "Project"), ("pool", "Pool"), ("owner", "Member"),
    ],
    hidden=["Time", "personal_runner", "Value #E"],
    overrides=[
        STATUS,
        column("Last report", unit("dateTimeFromNow")),
        column("Last poll", unit("dateTimeFromNow")),
        column("Uptime", unit("dtdurations")),
    ],
)

# Whether each runner's machine is healthy.
board.row("Health", 17)
board.table(
    "Machines",
    "Each machine the runners seen run on, as the reports the plane holds now give it; Disk floor is its runners' highest.",
    [
        target("A", MACHINE_AGE, instant=True, table=True),
        target("B", machine("chuggy_runner_disk_free_bytes"), instant=True, table=True),
        target("C", machine("chuggy_runner_disk_floor_bytes"), instant=True, table=True),
        target("D", machine("chuggy_runner_machine_memory_available_bytes"), instant=True, table=True),
        target("E", machine("chuggy_runner_machine_memory_total_bytes"), instant=True, table=True),
        target("F", machine("chuggy_runner_machine_cpus"), instant=True, table=True),
        target("G", machine("chuggy_runner_machine_load1"), instant=True, table=True),
    ],
    0, 18, 24, 5,
    columns=[
        ("host", "Machine"), ("Value #A", "Status"), ("Value #B", "Disk free"), ("Value #C", "Disk floor"),
        ("Value #D", "Memory available"), ("Value #E", "Memory total"), ("Value #F", "CPUs"), ("Value #G", "Load"),
    ],
    hidden=["Time"],
    overrides=[
        STATUS,
        *(column(name, unit("bytes")) for name in ("Disk free", "Disk floor", "Memory available", "Memory total")),
        column("CPUs", {"id": "decimals", "value": 0}),
        column("Load", {"id": "decimals", "value": 2}),
    ],
)
board.lines(
    "Disk free",
    "Free disk on each machine, and the highest floor below which a runner on it takes no job.",
    [
        target("A", machine("chuggy_runner_disk_free_bytes"), "{{host}}"),
        target("B", machine("chuggy_runner_disk_floor_bytes"), "{{host}} floor"),
    ],
    0, 23, 12, 8, "bytes", overrides=[dashed(".* floor$")],
)
board.lines(
    "Memory available",
    "Memory each machine has available, and all it has.",
    [
        target("A", machine("chuggy_runner_machine_memory_available_bytes"), "{{host}}"),
        target("B", machine("chuggy_runner_machine_memory_total_bytes"), "{{host}} total"),
    ],
    12, 23, 12, 8, "bytes", overrides=[dashed(".* total$")],
)
board.lines(
    "Memory room",
    "The memory room and ceiling each runner's latest poll named.",
    per_runner("AB", lambda only: now("chuggy_runner_memory_room_bytes", only=only))
    + per_runner("CD", lambda only: now("chuggy_runner_memory_ceiling_bytes", only=only), "Ceiling"),
    0, 31, 12, 8, "bytes", overrides=[dashed("^Ceiling .*")],
)
board.lines(
    "Load per CPU",
    "Each machine's one-minute load average over its CPUs.",
    [target("A", f"{machine('chuggy_runner_machine_load1')} / {machine('chuggy_runner_machine_cpus')}", "{{host}}")],
    12, 31, 12, 8, "percentunit",
)

# What each runner is doing.
board.row("Work", 39)
board.lines(
    "Jobs running",
    "Jobs each runner runs, and the most it takes at once.",
    per_runner("AB", lambda only: now("chuggy_runner_jobs_running", only=only))
    + per_runner("CD", lambda only: now("chuggy_runner_jobs_max", only=only), "Most"),
    0, 40, 12, 8, "short", decimals=0, overrides=[dashed("^Most .*")],
)
board.lines(
    "Sessions running",
    "Sessions each runner runs, and the most it takes at once.",
    per_runner("AB", lambda only: now("chuggy_runner_sessions_running", only=only))
    + per_runner("CD", lambda only: now("chuggy_runner_sessions_max", only=only), "Most"),
    12, 40, 12, 8, "short", decimals=0, overrides=[dashed("^Most .*")],
)


def bars(title, description, targets, x, y, overrides=()):
    board.bars(title, description + SHORT, targets, x, y, 12, 8, "short", "5m", decimals=0, overrides=overrides, points=100)


bars(
    "Polls by runner",
    "Polls each runner made.",
    per_runner("AB", lambda only: counted("chuggy_runner_polls_total", RUNNER, STEP, only)),
    0, 48,
)
bars(
    "Failed polls by runner",
    "Polls each runner made that never reached the plane.",
    per_runner("AB", lambda only: counted("chuggy_runner_polls_failed_total", RUNNER, STEP, only)),
    12, 48,
)
bars(
    "Settlements by outcome",
    "Assignments the runners settled, by outcome.",
    [target("A", counted("chuggy_runner_settlements_total", "outcome", STEP), "{{outcome}}")],
    0, 56, colours([("Accepted", "green"), ("Refused", "red"), ("Unavailable", "orange")]),
)
bars(
    "Refusals by fault",
    "Assignments the runners refused, by the image fault named; Other named none.",
    [target("A", counted("chuggy_runner_refusals_total", "fault", STEP), "{{fault}}")],
    12, 56, [column("NoFault", {"id": "displayName", "value": "Other"})],
)
bars(
    "Jobs ended",
    "Jobs the runners ran that ended, by how.",
    [target("A", counted("chuggy_runner_jobs_ended_total", "end", STEP), "{{end}}")],
    0, 64, colours([
        ("Succeeded", "green"), ("Failed", "red"), ("Deadline", "orange"), ("DiskLow", "purple"),
        ("Stopped", "text"), ("PlacementFailed", "dark-red"),
    ]),
)
bars(
    "Sessions ended",
    "Sessions the runners ran that ended, by how.",
    [target("A", counted("chuggy_runner_sessions_ended_total", "end", STEP), "{{end}}")],
    12, 64, colours([("Succeeded", "green"), ("Failed", "red")]),
)

# How long things take.
board.row("Durations", 72)
board.bargauge(
    "Image pulls",
    "The median and 90th percentile image pull over the selected time." + SHORT,
    [
        quantile("A", "0.5", "chuggy_runner_image_pull_seconds", "", "Median"),
        quantile("B", "0.9", "chuggy_runner_image_pull_seconds", "", "90th percentile"),
    ],
    0, 73, 12, 8, "s", none="None", tallest=48,
)
board.bargauge(
    "Runs",
    "The median and 90th percentile job and session over the selected time." + SHORT,
    [
        quantile(ref, q, "chuggy_runner_run_seconds", f', kind="{kind}"', f"{kind}, {name}")
        for ref, kind, q, name in (
            ("A", "Job", "0.5", "median"), ("B", "Job", "0.9", "90th percentile"),
            ("C", "Session", "0.5", "median"), ("D", "Session", "0.9", "90th percentile"),
        )
    ],
    12, 73, 12, 8, "s", none="None", tallest=48,
)

RUNNERS = dashboard(
    "chuggy-runners",
    "Chuggy runners",
    "Each runner reporting to chuggy: what it is, whether its machine is healthy, what it is doing and how long its pulls and runs take. A runner reports only where its own configuration turns reporting on. "
    f"Offline is a runner seen in the selected time that has not reported in over {HELD}. "
    "What a runner counted before its first report is in no total, and a pool-plane release can drop a report period of counts. Who opens on your own runners; Everyone widens it to every runner, and a Project to that project's pools. It is a view, not a boundary.",
    "now-24h",
    "1m",
    [
        query_variable(
            "tenant", "Tenant",
            f"label_values({REPORTED}, tenant)",
            "The tenants of the runners seen.",
        ),
        query_variable(
            "project", "Project",
            f'label_values({REPORTED}{{tenant=~"$tenant"}}, project)',
            "The projects whose pools were seen. A member's own runners are in none.",
        ),
        who(
            "Your own runners, or every runner, every project's pools among them.",
            [("Me", ME), ("Everyone", ".*")],
            "Me",
        ),
    ],
    board.panels,
)

MANIFEST = manifest(HEADER, "chuggy-runners-dashboard", "chuggy-runners.json", RUNNERS)

if __name__ == "__main__":
    print(MANIFEST, end="")
