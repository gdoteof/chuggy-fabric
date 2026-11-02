"""What the dashboards written here are built from: Grafana's JSON for a panel,
a query and a variable, and the ConfigMap Grafana's dashboard sidecar loads
one from.

Each dashboard is a module beside this one that writes its manifest whole, the
comment above the ConfigMap included, and its test holds the manifest under
`cluster/apps/` to exactly what the module writes:

    python3 dashboards/<name>.py > cluster/apps/<name>-dashboard.yaml
"""

import json

# The chart's own Prometheus, which every query here reads.
DS = {"type": "prometheus", "uid": "prometheus"}
# What Grafana fills with the signed-in person's login.
ME = "${__user.login}"


def target(ref, expr, legend=None, instant=False, table=False):
    found = {"refId": ref, "datasource": DS, "expr": expr}
    if legend is not None:
        found["legendFormat"] = legend
    if instant:
        found["instant"] = True
        found["range"] = False
    else:
        found["range"] = True
    if table:
        found["format"] = "table"
    return found


def colours(pairs):
    return [
        {
            "matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": colour}}],
        }
        for name, colour in pairs
    ]


def query_variable(name, label, query, description):
    return {
        "name": name,
        "label": label,
        "description": description,
        "type": "query",
        "datasource": DS,
        "query": query,
        "definition": query,
        "refresh": 2,
        "sort": 1,
        "multi": True,
        "includeAll": True,
        "allValue": ".*",
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
        "options": [],
    }


def who(description, choices, chosen):
    """The owner variable: each choice a name and the regex `owner` is matched by."""
    options = [{"selected": text == chosen, "text": text, "value": value} for text, value in choices]
    (current,) = [option for option in options if option["selected"]]
    return {
        "name": "owner",
        "label": "Who",
        "description": description,
        "type": "custom",
        "query": ",".join(f"{text} : {value}" for text, value in choices),
        "multi": False,
        "includeAll": False,
        "current": dict(current),
        "options": options,
    }


def dashboard(uid, title, description, time_from, refresh, variables, panels, links=()):
    found = {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": ["chuggy"],
        "schemaVersion": 39,
        "version": 1,
        "editable": False,
        "graphTooltip": 1,
        "timezone": "browser",
        "time": {"from": time_from, "to": "now"},
        "refresh": refresh,
        "templating": {"list": variables},
        "panels": panels,
    }
    if links:
        found["links"] = list(links)
    return found


def link(title, url, tooltip):
    """A link in the page's header to an address outside Grafana, opened in a new tab."""
    return {
        "title": title,
        "type": "link",
        "url": url,
        "tooltip": tooltip,
        "icon": "external link",
        "targetBlank": True,
        "asDropdown": False,
        "includeVars": False,
        "keepTime": False,
        "tags": [],
    }


def manifest(header, name, key, board):
    """The ConfigMap the sidecar delivers `board` from, under `header`."""
    lines = [header.rstrip("\n")] + [
        "apiVersion: v1",
        "kind: ConfigMap",
        "metadata:",
        f"  name: {name}",
        "  namespace: monitoring",
        "  labels:",
        '    grafana_dashboard: "1"',
        "data:",
        f"  {key}: |-",
    ]
    lines += ["    " + line for line in json.dumps(board, indent=2).split("\n")]
    return "\n".join(lines) + "\n"


def nothing(none):
    """What a panel reads where a query has no value, or one Prometheus gives as NaN."""
    return {"noValue": none, "mappings": [{"type": "special", "options": {"match": "nan", "result": {"text": none, "index": 0}}}]}


