#!/usr/bin/env python3
"""Run the dump the migration Job takes, as the Job's pod is given it, against
a PostgreSQL started for the purpose.

WHAT IS RENDERED AND WHAT IS THIS SUITE'S. The script is the bytes of the
ConfigMap the rendered `dump` container mounts, run by that container's own
`command`, with every environment value the manifest writes out. What the
manifest takes from the cluster is stood in for here and nothing else is: the
server's address, the directory the claim is mounted at, the superuser's
password, and the Job's name where the pod reads its own label. So a script
that stops working under the command the manifest gives it, or that reads a
variable the manifest does not set, fails here rather than in a release.

A variable from a source this does not know is refused rather than skipped:
it is one the pod would have and this run would not.

TWO THINGS ARE SET AGAINST THE SCRIPT ON PURPOSE, because a run that inherited
this build's would pass without the line that answers each: the zone is hours
from UTC, so a stamp taken in local time is not the one a name is held to, and
the umask this starts with leaves a new file readable by anyone.

THE SERVER REQUIRES A PASSWORD, so a run that succeeds has used the one it was
given and a run with the wrong one is refused by the server rather than by
anything this suite arranged. Its bootstrap superuser is not `postgres`: the
role the script connects as is made beside it, which is what lets one case
take the superuser attribute away from it and give it back.

THE CASES, and the half of the script each is the only reader of:

- a good run leaves one pair, named for the Job and the UTC second it ran
  in, closed to everyone but its owner, with nothing partial beside it; the
  archive restores into an empty database with every row, and the globals
  carry a role's password, which only a superuser's dump does;
- a server that refuses the password, and no server at all, each end non-zero
  with nothing under a final name;
- a role that can dump the database and cannot read the globals ends non-zero
  with nothing under a final name, though the archive was written and read
  back -- the case for renaming neither file before both are whole;
- a `pg_dump` that exits 0 over an archive that has lost its last bytes, its
  table of contents whole, ends non-zero with nothing under a final name,
  which only a read-back of every block stands behind;
- a `pg_dumpall` that exits 0 over globals that have lost their last bytes, or
  all of them, ends the same way, which only the hold on the lines it ends a
  dump with stands behind. A role's comment here carries those lines, so a
  hold that found them anywhere would pass the file that was cut;
- a `mv` that will not rename the globals leaves no archive under a final
  name, which is the order of the two renames;
- each of those leaves every file that was already there, which is the rule
  that a run that failed removes nothing;
- retention keeps the count the manifest sets, counts the pair just written
  first even when that many archives are stamped later than it, removes what
  failed runs left, and removes nothing it did not name -- a file, a directory
  and a link, each named almost like its own;
- retention keeps the same count in the ordinary run, where nothing is stamped
  later and the pair just written is itself among the newest;
- a count of zero, a Job's name retention would not know for its own, and a
  password the pod was not given are each refused by name, with the directory
  exactly as it was;
- a pair already under the name this run would take is refused rather than
  written over.

WHAT THIS CANNOT SEE. The image: the pod runs these bytes with the `bash` and
the PostgreSQL clients of `postgres:18.3-trixie`, and this runs them with the
ones nixpkgs pins, an earlier major. Nothing here uses an option the two do
not share, and that is an argument rather than a check. The NetworkPolicy,
the Secret and the volume are `tests/rollout-order.py`'s.
"""

import os
import re
import shutil
import calendar
import subprocess
import sys
import time
from pathlib import Path

import yaml

RENDERED = Path(sys.argv[1])
WORK = Path(sys.argv[2]).resolve()
SOCKET = WORK / "s"

DUMP = "dump"
JOB_LABEL = "metadata.labels['job-name']"
ADMIN = "bootstrap"
ADMIN_PASSWORD = "bootstrap-password"
SUPERUSER = "postgres"
SUPERUSER_PASSWORD = "superuser-password"
DATABASE = "chuggy"
ROWS = 1000
# How many seconds ahead `collision` takes the name of. A run that started
# later than that would find its name free, succeed, and fail the case.
AHEAD = 120
# The line `pg_dumpall` closes a dump with, between two that are `--` alone.
CLOSING = "-- PostgreSQL database cluster dump complete"

# Set from the render before anything runs: the command the container gives,
# and the port its environment names, which the server here listens under.
ARGV = []
PORT = ""

FAILURES = []


