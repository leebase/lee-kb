"""Offline golden-corpus harness for the governed lexical baseline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import tomllib

from lee_kb.chunking import chunk_document
from lee_kb.connectors.local_files import LocalFilesConnector, RootConfig
from lee_kb.contracts import ChangeType, KnowledgeItem, KnowledgeItemId, Principal
from lee_kb.governance import retrieve
from lee_kb.repository import SQLiteRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = Path(__file__).with_name("corpus.toml")
SYNC_TIME = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
RETRIEVAL_TIME = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
DEFAULT_PROJECT = "default"
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
