"""Microsoft Graph mapping for the read-only calendar connector."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import quote

from ..microsoft_graph import GraphClient, GraphError, GraphErrorCode
from .base import ConnectorReadError, ReadFailureKind
from .calendar import CalendarEvent, CalendarScope, CalendarTransport

__all__ = ["GraphCalendarTransport"]

_EVENT_SELECT = (
    "id,subject,body,start,end,lastModifiedDateTime,organizer,attendees,"
    "location,isAllDay,isCancelled,seriesMasterId"
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class GraphCalendarTransport(CalendarTransport):
    """Map one delegated Graph calendar view into ``CalendarTransport``."""

    def __init__(self, client: GraphClient, *, page_size: int = 50) -> None:
        if not isinstance(client, GraphClient):
            raise TypeError("client must be a GraphClient")
        if (
            not isinstance(page_size, int)
            or isinstance(page_size, bool)
            or page_size < 1
        ):
            raise ValueError("page_size must be positive")
        scopes = {scope.casefold() for scope in client.credential.scopes}
        if scopes != {"calendars.read", "user.read"}:
            raise ValueError(
                "Graph calendar transport requires exactly Calendars.Read and User.Read"
            )
        self._client = client
        self._page_size = page_size

    def list_events(self, scope: CalendarScope) -> tuple[CalendarEvent, ...]:
        request: str | None = self._view_url(scope)
        seen: set[str] = set()
        events: dict[str, CalendarEvent] = {}
        try:
            while request is not None:
                if request in seen:
                    raise ConnectorReadError(
                        "calendar Graph response repeated a continuation link",
                        kind=ReadFailureKind.MALFORMED,
                    )
                seen.add(request)
                page = self._client.collection_page(request, headers=self._headers())
                for value in page.values:
                    event = _event_from_graph(
                        value, expected_calendar=scope.calendar_id
                    )
                    if event.event_id in events:
                        raise ConnectorReadError(
                            "calendar Graph view contained a duplicate event ID",
                            kind=ReadFailureKind.MALFORMED,
                        )
                    events[event.event_id] = event
                request = page.next_link
        except GraphError as error:
            raise _connector_error(
                "calendar Graph view request failed", error
            ) from None
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            raise ConnectorReadError(
                "calendar Graph view response was malformed",
                kind=ReadFailureKind.MALFORMED,
            ) from None
        return tuple(events[event_id] for event_id in sorted(events))

    def fetch_event(self, event_id: str, calendar_id: str) -> CalendarEvent:
        try:
            payload = self._client.get_json(
                f"/me/calendars/{quote(calendar_id, safe='')}/events/"
                f"{quote(event_id, safe='')}?$select={quote(_EVENT_SELECT, safe=',')}",
                headers=self._headers(),
            )
            if not isinstance(payload, Mapping):
                raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
            return _event_from_graph(payload, expected_calendar=calendar_id)
        except GraphError as error:
            raise _connector_error("calendar Graph event fetch failed", error) from None
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            raise ConnectorReadError(
                "calendar Graph event response was malformed",
                kind=ReadFailureKind.MALFORMED,
            ) from None

    def health(self, calendar_id: str) -> tuple[bool, str]:
        try:
            self._client.verify_account()
            payload = self._client.get_json(
                f"/me/calendars/{quote(calendar_id, safe='')}?$select=id",
                headers=self._headers(),
            )
            if not isinstance(payload, Mapping) or payload.get("id") != calendar_id:
                return False, "Graph returned an invalid calendar health response"
            return True, "Graph calendar access is available"
        except GraphError as error:
            return False, f"Graph calendar health failed: {error.code.value}"

    def _view_url(self, scope: CalendarScope) -> str:
        start = quote(scope.start.isoformat(), safe="")
        end = quote(scope.end.isoformat(), safe="")
        return (
            f"/me/calendars/{quote(scope.calendar_id, safe='')}/calendarView"
            f"?startDateTime={start}&endDateTime={end}"
            f"&$select={quote(_EVENT_SELECT, safe=',')}&$top={self._page_size}"
        )

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Prefer": 'IdType="ImmutableId", outlook.timezone="UTC"',
        }


def _connector_error(message: str, error: GraphError) -> ConnectorReadError:
    if error.code in {
        GraphErrorCode.NETWORK,
        GraphErrorCode.THROTTLED,
        GraphErrorCode.TRANSIENT,
        GraphErrorCode.AUTHENTICATION,
        GraphErrorCode.AUTHORIZATION,
    }:
        kind = ReadFailureKind.TEMPORARILY_INACCESSIBLE
    elif error.code is GraphErrorCode.NOT_FOUND:
        kind = ReadFailureKind.UNREADABLE
    else:
        kind = ReadFailureKind.MALFORMED
    return ConnectorReadError(message, kind=kind)


def _event_from_graph(
    value: Mapping[str, object], *, expected_calendar: str | None
) -> CalendarEvent:
    return CalendarEvent(
        event_id=_required_text(value.get("id"), "id"),
        calendar_id=expected_calendar
        or _required_text(value.get("calendarId"), "calendarId"),
        subject=_optional_text(value.get("subject")),
        start=_graph_datetime(value.get("start"), "start"),
        end=_graph_datetime(value.get("end"), "end"),
        modified_timestamp=_timestamp(
            value.get("lastModifiedDateTime"), "lastModifiedDateTime"
        ),
        organizer=_email(value.get("organizer")),
        attendees=_attendees(value.get("attendees")),
        location=_location(value.get("location")),
        body_text=_body_text(value.get("body")),
        is_all_day=_bool(value.get("isAllDay", False), "isAllDay"),
        is_cancelled=_bool(value.get("isCancelled", False), "isCancelled"),
        series_master_id=_optional_text_or_none(value.get("seriesMasterId")),
    )


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _optional_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _timestamp(value: object, name: str) -> datetime:
    text = _required_text(value, name)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include an offset")
    return parsed


def _graph_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    text = _required_text(value.get("dateTime"), f"{name}.dateTime")
    zone = _required_text(value.get("timeZone"), f"{name}.timeZone")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if zone.casefold() not in {"utc", "etc/utc"}:
            raise ValueError(f"{name} was not normalized to UTC")
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _email(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    address = value.get("emailAddress")
    if not isinstance(address, Mapping):
        return None
    email_address = address.get("address")
    return (
        email_address
        if isinstance(email_address, str) and email_address.strip()
        else None
    )


def _attendees(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError("attendees must be a list")
    result: list[str] = []
    for attendee in value:
        address = _email(attendee)
        if address:
            result.append(address)
    return tuple(result)


def _location(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    name = value.get("displayName")
    return name if isinstance(name, str) and name.strip() else None


def _body_text(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    content = value.get("content")
    if not isinstance(content, str):
        return ""
    content_type = value.get("contentType")
    if isinstance(content_type, str) and content_type.casefold() == "html":
        parser = _TextExtractor()
        parser.feed(content)
        return html.unescape(" ".join(parser.parts)).strip()
    return content.strip()


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")
    return value
