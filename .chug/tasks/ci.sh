#!/usr/bin/env bash
# cluster/chuggy-migrate and cluster/chuggy name no release.
#
# A release is made by cluster/build-system/publish.sh, which writes over a
# copy of those two directories the digest of each of its two images, chuggy's
# commit as an annotation and that commit into the migration Job's name. So one
# written in git is replaced without a word by the next release published: it
# deploys nothing, and a reader of the file believes it. Every file under the
# two is read, and refused where a line that is not a comment
#
#   - names either image and not at the digest of sixty-four zeroes, which is
#     what git carries there and cluster/chuggy/chuggy-ticket-service.yaml
#     argues: another digest, a tag, or the name alone, which is a tag a
#     registry can be given;
#   - carries the `fabric.chuggy.dev/source-commit` key, as a manifest writes
#     it or as the path of a JSON patch does, with `~1` for its `/`;
#   - names a Job anything but `chuggy-migrate`.
#
# IT READS THE FILES AND NOT THE RENDER, because the image an evaluation runs
# in carries python3 and git, and neither kubectl nor a YAML parser. The first
# two are held of every line rather than of a field, which is also what
# refuses one written through a directory's own kustomization. The Job's name
# is read from the document that declares it, laid out as this tree lays one
# out; a rename patched in from another file is not read. A tree in which
# nothing names one of the images or declares a Job, or whose Job this cannot
# find the name of, is a run that did not happen. tests/chug-ci.nix drives
# this file through each refusal and through trees it cannot run in.
#
# THIS IS THE PORTABLE SUBSET, NOT THE FABRIC'S GATE. `nix flake check` builds
# the hosts, holds the assertions and warnings a host is refused or warned by,
# and runs the rendered-manifest gates. None of it runs here. Its checks read
# the tree, this file included, so what a change still needs run is read off
# `flake.nix` rather than assumed from this gate passing.
#
# Exit 0 clean, 1 on a finding, 2 when it could not run. Exit 2 is not a pass.
set -o errexit -o nounset -o pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)

command -v python3 >/dev/null 2>&1 ||
  { echo "cannot run: python3 is not on PATH" >&2; exit 2; }
for directory in chuggy-migrate chuggy; do
  [ -d "$root/cluster/$directory" ] ||
    { echo "cannot run: $root/cluster/$directory is not a directory" >&2; exit 2; }
done

# The reading exits 3 for a finding and 2 for a tree it cannot read, and
# nothing else does: an exception in it exits 1 like a finding would have, and
# reporting that as one sends a reader to the manifests.
status=0
python3 - "$root" <<'PYTHON' || status=$?
import re
import sys
from pathlib import Path

IMAGES = (
    "registry.chuggy.internal/chuggy/api",
    "registry.chuggy.internal/chuggy/web",
)
NOTHING = "@sha256:" + "0" * 64
ANNOTATION = "fabric.chuggy.dev/source-commit"
SPELLINGS = (ANNOTATION, ANNOTATION.replace("/", "~1"))
JOB = "chuggy-migrate"

root = Path(sys.argv[1])
findings = []
named = dict.fromkeys(IMAGES, 0)
jobs = 0


def unreadable(message):
    print(f"cannot run: {message}", file=sys.stderr)
    raise SystemExit(2)


def job_name(where, document):
    """The line naming the Job a document declares: `name` two spaces in,
    which is its metadata's and no other field's."""
    for line in document:
        if re.match(r"  name:", line):
            return line
    unreadable(f"{where} declares a Job whose name is not a line of its metadata")


for directory in ("cluster/chuggy-migrate", "cluster/chuggy"):
    for path in sorted(p for p in (root / directory).rglob("*") if p.is_file()):
        where = path.relative_to(root)
        document = []
        for number, line in enumerate(path.read_text().splitlines() + ["---"], 1):
            if line.lstrip().startswith("#"):
                continue
            for image in IMAGES:
                for found in re.finditer(re.escape(image), line):
                    named[image] += 1
                    if not line.startswith(NOTHING, found.end()):
                        findings.append(
                            f"{where}:{number} names {image} and not at the digest of "
                            f"nothing: {line.strip()}"
                        )
            if any(spelling in line for spelling in SPELLINGS):
                findings.append(f"{where}:{number} carries {ANNOTATION}: {line.strip()}")
            if line.rstrip() != "---":
                document.append(line)
                continue
            if any(re.fullmatch(r"kind:\s+Job\s*", entry) for entry in document):
                jobs += 1
                name = job_name(where, document)
                if not re.fullmatch(rf"  name:\s+{JOB}\s*", name):
                    findings.append(f"{where} names its Job `{name.strip()}`, not `name: {JOB}`")
            document = []

for image, count in named.items():
    if not count:
        unreadable(f"nothing under cluster/chuggy-migrate or cluster/chuggy names {image}")
if not jobs:
    unreadable("nothing under cluster/chuggy-migrate or cluster/chuggy declares a Job")
for finding in findings:
    print(finding, file=sys.stderr)
if findings:
    raise SystemExit(3)
PYTHON
case $status in
  0) ;;
  3) exit 1 ;;
  2) exit 2 ;;
  *) echo "cannot run: reading $root/cluster exited $status" >&2; exit 2 ;;
esac

echo "clean: cluster/chuggy-migrate and cluster/chuggy name no release; nix flake check did not run"
