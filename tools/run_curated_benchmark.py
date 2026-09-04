"""Run the public-safe curated FAQ benchmark.

The runner deliberately keeps FAQ questions and source pointers in memory.  Its
only serialized output is aggregate benchmark data plus opaque, sequential case
identifiers.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from statistics import mean

from lee_kb.answer import answer
from lee_kb.answer_contracts import AbsenceKind, Answer
from lee_kb.contracts import (
    DEFAULT_PROJECT,
    FreshnessRequirement,
    MetadataFilters,
    Principal,
)
from lee_kb.governance import (
    PermissionEvaluator,
    RetrievalProviderError,
    StaleEvidenceError,
    retrieve,
)
from lee_kb.repository import SQLiteRepository

STABLE_SECTIONS = ("Commercial", "Strategy", "Product verticals", "Platform")
_SOURCE_RE = re.compile(r"^\s*Source:\s*(.*?)\s*$", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_QUESTION_RE = re.compile(r"^\s*\*\*(.+?)\*\*\s*$")


@dataclass(frozen=True, slots=True)
class FAQCase:
    """An in-memory FAQ benchmark case; never serialize this object."""

    question: str
    expected_source_id: str
    section: str
    ordinal: int

    @property
    def source_id(self) -> str:
        """Compatibility alias for callers that call the pointer a source ID."""
        return self.expected_source_id

    @property
    def case_id(self) -> str:
        return f"case-{self.ordinal:03d}"


def _clean_heading(value: str) -> str:
    return value.strip().rstrip("#").strip()


def strip_source_fragment(pointer: str) -> str:
    """Remove a markdown fragment and presentation wrappers from a pointer."""
    value = pointer.strip()
    if (value.startswith("`") and value.endswith("`")) or (
        value.startswith("<") and value.endswith(">")
    ):
        value = value[1:-1].strip()
    return value.split("#", 1)[0].strip()


def parse_faq(text: str) -> tuple[FAQCase, ...]:
    """Parse bold question lines and their subsequent ``Source:`` pointers.

    Parsing is source-order preserving.  A question is retained only when a
    source pointer appears before the next question or heading.
    """
    if not isinstance(text, str):
        raise TypeError("FAQ text must be a string")
    parsed: list[tuple[str, str, str]] = []
    section = ""
    question: str | None = None
    source_id: str | None = None

    def finish() -> None:
        nonlocal question, source_id
        if question is not None and source_id:
            parsed.append((question, source_id, section))
        question = None
        source_id = None

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            finish()
            if len(heading.group(1)) <= 2:
                section = _clean_heading(heading.group(2))
            continue
        question_match = _QUESTION_RE.match(line)
        if question_match:
            finish()
            question = question_match.group(1).strip()
            if question.lower().startswith("question:"):
                question = question[len("question:") :].strip()
            continue
        source_match = _SOURCE_RE.match(line)
        if source_match and question is not None and source_id is None:
            source_id = strip_source_fragment(source_match.group(1))
    finish()

    return tuple(
        FAQCase(question=q, expected_source_id=s, section=heading, ordinal=i)
        for i, (q, s, heading) in enumerate(parsed, start=1)
    )


def select_stable_cases(
    cases_or_text: Iterable[FAQCase] | str,
    sections: Iterable[str] = STABLE_SECTIONS,
) -> tuple[FAQCase, ...]:
    """Select the named current FAQ sections while retaining source order."""
    cases = (
        parse_faq(cases_or_text)
        if isinstance(cases_or_text, str)
        else tuple(cases_or_text)
    )
    selected_names = {name.strip().casefold() for name in sections}
    selected = [case for case in cases if case.section.casefold() in selected_names]
    return tuple(
        FAQCase(
            question=case.question,
            expected_source_id=case.expected_source_id,
            section=case.section,
            ordinal=i,
        )
        for i, case in enumerate(selected, start=1)
    )


def select_current_stable_sections(text: str) -> tuple[FAQCase, ...]:
    """Parse and select the four stable benchmark sections."""
    return select_stable_cases(parse_faq(text))


def source_matches(expected_source_id: str, candidate: object) -> bool:
    """Match an expected pointer to a citation's source-object ID.

    The source locator itself is intentionally ignored: governance identity is
    the ``KnowledgeItemId.source_object_id`` carried by a citation.
    """
    expected = strip_source_fragment(expected_source_id)
    actual: object = candidate
    for attribute in ("citation", "item_id"):
        if hasattr(actual, attribute):
            actual = getattr(actual, attribute)
    if hasattr(actual, "source_object_id"):
        actual = getattr(actual, "source_object_id")
    if not isinstance(actual, str):
        return False
    return actual == expected


def copy_sqlite_database(source: str | Path, destination: str | Path) -> None:
    """Copy a SQLite database using SQLite's backup API, without mutation."""
    source_connection = sqlite3.connect(
        f"file:{Path(source).resolve()}?mode=ro", uri=True
    )
    destination_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


