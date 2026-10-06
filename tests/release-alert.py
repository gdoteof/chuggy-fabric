#!/usr/bin/env python3
"""Refuse a release trigger that can stop with nothing saying so, or that is
announced as stopped when a person switched it off.

usage: release-alert.py RENDERED_BUILD_SYSTEM RENDERED_APPS WORK

THE RULE IS EVALUATED, NOT READ. promtool runs the rule the `apps` layer
renders over the two series kube-state-metrics exports for a CronJob, labelled
for the trigger as `cluster/build-system` renders it, so a rule about another
object is silent where a case expects it to fire. Each case below is what
those series do over one story of a trigger, a sample a minute, and what the
alert is at the minutes named. Where a case fires, the minute before is held
silent, so the wait is held from both sides.

WHAT IS READ is the one thing evaluating cannot show: the label this
Prometheus selects a rule by. An object without it is loaded by nothing, and
nothing reports that.
"""

import subprocess
import sys
from pathlib import Path

import yaml

NAMESPACE = "monitoring"
RELEASE = "kube-prometheus-stack"
RULE = "release-trigger"
TRIGGER_NAMESPACE = "chuggy-release-trigger"
TRIGGER = "release-trigger"
MINUTES = 40
# A success before any minute of a case.
LONG_AGO = -86400


def refuse(message):
    raise SystemExit(f"release-alert: {message}")


def objects(path):
    return [document for document in yaml.safe_load_all(Path(path).read_text()) if document]


def one(documents, kind, namespace, name):
    found = [
        document
        for document in documents
        if document.get("kind") == kind
        and document["metadata"]["name"] == name
        and document["metadata"].get("namespace") == namespace
    ]
    if len(found) != 1:
        refuse(f"expected one {kind} {namespace}/{name}, found {len(found)}")
    return found[0]


def each_minute(value):
    """What a series holds at each minute of a case; None is no sample."""
    return [value(minute) for minute in range(MINUTES + 1)]


def succeeding(until=MINUTES, again=None, before=None):
    """When the trigger last succeeded, read at each minute: that minute, up
    to `until`, and again from `again` on. `before` is what it read earlier,
    or None for a trigger that had never succeeded."""

    def at(minute):
        if again is not None and minute >= again:
            return minute * 60
        if minute <= until:
            return minute * 60
        return until * 60 if until >= 0 else before

    return each_minute(at)


def suspended(during):
    return each_minute(lambda minute: 1 if minute in during else 0)


ALWAYS = range(MINUTES + 1)
NEVER = range(0)

# name: (whether it is suspended, when it last succeeded, another CronJob's
# two series, {minute: whether the alert fires}).
CASES = {
    "suspended-and-never-ran": (suspended(ALWAYS), None, None, {0: False, 10: False, 30: False}),
    "suspended-since-a-success-long-ago": (
        suspended(ALWAYS),
        each_minute(lambda minute: LONG_AGO),
        None,
        {0: False, 10: False, 30: False},
    ),
    "succeeding-each-minute": (suspended(NEVER), succeeding(), None, {0: False, 10: False, 30: False}),
    "resumed-and-its-first-job-succeeds": (
        suspended(range(10)),
        succeeding(until=-1, before=LONG_AGO, again=12),
        None,
        {9: False, 10: False, 11: False, 12: False, 20: False, 30: False},
    ),
    "resumed-and-nothing-succeeds": (
        suspended(range(10)),
        each_minute(lambda minute: LONG_AGO),
        None,
        {9: False, 14: False, 15: True, 30: True},
    ),
    "never-suspended-and-never-succeeded": (suspended(NEVER), None, None, {4: False, 5: True, 30: True}),
    "some-minutes-fail-and-the-next-succeeds": (
        suspended(NEVER),
        succeeding(until=9, again=18),
        None,
        {minute: False for minute in range(9, 26)},
    ),
    "stops-succeeding": (
        suspended(NEVER),
        succeeding(until=9, again=31),
        None,
        {9: False, 18: False, 19: True, 30: True, 31: False, 35: False},
    ),
    "stops-succeeding-and-is-suspended": (
        suspended(range(25, MINUTES + 1)),
        succeeding(until=9),
        None,
        {18: False, 19: True, 24: True, 25: False, 35: False},
    ),
    "stops-succeeding-while-another-cronjob-succeeds": (
        suspended(NEVER),
        succeeding(until=9),
        (suspended(NEVER), succeeding()),
        {18: False, 19: True, 30: True},
    ),
    "succeeding-while-another-cronjob-does-not": (
        suspended(NEVER),
        succeeding(),
        (suspended(NEVER), None),
        {10: False, 30: False},
    ),
}


