"""Secure local token-store implementations.

The default is an OS secret service.  The encrypted-file implementation is an
explicit opt-in for deployments that can supply its master key from an OS-
protected source; it never invents or persists a plaintext fallback.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .errors import SecureStorageError
from .models import TokenSet

_TOKEN_SCHEMA_VERSION = 1
_SERVICE_NAME = "lee-kb.microsoft-graph"


def _require_account_id(account_id: str) -> None:
    if not isinstance(account_id, str) or not account_id.strip():
        raise ValueError("account_id must be a non-empty string")
    if any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in account_id
    ):
        raise ValueError("account_id contains unsupported characters")


class TokenStore(Protocol):
    """Storage boundary; implementations must protect token material."""

    def load(self, account_id: str) -> TokenSet | None:
        """Load one account's token set or return ``None``."""

    def save(self, account_id: str, token_set: TokenSet) -> None:
        """Atomically replace one account's token set."""

    def delete(self, account_id: str) -> None:
        """Remove local token state for one account."""


class SecretStore(Protocol):
    """OS-protected opaque secret storage."""

    def get(self, key: str) -> str | None:
        """Return a stored secret without logging it."""

    def put(self, key: str, value: str) -> None:
        """Replace a stored secret."""

    def delete(self, key: str) -> None:
        """Delete a stored secret if present."""


