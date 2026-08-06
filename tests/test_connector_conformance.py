"""Focused conformance coverage for the shared connector contract.

The local connector is the reference implementation. These tests exercise the
contract methods directly and use the real sync boundary for failure and
checkpoint assertions, so a future connector can be compared without changing
the normalized repository or retrieval contracts.
"""

import json
from datetime import datetime, timezone

import pytest

from lee_kb.connectors.base import (
    Connector,
    ConnectorReadError,
    ReadFailureKind,
)
from lee_kb.connectors.local_files import LocalFilesConnector, RootConfig
from lee_kb.contracts import (
    ChangeType,
    DocumentType,
    KnowledgeItemId,
    Visibility,
    compute_content_hash,
)
from lee_kb.main import _sync_connector
from lee_kb.repository import SQLiteRepository

SYNC_TIME = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def local_case(tmp_path):
    source_root = tmp_path / "notes"
    (source_root / "nested").mkdir(parents=True)
    (source_root / "guide.md").write_text(
        "# Guide\n\nThe local connector is the reference.", encoding="utf-8"
    )
    (source_root / "nested" / "note.md").write_text("A nested note.", encoding="utf-8")
    (source_root / "not-in-scope.txt").write_text(
        "The configured scope is Markdown only.", encoding="utf-8"
    )
    connector = LocalFilesConnector(
        (
            RootConfig(
                name="notes",
                path=source_root,
                owner="lee@leebase.com",
                include=("**/*.md",),
                project="personal",
                visibility=Visibility.PROJECT,
            ),
        ),
        connector_id="local-conformance",
    )
    return connector, source_root


def test_local_connector_conforms_on_identity_scope_and_discovery(local_case) -> None:
    connector, _source_root = local_case

    assert isinstance(connector, Connector)
    assert connector.connector_id == "local-conformance"

    objects = connector.discover()

    assert [obj.source_object_id for obj in objects] == [
        "notes:guide.md",
        "notes:nested/note.md",
    ]
    assert all(
        obj.source_locator.connector_id == connector.connector_id for obj in objects
    )
    assert all(obj.project == "personal" for obj in objects)
    assert all(obj.document_type is DocumentType.MARKDOWN for obj in objects)
    assert objects[0].content_hash == compute_content_hash(
        "# Guide\n\nThe local connector is the reference."
    )
    assert all(
        obj.source_timestamp.tzinfo is not None
        and obj.source_timestamp.utcoffset() is not None
        for obj in objects
    )


def test_snapshot_cursor_detects_create_update_delete_and_no_change(local_case) -> None:
    connector, source_root = local_case
    initial_objects = connector.discover()
    initial_cursor = connector.checkpoint(initial_objects)
    initial_changes = connector.list_changes()

    assert json.loads(initial_cursor) == {
        obj.source_object_id: obj.content_hash for obj in initial_objects
    }
    assert connector.checkpoint(tuple(reversed(initial_objects))) == initial_cursor
    assert [change.source_object_id for change in initial_changes] == [
        "notes:guide.md",
        "notes:nested/note.md",
    ]
    assert all(change.change_type is ChangeType.CREATED for change in initial_changes)
    assert connector.list_changes(initial_cursor) == ()

    (source_root / "new.md").write_text("A new source.", encoding="utf-8")
    created = connector.list_changes(initial_cursor)
    assert [(change.source_object_id, change.change_type) for change in created] == [
        ("notes:new.md", ChangeType.CREATED)
    ]

    after_create_cursor = connector.checkpoint(connector.discover())
    (source_root / "guide.md").write_text(
        "# Guide\n\nThe reference changed.", encoding="utf-8"
    )
    updated = connector.list_changes(after_create_cursor)
    assert len(updated) == 1
    assert updated[0].source_object_id == "notes:guide.md"
    assert updated[0].change_type is ChangeType.UPDATED
    assert updated[0].previous_content_hash == initial_objects[0].content_hash

    after_update_cursor = connector.checkpoint(connector.discover())
    (source_root / "new.md").unlink()
    deleted = connector.list_changes(after_update_cursor)
    assert len(deleted) == 1
    assert deleted[0].source_object_id == "notes:new.md"
    assert deleted[0].change_type is ChangeType.DELETED
    assert connector.list_changes(after_update_cursor)[0] == deleted[0]


