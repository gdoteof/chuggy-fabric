#!/usr/bin/env python3
"""Refuse a `fabric-release` whose `ignore` does not keep exactly two directories.

THE LINES ARE READ FROM THE MANIFEST A HOST GENERATES and decided against this
repository's own files, so what is held is what they keep and not how they are
spelled.

A PATH IS DECIDED AS SOURCE-CONTROLLER DECIDES IT. Its archive walks every
regular file, descending into a directory whether or not the directory is
excluded, and asks go-git's gitignore matcher about each: the patterns are
tried from the last line to the first and the first that matches decides.
`parse` and `match` below are that matcher's rule for the lines accepted here.

WHAT IS NOT MODELLED IS REFUSED, NOT GUESSED. A line using `**`, `?`, `[` or
`\\` is one; so is a file that no line decides, because the patterns that
decide it then are source-controller's own exclusions and any `.sourceignore`
in the tree, and neither is read here.

EACH DIRECTORY MUST HOLD A FILE, or the two sets are equal over a directory
that is not there.
"""

import os
import re
import sys
from pathlib import Path

import yaml

RELEASE = "fabric-release"
KEPT = ("cluster/chuggy-migrate", "cluster/chuggy")


def refuse(message):
    raise SystemExit(f"flux-release-source: {message}")


def parse(line):
    keeps = line.startswith("!")
    text = line[1:] if keeps else line
    for unmodelled in ("**", "?", "[", "\\"):
        if unmodelled in text:
            refuse(
                f"the line `{line}` uses `{unmodelled}`, which this check does "
                "not model, so what the lines keep is not decided here"
            )
    text = text.rstrip(" ")
    directory_only = text.endswith("/")
    if directory_only:
        text = text[:-1]
    segments = [
        re.compile("[^/]*".join(re.escape(part) for part in segment.split("*")))
        for segment in text.split("/")
    ]
    return keeps, directory_only, "/" in text, segments


def match(pattern, path):
    """Whether the pattern matches the path of a regular file."""
    _, directory_only, anchored, segments = pattern
    if not anchored:
        for index, name in enumerate(path):
            if segments[0].fullmatch(name):
                return not (directory_only and index == len(path) - 1)
        return False
    rest, matched = path, False
    for segment in segments:
        if segment.pattern == "":
            continue
        if not rest or not segment.fullmatch(rest[0]):
            return False
        rest, matched = rest[1:], True
    return matched and not (directory_only and not rest)


def main():
    if len(sys.argv) != 3:
        refuse("usage: flux-release-source.py MANIFEST TREE")
    tree = Path(sys.argv[2])
    releases = [
        document
        for document in yaml.safe_load_all(Path(sys.argv[1]).read_text())
        if document
        and document.get("kind") == "GitRepository"
        and document["metadata"].get("name") == RELEASE
    ]
    if len(releases) != 1:
        refuse(f"expected one GitRepository {RELEASE}, found {len(releases)}")
    ignore = (releases[0].get("spec") or {}).get("ignore")
    if not isinstance(ignore, str):
        refuse(f"{RELEASE} carries no `ignore`, so it keeps the whole repository")
    patterns = [
        parse(line)
        for line in (line.removesuffix("\r") for line in ignore.split("\n"))
        if line.strip() and not line.startswith("#")
    ]

    files = sorted(
        (Path(directory) / name).relative_to(tree).as_posix()
        for directory, _, names in os.walk(tree)
        for name in names
        if not (Path(directory) / name).is_symlink()
    )
    kept = set()
    for file in files:
        path = file.split("/")
        deciding = next(
            (pattern for pattern in reversed(patterns) if match(pattern, path)), None
        )
        if deciding is None:
            refuse(
                f"no line of the `ignore` decides {file}, and what decides it "
                "then is not modelled here"
            )
        if deciding[0]:
            kept.add(file)

    expected = set()
    for directory in KEPT:
        under = {file for file in files if file.startswith(f"{directory}/")}
        if not under:
            refuse(f"{directory}/ holds no file in this tree")
        expected |= under

    directories = " and ".join(f"{directory}/" for directory in KEPT)
    for verdict, differing in (("keeps", kept - expected), ("drops", expected - kept)):
        if differing:
            refuse(
                f"{RELEASE} {verdict} these, and is held to exactly the files "
                f"under {directories}:\n  " + "\n  ".join(sorted(differing))
            )


if __name__ == "__main__":
    main()
