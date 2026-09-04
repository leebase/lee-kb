"""Behavioral tests for the SQLite latest-state repository."""

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.contracts import (
    DEFAULT_PROJECT,
    SCHEMA_VERSION,
    ChangeType,
    Chunk,
    ChunkId,
    DocumentType,
    KnowledgeItem,
    KnowledgeItemId,
    MemoryConfidence,
    MemoryType,
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
    assert repository.schema_version == SCHEMA_VERSION
    assert repository.get_schema_version() == SCHEMA_VERSION


def test_existing_projection_can_open_without_schema_initialization(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "knowledge.sqlite"
    with SQLiteRepository(database) as repository:
        item, chunks = make_projection()
        repository.sync_item(item, chunks)

    def unexpected_schema_initialization(_repository) -> None:
        raise AssertionError("existing retrieval projection attempted schema writes")

    monkeypatch.setattr(
        SQLiteRepository, "_create_schema", unexpected_schema_initialization
    )
    with SQLiteRepository(database, initialize_schema=False) as existing:
        hits = existing.search("disposable", project=DEFAULT_PROJECT)

    assert hits[0].item.item_id == item.item_id


def test_existing_projection_open_refuses_schema_that_requires_migration(
    tmp_path,
) -> None:
    database = tmp_path / "knowledge.sqlite"
    with SQLiteRepository(database):
        pass
    connection = sqlite3.connect(database)
    connection.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="requires migration"):
        SQLiteRepository(database, initialize_schema=False)

    connection = sqlite3.connect(database)
    stored_version = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    connection.close()
    assert stored_version == "2"


def test_schema_v1_migrates_to_query_audit_events(tmp_path) -> None:
    database = tmp_path / "knowledge.sqlite"
    with SQLiteRepository(database) as repository:
        item, chunks = make_projection()
        repository.sync_item(item, chunks)

    connection = sqlite3.connect(database)
    connection.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    connection.execute("DROP TABLE retrieval_audit_events")
    connection.execute("UPDATE knowledge_items SET schema_version = 1")
    connection.commit()
    connection.close()

    with SQLiteRepository(database) as migrated:
        assert migrated.schema_version == SCHEMA_VERSION
        assert migrated.get_item(item.item_id).schema_version == SCHEMA_VERSION
        assert migrated.list_retrieval_events() == ()


def test_schema_v2_migrates_additively_with_null_memory_columns(tmp_path) -> None:
    """A v2 projection (no memory columns) opens cleanly under v3.

    Existing rows survive untouched, gain NULL memory columns via
    ``_ensure_column``, and get their per-row ``schema_version`` bumped --
    mirroring the v1 migration test above.
    """
    database = tmp_path / "knowledge.sqlite"
    with SQLiteRepository(database) as repository:
        item, chunks = make_projection()
        repository.sync_item(item, chunks)

    connection = sqlite3.connect(database)
    connection.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    connection.execute("UPDATE knowledge_items SET schema_version = 2")
    connection.commit()
    connection.close()

    with SQLiteRepository(database) as migrated:
        assert migrated.schema_version == SCHEMA_VERSION
        restored = migrated.get_item(item.item_id)
        assert restored.schema_version == SCHEMA_VERSION
        assert restored.memory_type is None
        assert restored.importance is None
        # And the memory columns are genuinely writable post-migration.
        memory_item = make_projection(text="Lee prefers concise status updates.")[0]
        memory_item = replace(
            memory_item,
            item_id=KnowledgeItemId("local_files", "memory/preferences/status.md"),
            memory_type=MemoryType.PREFERENCE,
            subject_principal="lee",
            memory_confidence=MemoryConfidence.STATED,
            importance=0.8,
        )
        chunk = replace(
            make_projection()[1][0],
            chunk_id=ChunkId(
                item_id=memory_item.item_id,
                chunk_ordinal=0,
                content_hash=compute_content_hash("Lee prefers concise status updates."),
            ),
            text="Lee prefers concise status updates.",
        )
        migrated.sync_item(memory_item, (chunk,))
        reloaded = migrated.get_item(memory_item.item_id)
        assert reloaded.memory_type is MemoryType.PREFERENCE
        assert reloaded.subject_principal == "lee"
        assert reloaded.memory_confidence is MemoryConfidence.STATED
        assert reloaded.importance == 0.8


def test_cursor_does_not_advance_when_ingestion_fails(repository) -> None:
    item, chunks = make_projection()
    repository.sync_item(item, chunks, cursor="safe-cursor")
    bad_chunk = replace(chunks[0], project="wrong-project")

    with pytest.raises(ValueError, match="project"):
        repository.sync_item(item, (bad_chunk,), cursor="unsafe-cursor")

    assert repository.get_connector_cursor("local_files") == "safe-cursor"


def test_cursor_only_advance_persists_empty_delta_without_projection_rows(
    repository,
) -> None:
    item, chunks = make_projection()
    repository.sync_item(item, chunks, cursor="cursor-before")

    repository.advance_cursor(
        "local_files",
        "cursor-after-empty-delta",
        updated_at=SYNC_TIME + timedelta(minutes=1),
        project="personal",
    )

    assert repository.get_connector_cursor("local_files") == "cursor-after-empty-delta"
    assert repository.get_item(item.item_id) == item
    assert repository.get_chunks(item.item_id) == chunks
    assert len(repository.journal_entries(item.item_id)) == 1


def test_cursor_only_advance_rolls_back_when_cursor_write_fails(
    repository, monkeypatch
) -> None:
    item, chunks = make_projection()
    repository.sync_item(item, chunks, cursor="cursor-before")
    original_upsert = repository._upsert_cursor

    def fail_after_write(connector_id, cursor, updated_at):
        original_upsert(connector_id, cursor, updated_at)
        raise RuntimeError("simulated cursor commit failure")

    monkeypatch.setattr(repository, "_upsert_cursor", fail_after_write)

    with pytest.raises(RuntimeError, match="simulated cursor commit failure"):
        repository.advance_cursor(
            "local_files",
            "cursor-should-rollback",
            updated_at=SYNC_TIME + timedelta(minutes=1),
            project="empty-project",
        )

    assert repository.get_connector_cursor("local_files") == "cursor-before"
    assert not repository.has_synchronized_project("empty-project")


def test_external_round_rolls_back_projection_and_cursor_together(
    repository, monkeypatch
) -> None:
    first, first_chunks = make_projection("first external item")
    second_base, second_base_chunks = make_projection("second external item")
    second_id = KnowledgeItemId("local_files", "second.md")
    second = replace(
        second_base,
        item_id=second_id,
        source_locator=SourceLocator(
            connector_id="local_files",
            uri="file:///workspace/second.md",
            label="second.md",
        ),
    )
    second_chunks = (
        replace(
            second_base_chunks[0],
            chunk_id=ChunkId(
                second_id,
                0,
                second_base_chunks[0].content_hash,
            ),
        ),
    )
    original_upsert = repository._upsert_item
    calls = 0

    def fail_on_second(item):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated external round failure")
        original_upsert(item)

    monkeypatch.setattr(repository, "_upsert_item", fail_on_second)

    with pytest.raises(RuntimeError, match="external round failure"):
        repository.apply_external_round(
            [
                (first.item_id, first, first_chunks),
                (second.item_id, second, second_chunks),
            ],
            cursor="cursor-after-round",
            updated_at=SYNC_TIME,
        )

    assert repository.get_item(first.item_id) is None
    assert repository.get_item(second.item_id) is None
    assert repository.get_connector_cursor("local_files") is None
