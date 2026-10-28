#!/usr/bin/env python3
"""Run cluster/build-system/arm64-builder.sh as an operator does, against
openssl and a docker that is a file, and hold what it makes to the run that
speaks to the daemon.

WHAT IS THE TREE'S AND WHAT IS THIS SUITE'S. The script is the file, run by a
BusyBox shell with BusyBox's tools and the real openssl. `docker` is stood in
for: it keeps what it was called with, and answers `logs` with the line the
daemon prints once it listens and `inspect` with a running container. The run
is worker-image-run.yaml, and the Task is the rendered one.

THE CASES.

certificates:

- a set for the address the run names the daemon by is exactly the CA's
  certificate and the two pairs, each file at mode 0600 in a directory at
  0700; the daemon's is for that address and for serving, the client's for
  being a client, and each is signed by the CA and is no CA itself;
- the CA's key is in none of them, no key there is the one the CA's
  certificate holds, and nothing the run made is left in its temporary
  directory;
- a directory that is there, an address that is not an IPv4 one, and the
  wrong number of arguments are refused, with nothing written;
- a run interrupted by SIGINT, SIGTERM or SIGHUP once the CA's key is made
  fails, and leaves nothing in its temporary directory: the stand-in for
  openssl that signs with the CA's key sends the signal to the script first.

start:

- with a set in place it runs the daemon once, afresh, as docker on the Mac
  is told -- privileged, restarted with docker, its state on a volume, the
  configuration bound read-only -- at the run's port, of the image of the
  same BuildKit version as the Task's client, pinned by digest;
- the configuration it writes listens on that port alone, over TLS, asks a
  client for a certificate from the set's CA, and bounds the collector;
- a missing file of the set, and a key not at 0600, are refused before docker
  is run, and so is a start with no docker to run.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

TASK = "build-two-platform-image"
SCRIPT = "arm64-builder.sh"
ADDRESS = re.compile(r"tcp://(\d{1,3}(?:\.\d{1,3}){3}):(\d+)")
SET = {"ca.crt", "server.crt", "server.key", "client.crt", "client.key"}
# Where `start` reads the set and writes the configuration, under HOME.
CONFIG = Path("Library/Application Support/chuggy-buildkitd")
# Where the daemon's container sees that directory.
MOUNTED = Path("/etc/buildkit")

FAILURES = []


def refuse(message):
    raise SystemExit(f"arm64-builder: {message}")


def report(case, message):
    FAILURES.append(case)
    print(f"arm64-builder: {case}: {message}", file=sys.stderr)


def executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class Suite:
    def __init__(self, script, rendered, run, busybox, openssl, work):
        self.script = Path(script)
        self.busybox = Path(busybox)
        self.openssl = Path(openssl)
        self.work = Path(work)
        manifest = yaml.safe_load(Path(run).read_text())
        if manifest["spec"]["taskRef"]["name"] != TASK:
            refuse(f"{run} is not a run of {TASK}")
        passed = {param["name"]: param["value"] for param in manifest["spec"]["params"]}
        address = ADDRESS.fullmatch(passed.get("arm64-builder", ""))
        if address is None:
            refuse(f"{run} names no daemon as tcp://<address>:<port>")
        self.address, self.port = address.group(1), int(address.group(2))
        (task,) = [
            document
            for document in yaml.safe_load_all(Path(rendered).read_text())
            if document and document["kind"] == "Task" and document["metadata"]["name"] == TASK
        ]
        (build,) = [step for step in task["spec"]["steps"] if step["name"] == "build"]
        self.client = build["image"]

    def openssl_says(self, *arguments):
        return subprocess.run(
            [str(self.openssl / "openssl"), *arguments], check=True, text=True, capture_output=True
        ).stdout

    def case(self, name):
        """A directory for one case, with the temporary directory its run is
        given in it."""
        case = self.work / name
        (case / "tmp").mkdir(parents=True)
        return case

    def sh(self, case, home, *arguments, path=None):
        environment = {
            "PATH": path or f"{self.openssl}:{self.busybox}",
            "HOME": str(home),
            "TMPDIR": str(case / "tmp"),
        }
        completed = subprocess.run(
            [str(self.busybox / "sh"), str(self.script), *arguments],
            env=environment,
            text=True,
            capture_output=True,
            cwd=case,
        )
        return completed

    # certificates

    def made(self, name):
        """A set made for the run's address. Returns its directory."""
        case = self.case(name)
        directory = case / "set"
        completed = self.sh(case, case, "certificates", str(directory), self.address)
        if completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
            return None
        left = sorted(str(path.relative_to(case)) for path in (case / "tmp").rglob("*"))
        if left:
            report(name, f"the set was made and {left} was left beside it")
        return directory

    def certificates(self, name):
        directory = self.made(name)
        if directory is None:
            return
        files = {path.name for path in directory.iterdir()}
        if files != SET:
            report(name, f"the set is {sorted(files)}, not {sorted(SET)}")
            return
        if stat.S_IMODE(directory.stat().st_mode) != 0o700:
            report(name, f"the set's directory is at {oct(stat.S_IMODE(directory.stat().st_mode))}")
        for file in sorted(files):
            mode = stat.S_IMODE((directory / file).stat().st_mode)
            if mode != 0o600:
                report(name, f"{file} is at {oct(mode)}, not 0o600")

        def text(certificate):
            return self.openssl_says("x509", "-in", str(directory / certificate), "-noout", "-text")

        ca = text("ca.crt")
        if not re.search(r"CA:TRUE", ca):
            report(name, "the CA's certificate is not a CA's")
        for certificate, usage in (("server.crt", "TLS Web Server Authentication"), ("client.crt", "TLS Web Client Authentication")):
            body = text(certificate)
            usages = re.search(r"X509v3 Extended Key Usage:.*?\n\s*(.+)\n", body)
            if usages is None or usages.group(1).strip() != usage:
                report(name, f"{certificate} is for {usages and usages.group(1).strip()!r}, not {usage!r} alone")
            if "CA:FALSE" not in body:
                report(name, f"{certificate} is not held to being no CA")
            verified = subprocess.run(
                [str(self.openssl / "openssl"), "verify", "-CAfile", str(directory / "ca.crt"), str(directory / certificate)],
                text=True,
                capture_output=True,
            )
            if verified.returncode != 0:
                report(name, f"{certificate} is not the CA's: {verified.stdout.strip()} {verified.stderr.strip()}")
        names = re.search(r"X509v3 Subject Alternative Name:.*?\n\s*(.+)\n", text("server.crt"))
        if names is None or names.group(1).strip() != f"IP Address:{self.address}":
            report(name, f"the daemon's certificate is for {names and names.group(1).strip()!r}, not the run's {self.address} alone")
        if re.search(r"X509v3 Subject Alternative Name", text("client.crt")):
            report(name, "the client's certificate names an address")

        # No key in the set is the CA's.
        held = self.openssl_says("x509", "-in", str(directory / "ca.crt"), "-noout", "-pubkey")
        for key in ("server.key", "client.key"):
            public = self.openssl_says("pkey", "-in", str(directory / key), "-pubout")
            if public == held:
                report(name, f"{key} is the CA's key")
        for file in files:
            if "PRIVATE KEY" in (directory / file).read_text() and file not in ("server.key", "client.key"):
                report(name, f"{file} holds a key")

    def not_made(self, name, said, arguments, before=None):
        case = self.case(name)
        if before:
            before(case)
        listed = sorted(str(path.relative_to(case)) for path in case.rglob("*"))
        completed = self.sh(case, case, "certificates", *arguments(case))
        if completed.returncode == 0:
            report(name, "made a set, and it is one this must refuse")
        elif said not in completed.stderr:
            report(name, f"was refused without saying `{said}`: {completed.stderr.strip()}")
        after = sorted(str(path.relative_to(case)) for path in case.rglob("*"))
        if after != listed:
            report(name, f"was refused and left {sorted(set(after) - set(listed))}")

    def interrupted(self, name, signal_name):
        case = self.case(name)
        programs = case / "bin"
        programs.mkdir()
        real = str(self.openssl / "openssl")
        executable(
            programs / "openssl",
            f"""#!{sys.executable}
import os, signal, sys
if "-CAkey" in sys.argv:
    os.kill(os.getppid(), signal.{signal_name})
os.execv({real!r}, [{real!r}] + sys.argv[1:])
""",
        )
        completed = self.sh(
            case, case, "certificates", str(case / "set"), self.address, path=f"{programs}:{self.busybox}"
        )
        if completed.returncode == 0:
            report(name, f"made a set through {signal_name}")
        left = sorted(str(path.relative_to(case)) for path in (case / "tmp").rglob("*"))
        if left:
            report(name, f"was interrupted by {signal_name} and left {left}")

    # start

    def docker(self, case):
        programs = case / "bin"
        programs.mkdir()
        executable(
            programs / "docker",
            f"""#!{sys.executable}
import json, sys
argv = sys.argv[1:]
open({str(case / 'docker.log')!r}, "a").write(json.dumps(argv) + "\\n")
if argv[:1] == ["logs"]:
    print("time=x level=info msg=\\"running server on [::]:{self.port}\\"")
elif argv[:1] == ["inspect"]:
    print("true")
""",
        )
        return programs

    def started(self, name, layout=None):
        """`start` with the set in place, as an operator puts it there.
        Returns what docker was told and the configuration, or None."""
        case = self.case(name)
        directory = self.made(name + "-set")
        if directory is None:
            return case, None, None, None
        tls = case / CONFIG / "tls"
        tls.mkdir(parents=True)
        for file in ("ca.crt", "server.crt", "server.key"):
            shutil.copy(directory / file, tls / file)
            (tls / file).chmod(0o600)
        if layout:
            layout(tls)
        programs = self.docker(case)
        completed = self.sh(case, case, "start", path=f"{programs}:{self.busybox}")
        log = case / "docker.log"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return case, completed, calls, case / CONFIG / "buildkitd.toml"

    def starts(self, name):
        case, completed, calls, configuration = self.started(name)
        if completed is None:
            return
        if completed.returncode != 0:
            report(name, f"exited {completed.returncode}: {completed.stderr.strip()}")
            return
        runs = [call for call in calls if call[:1] == ["run"]]
        if len(runs) != 1:
            report(name, f"docker was told to run {runs}, not one daemon")
            return
        run = runs[0]
        before = calls[: calls.index(run)]
        if not before or before[0][:2] != ["rm", "--force"] or before[0][-1] != "chuggy-buildkitd":
            report(name, f"the daemon is not run afresh: docker was told {before} first")
        config = case / CONFIG
        expected = [
            "run", "--detach", "--name", "chuggy-buildkitd", "--restart", "unless-stopped", "--privileged",
            "--publish", f"{self.port}:{self.port}",
            "--mount", "type=volume,source=chuggy-buildkitd,target=/var/lib/buildkit",
            "--mount", f"type=bind,source={config},target={MOUNTED},readonly",
        ]
        if run[:-1] != expected:
            report(name, f"docker was told {run[:-1]}, not {expected}")
        image = run[-1]
        pinned = re.fullmatch(r"moby/buildkit:(v[0-9.]+)@sha256:[0-9a-f]{64}", image)
        client = re.fullmatch(r"moby/buildkit:(v[0-9.]+)-rootless@sha256:[0-9a-f]{64}", self.client)
        if pinned is None or client is None or pinned.group(1) != client.group(1):
            report(name, f"the daemon is {image} and the Task's client {self.client}: not one BuildKit version, each pinned")

        settings = tomllib.loads(configuration.read_text())
        grpc = settings.get("grpc", {})
        if grpc.get("address") != [f"tcp://0.0.0.0:{self.port}"]:
            report(name, f"the daemon listens on {grpc.get('address')}, not the run's port alone")
        expected_tls = {field: str(MOUNTED / "tls" / file) for field, file in (("cert", "server.crt"), ("key", "server.key"), ("ca", "ca.crt"))}
        if grpc.get("tls") != expected_tls:
            report(name, f"the daemon's TLS is {grpc.get('tls')}, not {expected_tls}")
        for field, path in expected_tls.items():
            if not (config / Path(path).relative_to(MOUNTED)).is_file():
                report(name, f"the daemon's {field} is {path}, which is no file of the set it is bound")
        worker = settings.get("worker", {}).get("oci", {})
        bounds = {key: worker.get(key) for key in ("gc", "reservedSpace", "maxUsedSpace", "minFreeSpace")}
        if bounds["gc"] is not True or not all(bounds.values()):
            report(name, f"the collector is {bounds}, not on and bounded")
        if set(settings) != {"grpc", "worker"} or set(settings["worker"]) != {"oci"}:
            report(name, f"the configuration sets {sorted(settings)}, beyond what this holds")

    def not_started_without_docker(self, name):
        case = self.case(name)
        completed = self.sh(case, case, "start", path=str(self.busybox))
        if completed.returncode == 0:
            report(name, "started with no docker to run")
        elif "docker is not on PATH" not in completed.stderr:
            report(name, f"was refused without saying docker is not there: {completed.stderr.strip()}")

    def not_started(self, name, said, layout):
        case, completed, calls, _ = self.started(name, layout)
        if completed is None:
            return
        if completed.returncode == 0:
            report(name, "started the daemon, and it is a start this must refuse")
        elif said not in completed.stderr:
            report(name, f"was refused without saying `{said}`: {completed.stderr.strip()}")
        if calls:
            report(name, f"was refused after docker was told {calls}")


