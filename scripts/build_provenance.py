import hashlib
import json
import re
import subprocess
from pathlib import Path


DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
DNS_SUBDOMAIN = re.compile(r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?")

FIELDS = (
    "fabric.chuggy.dev/request-digest",
    "fabric.chuggy.dev/source-repository-id",
    "fabric.chuggy.dev/source-commit",
    "fabric.chuggy.dev/target-image-repository",
    "fabric.chuggy.dev/renderer",
    "fabric.chuggy.dev/shipwright-version",
    "fabric.chuggy.dev/profile",
    "fabric.chuggy.dev/profile-digest",
)


def required_string(value, description, pattern=None, length_max=None):
    valid = isinstance(value, str) and bool(value)
    valid = valid and (pattern is None or pattern.fullmatch(value) is not None)
    valid = valid and (length_max is None or len(value) <= length_max)
    if not valid:
        raise SystemExit(f"invalid {description}")
    return value


def load_verified_result(path):
    """One record and the result inside it, held to the two checksums that make
    it a record rather than a file: the one beside it over the bytes, and the
    one inside it over the canonical result. Neither says the cluster produced
    it -- `verify_record` against the request in `builds/` is what says that --
    and a caller selecting an image from a result runs both."""
    checksum_path = Path(f"{path}.sha256")
    if path.is_symlink() or checksum_path.is_symlink() or not path.is_file() or not checksum_path.is_file():
        raise SystemExit("regular build result and checksum files are required")
    encoded = path.read_bytes()
    expected_checksum = required_string(checksum_path.read_text().strip(), "build result checksum", DIGEST)
    if f"sha256:{hashlib.sha256(encoded).hexdigest()}" != expected_checksum:
        raise SystemExit("build result checksum mismatch")
    try:
        record = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid build result JSON: {error}")
    result = record.get("result")
    if not isinstance(result, dict):
        raise SystemExit("build result has no result payload")
    canonical = (json.dumps(result, sort_keys=True, indent=2, separators=(",", ": ")) + "\n").encode()
    expected_provenance = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    if record.get("provenanceRecordDigest") != expected_provenance:
        raise SystemExit("build result provenance digest mismatch")
    return record, result


def validate_result(result, repository_id):
    """What a successful result has to say before an image is selected from it:
    that it succeeded, that it is the configured repository's, that what was
    asked for is what was observed, and that it names a digest at all."""
    condition = result.get("terminalCondition", {})
    if condition.get("type") != "Succeeded" or condition.get("status") != "True":
        raise SystemExit("build result is not successful")
    source = result.get("source", {})
    recorded_repository_id = required_string(source.get("repositoryId"), "source repository id", DNS_SUBDOMAIN, 253)
    if recorded_repository_id != repository_id:
        raise SystemExit("build result source repository does not match configured repository id")
    requested = required_string(source.get("requestedCommit"), "requested source commit", COMMIT)
    observed = required_string(source.get("observedCommit"), "observed source commit", COMMIT)
    if requested != observed:
        raise SystemExit("build result source commits do not match")
    output = result.get("output", {})
    image_repository = required_string(output.get("repository"), "output repository")
    digest = required_string(output.get("digest"), "output digest", DIGEST)
    request_digest = required_string(result.get("requestDigest"), "request digest", DIGEST)
    attempt = result.get("attempt", {})
    attempt_name = required_string(attempt.get("name"), "attempt name", DNS_SUBDOMAIN, 253)
    return requested, image_repository, digest, request_digest, attempt_name


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
        "renderer": annotation(run, "fabric.chuggy.dev/renderer"),
        "controller": annotation(run, "fabric.chuggy.dev/shipwright-version"),
        "profile": annotation(run, "fabric.chuggy.dev/profile"),
        "profile_digest": annotation(run, "fabric.chuggy.dev/profile-digest"),
    }


class Unrunnable(SystemExit):
    """The verifier reached no verdict -- a tool it needs is absent, or it could
    not be executed at all. Uncaught this ends a run exactly as every other
    refusal in this module does; a caller whose exit codes separate a finding
    from a run that did not happen catches it and says which this was."""


def verify_record(record, identities):
    """The verified result at an arbitrary path. Split from `verify` below
    because the host's directory is not the only place a record lives: `results/`
    in this repository holds the same bytes under a path that names the request's
    repository and commit too, and one verifier decides both.

    The verifier exits 1 for a record that does not answer the identities and
    anything else for a run it could not complete -- 64 for arguments it does not
    take, and the shell's own codes for a tool it could not find. Only the first
    is a fact about the record."""
    verifier = Path(__file__).with_name("verify-build-provenance")
    command = [str(verifier), str(record)]
    for name, value in identities.items():
        command.extend((f"--{name.replace('_', '-')}", str(value)))
    try:
        completed = subprocess.run(command, text=True, capture_output=True)
    except OSError as error:
        raise Unrunnable(f"{verifier} could not be run: {error}")
    if completed.returncode == 1:
        raise SystemExit(completed.stderr.strip() or "provenance verification failed")
    if completed.returncode != 0:
        raise Unrunnable(
            f"{verifier} exited {completed.returncode}: "
            f"{completed.stderr.strip() or 'no detail'}"
        )
    return json.loads(completed.stdout)


def verify(results_path, identities):
    return verify_record(
        results_path / identities["request"] / f'{identities["attempt"]}.json', identities
    )
