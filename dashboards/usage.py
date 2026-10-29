#!/usr/bin/env python3
"""Writes cluster/apps/usage-dashboard.yaml: python3 dashboards/usage.py > cluster/apps/usage-dashboard.yaml"""

from grafana import Board, ME, colours, dashboard, manifest, query_variable, target, who

HEADER = """\
# What chuggy's ticket work and chat cost, how long they took and how they
# ended, on one page, read from the series chuggy-metrics-plane-monitor.yaml
# has Prometheus scrape.
#
# THE DASHBOARD'S UID IS AN ADDRESS. `/d/chuggy-usage` is the page, and a link
# handed to someone is not this file's to change: renaming the uid breaks every
# one already given out.
#
# WHO IS A VIEW, NOT A BOUNDARY. Every selector of a family that carries an
# owner matches `owner=~"$owner"`. Everyone is `.*`, and Me is
# `${__user.login}`, which Grafana fills with the signed-in person's login;
# monitoring.yaml's `login_attribute_path` makes that login the subject the
# plane cuts its `owner` label from. Every member signed in can query every
# series whatever this page shows. A ticket's count carries no owner, so
# Tickets by phase is not narrowed by Who, and its description says so.
#
# EVERY QUERY SUMS, AND ONLY BY ITS FAMILY'S OWN LABELS. A family's series
# differ by every label it carries -- stage, workload, placement and the rest
# -- so a panel that did not sum would draw a line for each combination of
# them rather than one for what it asks. Where one question covers ticket work
# and chat alike -- spend and tokens -- the two families are named in one
# selector's `__name__` and summed together.
#
# A RANGE HOLDS WHAT A SERIES ROSE BY WHILE PROMETHEUS WATCHED IT. Each counter
# is a total over every row the plane reads, and `increase` counts only the
# rise between two scrapes of one series. What a series reports when it first
# appears is in no range: all of its history the first time Prometheus scraped
# the plane, and the first rows of every combination of labels that appears
# after. So every panel built on `increase` leaves some out, and its
# description says so, until the plane marks when each series began. Until
# then no alert rule may reuse these queries: a new combination's first Lost
# attempt, say, would never fire one.
#
# It is a plain ConfigMap for the reason release-dashboard.yaml's is: the
# sidecar finds it by label and nothing mounts it. dashboards/usage.py writes
# this file whole; tests/usage-dashboard.py holds it to that writer and to
# what its own header lists.
"""

# Every family carrying an owner is narrowed by all three; chuggy_tickets by two.
S = 'tenant=~"$tenant", project=~"$project", owner=~"$owner"'
T = 'tenant=~"$tenant", project=~"$project"'
COST = '__name__=~"chuggy_run_cost_usd_total|chuggy_session_turn_cost_usd_total"'
TOKENS = '__name__=~"chuggy_run_tokens_total|chuggy_session_turn_tokens_total"'

BARS = " Each bar is an hour or more, drawn once it has ended, and the legend totals the bars."
# Every panel but Tickets by phase is built on increase(), which cannot count a series' first value.
UNCOUNTED = "a new series' first value is not counted."
LOW = " Reads low for now: " + UNCOUNTED
PART = " Leaves some out for now: " + UNCOUNTED

board = Board()


def row(title, y):
    board.row(title, y)


def stat(title, description, targets, x, y, w, h, unit, decimals=None, thresholds=None, note=LOW):
    board.stat(title, description + note, targets, x, y, w, h, unit, decimals, thresholds)


def bars(title, description, targets, x, y, w, h, unit, decimals=None, overrides=()):
    board.bars(title, description + BARS + LOW, targets, x, y, w, h, unit, "1h", decimals, overrides)


def bargauge(title, description, targets, x, y, w, h, unit, overrides=(), note=LOW):
    board.bargauge(title, description + note, targets, x, y, w, h, unit, overrides)


RANGE = "[$__range]"
STEP = "[$__interval]"

ATTEMPT_COLOURS = colours([
    ("Reported", "green"),
    ("Lost", "red"),
    ("Withdrawn", "text"),
    ("Superseded", "blue"),
])
TURN_COLOURS = colours([
    ("Answered", "green"),
    ("Failed", "red"),
    ("Abandoned", "orange"),
])
AGENT = 'runner="Agent"'
CI = 'runner="Commands", phase="Evaluation"'

