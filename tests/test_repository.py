"""Behavioral tests for the SQLite latest-state repository."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.contracts import (
    DEFAULT_PROJECT,
    ChangeType,
    Chunk,
    ChunkId,
    DocumentType,
    KnowledgeItem,
    KnowledgeItemId,
    PermissionSet,
    Principal,
    RetrievalReceipt,
    SourceLocator,
    compute_content_hash,
)
from lee_kb.repository import SQLiteRepository

SOURCE_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
SYNC_TIME = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)


def make_projection(
    text: str = "The SQLite projection is disposable and source-backed.",
    *,
    sync_timestamp: datetime = SYNC_TIME,
) -> tuple[KnowledgeItem, tuple[Chunk, ...]]:
    item_id = KnowledgeItemId("local_files", "architecture.md")
    item = KnowledgeItem(
        item_id=item_id,
        project=DEFAULT_PROJECT,
        source_locator=SourceLocator(
            connector_id="local_files",
            uri="file:///workspace/architecture.md",
            label="architecture.md",
        ),
        document_type=DocumentType.MARKDOWN,
        content_hash=compute_content_hash(text),
        source_timestamp=SOURCE_TIME,
        sync_timestamp=sync_timestamp,
        permissions=PermissionSet(owner="lee"),
        title="Architecture",
        tags=("architecture", "persistence"),
    )
    chunk = Chunk(
        chunk_id=ChunkId(item_id, 0, compute_content_hash(text)),
        project=DEFAULT_PROJECT,
        text=text,
        chunker_id="markdown-atx-v1:1",
        heading="Persistence",
    )
    return item, (chunk,)


@pytest.fixture
def repository(tmp_path):
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as instance:
        yield instance


def test_syncing_same_document_twice_is_duplicate_free(repository) -> None:
    item, chunks = make_projection()

    created = repository.sync_item(item, chunks, cursor="cursor-1")
    unchanged = repository.sync_item(
        replace(item, sync_timestamp=SYNC_TIME + timedelta(minutes=1)),
        chunks,
        cursor="cursor-2",
    )

    assert created is not None and created.change_type is ChangeType.CREATED
    assert unchanged is None
    assert repository.get_item(item.item_id) is not None
    assert repository.get_chunks(item.item_id) == chunks
    assert len(repository.journal_entries(item.item_id)) == 1
    assert repository.get_connector_cursor("local_files") == "cursor-2"


def test_changed_document_replaces_projection_and_journals_previous_hash(
    repository,
) -> None:
    original, original_chunks = make_projection()
    repository.sync_item(original, original_chunks)
    changed, changed_chunks = make_projection(
        "The latest projection is rebuilt from authoritative sources.",
        sync_timestamp=SYNC_TIME + timedelta(hours=1),
    )

    entry = repository.sync_item(changed, changed_chunks)

    assert entry is not None
    assert entry.change_type is ChangeType.UPDATED
    assert entry.previous_content_hash == original.content_hash
    assert entry.content_hash == changed.content_hash
    assert repository.get_item(changed.item_id) == changed
    assert repository.get_chunks(changed.item_id) == changed_chunks
    assert (
        repository.search("authoritative sources", project=DEFAULT_PROJECT)[0].chunk
        == changed_chunks[0]
    )
    assert repository.search("disposable", project=DEFAULT_PROJECT) == ()


def test_tombstone_hides_search_result_but_receipt_remains_resolvable(
    repository,
) -> None:
    item, chunks = make_projection()
    repository.sync_item(item, chunks)
    receipt = RetrievalReceipt(
        knowledge_item_id=item.item_id,
        chunk_id=chunks[0].chunk_id,
        content_hash=chunks[0].content_hash,
        source_locator=item.source_locator,
        retrieval_timestamp=SYNC_TIME + timedelta(minutes=5),
        principal=Principal("lee"),
        project=DEFAULT_PROJECT,
        query="disposable projection",
    )
    receipt_id = repository.record_receipt(receipt)

    deleted = repository.tombstone_item(
        item.item_id,
        sync_timestamp=SYNC_TIME + timedelta(hours=2),
        cursor="cursor-after-delete",
    )

    assert deleted is not None and deleted.change_type is ChangeType.DELETED
    assert repository.get_item(item.item_id).tombstone is True
    assert repository.search("disposable", project=DEFAULT_PROJECT) == ()
    assert repository.get_receipt(receipt_id) == receipt
    assert repository.get_connector_cursor("local_files") == "cursor-after-delete"


def test_schema_version_is_stored_and_readable(repository) -> None:
    assert repository.schema_version == 1
    assert repository.get_schema_version() == 1


def test_cursor_does_not_advance_when_ingestion_fails(repository) -> None:
    item, chunks = make_projection()
    repository.sync_item(item, chunks, cursor="safe-cursor")
    bad_chunk = replace(chunks[0], project="wrong-project")

    with pytest.raises(ValueError, match="project"):
        repository.sync_item(item, (bad_chunk,), cursor="unsafe-cursor")

    assert repository.get_connector_cursor("local_files") == "safe-cursor"
