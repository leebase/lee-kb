"""Offline golden-corpus harness for the governed lexical baseline."""

from __future__ import annotations

import math
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lee_kb.chunking import chunk_document
from lee_kb.connectors.local_files import LocalFilesConnector, RootConfig
from lee_kb.contracts import ChangeType, KnowledgeItem, KnowledgeItemId, Principal
from lee_kb.governance import retrieve
from lee_kb.repository import SQLiteRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = Path(__file__).with_name("corpus.toml")
BASELINE_DOC_PATH = REPO_ROOT / "docs" / "golden-baseline.md"
SYNC_TIME = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
RETRIEVAL_TIME = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
DEFAULT_PROJECT = "default"
# One percentage point / 0.01 MRR. Loose enough to absorb the doc's rounding
# to one decimal place, tight enough that a single question's rank moving by
# one place (let alone the "every answer from rank 1 to rank 10" regression
# S1-R-16 exists to catch) crosses it in either direction.
METRIC_TOLERANCE = 0.01
SCOPE_CONTROL_PROJECT = "scope-control"
EXPECTED_CATEGORIES = {
    "operational_status",
    "project_management",
    "architecture",
    "job_search",
    "knowledge_discovery",
}
POSITIVE_SOURCES = (
    "product-definition.md",
    "architecture.md",
    "project-plan.md",
    "research/employee-zero-kb-reference.md",
    "backlog/schema.md",
)


def _load_cases() -> tuple[dict[str, object], ...]:
    with CORPUS_PATH.open("rb") as handle:
        return tuple(tomllib.load(handle)["cases"])


CASES = _load_cases()
POSITIVE_CASES = tuple(case for case in CASES if case["kind"] == "positive")
NEGATIVE_CASES = tuple(case for case in CASES if case["kind"] != "positive")


def _connector() -> LocalFilesConnector:
    return LocalFilesConnector(
        (
            RootConfig(
                name="repo",
                path=REPO_ROOT,
                owner="lee",
                include=POSITIVE_SOURCES,
                project=DEFAULT_PROJECT,
            ),
            RootConfig(
                name="scope-control",
                path=REPO_ROOT,
                owner="lee",
                include=("docs/project-onboarding.md",),
                project=SCOPE_CONTROL_PROJECT,
            ),
        ),
        connector_id="golden_local_files",
    )


def _sync(connector: LocalFilesConnector, repository: SQLiteRepository) -> None:
    discovered = connector.discover()
    discovered_by_id = {item.source_object_id: item for item in discovered}

    for change in connector.list_changes():
        assert change.change_type is ChangeType.CREATED
        document = connector.fetch(change.source_object_id)
        item_id = KnowledgeItemId(connector.connector_id, document.source_object_id)
        item = KnowledgeItem(
            item_id=item_id,
            project=document.project,
            source_locator=document.source_locator,
            document_type=document.document_type,
            content_hash=document.content_hash,
            source_timestamp=document.source_timestamp,
            sync_timestamp=SYNC_TIME,
            permissions=connector.permissions(document.source_object_id),
            title=document.title,
            authority=document.authority,
            trust=document.trust,
        )
        chunks = chunk_document(
            document.content,
            item_id=item_id,
            project=document.project,
            document_type=document.document_type,
        )
        repository.sync_item(item, chunks)

    assert len(discovered_by_id) == len(POSITIVE_SOURCES) + 1
    assert connector.checkpoint(discovered)


@pytest.fixture(scope="module")
def repository(tmp_path_factory):
    database = tmp_path_factory.mktemp("golden-corpus") / "knowledge.sqlite"
    with SQLiteRepository(database) as instance:
        _sync(_connector(), instance)
        yield instance


def _run(repository: SQLiteRepository, case: dict[str, object]):
    return retrieve(
        repository,
        str(case["question"]),
        principal=Principal(str(case["principal"])),
        project=str(case["project"]),
        top_k=10,
        clock=lambda: RETRIEVAL_TIME,
    )


def _case_id(case: dict[str, object]) -> str:
    return str(case["id"])


