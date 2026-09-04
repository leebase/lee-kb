"""Bounded, read-only Microsoft 365 calendar connector.

The connector snapshots one explicit calendar view.  Its persisted cursor contains
only normalized object metadata; authentication and Graph transport remain behind
``CalendarTransport``.  A moving or unbounded window is deliberately unsupported:
the configured UTC range is part of the connector identity and evidence boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from urllib.parse import quote

from ..contracts import (
    DEFAULT_PROJECT,
    Authority,
    ChangeType,
    DocumentType,
    PermissionSet,
    SourceLocator,
    Trust,
    Visibility,
    compute_content_hash,
)
from .base import (
    Connector,
    ConnectorConfigError,
    ConnectorReadError,
    FetchedDocument,
    HealthStatus,
    ObjectChange,
    ReadFailureKind,
    SourceObject,
)

__all__ = [
    "GRAPH_DELEGATED_SCOPE",
    "CalendarConnector",
    "CalendarEvent",
    "CalendarScope",
    "CalendarTransport",
    "normalize_event",
]

GRAPH_DELEGATED_SCOPE = "Calendars.Read"
_CURSOR_VERSION = 1
_EVENT_PREFIX = "event:"


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_optional_text(value: object, name: str) -> None:
    if value is not None:
        _require_text(value, name)


def _require_aware(value: object, name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CalendarScope:
    """One immutable delegated calendar-view boundary."""

    owner: str
    calendar_id: str
    start: datetime
    end: datetime
    calendar_name: str | None = None
    project: str = DEFAULT_PROJECT
    authority: Authority = Authority.CANONICAL
    trust: Trust = Trust.HUMAN_AUTHORED
    account_id: str | None = None
    tenant: str | None = None
    credential_binding: str | None = None
    allowed_principals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.owner, "owner")
        _require_text(self.calendar_id, "calendar_id")
        _require_aware(self.start, "start")
        _require_aware(self.end, "end")
        if self.start >= self.end:
            raise ValueError("start must be before end")
        _require_optional_text(self.calendar_name, "calendar_name")
        _require_text(self.project, "project")
        if not isinstance(self.authority, Authority):
            raise TypeError("authority must be an Authority")
        if not isinstance(self.trust, Trust):
            raise TypeError("trust must be a Trust")
        _require_optional_text(self.account_id, "account_id")
        _require_optional_text(self.tenant, "tenant")
        _require_optional_text(self.credential_binding, "credential_binding")
        if not isinstance(self.allowed_principals, tuple):
            raise TypeError("allowed_principals must be a tuple")
        for principal in self.allowed_principals:
            _require_text(principal, "allowed_principals entry")


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """Normalized event data supplied by a calendar transport."""

    event_id: str
    calendar_id: str
    subject: str
    start: datetime
    end: datetime
    modified_timestamp: datetime
    organizer: str | None = None
    attendees: tuple[str, ...] = ()
    location: str | None = None
    body_text: str = ""
    is_all_day: bool = False
    is_cancelled: bool = False
    series_master_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _require_text(self.calendar_id, "calendar_id")
        if not isinstance(self.subject, str):
            raise TypeError("subject must be a str")
        _require_aware(self.start, "start")
        _require_aware(self.end, "end")
        _require_aware(self.modified_timestamp, "modified_timestamp")
        if self.start > self.end:
            raise ValueError("event start must not be after end")
        _require_optional_text(self.organizer, "organizer")
        if not isinstance(self.attendees, tuple):
            raise TypeError("attendees must be a tuple")
        for attendee in self.attendees:
            _require_text(attendee, "attendee")
        _require_optional_text(self.location, "location")
        if not isinstance(self.body_text, str):
            raise TypeError("body_text must be a str")
        if not isinstance(self.is_all_day, bool) or not isinstance(
            self.is_cancelled, bool
        ):
            raise TypeError("calendar flags must be bool values")
        _require_optional_text(self.series_master_id, "series_master_id")

    @property
    def source_object_id(self) -> str:
        return _EVENT_PREFIX + self.event_id


@runtime_checkable
class CalendarTransport(Protocol):
    """Provider boundary for a complete bounded view, fetch, and health."""

    def list_events(self, scope: CalendarScope) -> tuple[CalendarEvent, ...]: ...

    def fetch_event(self, event_id: str, calendar_id: str) -> CalendarEvent: ...

    def health(self, calendar_id: str) -> tuple[bool, str]: ...


def normalize_event(event: CalendarEvent) -> str:
    """Produce deterministic, searchable event text without join URLs."""
    lines = [
        f"Subject: {event.subject or '(no subject)'}",
        f"Start: {event.start.isoformat()}",
        f"End: {event.end.isoformat()}",
        f"All day: {'yes' if event.is_all_day else 'no'}",
        f"Cancelled: {'yes' if event.is_cancelled else 'no'}",
    ]
    if event.organizer:
        lines.append(f"Organizer: {event.organizer}")
    if event.attendees:
        lines.append("Attendees: " + ", ".join(event.attendees))
    if event.location:
        lines.append(f"Location: {event.location}")
    body = event.body_text.strip()
    if body:
        lines.extend(("", body))
    return "\n".join(lines)


@dataclass(slots=True)
class _PendingRead:
    input_cursor: str | None
    objects: tuple[SourceObject, ...]
    changes: tuple[ObjectChange, ...]
    checkpointed: bool = False


class CalendarConnector(Connector):
    """Snapshot one fixed calendar view through a read-only transport."""

    def __init__(self, scope: CalendarScope, transport: CalendarTransport) -> None:
        if not isinstance(scope, CalendarScope):
            raise TypeError("scope must be a CalendarScope")
        if not isinstance(transport, CalendarTransport):
            raise TypeError("transport must implement CalendarTransport")
        self._scope = scope
        self._transport = transport
        identity = "\0".join(
            (
                scope.account_id or scope.owner,
                scope.calendar_id,
                scope.start.isoformat(),
                scope.end.isoformat(),
            )
        ).encode()
        self._connector_id = "calendar:" + hashlib.sha256(identity).hexdigest()[:16]
        self._events: dict[str, CalendarEvent] = {}
        self._pending: _PendingRead | None = None

    @property
    def connector_id(self) -> str:
        return self._connector_id

    @property
    def project(self) -> str:
        return self._scope.project

    def discover(self) -> tuple[SourceObject, ...]:
        return self._read(None)[0]

    def list_changes(self, cursor: str | None = None) -> tuple[ObjectChange, ...]:
        return self._read(cursor)[1]

    def fetch(self, source_object_id: str) -> FetchedDocument:
        event = self._events.get(source_object_id)
        if event is None:
            raise ConnectorReadError(
                "calendar event is not present in the completed view",
                kind=ReadFailureKind.UNREADABLE,
            )
        return self._fetched(event)

    def refresh(self, source_object_id: str) -> FetchedDocument:
        event_id = self._event_id(source_object_id)
        try:
            event = self._transport.fetch_event(event_id, self._scope.calendar_id)
        except ConnectorReadError:
            raise
        except (ConnectionError, TimeoutError, OSError) as error:
            raise ConnectorReadError(
                "calendar event refresh was temporarily unavailable",
                kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
            ) from error
        self._validate_event(event)
        self._events[source_object_id] = event
        return self._fetched(event)

    def permissions(self, source_object_id: str) -> PermissionSet:
        self._event_id(source_object_id)
        return PermissionSet(
            owner=self._scope.owner,
            visibility=Visibility.PRIVATE,
            allowed_principals=self._scope.allowed_principals,
            classification="delegated-calendar-read",
        )

    def relationships(self, source_object_id: str) -> tuple[str, ...]:
        event = self._events.get(source_object_id)
        if event is None:
            self._event_id(source_object_id)
            return ()
        if event.series_master_id and event.series_master_id != event.event_id:
            return (_EVENT_PREFIX + event.series_master_id,)
        return ()

    def health(self) -> HealthStatus:
        checked_at = datetime.now(UTC)
        try:
            healthy, _detail = self._transport.health(self._scope.calendar_id)
        except (
            ConnectorReadError,
            ConnectionError,
            TimeoutError,
            OSError,
        ) as error:
            return HealthStatus(
                False,
                checked_at,
                detail=f"calendar health check failed: {type(error).__name__}",
            )
        if not isinstance(healthy, bool) or not isinstance(_detail, str):
            return HealthStatus(
                False,
                checked_at,
                detail="calendar transport returned an invalid health result",
            )
        label = self._scope.calendar_name or self._scope.calendar_id
        transport_status = "healthy" if healthy else "unhealthy"
        return HealthStatus(
            healthy,
            checked_at,
            detail=f"calendar {label}: transport {transport_status}",
        )

    def checkpoint(self, objects: Sequence[SourceObject]) -> str:
        pending = self._pending
        if pending is None:
            raise ConnectorConfigError("calendar checkpoint requires a completed pass")
        provided = tuple(objects)
        if provided != pending.objects:
            raise ConnectorConfigError(
                "calendar checkpoint objects do not match the completed pass"
            )
        body = {
            "schema_version": _CURSOR_VERSION,
            "objects": [self._cursor_object(item) for item in pending.objects],
        }
        pending.checkpointed = True
        return json.dumps(body, sort_keys=True, separators=(",", ":"))

    def _read(
        self, cursor: str | None
    ) -> tuple[tuple[SourceObject, ...], tuple[ObjectChange, ...]]:
        if self._pending is not None:
            if not self._pending.checkpointed and self._pending.input_cursor == cursor:
                return self._pending.objects, self._pending.changes
            if self._pending.checkpointed:
                self._pending = None
        previous = self._decode_cursor(cursor)
        try:
            events = self._transport.list_events(self._scope)
        except ConnectorReadError:
            raise
        except (ConnectionError, TimeoutError, OSError) as error:
            raise ConnectorReadError(
                "calendar view was temporarily unavailable",
                kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
            ) from error
        if not isinstance(events, tuple) or not all(
            isinstance(event, CalendarEvent) for event in events
        ):
            raise ConnectorReadError(
                "calendar transport returned malformed events",
                kind=ReadFailureKind.MALFORMED,
            )
        current_events: dict[str, CalendarEvent] = {}
        current: dict[str, SourceObject] = {}
        for event in events:
            self._validate_event(event)
            source_id = event.source_object_id
            if source_id in current:
                raise ConnectorReadError(
                    "calendar view contained a duplicate event ID",
                    kind=ReadFailureKind.MALFORMED,
                )
            current_events[source_id] = event
            current[source_id] = self._source_object(event)
        changes: list[ObjectChange] = []
        for source_id, item in sorted(current.items()):
            old = previous.get(source_id)
            if old is None:
                changes.append(
                    ObjectChange(
                        source_id, ChangeType.CREATED, content_hash=item.content_hash
                    )
                )
            elif old.content_hash != item.content_hash:
                changes.append(
                    ObjectChange(
                        source_id,
                        ChangeType.UPDATED,
                        content_hash=item.content_hash,
                        previous_content_hash=old.content_hash,
                    )
                )
        for source_id, old in sorted(previous.items()):
            if source_id not in current:
                changes.append(
                    ObjectChange(
                        source_id,
                        ChangeType.DELETED,
                        previous_content_hash=old.content_hash,
                    )
                )
        objects = tuple(item for _, item in sorted(current.items()))
        self._events = current_events
        self._pending = _PendingRead(cursor, objects, tuple(changes))
        return objects, tuple(changes)

    def _validate_event(self, event: CalendarEvent) -> None:
        if event.calendar_id != self._scope.calendar_id:
            raise ConnectorReadError(
                "calendar event was outside the configured calendar",
                kind=ReadFailureKind.MALFORMED,
            )
        if event.end < self._scope.start or event.start > self._scope.end:
            raise ConnectorReadError(
                "calendar event was outside the configured view",
                kind=ReadFailureKind.MALFORMED,
            )

    def _source_object(self, event: CalendarEvent) -> SourceObject:
        content = normalize_event(event)
        return SourceObject(
            source_object_id=event.source_object_id,
            source_locator=self._locator(event),
            document_type=DocumentType.CALENDAR,
            content_hash=compute_content_hash(content),
            source_timestamp=event.modified_timestamp,
            project=self._scope.project,
            authority=self._scope.authority,
            trust=self._scope.trust,
        )

    def _fetched(self, event: CalendarEvent) -> FetchedDocument:
        content = normalize_event(event)
        return FetchedDocument(
            source_object_id=event.source_object_id,
            source_locator=self._locator(event),
            document_type=DocumentType.CALENDAR,
            content=content,
            content_hash=compute_content_hash(content),
            source_timestamp=event.modified_timestamp,
            project=self._scope.project,
            title=event.subject.strip() or "(no subject)",
            authority=self._scope.authority,
            trust=self._scope.trust,
        )

    def _locator(self, event: CalendarEvent) -> SourceLocator:
        return SourceLocator(
            connector_id=self.connector_id,
            uri="https://graph.microsoft.com/v1.0/me/events/"
            + quote(event.event_id, safe=""),
            label=event.subject.strip() or "(no subject)",
        )

    @staticmethod
    def _event_id(source_object_id: str) -> str:
        if (
            not isinstance(source_object_id, str)
            or not source_object_id.startswith(_EVENT_PREFIX)
            or len(source_object_id) == len(_EVENT_PREFIX)
        ):
            raise ConnectorReadError(
                "invalid calendar source object ID", kind=ReadFailureKind.MALFORMED
            )
        return source_object_id[len(_EVENT_PREFIX) :]

    @staticmethod
    def _cursor_object(item: SourceObject) -> dict[str, str]:
        return {
            "source_object_id": item.source_object_id,
            "content_hash": item.content_hash,
            "source_timestamp": item.source_timestamp.isoformat(),
            "uri": item.source_locator.uri,
            "label": item.source_locator.label or "",
        }

    def _decode_cursor(self, cursor: str | None) -> dict[str, SourceObject]:
        if cursor is None:
            return {}
        try:
            body = json.loads(cursor)
            if (
                not isinstance(body, Mapping)
                or body.get("schema_version") != _CURSOR_VERSION
            ):
                raise ValueError
            rows = body.get("objects")
            if not isinstance(rows, list):
                raise TypeError
            result: dict[str, SourceObject] = {}
            for row in rows:
                if not isinstance(row, Mapping):
                    raise TypeError
                source_id = row["source_object_id"]
                timestamp = datetime.fromisoformat(row["source_timestamp"])
                locator = SourceLocator(
                    self.connector_id, row["uri"], row.get("label") or None
                )
                item = SourceObject(
                    source_object_id=source_id,
                    source_locator=locator,
                    document_type=DocumentType.CALENDAR,
                    content_hash=row["content_hash"],
                    source_timestamp=timestamp,
                    project=self._scope.project,
                    authority=self._scope.authority,
                    trust=self._scope.trust,
                )
                if source_id in result:
                    raise ValueError
                result[source_id] = item
            return result
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ConnectorConfigError(
                "calendar cursor is malformed or unsupported"
            ) from error
