"""Delegated Microsoft identity authentication and token lifecycle."""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

from .errors import (
    CredentialError,
    CredentialRevokedError,
    CredentialUnavailableError,
    GraphError,
    GraphErrorCode,
    SecureStorageError,
)
from .http import HttpResponse, HttpTransport, UrllibHttpTransport
from .models import GraphCredential, TokenSet, _DeviceCode
from .token_store import TokenStore, default_token_store

__all__ = [
    "OAuthTokenManager",
    "TokenStore",
]

_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _safe_provider_code(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("error")
    if isinstance(value, dict):
        value = value.get("code")
    if not isinstance(value, str) or not value:
        return None
    if len(value) > 80 or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in value
    ):
        return None
    return value


def _json_body(response: HttpResponse) -> object:
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GraphError(
            GraphErrorCode.MALFORMED_RESPONSE,
            status_code=response.status_code,
        ) from error


def _auth_response_error(response: HttpResponse, payload: object) -> GraphError:
    provider_code = _safe_provider_code(payload)
    if response.status_code == 429:
        code = GraphErrorCode.THROTTLED
    elif response.status_code in {408, 500, 502, 503, 504}:
        code = GraphErrorCode.TRANSIENT
    else:
        code = GraphErrorCode.AUTHENTICATION
    return GraphError(
        code,
        status_code=response.status_code,
        provider_code=provider_code,
        request_id=_header(response.headers, "request-id"),
        retry_after=_response_retry_after(response),
    )


