#!/usr/bin/env python3
"""Scan every tracked file for the absolute-host-path disclosure class.

This repository is public. Four separate review findings (S2-R-01, S2-R-02,
S2-R-12, S3-R-14) were the same defect in four different places: a real host
path committed to a public repo. Each was found by a human or a reviewer
reading files one at a time, and each earlier scan was narrowed to the
pattern that had just been found -- so the next instance survived.

This checks the whole class over the whole tree, mechanically:

    python3 tools/check_disclosure.py

Exits 0 when clean, 1 with every hit listed. Intended for the verification
step of every sprint and before any push.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

#: Absolute host paths in any form a real machine produces.
PATTERNS: tuple[tuple[str, str], ...] = (
    (r"/home/[A-Za-z0-9._-]+", "POSIX home directory"),
    (r"/Users/[A-Za-z0-9._-]+", "macOS home directory"),
    (r"/Volumes/[A-Za-z0-9._-]+", "macOS mounted volume"),
    (r"[A-Z]:\\\\?[A-Za-z0-9._-]+", "Windows drive path"),
    (r"/root/[A-Za-z0-9._-]+", "root home directory"),
    (r"/var/folders/[A-Za-z0-9._-]+", "macOS temp directory"),
    (r"/private/var/[A-Za-z0-9._-]+", "macOS private var"),
    (r"/mnt/[A-Za-z0-9._-]+", "Linux mount point"),
    (r"/media/[A-Za-z0-9._-]+", "Linux removable media"),
    (r"(?:sk|ghp|gho|xox[baprs])-[A-Za-z0-9]{16,}", "credential-shaped token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY", "private key block"),
)

#: Paths that legitimately contain a pattern hit.
#:
#: ``~/.config/lee-kb/config.toml`` is the documented public configuration
#: contract, not a host path -- it names no user. Review artifacts quote the
#: findings they report, which necessarily include the offending strings.
ALLOWED_PREFIXES: tuple[str, ...] = (
    "code-reviews/",
    "tools/check_disclosure.py",
)

#: Substrings that make a hit a documented placeholder rather than a leak.
#: ``contains_token_shaped_secret(`` marks a line that feeds the connector's
#: own credential tripwire its test input; the literal key header there is the
#: fixture proving the detector fires, not a leaked secret.
PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "/path/to/",
    "/synthetic/",
    "<user>",
    "$CORPUS_",
    "contains_token_shaped_secret(",
)


def tracked_files() -> list[Path]:
    """Return every file git tracks, so nothing is scanned by hand."""
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [Path(name) for name in output.split("\0") if name]


def scan(paths: list[Path]) -> list[tuple[Path, int, str, str]]:
    """Return (path, line number, description, line) for every disclosure hit."""
    compiled = [(re.compile(pattern), label) for pattern, label in PATTERNS]
    hits: list[tuple[Path, int, str, str]] = []
    for path in paths:
        if str(path).startswith(ALLOWED_PREFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: nothing quotable to leak
        for number, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in PLACEHOLDER_MARKERS):
                continue
            for expression, label in compiled:
                if expression.search(line):
                    hits.append((path, number, label, line.strip()[:120]))
                    break
    return hits


def main() -> int:
    hits = scan(tracked_files())
    if not hits:
        print(
            "check_disclosure: clean — no host paths or credentials in tracked files."
        )
        return 0
    print(f"check_disclosure: {len(hits)} disclosure hit(s) in tracked files:")
    for path, number, label, line in hits:
        print(f"  {path}:{number}: {label}")
        print(f"      {line}")
    print("\nThis repository is public. Replace with a synthetic or placeholder value.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
