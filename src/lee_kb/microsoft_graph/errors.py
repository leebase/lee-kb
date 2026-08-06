"""Safe, provider-independent Graph error classifications."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GraphErrorCode(str, Enum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    DELTA_EXPIRED = "delta_expired"
    INVALID_REQUEST = "invalid_request"
    MALFORMED_RESPONSE = "malformed_response"
    NOT_FOUND = "not_found"
    NETWORK = "network"
    THROTTLED = "throttled"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GraphError(Exception):
    """A normalized failure that never carries a provider response body.

    Microsoft Graph error messages can contain dynamic resource information.
    Only a bounded machine code, HTTP status, request ID, and retry hint are
    retained.  Request IDs are useful for support and contain no bearer token;
    callers may omit them from user-facing output.
    """

    code: GraphErrorCode
    status_code: int | None = None
    provider_code: str | None = None
    request_id: str | None = None
    retry_after: float | None = None
    attempts: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.code, GraphErrorCode):
            raise TypeError("code must be a GraphErrorCode")
        if self.status_code is not None and (
            not isinstance(self.status_code, int) or self.status_code < 100
        ):
            raise ValueError("status_code must be a valid HTTP status")
        if self.provider_code is not None and (
            not isinstance(self.provider_code, str) or not self.provider_code
        ):
            raise ValueError("provider_code must be non-empty when present")
        if self.request_id is not None and (
            not isinstance(self.request_id, str) or not self.request_id
        ):
            raise ValueError("request_id must be non-empty when present")
        if self.retry_after is not None and self.retry_after < 0:
            raise ValueError("retry_after must not be negative")
        if not isinstance(self.attempts, int) or self.attempts < 1:
            raise ValueError("attempts must be positive")
        Exception.__init__(self, self.safe_message)

    @property
    def safe_message(self) -> str:
        if self.status_code is None:
            return f"Microsoft Graph {self.code.value} failure"
        return f"Microsoft Graph request failed ({self.status_code}: {self.code.value})"

    @property
    def retryable(self) -> bool:
        return self.code in {
            GraphErrorCode.NETWORK,
            GraphErrorCode.THROTTLED,
            GraphErrorCode.TRANSIENT,
        }

    def __str__(self) -> str:
        return self.safe_message


class CredentialError(Exception):
    """Base class for local credential and token lifecycle failures."""


class CredentialUnavailableError(CredentialError):
    """No usable token or secure token storage is available."""


class CredentialRevokedError(CredentialError):
    """The refresh grant is no longer valid and local state was removed."""


class SecureStorageError(CredentialError):
    """Secure token storage failed; callers must fail closed."""