class _DeviceCodeAuthenticator:
    """Raw device-code protocol for a native/public client.

    The caller owns presentation of ``DeviceCode``.  This class never prints
    or logs the device code and never stores it in the token store.
    """

    def __init__(
        self,
        credential: GraphCredential,
        *,
        transport: HttpTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        request_waiter: Callable[[], None] | None = None,
    ) -> None:
        if not isinstance(credential, GraphCredential):
            raise TypeError("credential must be a GraphCredential")
        self._credential = credential
        self._transport = transport or UrllibHttpTransport()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or time.sleep
        self._request_waiter = request_waiter or (lambda: None)

    @property
    def _device_code_url(self) -> str:
        return f"{self._credential.authority_url}/oauth2/v2.0/devicecode"

    @property
    def _token_url(self) -> str:
        return f"{self._credential.authority_url}/oauth2/v2.0/token"

    def begin(self) -> _DeviceCode:
        response = self._post_form(
            self._device_code_url,
            {
                "client_id": self._credential.client_id,
                "scope": " ".join(self._credential.requested_scopes),
            },
        )
        payload = self._successful_payload(response)
        if not isinstance(payload, dict):
            raise GraphError(GraphErrorCode.MALFORMED_RESPONSE, response.status_code)
        try:
            expires_in = int(payload["expires_in"])
            interval = max(float(payload.get("interval", 5)), 1.0)
            return _DeviceCode(
                user_code=payload["user_code"],
                verification_uri=payload.get(
                    "verification_uri", payload.get("verification_url")
                ),
                message=payload.get("message", "Complete sign-in in your browser."),
                expires_at=self._now() + timedelta(seconds=expires_in),
                interval=interval,
                device_code=payload["device_code"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise GraphError(
                GraphErrorCode.MALFORMED_RESPONSE, response.status_code
            ) from error

    def login(
        self,
        *,
        on_device_code: Callable[[_DeviceCode], None] | None = None,
        expose_token: bool = False,
    ) -> TokenSet | None:
        device = self.begin()
        if on_device_code is not None:
            on_device_code(device)
        interval = device.interval
        while self._now() < device.expires_at:
            self._sleep(interval)
            try:
                response = self._post_form(
                    self._token_url,
                    {
                        "grant_type": _DEVICE_GRANT,
                        "client_id": self._credential.client_id,
                        "device_code": device.device_code,
                    },
                )
            except GraphError as error:
                if not error.retryable:
                    raise
                continue
            payload = self._payload_or_none(response)
            if response.status_code == 200:
                return _token_from_response(payload, self._now())
            provider_code = _safe_provider_code(payload)
            if provider_code == "authorization_pending":
                continue
            if provider_code == "slow_down":
                interval += 5
                continue
            if provider_code in {
                "authorization_declined",
                "access_denied",
                "expired_token",
                "bad_verification_code",
            }:
                raise CredentialError(
                    "Microsoft device authorization was not completed"
                )
            raise _auth_response_error(response, payload)
        raise CredentialError("Microsoft device authorization expired")

    def _post_form(self, url: str, values: Mapping[str, str]) -> HttpResponse:
        self._request_waiter()
        try:
            return self._transport.request(
                "POST",
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body=urlencode(values).encode("utf-8"),
            )
        except (ConnectionError, TimeoutError, OSError):
            raise GraphError(GraphErrorCode.NETWORK) from None

    def _successful_payload(self, response: HttpResponse) -> object:
        payload = self._payload_or_none(response)
        if response.status_code < 200 or response.status_code >= 300:
            raise _auth_response_error(response, payload)
        if payload is None:
            raise GraphError(GraphErrorCode.MALFORMED_RESPONSE, response.status_code)
        return payload

    @staticmethod
    def _payload_or_none(response: HttpResponse) -> object | None:
        if not response.body:
            return None
        return _json_body(response)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now


class OAuthTokenManager:
    """Load, refresh, rotate, and revoke delegated Graph tokens."""

    def __init__(
        self,
        credential: GraphCredential,
        *,
        token_store: TokenStore | None = None,
        transport: HttpTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        request_waiter: Callable[[], None] | None = None,
        refresh_skew: timedelta = timedelta(seconds=60),
        auth_max_attempts: int = 3,
        auth_base_delay: float = 1.0,
        auth_max_delay: float = 30.0,
    ) -> None:
        if not isinstance(credential, GraphCredential):
            raise TypeError("credential must be a GraphCredential")
        if refresh_skew < timedelta(0):
            raise ValueError("refresh_skew must not be negative")
        if not isinstance(auth_max_attempts, int) or auth_max_attempts < 1:
            raise ValueError("auth_max_attempts must be positive")
        if auth_base_delay < 0 or auth_max_delay < auth_base_delay:
            raise ValueError("invalid authentication retry delays")
        self.credential = credential
        self._store = token_store or default_token_store()
        self._transport = transport or UrllibHttpTransport()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or time.sleep
        self._request_waiter = request_waiter or (lambda: None)
        self._refresh_skew = refresh_skew
        self._auth_max_attempts = auth_max_attempts
        self._auth_base_delay = auth_base_delay
        self._auth_max_delay = auth_max_delay
        self._session_token: TokenSet | None = None
        self._lock = threading.Lock()

    def _load(self) -> TokenSet | None:
        try:
            token_set = self._store.load(self.credential.account.account_id)
        except SecureStorageError:
            raise
        except Exception as error:
            raise SecureStorageError(
                "Microsoft token storage could not be read"
            ) from error
        if (
            token_set is not None
            and token_set.credential_binding != self.credential.binding
        ):
            raise CredentialUnavailableError(
                "stored Microsoft token is bound to a different account configuration"
            )
        return token_set

    def set_request_waiter(self, request_waiter: Callable[[], None]) -> None:
        """Attach the shared Graph pacing boundary to token requests."""
        if not callable(request_waiter):
            raise TypeError("request_waiter must be callable")
        self._request_waiter = request_waiter

    def login(
        self,
        *,
        on_device_code: Callable[[_DeviceCode], None] | None = None,
    ) -> None:
        self._login_for_graph_client(on_device_code=on_device_code)

    def _login_for_graph_client(
        self,
        *,
        on_device_code: Callable[[_DeviceCode], None] | None = None,
    ) -> TokenSet:
        authenticator = _DeviceCodeAuthenticator(
            self.credential,
            transport=self._transport,
            clock=self._clock,
            sleep=self._sleep,
            request_waiter=self._request_waiter,
        )
        self._session_token = None
        token_set = authenticator.login(on_device_code=on_device_code)
        self._session_token = token_set
        return token_set

    def discard_session(self) -> None:
        """Discard a newly acquired grant that has not been identity-bound."""
        self._session_token = None

    def verified_identity(self) -> tuple[str | None, str | None]:
        """Return the provider identity last bound to the stored token."""
        token_set = self._load()
        if token_set is None:
            return None, None
        return token_set.verified_subject, token_set.verified_tenant

    def _bind_verified_identity(self, subject: str, tenant: str) -> TokenSet:
        """Persist identity observed by the Graph client after ``/me``."""
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("verified subject must be a non-empty string")
        if not isinstance(tenant, str) or not tenant.strip():
            raise ValueError("verified tenant must be a non-empty string")
        token_set = self._session_token or self._load()
        if token_set is None:
            raise CredentialUnavailableError("Microsoft account is not authenticated")
        bound = replace(
            token_set,
            verified_subject=subject,
            verified_tenant=tenant,
        )
        self._save(bound)
        self._session_token = None
        return bound

    def access_token(self, *, force_refresh: bool = False) -> str:
        return self._access_token_impl(force_refresh=force_refresh)

    def _access_token_for_graph_client(self, *, force_refresh: bool = False) -> str:
        return self._access_token_impl(
            force_refresh=force_refresh,
            allow_unverified=True,
        )

    def _access_token_impl(
        self, *, force_refresh: bool, allow_unverified: bool = False
    ) -> str:
        token_set = self._session_token or self._load()
        if token_set is None:
            raise CredentialUnavailableError("Microsoft account is not authenticated")
        if not allow_unverified and (
            token_set.verified_subject is None or token_set.verified_tenant is None
        ):
            raise CredentialUnavailableError(
                "Microsoft account identity has not been verified"
            )
        if not force_refresh and not token_set.is_expired(
            self._now(), refresh_skew=self._refresh_skew
        ):
            return token_set.access_token
        if token_set.refresh_token is None:
            raise CredentialUnavailableError(
                "Microsoft access token expired and no refresh token is available"
            )

        with self._lock:
            latest = self._session_token or self._load()
            if (
                latest is not None
                and not latest.is_expired(self._now(), refresh_skew=self._refresh_skew)
                and not force_refresh
            ):
                return latest.access_token
            if latest is not None:
                token_set = latest
            if token_set.refresh_token is None:
                raise CredentialUnavailableError(
                    "Microsoft access token expired and no refresh token is available"
                )
            refreshed = self._refresh(token_set)
            if self._session_token is not None:
                self._session_token = refreshed
            else:
                self._save(refreshed)
            return refreshed.access_token

    def revoke(self) -> None:
        """Revoke this app's local grant by deleting all local token material."""
        self._session_token = None
        try:
            self._store.delete(self.credential.account.account_id)
        except SecureStorageError:
            raise
        except Exception as error:
            raise SecureStorageError(
                "Microsoft token storage could not be revoked"
            ) from error

    def _refresh(self, previous: TokenSet) -> TokenSet:
        response = self._post_form_retry(
            f"{self.credential.authority_url}/oauth2/v2.0/token",
            {
                "client_id": self.credential.client_id,
                "grant_type": "refresh_token",
                "refresh_token": previous.refresh_token or "",
                "scope": " ".join(self.credential.requested_scopes),
            },
        )
        payload = self._payload_or_none(response)
        if response.status_code == 400 and _safe_provider_code(payload) in {
            "invalid_grant",
            "interaction_required",
            "invalid_client",
        }:
            self.revoke()
            raise CredentialRevokedError(
                "Microsoft refresh authorization is no longer valid"
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise _auth_response_error(response, payload)
        return _token_from_response(
            payload,
            self._now(),
            fallback_refresh_token=previous.refresh_token,
            fallback_scopes=previous.scopes,
            fallback_verified_subject=previous.verified_subject,
            fallback_verified_tenant=previous.verified_tenant,
        )

    def _post_form(self, url: str, values: Mapping[str, str]) -> HttpResponse:
        self._request_waiter()
        try:
            return self._transport.request(
                "POST",
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body=urlencode(values).encode("utf-8"),
            )
        except (ConnectionError, TimeoutError, OSError):
            raise GraphError(GraphErrorCode.NETWORK) from None

    def _post_form_retry(self, url: str, values: Mapping[str, str]) -> HttpResponse:
        for attempt in range(1, self._auth_max_attempts + 1):
            try:
                response = self._post_form(url, values)
            except GraphError:
                # A lost refresh response is ambiguous: retrying may replay a
                # refresh token that Microsoft already rotated.
                raise
            if response.status_code not in {429, 509}:
                return response
            if attempt == self._auth_max_attempts:
                return response
            retry_after = _response_retry_after(response)
            self._sleep(
                min(
                    (
                        retry_after
                        if retry_after is not None
                        else self._auth_base_delay * (2 ** (attempt - 1))
                    ),
                    self._auth_max_delay,
                )
            )
        raise GraphError(GraphErrorCode.UNKNOWN)

    @staticmethod
    def _payload_or_none(response: HttpResponse) -> object | None:
        if not response.body:
            return None
        return _json_body(response)

    def _save(self, token_set: TokenSet) -> None:
        token_set = replace(
            token_set,
            credential_binding=self.credential.binding,
        )
        try:
            self._store.save(self.credential.account.account_id, token_set)
        except SecureStorageError:
            raise
        except Exception as error:
            raise SecureStorageError(
                "Microsoft token storage could not be written"
            ) from error

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now


def _token_from_response(
    payload: object,
    now: datetime,
    *,
    fallback_refresh_token: str | None = None,
    fallback_scopes: tuple[str, ...] = (),
    fallback_verified_subject: str | None = None,
    fallback_verified_tenant: str | None = None,
) -> TokenSet:
    if not isinstance(payload, dict):
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE, 200)
    try:
        access_token = payload["access_token"]
        expires_in = int(payload["expires_in"])
        refresh_token = payload.get("refresh_token", fallback_refresh_token)
        scope_value = payload.get("scope")
        scopes = (
            tuple(scope_value.split())
            if isinstance(scope_value, str) and scope_value.strip()
            else fallback_scopes
        )
        return TokenSet(
            access_token=access_token,
            expires_at=now + timedelta(seconds=expires_in),
            refresh_token=refresh_token,
            scopes=scopes,
            token_type=payload.get("token_type", "Bearer"),
            verified_subject=fallback_verified_subject,
            verified_tenant=fallback_verified_tenant,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise GraphError(GraphErrorCode.MALFORMED_RESPONSE, 200) from error


def _response_retry_after(response: HttpResponse) -> float | None:
    value = _header(response.headers, "retry-after")
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
