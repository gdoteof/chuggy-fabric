#!/usr/bin/env python3
"""Run the `report` step as its pod is given it, against an API that is this
suite's own.

usage: release-report.py RENDERED_BUILD_SYSTEM BUSYBOX_BIN WORK

WHAT IS RENDERED AND WHAT IS THIS SUITE'S. The script is the bytes of the
ConfigMap the rendered step mounts, run by that step's own `command` under a
BusyBox shell, which is what the step's image has. Its environment is the
step's and nothing else, with each parameter resolved as the rendered Pipeline
passes it to its `finally` task: a task's status is the case's, the run's name
and the commit this suite's, and a path of the pod's is put under the case's
own directory. The bearer is a file where the rendered Secret volume puts its
key, when the case has a Secret. A reference this does not know how to resolve
is refused rather than skipped.

`curl` is the real one, so its retries, its limits and what it prints of a
failure are its own. It is reached through a stand-in that adds two arguments
after the script's: where the address is answered, and whose certificate is
trusted there. That is this suite's API, a server on the loopback that answers
under the name the Pipeline posts to and keeps every request. Every program
the script runs goes through a stand-in that keeps its arguments and its
environment, and BusyBox's own are otherwise untouched.

WHAT IS HELD OF EVERY CASE. The step ends 0. The bearer is in nothing the
step printed and in no argument or environment of anything it ran. Each
request is a POST to the action's address, carrying the bearer as chuggy reads
one and a body chuggy's report document admits, whose rules are restated below
from kasofsk/chuggy's `actionReportDocumentSchema`. And the step took no more
than half of what bounds its task, the other half being the pod's to start
in: the case in which nothing answers is the one that comes nearest.

THE CASES, and what each is the only reader of.

- every task `Succeeded`, one `Failed` beside one that never started, none
  that ended, and a status Tekton does not write: the two outcomes that are
  reported, each under its own task's name, and that nothing else is;
- no Secret, an empty one, one of blanks and one the step's user cannot read:
  one line each and no request. A bearer written with blanks about it is
  presented without them, which is how chuggy reads its own copy;
- each answer: `Recorded`, `Repeated` and `Ignored` are named, a 200 that says
  none of them is not, and 404 and 422 are final and asked once. One action
  chuggy does not know leaves the others recorded;
- a 503 is asked again and the second answer is the one read; one that never
  clears is asked as often as the script allows and no more; one whose
  `Retry-After` is an hour is not waited for;
- nothing listening, and a server that takes the request and never answers:
  more than one attempt is made, each of the second kind is given up by the
  client, and the next action is still asked about;
- an answer that echoes the bearer back in its body and a header prints none
  of it; a redirect is not followed; an address that is not https is not
  spoken to;
- no `curl` at all, a variable the step is not given, a commit that is no full
  hash, a detail or a link that would end a JSON string, and an action's name
  that would leave its address: a line each, no request or the others', and 0.
"""

import http.server
import json
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import yaml

TASK = "report-actions"
STEP = "report"
PIPELINE = "chuggy-release"
FINALLY = "report"

RUN = "chuggy-release-x7k2p"
COMMIT = "f22d1b8b70070de0cb53dc2b628335b7a069d5f3"
# The length and alphabet modules/chuggy-secrets.nix draws a token in.
BEARER = "9f2c41d07ab35e6618c0d4f7e2b95a3371d8c6e04fa1b25d9367e0c8a4f1d2b6"

# How often a report is asked again is the script's to say: more than once,
# and each action as often as the others.
SEVERAL = "several"

REFERENCE = re.compile(r"\$\(([^)]+)\)")
STATUS = re.compile(r"tasks\.([^.]+)\.status")
DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")
ADDRESS = re.compile(r"/api/v1/tenants/[^/]+/projects/[^/]+/actions/([^/]+)/reports")

