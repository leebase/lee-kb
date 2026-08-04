"""Evidence selection tests over the governed retrieve() surface."""

from datetime import datetime, timezone

import pytest

from lee_kb.answer_evidence import (
    SelectionOmissionReason,
    select_evidence,
)
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
    Trust,
    compute_content_hash,
)
from lee_kb.governance import retrieve
from lee_kb.repository import SQLiteRepository

SOURCE_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
SYNC_TIME = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
RETRIEVAL_TIME = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
PRINCIPAL = Principal("lee")


@pytest.fixture
def repository(tmp_path):
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as instance:
        yield instance


def add_source(
    repository,
    name: str,
    chunks: tuple[str, ...],
    *,
    authority: Authority = Authority.DERIVED,
    trust: Trust = Trust.CURATED,
) -> KnowledgeItem:
    item_id = KnowledgeItemId("local_files", name)
    locator = SourceLocator(
        connector_id="local_files",
        uri=f"file:///knowledge/{name}",
        label=name,
    )
    item = KnowledgeItem(
        item_id=item_id,
        project=DEFAULT_PROJECT,
        source_locator=locator,
        document_type=DocumentType.MARKDOWN,
        content_hash=compute_content_hash("\n".join(chunks)),
        source_timestamp=SOURCE_TIME,
        sync_timestamp=SYNC_TIME,
        permissions=PermissionSet(owner=PRINCIPAL.principal_id),
        title=name,
        authority=authority,
        trust=trust,
    )
    projected_chunks = tuple(
        Chunk(
            chunk_id=ChunkId(
                item_id=item_id,
                chunk_ordinal=ordinal,
                content_hash=compute_content_hash(text),
            ),
            project=DEFAULT_PROJECT,
            text=text,
            chunker_id=MARKDOWN_CHUNKER_ID,
        )
        for ordinal, text in enumerate(chunks)
    )
    repository.sync_item(item, projected_chunks)
    return item


def governed_bundle(repository, query: str, *, top_k: int = 10):
    return retrieve(
        repository,
        query,
        principal=PRINCIPAL,
        project=DEFAULT_PROJECT,
        top_k=top_k,
        clock=lambda: RETRIEVAL_TIME,
    )


def test_later_chunks_that_add_no_source_diversity_are_omitted(repository) -> None:
    add_source(
        repository,
        "policy.md",
        (
            "retention policy is ninety days",
            "retention policy implementation details",
            "retention policy appendix",
        ),
    )
    bundle = governed_bundle(repository, "retention policy")

    selection = select_evidence(bundle)

    assert len(bundle.evidence) == 3
    assert len(selection.selected) == 1
    assert len(selection.selected) < len(bundle.evidence)
    assert {item.reason for item in selection.omitted} == {
        SelectionOmissionReason.REDUNDANT_SAME_SOURCE
    }


def test_every_omitted_item_is_recorded_with_a_reason(repository) -> None:
    add_source(repository, "strong.md", ("alpha beta gamma delta decision",))
    add_source(repository, "weak.md", ("alpha unrelated note",))
    bundle = governed_bundle(repository, "alpha beta gamma delta")

    selection = select_evidence(bundle, relevance_threshold=0.5)

    accounted = {item.chunk_id for item in selection.selected} | {
        item.chunk_id for item in selection.omitted
    }
    assert accounted == {item.chunk_id for item in bundle.evidence}
    assert len(accounted) == len(selection.selected) + len(selection.omitted)
    weak_omission = next(
        item
        for item in selection.omitted
        if item.evidence.item_id.source_object_id == "weak.md"
    )
    assert weak_omission.reason is SelectionOmissionReason.BELOW_RELEVANCE_THRESHOLD
    assert "below threshold" in weak_omission.detail


def test_selection_is_deterministic_for_the_same_governed_bundle(repository) -> None:
    add_source(repository, "a.md", ("deterministic evidence", "deterministic detail"))
    add_source(repository, "b.md", ("deterministic second source",))
    bundle = governed_bundle(repository, "deterministic evidence")

    first = select_evidence(bundle)
    second = select_evidence(bundle)

    assert first == second
    assert tuple(item.chunk_id for item in first.selected) == tuple(
        item.chunk_id for item in second.selected
    )


def test_one_source_cannot_dominate_when_another_source_is_available(
    repository,
) -> None:
    add_source(
        repository,
        "a-dominant.md",
        tuple(f"launch status detail {index}" for index in range(5)),
    )
    add_source(repository, "z-independent.md", ("launch status independent report",))
    bundle = governed_bundle(repository, "launch status")

    selection = select_evidence(bundle)

    selected_sources = {item.item_id for item in selection.selected}
    assert len(bundle.evidence) == 6
    assert len(selection.selected) == 2
    assert len(selected_sources) == 2
    assert (
        max(
            sum(item.item_id == source for item in selection.selected)
            for source in selected_sources
        )
        == 1
    )


def test_selected_evidence_preserves_complete_provenance(repository) -> None:
    item = add_source(
        repository,
        "canonical.md",
        ("governed answer provenance",),
        authority=Authority.CANONICAL,
        trust=Trust.HUMAN_AUTHORED,
    )
    bundle = governed_bundle(repository, "governed answer provenance")

    selected = select_evidence(bundle).selected[0]

    assert selected.item_id == item.item_id
    assert selected.chunk_id == bundle.evidence[0].chunk_id
    assert selected.content_hash == selected.chunk_id.content_hash
    assert selected.citation.source_locator == item.source_locator
    assert selected.citation.authority is Authority.CANONICAL
    assert selected.citation.trust is Trust.HUMAN_AUTHORED
    assert selected.source_timestamp == SOURCE_TIME
    assert selected.sync_timestamp == SYNC_TIME


def test_selector_rejects_candidates_not_from_governed_retrieve() -> None:
    with pytest.raises(TypeError, match="EvidenceBundle"):
        select_evidence(())


def test_all_mechanical_omission_reasons_are_explicit() -> None:
    assert {reason.value for reason in SelectionOmissionReason} == {
        "below_relevance_threshold",
        "redundant_same_source",
        "outside_requested_project",
    }