def grid(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


class Board:
    """A dashboard's panels, numbered in the order they are added."""

    def __init__(self):
        self.panels = []
        self.next_id = 1

    def add(self, panel):
        self.panels.append({"id": self.next_id, **panel})
        self.next_id += 1

    def row(self, title, y):
        self.add({
            "type": "row",
            "title": title,
            "collapsed": False,
            "gridPos": grid(0, y, 24, 1),
            "panels": [],
        })

    def stat(self, title, description, targets, x, y, w, h, unit, decimals=None, thresholds=None, none=None):
        """A value for each query, which reads 0 where it has none, or `none` where given."""
        defaults = {
            "unit": unit,
            "noValue": "0",
            "color": {"mode": "thresholds"},
            "thresholds": {
                "mode": "absolute",
                "steps": thresholds or [{"color": "text", "value": None}],
            },
        }
        if decimals is not None:
            defaults["decimals"] = decimals
        if none is not None:
            defaults |= nothing(none)
        self.add({
            "type": "stat",
            "title": title,
            "description": description,
            "datasource": DS,
            "gridPos": grid(x, y, w, h),
            "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "colorMode": "value",
                "graphMode": "none",
                "textMode": "auto",
                "justifyMode": "auto",
                "orientation": "auto",
                "wideLayout": True,
            },
        })

    def bars(self, title, description, targets, x, y, w, h, unit, interval, decimals=None, overrides=(), points=None):
        """Stacked bars, each what its counters rose by over one step, the legend totalling them."""
        defaults = {
            "unit": unit,
            "min": 0,
            "color": {"mode": "palette-classic"},
            "custom": {
                "drawStyle": "bars",
                "fillOpacity": 80,
                "lineWidth": 1,
                "showPoints": "never",
                "stacking": {"mode": "normal", "group": "A"},
            },
        }
        if decimals is not None:
            defaults["decimals"] = decimals
        panel = {
            "type": "timeseries",
            "title": title,
            "description": description,
            "datasource": DS,
            "interval": interval,
        }
        if points is not None:
            panel["maxDataPoints"] = points
        panel |= {
            "gridPos": grid(x, y, w, h),
            "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": list(overrides)},
            "options": {
                "legend": {
                    "displayMode": "table",
                    "placement": "right",
                    "showLegend": True,
                    "calcs": ["sum"],
                    "sortBy": "Total",
                    "sortDesc": True,
                },
                "tooltip": {"mode": "multi", "sort": "desc"},
            },
        }
        self.add(panel)

    def lines(self, title, description, targets, x, y, w, h, unit, decimals=None, overrides=(), interval=None, most=None):
        """A line for each series, the legend giving each one's latest value; `interval`,
        where given, is the least step, and a point is drawn where steps are few; `most`,
        where given, is the top of the axis."""
        defaults = {
            "unit": unit,
            "min": 0,
            "color": {"mode": "palette-classic"},
            "custom": {
                "drawStyle": "line",
                "lineWidth": 1,
                "fillOpacity": 0,
                "showPoints": "never" if interval is None else "auto",
                "spanNulls": False,
            },
        }
        if decimals is not None:
            defaults["decimals"] = decimals
        if most is not None:
            defaults["max"] = most
        panel = {
            "type": "timeseries",
            "title": title,
            "description": description,
            "datasource": DS,
        }
        if interval is not None:
            panel["interval"] = interval
        self.add(panel | {
            "gridPos": grid(x, y, w, h),
            "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": list(overrides)},
            "options": {
                "legend": {
                    "displayMode": "table",
                    "placement": "right",
                    "showLegend": True,
                    "calcs": ["lastNotNull"],
                },
                "tooltip": {"mode": "multi", "sort": "desc"},
            },
        })

    def bargauge(self, title, description, targets, x, y, w, h, unit, overrides=(), none=None, tallest=None, most=None, named=False):
        """A bar for each series; `none`, where given, is what a series of no value reads,
        `tallest` the most pixels a bar is drawn, which keeps a few bars' names their size,
        `most`, where given, the value a full bar is, and `named` keeps a bar's name when it
        is the only one, which Grafana otherwise leaves to the panel's title."""
        defaults = {
            "unit": unit,
            "min": 0,
            "color": {"mode": "palette-classic"},
            "thresholds": {"mode": "absolute", "steps": [{"color": "text", "value": None}]},
        }
        if most is not None:
            defaults["max"] = most
        if named:
            defaults["displayName"] = "${__series.name}"
        if none is not None:
            defaults |= nothing(none)
        self.add({
            "type": "bargauge",
            "title": title,
            "description": description,
            "datasource": DS,
            "gridPos": grid(x, y, w, h),
            "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": list(overrides)},
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "orientation": "horizontal",
                "displayMode": "basic",
                "valueMode": "color",
                "showUnfilled": True,
                "namePlacement": "left",
                **({"sizing": "auto"} if tallest is None else {"sizing": "manual", "minVizHeight": 16, "maxVizHeight": tallest}),
            },
        })

    def table(self, title, description, targets, x, y, w, h, columns, hidden, overrides=()):
        """One row a series, the frames of every query merged on the labels they share.

        `columns` names each field shown, in order, by what it is called; `hidden`
        names the fields left out.
        """
        self.add({
            "type": "table",
            "title": title,
            "description": description,
            "datasource": DS,
            "gridPos": grid(x, y, w, h),
            "targets": targets,
            "transformations": [
                {"id": "merge", "options": {}},
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {name: True for name in hidden},
                        "indexByName": {field: at for at, (field, _) in enumerate(columns)},
                        "renameByName": {field: shown for field, shown in columns if field != shown},
                    },
                },
            ],
            "fieldConfig": {
                "defaults": {"custom": {"align": "auto", "minWidth": 50, "cellOptions": {"type": "auto"}}},
                "overrides": list(overrides),
            },
            "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
        })
