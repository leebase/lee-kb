"""Conflict identification keeps both governed, cited sides."""

from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.answer import answer
from lee_kb.answer_conflict import detect_conflicts, retain_conflict_sides
from lee_kb.answer_contracts import Answer, Claim, Confidence, EvidenceRef, Side
from lee_kb.answer_evidence import select_evidence
from lee_kb.chunking import MARKDOWN_CHUNKER_ID
from lee_kb.contracts import (
    DEFAULT_PROJECT,
    Authority,
    Chunk,
    ChunkId,
    DocumentType,
    KnowledgeItem,
    KnowledgeItemId,
    PermissionSet,
    Principal,
    SourceLocator,
    compute_content_hash,
)
from lee_kb.governance import retrieve
from lee_kb.repository import SQLiteRepository

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
LEE = Principal("lee")


@pytest.fixture
def repository(tmp_path):
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as instance:
        yield instance


def add_source(
    repository,
    name: str,
    text: str,
    *,
    authority: Authority,
    source_timestamp: datetime,
) -> None:
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
            source_timestamp=source_timestamp,
            sync_timestamp=NOW - timedelta(hours=1),
            permissions=PermissionSet(owner=LEE.principal_id),
            title=name,
            authority=authority,
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


def selection_for(repository, query: str):
    bundle = retrieve(
        repository,
        query,
        principal=LEE,
        project=DEFAULT_PROJECT,
        clock=lambda: NOW,
    )
    return bundle, select_evidence(bundle)


def test_differing_declared_authority_reports_both_cited_sides(repository) -> None:
    add_source(
        repository,
        "canonical.md",
        "Retention policy is 90 days.",
        authority=Authority.CANONICAL,
        source_timestamp=NOW - timedelta(days=300),
    )
    add_source(
        repository,
        "derived.md",
        "Retention policy is 30 days.",
        authority=Authority.DERIVED,
        source_timestamp=NOW,
    )
    _, selection = selection_for(repository, "retention policy days")

    conflicts = detect_conflicts(selection)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert {claim.text for claim in conflict.claims} == {
        "Retention policy is 90 days.",
        "Retention policy is 30 days.",
    }
    assert {
        citation.source_locator.label
        for claim in conflict.claims
        for citation in claim.citations
    } == {
        "canonical.md",
        "derived.md",
    }
    assert conflict.more_authoritative is not Side.NEITHER
    authoritative = (
        conflict.left if conflict.more_authoritative is Side.LEFT else conflict.right
    )
    assert authoritative.authority is Authority.CANONICAL
    assert not hasattr(conflict, "winner")


def test_newer_explicit_supersession_is_an_ordering_signal_only(repository) -> None:
    add_source(
        repository,
        "old-status.md",
        "Launch status is approved.",
        authority=Authority.DERIVED,
        source_timestamp=NOW - timedelta(days=20),
    )
    add_source(
        repository,
        "new-status.md",
        "Launch status is blocked; this supersedes the earlier launch status.",
        authority=Authority.DERIVED,
        source_timestamp=NOW,
    )
    _, selection = selection_for(repository, "launch status")

    conflicts = detect_conflicts(selection)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.newer is not Side.NEITHER
    assert conflict.more_authoritative is Side.NEITHER
    newer = conflict.left if conflict.newer is Side.LEFT else conflict.right
    assert "supersedes" in newer.claim.text
    assert not hasattr(conflict, "resolved")


def test_detected_conflict_retains_both_sides_through_answer_assembly(
    repository,
) -> None:
    add_source(
        repository,
        "canonical.md",
        "Retention policy is 90 days.",
        authority=Authority.CANONICAL,
        source_timestamp=NOW - timedelta(days=300),
    )
    add_source(
        repository,
        "derived.md",
        "Retention policy is 30 days.",
        authority=Authority.DERIVED,
        source_timestamp=NOW,
    )
    bundle, selection = selection_for(repository, "retention policy days")
    prematurely_merged = Claim(
        text="The sources disagree about the retention policy.",
        citations=tuple(evidence.citation for evidence in selection.selected),
        confidence=Confidence.SYNTHESIZED,
    )
    conflicts = detect_conflicts(selection, claims=(prematurely_merged,))

    claims = retain_conflict_sides((conflicts[0].left.claim,), conflicts)
    answer = Answer(
        question=bundle.request.query,
        principal=bundle.request.principal,
        project=bundle.request.project,
        claims=claims,
        confidence=Confidence.DIRECTLY_EVIDENCED,
        receipt_ids=selection.receipt_ids,
        evidence_used=tuple(
            EvidenceRef(
                chunk_id=evidence.chunk_id,
                source_locator=evidence.citation.source_locator,
            )
            for evidence in selection.selected
        ),
        evidence_omitted=selection.answer_omissions,
        conflicts=conflicts,
    )

    assert answer.conflicts == conflicts
    assert len(answer.claims) == 2
    assert set(answer.claims) == set(conflicts[0].claims)
    assert set(answer.cited_chunk_ids) == {
        evidence.chunk_id for evidence in selection.selected
    }
    assert {receipt.chunk_id for receipt in answer.receipt_ids} == {
        receipt.chunk_id for receipt in bundle.receipts
    }


def test_noncompeting_same_authority_statements_do_not_create_a_conflict(
    repository,
) -> None:
    add_source(
        repository,
        "overview.md",
        "Retention policy has an owner.",
        authority=Authority.DERIVED,
        source_timestamp=NOW - timedelta(days=1),
    )
    add_source(
        repository,
        "implementation.md",
        "Retention policy has an implementation guide.",
        authority=Authority.DERIVED,
        source_timestamp=NOW,
    )
    _, selection = selection_for(repository, "retention policy")

    assert detect_conflicts(selection) == ()


def test_negation_in_another_clause_does_not_hide_a_conflict(repository) -> None:
    add_source(
        repository,
        "encrypted.md",
        "The Nimbus archive is encrypted and no external link is present.",
        authority=Authority.DERIVED,
        source_timestamp=NOW - timedelta(days=1),
    )
    add_source(
        repository,
        "not-encrypted.md",
        "The Nimbus archive is not encrypted and no external link is present.",
        authority=Authority.DERIVED,
        source_timestamp=NOW,
    )

    result = answer(
        repository,
        "Is the Nimbus archive encrypted?",
        principal=LEE,
        project=DEFAULT_PROJECT,
        clock=lambda: NOW,
    )

    assert len(result.conflicts) == 1
    assert len(result.claims) == 2


def test_unrelated_negative_elaboration_does_not_create_a_conflict(repository) -> None:
    add_source(
        repository,
        "required.md",
        "The Fennel gate is required.",
        authority=Authority.DERIVED,
        source_timestamp=NOW - timedelta(days=1),
    )
    add_source(
        repository,
        "required-owner.md",
        "The Fennel gate is required and no owner is assigned.",
        authority=Authority.DERIVED,
        source_timestamp=NOW,
    )

    result = answer(
        repository,
        "What is the Fennel gate requirement?",
        principal=LEE,
        project=DEFAULT_PROJECT,
        clock=lambda: NOW,
    )

    assert result.conflicts == ()


def test_detect_conflicts_rejects_an_ungoverned_iterable() -> None:
    with pytest.raises(TypeError, match="EvidenceSelection"):
        detect_conflicts(())
