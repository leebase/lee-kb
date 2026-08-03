"""Behavioral tests for the local-file connector.

These tests double as the connector's ingestion loop: they call
``list_changes``/``fetch``/``permissions`` the way a future ingestion engine
would, then persist through :class:`SQLiteRepository`, so a scenario that
compiles here also proves the contract methods compose correctly.
"""

from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.connectors.base import ConnectorReadError
from lee_kb.connectors.local_files import LocalFilesConnector
from lee_kb.contracts import (
    DEFAULT_PROJECT,
    ChangeType,
    Chunk,
    ChunkId,
    KnowledgeItem,
    KnowledgeItemId,
    compute_content_hash,
)
from lee_kb.repository import SQLiteRepository

SYNC_TIME = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def write_config(
    config_path,
    source_root,
    *,
    include=("*.md", "*.txt"),
    exclude=(),
    authority="derived",
    trust="curated",
    owner="lee@leebase.com",
) -> None:
    include_toml = ", ".join(f'"{pattern}"' for pattern in include)
    exclude_toml = ", ".join(f'"{pattern}"' for pattern in exclude)
    config_path.write_text(f"""
schema = 1

[roots.notes]
path = "{source_root.as_posix()}"
owner = "{owner}"
include = [{include_toml}]
exclude = [{exclude_toml}]
authority = "{authority}"
trust = "{trust}"
""")


def make_connector(tmp_path, files, **config_kwargs) -> LocalFilesConnector:
    source_root = tmp_path / "source"
    source_root.mkdir()
    for relative, content in files.items():
        path = source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    config_path = tmp_path / "sources.toml"
    write_config(config_path, source_root, **config_kwargs)
    return LocalFilesConnector.from_config(config_path)


def build_item(connector, document, *, sync_timestamp) -> KnowledgeItem:
    item_id = KnowledgeItemId(connector.connector_id, document.source_object_id)
    return KnowledgeItem(
        item_id=item_id,
        project=document.project,
        source_locator=document.source_locator,
        document_type=document.document_type,
        content_hash=document.content_hash,
        source_timestamp=document.source_timestamp,
        sync_timestamp=sync_timestamp,
        permissions=connector.permissions(document.source_object_id),
        title=document.title,
        authority=document.authority,
        trust=document.trust,
    )


def build_chunk(item_id: KnowledgeItemId, document) -> Chunk:
    text = document.content
    return Chunk(
        chunk_id=ChunkId(item_id, 0, compute_content_hash(text)),
        project=document.project,
        text=text,
        chunker_id="whole-document-v1:1",
    )


def sync_all(connector, repository, *, cursor, sync_timestamp) -> str:
    """Apply one incremental sync pass and return the next cursor."""
    for change in connector.list_changes(cursor):
        item_id = KnowledgeItemId(connector.connector_id, change.source_object_id)
        if change.change_type is ChangeType.DELETED:
            repository.tombstone_item(item_id, sync_timestamp=sync_timestamp)
            continue
        document = connector.fetch(change.source_object_id)
        item = build_item(connector, document, sync_timestamp=sync_timestamp)
        repository.sync_item(item, (build_chunk(item_id, document),))
    return connector.checkpoint(connector.discover())


def initial_sync(connector, repository) -> str:
    return sync_all(connector, repository, cursor=None, sync_timestamp=SYNC_TIME)


@pytest.fixture
def repository(tmp_path):
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as instance:
        yield instance


def test_initial_sync_persists_every_discovered_object(tmp_path, repository) -> None:
    connector = make_connector(
        tmp_path,
        {
            "architecture.md": "# Architecture\n\nSource systems stay authoritative.",
            "notes.txt": "Plain notes about the sprint.",
        },
    )

    cursor = initial_sync(connector, repository)

    architecture_id = KnowledgeItemId("local_files", "notes:architecture.md")
    notes_id = KnowledgeItemId("local_files", "notes:notes.txt")
    architecture = repository.get_item(architecture_id)
    notes = repository.get_item(notes_id)

    assert architecture is not None and not architecture.tombstone
    assert notes is not None and not notes.tombstone
    assert architecture.source_locator.uri.startswith("file://")
    assert len(repository.journal_entries()) == 2
    assert {entry.change_type for entry in repository.journal_entries()} == {
        ChangeType.CREATED
    }
    assert cursor  # a non-empty snapshot cursor was produced


def test_noop_resync_journals_nothing(tmp_path, repository) -> None:
    connector = make_connector(
        tmp_path,
        {"architecture.md": "# Architecture\n\nStable content."},
    )
    cursor = initial_sync(connector, repository)

    changes = connector.list_changes(cursor)
    next_cursor = sync_all(
        repository=repository,
        connector=connector,
        cursor=cursor,
        sync_timestamp=SYNC_TIME + timedelta(hours=1),
    )

    assert changes == ()
    assert next_cursor == cursor
    assert len(repository.journal_entries()) == 1