# What chuggy reads a report by.
MEDIA_TYPES = ("application/json", "application/vnd.chuggy.v1+json")
PRESENTED = re.compile(r"Bearer ([^ ]+)", re.IGNORECASE)
BLANKS = " \t\r\n"
DOCUMENT_FIELDS = {"version", "commit", "outcome", "observedAt", "detail", "link"}
DOCUMENT_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
DOCUMENT_LINK = re.compile(r"https://[^/\\?#@]+(?:[/?#]|$)")
BODY_BYTES_MAX = 65_536
DETAIL_CHARS_MAX = 1_024
LINK_CHARS_MAX = 2_048

FAILURES = []


def refuse(message):
    raise SystemExit(f"release-report: {message}")


def report(case, message):
    FAILURES.append(case)
    print(f"release-report: {case}: {message}", file=sys.stderr)


def objects(text):
    return [document for document in yaml.safe_load_all(text) if document]


def one(documents, kind, name):
    found = [
        document
        for document in documents
        if document["kind"] == kind and document["metadata"]["name"] == name
    ]
    if len(found) != 1:
        refuse(f"the render holds {len(found)} {kind} {name}, not one")
    return found[0]


def seconds(duration):
    match = DURATION.fullmatch(duration or "")
    if not match or not any(match.groups()):
        refuse(f"{duration!r} is not a duration this reads")
    hours, minutes, rest = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + rest


def executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def admitted(document):
    """Why chuggy would refuse a report document, or nothing."""
    if not isinstance(document, dict) or not set(document) <= DOCUMENT_FIELDS:
        return "it is not an object of the document's fields alone"
    if document.get("version") != 1 or isinstance(document.get("version"), bool):
        return "its version is not 1"
    if not isinstance(document.get("commit"), str) or not DOCUMENT_COMMIT.fullmatch(document["commit"]):
        return "its commit is not a full hash"
    if document.get("outcome") not in ("Succeeded", "Failed"):
        return "its outcome is not one chuggy reads"
    detail = document.get("detail")
    if detail is not None and (
        not isinstance(detail, str) or not 1 <= len(detail) <= DETAIL_CHARS_MAX or "\0" in detail
    ):
        return "its detail is not bounded text"
    link = document.get("link")
    if link is not None:
        if not isinstance(link, str) or len(link) > LINK_CHARS_MAX or not re.fullmatch(r"[!-~]+", link):
            return "its link is not bounded visible ASCII"
        if not DOCUMENT_LINK.match(link):
            return "its link does not write an https host where every reader finds it"
        parsed = urllib.parse.urlsplit(link)
        if parsed.username or parsed.password:
            return "its link carries a credential"
    if "observedAt" in document:
        return "it states an instant, which this suite does not read the form of"
    return None


class Answer:
    def __init__(self, status, body="", headers=()):
        self.status, self.body, self.headers = status, body, list(headers)


def said(word):
    return Answer(200, json.dumps({"report": word}))


HANG = object()
REFUSED = Answer(404, json.dumps({"error": {"code": "NotFound", "message": "Resource not found."}}))
UNREADABLE = Answer(422, json.dumps({"error": {"code": "ReportRefused", "message": "The report could not be read."}}))


def unavailable(after):
    return Answer(
        503,
        json.dumps({"error": {"code": "ReportUnavailable", "message": "Try again."}}),
        [("Retry-After", str(after))],
    )