# Short alias useful to operators and tests.
backup_sqlite = copy_sqlite_database


def projection_counts(database: str | Path) -> dict[str, int]:
    """Return disclosure-safe counts from a copied projection."""
    connection = sqlite3.connect(str(database))
    try:
        item_count = int(
            connection.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
        )
        live_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM knowledge_items WHERE tombstone = 0"
            ).fetchone()[0]
        )
        chunk_count = int(
            connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        )
        return {
            "knowledge_items": item_count,
            "live_items": live_count,
            "chunks": chunk_count,
        }
    finally:
        connection.close()


def projection_source_ids(database: str | Path) -> frozenset[str]:
    """Read source-object IDs from the copied, live projection."""
    connection = sqlite3.connect(str(database))
    try:
        rows = connection.execute(
            "SELECT source_object_id FROM knowledge_items WHERE tombstone = 0"
        )
        return frozenset(str(row[0]) for row in rows)
    finally:
        connection.close()


def _latency_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean_ms": None, "min_ms": None, "max_ms": None}
    return {
        "count": len(values),
        "mean_ms": round(mean(values), 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
    }


def _rate(hits: int, eligible: int) -> dict[str, int | float]:
    return {
        "hits": hits,
        "eligible": eligible,
        "rate": round(hits / eligible, 4) if eligible else 0.0,
    }


def _citation_source_hit(answer_result: Answer, expected: str) -> bool:
    return any(
        source_matches(expected, citation)
        for claim in answer_result.claims
        for citation in claim.citations
    )


def build_report(
    *,
    projection: Mapping[str, int],
    selected_cases: int,
    source_present: int,
    source_missing: int,
    retrieve_hit_at_1: int,
    retrieve_hit_at_10: int,
    retrieve_eligible: int,
    retrieve_failures: int,
    answer_source_citation_hits: int,
    answer_eligible: int,
    answer_failures: int,
    claim_total: int,
    conflict_total: int,
    retrieve_latency_ms: list[float],
    answer_latency_ms: list[float],
    case_ids: Iterable[str],
    controls: Mapping[str, str],
) -> dict[str, object]:
    """Build the only report shape emitted by the CLI."""
    return {
        "schema_version": 1,
        "projection": {key: int(value) for key, value in projection.items()},
        "cases": {
            "selected": int(selected_cases),
            "source_present": int(source_present),
            "source_missing": int(source_missing),
            "case_ids": list(case_ids),
        },
        "retrieval": {
            "hit_at_1": _rate(retrieve_hit_at_1, retrieve_eligible),
            "hit_at_10": _rate(retrieve_hit_at_10, retrieve_eligible),
            "failures": int(retrieve_failures),
        },
        "answer": {
            "source_citation_hits": _rate(answer_source_citation_hits, answer_eligible),
            "failures": int(answer_failures),
            "claim_total": int(claim_total),
            "conflict_total": int(conflict_total),
        },
        "latency_ms": {
            "retrieve": _latency_summary(retrieve_latency_ms),
            "answer": _latency_summary(answer_latency_ms),
        },
        "controls": dict(controls),
    }


class _DenyAll(PermissionEvaluator):
    def is_permitted(self, item: object, principal: Principal) -> bool:
        return False


def run_controls(
    repository: SQLiteRepository,
    control_question: str,
    *,
    principal_id: str,
    project: str = DEFAULT_PROJECT,
) -> dict[str, str]:
    """Exercise no-evidence, authorization, and strict-stale controls."""
    principal = Principal(principal_id)
    statuses: dict[str, str] = {}

    try:
        no_evidence = answer(
            repository,
            control_question,
            principal=principal,
            project=project,
            filters=MetadataFilters(connectors=("__benchmark_no_evidence__",)),
        )
        statuses["no_evidence"] = (
            "not_found"
            if no_evidence.absence is not None
            and no_evidence.absence.kind is AbsenceKind.NOT_FOUND
            else "unexpected"
        )
    except StaleEvidenceError:
        statuses["no_evidence"] = "stale"
    except RetrievalProviderError:
        statuses["no_evidence"] = "provider_failed"
    except Exception:
        statuses["no_evidence"] = "error"

    try:
        unauthorized = answer(
            repository,
            control_question,
            principal=Principal("__benchmark_unauthorized__"),
            project=project,
            permission_evaluator=_DenyAll(),
        )
        statuses["unauthorized"] = (
            "inaccessible"
            if unauthorized.absence is not None
            and unauthorized.absence.kind is AbsenceKind.INACCESSIBLE
            else "unexpected"
        )
    except StaleEvidenceError:
        statuses["unauthorized"] = "stale"
    except RetrievalProviderError:
        statuses["unauthorized"] = "provider_failed"
    except Exception:
        statuses["unauthorized"] = "error"

    try:
        retrieve(
            repository,
            control_question,
            principal=principal,
            project=project,
            freshness=FreshnessRequirement(
                max_staleness=timedelta(0), fail_on_stale=True
            ),
        )
        statuses["strict_stale"] = "not_stale"
    except StaleEvidenceError:
        statuses["strict_stale"] = "stale"
    except RetrievalProviderError:
        statuses["strict_stale"] = "provider_failed"
    except Exception:
        statuses["strict_stale"] = "error"
    return statuses


def run_benchmark(
    workspace_root: str | Path,
    database: str | Path,
    *,
    principal_id: str = "lee@leebase.com",
    project: str = DEFAULT_PROJECT,
) -> dict[str, object]:
    """Copy, query, and aggregate the stable FAQ benchmark."""
    faq_path = Path(workspace_root) / "knowledge" / "faq.md"
    cases = select_current_stable_sections(faq_path.read_text(encoding="utf-8"))
    if not cases:
        raise ValueError("no stable FAQ cases")
    principal = Principal(principal_id)

    retrieve_latencies: list[float] = []
    answer_latencies: list[float] = []
    source_ids: frozenset[str]
    source_present = 0
    source_missing = 0
    retrieve_eligible = 0
    retrieve_hit_1 = 0
    retrieve_hit_10 = 0
    retrieve_failures = 0
    answer_eligible = 0
    answer_hits = 0
    answer_failures = 0
    claim_total = 0
    conflict_total = 0

    with tempfile.TemporaryDirectory(
        prefix="curated-benchmark-"
    ) as temporary_directory:
        copied_database = Path(temporary_directory) / "projection.sqlite"
        copy_sqlite_database(database, copied_database)
        counts = projection_counts(copied_database)
        source_ids = projection_source_ids(copied_database)
        with SQLiteRepository(copied_database) as repository:
            for case in cases:
                present = case.expected_source_id in source_ids
                source_present += int(present)
                source_missing += int(not present)
                retrieve_started = time.perf_counter()
                try:
                    bundle = retrieve(
                        repository,
                        case.question,
                        principal=principal,
                        project=project,
                        top_k=10,
                    )
                    evidence = bundle.evidence
                    if present:
                        retrieve_eligible += 1
                        ranks = [
                            evidence_item.fused_rank
                            for evidence_item in evidence
                            if source_matches(
                                case.expected_source_id, evidence_item.citation
                            )
                        ]
                        retrieve_hit_1 += int(any(rank == 1 for rank in ranks))
                        retrieve_hit_10 += int(any(rank <= 10 for rank in ranks))
                except Exception:
                    retrieve_failures += 1
                    # Status is intentionally not serialized per case; a failed
                    # case cannot become a retrieval hit.
                    pass
                finally:
                    retrieve_latencies.append(
                        (time.perf_counter() - retrieve_started) * 1000
                    )

                answer_started = time.perf_counter()
                try:
                    result = answer(
                        repository,
                        case.question,
                        principal=principal,
                        project=project,
                        top_k=10,
                    )
                    claim_total += len(result.claims)
                    conflict_total += len(result.conflicts)
                    if present:
                        answer_eligible += 1
                        answer_hits += int(
                            _citation_source_hit(result, case.expected_source_id)
                        )
                except Exception:
                    answer_failures += 1
                    pass
                finally:
                    answer_latencies.append(
                        (time.perf_counter() - answer_started) * 1000
                    )

            controls = run_controls(
                repository,
                cases[0].question,
                principal_id=principal_id,
                project=project,
            )

    return build_report(
        projection=counts,
        selected_cases=len(cases),
        source_present=source_present,
        source_missing=source_missing,
        retrieve_hit_at_1=retrieve_hit_1,
        retrieve_hit_at_10=retrieve_hit_10,
        retrieve_eligible=retrieve_eligible,
        retrieve_failures=retrieve_failures,
        answer_source_citation_hits=answer_hits,
        answer_eligible=answer_eligible,
        answer_failures=answer_failures,
        claim_total=claim_total,
        conflict_total=conflict_total,
        retrieve_latency_ms=retrieve_latencies,
        answer_latency_ms=answer_latencies,
        case_ids=(case.case_id for case in cases),
        controls=controls,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the curated FAQ benchmark")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--principal", default="lee@leebase.com")
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    args = parser.parse_args(argv)
    try:
        report = run_benchmark(
            args.workspace_root,
            args.database,
            principal_id=args.principal,
            project=args.project,
        )
    except Exception:
        # Never expose exception text, source paths, or provider details.
        print(json.dumps({"schema_version": 1, "status": "error"}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