def test_changed_file_is_detected_and_updates_the_projection(
    tmp_path, repository
) -> None:
    connector = make_connector(
        tmp_path,
        {"architecture.md": "# Architecture\n\nOriginal content."},
    )
    cursor = initial_sync(connector, repository)
    item_id = KnowledgeItemId("local_files", "notes:architecture.md")
    original_hash = repository.get_item(item_id).content_hash

    (tmp_path / "source" / "architecture.md").write_text(
        "# Architecture\n\nRevised content after the sprint."
    )
    changes = connector.list_changes(cursor)

    assert len(changes) == 1
    assert changes[0].change_type is ChangeType.UPDATED
    assert changes[0].previous_content_hash == original_hash

    sync_all(
        repository=repository,
        connector=connector,
        cursor=cursor,
        sync_timestamp=SYNC_TIME + timedelta(hours=2),
    )

    updated = repository.get_item(item_id)
    assert updated.content_hash != original_hash
    assert repository.get_chunks(item_id)[0].text == (
        "# Architecture\n\nRevised content after the sprint."
    )
    entries = repository.journal_entries(item_id)
    assert [entry.change_type for entry in entries] == [
        ChangeType.CREATED,
        ChangeType.UPDATED,
    ]


def test_deleted_file_is_detected_and_tombstoned_via_repository(
    tmp_path, repository
) -> None:
    connector = make_connector(
        tmp_path,
        {
            "architecture.md": "# Architecture\n\nKept around.",
            "notes.txt": "Removed later.",
        },
    )
    cursor = initial_sync(connector, repository)
    notes_id = KnowledgeItemId("local_files", "notes:notes.txt")

    (tmp_path / "source" / "notes.txt").unlink()
    changes = connector.list_changes(cursor)

    assert len(changes) == 1
    assert changes[0].change_type is ChangeType.DELETED
    assert changes[0].source_object_id == "notes:notes.txt"

    sync_all(
        repository=repository,
        connector=connector,
        cursor=cursor,
        sync_timestamp=SYNC_TIME + timedelta(hours=3),
    )

    tombstoned = repository.get_item(notes_id)
    assert tombstoned.tombstone is True
    assert repository.search("Removed", project=DEFAULT_PROJECT) == ()
    entries = repository.journal_entries(notes_id)
    assert entries[-1].change_type is ChangeType.DELETED
    with pytest.raises(ConnectorReadError):
        connector.fetch("notes:notes.txt")


def test_include_exclude_and_format_registry_enforce_default_deny(tmp_path) -> None:
    connector = make_connector(
        tmp_path,
        {
            "architecture.md": "included by *.md",
            "notes.txt": "included by *.txt",
            "drafts/todo.md": "excluded by drafts/** even though it matches *.md",
            "config.secret.md": "excluded by *.secret.md",
            "diagram.png": "matches include but has no registered format handler",
            "readme.rst": "matches no include pattern at all",
        },
        include=("*.md", "*.txt", "*.png"),
        exclude=("drafts/**", "*.secret.md"),
    )

    discovered = {obj.source_object_id for obj in connector.discover()}

    assert discovered == {"notes:architecture.md", "notes:notes.txt"}


def test_discover_skips_symlink_whose_target_escapes_the_root(tmp_path) -> None:
    """Discovery and fetch agree on containment (S1-R-10).

    A symlink inside a declared root whose resolved target escapes the root
    is never handed out by discover(), so every discovered object is
    fetchable under _resolve()'s containment rule.
    """
    connector = make_connector(tmp_path, {"inside.md": "inside the root"})
    source_root = tmp_path / "source"
    outside = tmp_path / "outside.md"
    outside.write_text("outside the declared root", encoding="utf-8")
    (source_root / "escape.md").symlink_to(outside)
    (source_root / "broken.md").symlink_to(tmp_path / "no-such-target.md")

    discovered = {obj.source_object_id for obj in connector.discover()}

    assert discovered == {"notes:inside.md"}
    with pytest.raises(ConnectorReadError):
        connector.fetch("notes:escape.md")


def test_sync_pass_skips_unfetchable_object_and_continues(
    tmp_path, repository, monkeypatch
) -> None:
    """One bad object degrades a sync pass instead of ending it (S1-R-10)."""
    from datetime import datetime as _datetime

    from lee_kb.main import _sync_connector

    connector = make_connector(
        tmp_path, {"good.md": "good document", "bad.md": "bad document"}
    )
    real_fetch = connector.fetch

    def flaky_fetch(source_object_id):
        if source_object_id.endswith("bad.md"):
            raise ConnectorReadError("simulated unreadable object")
        return real_fetch(source_object_id)

    monkeypatch.setattr(connector, "fetch", flaky_fetch)

    summary = _sync_connector(
        connector,
        repository,
        root_filter=None,
        sync_timestamp=_datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert summary.created == 1
    assert summary.skipped == 1
    assert len(summary.skipped_objects) == 1
    assert "bad.md" in summary.skipped_objects[0]
    hits = repository.search("good", project=DEFAULT_PROJECT, limit=5)
    assert {hit.item.item_id.source_object_id for hit in hits} == {"notes:good.md"}