# At a glance: what the selected time added up to.
row("At a glance", 0)
stat(
    "Spent",
    "What ticket work and chat cost over the selected time. An estimate, at list price.",
    [target("A", f"sum(increase({{{COST}, {S}}}{RANGE}))", instant=True)],
    0, 1, 4, 4, "currencyUSD", decimals=2,
)
stat(
    "Tokens",
    "Tokens ticket work and chat spent over the selected time, of every kind.",
    [target("A", f"sum(increase({{{TOKENS}, {S}}}{RANGE}))", instant=True)],
    4, 1, 4, 4, "short", decimals=0,
)
stat(
    "Agent turns",
    "Turns the agents took on ticket work over the selected time.",
    [target("A", f"sum(increase(chuggy_run_turns_total{{{S}}}{RANGE}))", instant=True)],
    8, 1, 4, 4, "short", decimals=0,
)
stat(
    "Agent time",
    "How long the attempts of stages an agent runs were open, in work and in review, added up over the selected time.",
    [target("A", f"sum(increase(chuggy_attempt_duration_seconds_sum{{{S}, {AGENT}}}{RANGE}))", instant=True)],
    12, 1, 4, 4, "s",
)
stat(
    "CI time",
    "How long the attempts of evaluation's stages that run commands were open, added up over the selected time.",
    [target("A", f"sum(increase(chuggy_attempt_duration_seconds_sum{{{S}, {CI}}}{RANGE}))", instant=True)],
    16, 1, 4, 4, "s",
)
stat(
    "Lost attempts",
    "Attempts that ran and ended without a result over the selected time. Each counts against the retries its work is allowed.",
    [target("A", f'sum(increase(chuggy_attempts_ended_total{{{S}, state="Lost"}}{RANGE}))', instant=True)],
    20, 1, 4, 4, "short", decimals=0,
    thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
)
# Spend: ticket work and chat together.
row("Spend", 5)
bars(
    "Spent by project",
    "What ticket work and chat cost, by project. An estimate, at list price.",
    [target("A", f"sum by (tenant, project) (increase({{{COST}, {S}}}{STEP}))", "{{tenant}}/{{project}}")],
    0, 6, 12, 9, "currencyUSD", decimals=2,
)
bars(
    "Spent by model",
    "What ticket work and chat cost, by model. An estimate, at list price.",
    [target("A", f"sum by (model) (increase({{{COST}, {S}}}{STEP}))", "{{model}}")],
    12, 6, 12, 9, "currencyUSD", decimals=2,
)

# Ticket work.
row("Ticket work", 15)
bars(
    "Tokens by type",
    "Tokens ticket work spent, by kind of token. Chat's tokens carry no kind and are under Chat.",
    [target("A", f"sum by (type) (increase(chuggy_run_tokens_total{{{S}}}{STEP}))", "{{type}}")],
    0, 16, 12, 8, "short", decimals=0,
)
bars(
    "Agent turns by phase",
    "Turns the agents took, in work and in evaluation.",
    [target("A", f"sum by (phase) (increase(chuggy_run_turns_total{{{S}}}{STEP}))", "{{phase}}")],
    12, 16, 12, 8, "short", decimals=0,
)
bars(
    "Agent and CI time",
    "How long attempts were open: Agent is every stage an agent runs, in work and in review; CI is evaluation's stages that run commands.",
    [
        target("A", f"sum(increase(chuggy_attempt_duration_seconds_sum{{{S}, {AGENT}}}{STEP}))", "Agent"),
        target("B", f"sum(increase(chuggy_attempt_duration_seconds_sum{{{S}, {CI}}}{STEP}))", "CI"),
    ],
    0, 24, 12, 8, "s",
)


def quantile(ref, q, which, legend):
    bucket = f"chuggy_attempt_duration_seconds_bucket{{{S}, {which}}}{RANGE}"
    return target(ref, f"histogram_quantile({q}, sum by (le) (increase({bucket})))", legend, instant=True)


bargauge(
    "How long one attempt takes",
    "The median and the 90th percentile of how long one attempt was open over the selected time: Agent for stages an agent runs, CI for evaluation's stages that run commands.",
    [
        quantile("A", "0.5", AGENT, "Agent, median"),
        quantile("B", "0.5", CI, "CI, median"),
        quantile("C", "0.9", AGENT, "Agent, 90th percentile"),
        quantile("D", "0.9", CI, "CI, 90th percentile"),
    ],
    12, 24, 12, 8, "s", note=PART,
)
bars(
    "How attempts ended",
    "Attempts that ended, by how. Lost ran and ended without a result; Withdrawn was never run, or was held; Superseded was replaced by another.",
    [target("A", f"sum by (state) (increase(chuggy_attempts_ended_total{{{S}}}{STEP}))", "{{state}}")],
    0, 32, 12, 8, "short", decimals=0, overrides=ATTEMPT_COLOURS,
)
bars(
    "Where work ran",
    "How long attempts were open, by where they were placed: in the cluster, on a pool's runner, or on a member's own.",
    [target("A", f"sum by (placement) (increase(chuggy_attempt_duration_seconds_sum{{{S}}}{STEP}))", "{{placement}}")],
    12, 32, 12, 8, "s",
)

