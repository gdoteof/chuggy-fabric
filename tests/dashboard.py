"""What every chuggy dashboard's check holds it to: that it does not come up
empty, or show more or less than it says, with nothing reporting why. A check
names its dashboard and the families its plane serves, and calls
`held_dashboard`.

- A manifest other than what its writer in `dashboards/` writes was edited by
  hand, and the next write undoes the edit.
- A dashboard the sidecar does not deliver, a document Grafana cannot parse, a
  uid other than the one links are written to, and a query naming a datasource
  other than the chart's Prometheus are each an empty page or a page at
  another address.
- A selector naming a series the plane does not serve draws "No data". Each
  check copies its plane's families and their labels from kasofsk/chuggy; a
  family the plane renames, or a label it drops, is not seen until the copy is
  changed with it.
- A matcher on a label its family does not carry matches nothing once its
  value is narrowed.
- A selector naming a family that carries `tenant`, `project` or `owner`
  without that label's variable matcher is a panel the variables do not
  narrow, and nothing on the page says so.
- A selector no aggregation encloses reaches the panel as scraped, one series
  per combination of its family's labels and of those Prometheus adds. A
  grouping by a label its family does not carry is one series with that label
  empty. `without` keeps every label it does not name, those Prometheus adds
  at the scrape among them, so it is refused rather than read.
- An operator between two vectors pairs the series whose labels are equal, so
  both sides carry the same labels: each side's outermost aggregation groups
  by the same ones, or both are families as scraped with the same labels. A
  side grouped otherwise pairs none of its series, or the wrong ones, and the
  panel reads "No data" or counts what it does not say. A number or `time()`
  on either side pairs with every series, a comparison with one among them.
- A counter, and each series of a histogram, starts again at zero with
  whatever counts it, so it is read only through `increase` or `rate`, which
  take a fall for a restart. Either of a gauge means nothing, and
  `last_over_time` reads a gauge alone. A bucket series any aggregation on its
  way into histogram_quantile sums without `le` leaves it nothing to read.
- A stat, a bar gauge or a table shows one value for the selected time and a
  time series one for each step, so the first three read instant queries and
  any window over `[$__range]`, and the last a range query and any window over
  `[$__interval]`. Either window in the other panel counts a span the panel
  does not say, and either query in it draws the wrong shape. A kind of panel
  not named here is refused rather than read.
- A table shows one frame at a time unless it merges them, and a query it does
  not read as a table is a row a step rather than a row a series, so a table
  reads every query as a table and merges their frames.
- A variable a query names that the page does not define reaches Prometheus as
  text, and Who without `${__user.login}` among its values has no Me.

WHAT THIS CANNOT READ IT REFUSES rather than passes: PromQL beyond the grammar
below -- `without`, `offset`, `@`, a subquery, `on`, `ignoring`, `group_left`,
`group_right`, `bool` -- and a `__name__` matcher other than an alternation of
names.

It does not read what a query means, that the plane is scraped, or that
Grafana fills `${__user.login}` with the login monitoring.yaml names.
"""

import json
import re
from pathlib import Path

import yaml

NAMESPACE = "monitoring"
# The label and value the chart's dashboard sidecar watches for.
SIDECAR = ("grafana_dashboard", "1")
# The datasource the chart provisions for its own Prometheus.
DATASOURCE = "prometheus"
ME = "${__user.login}"
# The variables Grafana defines on every page that a query here may name.
BUILT_IN = {"__range", "__interval", "__rate_interval"}

# What a selector naming a family that carries each label matches it by.
NARROWED = {"tenant": '=~"$tenant"', "project": '=~"$project"', "owner": '=~"$owner"'}

# Each kind of panel: whether its queries are instant, and the window a range reads.
PANELS = {
    "stat": (True, "$__range"),
    "bargauge": (True, "$__range"),
    "table": (True, "$__range"),
    "timeseries": (False, "$__interval"),
}

