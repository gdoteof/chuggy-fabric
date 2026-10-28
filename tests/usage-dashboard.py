#!/usr/bin/env python3
"""Refuse a cluster whose usage dashboard would come up empty, or show more or
less than it says, with nothing reporting why.

- A dashboard the sidecar does not deliver, a document Grafana cannot parse, a
  uid other than the one links are written to, and a query naming a datasource
  other than the chart's Prometheus are each an empty page or a page at
  another address.
- A selector naming a series the plane does not serve draws "No data". The
  plane's families and each one's labels are copied below from kasofsk/chuggy's
  `src/interpreter/metricsPlane.ts`; a family the plane renames, or a label it
  drops, is not seen here until the copy is changed with it.
- A matcher on a label its family does not carry matches nothing once its
  value is narrowed: `owner` on chuggy_tickets is every ticket under Everyone
  and none under Me.
- A selector without the tenant and project matchers, or without the owner
  matcher where any family it names has an owner, is a panel the variables do
  not narrow, and nothing on the page says so.
- A selector no aggregation encloses reaches the panel as scraped, one series
  per combination of its family's labels. A grouping by a label its family
  does not carry is one series with that label empty. `without` keeps every
  label it does not name, those Prometheus adds at the scrape among them, so it
  is refused rather than read. Any other grouping is bounded by the plane,
  which labels nothing by ticket, execution, attempt or session: its `session`
  is the kind of session.
- `increase` or `rate` of a gauge means nothing, and a bucket series any
  aggregation on its way into histogram_quantile sums without `le` leaves it
  nothing to read.
- A stat or a bar gauge shows one value for the selected time and a time series
  one for each step, so the one reads an instant query over `[$__range]` and
  the other a range query over `[$__interval]`. Either window in the other
  panel counts a span the panel does not say, and either query in it draws
  the wrong shape. A kind of panel not named here is refused rather than read.
- A variable a query names that the page does not define reaches Prometheus as
  text, and Who without `${__user.login}` among its values has no Me.

WHAT THIS CANNOT READ IT REFUSES rather than passes: PromQL beyond the grammar
below -- `without`, `offset`, `@`, a subquery, vector matching, a comparison --
and a `__name__` matcher other than an alternation of names.

It does not read what a query means, that the plane is scraped
(tests/metrics-plane.py holds that), or that Grafana fills `${__user.login}`
with the login monitoring.yaml names.
"""

import json
import re
import sys
from pathlib import Path

import yaml

NAMESPACE = "monitoring"
DASHBOARD = "chuggy-usage-dashboard"
UID = "chuggy-usage"
# The label and value the chart's dashboard sidecar watches for.
SIDECAR = ("grafana_dashboard", "1")
# The datasource the chart provisions for its own Prometheus.
DATASOURCE = "prometheus"
ME = "${__user.login}"
# The variables Grafana defines on every page that a query here may name.
BUILT_IN = {"__range", "__interval", "__rate_interval"}

# Each family the plane serves, its type and its labels.
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
# What every selector matches, and what one naming a family with an owner adds.
NARROWED = {"tenant": '=~"$tenant"', "project": '=~"$project"'}
OWNED = {"owner": '=~"$owner"'}

# Each kind of panel: whether its queries are instant, and the window increase reads.
PANELS = {
    "stat": (True, "$__range"),
    "bargauge": (True, "$__range"),
    "timeseries": (False, "$__interval"),
}

AGGREGATIONS = {"sum", "min", "max", "avg", "count"}
FUNCTIONS = {"increase", "rate", "histogram_quantile"}
OPERATORS = {"+", "-", "*", "/", "or", "and", "unless"}
TOKEN = re.compile(
    r"""(?P<space>\s+)
      |(?P<number>\d+(?:\.\d+)?)
      |(?P<name>[A-Za-z_][A-Za-z0-9_:]*)
      |(?P<braces>\{(?:[^{}"]|"(?:[^"\\]|\\.)*")*\})
      |(?P<range>\[[^\[\]]*\])
      |(?P<punctuation>[-+*/(),])""",
    re.X,
)
MATCHER = re.compile(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*(=~|!~|!=|=)\s*("(?:[^"\\]|\\.)*")\s*(?:,|$)')
VARIABLE = re.compile(r"\$\{([A-Za-z0-9_]+)(?:[.:][^}]*)?\}|\$([A-Za-z0-9_]+)|\[\[([A-Za-z0-9_]+)")
LABEL_VALUES = re.compile(r"^label_values\((.+),\s*([A-Za-z_][A-Za-z0-9_]*)\)$")


