import json
import re
import subprocess
from pathlib import Path


FIELDS = (
    "fabric.chuggy.dev/request-digest",
    "fabric.chuggy.dev/source-repository-id",
    "fabric.chuggy.dev/source-commit",
    "fabric.chuggy.dev/target-image-repository",
    "fabric.chuggy.dev/profile",
    "fabric.chuggy.dev/profile-digest",
)


def annotation(document, name):
    match = re.search(rf"^    {re.escape(name)}: (?:\"([^\"]+)\"|([^\n]+))$", document, re.MULTILINE)
    if match is None:
        raise SystemExit(f"manifest is missing {name}")
    return match.group(1) or match.group(2)


def manifest_identities(content):
    documents = content.split("---\n")
    if len(documents) != 2 or "kind: Build\n" not in documents[0] or "kind: BuildRun\n" not in documents[1]:
        raise SystemExit("request manifest must contain one Build and one live BuildRun")
    build, run = documents
    for field in FIELDS:
        if annotation(build, field) != annotation(run, field):
            raise SystemExit(f"Build and attempt disagree on {field}")
    request = annotation(run, FIELDS[0])
    ordinal = int(annotation(run, "fabric.chuggy.dev/attempt-ordinal"))
    build_name = re.search(r"^  name: ([a-z0-9.-]+)$", build, re.MULTILINE)
    run_name = re.search(r"^  name: ([a-z0-9.-]+)$", run, re.MULTILINE)
    if build_name is None or run_name is None:
        raise SystemExit("manifest is missing a resource name")
    expected_build = f"build-{request.removeprefix('sha256:')[:40]}"
    expected_attempt = f"{expected_build}-a{ordinal}"
    if build_name.group(1) != expected_build or run_name.group(1) != expected_attempt:
        raise SystemExit("resource names do not match request digest and attempt ordinal")
    source = annotation(run, "fabric.chuggy.dev/source-commit")
    target = annotation(run, "fabric.chuggy.dev/target-image-repository")
    if f"    revision: {source}\n" not in build:
        raise SystemExit("Build does not name the provenance source commit")
    if f'    image: "{target}:request-{request.removeprefix("sha256:")}"\n' not in build:
        raise SystemExit("Build output does not match the request target")
    if f"    name: {expected_build}\n" not in run:
        raise SystemExit("BuildRun does not reference the immutable Build")
    return documents, {
        "request": request,
        "attempt": expected_attempt,
        "ordinal": ordinal,
        "repository": annotation(run, "fabric.chuggy.dev/source-repository-id"),
        "source_commit": source,
        "target": target,
        "profile": annotation(run, "fabric.chuggy.dev/profile"),
        "profile_digest": annotation(run, "fabric.chuggy.dev/profile-digest"),
    }


def verify(results_path, identities):
    record = results_path / identities["request"] / f'{identities["attempt"]}.json'
    verifier = Path(__file__).with_name("verify-build-provenance")
    command = [str(verifier), str(record)]
    for name, value in identities.items():
        command.extend((f"--{name.replace('_', '-')}", str(value)))
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or "provenance verification failed")
    return json.loads(completed.stdout)
