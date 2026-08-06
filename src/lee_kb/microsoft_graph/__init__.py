"""Reusable Microsoft Graph plumbing.

The package deliberately stops at provider plumbing.  Connector modules map
Graph resources into the common lee-kb connector contract; this package owns
authentication, token lifecycle, HTTP execution, retries, pacing, and generic
collection/delta mechanics.
"""

from .auth import OAuthTokenManager, TokenStore
from .client import (
    GraphClient,
    GraphDeltaResult,
    GraphPage,
    RateLimiter,
    RetryPolicy,
    SpacingRateLimiter,
)
from .errors import (
    CredentialError,
    CredentialRevokedError,
    CredentialUnavailableError,
    GraphError,
    GraphErrorCode,
    SecureStorageError,
)
from .http import HttpResponse, HttpResponseTooLarge, HttpTransport, UrllibHttpTransport
from .models import (
    GraphCredential,
    MicrosoftAccount,
    TokenSet,
)
from .token_store import (
    EncryptedFileTokenStore,
    InMemoryTokenStore,
    KeyringTokenStore,
    SecretStore,
    SecretToolStore,
    default_token_store,
)

__all__ = [
    "EncryptedFileTokenStore",
    "CredentialError",
    "CredentialRevokedError",
    "CredentialUnavailableError",
    "GraphClient",
    "GraphCredential",
    "GraphDeltaResult",
    "GraphError",
    "GraphErrorCode",
    "GraphPage",
    "HttpResponse",
    "HttpResponseTooLarge",
    "HttpTransport",
    "InMemoryTokenStore",
    "KeyringTokenStore",
    "MicrosoftAccount",
    "OAuthTokenManager",
    "RateLimiter",
    "RetryPolicy",
    "SecureStorageError",
    "SecretStore",
    "SecretToolStore",
    "SpacingRateLimiter",
    "TokenSet",
    "TokenStore",
    "UrllibHttpTransport",
    "default_token_store",
]