AGGREGATIONS = {"sum", "min", "max", "avg", "count"}
# What reads a range: of a counter, and of a gauge.
RISING = {"increase", "rate"}
LASTING = {"last_over_time"}
FUNCTIONS = RISING | LASTING | {"histogram_quantile", "time"}
COMPARISONS = {"==", "!=", "<=", ">=", "<", ">"}
OPERATORS = {"+", "-", "*", "/", "or", "and", "unless"} | COMPARISONS
# What changes how an operator pairs the series of its two sides.
MODIFIERS = {"on", "ignoring", "group_left", "group_right", "bool"}
TOKEN = re.compile(
    r"""(?P<space>\s+)
      |(?P<number>\d+(?:\.\d+)?)
      |(?P<name>[A-Za-z_][A-Za-z0-9_:]*)
      |(?P<braces>\{(?:[^{}"]|"(?:[^"\\]|\\.)*")*\})
      |(?P<range>\[[^\[\]]*\])
      |(?P<comparison>==|!=|<=|>=|<|>)
      |(?P<punctuation>[-+*/(),])""",
    re.X,
)
# A side's labels where an Expression is not given its series' labels.
UNREAD = object()
# What Prometheus adds to a series at the scrape, which a family's labels do not list.
SCRAPED = "<added at the scrape>"
MATCHER = re.compile(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*(=~|!~|!=|=)\s*("(?:[^"\\]|\\.)*")\s*(?:,|$)')
VARIABLE = re.compile(r"\$\{([A-Za-z0-9_]+)(?:[.:][^}]*)?\}|\$([A-Za-z0-9_]+)|\[\[([A-Za-z0-9_]+)")
LABEL_VALUES = re.compile(r"^label_values\((.+),\s*([A-Za-z_][A-Za-z0-9_]*)\)$")


class Refused(Exception):
    pass


class Unpaired(Exception):
    """An operator between two vectors whose labels differ."""


def refuse(message):
    raise Refused(message)


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
    """The selectors of one PromQL expression, each with what encloses it.

    Where `labels_of` gives the labels a selector's series carry, each operator
    between two vectors is held to sides of the same labels, and raises
    Unpaired where they differ. A side's labels are a set, or None for a number,
    and `labels` are the whole expression's.
    """

    def __init__(self, text, labels_of=None):
        self.labels_of = labels_of
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
        self.labels = self.expression(())
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
        """Reads an expression, and gives the labels its series carry."""
        labels = self.unary(enclosing)
        while self.peek()[1] in OPERATORS:
            operator = self.take()[1]
            if self.peek()[1] in MODIFIERS:
                raise ValueError(f"`{self.peek()[1]}`, which changes how `{operator}` pairs series")
            labels = paired(operator, labels, self.unary(enclosing))
        return labels

    def unary(self, enclosing):
        if self.peek()[1] == "-":
            self.take()
        kind, value = self.take()
        if kind == "number":
            return None
        if value == "(":
            labels = self.expression(enclosing)
            self.take(")")
            return labels
        if kind == "braces":
            return self.selector(None, value, enclosing)
        if value in AGGREGATIONS:
            return self.aggregation(value, enclosing)
        if value == "time":
            self.take("(")
            self.take(")")
            return None
        if value in FUNCTIONS:
            self.take("(")
            arguments = [self.expression(enclosing + (("function", value),))]
            while self.peek()[1] == ",":
                self.take()
                arguments.append(self.expression(enclosing + (("function", value),)))
            self.take(")")
            labels = arguments[-1]
            return labels - {"le"} if value == "histogram_quantile" and isinstance(labels, frozenset) else labels
        if kind == "name":
            braces = self.take()[1] if self.peek()[0] == "braces" else None
            return self.selector(value, braces, enclosing)
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
        inner = self.expression(enclosing + (("aggregation", aggregation),))
        self.take(")")
        self.grouping(aggregation)
        return UNREAD if inner is UNREAD else frozenset(aggregation["by"])

    def selector(self, metric, braces, enclosing):
        selector = Selector(metric, braces, enclosing)
        if self.peek()[0] == "range":
            selector.range = self.take()[1][1:-1]
            if ":" in selector.range:
                raise ValueError(f"the subquery [{selector.range}]")
        self.selectors.append(selector)
        if self.labels_of is None:
            return UNREAD
        return frozenset(self.labels_of(selector)) | {SCRAPED}