def refuse(message):
    raise SystemExit(f"usage-dashboard: {message}")


class Selector:
    def __init__(self, metric, braces, enclosing):
        self.metric = metric
        self.matchers = matchers_of(braces)
        self.enclosing = enclosing
        self.range = None


def matchers_of(braces):
    inside = (braces or "{}")[1:-1]
    found, at = [], 0
    while inside[at:].strip():
        match = MATCHER.match(inside, at)
        if match is None:
            raise ValueError(f"a matcher this check does not read in {braces}")
        found.append((match[1], match[2], json.loads(match[3])))
        at = match.end()
    return found


class Expression:
    """The selectors of one PromQL expression, each with what encloses it."""

    def __init__(self, text):
        self.tokens, at = [], 0
        while at < len(text):
            match = TOKEN.match(text, at)
            if match is None:
                raise ValueError(f"{text[at:at + 20]!r}")
            if match.lastgroup != "space":
                self.tokens.append((match.lastgroup, match.group()))
            at = match.end()
        self.at = 0
        self.selectors = []
        self.expression(())
        if self.at != len(self.tokens):
            raise ValueError(f"{self.tokens[self.at][1]!r}")

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else (None, None)

    def take(self, value=None):
        token = self.peek()
        if token[0] is None or (value is not None and token[1] != value):
            raise ValueError(f"{token[1]!r} where {value or 'more'} was expected")
        self.at += 1
        return token

    def expression(self, enclosing):
        self.unary(enclosing)
        while self.peek()[1] in OPERATORS:
            self.take()
            self.unary(enclosing)

    def unary(self, enclosing):
        if self.peek()[1] == "-":
            self.take()
        kind, value = self.take()
        if kind == "number":
            return
        if value == "(":
            self.expression(enclosing)
            self.take(")")
        elif kind == "braces":
            self.selector(None, value, enclosing)
        elif value in AGGREGATIONS:
            self.aggregation(value, enclosing)
        elif value in FUNCTIONS:
            self.take("(")
            self.expression(enclosing + (("function", value),))
            while self.peek()[1] == ",":
                self.take()
                self.expression(enclosing + (("function", value),))
            self.take(")")
        elif kind == "name":
            braces = self.take()[1] if self.peek()[0] == "braces" else None
            self.selector(value, braces, enclosing)
        else:
            raise ValueError(f"{value!r}")

    def grouping(self, aggregation):
        if self.peek()[1] in ("by", "without"):
            if self.take()[1] == "without":
                raise ValueError("`without`, which keeps every label it does not name")
            self.take("(")
            while self.peek()[1] != ")":
                aggregation["by"].add(self.take()[1])
                if self.peek()[1] == ",":
                    self.take()
            self.take(")")

    def aggregation(self, operator, enclosing):
        aggregation = {"operator": operator, "by": set()}
        self.grouping(aggregation)
        self.take("(")
        self.expression(enclosing + (("aggregation", aggregation),))
        self.take(")")
        self.grouping(aggregation)

    def selector(self, metric, braces, enclosing):
        selector = Selector(metric, braces, enclosing)
        if self.peek()[0] == "range":
            selector.range = self.take()[1][1:-1]
            if ":" in selector.range:
                raise ValueError(f"the subquery [{selector.range}]")
        self.selectors.append(selector)


