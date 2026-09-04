"""Offline contract tests for the bounded calendar connector."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from lee_kb.connectors.base import (
    ConnectorConfigError,
    ConnectorReadError,
    ReadFailureKind,
)
from lee_kb.connectors.calendar import (
    CalendarConnector,
    CalendarEvent,
    CalendarScope,
    normalize_event,
)
from lee_kb.connectors.calendar_graph import _event_from_graph
from lee_kb.contracts import ChangeType, DocumentType, Visibility
from lee_kb.main import _calendar_connector_from_config, _sync_external_connector
from lee_kb.repository import SQLiteRepository

OWNER = "lee@example.test"
EMPLOYEE = "employee:employee-zero"
CALENDAR_ID = "calendar-1"
START = datetime(2026, 8, 8, tzinfo=UTC)
END = START + timedelta(days=90)
STAMP = START + timedelta(hours=1)


def event(
    event_id: str = "event-1", *, subject: str = "Project review"
) -> CalendarEvent:
    return CalendarEvent(
        event_id=event_id,
        calendar_id=CALENDAR_ID,
        subject=subject,
        start=STAMP,
        end=STAMP + timedelta(hours=1),
        modified_timestamp=STAMP,
        organizer=OWNER,
        attendees=("teammate@example.test",),
        location="Office",
        body_text="Review the current project risks.",
    )


class ScriptedTransport:
    def __init__(self, events: tuple[CalendarEvent, ...]) -> None:
        self.events = events
        self.fail = False

    def list_events(self, scope: CalendarScope) -> tuple[CalendarEvent, ...]:
        assert scope.calendar_id == CALENDAR_ID
        if self.fail:
            raise ConnectionError("offline")
        return self.events

    def fetch_event(self, event_id: str, calendar_id: str) -> CalendarEvent:
        assert calendar_id == CALENDAR_ID
        return next(item for item in self.events if item.event_id == event_id)

    def health(self, calendar_id: str) -> tuple[bool, str]:
        assert calendar_id == CALENDAR_ID
        return True, "scripted"


def connector_for(
    transport: ScriptedTransport,
    *,
    allowed_principals: tuple[str, ...] = (EMPLOYEE,),
) -> CalendarConnector:
    return CalendarConnector(
        CalendarScope(
            owner=OWNER,
            calendar_id=CALENDAR_ID,
            calendar_name="Calendar",
            start=START,
            end=END,
            project="personal",
            account_id="calendar-account",
            allowed_principals=allowed_principals,
        ),
        transport,
    )


def test_calendar_snapshot_is_private_searchable_and_contains_no_join_url() -> None:
    item = event()
    transport = ScriptedTransport((item,))
    connector = connector_for(transport)

    objects = connector.discover()
    changes = connector.list_changes()
    fetched = connector.fetch("event:event-1")

    assert len(objects) == 1
    assert objects[0].document_type is DocumentType.CALENDAR
    assert changes[0].change_type is ChangeType.CREATED
    assert "Subject: Project review" in fetched.content
    assert "Attendees: teammate@example.test" in fetched.content
    assert "https://" not in fetched.content
    permissions = connector.permissions("event:event-1")
    assert permissions.visibility is Visibility.PRIVATE
    assert permissions.allowed_principals == (EMPLOYEE,)
    assert json.loads(connector.checkpoint(objects))["schema_version"] == 1


def test_calendar_sync_applies_changed_grant_without_content_churn(tmp_path) -> None:
    transport = ScriptedTransport((event(),))
    first = connector_for(transport)
    second = connector_for(
        transport,
        allowed_principals=("employee:documentation-steward",),
    )

    with SQLiteRepository(tmp_path / "knowledge.sqlite") as repository:
        created = _sync_external_connector(
            first,
            repository,
            sync_timestamp=STAMP,
        )
        unchanged = _sync_external_connector(
            second,
            repository,
            sync_timestamp=STAMP + timedelta(minutes=1),
        )
        hits = repository.search("Project", project="personal")

    assert created.created == 1
    assert unchanged.unchanged == 1
    assert hits[0].item.permissions.allowed_principals == (
        "employee:documentation-steward",
    )


def test_calendar_snapshot_updates_and_deletes_without_advancing_failed_pass() -> None:
    first = event("event-1")
    second = event("event-2", subject="Second meeting")
    transport = ScriptedTransport((first, second))
    connector = connector_for(transport)
    initial = connector.discover()
    cursor = connector.checkpoint(initial)

    transport.events = (replace(first, subject="Updated project review"),)
    changes = connector.list_changes(cursor)
    assert [(change.source_object_id, change.change_type) for change in changes] == [
        ("event:event-1", ChangeType.UPDATED),
        ("event:event-2", ChangeType.DELETED),
    ]
    current = connector.discover()
    next_cursor = connector.checkpoint(current)

    transport.fail = True
    with pytest.raises(ConnectorReadError) as error:
        connector.list_changes(next_cursor)
    assert error.value.kind is ReadFailureKind.TEMPORARILY_INACCESSIBLE


def test_calendar_checkpoint_rejects_objects_outside_completed_pass() -> None:
    connector = connector_for(ScriptedTransport((event(),)))
    objects = connector.discover()

    with pytest.raises(ConnectorConfigError, match="do not match"):
        connector.checkpoint(())
    assert connector.checkpoint(objects)


def test_graph_event_mapping_requires_utc_and_omits_online_meeting_url() -> None:
    mapped = _event_from_graph(
        {
            "id": "event-1",
            "subject": "Planning",
            "body": {"contentType": "html", "content": "<p>Decide next steps.</p>"},
            "start": {"dateTime": "2026-08-08T10:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-08-08T11:00:00", "timeZone": "UTC"},
            "lastModifiedDateTime": "2026-08-08T09:00:00Z",
            "organizer": {"emailAddress": {"address": OWNER}},
            "attendees": [{"emailAddress": {"address": "teammate@example.test"}}],
            "location": {"displayName": "Office"},
            "isAllDay": False,
            "isCancelled": False,
            "onlineMeetingUrl": "https://secret.example.test/join",
        },
        expected_calendar=CALENDAR_ID,
    )

    normalized = normalize_event(mapped)
    assert mapped.start.tzinfo is UTC
    assert "Decide next steps." in normalized
    assert "secret.example.test" not in normalized

    malformed = {
        "id": "event-2",
        "subject": "Bad timezone",
        "body": {"contentType": "text", "content": "Body"},
        "start": {
            "dateTime": "2026-08-08T10:00:00",
            "timeZone": "Pacific Standard Time",
        },
        "end": {"dateTime": "2026-08-08T11:00:00", "timeZone": "Pacific Standard Time"},
        "lastModifiedDateTime": "2026-08-08T09:00:00Z",
        "isAllDay": False,
        "isCancelled": False,
    }
    with pytest.raises(ValueError, match="not normalized to UTC"):
        _event_from_graph(malformed, expected_calendar=CALENDAR_ID)


def test_calendar_config_requires_an_isolated_read_only_graph_grant() -> None:
    raw_config = {
        "owner": OWNER,
        "microsoft_graph": {
            "client_id": "public-client-id",
            "user_id": OWNER,
            "tenant": "common",
            "scopes": ["Calendars.Read", "User.Read"],
        },
        "calendar": {
            "chief_of_staff": {
                "calendar_id": CALENDAR_ID,
                "start": START.isoformat(),
                "end": END.isoformat(),
                "project": "personal",
                "allowed_principals": [EMPLOYEE],
            }
        },
    }

    connector, client = _calendar_connector_from_config(raw_config, "chief_of_staff")
    assert connector.project == "personal"
    assert set(client.credential.scopes) == {"Calendars.Read", "User.Read"}
    assert connector.permissions("event:event-1").allowed_principals == (EMPLOYEE,)

    raw_config["microsoft_graph"]["scopes"] = ["Mail.Read", "User.Read"]
    with pytest.raises(
        ConnectorConfigError, match="exactly Calendars.Read and User.Read"
    ):
        _calendar_connector_from_config(raw_config, "chief_of_staff")