class Api:
    """A server on the loopback that keeps each request and answers it as the
    case says. `hold` is how long a request left unanswered is kept open."""

    def __init__(self, hold, certificate=None):
        api = self
        self.requests = []
        self.plan = None
        self.hold = hold

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *arguments):
                pass

            def answer(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                request = {
                    "method": self.command,
                    "path": self.path,
                    "headers": {name.lower(): value for name, value in self.headers.items()},
                    "body": body,
                }
                api.requests.append(request)
                answer = api.plan(request, len(api.requests))
                if answer is HANG:
                    self.connection.settimeout(api.hold)
                    try:
                        while self.connection.recv(1024):
                            pass
                        request["given up by"] = "the client"
                    except socket.timeout:
                        request["given up by"] = "this suite"
                    except OSError:
                        request["given up by"] = "the client"
                    self.close_connection = True
                    return
                sent = answer.body.encode()
                self.send_response(answer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(sent)))
                self.send_header("Connection", "close")
                for name, value in answer.headers:
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(sent)
                self.close_connection = True

            do_GET = do_POST = do_PUT = do_HEAD = answer

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        if certificate is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(*certificate)
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Suite:
    def __init__(self, rendered, busybox, work):
        documents = objects(Path(rendered).read_text())
        self.busybox = Path(busybox)
        self.work = Path(work)
        self.task = one(documents, "Task", TASK)
        steps = self.task["spec"]["steps"]
        if [step["name"] for step in steps] != [STEP]:
            refuse(f"Task {TASK} is not the one step {STEP}")
        self.step = steps[0]
        command = self.step.get("command")
        if not command or command[0] != "/bin/sh" or len(command) != 2:
            refuse(f"Task {TASK} step {STEP} runs {command}, not /bin/sh over one script")
        volumes = {volume["name"]: volume for volume in self.task["spec"]["volumes"]}
        self.mounts = {mount["mountPath"]: volumes[mount["name"]] for mount in self.step["volumeMounts"]}
        directory, _, file = command[1].rpartition("/")
        config = self.mounts.get(directory, {}).get("configMap")
        if config is None:
            refuse(f"{command[1]} is not a file of a ConfigMap the step mounts")
        self.script = one(documents, "ConfigMap", config["name"])["data"].get(file)
        if self.script is None:
            refuse(f"ConfigMap {config['name']} holds no {file}")
        secrets = [(path, volume["secret"]) for path, volume in self.mounts.items() if "secret" in volume]
        if len(secrets) != 1:
            refuse(f"Task {TASK} step {STEP} mounts {len(secrets)} Secrets, not the one it reports with")
        # The files the kubelet writes for the Secret, which holds each key
        # the volume asks it for.
        mounted, secret = secrets[0]
        self.secret_files = [f"{mounted}/{item['path']}" for item in secret.get("items") or []]
        if len(self.secret_files) != 1:
            refuse(f"Task {TASK} takes {len(self.secret_files)} keys of its Secret by name, and this suite writes one")

        pipeline = one(documents, "Pipeline", PIPELINE)
        entries = [entry for entry in pipeline["spec"].get("finally", []) if entry["name"] == FINALLY]
        if len(entries) != 1 or entries[0]["taskRef"] != {"name": TASK}:
            refuse(f"Pipeline {PIPELINE} has no `finally` task {FINALLY} of {TASK}")
        self.passed = {param["name"]: param["value"] for param in entries[0]["params"]}
        self.tasks = [entry["name"] for entry in pipeline["spec"]["tasks"]]
        self.bound = seconds(entries[0].get("timeout"))

        address = urllib.parse.urlsplit(self.passed["actions"])
        self.host, self.base = address.hostname, address.path
        certificate = self.certificate()
        self.api = Api(self.bound, certificate)
        self.plain = Api(self.bound)
        self.longest = 0
        self.programs = self.stand_ins(with_curl=True)
        self.programs_without_curl = self.stand_ins(with_curl=False)

    def certificate(self):
        """A certificate for the name the Pipeline posts to, signed by itself."""
        key, certificate = self.work / "key.pem", self.work / "certificate.pem"
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                "-keyout", str(key), "-out", str(certificate),
                "-subj", f"/CN={self.host}", "-addext", f"subjectAltName=DNS:{self.host}",
            ],
            check=True,
            capture_output=True,
        )
        return certificate, key

    def stand_ins(self, with_curl):
        """BusyBox's programs and `curl`, each keeping what it was run with
        and then running the real one. `curl` is told where its address is
        answered by the file the case writes."""
        directory = self.work / ("programs" if with_curl else "programs-without-curl")
        directory.mkdir()
        kept = str(self.work / "ran.log")
        keep = f"""#!{sys.executable}
import json, os, sys
name = os.path.basename(sys.argv[0])
line = json.dumps({{"program": name, "arguments": sys.argv[1:], "environment": dict(os.environ)}}) + "\\n"
descriptor = os.open({kept!r}, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
os.write(descriptor, line.encode())
os.close(descriptor)
"""
        for program in sorted(self.busybox.iterdir()):
            executable(
                directory / program.name,
                keep + f"os.execv({str(program)!r}, [name, *sys.argv[1:]])\n",
            )
        if with_curl:
            executable(
                directory / "curl",
                keep
                + f"""answered = json.load(open({str(self.work / 'answered.json')!r}))
os.execv({shutil.which('curl')!r}, ["curl", *sys.argv[1:], "--cacert", {str(self.work / 'certificate.pem')!r},
    "--connect-to", f"{self.host}:443:127.0.0.1:{{answered['https']}}",
    "--connect-to", f"{self.host}:80:127.0.0.1:{{answered['http']}}"])
""",
            )
        return directory

    def environment(self, root, statuses, params):
        def of_the_run(match):
            reference = match.group(1)
            status = STATUS.fullmatch(reference)
            if reference == "context.pipelineRun.name":
                return RUN
            if reference == "params.chuggy-commit":
                return COMMIT
            if status and status.group(1) in statuses:
                return statuses[status.group(1)]
            refuse(f"Pipeline {PIPELINE} passes `report` $({reference}), which this suite does not stand in for")

        passed = {name: REFERENCE.sub(of_the_run, value) for name, value in self.passed.items()}
        passed.update(params)

        def of_the_task(match):
            kind, _, rest = match.group(1).partition(".")
            if kind == "params" and rest in passed:
                return passed[rest]
            refuse(f"Task {TASK} step {STEP} reads $({match.group(1)}), which this suite does not stand in for")

        environment = {}
        for entry in self.step["env"]:
            if set(entry) != {"name", "value"}:
                refuse(f"Task {TASK} step {STEP} takes {entry['name']} from a source this suite does not stand in for")
            value = REFERENCE.sub(of_the_task, entry["value"])
            environment[entry["name"]] = str(root / value.lstrip("/")) if value.startswith("/") else value
        return environment

    def case(
        self,
        name,
        statuses,
        printed,
        plan=None,
        asked=(),
        bearer=BEARER,
        mode=None,
        listening=True,
        params=None,
        without=(),
        curl=True,
        attempts=1,
        also=None,
    ):
        """One run of the step. `statuses` is how each task ended, `plan` what
        the API answers, `printed` each line the step says of itself, with
        `{bearer}` where it names the bearer's file, `asked` each report as
        the action and the outcome, and `attempts` how often each is sent."""
        case = self.work / name
        root = case / "root"
        for mounted in self.mounts:
            (root / mounted.lstrip("/")).mkdir(parents=True)
        if bearer is not None:
            for file in self.secret_files:
                written = root / file.lstrip("/")
                written.write_text(bearer)
                if mode is not None:
                    written.chmod(mode)
        (case / "script").write_text(self.script)
        environment = self.environment(root, {task: "None" for task in self.tasks} | statuses, params or {})
        mentioned = [value for entry, value in environment.items() if entry == "BEARER"]
        for entry in without:
            del environment[entry]
        environment["PATH"] = str(self.programs if curl else self.programs_without_curl)

        ran = self.work / "ran.log"
        ran.write_text("")
        for api in (self.api, self.plain):
            api.requests.clear()
            api.plan = plan
        (self.work / "answered.json").write_text(
            json.dumps({"https": self.api.port if listening else unused_port(), "http": self.plain.port})
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [str(self.busybox / "sh"), str(case / "script")],
                env=environment,
                cwd=case,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.bound,
            )
        except subprocess.TimeoutExpired:
            return report(name, f"the step had not ended after the {self.bound}s that bound its task")
        took = time.monotonic() - started
        self.longest = max(self.longest, took)

        if completed.returncode != 0:
            report(name, f"the step ended {completed.returncode}: {completed.stderr}")
        if took * 2 > self.bound:
            report(name, f"the step took {took:.0f}s, more than half of the {self.bound}s that bound its task")
        expected = [line.format(bearer=mentioned[0] if mentioned else "") for line in printed]
        if completed.stdout.splitlines() != expected:
            report(name, f"the step printed {completed.stdout.splitlines()}, not {expected}")

        ran = [json.loads(line) for line in ran.read_text().splitlines()]
        secret = (bearer or "").strip(BLANKS)
        if secret:
            for where, text in (
                ("what the step printed", completed.stdout),
                ("what the step printed as an error", completed.stderr),
                ("an argument or the environment of a program the step ran", json.dumps(ran)),
            ):
                if secret in text:
                    report(name, f"the bearer is in {where}")

        if self.plain.requests:
            report(name, f"{len(self.plain.requests)} requests were made in the clear")
        requests = list(self.api.requests)
        # A request this suite kept is one `curl` made, so one its stand-in
        # kept the arguments of: a stand-in that keeps nothing holds nothing.
        if requests and "curl" not in [program["program"] for program in ran]:
            report(name, "the API was asked and no `curl` was kept as run")
        sent = []
        for request in requests:
            action = self.action_of(request)
            if sent and sent[-1][0] == action:
                sent[-1][1].append(request)
            else:
                sent.append((action, [request]))
        if [action for action, _ in sent] != [action for action, _ in asked]:
            return report(name, f"the API was asked about {[action for action, _ in sent]}, not {[action for action, _ in asked]}")
        counts = [len(requests) for _, requests in sent]
        if attempts == SEVERAL and (len(set(counts)) > 1 or min(counts, default=2) < 2):
            report(name, f"the reports were sent {counts} times, not each more than once and as often as the others")
        if isinstance(attempts, int) and set(counts) - {attempts}:
            report(name, f"the reports were sent {counts} times, not each {attempts}")
        for (_, requests), (_, outcome) in zip(sent, asked):
            for request in requests:
                self.is_a_report(name, request, outcome)
        if also is not None:
            also(name, requests, completed)
        return None

    def action_of(self, request):
        path = request["path"]
        match = ADDRESS.fullmatch(path)
        return match.group(1) if match and path.startswith(self.base + "/") else path

    def is_a_report(self, name, request, outcome):
        headers = request["headers"]
        if request["method"] != "POST":
            report(name, f"a report was a {request['method']}")
        if headers.get("host") != self.host:
            report(name, f"a report was sent to the host {headers.get('host')}")
        if headers.get("content-type") not in MEDIA_TYPES:
            report(name, f"a report's body was called {headers.get('content-type')}, which chuggy does not read")
        match = PRESENTED.fullmatch(headers.get("authorization", ""))
        if not match or match.group(1) != BEARER:
            report(name, "a report did not present the bearer as chuggy reads one")
        if len(request["body"]) > BODY_BYTES_MAX:
            report(name, f"a report's body is {len(request['body'])} bytes")
        try:
            document = json.loads(request["body"].decode("utf-8"))
        except ValueError as error:
            return report(name, f"a report's body is not JSON: {error}")
        refused = admitted(document)
        if refused:
            report(name, f"chuggy refuses a report: {refused}: {document}")
        expected = {
            "version": 1,
            "commit": COMMIT,
            "outcome": outcome,
            "detail": RUN,
            "link": self.passed["link"].replace("$(context.pipelineRun.name)", RUN),
        }
        if document != expected:
            report(name, f"a report said {document}, not {expected}")
        return None