def series(name, labels, values):
    selector = ", ".join(f'{label}="{value}"' for label, value in labels.items())
    return {
        "series": f"{name}{{{selector}}}",
        "values": " ".join("_" if value is None else str(value) for value in values),
    }


def main():
    if len(sys.argv) != 4:
        refuse("usage: release-alert.py RENDERED_BUILD_SYSTEM RENDERED_APPS WORK")
    build, apps = (objects(path) for path in sys.argv[1:3])
    work = Path(sys.argv[3])

    one(build, "CronJob", TRIGGER_NAMESPACE, TRIGGER)
    one(apps, "HelmRelease", NAMESPACE, RELEASE)
    rule = one(apps, "PrometheusRule", NAMESPACE, RULE)
    if (rule["metadata"].get("labels") or {}).get("release") != RELEASE:
        refuse(f"PrometheusRule {RULE} lacks the label release={RELEASE}, so Prometheus does not load it")
    alerts = [entry for group in rule["spec"]["groups"] for entry in group["rules"] if "alert" in entry]
    if len(alerts) != 1:
        refuse(f"PrometheusRule {RULE} holds {len(alerts)} alerts, and the cases here are of one")
    (alert,) = alerts

    (work / "rules.yaml").write_text(yaml.safe_dump(rule["spec"]))
    checked = subprocess.run(
        ["promtool", "check", "rules", str(work / "rules.yaml")], capture_output=True, text=True
    )
    if checked.returncode != 0:
        refuse(f"promtool does not take PrometheusRule {RULE}: {checked.stderr.strip() or checked.stdout.strip()}")

    this = {"namespace": TRIGGER_NAMESPACE, "cronjob": TRIGGER}
    other = {"namespace": "another", "cronjob": "another"}
    firing = [
        {
            "exp_labels": {**this, **(alert.get("labels") or {})},
            "exp_annotations": alert.get("annotations") or {},
        }
    ]
    failed = []
    asked = 0
    for name, (suspend, succeeded, another, expected) in CASES.items():
        given = [series("kube_cronjob_spec_suspend", this, suspend)]
        if succeeded is not None:
            given.append(series("kube_cronjob_status_last_successful_time", this, succeeded))
        if another is not None:
            given.append(series("kube_cronjob_spec_suspend", other, another[0]))
            if another[1] is not None:
                given.append(series("kube_cronjob_status_last_successful_time", other, another[1]))
        for minute, fires in expected.items():
            asked += 1
            case = work / f"{name}-{minute}.yaml"
            case.write_text(
                yaml.safe_dump(
                    {
                        "rule_files": ["rules.yaml"],
                        "evaluation_interval": "1m",
                        "tests": [
                            {
                                "interval": "1m",
                                "input_series": given,
                                "alert_rule_test": [
                                    {
                                        "eval_time": f"{minute}m",
                                        "alertname": alert["alert"],
                                        "exp_alerts": firing if fires else [],
                                    }
                                ],
                            }
                        ],
                    }
                )
            )
            ran = subprocess.run(["promtool", "test", "rules", case.name], cwd=work, capture_output=True, text=True)
            if ran.returncode != 0:
                was = "silent, or fires with other labels or annotations" if fires else "firing"
                failed.append(f"{name}: at {minute}m {alert['alert']} is {was}")
                print(f"release-alert: {failed[-1]}")
                print(ran.stdout + ran.stderr)
    if failed:
        refuse(f"{len(failed)} of {asked} failed: {'; '.join(failed)}")


if __name__ == "__main__":
    main()
