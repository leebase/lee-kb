"""Focused Microsoft Graph foundation, lifecycle, and live-Outlook tests."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from lee_kb.connectors.base import ConnectorConfigError
from lee_kb.connectors.outlook import (
    OutlookConnector,
    OutlookScope,
    _message_source_uri,
    normalize_message,
)
from lee_kb.connectors.outlook_graph import GraphOutlookTransport
from lee_kb.contracts import KnowledgeItemId
from lee_kb.main import _outlook_connector_from_config, _sync_external_connector
from lee_kb.microsoft_graph import (
    CredentialRevokedError,
    CredentialUnavailableError,
    EncryptedFileTokenStore,
    GraphClient,
    GraphCredential,
    GraphDeltaResult,
    GraphError,
    GraphErrorCode,
    HttpResponse,
    InMemoryTokenStore,
    MicrosoftAccount,
    OAuthTokenManager,
    RetryPolicy,
    SpacingRateLimiter,
    TokenSet,
)
from lee_kb.microsoft_graph.http import _NoRedirectHandler
from lee_kb.repository import SQLiteRepository

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def credential() -> GraphCredential:
    return GraphCredential(
        MicrosoftAccount("personal", "lee@example.test"),
        client_id="client-id",
        scopes=("Mail.Read", "User.Read"),
    )


def response(status: int, payload: object, headers: dict[str, str] | None = None):
    return HttpResponse(
        status,
        headers or {},
        json.dumps(payload).encode("utf-8"),
    )


class ScriptedHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(self, method, url, *, headers, body=None, timeout=30.0):
        self.calls.append((method, url, dict(headers), body))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        response_value = self.responses.pop(0)
        if isinstance(response_value, BaseException):
            raise response_value
        return response_value


class StaticTokenManager:
    def __init__(self, *tokens: str):
        self.tokens = list(tokens)
        self.index = 0
        self.forced: list[bool] = []

    def access_token(self, *, force_refresh=False):
        self.forced.append(force_refresh)
        if force_refresh and self.index + 1 < len(self.tokens):
            self.index += 1
        return self.tokens[self.index]


def token(
    access: str = "access-old",
    refresh: str | None = "refresh-old",
    expires: datetime = NOW + timedelta(hours=1),
) -> TokenSet:
    return TokenSet(
        access_token=access,
        refresh_token=refresh,
        expires_at=expires,
        scopes=("Mail.Read", "User.Read"),
        credential_binding=credential().binding,
        verified_subject=credential().account.user_id.casefold(),
        verified_tenant=credential().account.tenant.casefold(),
    )


def graph_message(message_id: str = "immutable-1", *, body: str = "Launch Friday"):
    return {
        "id": message_id,
        "parentFolderId": "folder-inbox",
        "conversationId": "conversation-1",
        "subject": "Launch review",
        "from": {"emailAddress": {"address": "sender@example.test"}},
        "toRecipients": [
            {"emailAddress": {"address": "lee@example.test"}},
        ],
        "ccRecipients": [],
        "body": {"contentType": "text", "content": body},
        "sentDateTime": "2026-08-05T11:00:00Z",
        "receivedDateTime": "2026-08-05T11:01:00Z",
        "lastModifiedDateTime": "2026-08-05T11:02:00Z",
        "webLink": "https://outlook.office.com/mail/id/immutable-1",
    }


def make_graph_client(http: ScriptedHttp, manager=None, **kwargs) -> GraphClient:
    client = GraphClient(
        credential(),
        token_manager=manager or StaticTokenManager("access-token"),
        http=http,
        sleep=lambda _delay: None,
        retry_policy=RetryPolicy(
            max_attempts=kwargs.pop("max_attempts", 4), base_delay=0
        ),
        **kwargs,
    )
    # Most transport tests focus on resource mapping and inject a token that
    # has already passed the account-binding probe. Dedicated verification
    # tests below exercise the first-use check.
    client._account_verified = True
    client._verified_token = (
        manager.tokens[manager.index]
        if isinstance(manager, StaticTokenManager)
        else "access-token"
    )
    client._verified_subject = credential().account.user_id.casefold()
    client._verified_tenant = credential().account.tenant.casefold()
    return client


def test_token_repr_and_encrypted_file_store_never_write_plaintext(tmp_path) -> None:
    token_store = EncryptedFileTokenStore(tmp_path / "tokens.json", b"k" * 32)
    token_store.save("personal", token())

    raw = (tmp_path / "tokens.json").read_text()
    assert "access-old" not in raw
    assert "refresh-old" not in raw
    assert oct(os.stat(tmp_path / "tokens.json").st_mode & 0o777) == "0o600"
    assert "access-old" not in repr(token())
    assert token_store.load("personal") == token()


def test_unsafe_outlook_web_link_falls_back_to_canonical_graph_locator() -> None:
    from lee_kb.connectors.outlook_graph import _message_from_graph

    message = _message_from_graph(
        {
            **graph_message(),
            "webLink": "https://outlook.office.com/mail?access_token=secret",
        },
        expected_folder="folder-inbox",
    )

    normalized = normalize_message(message)
    assert "access_token=secret" not in normalized
    assert _message_source_uri(message) == (
        "https://graph.microsoft.com/v1.0/me/messages/immutable-1"
    )


def test_outlook_web_link_fragment_is_not_persisted() -> None:
    from lee_kb.connectors.outlook_graph import _message_from_graph

    message = _message_from_graph(
        {
            **graph_message(),
            "webLink": "https://outlook.office.com/mail/id/immutable-1#access_token=secret",
        },
        expected_folder="folder-inbox",
    )

    assert _message_source_uri(message) == (
        "https://graph.microsoft.com/v1.0/me/messages/immutable-1"
    )


def test_outlook_web_link_with_credential_shaped_path_is_not_persisted() -> None:
    from lee_kb.connectors.outlook_graph import _message_from_graph

    message = _message_from_graph(
        {
            **graph_message(),
            "webLink": "https://outlook.office.com/mail/token/secret",
        },
        expected_folder="folder-inbox",
    )

    assert _message_source_uri(message) == (
        "https://graph.microsoft.com/v1.0/me/messages/immutable-1"
    )


def test_outlook_web_link_with_encoded_credential_path_is_not_persisted() -> None:
    from lee_kb.connectors.outlook_graph import _message_from_graph

    message = _message_from_graph(
        {
            **graph_message(),
            "webLink": "https://outlook.office.com/mail/id/access%5Ftoken%3Dsecret",
        },
        expected_folder="folder-inbox",
    )

    assert _message_source_uri(message) == (
        "https://graph.microsoft.com/v1.0/me/messages/immutable-1"
    )


def test_outlook_web_link_with_token_shaped_path_is_not_persisted() -> None:
    from lee_kb.connectors.outlook_graph import _message_from_graph

    token_path = "sk-" + "a" * 20
    message = _message_from_graph(
        {
            **graph_message(),
            "webLink": f"https://outlook.office.com/mail/id/{token_path}",
        },
        expected_folder="folder-inbox",
    )

    assert _message_source_uri(message) == (
        "https://graph.microsoft.com/v1.0/me/messages/immutable-1"
    )


def test_outlook_config_cannot_assign_mailbox_content_to_another_owner() -> None:
    config = {
        "microsoft_graph": {
            "client_id": "client-id",
            "accounts": {"personal": {"user_id": "lee@example.test"}},
        },
        "outlook": {
            "inbox": {
                "account": "personal",
                "folder_id": "folder-inbox",
                "mailbox_owner": "mallory@example.test",
            }
        },
    }

    with pytest.raises(ConnectorConfigError, match="mailbox_owner"):
        _outlook_connector_from_config(config, "inbox")


def test_outlook_config_derives_owner_and_connector_identity_from_account() -> None:
    config = {
        "microsoft_graph": {
            "client_id": "client-id",
            "accounts": {"personal": {"user_id": "lee@example.test"}},
        },
        "outlook": {
            "inbox": {
                "account": "personal",
                "folder_id": "folder-inbox",
                "mailbox_owner": "LEE@example.test",
            }
        },
    }

    connector, _client = _outlook_connector_from_config(config, "inbox")

    assert connector.connector_id.startswith("outlook_mail:personal:folder-inbox:")
    assert connector.permissions("message:one").owner == "lee@example.test"


def test_outlook_cursor_rejects_legacy_and_cross_account_scope() -> None:
    from lee_kb.connectors.outlook import OutlookDeltaPage, OutlookMessage

    outlook_message = OutlookMessage(
        message_id="immutable-1",
        folder_id="folder-inbox",
        conversation_id="conversation-1",
        subject="subject",
        sender="sender@example.test",
        to_recipients=("lee@example.test",),
        cc_recipients=(),
        body_text="body",
        sent_timestamp=NOW,
        received_timestamp=NOW,
        modified_timestamp=NOW,
    )

    class Transport:
        def delta_page(self, _folder_id, _request):
            return OutlookDeltaPage(messages=(outlook_message,), delta_link="delta-1")

        def fetch_message(self, _message_id):
            return outlook_message

        def health(self, _folder_id):
            return True, "ok"

    first = OutlookConnector(
        OutlookScope(
            "lee@example.test",
            "folder-inbox",
            account_id="personal",
            tenant="common",
            credential_binding="a" * 64,
        ),
        Transport(),
        connector_id="outlook:personal",
    )
    cursor = first.checkpoint(first.discover())
    legacy = json.loads(cursor)
    legacy["version"] = 1
    legacy.pop("account_id")
    legacy.pop("tenant")
    legacy.pop("credential_binding")
    with pytest.raises(ConnectorConfigError):
        first.list_changes(json.dumps(legacy))

    other = OutlookConnector(
        OutlookScope(
            "lee@example.test",
            "folder-inbox",
            account_id="other",
            tenant="common",
            credential_binding="b" * 64,
        ),
        Transport(),
        connector_id="outlook:other",
    )
    with pytest.raises(ConnectorConfigError):
        other.list_changes(cursor)

    other_project = OutlookConnector(
        OutlookScope(
            "lee@example.test",
            "folder-inbox",
            project="other",
            account_id="personal",
            tenant="common",
            credential_binding="a" * 64,
        ),
        Transport(),
        connector_id="outlook:personal",
    )
    with pytest.raises(ConnectorConfigError, match="project"):
        other_project.list_changes(cursor)


def test_expired_token_refresh_rotates_refresh_token_and_persists_it() -> None:
    store = InMemoryTokenStore()
    store.save("personal", token(expires=NOW - timedelta(minutes=1)))
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "access_token": "access-new",
                    "refresh_token": "refresh-new",
                    "expires_in": 3600,
                    "scope": "Mail.Read offline_access",
                    "token_type": "Bearer",
                },
            )
        ]
    )
    manager = OAuthTokenManager(
        credential(), token_store=store, transport=http, clock=lambda: NOW
    )

    assert manager.access_token() == "access-new"
    assert store.load("personal").refresh_token == "refresh-new"
    assert b"refresh-old" in http.calls[0][3]
    assert b"access-old" not in http.calls[0][3]


def test_refresh_retries_transient_identity_endpoint_failure() -> None:
    store = InMemoryTokenStore()
    store.save("personal", token(expires=NOW - timedelta(minutes=1)))
    http = ScriptedHttp(
        [
            response(429, {"error": {"code": "TooManyRequests"}}, {"Retry-After": "0"}),
            response(
                200,
                {
                    "access_token": "access-new",
                    "refresh_token": "refresh-new",
                    "expires_in": 3600,
                },
            ),
        ]
    )
    sleeps: list[float] = []
    manager = OAuthTokenManager(
        credential(),
        token_store=store,
        transport=http,
        clock=lambda: NOW,
        sleep=sleeps.append,
    )

    assert manager.access_token() == "access-new"
    assert sleeps == [0]


def test_refresh_does_not_retry_ambiguous_server_failure() -> None:
    store = InMemoryTokenStore()
    previous = token(expires=NOW - timedelta(minutes=1))
    store.save("personal", previous)
    http = ScriptedHttp([response(503, {"error": {"code": "temporarilyUnavailable"}})])
    manager = OAuthTokenManager(
        credential(), token_store=store, transport=http, clock=lambda: NOW
    )

    with pytest.raises(GraphError) as error:
        manager.access_token()

    assert error.value.code is GraphErrorCode.TRANSIENT
    assert len(http.calls) == 1
    assert store.load("personal") == previous


def test_invalid_refresh_revokes_local_token_state() -> None:
    store = InMemoryTokenStore()
    store.save("personal", token(expires=NOW - timedelta(minutes=1)))
    http = ScriptedHttp(
        [response(400, {"error": {"code": "invalid_grant", "message": "secret"}})]
    )
    manager = OAuthTokenManager(
        credential(), token_store=store, transport=http, clock=lambda: NOW
    )

    with pytest.raises(CredentialRevokedError):
        manager.access_token()
    assert store.load("personal") is None


def test_device_code_flow_polls_without_persisting_device_code() -> None:
    clock = [NOW]
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "device_code": "private-device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "message": "Sign in",
                    "expires_in": 600,
                    "interval": 1,
                },
            ),
            response(400, {"error": "authorization_pending"}),
            response(
                200,
                {
                    "access_token": "access-device",
                    "refresh_token": "refresh-device",
                    "expires_in": 3600,
                    "scope": "Mail.Read offline_access",
                },
            ),
        ]
    )

    def sleep(delay: float) -> None:
        clock[0] += timedelta(seconds=delay)

    shown = []
    manager = OAuthTokenManager(
        credential(),
        token_store=InMemoryTokenStore(),
        transport=http,
        clock=lambda: clock[0],
        sleep=sleep,
    )
    result = manager._login_for_graph_client(on_device_code=shown.append)

    assert result.access_token == "access-device"
    assert shown[0].user_code == "ABCD-EFGH"
    assert "private-device-code" not in repr(shown[0])
    assert b"private-device-code" in http.calls[1][3]


def test_oauth_login_does_not_persist_until_identity_is_bound() -> None:
    clock = [NOW]
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "device_code": "private-device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "message": "Sign in",
                    "expires_in": 600,
                    "interval": 1,
                },
            ),
            response(
                200,
                {
                    "access_token": "access-device",
                    "refresh_token": "refresh-device",
                    "expires_in": 3600,
                },
            ),
        ]
    )
    store = InMemoryTokenStore()
    manager = OAuthTokenManager(
        credential(),
        token_store=store,
        transport=http,
        clock=lambda: clock[0],
        sleep=lambda delay: clock.__setitem__(0, clock[0] + timedelta(seconds=delay)),
    )

    assert manager.login() is None

    assert store.load("personal") is None
    with pytest.raises(CredentialUnavailableError):
        manager.access_token()
    manager._bind_verified_identity("lee@example.test", "common")
    stored = store.load("personal")
    assert stored is not None
    assert stored.verified_subject == "lee@example.test"
    assert stored.verified_tenant == "common"


def test_graph_client_retries_throttling_and_normalizes_provider_body() -> None:
    http = ScriptedHttp(
        [
            response(
                429,
                {"error": {"code": "TooManyRequests", "message": "bearer-secret"}},
                {"Retry-After": "0"},
            ),
            response(503, {"error": {"code": "serviceUnavailable", "message": "raw"}}),
            response(200, {"id": "ok"}),
        ]
    )
    client = make_graph_client(http, max_attempts=3)

    assert client.get_json("/me") == {"id": "ok"}
    assert len(http.calls) == 3
    assert all("bearer-secret" not in str(call) for call in http.calls)

    failed_http = ScriptedHttp(
        [
            response(
                429,
                {"error": {"code": "TooManyRequests", "message": "bearer-secret"}},
            )
        ]
    )
    failed = make_graph_client(failed_http, max_attempts=1)
    with pytest.raises(GraphError) as error:
        failed.get_json("/me")
    assert error.value.code is GraphErrorCode.THROTTLED
    assert "bearer-secret" not in str(error.value)


def test_graph_client_clamps_retry_after_to_policy_bound() -> None:
    sleeps: list[float] = []
    http = ScriptedHttp(
        [
            response(
                429,
                {"error": {"code": "TooManyRequests"}},
                {"Retry-After": "999999"},
            ),
            response(200, {}),
        ]
    )
    client = GraphClient(
        credential(),
        token_manager=StaticTokenManager("access-token"),
        http=http,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=1, max_delay=2),
        sleep=sleeps.append,
    )

    assert client.get_json("/me") == {}
    assert sleeps == [2]


def test_graph_client_rejects_oversized_response() -> None:
    client = make_graph_client(
        ScriptedHttp([response(200, {"content": "too large"})]),
        max_response_bytes=10,
    )

    with pytest.raises(GraphError) as error:
        client.get_json("/me")
    assert error.value.code is GraphErrorCode.MALFORMED_RESPONSE


def test_graph_client_does_not_retry_non_idempotent_requests() -> None:
    http = ScriptedHttp([response(503, {"error": {"code": "busy"}}), response(200, {})])
    client = make_graph_client(http, max_attempts=3)

    with pytest.raises(GraphError) as error:
        client.request_json("POST", "/me", body=b"{}")
    assert error.value.code is GraphErrorCode.TRANSIENT
    assert len(http.calls) == 1


def test_graph_client_does_not_replay_non_idempotent_request_after_401() -> None:
    manager = StaticTokenManager("access-old", "access-new")
    http = ScriptedHttp([response(401, {"error": {"code": "expired"}})])
    client = make_graph_client(http, manager=manager, max_attempts=3)

    with pytest.raises(GraphError) as error:
        client.request_json("POST", "/me", body=b"{}")

    assert error.value.code is GraphErrorCode.AUTHENTICATION
    assert len(http.calls) == 1
    assert manager.forced == [False]


def test_graph_client_refreshes_once_after_401() -> None:
    manager = StaticTokenManager("access-old", "access-new")
    http = ScriptedHttp(
        [
            response(401, {"error": {"code": "InvalidAuthenticationToken"}}),
            response(200, {}),
        ]
    )
    client = make_graph_client(http, manager=manager)

    assert client.get_json("/me") == {}
    assert manager.forced == [False, True]
    assert http.calls[0][2]["Authorization"] == "Bearer access-old"
    assert http.calls[1][2]["Authorization"] == "Bearer access-new"


def test_graph_client_replays_one_401_even_with_one_retry_attempt() -> None:
    manager = StaticTokenManager("access-old", "access-new")
    http = ScriptedHttp(
        [
            response(401, {"error": {"code": "InvalidAuthenticationToken"}}),
            response(200, {}),
        ]
    )
    client = make_graph_client(http, manager=manager, max_attempts=1)

    assert client.get_json("/me") == {}
    assert len(http.calls) == 2


def test_graph_client_verifies_delegated_subject_before_resource_use() -> None:
    http = ScriptedHttp(
        [
            response(200, {"id": "lee@example.test", "mail": None}),
            response(200, {"value": []}),
        ]
    )
    client = GraphClient(
        credential(),
        token_manager=StaticTokenManager("access-token"),
        http=http,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    assert client.get_json("/me/mailFolders") == {"value": []}
    assert urlsplit(http.calls[0][1]).path.endswith("/me")

    wrong_http = ScriptedHttp([response(200, {"id": "mallory@example.test"})])
    wrong_client = GraphClient(
        credential(),
        token_manager=StaticTokenManager("access-token"),
        http=wrong_http,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    with pytest.raises(GraphError) as error:
        wrong_client.get_json("/me/mailFolders")
    assert error.value.code is GraphErrorCode.AUTHENTICATION


def test_graph_client_rechecks_subject_after_refresh() -> None:
    manager = StaticTokenManager("access-lee", "access-mallory")
    http = ScriptedHttp(
        [
            response(200, {"id": "lee@example.test"}),
            response(401, {"error": {"code": "InvalidAuthenticationToken"}}),
            response(200, {"id": "mallory@example.test"}),
        ]
    )
    client = GraphClient(
        credential(),
        token_manager=manager,
        http=http,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(GraphError) as error:
        client.get_json("/me/mailFolders")

    assert error.value.code is GraphErrorCode.AUTHENTICATION
    assert len(http.calls) == 3
    assert manager.forced.count(True) == 1


def test_graph_client_rechecks_tenant_claim_after_refresh() -> None:
    def jwt(tid: str) -> str:
        payload = (
            base64.urlsafe_b64encode(json.dumps({"tid": tid}).encode("utf-8"))
            .rstrip(b"=")
            .decode("ascii")
        )
        return f"header.{payload}.signature"

    account_credential = GraphCredential(
        MicrosoftAccount("personal", "lee@example.test", tenant="tenant-a"),
        client_id="client-id",
        scopes=("Mail.Read", "User.Read"),
    )
    manager = StaticTokenManager(jwt("tenant-a"), jwt("tenant-b"))
    http = ScriptedHttp(
        [
            response(200, {"id": "lee@example.test"}),
            response(401, {"error": {"code": "InvalidAuthenticationToken"}}),
            response(200, {"id": "lee@example.test"}),
        ]
    )
    client = GraphClient(
        account_credential,
        token_manager=manager,
        http=http,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(GraphError) as error:
        client.get_json("/me/mailFolders")

    assert error.value.code is GraphErrorCode.AUTHENTICATION
    assert len(http.calls) == 3


def test_graph_client_rejects_a_token_manager_for_another_credential() -> None:
    other = GraphCredential(
        MicrosoftAccount("other", "other@example.test"),
        client_id="client-id",
        scopes=("Mail.Read", "User.Read"),
    )
    manager = OAuthTokenManager(other, token_store=InMemoryTokenStore())

    with pytest.raises(ValueError, match="does not match"):
        GraphClient(
            credential(),
            token_manager=manager,
            http=ScriptedHttp([]),
        )


def test_urllib_transport_does_not_follow_redirects() -> None:
    handler = _NoRedirectHandler()

    assert (
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.test")
        is None
    )


def test_graph_client_rejects_credential_bearing_graph_url_fragment() -> None:
    client = make_graph_client(ScriptedHttp([response(200, {})]))

    with pytest.raises(ValueError, match="Graph URLs"):
        client.get_json("https://graph.microsoft.com/v1.0/me#access_token=secret")


def test_graph_client_rejects_nonstandard_graph_port() -> None:
    client = make_graph_client(ScriptedHttp([response(200, {})]))

    with pytest.raises(ValueError, match="Graph HTTPS host"):
        client.get_json("https://graph.microsoft.com:8443/v1.0/me")


def test_graph_retry_jitter_remains_within_max_delay() -> None:
    client = GraphClient(
        credential(),
        token_manager=StaticTokenManager("access-token"),
        http=ScriptedHttp([]),
        retry_policy=RetryPolicy(max_attempts=2, base_delay=1, max_delay=2, jitter=10),
        random_source=lambda: 1,
    )

    assert client._delay(1) == 2


def test_graph_outlook_transport_rejects_broad_scopes() -> None:
    broad = GraphCredential(
        MicrosoftAccount("personal", "lee@example.test"),
        client_id="client-id",
        scopes=("Mail.Read", "User.Read", "Mail.Send"),
    )
    client = GraphClient(
        broad,
        token_manager=StaticTokenManager("access-token"),
        http=ScriptedHttp([]),
    )

    with pytest.raises(ValueError, match="exactly Mail.Read and User.Read"):
        GraphOutlookTransport(client)


def test_graph_outlook_connector_requires_bound_scope() -> None:
    transport = GraphOutlookTransport(make_graph_client(ScriptedHttp([])))

    with pytest.raises(ConnectorConfigError, match="bound"):
        OutlookConnector(OutlookScope("lee@example.test", "folder-inbox"), transport)


def test_graph_outlook_cursor_binds_verified_provider_tenant() -> None:
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "value": [],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-bound",
                },
            )
        ]
    )
    client = make_graph_client(http)
    connector = OutlookConnector(
        OutlookScope(
            "lee@example.test",
            "folder-inbox",
            account_id="personal",
            tenant="common",
            credential_binding=credential().binding,
        ),
        GraphOutlookTransport(client),
    )
    cursor = connector.checkpoint(connector.discover())
    client._verified_tenant = "different-tenant"

    with pytest.raises(ConnectorConfigError, match="provider tenant"):
        connector.list_changes(cursor)


def test_graph_client_rejects_caller_authorization_header() -> None:
    client = make_graph_client(ScriptedHttp([response(200, {})]))

    with pytest.raises(ValueError, match="security headers"):
        client.get_json("/me", headers={"authorization": "Bearer caller-token"})


def test_delta_round_owns_pagination_and_recovers_expired_cursor() -> None:
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "value": [{"id": "one"}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/next",
                },
            ),
            response(
                200,
                {
                    "value": [{"id": "two"}],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-new",
                },
            ),
        ]
    )
    client = make_graph_client(http)
    result = client.delta_round("/me/messages/delta")
    assert result == GraphDeltaResult(
        ({"id": "one"}, {"id": "two"}),
        "https://graph.microsoft.com/v1.0/delta-new",
    )
    assert [urlsplit(call[1]).path for call in http.calls] == [
        "/v1.0/me/messages/delta",
        "/v1.0/next",
    ]

    reset_http = ScriptedHttp(
        [
            response(410, {"error": {"code": "syncStateNotFound"}}),
            response(
                200,
                {
                    "value": [{"id": "fresh"}],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-fresh",
                },
            ),
        ]
    )
    reset_client = make_graph_client(reset_http)
    reset = reset_client.delta_round(
        "/me/messages/delta", "https://graph.microsoft.com/v1.0/expired"
    )
    assert reset.reset is True
    assert reset.values == ({"id": "fresh"},)
    assert urlsplit(reset_http.calls[1][1]).path == "/v1.0/me/messages/delta"


def test_delta_round_restarts_when_a_continuation_expires() -> None:
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "value": [{"id": "stale-page"}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/next",
                },
            ),
            response(410, {"error": {"code": "syncStateNotFound"}}),
            response(
                200,
                {
                    "value": [{"id": "rebuilt-page"}],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/rebuilt",
                },
            ),
        ]
    )

    result = make_graph_client(http).delta_round(
        "/me/messages/delta", "https://graph.microsoft.com/v1.0/cursor"
    )

    assert result.reset is True
    assert result.values == ({"id": "rebuilt-page"},)
    assert urlsplit(http.calls[2][1]).path == "/v1.0/me/messages/delta"


def test_rate_limiter_paces_requests() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay

    limiter = SpacingRateLimiter(2.0, clock=clock, sleep=sleep)
    limiter.wait()
    limiter.wait()
    assert sleeps == [2.0]


def test_graph_outlook_transport_maps_html_and_immutable_headers() -> None:
    item = graph_message(body="<p>Current&nbsp;plan</p><blockquote>old</blockquote>")
    item["body"]["contentType"] = "html"
    item["attachments"] = [
        {
            "id": "attachment-1",
            "name": "plan.txt",
            "contentType": "text/plain",
            "size": 12,
            "isInline": False,
        }
    ]
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "value": [item],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-1",
                },
            ),
            response(200, item),
        ]
    )
    client = make_graph_client(http)
    transport = GraphOutlookTransport(client)

    page = transport.delta_page("folder-inbox", None)
    message = page.messages[0]
    fetched = transport.fetch_message("immutable-1")

    assert page.delta_link.endswith("delta-1")
    assert message.body_text == "Current plan\nold"
    assert message.attachments[0].name == "plan.txt"
    assert fetched.source_object_id == "message:immutable-1"
    assert all('IdType="ImmutableId"' in call[2]["Prefer"] for call in http.calls)
    assert parse_qs(urlsplit(http.calls[0][1]).query)["$select"]


def test_graph_outlook_transport_expired_delta_is_marked_full_sync() -> None:
    http = ScriptedHttp(
        [
            response(410, {"error": {"code": "syncStateNotFound"}}),
            response(
                200,
                {
                    "value": [graph_message()],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-rebuilt",
                },
            ),
        ]
    )
    transport = GraphOutlookTransport(make_graph_client(http))

    page = transport.delta_page(
        "folder-inbox", "https://graph.microsoft.com/v1.0/expired"
    )

    assert page.full_sync is True
    assert page.messages[0].message_id == "immutable-1"


def test_graph_delta_keeps_final_event_when_one_id_is_updated_then_removed() -> None:
    item = graph_message()
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "value": [
                        item,
                        {"id": "immutable-1", "@removed": {"reason": "deleted"}},
                    ],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-removed",
                },
            )
        ]
    )
    page = GraphOutlookTransport(make_graph_client(http)).delta_page(
        "folder-inbox", None
    )

    assert page.messages == ()
    assert page.removed_message_ids == ("immutable-1",)
    assert page.event_order == (("immutable-1", "removed"),)


def test_expired_delta_reconciliation_tombstones_missing_messages(tmp_path) -> None:
    first = graph_message("immutable-1")
    second = graph_message("immutable-2", body="Second")
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "value": [first, second],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-1",
                },
            ),
            response(200, first),
            response(200, second),
            response(410, {"error": {"code": "syncStateNotFound"}}),
            response(
                200,
                {
                    "value": [first],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-rebuilt",
                },
            ),
        ]
    )
    connector = OutlookConnector(
        OutlookScope(
            "lee@example.test",
            "folder-inbox",
            account_id="personal",
            tenant="common",
            credential_binding=credential().binding,
        ),
        GraphOutlookTransport(make_graph_client(http)),
    )

    with SQLiteRepository(tmp_path / "knowledge.sqlite") as repository:
        _sync_external_connector(connector, repository, sync_timestamp=NOW)
        recovered = _sync_external_connector(
            connector, repository, sync_timestamp=NOW + timedelta(minutes=1)
        )
        deleted = repository.get_item(
            KnowledgeItemId(connector.connector_id, "message:immutable-2")
        )

    assert recovered.deleted == 1
    assert deleted is not None and deleted.tombstone


def test_live_outlook_path_persists_projection_and_empty_cursor_round(tmp_path) -> None:
    item = graph_message()
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "value": [item],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-1",
                },
            ),
            response(200, item),
            response(
                200,
                {
                    "value": [],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-2",
                },
            ),
        ]
    )
    transport = GraphOutlookTransport(make_graph_client(http))
    connector = OutlookConnector(
        OutlookScope(
            "lee@example.test",
            "folder-inbox",
            project="default",
            account_id="personal",
            tenant="common",
            credential_binding=credential().binding,
        ),
        transport,
    )

    with SQLiteRepository(tmp_path / "knowledge.sqlite") as repository:
        first = _sync_external_connector(connector, repository, sync_timestamp=NOW)
        cursor_after_first = repository.get_connector_cursor(connector.connector_id)
        second = _sync_external_connector(
            connector, repository, sync_timestamp=NOW + timedelta(minutes=1)
        )
        cursor_after_second = repository.get_connector_cursor(connector.connector_id)
        stored = repository.get_item(
            KnowledgeItemId(connector.connector_id, "message:immutable-1")
        )

    assert first.created == 1
    assert second.unchanged == 1
    assert cursor_after_first != cursor_after_second
    assert stored is not None
    assert stored.document_type.value == "email"


def test_empty_initial_outlook_sync_marks_project_as_synchronized(tmp_path) -> None:
    http = ScriptedHttp(
        [
            response(
                200,
                {
                    "value": [],
                    "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-empty",
                },
            )
        ]
    )
    transport = GraphOutlookTransport(make_graph_client(http))
    connector = OutlookConnector(
        OutlookScope(
            "lee@example.test",
            "folder-inbox",
            account_id="personal",
            tenant="common",
            credential_binding=credential().binding,
        ),
        transport,
    )

    with SQLiteRepository(tmp_path / "knowledge.sqlite") as repository:
        summary = _sync_external_connector(
            connector,
            repository,
            sync_timestamp=NOW,
        )
        assert summary.created == 0
        assert repository.has_synchronized_project("default")
        assert repository.get_connector_cursor(connector.connector_id) is not None
