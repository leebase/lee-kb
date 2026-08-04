"""Authoritative absence classification over governed retrieval results."""

from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.answer_absence import AbsenceBasis, classify_absence
from lee_kb.answer_contracts import AbsenceKind, Confidence
from lee_kb.chunking import MARKDOWN_CHUNKER_ID
from lee_kb.contracts import (
    DEFAULT_PROJECT,
    Chunk,
    ChunkId,
    DocumentType,
    FreshnessRequirement,
    KnowledgeItem,
    KnowledgeItemId,
    PermissionSet,
    Principal,
    SourceLocator,
    compute_content_hash,
)
from lee_kb.governance import retrieve
from lee_kb.repository import SQLiteRepository

SOURCE_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
SYNC_TIME = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
RETRIEVAL_TIME = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
LEE = Principal("lee")


@pytest.fixture
def repository(tmp_path):
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as instance:
        yield instance


def add_source(repository, name: str, text: str, *, owner: str = "lee") -> None:
    item_id = KnowledgeItemId("local_files", name)
    content_hash = compute_content_hash(text)
    repository.sync_item(
        KnowledgeItem(
            item_id=item_id,
            project=DEFAULT_PROJECT,
            source_locator=SourceLocator(
                "local_files", f"file:///knowledge/{name}", name
            ),
            document_type=DocumentType.MARKDOWN,
            content_hash=content_hash,
            source_timestamp=SOURCE_TIME,
            sync_timestamp=SYNC_TIME,
            permissions=PermissionSet(owner=owner),
            title=name,
        ),
        (
            Chunk(
                chunk_id=ChunkId(item_id, 0, content_hash),
                project=DEFAULT_PROJECT,
                text=text,
                chunker_id=MARKDOWN_CHUNKER_ID,
            ),
        ),
    )


def governed_bundle(repository, query: str, *, freshness=None):
    return retrieve(
        repository,
        query,
        principal=LEE,
        project=DEFAULT_PROJECT,
        freshness=freshness,
        clock=lambda: RETRIEVAL_TIME,
    )


def test_governed_corpus_miss_is_authoritative_not_found(repository) -> None:
    add_source(repository, "known.md", "A synchronized operating policy exists.")

    assessment = classify_absence(governed_bundle(repository, "missing telescope"))

    assert assessment is not None
    assert assessment.kind is AbsenceKind.NOT_FOUND
    assert assessment.basis is AbsenceBasis.SILENCE
    assert assessment.absence.searched_projects == (DEFAULT_PROJECT,)
    assert assessment.confidence is Confidence.UNKNOWN
    assert assessment.citations == ()


def test_denied_match_is_inaccessible_and_never_not_found(repository) -> None:
    add_source(
        repository,
        "restricted.md",
        "The restricted telescope launch plan exists.",
        owner="another-principal",
    )
    bundle = governed_bundle(repository, "restricted telescope launch plan")

    assessment = classify_absence(bundle)

    assert bundle.evidence == ()
    assert bundle.denied_count == 1
    assert assessment is not None
    assert assessment.kind is AbsenceKind.INACCESSIBLE
    assert assessment.kind is not AbsenceKind.NOT_FOUND
    assert assessment.basis is AbsenceBasis.WITHHELD
    assert assessment.absence.withheld_count == 1
    assert assessment.citations == ()
    assert "restricted.md" not in (assessment.absence.detail or "")


def test_project_without_synchronized_content_is_unknown(repository) -> None:
    assessment = classify_absence(
        governed_bundle(repository, "telescope launch plan"),
        project_has_synchronized_content=False,
    )

    assert assessment is not None
    assert assessment.kind is AbsenceKind.UNKNOWN
    assert assessment.basis is AbsenceBasis.UNRESOLVED
    assert "no synchronized content" in (assessment.absence.detail or "")


def test_evidence_stale_beyond_requested_freshness_is_unknown(repository) -> None:
    add_source(repository, "status.md", "Telescope launch status is approved.")
    bundle = governed_bundle(
        repository,
        "telescope launch status",
        freshness=FreshnessRequirement(max_staleness=timedelta(hours=1)),
    )

    assessment = classify_absence(bundle)

    assert bundle.evidence
    assert not bundle.freshness.requirement_satisfied
    assert assessment is not None
    assert assessment.kind is AbsenceKind.UNKNOWN
    assert "freshness" in (assessment.absence.detail or "")


def test_explicit_never_created_statement_is_evidenced_not_found(repository) -> None:
    add_source(
        repository,
        "decision.md",
        (
            "The Atlas name is approved, but this decision does not authorize "
            "creation of an Atlas repository."
        ),
    )
    bundle = governed_bundle(repository, "Where is the Atlas repository?")

    assessment = classify_absence(bundle)

    assert assessment is not None
    assert assessment.kind is AbsenceKind.NOT_FOUND
    assert assessment.basis is AbsenceBasis.EVIDENCED
    assert assessment.is_evidenced
    assert assessment.confidence is Confidence.DIRECTLY_EVIDENCED
    assert assessment.supporting_claim is not None
    assert "does not authorize creation" in assessment.supporting_claim.text
    assert assessment.citations == (bundle.evidence[0].citation,)


def test_released_nonabsence_evidence_is_not_misclassified(repository) -> None:
    add_source(repository, "status.md", "The Atlas repository is active.")

    assessment = classify_absence(
        governed_bundle(repository, "Where is the Atlas repository?")
    )

    assert assessment is None


def test_explicit_absence_is_checked_only_in_selected_evidence(repository) -> None:
    add_source(
        repository,
        "decision.md",
        "The Atlas repository was never created.",
    )
    bundle = governed_bundle(repository, "Was the Atlas repository created?")

    assessment = classify_absence(bundle, selected_evidence=())

    assert bundle.evidence
    assert assessment is None


def test_absence_sentence_must_clear_question_term_coverage(repository) -> None:
    add_source(
        repository,
        "atlas-overview.md",
        (
            "Atlas launch security retention ownership policy overview. "
            "The legacy Atlas manifest does not exist."
        ),
    )
    bundle = governed_bundle(
        repository,
        "What is the Atlas launch security retention ownership policy?",
    )

    assessment = classify_absence(bundle, selected_evidence=bundle.evidence)

    assert bundle.evidence
    assert assessment is None
