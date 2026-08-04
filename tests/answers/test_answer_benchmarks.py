"""Permanent offline regressions for the seven governed-answer families.

Every document in this module is synthetic.  The harness writes distinct source
roots under pytest's temporary directory, discovers and fetches them through the
local-file connector, projects connector output into temporary SQLite, and asks
questions only through the public :func:`lee_kb.answer.answer` surface.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from lee_kb.answer import answer
from lee_kb.answer_contracts import Confidence, OmissionReason
from lee_kb.chunking import chunk_document
from lee_kb.connectors.local_files import LocalFilesConnector, RootConfig
from lee_kb.contracts import (
    Authority,
    ChangeType,
    KnowledgeItem,
    KnowledgeItemId,
    Principal,
)
from lee_kb.repository import SQLiteRepository

PROJECT = "answer-benchmarks"
PRINCIPAL = Principal("lee")
CONNECTOR_ID = "benchmark_local_files"
SOURCE_TIME = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
SYNC_TIME = datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc)
ANSWER_TIME = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SourceFixture:
    root: str
    filename: str
    content: str
    authority: Authority = Authority.DERIVED


SOURCES = (
    SourceFixture(
        "naming-repository",
        "naming-decision.md",
        """# Documentation Steward Naming Decision

The full official name is Documentation Steward Coordination Service.
Its identifiers are DSCS and steward-coordinator. The naming decision assigns
the steward-manifest work package to the Documentation Steward Coordination
Service.
""",
    ),
    SourceFixture(
        "gate-repository",
        "blocking-gate.md",
        """# Documentation Steward Blocking Gate

The documentation steward blocking gate remains blocked until the
steward-manifest work described by the naming decision is implemented and the
DSCS identifier is registered.
""",
    ),
    SourceFixture(
        "status-repository",
        "current-status.md",
        """# Documentation Steward Current Status

The current documentation steward status says naming is approved, DSCS
registration is in progress, and the blocking gate remains blocked.
""",
    ),
    SourceFixture(
        "absence-repository",
        "orbital-archive-decision.md",
        """# Orbital Archive Decision

The planning record names the Orbital Archive dossier. The Orbital Archive
dossier was never created.
""",
    ),
    SourceFixture(
        "canonical-operations",
        "meridian-channel.md",
        """# Meridian Deployment Channel

The deployment channel for Meridian is enabled.
""",
        authority=Authority.CANONICAL,
    ),
    SourceFixture(
        "field-operations",
        "meridian-field-note.md",
        """# Meridian Deployment Channel

The deployment channel for Meridian is disabled.
""",
        authority=Authority.DERIVED,
    ),
    SourceFixture(
        "duplicate-repository",
        "harbor-readiness.md",
        """# Harbor Readiness Summary

Harbor readiness requires the cobalt checklist.

# Harbor Readiness Detail

Harbor readiness requires the cobalt checklist.

# Harbor Readiness Appendix

Harbor readiness requires the cobalt checklist.
""",
    ),
    SourceFixture(
        "independent-audit",
        "harbor-audit.md",
        """# Harbor Readiness Audit

The independent audit confirms that harbor readiness requires the cobalt
checklist.
""",
    ),
    SourceFixture(
        "legacy-harbor-notes",
        "legacy-manifest.md",
        """# Legacy Harbor Notes

The legacy harbor manifest does not exist.
""",
    ),
    SourceFixture(
        "canonical-navigation",
        "solstice-route.md",
        """# Solstice Navigation Route

The navigation route for Solstice uses the eastern corridor.
""",
        authority=Authority.CANONICAL,
    ),
    SourceFixture(
        "derived-navigation-a",
        "solstice-route.md",
        """# Solstice Navigation Route

The navigation route for Solstice uses the western corridor.
""",
    ),
    SourceFixture(
        "derived-navigation-b",
        "solstice-route.md",
        """# Solstice Navigation Route

The navigation route for Solstice uses the western corridor.
""",
    ),
)

SAME_AUTHORITY_SOURCES = (
    SourceFixture(
        "same-authority-a",
        "equinox-channel-enabled.md",
        """# Equinox Deployment Channel

The deployment channel for Equinox is enabled.
""",
    ),
    SourceFixture(
        "same-authority-b",
        "equinox-channel-disabled.md",
        """# Equinox Deployment Channel