def test_fetch_refresh_permissions_freshness_and_relationships(local_case) -> None:
    connector, _source_root = local_case
    source_object = connector.discover()[0]

    fetched = connector.fetch(source_object.source_object_id)
    refreshed = connector.refresh(source_object.source_object_id)
    permissions = connector.permissions(source_object.source_object_id)

    assert fetched.source_object_id == source_object.source_object_id
    assert fetched.source_locator == source_object.source_locator
    assert fetched.content_hash == source_object.content_hash
    assert fetched.content.startswith("# Guide")
    assert fetched.source_timestamp == source_object.source_timestamp
    assert fetched.project == "personal"
    assert refreshed == fetched
    assert permissions.owner == "lee@leebase.com"
    assert permissions.visibility is Visibility.PROJECT
    assert connector.relationships(source_object.source_object_id) == ()


def test_health_reports_reachable_and_missing_required_scope(local_case) -> None:
    connector, source_root = local_case

    healthy = connector.health()
    assert healthy.healthy
    assert healthy.missing_required_roots == ()
    assert healthy.checked_at.tzinfo is not None
    assert healthy.checked_at.utcoffset() is not None

    (source_root / "guide.md").unlink()
    (source_root / "nested" / "note.md").unlink()
    (source_root / "nested").rmdir()
    (source_root / "not-in-scope.txt").unlink()
    source_root.rmdir()

    missing = connector.health()
    assert not missing.healthy
    assert missing.missing_required_roots == ("notes",)


def test_temporary_discovery_failure_is_not_deletion_or_checkpoint_advance(
    local_case, tmp_path, monkeypatch
) -> None:
    connector, _source_root = local_case

    with SQLiteRepository(tmp_path / "projection.sqlite") as repository:
        first = _sync_connector(
            connector,
            repository,
            root_filter=None,
            sync_timestamp=SYNC_TIME,
        )
        previous_cursor = repository.get_connector_cursor(connector.connector_id)
        assert first.created == 2
        assert previous_cursor
        original_describe = connector._describe

        def unavailable(root, relative, file_path, handler):
            if relative == "guide.md":
                raise ConnectorReadError(
                    "source object is temporarily inaccessible",
                    kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
                )
            return original_describe(root, relative, file_path, handler)

        monkeypatch.setattr(connector, "_describe", unavailable)

        summary = _sync_connector(
            connector,
            repository,
            root_filter=None,
            sync_timestamp=SYNC_TIME,
        )

        item = repository.get_item(
            KnowledgeItemId(connector.connector_id, "notes:guide.md")
        )
        assert summary.deleted == 0
        assert summary.failure_counts == {"temporarily_inaccessible": 1}
        assert item is not None and not item.tombstone
        assert (
            repository.get_connector_cursor(connector.connector_id) == previous_cursor
        )


def test_temporary_fetch_failure_retries_without_advancing_checkpoint(
    local_case, tmp_path, monkeypatch
) -> None:
    connector, source_root = local_case

    with SQLiteRepository(tmp_path / "projection.sqlite") as repository:
        _sync_connector(
            connector,
            repository,
            root_filter=None,
            sync_timestamp=SYNC_TIME,
        )
        previous_cursor = repository.get_connector_cursor(connector.connector_id)
        old_hash = repository.get_item(
            KnowledgeItemId(connector.connector_id, "notes:guide.md")
        ).content_hash
        (source_root / "guide.md").write_text(
            "# Guide\n\nThe source changed while unavailable.", encoding="utf-8"
        )
        original_fetch = connector.fetch

        def unavailable(source_object_id):
            if source_object_id == "notes:guide.md":
                raise ConnectorReadError(
                    "source object is temporarily inaccessible",
                    kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
                )
            return original_fetch(source_object_id)

        monkeypatch.setattr(connector, "fetch", unavailable)
        failed = _sync_connector(
            connector,
            repository,
            root_filter=None,
            sync_timestamp=SYNC_TIME,
        )

        item = repository.get_item(
            KnowledgeItemId(connector.connector_id, "notes:guide.md")
        )
        assert failed.updated == 0
        assert failed.failure_counts == {"temporarily_inaccessible": 1}
        assert item is not None and item.content_hash == old_hash
        assert (
            repository.get_connector_cursor(connector.connector_id) == previous_cursor
        )

        monkeypatch.setattr(connector, "fetch", original_fetch)
        recovered = _sync_connector(
            connector,
            repository,
            root_filter=None,
            sync_timestamp=SYNC_TIME,
        )

        assert recovered.updated == 1
        assert (
            repository.get_connector_cursor(connector.connector_id) != previous_cursor
        )