def paired(operator, left, right):
    """The labels of `left operator right`, where both sides' labels let it pair them."""
    if left is None or right is None:
        return right if left is None else left
    if left is UNREAD or right is UNREAD:
        return UNREAD
    if left != right:
        raise Unpaired(
            f"pairs a side by {shown(left)} with one by {shown(right)} at `{operator}`, "
            "and an operator between two vectors pairs only series whose labels are equal"
        )
    return left


def shown(labels):
    return "(" + ", ".join(sorted(labels)) + ")"


class Check:
    """One dashboard's check: its ConfigMap and uid, and its plane's families,
    each name its type and the labels its series carry."""

    def __init__(self, configmap, uid, families):
        self.configmap = configmap
        self.uid = uid
        self.families = families

    def series_of(self, name):
        """The family a series name is of, its type, and the labels the series carries."""
        families = self.families
        if name in families and families[name][0] != "histogram":
            return (name, *families[name])
        for suffix in ("_bucket", "_sum", "_count"):
            family = name.removesuffix(suffix)
            if family != name and families.get(family, ("",))[0] == "histogram":
                labels = families[family][1] | ({"le"} if suffix == "_bucket" else set())
                return (family, "counter", labels)
        return None

    def resolved(self, selector, where):
        """The series a selector names, each with its family, type and labels, and
        the labels they all carry; refused where one is not the plane's or a
        matcher reads a label they do not all carry."""
        found = []
        for name in names_of(selector, where):
            series = self.series_of(name)
            if series is None:
                refuse(f"{where} reads {name}, which the plane does not serve")
            found.append((name, *series))
        labels = set.intersection(*(labels for *_, labels in found))
        for label, _, _ in selector.matchers:
            if label != "__name__" and label not in labels:
                refuse(f"{where} matches {label}, which {', '.join(name for name, *_ in found)} does not carry")
        return found, labels

    def held(self, selector, where):
        """A panel's selector, resolved and narrowed by every variable that can narrow it."""
        found, labels = self.resolved(selector, where)
        present = {label: operator + json.dumps(value) for label, operator, value in selector.matchers}
        for label, matcher in NARROWED.items():
            carried = any(label in labels for *_, labels in found)
            if carried and present.get(label) != matcher:
                refuse(f"{where} does not match {label}{matcher}, so the page's {label} does not narrow it")
        return found, labels

    def panel_selector(self, selector, where, window):
        found, labels = self.held(selector, where)
        aggregations = [inner for kind, inner in selector.enclosing if kind == "aggregation"]
        functions = [inner for kind, inner in selector.enclosing if kind == "function"]
        if not aggregations:
            refuse(f"{where} reaches the panel unsummed: a series per combination of its family's labels")
        for aggregation in aggregations:
            strange = aggregation["by"] - labels
            if strange:
                refuse(f"{where} groups by {sorted(strange)}, which its series do not carry")
        rising = [name for name in functions if name in RISING]
        windowed = [name for name in functions if name in RISING | LASTING]
        if bool(windowed) != (selector.range is not None):
            refuse(f"{where} has a range only where increase, rate or last_over_time reads it")
        if selector.range is not None and selector.range != window:
            refuse(f"{where} reads [{selector.range}], and its kind of panel reads [{window}]")
        for name, _, kind, _ in found:
            if kind == "gauge" and rising:
                refuse(f"{where} takes {rising[0]} of {name}, which is a gauge")
            if kind == "counter" and not rising:
                refuse(f"{where} reads {name}, a counter, other than through increase or rate")
            if name.endswith("_bucket"):
                quantile = [at for at, step in enumerate(selector.enclosing) if step == ("function", "histogram_quantile")]
                between = [inner for kind, inner in selector.enclosing[quantile[-1] + 1:] if kind == "aggregation"] if quantile else []
                if not between or any("le" not in aggregation["by"] for aggregation in between):
                    refuse(f"{where} sums {name} other than by le into histogram_quantile")
            elif "histogram_quantile" in functions:
                refuse(f"{where} reads histogram_quantile of {name}, which is not a bucket series")

    def dashboard_of(self, documents):
        name = self.configmap
        found = [
            document
            for document in documents
            if document.get("kind") == "ConfigMap"
            and document["metadata"]["name"] == name
            and document["metadata"].get("namespace") == NAMESPACE
        ]
        if len(found) != 1:
            refuse(f"expected one ConfigMap {NAMESPACE}/{name}, found {len(found)}")
        config = found[0]
        label, value = SIDECAR
        if (config["metadata"].get("labels") or {}).get(label) != value:
            refuse(f"{name} lacks the label {label}={value}, so the sidecar does not deliver it")
        if len(config.get("data") or {}) != 1:
            refuse(f"{name} holds {len(config.get('data') or {})} documents; one dashboard is one document")
        (text,) = config["data"].values()
        try:
            dashboard = json.loads(text)
        except json.JSONDecodeError as error:
            refuse(f"{name} is not JSON: {error}")
        if dashboard.get("uid") != self.uid:
            refuse(f"the dashboard's uid is {dashboard.get('uid')!r}, and links are written to {self.uid!r}")
        return dashboard

    def held_dashboard(self, documents):
        """The dashboard, every query and variable of it held; refused where one is not."""
        dashboard = self.dashboard_of(documents)
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
                if panel["type"] == "table" and target.get("format") != "table":
                    refuse(f"{where} is not read as a table, so its rows are steps rather than series")
                queries.append((where, target["expr"]))
                labels_of = lambda selector, where=where: self.resolved(selector, where)[1]
                for selector in parsed(target["expr"], where, labels_of).selectors:
                    self.panel_selector(selector, where, window)
            merged = any(step.get("id") == "merge" for step in panel.get("transformations") or [])
            if panel.get("type") == "table" and len(panel.get("targets") or []) > 1 and not merged:
                refuse(f"table {panel.get('title')!r} does not merge its queries' frames, so it shows one of them")
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
            _, labels = self.resolved(selectors[0], where)
            if match[2] not in labels:
                refuse(f"{where} reads the values of {match[2]}, which its series do not carry")
        for where, text in queries:
            unknown = variables_named(text) - set(variables) - BUILT_IN
            if unknown:
                refuse(f"{where} names {sorted(unknown)}, which the page does not define")
        owner = variables.get("owner") or {}
        if owner.get("type") != "custom" or ME not in custom_values(owner.get("query") or ""):
            refuse(f"the owner variable is not a custom one with {ME} among its values, so the page has no Me")
        return dashboard


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