def test_corpus_shape_and_seed_provenance() -> None:
    first_line = CORPUS_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == (
        "# Seed corpus drawn from repo documents; Lee curates the final twenty "
        "from real Chief of Staff usage."
    )
    assert len(POSITIVE_CASES) == 20
    assert len(NEGATIVE_CASES) == 3
    assert {case["category"] for case in POSITIVE_CASES} == EXPECTED_CATEGORIES
    assert all(
        sum(case["category"] == category for case in POSITIVE_CASES) == 4
        for category in EXPECTED_CATEGORIES
    )
    assert {case["kind"] for case in NEGATIVE_CASES} == {
        "no_evidence",
        "out_of_scope",
        "unauthorized",
    }
    assert len({_case_id(case) for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", POSITIVE_CASES, ids=_case_id)
def test_positive_question_returns_expected_citation_and_token(
    repository, case
) -> None:
    bundle = _run(repository, case)
    expected_source = str(case["expected_source"])
    expected_token = str(case["expected_evidence_token"])
    matching_evidence = tuple(
        evidence
        for evidence in bundle.evidence
        if evidence.citation.source_locator.label == expected_source
        and expected_token.casefold() in evidence.text.casefold()
    )

    assert matching_evidence, (
        f"{case['id']} did not cite {expected_source!r} with token "
        f"{expected_token!r}"
    )
    assert bundle.citations == tuple(item.citation for item in bundle.evidence)
    assert len(bundle.receipts) == len(bundle.evidence)
    assert all(receipt.principal == Principal("lee") for receipt in bundle.receipts)
    assert bundle.freshness.requirement_satisfied is True
    assert bundle.retrieval_timestamp == RETRIEVAL_TIME


def test_no_evidence_returns_an_auditable_empty_bundle(repository) -> None:
    case = next(case for case in NEGATIVE_CASES if case["kind"] == "no_evidence")
    bundle = _run(repository, case)

    assert bundle.evidence == ()
    assert bundle.citations == ()
    # RetrievalReceipt is evidence-shaped in Sprint 1, so an empty result has
    # no fabricated item receipt. The retained request and timestamp audit the
    # empty governed query itself.
    assert bundle.receipts == ()
    assert bundle.request.query == case["question"]
    assert bundle.request.principal == Principal("lee")
    assert bundle.retrieval_timestamp == RETRIEVAL_TIME


def test_evidence_outside_the_queried_project_is_excluded(repository) -> None:
    case = next(case for case in NEGATIVE_CASES if case["kind"] == "out_of_scope")
    outside_hits = repository.search(
        str(case["question"]),
        project=str(case["evidence_project"]),
        limit=10,
    )
    assert outside_hits
    assert {hit.item.source_locator.label for hit in outside_hits} == {
        case["evidence_source"]
    }

    bundle = _run(repository, case)
    assert bundle.evidence == ()
    assert bundle.citations == ()
    assert bundle.receipts == ()
    assert bundle.denied_count == 0


def test_unauthorized_principal_is_denied_before_evidence_assembly(repository) -> None:
    case = next(case for case in NEGATIVE_CASES if case["kind"] == "unauthorized")
    ungoverned_hits = repository.search(
        str(case["question"]), project=str(case["project"]), limit=10
    )
    assert any(
        hit.item.source_locator.label == case["evidence_source"]
        for hit in ungoverned_hits
    )

    bundle = _run(repository, case)
    assert bundle.evidence == ()
    assert bundle.citations == ()
    assert bundle.receipts == ()
    assert bundle.denied_count >= 1


def _first_matching_rank(
    bundle, expected_source: str, expected_token: str
) -> int | None:
    """Rank (1-based) of the first evidence item citing expected_source/token, else
    None."""
    for rank, evidence in enumerate(bundle.evidence, start=1):
        if (
            evidence.citation.source_locator.label == expected_source
            and expected_token.casefold() in evidence.text.casefold()
        ):
            return rank
    return None


def _parse_recorded_baseline() -> dict[str, float]:
    """Read hit-at-1, hit-at-10, and MRR from docs/golden-baseline.md.

    Reads the gate from the document instead of duplicating it as a second
    hardcoded copy, so the two cannot silently drift apart.
    """
    text = BASELINE_DOC_PATH.read_text(encoding="utf-8")
    hit_at_1 = re.search(
        r"Expected-citation hit rate at 1:\s*\*\*\d+/\d+ \(([\d.]+)%\)\*\*", text
    )
    hit_at_10 = re.search(
        r"Expected-citation hit rate at 10:\s*\*\*\d+/\d+ \(([\d.]+)%\)\*\*", text
    )
    mrr = re.search(r"Mean reciprocal rank:\s*\*\*([\d.]+)\*\*", text)
    assert hit_at_1 and hit_at_10 and mrr, (
        "Could not parse the Baseline section of docs/golden-baseline.md; "
        "update the parser in test_golden_corpus.py if its wording changed."
    )
    return {
        "hit_at_1": float(hit_at_1.group(1)) / 100.0,
        "hit_at_10": float(hit_at_10.group(1)) / 100.0,
        "mrr": float(mrr.group(1)),
    }


def test_recorded_baseline_metrics_are_enforced_by_the_harness(repository) -> None:
    """Guard S1-R-16: hit-at-1, hit-at-10, and MRR must match the recorded gate.

    Computes the metrics over the golden corpus through the governed
    retrieve() surface, using the same hit definition documented in
    docs/golden-baseline.md (declared source + evidence token present in the
    governed top-10; rank is the first matching citation's position). A
    ranking regression that pushed every answer to the back of the result
    set would fail this test even though the existing per-question
    assertions -- which only check "somewhere in the top 10" -- would stay
    green. The comparison is symmetric (math.isclose), so an unrecorded
    *improvement* beyond tolerance fails just as loudly as a regression:
    docs/golden-baseline.md must be the thing that changes, not just the code.
    """
    ranks: list[int] = []
    for case in POSITIVE_CASES:
        bundle = _run(repository, case)
        rank = _first_matching_rank(
            bundle,
            str(case["expected_source"]),
            str(case["expected_evidence_token"]),
        )
        assert rank is not None, f"{case['id']} lost its top-10 citation entirely"
        ranks.append(rank)

    total = len(POSITIVE_CASES)
    observed = {
        "hit_at_1": sum(1 for rank in ranks if rank == 1) / total,
        "hit_at_10": sum(1 for rank in ranks if rank <= 10) / total,
        "mrr": sum(1.0 / rank for rank in ranks) / total,
    }
    recorded = _parse_recorded_baseline()

    for metric, observed_value in observed.items():
        recorded_value = recorded[metric]
        assert math.isclose(observed_value, recorded_value, abs_tol=METRIC_TOLERANCE), (
            f"{metric} drifted from the docs/golden-baseline.md gate: "
            f"observed {observed_value:.4f}, recorded {recorded_value:.4f} "
            f"(tolerance {METRIC_TOLERANCE}). If retrieval regressed, fix it; "
            "if it genuinely improved, re-record docs/golden-baseline.md."
        )
