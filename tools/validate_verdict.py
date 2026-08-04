#!/usr/bin/env python3
"""Preflight a review verdict against the gate's required shape.

Review steps are gated by Agent-Orch's builtin ``review_verdict/v1`` schema.
Two review cycles have already been spent failing that gate on field names
rather than review quality, so reviewers run this before finishing:

    python3 tools/validate_verdict.py code-reviews/<name>.verdict.json

Exits 0 when the document satisfies the required shape, 1 otherwise with
every problem listed. This mirrors the platform schema; the platform remains
authoritative, and this script is a fast local check, not a substitute.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOP_LEVEL_REQUIRED = ("verdict", "findings", "checks_run", "lenses")
FINDING_REQUIRED = ("id", "severity", "file", "location", "problem", "proposed_fix")
CHECK_REQUIRED = ("command", "exit_code", "summary")
VALID_SEVERITIES = {"Critical", "High", "Medium", "Low"}
VALID_VERDICTS = {"pass", "fail"}


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate(document: object) -> list[str]:
    """Return a list of problems; empty means the document satisfies the gate."""
    problems: list[str] = []
    if not isinstance(document, dict):
        return ["top level must be a JSON object"]

    for key in TOP_LEVEL_REQUIRED:
        if key not in document:
            problems.append(f"missing required top-level key: {key}")

    verdict = document.get("verdict")
    if verdict is not None and verdict not in VALID_VERDICTS:
        problems.append(
            f"verdict must be one of {sorted(VALID_VERDICTS)}, got {verdict!r}"
        )

    findings = document.get("findings")
    if findings is not None and not isinstance(findings, list):
        problems.append("findings must be a list")
    elif isinstance(findings, list):
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                problems.append(f"findings[{index}] must be an object")
                continue
            for key in FINDING_REQUIRED:
                if key not in finding:
                    hint = ""
                    if key == "proposed_fix" and "fix" in finding:
                        hint = " (found 'fix' — the required field is 'proposed_fix')"
                    problems.append(f"findings[{index}]: missing {key}{hint}")
                elif not _nonempty_string(finding[key]):
                    problems.append(
                        f"findings[{index}]: {key} must be a non-empty string"
                    )
            severity = finding.get("severity")
            if severity is not None and severity not in VALID_SEVERITIES:
                problems.append(
                    f"findings[{index}]: severity must be one of "
                    f"{sorted(VALID_SEVERITIES)}, got {severity!r}"
                )

    checks = document.get("checks_run")
    if checks is not None and not isinstance(checks, list):
        problems.append("checks_run must be a list")
    elif isinstance(checks, list):
        for index, check in enumerate(checks):
            if not isinstance(check, dict):
                problems.append(f"checks_run[{index}] must be an object")
                continue
            for key in CHECK_REQUIRED:
                if key not in check:
                    problems.append(f"checks_run[{index}]: missing {key}")
            if "exit_code" in check and not isinstance(check["exit_code"], int):
                problems.append(f"checks_run[{index}]: exit_code must be an integer")

    lenses = document.get("lenses")
    if lenses is not None:
        if not isinstance(lenses, dict) or not lenses:
            problems.append("lenses must be a non-empty object keyed by lens name")
        else:
            for name, lens in lenses.items():
                if not isinstance(lens, dict):
                    problems.append(f"lenses[{name!r}] must be an object")
                    continue
                ids = lens.get("finding_ids")
                justification = lens.get("justification")
                has_ids = isinstance(ids, list) and bool(ids)
                if not has_ids and not _nonempty_string(justification):
                    problems.append(
                        f"lenses[{name!r}] needs a non-empty finding_ids list "
                        "or a non-empty justification"
                    )

    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <verdict.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"verdict file not found: {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as error:
        print(f"invalid JSON in {path}: {error}", file=sys.stderr)
        return 1

    problems = validate(document)
    if problems:
        print(f"{path}: {len(problems)} problem(s) — this verdict would FAIL the gate:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"{path}: OK — satisfies the review verdict gate's required shape.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