# Chat.
row("Chat", 40)
bars(
    "How chat turns ended",
    "Chat turns that ended, by how.",
    [target("A", f"sum by (state) (increase(chuggy_session_turns_ended_total{{{S}}}{STEP}))", "{{state}}")],
    0, 45, 12, 8, "short", decimals=0, overrides=TURN_COLOURS,
)
bars(
    "Chat tokens by model",
    "Tokens chat turns spent, by model.",
    [target("A", f"sum by (model) (increase(chuggy_session_turn_tokens_total{{{S}}}{STEP}))", "{{model}}")],
    12, 45, 12, 8, "short", decimals=0,
)
stat(
    "Chat turns",
    "Chat turns that ended over the selected time, however they ended.",
    [target("A", f"sum(increase(chuggy_session_turns_ended_total{{{S}}}{RANGE}))", instant=True)],
    0, 41, 6, 4, "short", decimals=0,
)
stat(
    "Chat spent",
    "What chat turns cost over the selected time. An estimate, at list price.",
    [target("A", f"sum(increase(chuggy_session_turn_cost_usd_total{{{S}}}{RANGE}))", instant=True)],
    6, 41, 6, 4, "currencyUSD", decimals=2,
)
stat(
    "Chat tokens",
    "Tokens chat turns spent over the selected time.",
    [target("A", f"sum(increase(chuggy_session_turn_tokens_total{{{S}}}{RANGE}))", instant=True)],
    12, 41, 6, 4, "short", decimals=0,
)
stat(
    "Chat turn time",
    "How long chat turns took over the selected time: all of them added up, and the 90th percentile turn.",
    [
        target("A", f"sum(increase(chuggy_session_turn_duration_seconds_sum{{{S}}}{RANGE}))", "Total", instant=True),
        target(
            "B",
            f"histogram_quantile(0.9, sum by (le) (increase(chuggy_session_turn_duration_seconds_bucket{{{S}}}{RANGE})))",
            "90th percentile",
            instant=True,
        ),
    ],
    18, 41, 6, 4, "s", note=PART,
)

# Tickets.
row("Tickets", 53)
bargauge(
    "Tickets by phase",
    "Every ticket, by the phase it stands in now. Who does not narrow it: a ticket's count carries no owner.",
    [target("A", f"sum by (phase) (chuggy_tickets{{{T}}})", "{{phase}}", instant=True)],
    0, 54, 24, 7, "short", note="",
    overrides=colours([
        ("Pending", "yellow"), ("Work", "blue"), ("Evaluation", "purple"), ("Finalization", "light-green"),
        ("Done", "green"), ("Escalated", "red"), ("Revoked", "text"),
    ]),
)

SOURCE = '{__name__=~"chuggy_tickets|chuggy_session_turns_ended_total"'

USAGE = dashboard(
    "chuggy-usage",
    "Chuggy usage",
    "What chuggy's ticket work and chat cost, how long they took and how they ended, from the metrics plane. Costs are estimates at list price. Until the plane marks when each series began, every total but tickets by phase reads low: the first value of each new combination of labels counts nowhere. Who narrows the page to the person signed in; it is a view, not a boundary.",
    "now-7d",
    "5m",
    [
        query_variable(
            "tenant", "Tenant",
            f"label_values({SOURCE}}}, tenant)",
            "The tenants whose tickets or chat the plane has counted.",
        ),
        query_variable(
            "project", "Project",
            f'label_values({SOURCE}, tenant=~"$tenant"}}, project)',
            "The selected tenants' projects.",
        ),
        who(
            "Everyone's work and chat, or only the signed-in person's.",
            [("Everyone", ".*"), ("Me", ME)],
            "Everyone",
        ),
    ],
    board.panels,
)

MANIFEST = manifest(HEADER, "chuggy-usage-dashboard", "chuggy-usage.json", USAGE)

if __name__ == "__main__":
    print(MANIFEST, end="")
