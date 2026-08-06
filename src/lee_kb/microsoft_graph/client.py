"""Authenticated Microsoft Graph request execution and change-feed mechanics."""

from __future__ import annotations

import base64
import binascii
import json
import math
import random
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import parse_qsl, urljoin, urlsplit

from .auth import OAuthTokenManager
from .errors import (
    CredentialError,
    CredentialRevokedError,
    GraphError,
    GraphErrorCode,
)
from .http import (
    HttpResponse,
    HttpResponseTooLarge,
    HttpTransport,
    UrllibHttpTransport,
)
from .models import GraphCredential

__all__ = [
    "GraphClient",
    "GraphDeltaResult",
    "GraphPage",
    "RateLimiter",
    "RetryPolicy",
    "SpacingRateLimiter",
]

_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0/"
_GRAPH_HOST = "graph.microsoft.com"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry policy for safe Graph GET requests."""

    max_attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("retry delays must not be negative")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must not be below base_delay")
        if self.jitter < 0:
            raise ValueError("jitter must not be negative")


class RateLimiter(Protocol):
    """Pacing boundary shared by all Graph resources."""

    def wait(self) -> None:
        """Block until the next request may start."""


class SpacingRateLimiter:
    """A small process-local limiter suitable for a personal sync command."""

    def __init__(
        self,
        minimum_interval: float = 0.0,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if minimum_interval < 0:
            raise ValueError("minimum_interval must not be negative")
        self._minimum_interval = minimum_interval
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._last_request: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            remaining = self._minimum_interval - (now - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last_request = now


@dataclass(frozen=True, slots=True)
class GraphPage:
    """One generic OData collection page."""

    values: tuple[Mapping[str, object], ...]
    next_link: str | None = None
    delta_link: str | None = None
    reset: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple):
            raise TypeError("values must be a tuple")
        if not all(isinstance(value, Mapping) for value in self.values):
            raise TypeError("values must contain mappings")
        for link, name in (
            (self.next_link, "next_link"),
            (self.delta_link, "delta_link"),
        ):
            if link is not None and (not isinstance(link, str) or not link.strip()):
                raise ValueError(f"{name} must be a non-empty string when present")
        if self.next_link is not None and self.delta_link is not None:
            raise ValueError("a page cannot contain both next_link and delta_link")
        if not isinstance(self.reset, bool):
            raise TypeError("reset must be a bool")


@dataclass(frozen=True, slots=True)
class GraphDeltaResult:
    """A complete delta round, including whether expired state was rebuilt."""

    values: tuple[Mapping[str, object], ...]
    delta_link: str
    reset: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple):
            raise TypeError("values must be a tuple")
        if not all(isinstance(value, Mapping) for value in self.values):
            raise TypeError("values must contain mappings")
        if not isinstance(self.delta_link, str) or not self.delta_link.strip():
            raise ValueError("delta_link must be a non-empty string")


class GraphClient:
    """The shared authenticated Graph boundary for all Microsoft connectors."""

    def __init__(
        self,
        credential: GraphCredential,
        *,
        token_manager: OAuthTokenManager | None = None,
        http: HttpTransport | None = None,
        retry_policy: RetryPolicy | None = None,
        rate_limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] | None = None,
        random_source: Callable[[], float] | None = None,
        timeout: float = 30.0,
        max_pages: int = 10_000,
        max_response_bytes: int = 8 * 1024 * 1024,
        max_delta_items: int = 100_000,
        max_delta_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if not isinstance(credential, GraphCredential):
            raise TypeError("credential must be a GraphCredential")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError("max_pages must be positive")
        if not isinstance(max_response_bytes, int) or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        if not isinstance(max_delta_items, int) or max_delta_items < 1:
            raise ValueError("max_delta_items must be positive")
        if not isinstance(max_delta_bytes, int) or max_delta_bytes < 1:
            raise ValueError("max_delta_bytes must be positive")
        self._limiter = rate_limiter or SpacingRateLimiter()
        self.credential = credential
        if token_manager is not None:
            manager_credential = getattr(token_manager, "credential", None)
            if manager_credential is not None and (
                not isinstance(manager_credential, GraphCredential)
                or manager_credential.binding != credential.binding
            ):
                raise ValueError(
                    "token manager credential does not match Graph credential"
                )
        self._tokens = token_manager or OAuthTokenManager(
            credential,
            request_waiter=self._limiter.wait,
        )
        if isinstance(self._tokens, OAuthTokenManager):
            self._tokens.set_request_waiter(self._limiter.wait)
        self._http = http or UrllibHttpTransport(max_response_bytes)
        self._retry = retry_policy or RetryPolicy()
        self._sleep = sleep or time.sleep
        self._random = random_source or random.random
        self._timeout = timeout
        self._max_pages = max_pages
        self._max_response_bytes = max_response_bytes
        self._max_delta_items = max_delta_items
        self._max_delta_bytes = max_delta_bytes
        self._account_verified = False
        self._verified_token: str | None = None
        self._verified_subject: str | None = None
        self._verified_tenant: str | None = None
        self._identity_invalidated = False

    @property
    def token_manager(self) -> OAuthTokenManager:
        """Return the credential lifecycle provider used by this client."""
        return self._tokens

    def verified_identity(self) -> tuple[str | None, str | None]:
        """Return the provider subject and tenant bound to the current grant."""
        if self._identity_invalidated:
            return None, None
        if self._verified_subject is not None or self._verified_tenant is not None:
            return self._verified_subject, self._verified_tenant
        identity = getattr(self._tokens, "verified_identity", None)
        if callable(identity):
            try:
                stored = identity()
            except CredentialError:
                return None, None
            if (
                isinstance(stored, tuple)
                and len(stored) == 2
                and all(value is None or isinstance(value, str) for value in stored)
            ):
                return stored
        return None, None

    def login(self, *, on_device_code=None):
        """Acquire and verify a delegated grant before exposing it."""
        try:
            self._clear_verified_identity()
            self._identity_invalidated = False
            if isinstance(self._tokens, OAuthTokenManager):
                token_set = self._tokens._login_for_graph_client(
                    on_device_code=on_device_code,
                )
            else:
                token_set = self._tokens.login(on_device_code=on_device_code)
            self._account_verified = False
            self.verify_account()
            loaded = getattr(self._tokens, "_load", lambda: None)()
            return loaded if loaded is not None else token_set
        except GraphError as error:
            self._clear_verified_identity()
            discard = getattr(self._tokens, "discard_session", None)
            if callable(discard):
                discard()
            if error.code is GraphErrorCode.AUTHENTICATION:
                self._revoke_local_grant()
            raise

    def get_json(
        self,
        path_or_url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        """Execute an authenticated GET and parse its JSON response."""
        return self.request_json("GET", path_or_url, headers=headers)

    def request_json(
        self,
        method: str,
        path_or_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> object:
        """Execute one authenticated request and parse its JSON response."""
        if not isinstance(method, str) or not method.strip():
            raise ValueError("HTTP method must be a non-empty string")
        return self._request_json(
            method.upper(),
            path_or_url,
            headers=headers,
            body=body,
        )

    def verify_account(self) -> None:
        """Ensure the delegated token belongs to the configured account."""
        token = self._access_token()
        payload = self._request_json(
            "GET",
            "/me?$select=id,mail,userPrincipalName",
            headers=None,
            check_account=False,
        )
        if not isinstance(payload, Mapping):
            raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
        expected = self.credential.account.user_id.casefold()
        identities = {
            value.casefold()
            for key in ("id", "mail", "userPrincipalName")
            if isinstance(value := payload.get(key), str) and value.strip()
        }
        if expected not in identities:
            self._reject_account()
        subject = _provider_subject(payload)
        if subject is None:
            raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
        stored_subject, stored_tenant = self._stored_verified_identity()
        if stored_subject is not None and subject != stored_subject:
            self._reject_account()
        tenant = _token_tenant(token) or _payload_tenant(payload)
        if tenant is None:
            tenant = self.credential.account.tenant
        if stored_tenant is not None and tenant.casefold() != stored_tenant.casefold():
            self._reject_account()
        configured_tenant = self.credential.account.tenant.casefold()
        if configured_tenant not in {"common", "organizations", "consumers"} and (
            tenant.casefold() != configured_tenant
        ):
            self._reject_account()
        tenant = tenant.casefold()
        bind = getattr(self._tokens, "_bind_verified_identity", None)
        if callable(bind):
            try:
                bind(subject, tenant)
            except CredentialError as error:
                self._clear_verified_identity()
                self._revoke_local_grant()
                raise GraphError(GraphErrorCode.AUTHENTICATION) from error
        self._verified_subject = subject
        self._verified_tenant = tenant
        self._verified_token = token
        self._account_verified = True
        self._identity_invalidated = False

    def collection_page(
        self,
        path_or_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        reset_url: str | None = None,
        delta: bool = False,
    ) -> GraphPage:
        """Read one page, optionally rebuilding an expired delta token."""
        reset = False
        try:
            payload = self._request_json(
                "GET",
                path_or_url,
                headers=headers,
                delta=delta,
            )
        except GraphError as error:
            if error.code is not GraphErrorCode.DELTA_EXPIRED or reset_url is None:
                raise
            payload = self._request_json(
                "GET",
                reset_url,
                headers=headers,
                delta=delta,
            )
            reset = True
        return _page_from_payload(payload, reset=reset)

    def delta_round(
        self,
        initial_url: str,
        cursor: str | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> GraphDeltaResult:
        """Read every page of one delta round and return only final state.

        ``cursor`` is an opaque provider URL.  If Graph says it expired, the
        client starts a fresh initial enumeration and marks the result as a
        reset.  The connector can then reconcile missing IDs against its
        metadata snapshot without treating a partial rebuild as complete.
        """
        request = cursor or initial_url
        reset_url = initial_url if cursor is not None else None
        reset_attempted = False
        seen: set[str] = set()
        values: list[Mapping[str, object]] = []
        aggregate_bytes = 0
        did_reset = False
        for _page_number in range(self._max_pages):
            if request in seen:
                raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
            seen.add(request)
            page = self.collection_page(
                request,
                headers=headers,
                reset_url=reset_url if not reset_attempted else None,
                delta=True,
            )
            if page.reset:
                reset_attempted = True
                values.clear()
                aggregate_bytes = 0
                seen.clear()
            did_reset = did_reset or page.reset
            page_bytes = sum(
                len(json.dumps(value, separators=(",", ":"))) for value in page.values
            )
            aggregate_bytes += page_bytes
            if (
                len(values) + len(page.values) > self._max_delta_items
                or aggregate_bytes > self._max_delta_bytes
            ):
                raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
            values.extend(page.values)
            if page.next_link is not None:
                request = page.next_link
                continue
            if page.delta_link is None:
                raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
            return GraphDeltaResult(tuple(values), page.delta_link, did_reset)
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)

    def iter_collection(
        self,
        path_or_url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[GraphPage]:
        """Yield a bounded collection page sequence for future connectors."""
        request = path_or_url
        seen: set[str] = set()
        for _page_number in range(self._max_pages):
            if request in seen:
                raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
            seen.add(request)
            page = self.collection_page(request, headers=headers)
            yield page
            if page.next_link is None:
                return
            request = page.next_link
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)

    def _request_json(
        self,
        method: str,
        path_or_url: str,
        *,
        headers: Mapping[str, str] | None,
        body: bytes | None = None,
        check_account: bool = True,
        delta: bool = False,
    ) -> object:
        url = _safe_graph_url(path_or_url)
        request_headers = {"Accept": "application/json"}
        if headers:
            reserved = {
                "authorization",
                "cookie",
                "host",
                "proxy-authorization",
                "user-agent",
                "content-length",
            }
            if any(name.casefold() in reserved for name in headers):
                raise ValueError("caller cannot override Graph security headers")
            request_headers.update(headers)
        request_token = self._access_token()
        if check_account and not _is_me_url(url):
            if not self._account_verified or (
                self._verified_token is not None
                and self._verified_token != request_token
            ):
                self.verify_account()
                request_token = self._access_token()
        request_headers["Authorization"] = "Bearer " + request_token
        request_headers["User-Agent"] = "lee-kb/graph-client"
        refreshed_after_401 = False
        for attempt in range(1, self._retry.max_attempts + 2):
            # The limiter also applies to retries, not only successful
            # request starts, so a throttled client does not burst again.
            self._limiter.wait()
            auth_only_attempt = attempt > self._retry.max_attempts
            try:
                response = self._http.request(
                    method,
                    url,
                    headers=request_headers,
                    body=body,
                    timeout=self._timeout,
                )
            except HttpResponseTooLarge:
                raise GraphError(GraphErrorCode.MALFORMED_RESPONSE) from None
            except (ConnectionError, TimeoutError, OSError):
                if (
                    method not in {"GET", "HEAD", "OPTIONS"}
                    or auth_only_attempt
                    or attempt == self._retry.max_attempts
                ):
                    raise GraphError(GraphErrorCode.NETWORK, attempts=attempt) from None
                self._sleep(self._delay(attempt))
                continue

            if 200 <= response.status_code < 300:
                return _decode_json_response(response, self._max_response_bytes)

            error = _normalize_http_error(
                response,
                attempts=attempt,
                is_delta=delta,
                max_response_bytes=self._max_response_bytes,
            )
            if (
                error.code is GraphErrorCode.AUTHENTICATION
                and not refreshed_after_401
                and method in {"GET", "HEAD", "OPTIONS"}
            ):
                try:
                    refreshed_token = self._access_token(force_refresh=True)
                    if check_account and not _is_me_url(url):
                        self._account_verified = False
                        self.verify_account()
                        refreshed_token = self._access_token()
                except CredentialError as auth_error:
                    raise GraphError(GraphErrorCode.AUTHENTICATION, 401) from auth_error
                request_headers["Authorization"] = "Bearer " + refreshed_token
                refreshed_after_401 = True
                continue
            if (
                not error.retryable
                or method not in {"GET", "HEAD", "OPTIONS"}
                or auth_only_attempt
                or attempt == self._retry.max_attempts
            ):
                raise error
            delay = error.retry_after
            if delay is None:
                delay = self._delay(attempt)
            self._sleep(min(delay, self._retry.max_delay))
        raise GraphError(GraphErrorCode.UNKNOWN)

    def _access_token(self, *, force_refresh: bool = False) -> str:
        if self._identity_invalidated:
            raise GraphError(GraphErrorCode.AUTHENTICATION)
        try:
            if isinstance(self._tokens, OAuthTokenManager):
                token = self._tokens._access_token_for_graph_client(
                    force_refresh=force_refresh
                )
            else:
                token = self._tokens.access_token(force_refresh=force_refresh)
        except CredentialRevokedError as error:
            self._clear_verified_identity()
            raise GraphError(GraphErrorCode.AUTHENTICATION) from error
        except CredentialError as error:
            raise GraphError(GraphErrorCode.AUTHENTICATION) from error
        if not isinstance(token, str) or not token:
            raise GraphError(GraphErrorCode.AUTHENTICATION)
        if self._verified_token is not None and token != self._verified_token:
            self._account_verified = False
        return token

    def _stored_verified_identity(self) -> tuple[str | None, str | None]:
        identity = getattr(self._tokens, "verified_identity", None)
        if callable(identity):
            try:
                stored = identity()
            except CredentialError as error:
                raise GraphError(GraphErrorCode.AUTHENTICATION) from error
            if (
                isinstance(stored, tuple)
                and len(stored) == 2
                and all(value is None or isinstance(value, str) for value in stored)
            ):
                return stored
        return self._verified_subject, self._verified_tenant

    def _clear_verified_identity(self) -> None:
        self._account_verified = False
        self._verified_token = None
        self._verified_subject = None
        self._verified_tenant = None
        self._identity_invalidated = True

    def _revoke_local_grant(self) -> None:
        revoke = getattr(self._tokens, "revoke", None)
        if callable(revoke):
            try:
                revoke()
            except Exception as error:
                raise GraphError(GraphErrorCode.AUTHENTICATION) from error

    def _reject_account(self) -> None:
        self._clear_verified_identity()
        self._revoke_local_grant()
        raise GraphError(GraphErrorCode.AUTHENTICATION)

    def _delay(self, attempt: int) -> float:
        delay = min(
            self._retry.max_delay,
            self._retry.base_delay * (2 ** max(attempt - 1, 0)),
        )
        if self._retry.jitter:
            delay = min(
                self._retry.max_delay,
                delay + self._random() * self._retry.jitter,
            )
        return delay


def _safe_graph_url(path_or_url: str) -> str:
    if not isinstance(path_or_url, str) or not path_or_url.strip():
        raise ValueError("Graph URL must be a non-empty string")
    if path_or_url.startswith("/"):
        path_or_url = urljoin(_GRAPH_BASE_URL, path_or_url.lstrip("/"))
    parts = urlsplit(path_or_url)
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError("Graph URLs must use a valid HTTPS port") from error
    if (
        parts.scheme != "https"
        or parts.hostname != _GRAPH_HOST
        or port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
        or "#" in path_or_url
    ):
        raise ValueError("Graph URLs must use the Microsoft Graph HTTPS host")
    forbidden_query_keys = {
        "access_token",
        "authorization",
        "client_secret",
        "id_token",
        "password",
        "refresh_token",
        "secret",
    }
    if any(
        key.casefold() in forbidden_query_keys for key, _value in parse_qsl(parts.query)
    ):
        raise ValueError("Graph URL contains a credential-bearing query parameter")
    return path_or_url


def _is_me_url(url: str) -> bool:
    return urlsplit(url).path.rstrip("/") == "/v1.0/me"


def _provider_subject(payload: Mapping[str, object]) -> str | None:
    for key in ("id", "userPrincipalName", "mail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.casefold()
    return None


def _payload_tenant(payload: Mapping[str, object]) -> str | None:
    value = payload.get("tenantId")
    return (
        value.strip().casefold() if isinstance(value, str) and value.strip() else None
    )


def _token_tenant(token: str) -> str | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((parts[1] + padding).encode("ascii"))
        )
    except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    for key in ("tid", "tenantId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    return None


def _decode_json_response(response: HttpResponse, max_response_bytes: int) -> object:
    if not response.body:
        return {}
    if len(response.body) > max_response_bytes:
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE, response.status_code)
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GraphError(
            GraphErrorCode.MALFORMED_RESPONSE,
            status_code=response.status_code,
        ) from error


def _page_from_payload(payload: object, *, reset: bool = False) -> GraphPage:
    if not isinstance(payload, dict):
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
    values = payload.get("value")
    if not isinstance(values, list) or not all(
        isinstance(item, Mapping) for item in values
    ):
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
    next_link = payload.get("@odata.nextLink")
    delta_link = payload.get("@odata.deltaLink")
    if next_link is not None and not isinstance(next_link, str):
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
    if delta_link is not None and not isinstance(delta_link, str):
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE)
    try:
        if next_link is not None:
            _safe_graph_url(next_link)
        if delta_link is not None:
            _safe_graph_url(delta_link)
        return GraphPage(tuple(values), next_link, delta_link, reset)
    except (TypeError, ValueError) as error:
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE) from error


def _normalize_http_error(
    response: HttpResponse,
    *,
    attempts: int,
    is_delta: bool,
    max_response_bytes: int,
) -> GraphError:
    payload: object = None
    if response.body and len(response.body) <= max_response_bytes:
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
    provider_code = _provider_error_code(payload)
    status = response.status_code
    if status == 401:
        code = GraphErrorCode.AUTHENTICATION
    elif status == 403:
        code = GraphErrorCode.AUTHORIZATION
    elif status == 404:
        code = GraphErrorCode.NOT_FOUND
    elif is_delta and (
        status == 410
        or provider_code
        in {
            "syncstatenotfound",
            "resyncrequired",
            "deltatokenexpired",
        }
    ):
        code = GraphErrorCode.DELTA_EXPIRED
    elif status in {429, 509}:
        code = GraphErrorCode.THROTTLED
    elif status in {408, 409, 500, 502, 503, 504}:
        code = GraphErrorCode.TRANSIENT
    elif 400 <= status < 500:
        code = GraphErrorCode.INVALID_REQUEST
    else:
        code = GraphErrorCode.UNKNOWN
    return GraphError(
        code,
        status_code=status,
        provider_code=provider_code,
        request_id=_header(response.headers, "request-id")
        or _header(response.headers, "client-request-id"),
        retry_after=_retry_after(response.headers),
        attempts=attempts,
    )


def _provider_error_code(payload: object) -> str | None:
    current = payload.get("error") if isinstance(payload, dict) else None
    deepest: str | None = None
    while isinstance(current, dict):
        value = current.get("code")
        if isinstance(value, str) and value:
            deepest = value.lower()
        current = current.get("innerError", current.get("innererror"))
    if (
        deepest is None
        or len(deepest) > 80
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in deepest
        )
    ):
        return None
    return deepest


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _retry_after(headers: Mapping[str, str]) -> float | None:
    value = _header(headers, "retry-after")
    if value is None:
        return None
    try:
        parsed = float(value)
        return max(parsed, 0.0) if math.isfinite(parsed) else None
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max((date - datetime.now(timezone.utc)).total_seconds(), 0.0)
        except (TypeError, ValueError, OverflowError):
            return None