def parsed(text, where, labels_of=None):
    try:
        return Expression(text, labels_of)
    except ValueError as error:
        refuse(f"{where} is a query this check does not read: {error}")
    except Unpaired as error:
        refuse(f"{where} {error}")


def variables_named(text):
    return {next(name for name in match.groups() if name) for match in VARIABLE.finditer(text)}


def panels_of(holder):
    """Every panel, those inside a collapsed row among them."""
    for panel in holder.get("panels") or []:
        yield panel
        yield from panels_of(panel)


def custom_values(query):
    """A custom variable's values, as Grafana splits them: on unescaped commas, then `text : value`."""
    return [entry.split(" : ", 1)[-1].strip() for entry in re.findall(r"(?:\\,|[^,])+", query)]


def custom_current(variable):
    """The value a custom variable's page opens on."""
    return (variable.get("current") or {}).get("value")


def run(name, main):
    """Runs a check, a refusal ending it with its name and why."""
    try:
        main()
    except Refused as refusal:
        raise SystemExit(f"{name}: {refusal}") from None


def documents_of(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def written(source, text, manifest, writer):
    """Refused where the manifest at `source`, which is `manifest` in the tree, is not `text`, what `writer` writes."""
    if Path(source).read_text() != text:
        refuse(f"{manifest} is not what {writer} writes: python3 {writer} > {manifest}")
