"""Non-secret Microsoft Graph identity and token value objects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256

_TENANT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


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
class MicrosoftAccount:
    """A local account binding, separate from its short-lived token set.

    ``account_id`` is the local storage namespace.  ``user_id`` is a stable
    provider identity or verified sign-in name and is intentionally not used
    as the local key, so multiple accounts can later use the same mailbox
    address shape across tenants.
    """

    account_id: str
    user_id: str
    tenant: str = "common"

    def __post_init__(self) -> None:
        _require_text(self.account_id, "account_id")
        _require_text(self.user_id, "user_id")
        _require_text(self.tenant, "tenant")
        if not _TENANT_PATTERN.fullmatch(self.tenant):
            raise ValueError("tenant contains unsupported characters")


@dataclass(frozen=True, slots=True)
class GraphCredential:
    """Public-client configuration for delegated Microsoft Graph access.

    Client secrets are deliberately not a field.  The personal CLI uses the
    device authorization flow, where a native/public client does not need a
    client secret.  A future confidential deployment must provide its own
    separately governed secret provider rather than placing one here.
    """

    account: MicrosoftAccount
    client_id: str
    scopes: tuple[str, ...] = ("Mail.Read", "User.Read")
    authority_host: str = "https://login.microsoftonline.com"

    def __post_init__(self) -> None:
        if not isinstance(self.account, MicrosoftAccount):
            raise TypeError("account must be a MicrosoftAccount")
        _require_text(self.client_id, "client_id")
        if not isinstance(self.scopes, tuple):
            raise TypeError("scopes must be a tuple")
        if not self.scopes:
            raise ValueError("scopes must not be empty")
        for scope in self.scopes:
            _require_text(scope, "scope")
        _require_text(self.authority_host, "authority_host")
        if self.authority_host.rstrip("/") != "https://login.microsoftonline.com":
            raise ValueError("authority_host must be the Microsoft identity host")

    @property
    def authority_url(self) -> str:
        return f"{self.authority_host.rstrip('/')}/{self.account.tenant}"

    @property
    def requested_scopes(self) -> tuple[str, ...]:
        """Return resource scopes plus the refresh-token scope exactly once."""
        return (
            "offline_access",
            *tuple(scope for scope in self.scopes if scope.lower() != "offline_access"),
        )

    @property
    def binding(self) -> str:
        """Non-secret fingerprint that binds tokens to this credential config."""
        material = "\x1f".join(
            (
                self.account.account_id,
                self.account.user_id.casefold(),
                self.account.tenant.casefold(),
                self.client_id,
                *self.requested_scopes,
            )
        )
        return sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class TokenSet:
    """OAuth token material held only in memory or a secure token store.

    ``repr`` intentionally excludes every token field.  Callers should pass
    this object directly to the token manager and never serialize it into
    evidence, cursors, logs, or configuration.
    """

    access_token: str = field(repr=False)
    expires_at: datetime
    refresh_token: str | None = field(default=None, repr=False)
    scopes: tuple[str, ...] = ()
    token_type: str = "Bearer"
    credential_binding: str | None = None
    verified_subject: str | None = None
    verified_tenant: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.access_token, "access_token")
        _require_aware(self.expires_at, "expires_at")
        if self.refresh_token is not None:
            _require_text(self.refresh_token, "refresh_token")
        if not isinstance(self.scopes, tuple):
            raise TypeError("scopes must be a tuple")
        for scope in self.scopes:
            _require_text(scope, "scope")
        _require_text(self.token_type, "token_type")
        if self.token_type.lower() != "bearer":
            raise ValueError("only bearer Graph tokens are supported")
        if self.credential_binding is not None:
            if not re.fullmatch(r"[0-9a-f]{64}", self.credential_binding):
                raise ValueError("credential_binding must be a SHA-256 digest")
        _require_optional_text(self.verified_subject, "verified_subject")
        _require_optional_text(self.verified_tenant, "verified_tenant")

    def __repr__(self) -> str:
        return (
            "TokenSet(access_token='<redacted>', "
            "expires_at="
            f"{self.expires_at!r}, refresh_token='<redacted>' if present, "
            f"scopes={self.scopes!r}, token_type={self.token_type!r}, "
            f"credential_binding={self.credential_binding!r}, "
            f"verified_subject={self.verified_subject!r}, "
            f"verified_tenant={self.verified_tenant!r})"
        )

    def is_expired(
        self,
        now: datetime | None = None,
        *,
        refresh_skew: timedelta = timedelta(seconds=60),
    ) -> bool:
        """Treat a token near expiry as unusable to avoid request races."""
        current = datetime.now(timezone.utc) if now is None else now
        _require_aware(current, "now")
        if refresh_skew < timedelta(0):
            raise ValueError("refresh_skew must not be negative")
        return self.expires_at <= current + refresh_skew


@dataclass(frozen=True, slots=True, repr=False)
class _DeviceCode:
    """User-facing device-flow instructions plus private polling state."""

    user_code: str
    verification_uri: str
    message: str
    expires_at: datetime
    interval: float
    device_code: str = field(repr=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.user_code, "user_code"),
            (self.verification_uri, "verification_uri"),
            (self.message, "message"),
            (self.device_code, "device_code"),
        ):
            _require_text(value, name)
        _require_aware(self.expires_at, "expires_at")
        if not isinstance(self.interval, (int, float)) or self.interval <= 0:
            raise ValueError("interval must be positive")

    def __repr__(self) -> str:
        return (
            "DeviceCode(user_code="
            f"{self.user_code!r}, verification_uri={self.verification_uri!r}, "
            f"message={self.message!r}, expires_at={self.expires_at!r}, "
            f"interval={self.interval!r}, device_code='<redacted>')"
        )