def series_of(name):
    """The family a series name is of, its type, and the labels the series carries."""
    if name in FAMILIES and FAMILIES[name][0] != "histogram":
        return (name, *FAMILIES[name])
    for suffix in ("_bucket", "_sum", "_count"):
        family = name.removesuffix(suffix)
        if family != name and FAMILIES.get(family, ("",))[0] == "histogram":
            labels = FAMILIES[family][1] | ({"le"} if suffix == "_bucket" else set())
            return (family, "counter", labels)
    return None


def names_of(selector, where):
    names = [selector.metric] if selector.metric else []
    for label, operator, value in selector.matchers:
        if label != "__name__":
            continue
        if names or operator not in ("=", "=~") or not re.fullmatch(r"[A-Za-z0-9_:]+(\|[A-Za-z0-9_:]+)*", value):
            refuse(f"{where} names its series by a matcher this check does not read")
        names = value.split("|") if operator == "=~" else [value]
    if not names:
        refuse(f"{where} has a selector that names no series")
    return names


def resolved(selector, where):
    """The series a selector names, each with its family, type and labels, and
    the labels they all carry; refused where one is not the plane's or a
    matcher reads a label they do not all carry."""
    found = []
    for name in names_of(selector, where):
        series = series_of(name)
        if series is None:
            refuse(f"{where} reads {name}, which the plane does not serve")
        found.append((name, *series))
    labels = set.intersection(*(labels for *_, labels in found))
    for label, _, _ in selector.matchers:
        if label != "__name__" and label not in labels:
            refuse(f"{where} matches {label}, which {', '.join(name for name, *_ in found)} does not carry")
    return found, labels


def held(selector, where):
    """A panel's selector, resolved and narrowed by every variable that can narrow it."""
    found, labels = resolved(selector, where)
    present = {label: operator + json.dumps(value) for label, operator, value in selector.matchers}
    owned = any("owner" in carried for *_, carried in found)
    required = NARROWED | (OWNED if owned else {})
    for label, matcher in required.items():
        if present.get(label) != matcher:
            refuse(f"{where} does not match {label}{matcher}, so the page's {label} does not narrow it")
    return found, labels


def panel_selector(selector, where, window):
    found, labels = held(selector, where)
    aggregations = [inner for kind, inner in selector.enclosing if kind == "aggregation"]
    functions = [inner for kind, inner in selector.enclosing if kind == "function"]
    if not aggregations:
        refuse(f"{where} reaches the panel unsummed: a series per combination of its family's labels")
    for aggregation in aggregations:
        strange = aggregation["by"] - labels
        if strange:
            refuse(f"{where} groups by {sorted(strange)}, which its series do not carry")
    windowed = [name for name in functions if name in ("increase", "rate")]
    if bool(windowed) != (selector.range is not None):
        refuse(f"{where} has a range only where increase or rate reads it")
    if selector.range is not None and selector.range != window:
        refuse(f"{where} reads [{selector.range}], and its kind of panel reads [{window}]")
    for name, _, kind, _ in found:
        if windowed and kind == "gauge":
            refuse(f"{where} takes {windowed[0]} of {name}, which is a gauge")
        if name.endswith("_bucket"):
            quantile = [at for at, step in enumerate(selector.enclosing) if step == ("function", "histogram_quantile")]
            between = [inner for kind, inner in selector.enclosing[quantile[-1] + 1:] if kind == "aggregation"] if quantile else []
            if not between or any("le" not in aggregation["by"] for aggregation in between):
                refuse(f"{where} sums {name} other than by le into histogram_quantile")
        elif "histogram_quantile" in functions:
            refuse(f"{where} reads histogram_quantile of {name}, which is not a bucket series")


def parsed(text, where):
    try:
        return Expression(text)
    except ValueError as error:
        refuse(f"{where} is a query this check does not read: {error}")


def variables_named(text):
    return {next(name for name in match.groups() if name) for match in VARIABLE.finditer(text)}


def panels_of(holder):
    """Every panel, those inside a collapsed row among them."""
    for panel in holder.get("panels") or []:
        yield panel
        yield from panels_of(panel)


