"""Microsoft Graph mapping for the provider-neutral Outlook connector.

This module only translates Graph message resources.  Authentication, HTTP,
retry, throttling, pacing, pagination, and delta-expiry recovery are owned by
``lee_kb.microsoft_graph.GraphClient``.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import quote

from ..microsoft_graph import GraphClient, GraphDeltaResult, GraphError, GraphErrorCode
from .base import ConnectorReadError, ReadFailureKind
from .outlook import (
    OutlookAttachment,
    OutlookDeltaPage,
    OutlookMessage,
    OutlookTransport,
)

__all__ = ["GraphOutlookTransport"]

_MESSAGE_SELECT = ",".join(
    (
        "id",
        "parentFolderId",
        "conversationId",
        "subject",
        "from",
        "toRecipients",
        "ccRecipients",
        "body",
        "sentDateTime",
        "receivedDateTime",
        "lastModifiedDateTime",
        "webLink",
    )
)
_ATTACHMENT_EXPAND = "$expand=attachments($select=id,name,contentType,size,isInline)"


class GraphOutlookTransport(OutlookTransport):
    """Map one delegated Graph mailbox folder into ``OutlookTransport``."""

    def __init__(
        self,
        client: GraphClient,
        *,
        page_size: int = 50,
    ) -> None:
        if not isinstance(client, GraphClient):
            raise TypeError("client must be a GraphClient")
        if not isinstance(page_size, int) or page_size < 1:
            raise ValueError("page_size must be positive")
        scopes = {scope.casefold() for scope in client.credential.scopes}
        if scopes != {"mail.read", "user.read"}:
            raise ValueError(
                "Graph Outlook transport requires exactly Mail.Read and User.Read"
            )
        self._client = client
        self._page_size = page_size

    @property
    def account_id(self) -> str:
        return self._client.credential.account.account_id

    @property
    def user_id(self) -> str:
        return self._client.credential.account.user_id

    @property
    def tenant(self) -> str:
        return self._client.credential.account.tenant

    @property
    def credential_binding(self) -> str:
        return self._client.credential.binding

    @property
    def verified_subject(self) -> str | None:
        return self._client.verified_identity()[0]

    @property
    def verified_tenant(self) -> str | None:
        return self._client.verified_identity()[1]

    def delta_page(self, folder_id: str, request: str | None) -> OutlookDeltaPage:
        initial_url = self._delta_url(folder_id)
        try:
            result = self._client.delta_round(
                initial_url,
                request,
                headers=self._headers(),
            )
            return self._map_delta(result, folder_id)
        except GraphError as error:
            raise _connector_error(
                "Outlook Graph delta request failed", error
            ) from None

    def fetch_message(self, message_id: str) -> OutlookMessage:
        try:
            payload = self._client.get_json(
                f"/me/messages/{quote(message_id, safe='')}"
                f"?$select={quote(_MESSAGE_SELECT, safe=',')}"
                f"&{quote(_ATTACHMENT_EXPAND, safe='$=(),,')}",
                headers={
                    **self._headers(),
                    "Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"',
                },
            )
            if not isinstance(payload, Mapping):
                raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
            return _message_from_graph(payload, expected_folder=None)
        except GraphError as error:
            raise _connector_error(
                "Outlook Graph message fetch failed", error
            ) from None
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            raise ConnectorReadError(
                "Outlook Graph message response was malformed",
                kind=ReadFailureKind.MALFORMED,
            ) from None

    def health(self, folder_id: str) -> tuple[bool, str]:
        try:
            self._client.verify_account()
            payload = self._client.get_json(
                f"/me/mailFolders/{quote(folder_id, safe='')}?$select=id",
                headers=self._headers(),
            )
            if not isinstance(payload, Mapping) or payload.get("id") != folder_id:
                return False, "Graph returned an invalid mailbox-folder health response"
            return True, "Graph mailbox-folder access is available"
        except GraphError as error:
            return False, f"Graph mailbox-folder health failed: {error.code.value}"

    def _delta_url(self, folder_id: str) -> str:
        return (
            f"/me/mailFolders/{quote(folder_id, safe='')}/messages/delta"
            f"?$select={quote(_MESSAGE_SELECT, safe=',')}&$top={self._page_size}"
            f"&{quote(_ATTACHMENT_EXPAND, safe='$=(),,')}"
        )

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"',
        }

    def _map_delta(self, result: GraphDeltaResult, folder_id: str) -> OutlookDeltaPage:
        events: dict[str, Mapping[str, object]] = {}
        for value in result.values:
            message_id = value.get("id")
            if not isinstance(message_id, str) or not message_id.strip():
                raise ConnectorReadError(
                    "Outlook Graph delta event was malformed",
                    kind=ReadFailureKind.MALFORMED,
                )
            # A complete aggregated round can contain multiple events for one
            # immutable ID. Keep only the final event while retaining its
            # response order, so a later move-out/removal wins.
            if message_id in events:
                del events[message_id]
            events[message_id] = value
        messages: list[OutlookMessage] = []
        removed: list[str] = []
        event_order: list[tuple[str, str]] = []
        for message_id, value in events.items():
            if "@removed" in value:
                removed.append(message_id)
                event_order.append((message_id, "removed"))
            else:
                messages.append(_message_from_graph(value, expected_folder=folder_id))
                event_order.append((message_id, "message"))
        return OutlookDeltaPage(
            messages=tuple(messages),
            removed_message_ids=tuple(removed),
            delta_link=result.delta_link,
            full_sync=result.reset,
            event_order=tuple(event_order),
        )


def _connector_error(message: str, error: GraphError) -> ConnectorReadError:
    if error.code in {
        GraphErrorCode.NETWORK,
        GraphErrorCode.THROTTLED,
        GraphErrorCode.TRANSIENT,
        GraphErrorCode.AUTHENTICATION,
        GraphErrorCode.AUTHORIZATION,
        GraphErrorCode.DELTA_EXPIRED,
    }:
        kind = ReadFailureKind.TEMPORARILY_INACCESSIBLE
    elif error.code is GraphErrorCode.NOT_FOUND:
        kind = ReadFailureKind.UNREADABLE
    else:
        kind = ReadFailureKind.MALFORMED
    return ConnectorReadError(message, kind=kind)


def _message_from_graph(
    value: Mapping[str, object], *, expected_folder: str | None
) -> OutlookMessage:
    message_id = _required_text(value.get("id"), "id")
    folder_id = _required_text(
        value.get("parentFolderId", expected_folder), "parentFolderId"
    )
    if expected_folder is not None and folder_id != expected_folder:
        raise ConnectorReadError(
            "Outlook Graph message was outside the configured folder",
            kind=ReadFailureKind.MALFORMED,
        )
    sender = _address(value.get("from")) or "(unknown sender)"
    return OutlookMessage(
        message_id=message_id,
        folder_id=folder_id,
        conversation_id=_required_text(
            value.get("conversationId", message_id), "conversationId"
        ),
        subject=_optional_text(value.get("subject")),
        sender=sender,
        to_recipients=_addresses(value.get("toRecipients")),
        cc_recipients=_addresses(value.get("ccRecipients")),
        attachments=_attachments(value.get("attachments")),
        body_text=_body_text(value.get("body")),
        sent_timestamp=_timestamp(value.get("sentDateTime"), "sentDateTime"),
        received_timestamp=_timestamp(
            value.get("receivedDateTime"), "receivedDateTime"
        ),
        modified_timestamp=_timestamp(
            value.get("lastModifiedDateTime"), "lastModifiedDateTime"
        ),
        web_link=_optional_text_or_none(value.get("webLink")),
    )


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConnectorReadError(
            f"Outlook Graph response missing {name}",
            kind=ReadFailureKind.MALFORMED,
        )
    return value


def _optional_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = _optional_text(value)
    return text or None


def _address(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    nested = value.get("emailAddress")
    if not isinstance(nested, Mapping):
        return None
    address = nested.get("address")
    name = nested.get("name")
    if isinstance(address, str) and address.strip():
        return address.strip()
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _addresses(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConnectorReadError(
            "Outlook Graph recipients were malformed",
            kind=ReadFailureKind.MALFORMED,
        )
    addresses = tuple(address for item in value if (address := _address(item)))
    if len(addresses) != len(value):
        raise ConnectorReadError(
            "Outlook Graph recipients were malformed",
            kind=ReadFailureKind.MALFORMED,
        )
    return addresses


def _attachments(value: object) -> tuple[OutlookAttachment, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConnectorReadError(
            "Outlook Graph attachments were malformed",
            kind=ReadFailureKind.MALFORMED,
        )
    attachments: list[OutlookAttachment] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ConnectorReadError(
                "Outlook Graph attachments were malformed",
                kind=ReadFailureKind.MALFORMED,
            )
        attachment_id = _required_text(item.get("id"), "attachment id")
        name = _required_text(item.get("name"), "attachment name")
        content_type = item.get("contentType", "application/octet-stream")
        if not isinstance(content_type, str) or not content_type.strip():
            raise ConnectorReadError(
                "Outlook Graph attachment type was malformed",
                kind=ReadFailureKind.MALFORMED,
            )
        size = item.get("size")
        if size is not None and (
            not isinstance(size, int) or isinstance(size, bool) or size < 0
        ):
            raise ConnectorReadError(
                "Outlook Graph attachment size was malformed",
                kind=ReadFailureKind.MALFORMED,
            )
        is_inline = item.get("isInline", False)
        if not isinstance(is_inline, bool):
            raise ConnectorReadError(
                "Outlook Graph attachment inline flag was malformed",
                kind=ReadFailureKind.MALFORMED,
            )
        attachments.append(
            OutlookAttachment(
                attachment_id=attachment_id,
                name=name,
                content_type=content_type,
                size=size,
                is_inline=is_inline,
            )
        )
    return tuple(attachments)


def _body_text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, Mapping):
        raise ConnectorReadError(
            "Outlook Graph body was malformed",
            kind=ReadFailureKind.MALFORMED,
        )
    content = value.get("content", "")
    if not isinstance(content, str):
        raise ConnectorReadError(
            "Outlook Graph body was malformed",
            kind=ReadFailureKind.MALFORMED,
        )
    content_type = value.get("contentType", "text")
    if isinstance(content_type, str) and content_type.lower() == "html":
        return _html_to_text(content)
    return content


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {
            "br",
            "p",
            "div",
            "li",
            "tr",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")


def _html_to_text(content: str) -> str:
    parser = _TextHTMLParser()
    try:
        parser.feed(content)
        parser.close()
    except (ValueError, AssertionError):
        raise ConnectorReadError(
            "Outlook Graph HTML body was malformed",
            kind=ReadFailureKind.MALFORMED,
        ) from None
    text = html.unescape("".join(parser.parts))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ConnectorReadError(
            f"Outlook Graph response missing {name}",
            kind=ReadFailureKind.MALFORMED,
        )
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ConnectorReadError(
            f"Outlook Graph response had an invalid {name}",
            kind=ReadFailureKind.MALFORMED,
        ) from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ConnectorReadError(
            f"Outlook Graph response had an invalid {name}",
            kind=ReadFailureKind.MALFORMED,
        )
    return timestamp