def main():
    if len(sys.argv) != 7:
        refuse("usage: arm64-builder.py SCRIPT RENDERED_BUILD_SYSTEM RUN BUSYBOX_BIN OPENSSL_BIN WORK")
    suite = Suite(*sys.argv[1:])

    suite.certificates("certificates")

    def taken(case):
        (case / "set").mkdir()

    suite.not_made("certificates-into-a-directory-that-is-there", "exists", lambda case: [str(case / "set"), suite.address], taken)
    for number, address in enumerate(("192.168.0", "192.168.0.175.", "192..168.0.175", "mac.local", "::1", "")):
        suite.not_made(
            f"certificates-for-an-address-that-is-not-{number}",
            "is not an IPv4 address",
            lambda case, address=address: [str(case / "set"), address],
        )
    suite.not_made("certificates-with-no-address", "usage", lambda case: [str(case / "set")])
    for signal_name in ("SIGINT", "SIGTERM", "SIGHUP"):
        suite.interrupted(f"certificates-interrupted-by-{signal_name}", signal_name)

    suite.starts("start")
    for file in ("ca.crt", "server.crt", "server.key"):
        suite.not_started(f"start-without-{file}", f"{file} is not there", lambda tls, file=file: (tls / file).unlink())
    suite.not_started("start-with-a-key-others-read", "is not at mode 0600", lambda tls: (tls / "server.key").chmod(0o644))
    suite.not_started_without_docker("start-without-docker")

    if FAILURES:
        raise SystemExit(f"arm64-builder: {len(FAILURES)} failed: {', '.join(FAILURES)}")


if __name__ == "__main__":
    main()