def main():
    if len(sys.argv) != 4:
        refuse("usage: release-report.py RENDERED_BUILD_SYSTEM BUSYBOX_BIN WORK")
    suite = Suite(*sys.argv[1:])
    first, second, third = suite.tasks
    ended = {task: "Succeeded" for task in suite.tasks}
    each = [(task, "Succeeded") for task in suite.tasks]

    def always(answer):
        return lambda request, count: answer

    def lines(what):
        return [f"report: {task} Succeeded: {what}" for task in suite.tasks]

    # How each task ended.
    suite.case("every-task-succeeded", ended, lines("Recorded"), always(said("Recorded")), each)
    suite.case(
        "one-failed-and-one-never-started",
        {first: "Failed", second: "Succeeded", third: "None"},
        [
            f"report: {first} Failed: Recorded",
            f"report: {second} Succeeded: Recorded",
            f"report: {third} None: not a task that ended, so not reported",
        ],
        always(said("Recorded")),
        [(first, "Failed"), (second, "Succeeded")],
    )
    suite.case(
        "none-ended",
        {},
        [f"report: {task} None: not a task that ended, so not reported" for task in suite.tasks],
        always(said("Recorded")),
    )
    suite.case(
        "a-status-tekton-does-not-write",
        {first: "Cancelled", second: "succeeded", third: ""},
        [
            f"report: {first} Cancelled: not a task that ended, so not reported",
            f"report: {second} succeeded: not a task that ended, so not reported",
            f"report: {third} : not a task that ended, so not reported",
        ],
        always(said("Recorded")),
    )

    # The Secret.
    nobody = always(said("Recorded"))
    suite.case("no-secret", ended, ["report: no bearer is mounted at {bearer}, so nothing is reported"], nobody, bearer=None)
    suite.case("empty-secret", ended, ["report: the bearer at {bearer} is empty, so nothing is reported"], nobody, bearer="")
    suite.case("secret-of-blanks", ended, ["report: the bearer at {bearer} is empty, so nothing is reported"], nobody, bearer=" \t\r\n")
    suite.case(
        "secret-the-user-cannot-read",
        ended,
        ["report: the bearer at {bearer} is not this user's to read, so nothing is reported"],
        nobody,
        mode=0,
    )
    suite.case("bearer-written-with-blanks", ended, lines("Recorded"), nobody, each, bearer=f" \t{BEARER}\r\n")

    # Each answer.
    suite.case("repeated", ended, lines("Repeated"), always(said("Repeated")), each)
    suite.case("ignored", ended, lines("Ignored"), always(said("Ignored")), each)
    suite.case(
        "a-200-that-says-none-of-them",
        ended,
        lines("200, with an answer this does not know"),
        always(Answer(200, "<html>Recorded</html>")),
        each,
    )
    suite.case("a-200-that-says-nothing", ended, lines("200, with an answer this does not know"), always(Answer(200)), each)
    suite.case("not-found", ended, lines("404, not recorded"), always(REFUSED), each)
    suite.case("refused-as-unreadable", ended, lines("422, not recorded"), always(UNREADABLE), each)

    def once_unavailable():
        seen = set()

        def plan(request, count):
            if request["path"] in seen:
                return said("Recorded")
            seen.add(request["path"])
            return unavailable(1)

        return plan

    suite.case("unavailable-and-then-recorded", ended, lines("Recorded"), once_unavailable(), each, attempts=2)

    suite.case("unavailable-every-time", ended, lines("503, not recorded"), always(unavailable(1)), each, attempts=SEVERAL)
    suite.case("unavailable-for-an-hour", ended, lines("503, not recorded"), always(unavailable(3600)), each)

    # Nothing there, and nothing said.
    def tried_again(name, requests, completed):
        refused = completed.stderr.count("curl: (7)")
        if refused < 2 * len(suite.tasks):
            report(name, f"curl said {refused} times that it was refused, which is not each report tried again")

    suite.case("nothing-listening", ended, lines("not delivered, curl ended 7"), listening=False, also=tried_again)

    def given_up_by_the_client(name, requests, completed):
        kept = [request.get("given up by") for request in requests]
        if set(kept) != {"the client"}:
            report(name, f"the requests left unanswered were given up by {kept}")

    suite.case(
        "nothing-answers",
        ended,
        lines("not delivered, curl ended 28"),
        always(HANG),
        each,
        attempts=SEVERAL,
        also=given_up_by_the_client,
    )

    def one_is_unknown(request, count):
        return REFUSED if suite.action_of(request) == first else said("Recorded")

    suite.case(
        "one-not-found-and-the-rest-recorded",
        ended,
        [f"report: {first} Succeeded: 404, not recorded", *lines("Recorded")[1:]],
        one_is_unknown,
        each,
    )

    # What an answer may not do.
    def echo(status):
        def plan(request, count):
            presented = request["headers"].get("authorization", "")
            return Answer(status, json.dumps({"report": "Recorded", "presented": presented}), [("X-Presented", presented)])

        return plan

    suite.case("an-answer-that-echoes-the-bearer", ended, lines("Recorded"), echo(200), each)
    suite.case("a-refusal-that-echoes-the-bearer", ended, lines("404, not recorded"), echo(404), each)
    elsewhere = Answer(302, "", [("Location", f"https://{suite.host}/elsewhere")])
    suite.case("a-redirect", ended, lines("302, not recorded"), always(elsewhere), each)
    in_the_clear = suite.passed["actions"].replace("https://", "http://", 1)
    suite.case(
        "an-address-that-is-not-https",
        ended,
        lines("not delivered, curl ended 1"),
        always(said("Recorded")),
        params={"actions": in_the_clear},
    )

    # What the step is given.
    suite.case("no-curl", ended, lines("not delivered, curl ended 127"), always(said("Recorded")), curl=False)

    def names_what_is_missing(name, requests, completed):
        if "COMMIT" not in completed.stderr:
            report(name, f"the step did not say which variable it lacks: {completed.stderr!r}")

    suite.case("a-variable-not-given", ended, [], always(said("Recorded")), without=("COMMIT",), also=names_what_is_missing)
    suite.case(
        "a-commit-that-is-short",
        ended,
        [f"report: {COMMIT[:12]} is not a full commit hash, so nothing is reported"],
        always(said("Recorded")),
        params={"commit": COMMIT[:12]},
    )
    suite.case(
        "a-commit-that-is-no-hash",
        ended,
        ["report: main is not a commit hash, so nothing is reported"],
        always(said("Recorded")),
        params={"commit": "main"},
    )
    suite.case(
        "a-detail-that-ends-its-string",
        ended,
        ["report: the detail is not a run's name, so nothing is reported"],
        always(said("Recorded")),
        params={"detail": RUN + '","outcome":"Failed'},
    )
    suite.case(
        "a-link-that-ends-its-string",
        ended,
        ["report: an address holds a character that is not an address's, so nothing is reported"],
        always(said("Recorded")),
        params={"link": suite.passed["link"] + '"'},
    )
    unnamed = "report: an action's name is not one chuggy admits, so it is not reported"
    suite.case(
        "an-action-that-leaves-its-address",
        ended,
        [unnamed, unnamed, unnamed, f"report: {third} Succeeded: Recorded"],
        always(said("Recorded")),
        [(third, "Succeeded")],
        params={"statuses": f"../../tenants Succeeded\n.. Succeeded\n{first}?x Succeeded\n\n{third} Succeeded\n"},
    )

    if FAILURES:
        raise SystemExit(f"release-report: {len(FAILURES)} failed: {', '.join(dict.fromkeys(FAILURES))}")
    print(f"release-report: every case passed, the longest in {suite.longest:.0f}s of the {suite.bound}s that bound the task")


if __name__ == "__main__":
    main()