The deployment channel for Equinox is disabled.
""",
    ),
)


@pytest.fixture(scope="module")
def benchmark_repository(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("answer-benchmarks")
    roots = _write_sources(workspace, SOURCES)
    connector = LocalFilesConnector(tuple(roots), connector_id=CONNECTOR_ID)
    database = workspace / "knowledge.sqlite"
    with SQLiteRepository(database) as repository:
        _sync(connector, repository, expected_sources=len(SOURCES))
        yield repository


@pytest.fixture(scope="module")
def same_authority_repository(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("same-authority-conflict")
    roots = _write_sources(workspace, SAME_AUTHORITY_SOURCES)
    connector = LocalFilesConnector(
        tuple(roots), connector_id=f"{CONNECTOR_ID}_same_authority"
    )
    database = workspace / "knowledge.sqlite"
    with SQLiteRepository(database) as repository:
        _sync(
            connector,
            repository,
            expected_sources=len(SAME_AUTHORITY_SOURCES),
        )
        yield repository


def _write_sources(workspace, sources: tuple[SourceFixture, ...]):
    roots = []
    for fixture in sources:
        root_path = workspace / fixture.root
        root_path.mkdir()
        document_path = root_path / fixture.filename
        document_path.write_text(fixture.content, encoding="utf-8")
        timestamp = SOURCE_TIME.timestamp()
        os.utime(document_path, (timestamp, timestamp))
        roots.append(
            RootConfig(
                name=fixture.root,
                path=root_path,
                owner=PRINCIPAL.principal_id,
                include=("*.md",),
                authority=fixture.authority,
                project=PROJECT,
            )
        )
    return roots


def _sync(
    connector: LocalFilesConnector,
    repository: SQLiteRepository,
    *,
    expected_sources: int,
) -> None:
    """Project connector output through the same deterministic offline pattern."""
    discovered = connector.discover()
    changes = connector.list_changes()
    assert len(discovered) == expected_sources
    assert len(changes) == expected_sources

    for change in changes:
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

    assert connector.checkpoint(discovered)


def _ask(repository: SQLiteRepository, question: str, **options):
    top_k = options.pop("top_k", 20)
    return answer(
        repository,
        question,
        principal=PRINCIPAL,
        project=PROJECT,
        top_k=top_k,
        clock=lambda: ANSWER_TIME,
        **options,
    )


DOCUMENTATION_STEWARD_QUESTION = (
    "What is the documentation steward official name and identifier, what "
    "blocks its gate, and what is its current status?"
)


def test_documentation_steward_shape_combines_three_roots(
    benchmark_repository,
) -> None:
    result = _ask(benchmark_repository, DOCUMENTATION_STEWARD_QUESTION)
    answer_text = " ".join(claim.text for claim in result.claims)

    assert "Documentation Steward Coordination Service" in answer_text
    assert "steward-manifest" in answer_text
    assert "registration is in progress" in answer_text
    assert {
        citation.item_id.source_object_id.split(":", 1)[0]
        for claim in result.claims
        for citation in claim.citations
    } >= {"naming-repository", "gate-repository", "status-repository"}


def test_fuzzy_partial_name_finds_the_full_official_name(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "What is the full official name of documentation steward?",
    )

    matching = tuple(
        claim
        for claim in result.claims
        if "Documentation Steward Coordination Service" in claim.text
    )
    assert matching
    assert any(
        citation.item_id.source_object_id == "naming-repository:naming-decision.md"
        for claim in matching
        for citation in claim.citations
    )


def test_cross_repository_synthesis_attributes_at_least_three_roots(
    benchmark_repository,
) -> None:
    result = _ask(benchmark_repository, DOCUMENTATION_STEWARD_QUESTION)
    attributed_roots = {
        citation.item_id.source_object_id.split(":", 1)[0]
        for claim in result.claims
        for citation in claim.citations
    }

    assert len(attributed_roots) >= 3
    assert (
        len(
            {
                citation.source_locator.uri
                for claim in result.claims
                for citation in claim.citations
            }
        )
        >= 3
    )


def test_authoritative_absence_is_a_cited_evidenced_not_found(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "Was the Orbital Archive dossier created?",
    )

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert "never created" in claim.text
    assert claim.confidence is Confidence.DIRECTLY_EVIDENCED
    assert len(claim.citations) == 1
    assert (
        claim.citations[0].item_id.source_object_id
        == "absence-repository:orbital-archive-decision.md"
    )
    # A cited negative statement is the evidenced NOT_FOUND path. It is not a
    # silent empty-result absence, which would have no claims or citations.
    assert result.absence is None
    assert result.confidence is not Confidence.UNKNOWN


def test_conflicting_evidence_reports_both_sides_without_a_winner(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "Is the deployment channel for Meridian enabled or disabled?",
    )

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert not hasattr(conflict, "winner")
    assert {
        citation.item_id.source_object_id
        for claim in conflict.claims
        for citation in claim.citations
    } == {
        "canonical-operations:meridian-channel.md",
        "field-operations:meridian-field-note.md",
    }
    assert (
        "enabled" in conflict.left.claim.text or "enabled" in conflict.right.claim.text
    )
    assert (
        "disabled" in conflict.left.claim.text
        or "disabled" in conflict.right.claim.text
    )
    assert set(conflict.claims) <= set(result.claims)


def test_same_authority_value_word_contradiction_stays_as_two_claims(
    same_authority_repository,
) -> None:
    result = _ask(
        same_authority_repository,
        "Is the deployment channel for Equinox enabled or disabled?",
    )

    assert len(result.conflicts) == 1
    assert len(result.claims) == 2
    assert all(len(claim.citations) == 1 for claim in result.claims)
    assert {
        citation.item_id.source_object_id
        for claim in result.claims
        for citation in claim.citations
    } == {
        "same-authority-a:equinox-channel-enabled.md",
        "same-authority-b:equinox-channel-disabled.md",
    }
    claim_texts = tuple(claim.text.casefold() for claim in result.claims)
    assert any("enabled" in text and "disabled" not in text for text in claim_texts)
    assert any("disabled" in text and "enabled" not in text for text in claim_texts)


def test_unresponsive_absence_shaped_sentence_does_not_replace_answer(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "What does harbor readiness require?",
    )

    assert result.absence is None
    assert any("cobalt checklist" in claim.text for claim in result.claims)
    assert {
        citation.item_id.source_object_id
        for claim in result.claims
        for citation in claim.citations
    } >= {
        "duplicate-repository:harbor-readiness.md",
        "independent-audit:harbor-audit.md",
    }


def test_three_source_conflict_cites_each_chunk_in_exactly_one_claim(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "Which corridor does the Solstice navigation route use?",
        top_k=3,
    )

    source_ids = {
        "canonical-navigation:solstice-route.md",
        "derived-navigation-a:solstice-route.md",
        "derived-navigation-b:solstice-route.md",
    }
    citation_counts = Counter(
        citation.chunk_id
        for claim in result.claims
        for citation in claim.citations
        if citation.item_id.source_object_id in source_ids
    )
    assert len(result.claims) == 3
    assert all(len(claim.citations) == 1 for claim in result.claims)
    assert not any(
        "eastern" in claim.text.casefold() and "western" in claim.text.casefold()
        for claim in result.claims
    )
    assert len(citation_counts) == 3
    assert set(citation_counts.values()) == {1}


def test_duplicate_source_cannot_dominate_or_repeat_its_claim(
    benchmark_repository,
) -> None:
    result = _ask(
        benchmark_repository,
        "What does harbor readiness require from the cobalt checklist?",
    )
    duplicate_source = "duplicate-repository:harbor-readiness.md"
    duplicate_citations = tuple(
        citation
        for claim in result.claims
        for citation in claim.citations
        if citation.item_id.source_object_id == duplicate_source
    )

    assert len(duplicate_citations) == 1
    assert (
        sum(
            "Harbor readiness requires the cobalt checklist" in claim.text
            for claim in result.claims
        )
        == 1
    )
    redundant = tuple(
        omitted
        for omitted in result.evidence_omitted
        if omitted.evidence.item_id.source_object_id == duplicate_source
    )
    assert len(redundant) == 2
    assert {omitted.reason for omitted in redundant} == {OmissionReason.REDUNDANT}
    assert all(omitted.detail for omitted in redundant)


PROVENANCE_QUESTIONS = (
    DOCUMENTATION_STEWARD_QUESTION,
    "What is the full official name of documentation steward?",
    "Was the Orbital Archive dossier created?",
    "Is the deployment channel for Meridian enabled or disabled?",
    "What does harbor readiness require from the cobalt checklist?",
)


@pytest.mark.parametrize("question", PROVENANCE_QUESTIONS)
def test_every_positive_claim_has_resolvable_provenance_and_accounted_omissions(
    benchmark_repository,
    question,
) -> None:
    result = _ask(benchmark_repository, question)

    assert result.claims
    for claim in result.claims:
        assert claim.confidence is not Confidence.UNKNOWN
        assert claim.citations
        for citation in claim.citations:
            item = benchmark_repository.get_item(citation.item_id)
            assert item is not None
            assert citation.source_locator == item.source_locator
            assert any(
                chunk.chunk_id == citation.chunk_id
                for chunk in benchmark_repository.get_chunks(citation.item_id)
            )

    assert {receipt.chunk_id for receipt in result.receipt_ids} == {
        evidence.chunk_id for evidence in result.evidence_used
    } | {omitted.chunk_id for omitted in result.evidence_omitted}
    if len(result.receipt_ids) > len(result.evidence_used):
        assert result.evidence_omitted
        assert all(
            omitted.reason in OmissionReason and omitted.detail
            for omitted in result.evidence_omitted
        )


def test_benchmark_corpus_is_entirely_synthetic() -> None:
    assert len(SOURCES) == 12
    assert {fixture.root for fixture in SOURCES} == {
        "naming-repository",
        "gate-repository",
        "status-repository",
        "absence-repository",
        "canonical-operations",
        "field-operations",
        "duplicate-repository",
        "independent-audit",
        "legacy-harbor-notes",
        "canonical-navigation",
        "derived-navigation-a",
        "derived-navigation-b",
    }