def report(case, message):
    FAILURES.append(f"{case}: {message}")
    print(f"FAIL {case}: {message}", file=sys.stderr)


def refuse(message):
    raise SystemExit(f"dump-script: {message}")


# ------------------------------------------------------------- the render ----


def rendered_dump():
    """The `dump` container, the ConfigMaps it mounts and the Job's name."""
    documents = [
        document for document in yaml.safe_load_all(RENDERED.read_text()) if document
    ]
    jobs = [document for document in documents if document.get("kind") == "Job"]
    if len(jobs) != 1:
        refuse(f"expected one Job in {RENDERED}, found {len(jobs)}")
    job = jobs[0]
    pod = job["spec"]["template"]["spec"]
    containers = [
        container for container in pod.get("initContainers") or [] if container["name"] == DUMP
    ]
    if len(containers) != 1:
        refuse(f"expected one initContainer `{DUMP}`, found {len(containers)}")
    maps = {
        document["metadata"]["name"]: document
        for document in documents
        if document.get("kind") == "ConfigMap"
        and document["metadata"].get("namespace") == job["metadata"].get("namespace")
    }
    return job, pod, containers[0], maps


def mounted(pod, container, maps):
    """Each ConfigMap the container mounts, written out as the kubelet would
    project it, keyed by the path the container sees it at."""
    volumes = {volume["name"]: volume for volume in pod.get("volumes") or []}
    paths = {}
    for mount in container.get("volumeMounts") or []:
        source = (volumes[mount["name"]].get("configMap") or {}).get("name")
        if source is None:
            continue
        if source not in maps:
            refuse(f"`{DUMP}` mounts ConfigMap {source}, which the render does not carry")
        directory = WORK / "mounts" / mount["name"]
        directory.mkdir(parents=True)
        for key, value in (maps[source].get("data") or {}).items():
            (directory / key).write_text(value)
            # A projected key is a plain file. A command that needed it to be
            # executable would fail in the pod, so it has to fail here.
            (directory / key).chmod(0o644)
        paths[mount["mountPath"].rstrip("/")] = directory
    return paths


def command_of(container, paths):
    argv = []
    for argument in list(container.get("command") or []) + list(container.get("args") or []):
        for mount_path, directory in paths.items():
            if argument.startswith(mount_path + "/"):
                argument = str(directory / argument[len(mount_path) + 1 :])
        argv.append(argument)
    if not argv:
        refuse(f"`{DUMP}` has no command, so what it runs is the image's and not this tree's")
    return argv


def environment_of(job, container, socket, directory, password):
    """The container's environment as the manifest writes it, with the four
    values the cluster supplies stood in for."""
    # A POSIX zone needs no zone database: this one is seven hours behind UTC.
    environment = {"PATH": os.environ["PATH"], "TZ": "ELSEWHERE7"}
    for entry in container.get("env") or []:
        name, source = entry["name"], entry.get("valueFrom") or {}
        if "value" in entry:
            environment[name] = entry["value"]
        elif "secretKeyRef" in source:
            environment[name] = password
        elif (source.get("fieldRef") or {}).get("fieldPath") == JOB_LABEL:
            environment[name] = job["metadata"]["name"]
        else:
            refuse(f"`{DUMP}` takes {name} from {source}, which this suite has no stand-in for")
    for name, value in (("PGHOST", str(socket)), ("CHUG_DUMP_DIR", str(directory))):
        if name not in environment:
            refuse(f"`{DUMP}` does not set {name}, so the script cannot be pointed anywhere")
        environment[name] = value
    return environment


# ------------------------------------------------------------- the server ----


