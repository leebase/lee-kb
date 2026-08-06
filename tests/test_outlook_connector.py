"""Offline contract and normalization tests for the Outlook connector slice."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.chunking import chunk_document
from lee_kb.connectors.base import (
    Connector,
    ConnectorConfigError,
    ConnectorReadError,
    ReadFailureKind,
)
from lee_kb.connectors.outlook import (
    OutlookAttachment,
    OutlookConnector,
    OutlookDeltaPage,
    OutlookMessage,
    OutlookScope,
    normalize_message,
    strip_quoted_history,
)
from lee_kb.contracts import (
    ChangeType,
    DocumentType,
    KnowledgeItem,
    KnowledgeItemId,
    Principal,
    Visibility,
)
from lee_kb.governance import retrieve
from lee_kb.repository import SQLiteRepository

FOLDER_ID = "folder-inbox"
OWNER = "lee@example.test"
STAMP = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def message(
    message_id: str,
    *,
    body: str = "A useful message.",
    modified: datetime = STAMP,
    attachments: tuple[OutlookAttachment, ...] = (),
) -> OutlookMessage:
    return OutlookMessage(
        message_id=message_id,
        folder_id=FOLDER_ID,
        conversation_id="conversation-1",
        subject="Project update",
        sender="sender@example.test",
        to_recipients=(OWNER,),
        cc_recipients=(),
        body_text=body,
        sent_timestamp=STAMP,
        received_timestamp=STAMP,
        modified_timestamp=modified,
        web_link=f"https://outlook.office.com/mail/message/{message_id}",
        attachments=attachments,
    )


class ScriptedTransport:
    def __init__(self, pages, messages):
        self.pages = dict(pages)
        self.messages = {item.message_id: item for item in messages}
        self.requests: list[str | None] = []
        self.fail_requests: set[str | None] = set()

    def delta_page(self, folder_id: str, request: str | None) -> OutlookDeltaPage:
        assert folder_id == FOLDER_ID
        self.requests.append(request)
        if request in self.fail_requests:
            raise ConnectionError("offline transport failure")
        return self.pages[request]

    def fetch_message(self, message_id: str) -> OutlookMessage:
        return self.messages[message_id]

    def health(self, folder_id: str) -> tuple[bool, str]:
        assert folder_id == FOLDER_ID
        return True, "offline scripted transport"


def connector_for(transport: ScriptedTransport) -> OutlookConnector:
    return OutlookConnector(
        OutlookScope(
            mailbox_owner=OWNER,
            folder_id=FOLDER_ID,
            folder_name="Inbox",
            project="personal",
        ),
        transport,
        connector_id="outlook-test",
    )


def test_normalization_removes_quoted_history_and_keeps_attachment_metadata_once() -> (
    None
):
    attachment = OutlookAttachment(
        attachment_id="attachment-1",
        name="plan.txt",
        content_type="text/plain",
        size=12,
    )
    item = message(
        "message-1",
        body=(
            "The current plan is ready.\r\n\r\n"
            "On Tue, someone wrote:\n> The old plan.\n> More old history."
        ),
        attachments=(attachment,),
    )

    assert strip_quoted_history(item.body_text) == "The current plan is ready."
    normalized = normalize_message(item)

    assert "The current plan is ready." in normalized
    assert "The old plan" not in normalized
    assert normalized.count("plan.txt") == 1
    assert normalized.count("attachment:message-1:attachment-1") == 1
    assert "Modified: 2026-08-05T12:00:00+00:00" in normalized


def test_initial_delta_pages_produce_stable_objects_and_opaque_cursor() -> None:
    first = message("message-1")
    second = message("message-2", body="A second message.")
    transport = ScriptedTransport(
        {
            None: OutlookDeltaPage(messages=(first,), next_link="page-2"),
            "page-2": OutlookDeltaPage(messages=(second,), delta_link="delta-1"),
        },
        (first, second),
    )
    connector = connector_for(transport)

    assert isinstance(connector, Connector)
    objects = connector.discover()
    changes = connector.list_changes()

    assert transport.requests == [None, "page-2"]
    assert [item.source_object_id for item in objects] == [
        "message:message-1",
        "message:message-2",
    ]
    assert all(item.document_type is DocumentType.EMAIL for item in objects)
    assert [change.change_type for change in changes] == [
        ChangeType.CREATED,
        ChangeType.CREATED,
    ]
    assert all(change.content_hash for change in changes)

    cursor = connector.checkpoint(objects)
    decoded = json.loads(cursor)
    assert decoded["folder_id"] == FOLDER_ID
    assert decoded["connector_id"] == "outlook-test"
    assert decoded["mailbox_owner"] == OWNER
    assert decoded["delta_link"] == "delta-1"
    assert "body_text" not in cursor
    assert set(decoded["objects"]) == {
        "message:message-1",
        "message:message-2",
    }


def test_incremental_delta_updates_and_deletes_without_advancing_failed_cursor() -> (
    None
):
    first = message("message-1")
    second = message("message-2", body="A second message.")
    changed = message(
        "message-1",
        body="The message changed.",
        modified=datetime(2026, 8, 5, 13, 0, tzinfo=timezone.utc),
    )
    transport = ScriptedTransport(
        {
            None: OutlookDeltaPage(messages=(first, second), delta_link="delta-1"),
            "delta-1": OutlookDeltaPage(
                messages=(changed,),
                removed_message_ids=("message-2",),
                delta_link="delta-2",
            ),
        },
        (first, second, changed),
    )
    connector = connector_for(transport)

    initial_objects = connector.discover()
    initial_cursor = connector.checkpoint(initial_objects)
    changes = connector.list_changes(initial_cursor)

    assert [(item.source_object_id, item.change_type) for item in changes] == [
        ("message:message-1", ChangeType.UPDATED),
        ("message:message-2", ChangeType.DELETED),
    ]
    current_objects = connector.discover()
    assert [item.source_object_id for item in current_objects] == ["message:message-1"]
    next_cursor = connector.checkpoint(current_objects)
    assert json.loads(next_cursor)["delta_link"] == "delta-2"

    transport.pages["delta-2"] = OutlookDeltaPage(delta_link="delta-3")
    transport.fail_requests.add("delta-2")
    with pytest.raises(ConnectorReadError) as error:
        connector.list_changes(next_cursor)
    assert error.value.kind is ReadFailureKind.TEMPORARILY_INACCESSIBLE
    assert next_cursor != ""


def test_empty_delta_round_produces_a_new_checkpoint_without_changes() -> None:
    item = message("message-1")
    transport = ScriptedTransport(
        {
            None: OutlookDeltaPage(messages=(item,), delta_link="delta-1"),
            "delta-1": OutlookDeltaPage(delta_link="delta-2"),
        },
        (item,),
    )
    connector = connector_for(transport)

    initial_objects = connector.discover()
    initial_cursor = connector.checkpoint(initial_objects)
    assert connector.list_changes(initial_cursor) == ()

    current_objects = connector.discover()
    next_cursor = connector.checkpoint(current_objects)

    assert current_objects == initial_objects
    assert json.loads(next_cursor)["delta_link"] == "delta-2"


def test_delta_event_order_allows_a_later_delete_to_win() -> None:
    first = message("message-1")
    changed = message(
        "message-1",
        body="The message changed before it was moved out.",
        modified=STAMP + timedelta(minutes=1),
    )
    transport = ScriptedTransport(
        {
            None: OutlookDeltaPage(messages=(first,), delta_link="delta-1"),
            "delta-1": OutlookDeltaPage(
                messages=(changed,),
                next_link="page-2",
            ),
            "page-2": OutlookDeltaPage(
                removed_message_ids=("message-1",),
                delta_link="delta-2",
            ),
        },
        (first, changed),
    )
    connector = connector_for(transport)

    initial_objects = connector.discover()
    initial_cursor = connector.checkpoint(initial_objects)

    changes = connector.list_changes(initial_cursor)

    assert [(change.source_object_id, change.change_type) for change in changes] == [
        ("message:message-1", ChangeType.DELETED)
    ]
    assert connector.discover() == ()


def test_modified_timestamp_drift_is_visible_as_an_update() -> None:
    first = message("message-1")
    modified = message(
        "message-1",
        modified=STAMP + timedelta(minutes=1),
    )
    transport = ScriptedTransport(
        {
            None: OutlookDeltaPage(messages=(first,), delta_link="delta-1"),
            "delta-1": OutlookDeltaPage(messages=(modified,), delta_link="delta-2"),
        },
        (first,),
    )
    connector = connector_for(transport)

    initial_objects = connector.discover()
    initial_cursor = connector.checkpoint(initial_objects)
    transport.messages[modified.message_id] = modified

    changes = connector.list_changes(initial_cursor)
    current_objects = connector.discover()

    assert [(change.source_object_id, change.change_type) for change in changes] == [
        ("message:message-1", ChangeType.UPDATED)
    ]
    assert current_objects[0].source_timestamp == modified.modified_timestamp
    fetched = connector.fetch("message:message-1")
    assert fetched.source_timestamp == modified.modified_timestamp
    assert fetched.content_hash == current_objects[0].content_hash


def test_source_locator_drift_is_visible_as_an_update() -> None:
    first = message("message-1")
    moved_link = replace(
        first,
        web_link="https://outlook.office.com/mail/message/message-2",
    )
    transport = ScriptedTransport(
        {
            None: OutlookDeltaPage(messages=(first,), delta_link="delta-1"),
            "delta-1": OutlookDeltaPage(messages=(moved_link,), delta_link="delta-2"),
        },
        (first,),
    )
    connector = connector_for(transport)

    initial_objects = connector.discover()
    initial_cursor = connector.checkpoint(initial_objects)
    transport.messages[first.message_id] = moved_link

    changes = connector.list_changes(initial_cursor)

    assert [(change.source_object_id, change.change_type) for change in changes] == [
        ("message:message-1", ChangeType.UPDATED)
    ]


def test_failed_fetch_blocks_checkpoint_until_the_same_object_is_retried() -> None:
    item = message("message-1")
    transport = ScriptedTransport(
        {None: OutlookDeltaPage(messages=(item,), delta_link="delta-1")},
        (item,),
    )
    connector = connector_for(transport)
    objects = connector.discover()
    connector.list_changes()
    transport.messages.pop(item.message_id)

    with pytest.raises(ConnectorReadError) as error:
        connector.fetch(item.source_object_id)
    assert error.value.kind is ReadFailureKind.TEMPORARILY_INACCESSIBLE
    with pytest.raises(ConnectorConfigError):
        connector.checkpoint(objects)

    transport.messages[item.message_id] = item
    connector.fetch(item.source_object_id)
    cursor = connector.checkpoint(objects)
    assert json.loads(cursor)["delta_link"] == "delta-1"


def test_fetch_hash_drift_blocks_checkpoint_and_does_not_cache_new_content() -> None:
    item = message("message-1")
    changed = message(
        "message-1",
        body="The source changed after the delta page was read.",
        modified=STAMP + timedelta(minutes=1),
    )
    transport = ScriptedTransport(
        {None: OutlookDeltaPage(messages=(item,), delta_link="delta-1")},
        (item,),
    )
    connector = connector_for(transport)
    objects = connector.discover()
    connector.list_changes()
    transport.messages[item.message_id] = changed

    with pytest.raises(ConnectorReadError) as error:
        connector.fetch(item.source_object_id)

    assert error.value.kind is ReadFailureKind.TEMPORARILY_INACCESSIBLE
    with pytest.raises(ConnectorConfigError):
        connector.checkpoint(objects)

    transport.messages[item.message_id] = item
    fetched = connector.fetch(item.source_object_id)
    assert fetched.content == normalize_message(item)
    connector.checkpoint(objects)


def test_checkpoint_rejects_same_hash_with_substituted_source_metadata() -> None:
    item = message("message-1")
    transport = ScriptedTransport(
        {None: OutlookDeltaPage(messages=(item,), delta_link="delta-1")},
        (item,),
    )
    connector = connector_for(transport)
    objects = connector.discover()
    substituted = replace(objects[0], source_timestamp=STAMP + timedelta(minutes=1))

    with pytest.raises(ConnectorConfigError):
        connector.checkpoint((substituted,))


def test_attachment_relationships_are_scoped_to_the_parent_message() -> None:
    first = message(
        "message-1",
        attachments=(OutlookAttachment("same-id", "plan.txt"),),
    )
    second = message(
        "message-2",
        attachments=(OutlookAttachment("same-id", "plan.txt"),),
    )
    transport = ScriptedTransport(
        {None: OutlookDeltaPage(messages=(first, second), delta_link="delta-1")},
        (first, second),
    )
    connector = connector_for(transport)
    connector.discover()

    assert connector.relationships(first.source_object_id) == (
        "conversation:conversation-1",
        "attachment:message-1:same-id",
    )
    assert connector.relationships(second.source_object_id) == (
        "conversation:conversation-1",
        "attachment:message-2:same-id",
    )


def test_wrong_folder_delta_item_fails_closed_as_a_folder_move() -> None:
    item = message("message-1")
    moved = replace(item, folder_id="folder-archive")
    transport = ScriptedTransport(
        {
            None: OutlookDeltaPage(messages=(item,), delta_link="delta-1"),
            "delta-1": OutlookDeltaPage(messages=(moved,), delta_link="delta-2"),
        },
        (item, moved),
    )
    connector = connector_for(transport)
    initial_objects = connector.discover()
    initial_cursor = connector.checkpoint(initial_objects)

    with pytest.raises(ConnectorReadError) as error:
        connector.list_changes(initial_cursor)

    assert error.value.kind is ReadFailureKind.MALFORMED
    with pytest.raises(ConnectorConfigError):
        connector.checkpoint(initial_objects)


def test_cursor_is_bound_to_connector_and_mailbox_scope() -> None:
    item = message("message-1")
    transport = ScriptedTransport(
        {None: OutlookDeltaPage(messages=(item,), delta_link="delta-1")},
        (item,),
    )
    connector = connector_for(transport)
    cursor = connector.checkpoint(connector.discover())
    other_scope = OutlookScope(
        mailbox_owner="other@example.test",
        folder_id=FOLDER_ID,
        project="personal",
    )
    other = OutlookConnector(other_scope, transport, connector_id="outlook-test")

    with pytest.raises(ConnectorConfigError):
        other.list_changes(cursor)


def test_provider_diagnostics_are_not_echoed() -> None:
    class LeakyTransport(ScriptedTransport):
        def delta_page(self, folder_id, request):
            raise ConnectorReadError(
                "provider body contains bearer-secret",
                kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
            )

    transport = LeakyTransport({}, ())
    transport.health = lambda _folder_id: (True, "bearer-secret")
    connector = connector_for(transport)

    with pytest.raises(ConnectorReadError) as error:
        connector.discover()
    assert "bearer-secret" not in str(error.value)
    assert error.value.__cause__ is None
    assert connector.health().detail == "folder Inbox: transport healthy"


def test_repeated_delta_continuation_fails_closed() -> None:
    item = message("message-1")
    transport = ScriptedTransport(
        {
            None: OutlookDeltaPage(messages=(item,), next_link="page-2"),
            "page-2": OutlookDeltaPage(next_link="page-2"),
        },
        (item,),
    )
    connector = connector_for(transport)

    with pytest.raises(ConnectorReadError) as error:
        connector.discover()

    assert error.value.kind is ReadFailureKind.MALFORMED


def test_fetch_permissions_relationships_health_and_refresh_are_scoped() -> None:
    item = message(
        "message-1",
        attachments=(OutlookAttachment("attachment-1", "agenda.pdf"),),
    )
    transport = ScriptedTransport(
        {None: OutlookDeltaPage(messages=(item,), delta_link="delta-1")},
        (item,),
    )
    connector = connector_for(transport)
    objects = connector.discover()
    connector.checkpoint(objects)

    fetched = connector.fetch("message:message-1")
    refreshed = connector.refresh("message:message-1")
    permissions = connector.permissions("message:message-1")
    health = connector.health()

    assert fetched.document_type is DocumentType.EMAIL
    assert fetched.content_hash == objects[0].content_hash
    assert (
        fetched.source_locator.uri
        == "https://outlook.office.com/mail/message/message-1"
    )
    assert fetched.source_timestamp == item.modified_timestamp
    assert refreshed == fetched
    assert permissions.owner == OWNER
    assert permissions.visibility is Visibility.PRIVATE
    assert connector.relationships("message:message-1") == (
        "conversation:conversation-1",
        "attachment:message-1:attachment-1",
    )
    assert health.healthy
    assert "Inbox" in health.detail


def test_governed_retrieval_uses_email_citations_and_denies_other_principals(
    tmp_path,
) -> None:
    item = message("message-1", body="The launch review is scheduled for Friday.")
    transport = ScriptedTransport(
        {None: OutlookDeltaPage(messages=(item,), delta_link="delta-1")},
        (item,),
    )
    connector = connector_for(transport)
    objects = connector.discover()
    changes = connector.list_changes()

    with SQLiteRepository(tmp_path / "knowledge.sqlite") as repository:
        for change in changes:
            document = connector.fetch(change.source_object_id)
            item_id = KnowledgeItemId(connector.connector_id, document.source_object_id)
            knowledge_item = KnowledgeItem(
                item_id=item_id,
                project=document.project,
                source_locator=document.source_locator,
                document_type=document.document_type,
                content_hash=document.content_hash,
                source_timestamp=document.source_timestamp,
                sync_timestamp=STAMP,
                permissions=connector.permissions(document.source_object_id),
                title=document.title,
                authority=document.authority,
                trust=document.trust,
            )
            repository.sync_item(
                knowledge_item,
                chunk_document(
                    document.content,
                    item_id=item_id,
                    project=document.project,
                    document_type=document.document_type,
                ),
            )

        connector.checkpoint(objects)
        permitted = retrieve(
            repository,
            "launch review Friday",
            principal=Principal(OWNER),
            project="personal",
        )
        denied = retrieve(
            repository,
            "launch review Friday",
            principal=Principal("mallory@example.test"),
            project="personal",
        )

    assert permitted.evidence
    assert permitted.evidence[0].citation.source_locator.uri.startswith(
        "https://outlook.office.com/"
    )
    assert denied.evidence == ()
    assert denied.denied_count >= 1


def test_missing_delta_link_fails_closed() -> None:
    item = message("message-1")
    transport = ScriptedTransport(
        {None: OutlookDeltaPage(messages=(item,))},
        (item,),
    )
    connector = connector_for(transport)

    with pytest.raises(ConnectorReadError) as error:
        connector.discover()

    assert error.value.kind is ReadFailureKind.MALFORMED
