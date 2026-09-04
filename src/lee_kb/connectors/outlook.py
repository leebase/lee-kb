"""Offline-ready Outlook/Microsoft 365 mail connector adapter.

The connector owns provider-specific message identity, delta state, and email
normalization. Network transport and delegated authentication stay behind
``OutlookTransport`` so this slice can be tested without credentials or a live
Microsoft connection.

The bounded scope is one delegated ``/me`` mailbox folder per connector
instance. Message bodies are normalized as text, common quoted-history blocks
are removed, and attachment bodies are not indexed. Attachment identities and
conversation identities remain explicit relationships instead of being copied
into a second knowledge item.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable
from urllib.parse import quote, unquote, urlsplit

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
    "OutlookAttachment",
    "OutlookDeltaPage",
    "OutlookMessage",
    "OutlookScope",
    "OutlookTransport",
    "OutlookConnector",
    "normalize_message",
    "strip_quoted_history",
]

GRAPH_DELEGATED_SCOPE = "Mail.Read"
_CURSOR_VERSION = 2
_MESSAGE_PREFIX = "message:"
_OUTLOOK_WEB_HOSTS = frozenset(
    {"outlook.office.com", "outlook.office365.com", "outlook.live.com"}
)
_OUTLOOK_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9%._~+=-]+$")
_TOKEN_SHAPED_PATH = re.compile(
    r"^(?:sk-|gh[pousr]_|xox[baprs]-|eyj|akia)", re.IGNORECASE
)
_FORBIDDEN_PATH_SEGMENTS = frozenset(
    {
        "access_token",
        "authorization",
        "auth",
        "client_secret",
        "id_token",
        "password",
        "refresh_token",
        "secret",
        "sig",
        "signature",
        "token",
    }
)
_REPLY_HEADER = re.compile(r"^\s*On .+ wrote:\s*$", re.IGNORECASE)
_ORIGINAL_MESSAGE = re.compile(
    r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE
)
_QUOTED_LINE = re.compile(r"^\s*>")


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


def _require_tuple(values: object, name: str) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be a tuple")


@dataclass(frozen=True, slots=True)
class OutlookScope:
    """One explicit delegated mailbox-folder scope."""

    mailbox_owner: str
    folder_id: str
    folder_name: str | None = None
    project: str = DEFAULT_PROJECT
    authority: Authority = Authority.CANONICAL
    trust: Trust = Trust.HUMAN_AUTHORED
    account_id: str | None = None
    tenant: str | None = None
    credential_binding: str | None = None
    allowed_principals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.mailbox_owner, "mailbox_owner")
        _require_text(self.folder_id, "folder_id")
        _require_optional_text(self.folder_name, "folder_name")
        _require_text(self.project, "project")
        if not isinstance(self.authority, Authority):
            raise TypeError("authority must be an Authority")
        if not isinstance(self.trust, Trust):
            raise TypeError("trust must be a Trust")
        _require_optional_text(self.account_id, "account_id")
        _require_optional_text(self.tenant, "tenant")
        _require_optional_text(self.credential_binding, "credential_binding")
        _require_tuple(self.allowed_principals, "allowed_principals")
        for principal in self.allowed_principals:
            _require_text(principal, "allowed_principals entry")


@dataclass(frozen=True, slots=True)
class OutlookAttachment:
    """Attachment metadata retained as a relationship, never message body."""

    attachment_id: str
    name: str
    content_type: str = "application/octet-stream"
    size: int | None = None
    is_inline: bool = False

    def __post_init__(self) -> None:
        _require_text(self.attachment_id, "attachment_id")
        _require_text(self.name, "name")
        _require_text(self.content_type, "content_type")
        if self.size is not None:
            if not isinstance(self.size, int) or isinstance(self.size, bool):
                raise TypeError("size must be an int when present")
            if self.size < 0:
                raise ValueError("size must not be negative")
        if not isinstance(self.is_inline, bool):
            raise TypeError("is_inline must be a bool")


@dataclass(frozen=True, slots=True)
class OutlookMessage:
    """Normalized message data supplied by an Outlook transport."""

    message_id: str
    folder_id: str
    conversation_id: str
    subject: str
    sender: str
    to_recipients: tuple[str, ...]
    cc_recipients: tuple[str, ...]
    body_text: str
    sent_timestamp: datetime
    received_timestamp: datetime
    modified_timestamp: datetime
    web_link: str | None = None
    attachments: tuple[OutlookAttachment, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.message_id, "message_id")
        _require_text(self.folder_id, "folder_id")
        _require_text(self.conversation_id, "conversation_id")
        if not isinstance(self.subject, str):
            raise TypeError("subject must be a str")
        _require_text(self.sender, "sender")
        _require_tuple(self.to_recipients, "to_recipients")
        _require_tuple(self.cc_recipients, "cc_recipients")
        for recipient in (*self.to_recipients, *self.cc_recipients):
            _require_text(recipient, "recipient")
        if not isinstance(self.body_text, str):
            raise TypeError("body_text must be a str")
        _require_aware(self.sent_timestamp, "sent_timestamp")
        _require_aware(self.received_timestamp, "received_timestamp")
        _require_aware(self.modified_timestamp, "modified_timestamp")
        _require_optional_text(self.web_link, "web_link")
        _require_tuple(self.attachments, "attachments")
        if not all(isinstance(item, OutlookAttachment) for item in self.attachments):
            raise TypeError("attachments must contain OutlookAttachment values")
        attachment_ids = [item.attachment_id for item in self.attachments]
        if len(set(attachment_ids)) != len(attachment_ids):
            raise ValueError("attachment IDs must be unique within a message")

    @property
    def source_object_id(self) -> str:
        """Stable source identity based on the Graph immutable message ID."""
        return _message_source_id(self.message_id)


@dataclass(frozen=True, slots=True)
class OutlookDeltaPage:
    """One page from a folder delta response."""

    messages: tuple[OutlookMessage, ...] = ()
    removed_message_ids: tuple[str, ...] = ()
    next_link: str | None = None
    delta_link: str | None = None
    full_sync: bool = False
    event_order: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require_tuple(self.messages, "messages")
        if not all(isinstance(item, OutlookMessage) for item in self.messages):
            raise TypeError("messages must contain OutlookMessage values")
        _require_tuple(self.removed_message_ids, "removed_message_ids")
        for message_id in self.removed_message_ids:
            _require_text(message_id, "removed_message_id")
        message_ids = tuple(item.message_id for item in self.messages)
        if len(set(message_ids)) != len(message_ids):
            raise ValueError("message IDs must be unique within a delta page")
        if len(set(self.removed_message_ids)) != len(self.removed_message_ids):
            raise ValueError("removed message IDs must be unique within a delta page")
        if set(message_ids) & set(self.removed_message_ids):
            raise ValueError(
                "a delta page cannot contain both a message and its removal"
            )
        _require_optional_text(self.next_link, "next_link")
        _require_optional_text(self.delta_link, "delta_link")
        if self.next_link is not None and self.delta_link is not None:
            raise ValueError(
                "a delta page cannot contain both next_link and delta_link"
            )
        if not isinstance(self.full_sync, bool):
            raise TypeError("full_sync must be a bool")
        _require_tuple(self.event_order, "event_order")
        if self.event_order:
            message_ids_set = set(message_ids)
            removed_ids_set = set(self.removed_message_ids)
            seen_event_ids: set[str] = set()
            for source_id, event_type in self.event_order:
                _require_text(source_id, "event source ID")
                if event_type not in {"message", "removed"}:
                    raise ValueError("event type must be message or removed")
                if source_id in seen_event_ids:
                    raise ValueError("event_order must contain one final event per ID")
                seen_event_ids.add(source_id)
                if event_type == "message" and source_id not in message_ids_set:
                    raise ValueError(
                        "event_order message ID is not present on the page"
                    )
                if event_type == "removed" and source_id not in removed_ids_set:
                    raise ValueError(
                        "event_order removed ID is not present on the page"
                    )
            if seen_event_ids != message_ids_set | removed_ids_set:
                raise ValueError("event_order must cover every page event")


@runtime_checkable
class OutlookTransport(Protocol):
    """Provider boundary for Graph paging, fetch, and health checks."""

    def delta_page(self, folder_id: str, request: str | None) -> OutlookDeltaPage:
        """Return one initial or incremental page for ``folder_id``."""

    def fetch_message(self, message_id: str) -> OutlookMessage:
        """Fetch one complete normalized message by immutable ID."""

    def health(self, folder_id: str) -> tuple[bool, str]:
        """Return reachability and a safe diagnostic for one folder."""


def strip_quoted_history(body_text: str) -> str:
    """Remove common reply-history blocks from a plain-text message body.

    The first slice deliberately uses conservative markers. It removes a
    quoted-line block beginning with ``>`` and common Outlook/Gmail reply
    separators, but does not treat an arbitrary ``From:`` line as quoted text.
    The original message remains authoritative and can be fetched from Graph.
    """
    if not isinstance(body_text, str):
        raise TypeError("body_text must be a str")
    lines = body_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cutoff = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if (
            _QUOTED_LINE.match(line)
            or _REPLY_HEADER.match(line)
            or _ORIGINAL_MESSAGE.match(line)
        ):
            cutoff = index
            break
    return "\n".join(lines[:cutoff]).strip()


def _message_source_uri(message: OutlookMessage) -> str:
    if message.web_link and _safe_outlook_web_link(message.web_link):
        return message.web_link
    return "https://graph.microsoft.com/v1.0/me/messages/" + quote(
        message.message_id, safe=""
    )


def _safe_outlook_web_link(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    try:
        port = parts.port
    except ValueError:
        return False
    if (
        parts.scheme != "https"
        or parts.hostname not in _OUTLOOK_WEB_HOSTS
        or port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or "?" in value
        or "#" in value
        or not _safe_outlook_path(parts.path)
    ):
        return False
    return True


def _safe_outlook_path(path: str) -> bool:
    segments = path.strip("/").split("/")
    decoded_segments = [unquote(segment) for segment in segments]
    for segment, decoded in zip(segments, decoded_segments):
        if (
            not segment
            or not _OUTLOOK_PATH_SEGMENT.fullmatch(segment)
            or decoded.casefold() in _FORBIDDEN_PATH_SEGMENTS
            or _TOKEN_SHAPED_PATH.match(decoded)
            or any(character in decoded for character in "=/?#")
        ):
            return False
    return (
        segments[:2] in (["mail", "id"], ["mail", "message"])
        and len(segments) == 3
        or (
            len(segments) == 4
            and segments[:3] in (["mail", "deeplink", "read"], ["mail", "inbox", "id"])
        )
    )


def normalize_message(message: OutlookMessage) -> str:
    """Build the deterministic, non-duplicating text stored for one message."""
    subject = message.subject.strip() or "(no subject)"
    body = strip_quoted_history(message.body_text)
    lines = [
        f"Subject: {subject}",
        f"Source fingerprint: {compute_content_hash(_message_source_uri(message))}",
        f"From: {message.sender}",
        f"To: {', '.join(message.to_recipients) or '(none)'}",
    ]
    if message.cc_recipients:
        lines.append(f"Cc: {', '.join(message.cc_recipients)}")
    lines.extend(
        (
            f"Conversation: {message.conversation_id}",
            f"Sent: {message.sent_timestamp.isoformat()}",
            f"Received: {message.received_timestamp.isoformat()}",
            f"Modified: {message.modified_timestamp.isoformat()}",
            "",
            "Body:",
            body or "(empty)",
        )
    )
    if message.attachments:
        lines.extend(("", "Attachments:"))
        for attachment in sorted(
            message.attachments, key=lambda item: item.attachment_id
        ):
            inline = ", inline" if attachment.is_inline else ""
            size = f", {attachment.size} bytes" if attachment.size is not None else ""
            lines.append(
                f"- {attachment.name} ({attachment.content_type}{size}{inline}) "
                f"[{_attachment_relationship_id(message, attachment)}]"
            )
    return "\n".join(lines)


def _attachment_relationship_id(
    message: OutlookMessage, attachment: OutlookAttachment
) -> str:
    """Namespace provider-local attachment IDs by their parent message."""
    return f"attachment:{message.message_id}:{attachment.attachment_id}"


@dataclass(frozen=True, slots=True)
class _CursorState:
    delta_link: str | None
    objects: dict[str, SourceObject]


@dataclass(slots=True)
class _PendingRead:
    input_cursor: str | None
    objects: tuple[SourceObject, ...]
    changes: tuple[ObjectChange, ...]
    delta_link: str
    checkpointed: bool = False
    failed_fetches: set[str] = field(default_factory=set)


def _message_source_id(message_id: str) -> str:
    return f"{_MESSAGE_PREFIX}{message_id}"


def _message_id(source_object_id: str) -> str:
    if not source_object_id.startswith(_MESSAGE_PREFIX):
        raise ConnectorReadError(
            "malformed Outlook source object ID",
            kind=ReadFailureKind.MALFORMED,
        )
    message_id = source_object_id[len(_MESSAGE_PREFIX) :]
    if not message_id.strip():
        raise ConnectorReadError(
            "empty Outlook message ID",
            kind=ReadFailureKind.MALFORMED,
        )
    return message_id


class OutlookConnector(Connector):
    """A one-folder Outlook connector over an injected provider transport."""

    def __init__(
        self,
        scope: OutlookScope,
        transport: OutlookTransport,
        *,
        connector_id: str | None = None,
    ) -> None:
        if not isinstance(scope, OutlookScope):
            raise TypeError("scope must be an OutlookScope")
        if not isinstance(transport, OutlookTransport):
            raise TypeError("transport must implement OutlookTransport")
        self._scope = scope
        self._transport = transport
        transport_identity = {
            name: getattr(transport, name, None)
            for name in ("account_id", "user_id", "tenant", "credential_binding")
        }
        self._requires_bound_cursor = any(
            value is not None for value in transport_identity.values()
        )
        if self._requires_bound_cursor:
            if (
                scope.account_id != transport_identity["account_id"]
                or scope.tenant != transport_identity["tenant"]
                or scope.credential_binding != transport_identity["credential_binding"]
                or scope.mailbox_owner.casefold()
                != str(transport_identity["user_id"]).casefold()
            ):
                raise ConnectorConfigError(
                    "Outlook scope is not bound to the Graph account"
                )
        self._connector_id = (
            self._default_connector_id(scope) if connector_id is None else connector_id
        )
        if self._requires_bound_cursor and connector_id is not None:
            if connector_id != self._default_connector_id(scope):
                raise ConnectorConfigError(
                    "Graph Outlook connector_id must be derived from its account"
                )
        _require_text(self._connector_id, "connector_id")
        self._messages: dict[str, OutlookMessage] = {}
        self._pending: _PendingRead | None = None

    @staticmethod
    def _default_connector_id(scope: OutlookScope) -> str:
        owner = quote(
            scope.account_id or scope.mailbox_owner,
            safe="@._-",
        )
        folder = quote(scope.folder_id, safe="._-")
        project = quote(scope.project, safe="._-")
        binding = (
            f":{scope.credential_binding}"
            if scope.credential_binding is not None
            else ""
        )
        return f"outlook_mail:{owner}:{folder}:{project}{binding}"

    @property
    def connector_id(self) -> str:
        return self._connector_id

    @property
    def project(self) -> str:
        """Return the project associated with this one-folder connector."""
        return self._scope.project

    def discover(self) -> tuple[SourceObject, ...]:
        if self._pending is not None and not self._pending.checkpointed:
            return self._pending.objects
        objects, _changes = self._read(None)
        return objects

    def list_changes(self, cursor: str | None = None) -> tuple[ObjectChange, ...]:
        _objects, changes = self._read(cursor)
        return changes

    def fetch(self, source_object_id: str) -> FetchedDocument:
        pending = self._pending
        return self._fetch_document(
            source_object_id,
            validate_pending=pending is not None and not pending.checkpointed,
        )

    def permissions(self, source_object_id: str) -> PermissionSet:
        _message_id(source_object_id)
        return PermissionSet(
            owner=self._scope.mailbox_owner,
            visibility=Visibility.PRIVATE,
            allowed_principals=self._scope.allowed_principals,
            classification="delegated-mail-read",
        )

    def relationships(self, source_object_id: str) -> tuple[str, ...]:
        message = self._message_for_source_id(source_object_id)
        relationships: list[str] = [f"conversation:{message.conversation_id}"]
        relationships.extend(
            _attachment_relationship_id(message, attachment)
            for attachment in sorted(
                message.attachments, key=lambda item: item.attachment_id
            )
        )
        return tuple(relationships)

    def refresh(self, source_object_id: str) -> FetchedDocument:
        return self._fetch_document(source_object_id, validate_pending=False)

    def health(self) -> HealthStatus:
        checked_at = datetime.now(timezone.utc)
        try:
            healthy, _detail = self._transport.health(self._scope.folder_id)
        except ConnectorReadError as error:
            return HealthStatus(
                False,
                checked_at,
                detail=f"Outlook health check failed: {type(error).__name__}",
            )
        except (ConnectionError, TimeoutError, OSError) as error:
            return HealthStatus(
                False,
                checked_at,
                detail=(
                    f"Outlook transport temporarily unavailable: {type(error).__name__}"
                ),
            )
        except Exception as error:
            return HealthStatus(
                False,
                checked_at,
                detail=f"Outlook health check failed: {type(error).__name__}",
            )
        if not isinstance(healthy, bool) or not isinstance(_detail, str):
            return HealthStatus(
                False,
                checked_at,
                detail="Outlook transport returned an invalid health result",
            )
        scope_name = " ".join(
            (self._scope.folder_name or self._scope.folder_id).split()
        )
        status = "healthy" if healthy else "unhealthy"
        return HealthStatus(
            healthy,
            checked_at,
            detail=f"folder {scope_name}: transport {status}",
        )

    def checkpoint(self, objects: Sequence[SourceObject]) -> str:
        pending = self._pending
        if pending is None:
            raise ConnectorConfigError(
                "Outlook checkpoint requires a completed discovery or change pass"
            )
        if pending.failed_fetches:
            raise ConnectorConfigError(
                "Outlook checkpoint blocked by an unresolved message fetch failure"
            )
        normalized = tuple(objects)
        provided: dict[str, SourceObject] = {}
        for item in normalized:
            if not isinstance(item, SourceObject):
                raise ConnectorConfigError(
                    "Outlook checkpoint objects must be SourceObject values"
                )
            if item.source_object_id in provided:
                raise ConnectorConfigError(
                    "Outlook checkpoint objects contain a duplicate source ID"
                )
            provided[item.source_object_id] = item
        expected = {item.source_object_id: item for item in pending.objects}
        if provided != expected:
            raise ConnectorConfigError(
                "Outlook checkpoint objects do not match the completed pass"
            )
        cursor = self._encode_cursor(pending.delta_link, pending.objects)
        pending.checkpointed = True
        return cursor

    def _read(
        self, cursor: str | None
    ) -> tuple[tuple[SourceObject, ...], tuple[ObjectChange, ...]]:
        if self._pending is not None:
            if not self._pending.checkpointed and self._pending.input_cursor == cursor:
                return self._pending.objects, self._pending.changes
            if self._pending.failed_fetches:
                raise ConnectorConfigError(
                    "Outlook pass has an unresolved message fetch failure"
                )
            if self._pending.checkpointed:
                self._pending = None

        state = self._decode_cursor(cursor)
        previous = state.objects
        current = dict(previous)
        current_messages = {
            source_id: message
            for source_id, message in self._messages.items()
            if source_id in previous
        }
        changed_messages: dict[str, OutlookMessage] = {}
        removed_ids: set[str] = set()
        request = state.delta_link
        seen_requests: set[str] = set()
        first_page = True
        full_sync = False

        while True:
            if request is not None:
                if request in seen_requests:
                    raise ConnectorReadError(
                        "Outlook delta response repeated a continuation link",
                        kind=ReadFailureKind.MALFORMED,
                    )
                seen_requests.add(request)
            page = self._delta_page(request)
            if page.full_sync:
                if not first_page or cursor is None:
                    raise ConnectorReadError(
                        "Outlook full-sync marker appeared in an invalid delta page",
                        kind=ReadFailureKind.MALFORMED,
                    )
                # A delta token may expire after the connector has persisted a
                # good metadata snapshot.  The shared Graph client restarts a
                # complete enumeration and marks its first page; reconcile
                # that enumeration against the old snapshot instead of
                # retaining objects that disappeared during the rebuild.
                full_sync = True
                current.clear()
                current_messages.clear()
                changed_messages.clear()
                removed_ids.clear()
            messages_by_id = {message.message_id: message for message in page.messages}

            def apply_message(message: OutlookMessage) -> None:
                self._validate_scope(message)
                source_id = message.source_object_id
                current[source_id] = self._source_object(message)
                current_messages[source_id] = message
                changed_messages[source_id] = message
                removed_ids.discard(source_id)

            def apply_removal(message_id: str) -> None:
                source_id = _message_source_id(message_id)
                current.pop(source_id, None)
                current_messages.pop(source_id, None)
                changed_messages.pop(source_id, None)
                removed_ids.add(source_id)

            if page.event_order:
                for message_id, event_type in page.event_order:
                    if event_type == "message":
                        apply_message(messages_by_id[message_id])
                    else:
                        apply_removal(message_id)
            else:
                for message in page.messages:
                    apply_message(message)
                for message_id in page.removed_message_ids:
                    apply_removal(message_id)
            first_page = False
            if page.next_link is not None:
                request = page.next_link
                continue
            if page.delta_link is None:
                raise ConnectorReadError(
                    "Outlook delta response did not include a final delta link",
                    kind=ReadFailureKind.MALFORMED,
                )
            delta_link = page.delta_link
            break

        if full_sync:
            removed_ids.update(set(previous).difference(current))

        changes: list[ObjectChange] = []
        for source_id, message in sorted(
            changed_messages.items(), key=lambda item: item[0]
        ):
            content_hash = current[source_id].content_hash
            old = previous.get(source_id)
            if old is None:
                changes.append(
                    ObjectChange(
                        source_id,
                        ChangeType.CREATED,
                        content_hash=content_hash,
                    )
                )
            elif old.content_hash != content_hash:
                changes.append(
                    ObjectChange(
                        source_id,
                        ChangeType.UPDATED,
                        content_hash=content_hash,
                        previous_content_hash=old.content_hash,
                    )
                )
        for source_id in sorted(removed_ids):
            old = previous.get(source_id)
            if old is not None:
                changes.append(
                    ObjectChange(
                        source_id,
                        ChangeType.DELETED,
                        previous_content_hash=old.content_hash,
                    )
                )

        objects = tuple(
            sorted(current.values(), key=lambda item: item.source_object_id)
        )
        self._messages = current_messages
        self._pending = _PendingRead(
            input_cursor=cursor,
            objects=objects,
            changes=tuple(changes),
            delta_link=delta_link,
        )
        return objects, tuple(changes)

    def _delta_page(self, request: str | None) -> OutlookDeltaPage:
        try:
            page = self._transport.delta_page(self._scope.folder_id, request)
        except ConnectorReadError as error:
            raise ConnectorReadError(
                "Outlook delta request failed", kind=error.kind
            ) from None
        except (ConnectionError, TimeoutError, OSError):
            raise ConnectorReadError(
                "Outlook delta request temporarily failed",
                kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
            ) from None
        except ValueError:
            raise ConnectorReadError(
                "Outlook delta response was malformed",
                kind=ReadFailureKind.MALFORMED,
            ) from None
        except Exception:
            raise ConnectorReadError(
                "Outlook delta request failed",
                kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
            ) from None
        if not isinstance(page, OutlookDeltaPage):
            raise ConnectorReadError(
                "Outlook transport returned an invalid delta page",
                kind=ReadFailureKind.MALFORMED,
            )
        return page

    def _fetch_document(
        self, source_object_id: str, *, validate_pending: bool
    ) -> FetchedDocument:
        try:
            document = self._fetch_document_impl(
                source_object_id, validate_pending=validate_pending
            )
        except ConnectorReadError:
            self._record_fetch_failure(source_object_id, validate_pending)
            raise
        self._clear_fetch_failure(source_object_id, validate_pending)
        return document

    def _fetch_document_impl(
        self, source_object_id: str, *, validate_pending: bool
    ) -> FetchedDocument:
        message_id = _message_id(source_object_id)
        try:
            message = self._transport.fetch_message(message_id)
        except ConnectorReadError as error:
            raise ConnectorReadError(
                "Outlook message fetch failed", kind=error.kind
            ) from None
        except (ConnectionError, TimeoutError, OSError):
            raise ConnectorReadError(
                "Outlook message fetch temporarily failed",
                kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
            ) from None
        except ValueError:
            raise ConnectorReadError(
                "Outlook message response was malformed",
                kind=ReadFailureKind.MALFORMED,
            ) from None
        except Exception:
            raise ConnectorReadError(
                "Outlook message fetch failed",
                kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
            ) from None
        if not isinstance(message, OutlookMessage):
            raise ConnectorReadError(
                "Outlook transport returned an invalid message",
                kind=ReadFailureKind.MALFORMED,
            )
        self._validate_scope(message)
        if message.source_object_id != source_object_id:
            raise ConnectorReadError(
                "Outlook fetch returned a different message ID",
                kind=ReadFailureKind.MALFORMED,
            )
        normalized = normalize_message(message)
        content_hash = compute_content_hash(normalized)
        source_locator = self._source_locator(message)
        if validate_pending and self._pending is not None:
            expected = next(
                (
                    item
                    for item in self._pending.objects
                    if item.source_object_id == source_object_id
                ),
                None,
            )
            if expected is not None and (
                expected.content_hash != content_hash
                or expected.source_timestamp != message.modified_timestamp
                or expected.source_locator != source_locator
            ):
                raise ConnectorReadError(
                    "Outlook message changed during synchronization",
                    kind=ReadFailureKind.TEMPORARILY_INACCESSIBLE,
                )
        self._messages[source_object_id] = message
        return FetchedDocument(
            source_object_id=source_object_id,
            source_locator=source_locator,
            document_type=DocumentType.EMAIL,
            content=normalized,
            content_hash=content_hash,
            source_timestamp=message.modified_timestamp,
            project=self._scope.project,
            title=message.subject.strip() or "(no subject)",
            authority=self._scope.authority,
            trust=self._scope.trust,
        )

    def _record_fetch_failure(
        self, source_object_id: str, validate_pending: bool
    ) -> None:
        pending = self._pending
        if not validate_pending or pending is None or pending.checkpointed:
            return
        if any(item.source_object_id == source_object_id for item in pending.objects):
            pending.failed_fetches.add(source_object_id)

    def _clear_fetch_failure(
        self, source_object_id: str, validate_pending: bool
    ) -> None:
        pending = self._pending
        if not validate_pending or pending is None or pending.checkpointed:
            return
        pending.failed_fetches.discard(source_object_id)

    def _message_for_source_id(self, source_object_id: str) -> OutlookMessage:
        _message_id(source_object_id)
        message = self._messages.get(source_object_id)
        if message is not None:
            return message
        self._fetch_document(source_object_id, validate_pending=False)
        message = self._messages.get(source_object_id)
        if message is None:
            raise ConnectorReadError(
                "Outlook message was not cached after fetch",
                kind=ReadFailureKind.MALFORMED,
            )
        return message

    def _validate_scope(self, message: OutlookMessage) -> None:
        if message.folder_id != self._scope.folder_id:
            raise ConnectorReadError(
                "Outlook transport returned a message outside the configured folder",
                kind=ReadFailureKind.MALFORMED,
            )

    def _source_object(self, message: OutlookMessage) -> SourceObject:
        normalized = normalize_message(message)
        return SourceObject(
            source_object_id=message.source_object_id,
            source_locator=self._source_locator(message),
            document_type=DocumentType.EMAIL,
            content_hash=compute_content_hash(normalized),
            source_timestamp=message.modified_timestamp,
            project=self._scope.project,
            authority=self._scope.authority,
            trust=self._scope.trust,
        )

    def _source_locator(self, message: OutlookMessage) -> SourceLocator:
        return SourceLocator(
            connector_id=self._connector_id,
            uri=_message_source_uri(message),
            label=message.subject.strip() or message.message_id,
            fragment=message.message_id,
        )

    def _verified_provider_identity(self) -> tuple[str, str]:
        if not self._requires_bound_cursor:
            raise ConnectorConfigError(
                "verified provider identity is unavailable for this transport"
            )
        subject = getattr(self._transport, "verified_subject", None)
        tenant = getattr(self._transport, "verified_tenant", None)
        if not isinstance(subject, str) or not subject.strip():
            raise ConnectorConfigError(
                "Graph Outlook account identity must be verified before checkpointing"
            )
        if not isinstance(tenant, str) or not tenant.strip():
            raise ConnectorConfigError(
                "Graph Outlook tenant identity must be verified before checkpointing"
            )
        return subject.casefold(), tenant.casefold()

    def _decode_cursor(self, cursor: str | None) -> _CursorState:
        if cursor is None:
            return _CursorState(delta_link=None, objects={})
        if self._requires_bound_cursor and (
            self._scope.account_id is None
            or self._scope.tenant is None
            or self._scope.credential_binding is None
        ):
            raise ConnectorConfigError(
                "Graph Outlook cursors require account binding metadata"
            )
        try:
            raw = json.loads(cursor)
        except (TypeError, json.JSONDecodeError) as error:
            raise ConnectorConfigError(f"invalid Outlook cursor: {error}") from error
        if not isinstance(raw, dict) or raw.get("version") != _CURSOR_VERSION:
            raise ConnectorConfigError("invalid Outlook cursor version")
        if raw.get("folder_id") != self._scope.folder_id:
            raise ConnectorConfigError("Outlook cursor belongs to a different folder")
        if raw.get("project") != self._scope.project:
            raise ConnectorConfigError("Outlook cursor belongs to a different project")
        if raw.get("connector_id") != self._connector_id:
            raise ConnectorConfigError(
                "Outlook cursor belongs to a different connector"
            )
        cursor_mailbox_owner = raw.get("mailbox_owner")
        if cursor_mailbox_owner != self._scope.mailbox_owner:
            raise ConnectorConfigError("Outlook cursor belongs to a different mailbox")
        for name, expected in (
            ("account_id", self._scope.account_id),
            ("tenant", self._scope.tenant),
            ("credential_binding", self._scope.credential_binding),
        ):
            if raw.get(name) != expected:
                raise ConnectorConfigError(
                    f"Outlook cursor belongs to a different {name}"
                )
        if self._requires_bound_cursor:
            verified_subject, verified_tenant = self._verified_provider_identity()
            if raw.get("verified_subject") != verified_subject:
                raise ConnectorConfigError(
                    "Outlook cursor belongs to a different provider subject"
                )
            if raw.get("verified_tenant") != verified_tenant:
                raise ConnectorConfigError(
                    "Outlook cursor belongs to a different provider tenant"
                )
        delta_link = raw.get("delta_link")
        if not isinstance(delta_link, str) or not delta_link.strip():
            raise ConnectorConfigError("invalid Outlook cursor delta link")
        raw_objects = raw.get("objects")
        if not isinstance(raw_objects, dict):
            raise ConnectorConfigError("invalid Outlook cursor objects")
        objects: dict[str, SourceObject] = {}
        for source_id, record in raw_objects.items():
            if not isinstance(source_id, str) or not isinstance(record, dict):
                raise ConnectorConfigError("invalid Outlook cursor object record")
            objects[source_id] = self._object_from_cursor(source_id, record)
        return _CursorState(delta_link=delta_link, objects=objects)

    def _object_from_cursor(
        self, source_object_id: str, record: dict[str, object]
    ) -> SourceObject:
        try:
            _message_id(source_object_id)
            content_hash = record["content_hash"]
            source_timestamp_value = record["source_timestamp"]
            uri = record["uri"]
            label = record["label"]
            fragment = record["fragment"]
            if not isinstance(content_hash, str):
                raise TypeError("content_hash must be a string")
            if not isinstance(source_timestamp_value, str):
                raise TypeError("source_timestamp must be a string")
            if not isinstance(uri, str):
                raise TypeError("uri must be a string")
            if label is not None and not isinstance(label, str):
                raise TypeError("label must be a string or null")
            if fragment is not None and not isinstance(fragment, str):
                raise TypeError("fragment must be a string or null")
            source_timestamp = datetime.fromisoformat(source_timestamp_value)
            source_locator = SourceLocator(
                connector_id=self._connector_id,
                uri=uri,
                label=label,
                fragment=fragment,
            )
            return SourceObject(
                source_object_id=source_object_id,
                source_locator=source_locator,
                document_type=DocumentType.EMAIL,
                content_hash=content_hash,
                source_timestamp=source_timestamp,
                project=self._scope.project,
                authority=self._scope.authority,
                trust=self._scope.trust,
            )
        except (ConnectorReadError, KeyError, TypeError, ValueError) as error:
            raise ConnectorConfigError(
                "invalid Outlook cursor object metadata"
            ) from error

    def _encode_cursor(self, delta_link: str, objects: Sequence[SourceObject]) -> str:
        verified_subject = None
        verified_tenant = None
        if self._requires_bound_cursor:
            verified_subject, verified_tenant = self._verified_provider_identity()
        payload = {
            "version": _CURSOR_VERSION,
            "connector_id": self._connector_id,
            "folder_id": self._scope.folder_id,
            "project": self._scope.project,
            "mailbox_owner": self._scope.mailbox_owner,
            "account_id": self._scope.account_id,
            "tenant": self._scope.tenant,
            "credential_binding": self._scope.credential_binding,
            "verified_subject": verified_subject,
            "verified_tenant": verified_tenant,
            "delta_link": delta_link,
            "objects": {
                item.source_object_id: {
                    "content_hash": item.content_hash,
                    "source_timestamp": item.source_timestamp.isoformat(),
                    "uri": item.source_locator.uri,
                    "label": item.source_locator.label,
                    "fragment": item.source_locator.fragment,
                }
                for item in objects
            },
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))