class SecretToolStore:
    """Linux Secret Service adapter using ``secret-tool``.

    The token is sent over stdin for writes, never as a process argument.  A
    missing helper or a non-zero result is an explicit secure-storage failure.
    """

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or shutil.which("secret-tool")
        if self._executable is None:
            raise SecureStorageError("Linux Secret Service is unavailable")

    def _run(
        self,
        arguments: list[str],
        *,
        input_value: str | None = None,
        allow_missing: bool = False,
    ) -> str:
        try:
            result = subprocess.run(
                [self._executable, *arguments],
                input=None if input_value is None else input_value.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError as error:
            raise SecureStorageError("OS secret storage is unavailable") from error
        if result.returncode != 0 and not (allow_missing and result.returncode == 1):
            raise SecureStorageError("OS secret storage operation failed")
        return result.stdout.decode("utf-8").rstrip("\n")

    @staticmethod
    def _attributes(key: str) -> list[str]:
        return ["service", _SERVICE_NAME, "account", key]

    def get(self, key: str) -> str | None:
        _require_account_id(key)
        value = self._run(
            ["lookup", *self._attributes(key)],
            allow_missing=True,
        )
        return value or None

    def put(self, key: str, value: str) -> None:
        _require_account_id(key)
        if not isinstance(value, str) or not value:
            raise ValueError("secret value must be non-empty")
        self._run(
            [
                "store",
                "--label",
                "lee-kb Microsoft Graph token",
                *self._attributes(key),
            ],
            input_value=value,
        )

    def delete(self, key: str) -> None:
        _require_account_id(key)
        self._run(["clear", *self._attributes(key)], allow_missing=True)


class KeyringTokenStore:
    """Serialize token sets into an injected OS-protected secret store."""

    def __init__(self, secret_store: SecretStore) -> None:
        self._secret_store = secret_store

    def load(self, account_id: str) -> TokenSet | None:
        _require_account_id(account_id)
        raw = self._secret_store.get(account_id)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return _token_from_payload(payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise SecureStorageError(
                "stored Microsoft token data is invalid"
            ) from error

    def save(self, account_id: str, token_set: TokenSet) -> None:
        _require_account_id(account_id)
        if not isinstance(token_set, TokenSet):
            raise TypeError("token_set must be a TokenSet")
        payload = json.dumps(
            _token_to_payload(token_set), ensure_ascii=True, separators=(",", ":")
        )
        self._secret_store.put(account_id, payload)

    def delete(self, account_id: str) -> None:
        _require_account_id(account_id)
        self._secret_store.delete(account_id)


class InMemoryTokenStore:
    """Test-only store; never selected by ``default_token_store``."""

    def __init__(self) -> None:
        self._tokens: dict[str, TokenSet] = {}

    def load(self, account_id: str) -> TokenSet | None:
        _require_account_id(account_id)
        return self._tokens.get(account_id)

    def save(self, account_id: str, token_set: TokenSet) -> None:
        _require_account_id(account_id)
        if not isinstance(token_set, TokenSet):
            raise TypeError("token_set must be a TokenSet")
        self._tokens[account_id] = token_set

    def delete(self, account_id: str) -> None:
        _require_account_id(account_id)
        self._tokens.pop(account_id, None)


class EncryptedFileTokenStore:
    """AES-GCM token store with an externally supplied 256-bit master key.

    The key is intentionally not loaded from an environment variable by this
    class: callers must obtain it from an OS-protected mechanism.  The file is
    encrypted and mode ``0600``; if the optional cryptography package is not
    available, construction fails rather than writing plaintext.
    """

    def __init__(self, path: str | Path, master_key: bytes) -> None:
        if not isinstance(master_key, bytes) or len(master_key) != 32:
            raise ValueError("master_key must be exactly 32 bytes")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as error:
            raise SecureStorageError(
                "encrypted file token storage requires the cryptography package"
            ) from error
        self._aes = AESGCM(master_key)
        self._path = Path(path).expanduser()

    def load(self, account_id: str) -> TokenSet | None:
        _require_account_id(account_id)
        payload = self._read_payload()
        encoded = payload.get(account_id)
        if encoded is None:
            return None
        if not isinstance(encoded, str):
            raise SecureStorageError("encrypted token record is invalid")
        try:
            encrypted = base64.b64decode(encoded.encode("ascii"), validate=True)
            nonce, ciphertext = encrypted[:12], encrypted[12:]
            raw = self._aes.decrypt(nonce, ciphertext, account_id.encode("utf-8"))
            return _token_from_payload(json.loads(raw.decode("utf-8")))
        except Exception as error:
            raise SecureStorageError(
                "encrypted Microsoft token data is invalid"
            ) from error

    def save(self, account_id: str, token_set: TokenSet) -> None:
        _require_account_id(account_id)
        if not isinstance(token_set, TokenSet):
            raise TypeError("token_set must be a TokenSet")
        payload = self._read_payload()
        nonce = os.urandom(12)
        raw = json.dumps(
            _token_to_payload(token_set), ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        encrypted = nonce + self._aes.encrypt(nonce, raw, account_id.encode("utf-8"))
        payload[account_id] = base64.b64encode(encrypted).decode("ascii")
        self._write_payload(payload)

    def delete(self, account_id: str) -> None:
        _require_account_id(account_id)
        payload = self._read_payload()
        if account_id in payload:
            del payload[account_id]
            self._write_payload(payload)

    def _read_payload(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        try:
            if self._path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise SecureStorageError(
                    "encrypted token store permissions are too broad"
                )
        except OSError as error:
            raise SecureStorageError(
                "encrypted token store cannot be inspected"
            ) from error
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise SecureStorageError("encrypted token store cannot be read") from error
        if (
            not isinstance(raw, dict)
            or raw.get("version") != _TOKEN_SCHEMA_VERSION
            or not isinstance(raw.get("tokens"), dict)
        ):
            raise SecureStorageError("encrypted token store has an invalid format")
        return dict(raw["tokens"])

    def _write_payload(self, tokens: Mapping[str, object]) -> None:
        if not self._path.parent.exists():
            self._path.parent.mkdir(parents=True, mode=stat.S_IRWXU)
        payload = json.dumps(
            {"version": _TOKEN_SCHEMA_VERSION, "tokens": dict(tokens)},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.", dir=self._path.parent
        )
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self._path)
        except OSError as error:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise SecureStorageError(
                "encrypted token store cannot be written"
            ) from error


def _token_to_payload(token_set: TokenSet) -> dict[str, object]:
    return {
        "version": _TOKEN_SCHEMA_VERSION,
        "access_token": token_set.access_token,
        "expires_at": token_set.expires_at.isoformat(),
        "refresh_token": token_set.refresh_token,
        "scopes": list(token_set.scopes),
        "token_type": token_set.token_type,
        "credential_binding": token_set.credential_binding,
        "verified_subject": token_set.verified_subject,
        "verified_tenant": token_set.verified_tenant,
    }


def _token_from_payload(payload: object) -> TokenSet:
    if not isinstance(payload, dict) or payload.get("version") != _TOKEN_SCHEMA_VERSION:
        raise ValueError("unsupported token schema")
    scopes = payload.get("scopes", [])
    if not isinstance(scopes, list) or not all(
        isinstance(item, str) for item in scopes
    ):
        raise ValueError("invalid token scopes")
    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, str):
        raise ValueError("invalid token expiration")
    return TokenSet(
        access_token=payload["access_token"],
        expires_at=datetime.fromisoformat(expires_at),
        refresh_token=payload.get("refresh_token"),
        scopes=tuple(scopes),
        token_type=payload.get("token_type", "Bearer"),
        credential_binding=payload.get("credential_binding"),
        verified_subject=payload.get("verified_subject"),
        verified_tenant=payload.get("verified_tenant"),
    )


def default_token_store() -> TokenStore:
    """Select an OS-protected store or return a fail-closed unavailable store."""
    if shutil.which("secret-tool"):
        return KeyringTokenStore(SecretToolStore())
    return _UnavailableTokenStore()


class _UnavailableTokenStore:
    def _fail(self) -> None:
        raise SecureStorageError(
            "no supported OS-protected Microsoft token store is available"
        )

    def load(self, account_id: str) -> TokenSet | None:
        _require_account_id(account_id)
        self._fail()

    def save(self, account_id: str, token_set: TokenSet) -> None:
        _require_account_id(account_id)
        self._fail()

    def delete(self, account_id: str) -> None:
        _require_account_id(account_id)
        self._fail()