def dashboard_of(documents):
    found = [
        document
        for document in documents
        if document.get("kind") == "ConfigMap"
        and document["metadata"]["name"] == DASHBOARD
        and document["metadata"].get("namespace") == NAMESPACE
    ]
    if len(found) != 1:
        refuse(f"expected one ConfigMap {NAMESPACE}/{DASHBOARD}, found {len(found)}")
    config = found[0]
    label, value = SIDECAR
    if (config["metadata"].get("labels") or {}).get(label) != value:
        refuse(f"{DASHBOARD} lacks the label {label}={value}, so the sidecar does not deliver it")
    if len(config.get("data") or {}) != 1:
        refuse(f"{DASHBOARD} holds {len(config.get('data') or {})} documents; one dashboard is one document")
    (text,) = config["data"].values()
    try:
        dashboard = json.loads(text)
    except json.JSONDecodeError as error:
        refuse(f"{DASHBOARD} is not JSON: {error}")
    if dashboard.get("uid") != UID:
        refuse(f"the dashboard's uid is {dashboard.get('uid')!r}, and links are written to {UID!r}")
    return dashboard


def custom_values(query):
    """A custom variable's values, as Grafana splits them: on unescaped commas, then `text : value`."""
    return [entry.split(" : ", 1)[-1].strip() for entry in re.findall(r"(?:\\,|[^,])+", query)]


def main():
    documents = [document for document in yaml.safe_load_all(Path(sys.argv[1]).read_text()) if document]
    dashboard = dashboard_of(documents)
    variables = {variable["name"]: variable for variable in (dashboard.get("templating") or {}).get("list") or []}
    queries = []
    for panel in panels_of(dashboard):
        if panel.get("targets") and panel.get("type") not in PANELS:
            refuse(f"panel {panel.get('title')!r} is a {panel.get('type')}, a kind of panel this check does not read")
        instant, window = PANELS.get(panel.get("type"), (None, None))
        for target in panel.get("targets") or []:
            where = f"panel {panel.get('title')!r} query {target.get('refId')}"
            if (target.get("instant") is True, target.get("range") is True) != (instant, not instant):
                refuse(f"{where} is not {'an instant' if instant else 'a range'} query, as its {panel['type']} reads")
            for holder in (panel, target):
                uid = (holder.get("datasource") or {}).get("uid")
                if uid != DATASOURCE:
                    refuse(f"{where} reads datasource {uid!r}, and the chart's Prometheus is {DATASOURCE!r}")
            if not target.get("expr"):
                refuse(f"{where} has no expression")
            queries.append((where, target["expr"]))
            for selector in parsed(target["expr"], where).selectors:
                panel_selector(selector, where, window)
    if not queries:
        refuse("the dashboard queries nothing")
    for name, variable in variables.items():
        where = f"variable {name!r}"
        if variable.get("type") != "query":
            continue
        if (variable.get("datasource") or {}).get("uid") != DATASOURCE:
            refuse(f"{where} reads datasource {(variable.get('datasource') or {}).get('uid')!r}")
        text = variable["query"] if isinstance(variable["query"], str) else variable["query"].get("query", "")
        match = LABEL_VALUES.match(text.strip())
        if match is None:
            refuse(f"{where} is a query this check does not read: {text!r}")
        queries.append((where, text))
        selectors = parsed(match[1], where).selectors
        if len(selectors) != 1:
            refuse(f"{where} reads {len(selectors)} selectors where label_values reads one")
        _, labels = resolved(selectors[0], where)
        if match[2] not in labels:
            refuse(f"{where} reads the values of {match[2]}, which its series do not carry")
    for where, text in queries:
        unknown = variables_named(text) - set(variables) - BUILT_IN
        if unknown:
            refuse(f"{where} names {sorted(unknown)}, which the page does not define")
    owner = variables.get("owner") or {}
    if owner.get("type") != "custom" or ME not in custom_values(owner.get("query") or ""):
        refuse(f"the owner variable is not a custom one with {ME} among its values, so the page has no Me")


main()
