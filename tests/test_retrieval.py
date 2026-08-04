"""Deterministic chunking and lexical evidence tests."""

from datetime import datetime, timezone

import pytest

from lee_kb.chunking import chunk_document, chunk_markdown, chunk_plain_text
from lee_kb.contracts import (
    DEFAULT_PROJECT,
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
from lee_kb.retrieval import LEXICAL_RETRIEVER

SOURCE_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
SYNC_TIME = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
RETRIEVAL_TIME = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def repository(tmp_path):
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as instance:
        yield instance


def sync_markdown(
    repository,
    source_object_id: str,
    text: str,
    *,
    source_timestamp: datetime = SOURCE_TIME,
) -> KnowledgeItem:
    item_id = KnowledgeItemId("local_files", source_object_id)
    item = KnowledgeItem(
        item_id=item_id,
        project=DEFAULT_PROJECT,
        source_locator=SourceLocator(
            connector_id="local_files",
            uri=f"file:///knowledge/{source_object_id}",
            label=source_object_id,
        ),
        document_type=DocumentType.MARKDOWN,
        content_hash=compute_content_hash(text),
        source_timestamp=source_timestamp,
        sync_timestamp=SYNC_TIME,
        permissions=PermissionSet(owner="lee"),
        title=source_object_id,
    )
    chunks = chunk_document(
        text,
        item_id=item_id,
        project=DEFAULT_PROJECT,
        document_type=DocumentType.MARKDOWN,
    )
    repository.sync_item(item, chunks)
    return item


def retrieve_as_lee(repository, query: str, *, top_k: int = 10):
    """Exercise the one governed evidence surface as the owning principal."""
    return retrieve(
        repository,
        query,
        principal=Principal("lee"),
        project=DEFAULT_PROJECT,
        top_k=top_k,
        clock=lambda: RETRIEVAL_TIME,
    )


def test_exact_token_query_returns_expected_chunk_with_original_citation(
    repository,
) -> None:
    sync_markdown(
        repository,
        "architecture.md",
        "# Storage\n\nThe projection is disposable.\n\n# Ranking\n\n"
        "Rare token zebraflux identifies this section.",
    )

    bundle = retrieve_as_lee(repository, "zebraflux")

    assert len(bundle.evidence) == 1
    assert bundle.evidence[0].citation.heading == "Ranking"
    assert bundle.evidence[0].citation.source_locator.uri == (
        "file:///knowledge/architecture.md"
    )
    assert bundle.citations == (bundle.evidence[0].citation,)


def test_bm25_ranking_is_repeatable_and_breaks_ties_by_recency_then_id(
    repository,
) -> None:
    sync_markdown(repository, "z-old.md", "repeatable token")
    sync_markdown(
        repository,
        "z-new.md",
        "repeatable token",
        source_timestamp=datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc),
    )
    sync_markdown(
        repository,
        "a-new.md",
        "repeatable token",
        source_timestamp=datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc),
    )
    runs = [
        tuple(
            str(item.chunk_id)
            for item in retrieve_as_lee(repository, "repeatable").evidence
        )
        for _ in range(3)
    ]

    assert runs[0] == runs[1] == runs[2]
    assert [item.split(":", 1)[1].split("#", 1)[0] for item in runs[0]] == [
        "a-new.md",
        "z-new.md",
        "z-old.md",
    ]


def test_every_evidence_row_has_a_one_based_lexical_rank(repository) -> None:
    sync_markdown(repository, "one.md", "ranktoken alpha")
    sync_markdown(repository, "two.md", "ranktoken beta")

    bundle = retrieve_as_lee(repository, "ranktoken")

    assert [item.fused_rank for item in bundle.evidence] == [1, 2]
    assert [item.retriever_ranks[0].rank for item in bundle.evidence] == [1, 2]
    assert all(
        item.retriever_ranks[0].retriever == LEXICAL_RETRIEVER
        and item.retriever_ranks[0].score is not None
        for item in bundle.evidence
    )


def test_source_sync_and_retrieval_freshness_are_present(repository) -> None:
    item = sync_markdown(repository, "fresh.md", "freshness triplet")

    bundle = retrieve_as_lee(repository, "freshness")

    evidence = bundle.evidence[0]
    assert evidence.source_timestamp == item.source_timestamp
    assert evidence.sync_timestamp == item.sync_timestamp
    assert bundle.retrieval_timestamp == RETRIEVAL_TIME
    assert bundle.receipts[0].retrieval_timestamp == RETRIEVAL_TIME
    assert bundle.freshness.oldest_sync_timestamp == SYNC_TIME
    assert bundle.freshness.newest_source_timestamp == SOURCE_TIME


def test_empty_result_set_returns_an_empty_fresh_bundle(repository) -> None:
    sync_markdown(repository, "notes.md", "known vocabulary")

    bundle = retrieve_as_lee(repository, "missingtoken")

    assert bundle.evidence == ()
    assert bundle.citations == ()
    assert bundle.receipts == ()
    assert bundle.freshness.requirement_satisfied is True
    assert bundle.freshness.oldest_sync_timestamp is None


def test_chunking_is_heading_aware_and_deterministic() -> None:
    item_id = KnowledgeItemId("local_files", "repeated.md")
    text = "Intro.\n\n# Repeat\n\nFirst.\n\n# Repeat\n\nSecond."

    first = chunk_markdown(text, item_id=item_id, project=DEFAULT_PROJECT)
    second = chunk_markdown(text, item_id=item_id, project=DEFAULT_PROJECT)

    assert first == second
    assert [chunk.chunk_id.chunk_ordinal for chunk in first] == [0, 1, 2]
    assert [chunk.heading for chunk in first] == [None, "Repeat", "Repeat"]
    assert [chunk.occurrence for chunk in first] == [0, 0, 1]


def test_plain_text_fallback_chunks_by_paragraph() -> None:
    item_id = KnowledgeItemId("local_files", "notes.txt")

    chunks = chunk_plain_text(
        "First paragraph.\nStill first.\n\nSecond paragraph.",
        item_id=item_id,
        project=DEFAULT_PROJECT,
    )

    assert [chunk.text for chunk in chunks] == [
        "First paragraph.\nStill first.",
        "Second paragraph.",
    ]
    assert [chunk.chunk_id.chunk_ordinal for chunk in chunks] == [0, 1]