def postgres(*argv, password=ADMIN_PASSWORD, user=ADMIN, database="postgres", check=True):
    completed = subprocess.run(
        ["psql", "-XqAt", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", database, *argv],
        env={**os.environ, "PGHOST": str(SOCKET), "PGPORT": PORT, "PGPASSWORD": password},
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        refuse(f"psql {' '.join(argv)} failed: {completed.stderr}")
    return completed.stdout.strip()


def start():
    data = WORK / "data"
    SOCKET.mkdir(parents=True)
    pwfile = WORK / "pwfile"
    pwfile.write_text(ADMIN_PASSWORD + "\n")
    subprocess.run(
        [
            "initdb", "--pgdata", str(data), "--username", ADMIN, "--pwfile", str(pwfile),
            "--auth", "scram-sha-256", "--no-locale", "--encoding", "UTF8",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    options = f"-c listen_addresses= -c unix_socket_directories={SOCKET} -c port={PORT}"
    subprocess.run(
        ["pg_ctl", "--pgdata", str(data), "--log", str(WORK / "server.log"), "--wait",
         "-o", options, "start"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    postgres("-c", f"CREATE ROLE {SUPERUSER} LOGIN SUPERUSER PASSWORD '{SUPERUSER_PASSWORD}'")
    postgres("-c", "CREATE ROLE chuggy_api LOGIN PASSWORD 'a-service-password'")
    # The lines `pg_dumpall` ends a dump with, somewhere other than its end.
    postgres("-c", f"COMMENT ON ROLE chuggy_api IS 'kept\n--\n{CLOSING}\n--\n'")
    postgres("-c", f"CREATE DATABASE {DATABASE} OWNER {SUPERUSER}")
    postgres(
        "-c",
        "CREATE TABLE ledger (id integer PRIMARY KEY, applied text NOT NULL)",
        "-c",
        f"INSERT INTO ledger SELECT n, 'migration ' || n FROM generate_series(1, {ROWS}) AS n",
        user=SUPERUSER,
        password=SUPERUSER_PASSWORD,
        database=DATABASE,
    )


def stop():
    subprocess.run(
        ["pg_ctl", "--pgdata", str(WORK / "data"), "--mode", "immediate", "stop"],
        check=False,
        stdout=subprocess.DEVNULL,
    )


# -------------------------------------------------------------- the cases ----

OWN = re.compile(r"^(\d{8}T\d{6}Z-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\.(dump|globals\.sql)$")


def run(case, environment, **changed):
    completed = subprocess.run(
        ARGV, env={**environment, **changed}, capture_output=True, text=True, check=False
    )
    (WORK / f"{case}.log").write_text(completed.stdout + completed.stderr)
    return completed


def directory_for(case):
    directory = WORK / "dumps" / case
    directory.mkdir(parents=True)
    return directory


def listing(directory):
    """Every entry by name, with what it is, so that a file replaced by another
    of the same name does not read as kept."""
    found = {}
    for path in sorted(directory.iterdir()):
        if path.is_symlink():
            found[path.name] = ("link", os.readlink(path))
        elif path.is_dir():
            found[path.name] = ("directory", None)
        else:
            found[path.name] = ("file", path.read_bytes())
    return found


def whole(directory):
    return sorted(name for name in listing(directory) if not name.endswith(".partial"))


def seed(directory, base, endings=(".dump", ".globals.sql")):
    for ending in endings:
        (directory / f"{base}{ending}").write_text(f"seeded {base}{ending}\n")


def stamped(second):
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(second))


def good(environment, job):
    case = "good-run"
    directory = directory_for(case)
    started = int(time.time())
    completed = run(case, environment, CHUG_DUMP_DIR=str(directory))
    finished = int(time.time())
    if completed.returncode != 0:
        report(case, f"exit {completed.returncode}: {completed.stderr}")
        return
    names = sorted(listing(directory))
    matches = [OWN.match(name) for name in names]
    bases = {match.group(1) for match in matches if match}
    if len(names) != 2 or not all(matches) or len(bases) != 1:
        report(case, f"expected one pair and nothing else, found {names}")
        return
    base = bases.pop()
    if not re.fullmatch(rf"\d{{8}}T\d{{6}}Z-{re.escape(job)}", base):
        report(case, f"the pair is named {base}, not a UTC timestamp and then {job}")
        return
    stamped = calendar.timegm(time.strptime(base[:16], "%Y%m%dT%H%M%SZ"))
    if not started <= stamped <= finished:
        report(case, f"the pair is stamped {base[:16]}, which is not the UTC second it was taken in")
    archive, globals_ = directory / f"{base}.dump", directory / f"{base}.globals.sql"
    for path in (archive, globals_):
        mode = path.stat().st_mode & 0o777
        if mode != 0o600:
            report(case, f"{path.name} is mode {mode:o}, and the globals carry password hashes")

    listed = subprocess.run(
        ["pg_restore", "--list", str(archive)], capture_output=True, text=True, check=False
    )
    if listed.returncode != 0 or "TABLE DATA public ledger" not in listed.stdout:
        report(case, f"pg_restore --list does not read the archive's table: {listed.stderr}")
        return
    # Listing reads the archive's table of contents. That the rows are in it is
    # read by putting them back.
    postgres("-c", "CREATE DATABASE restored")
    restored = subprocess.run(
        ["pg_restore", "--no-owner", "-U", ADMIN, "-d", "restored", str(archive)],
        env={**os.environ, "PGHOST": str(SOCKET), "PGPORT": PORT, "PGPASSWORD": ADMIN_PASSWORD},
        capture_output=True,
        text=True,
        check=False,
    )
    count = postgres("-c", "SELECT count(*) FROM ledger", database="restored", check=False)
    if restored.returncode != 0 or count != str(ROWS):
        report(case, f"the archive restored {count or 'no'} rows of {ROWS}: {restored.stderr}")
    text = globals_.read_text()
    if not re.search(r"ALTER ROLE chuggy_api WITH .*PASSWORD 'SCRAM-SHA-256\$", text):
        report(case, "the globals do not carry a role's password, which a superuser's dump does")


def failing(case, environment, expected, untouched=False, **changed):
    """A run that must fail: non-zero, nothing under a final name that was not
    there before, and nothing that was there before gone or changed. One
    refused before it starts leaves no partial file either. Returns the files
    the run left."""
    directory = directory_for(case)
    seed(directory, "20200101T000000Z-chuggy-migrate-old")
    seed(directory, "20200102T000000Z-chuggy-migrate-failed", endings=(".dump.partial",))
    (directory / "operator-notes.txt").write_text("not a dump\n")
    before = listing(directory)
    completed = run(case, environment, CHUG_DUMP_DIR=str(directory), **changed)
    after = listing(directory)
    if completed.returncode == 0:
        report(case, "exit 0 from a dump that cannot have been taken")
    if expected not in completed.stderr:
        report(case, f"failed for another reason than `{expected}`: {completed.stderr}")
    for name, content in before.items():
        if after.get(name) != content:
            report(case, f"{name} was there before the run that failed and is gone or changed")
    new = sorted(name for name in after if name not in before and not name.endswith(".partial"))
    if new:
        report(case, f"a run that failed left {new} under a final name")
    if untouched and sorted(after) != sorted(before):
        report(case, f"a run refused before it started left {sorted(set(after) - set(before))}")
    return [directory / name for name in sorted(set(after) - set(before))]


def stand_in(case, program, script):
    """A PATH on which `program` is `script`, which is given the real one as
    `$real`."""
    shadow = WORK / "shadow" / case
    shadow.mkdir(parents=True)
    (shadow / program).write_text(
        f"#!{shutil.which('bash')}\nreal={shutil.which(program)}\n{script}"
    )
    (shadow / program).chmod(0o755)
    return f"{shadow}{os.pathsep}{os.environ['PATH']}"


# The real program, and then the file it was told to write in `$target` with
# the exit status still 0: a write that fell short and that nothing reported.
SHORT_WRITE = (
    '"$real" "$@" || exit\n'
    'while [ $# -gt 1 ]; do [ "$1" != -f ] || target=$2; shift; done\n'
)


def cut_short(environment):
    """An archive without its last bytes. The stand-in lists what it leaves,
    so the cut is known to fall after the table of contents, where a read-back
    that stopped at the contents would pass it."""
    failing(
        "cut-short",
        environment,
        "could not read from input file",
        PATH=stand_in(
            "cut-short",
            "pg_dump",
            SHORT_WRITE
            + 'truncate --size=-50 "$target"\n'
            'pg_restore --list "$target" >/dev/null 2>&1 && exit\n'
            'echo "the cut reached the table of contents" >&2\n'
            "exit 1\n",
        ),
    )


def globals_short(environment):
    """Globals without their last bytes, and globals with none: what
    `pg_dumpall` leaves, at exit 0, on a volume that filled while it wrote.
    What the cut leaves is read here, so it is known to carry the closing line
    still -- the one in the role's comment -- where a hold that found that
    line anywhere would pass the file."""
    left = {}
    for case, size in (("globals-cut-short", "-50"), ("globals-empty", "0")):
        left[case] = failing(
            case,
            environment,
            "does not end as pg_dumpall ends a dump",
            PATH=stand_in(case, "pg_dumpall", SHORT_WRITE + f'truncate --size={size} "$target"\n'),
        )
    cut = [path.read_text() for path in left["globals-cut-short"] if ".globals.sql" in path.name]
    if len(cut) != 1 or CLOSING not in cut[0].splitlines():
        refuse("globals-cut-short left no globals that carry the closing line and not the end")


def rename_refused(environment):
    """A `mv` that renames anything but the globals. Whichever rename the
    script makes first, no archive may be left under its final name without
    them."""
    failing(
        "rename-refused",
        environment,
        "the globals are not renamed",
        PATH=stand_in(
            "rename-refused",
            "mv",
            "for argument; do\n"
            "  case $argument in *.globals.sql.partial)\n"
            '    echo "the globals are not renamed" >&2; exit 1 ;;\n'
            "  esac\n"
            "done\n"
            'exec "$real" "$@"\n',
        ),
    )


def collision(environment, job):
    """An archive already under the name this run would take, whichever second
    it starts in: it is refused, and nothing is written over or removed."""
    case = "collision"
    directory = directory_for(case)
    now = int(time.time())
    for second in range(now, now + AHEAD):
        seed(directory, f"{stamped(second)}-{job}", endings=(".dump",))
    before = listing(directory)
    completed = run(case, environment, CHUG_DUMP_DIR=str(directory))
    if completed.returncode == 0:
        report(case, "exit 0 from a run whose name was taken")
    if "is already there" not in completed.stderr:
        report(case, f"failed for another reason than its name being taken: {completed.stderr}")
    if listing(directory) != before:
        report(case, "a run whose name was taken wrote, replaced or removed something")


def written(case, before, after, job):
    """The one pair a run that succeeded added, or None with the reason
    reported."""
    added = {
        OWN.match(name).group(1) for name in after if OWN.match(name) and name not in before
    }
    if not added:
        report(case, "the pair the run had just written is not there: retention removed it")
        return None
    if len(added) != 1 or not next(iter(added)).endswith(f"-{job}"):
        report(case, f"expected the run to add one pair named for {job}, found {sorted(added)}")
        return None
    return added.pop()


def archives_in(listed):
    return sorted(
        name[: -len(".dump")]
        for name in listed
        if OWN.match(name) and name.endswith(".dump") and listed[name][0] == "file"
    )


def retention(environment, job):
    case = "retention"
    directory = directory_for(case)
    keep = int(environment["CHUG_DUMP_KEEP"])
    # As many archives stamped after this run as the count: a retention that
    # read "newest" off the names alone would keep these and remove its own.
    later = [f"20990101T0000{n:02d}Z-chuggy-migrate-later{n}" for n in range(keep)]
    earlier = [f"202001{n:02d}T000000Z-chuggy-migrate-earlier{n}" for n in range(1, 4)]
    for base in later + earlier:
        seed(directory, base)
    seed(
        directory,
        "20200201T000000Z-chuggy-migrate-failed",
        endings=(".dump.partial", ".globals.sql.partial"),
    )
    seed(directory, "20200202T000000Z-chuggy-migrate-interrupted", endings=(".globals.sql",))
    # Not this script's, each one edit away from a name that is. The directory
    # and the link carry a name that IS one, stamped after everything else, so
    # a count that took them for archives would keep them in place of two.
    foreign = [
        "operator-notes.txt",
        "chuggy.dump",
        "pre-merge-20200101T000000Z.dump",
        "20200101T000000Z-Chuggy.dump",
        "20200101T000000Z-chuggy.dump.bak",
        "2020-01-01T00:00:00Z-chuggy.globals.sql",
    ]
    for name in foreign:
        (directory / name).write_text(f"foreign {name}\n")
    (directory / "21000103T000000Z-a-directory.dump").mkdir()
    (directory / "21000104T000000Z-a-link.dump").symlink_to("operator-notes.txt")
    before = listing(directory)

    completed = run(case, environment, CHUG_DUMP_DIR=str(directory))
    if completed.returncode != 0:
        report(case, f"exit {completed.returncode}: {completed.stderr}")
        return
    after = listing(directory)
    mine = written(case, before, after, job)
    if mine is None:
        return
    archives = archives_in(after)
    expected = sorted([mine] + sorted(later, reverse=True)[: keep - 1])
    if mine not in archives:
        report(case, "retention removed the archive the run had just written")
    if archives != expected:
        report(
            case,
            f"retention kept {archives}, not the pair just written and the newest "
            f"others up to {keep} in all: {expected}",
        )
    for base in archives:
        if f"{base}.globals.sql" not in after:
            report(case, f"{base}.dump was kept without its globals")
    leftovers = sorted(
        name
        for name in after
        if name.endswith(".partial")
        or (
            OWN.match(name)
            and name.endswith(".globals.sql")
            and OWN.match(name).group(1) not in archives
        )
    )
    if leftovers:
        report(case, f"retention left {leftovers}, which are this script's and no kept pair's")
    untouched = foreign + ["21000103T000000Z-a-directory.dump", "21000104T000000Z-a-link.dump"]
    for name in untouched:
        if after.get(name) != before[name]:
            report(case, f"{name} is not this script's and is gone or changed")


def newest(environment, job):
    """The ordinary run: nothing is stamped after the pair just written, so
    that pair is itself among the newest the count is taken over."""
    case = "retention-newest"
    directory = directory_for(case)
    keep = int(environment["CHUG_DUMP_KEEP"])
    start_of_2020 = calendar.timegm((2020, 1, 1, 0, 0, 0))
    earlier = [
        f"{stamped(start_of_2020 + n)}-chuggy-migrate-earlier{n}" for n in range(keep + 2)
    ]
    for base in earlier:
        seed(directory, base)
    before = listing(directory)
    completed = run(case, environment, CHUG_DUMP_DIR=str(directory))
    if completed.returncode != 0:
        report(case, f"exit {completed.returncode}: {completed.stderr}")
        return
    after = listing(directory)
    mine = written(case, before, after, job)
    if mine is None:
        return
    expected = sorted([mine] + sorted(earlier, reverse=True)[: keep - 1])
    if archives_in(after) != expected:
        report(
            case,
            f"retention kept {len(archives_in(after))} archives and not the {keep} that "
            f"are the pair just written and the newest before it: {archives_in(after)}",
        )
    pairs = sorted(f"{base}{ending}" for base in expected for ending in (".dump", ".globals.sql"))
    if sorted(after) != pairs:
        report(case, f"retention left {sorted(set(after) - set(pairs))} beside the pairs it kept")


def main():
    job, pod, container, maps = rendered_dump()
    name = job["metadata"]["name"]
    global ARGV, PORT
    ARGV = command_of(container, mounted(pod, container, maps))
    PORT = next(
        (entry.get("value") for entry in container.get("env") or [] if entry["name"] == "PGPORT"),
        None,
    )
    if not PORT:
        refuse(f"`{DUMP}` writes out no PGPORT, so the port the script asks for is not the render's")
    os.umask(0o022)
    start()
    try:
        environment = environment_of(job, container, SOCKET, WORK / "unused", SUPERUSER_PASSWORD)
        good(environment, name)
        failing(
            "refused-password",
            environment,
            "password authentication failed",
            PGPASSWORD="not-the-password",
        )
        failing(
            "no-server",
            environment,
            "No such file or directory",
            PGHOST=str(WORK / "no-socket-here"),
        )
        # The archive is written and read back, and then the globals are
        # refused: the role may read its own database and not the roles'
        # passwords.
        postgres("-c", f"ALTER ROLE {SUPERUSER} NOSUPERUSER")
        try:
            failing("refused-globals", environment, "permission denied")
        finally:
            postgres("-c", f"ALTER ROLE {SUPERUSER} SUPERUSER")
        cut_short(environment)
        globals_short(environment)
        rename_refused(environment)
        failing(
            "zero-count", environment, "CHUG_DUMP_KEEP is '0'", untouched=True, CHUG_DUMP_KEEP="0"
        )
        failing(
            "not-a-job",
            environment,
            "CHUG_DUMP_JOB is 'Not-A-Job'",
            untouched=True,
            CHUG_DUMP_JOB="Not-A-Job",
        )
        failing(
            "no-password", environment, "PGPASSWORD is not set", untouched=True, PGPASSWORD=""
        )
        collision(environment, name)
        retention(environment, name)
        newest(environment, name)
    finally:
        stop()

    if FAILURES:
        raise SystemExit(f"dump-script: {len(FAILURES)} failed")
    version = subprocess.run(
        ["pg_dump", "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    print(f"clean: `{' '.join(container['command'])}` as rendered, with {version}")


if __name__ == "__main__":
    main()
