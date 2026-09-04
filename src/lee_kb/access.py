"""Authenticated, multi-principal access boundary for lee-kb.

The projection and governed retrieval pipeline predate transport authentication.
This module is the narrow seam between an authenticated client and that existing
pipeline.  A transport authenticates a registered client once, receives an
opaque session, and may then ask for knowledge only through that session.  The
session never carries authority by itself: every request re-resolves the
server-owned client record, employee identity, and currently active grants.

The module deliberately does not authenticate JWTs, Graph accounts, MCP peers,
or browser cookies.  Those are transport/source concerns.  They must call
:meth:`AccessRegistry.authenticate` with a credential that was provisioned for
one employee, then pass the resulting session to
:class:`AuthenticatedKnowledgeGateway`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .contracts import (
    WHOLE_ROOT_PATH_PREFIX,
    AccessAuditEvent,
    AccessAuditOutcome,
    EvidenceBundle,
    FreshnessRequirement,
    KnowledgeItem,
    Principal,
    RetrievalAuthContext,
    SourceGrant,
    compute_content_hash,
)
from .governance import PermissionEvaluator, SingleUserPermissionEvaluator
from .repository import Repository

ACCESS_POLICY_VERSION = "lee-kb.access.policy/v1"
ACCESS_STATE_VERSION = 1
DEFAULT_SESSION_TTL = timedelta(hours=1)
DEFAULT_CREDENTIAL_TTL = timedelta(days=90)
_ALLOWED_OPERATIONS = frozenset({"search", "read", "cite"})
_PBKDF2_ITERATIONS = 210_000
_MAX_QUERY_BYTES = 16 * 1024


class AccessError(RuntimeError):
    """Base class for authentication and knowledge-access failures."""


class AuthenticationError(AccessError):
    """The supplied client credential or session is not usable."""


class AuthorizationError(AccessError):
    """The authenticated employee has no matching active knowledge grant."""


class AccessStateError(AccessError):
    """The persisted client state is missing, corrupt, or unsafe."""


@dataclass(frozen=True, slots=True)
class EmployeeIdentity:
    """One server-owned employee identity independent of any transport."""

    employee_id: str
    principal: Principal
    tenant: str
    lane: str
    scope_id: str
    purpose: str

    def __post_init__(self) -> None:
        _require_text(self.employee_id, "employee_id")
        if not isinstance(self.principal, Principal):
            raise TypeError("principal must be a Principal")
        for value, name in (
            (self.tenant, "tenant"),
            (self.lane, "lane"),
            (self.scope_id, "scope_id"),
            (self.purpose, "purpose"),
        ):
            _require_text(value, name)

    @property
    def principal_id(self) -> str:
        return self.principal.principal_id


@dataclass(frozen=True, slots=True)
class SourceAddress:
    """Normalized source coordinates used during grant admission."""

    source_namespace: str
    root: str
    path: str
    item_id: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.source_namespace, "source_namespace"),
            (self.root, "root"),
            (self.path, "path"),
            (self.item_id, "item_id"),
        ):
            _require_text(value, name)


@dataclass(frozen=True, slots=True)
class KnowledgeGrant:
    """An explicit, bounded read/search grant for one employee principal.

    ``path_prefix`` follows :class:`~lee_kb.contracts.SourceGrant`: a relative
    prefix inside ``root``, or the whole-root sentinel ``"*"``.
    """

    grant_id: str
    principal_id: str
    tenant: str
    lane: str
    scope_id: str
    purpose: str
    project: str
    source_namespace: str
    root: str
    path_prefix: str
    operations: frozenset[str]
    item_ids: tuple[str, ...] = ()
    classification: str | None = None
    not_before: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    policy_version: str = ACCESS_POLICY_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.grant_id, "grant_id"),
            (self.principal_id, "principal_id"),
            (self.tenant, "tenant"),
            (self.lane, "lane"),
            (self.scope_id, "scope_id"),
            (self.purpose, "purpose"),
            (self.project, "project"),
            (self.source_namespace, "source_namespace"),
            (self.root, "root"),
            (self.path_prefix, "path_prefix"),
            (self.policy_version, "policy_version"),
        ):
            _require_text(value, name)
        if not isinstance(self.operations, frozenset):
            raise TypeError("operations must be a frozenset")
        if not self.operations or not self.operations <= _ALLOWED_OPERATIONS:
            raise ValueError(
                "operations must contain only non-empty search/read/cite values"
            )
        if not isinstance(self.item_ids, tuple):
            raise TypeError("item_ids must be a tuple")
        if any(
            not isinstance(value, str) or not value.strip() for value in self.item_ids
        ):
            raise ValueError("item_ids must contain non-empty strings")
        if self.classification is not None:
            _require_text(self.classification, "classification")
        for value, name in (
            (self.not_before, "not_before"),
            (self.expires_at, "expires_at"),
            (self.revoked_at, "revoked_at"),
        ):
            if value is not None:
                _require_aware(value, name)
        if (
            self.not_before is not None
            and self.expires_at is not None
            and self.expires_at <= self.not_before
        ):
            raise ValueError("grant expiry must be after not_before")
        if self.path_prefix.startswith("/") or "\x00" in self.path_prefix:
            raise ValueError("path_prefix must be relative")
        if self.path_prefix != WHOLE_ROOT_PATH_PREFIX:
            if "*" in self.path_prefix:
                raise ValueError("path_prefix must not contain wildcards")
            if any(part in {"", ".", ".."} for part in self.path_prefix.split("/")):
                raise ValueError("path_prefix must not contain traversal components")

    @property
    def source_grant(self) -> SourceGrant:
        """Return the compatible lower-level source grant contract."""
        return SourceGrant(
            project=self.project,
            source_namespace=self.source_namespace,
            root=self.root,
            path_prefix=self.path_prefix,
            item_ids=self.item_ids,
        )

    def permits(
        self,
        *,
        employee: EmployeeIdentity,
        address: SourceAddress,
        item: KnowledgeItem,
        operation: str,
        now: datetime,
    ) -> bool:
        """Evaluate this grant without consulting transport-supplied fields."""
        if (
            employee.tenant != self.tenant
            or employee.lane != self.lane
            or employee.scope_id != self.scope_id
            or employee.purpose != self.purpose
        ):
            return False
        if operation not in self.operations:
            return False
        if self.not_before is not None and now < self.not_before:
            return False
        if self.expires_at is not None and now >= self.expires_at:
            return False
        if self.revoked_at is not None and now >= self.revoked_at:
            return False
        if self.classification is not None and (
            item.permissions.classification != self.classification
        ):
            return False
        return self.source_grant.permits(
            project=item.project,
            source_namespace=address.source_namespace,
            root=address.root,
            path=address.path,
            item_id=address.item_id,
        )


@dataclass(frozen=True, slots=True)
class KnowledgePolicy:
    """Immutable employee and grant registry used by every gateway request."""

    employees: tuple[EmployeeIdentity, ...]
    grants: tuple[KnowledgeGrant, ...]
    version: str = ACCESS_POLICY_VERSION
    policy_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.employees, tuple) or not isinstance(self.grants, tuple):
            raise TypeError("employees and grants must be tuples")
        if not self.employees:
            raise ValueError("at least one employee identity is required")
        employee_ids = [employee.employee_id for employee in self.employees]
        principal_ids = [employee.principal_id for employee in self.employees]
        if len(set(employee_ids)) != len(employee_ids):
            raise ValueError("employee_id values must be unique")
        if len(set(principal_ids)) != len(principal_ids):
            raise ValueError("principal_id values must be unique")
        if any(
            not isinstance(employee, EmployeeIdentity) for employee in self.employees
        ):
            raise TypeError("employees must contain EmployeeIdentity values")
        if any(not isinstance(grant, KnowledgeGrant) for grant in self.grants):
            raise TypeError("grants must contain KnowledgeGrant values")
        grant_ids = [grant.grant_id for grant in self.grants]
        if len(set(grant_ids)) != len(grant_ids):
            raise ValueError("grant_id values must be unique")
        employees_by_principal = {
            employee.principal_id: employee for employee in self.employees
        }
        for grant in self.grants:
            employee = employees_by_principal.get(grant.principal_id)
            if employee is None:
                raise ValueError(f"grant {grant.grant_id!r} names an unknown principal")
            if grant.tenant != employee.tenant:
                raise ValueError(f"grant {grant.grant_id!r} crosses tenant boundary")
            if (
                grant.lane != employee.lane
                or grant.scope_id != employee.scope_id
                or grant.purpose != employee.purpose
            ):
                raise ValueError(
                    f"grant {grant.grant_id!r} does not match employee context"
                )
        _require_text(self.version, "version")
        body = {
            "version": self.version,
            "employees": [
                {
                    "employee_id": employee.employee_id,
                    "principal_id": employee.principal_id,
                    "principal_type": employee.principal.principal_type.value,
                    "tenant": employee.tenant,
                    "lane": employee.lane,
                    "scope_id": employee.scope_id,
                    "purpose": employee.purpose,
                }
                for employee in self.employees
            ],
            "grants": [_grant_body(grant) for grant in self.grants],
        }
        expected = compute_content_hash(
            json.dumps(body, sort_keys=True, separators=(",", ":"))
        )
        if self.policy_hash:
            if self.policy_hash != expected:
                raise ValueError("policy_hash does not match policy contents")
        else:
            object.__setattr__(self, "policy_hash", expected)

    def employee_for_principal(self, principal_id: str) -> EmployeeIdentity:
        for employee in self.employees:
            if employee.principal_id == principal_id:
                return employee
        raise AuthorizationError("employee principal is not configured")

    def active_grants(
        self,
        employee: EmployeeIdentity,
        *,
        project: str,
        operation: str,
        now: datetime,
    ) -> tuple[KnowledgeGrant, ...]:
        _require_aware(now, "now")
        return tuple(
            grant
            for grant in self.grants
            if grant.principal_id == employee.principal_id
            and grant.project == project
            and operation in grant.operations
            and (grant.not_before is None or now >= grant.not_before)
            and (grant.expires_at is None or now < grant.expires_at)
            and (grant.revoked_at is None or now < grant.revoked_at)
        )

    def grants_for(
        self,
        principal_id: str,
        *,
        project: str,
        now: datetime,
        operation: str = "search",
    ) -> tuple[KnowledgeGrant, ...]:
        """Return active grants for one explicit project and operation.

        This method intentionally does not grant access by itself.  The gateway
        still evaluates each candidate's source address and item ACL before
        releasing evidence.
        """
        self.employee_for_principal(principal_id)
        _require_text(project, "project")
        _require_text(operation, "operation")
        _require_aware(now, "now")
        return tuple(
            grant
            for grant in self.grants
            if grant.principal_id == principal_id
            and grant.project == project
            and operation in grant.operations
            and (grant.not_before is None or now >= grant.not_before)
            and (grant.expires_at is None or now < grant.expires_at)
            and (grant.revoked_at is None or now < grant.revoked_at)
        )


@dataclass(frozen=True, slots=True)
class ClientCredential:
    """One-time registration result; the secret is never persisted."""

    client_id: str
    client_secret: str = field(repr=False)
    principal_id: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.client_id, "client_id"),
            (self.client_secret, "client_secret"),
            (self.principal_id, "principal_id"),
        ):
            _require_text(value, name)
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("credential expiry must be after issuance")


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """Non-secret client registration metadata suitable for operator listing."""

    client_id: str
    principal_id: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        now = datetime.now(timezone.utc)
        return self.revoked_at is None and now < self.expires_at


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Opaque session ticket returned after server-side credential verification."""

    session_id: str = field(repr=False)
    client_id: str
    principal_id: str
    tenant: str
    lane: str
    scope_id: str
    purpose: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.session_id, "session_id"),
            (self.client_id, "client_id"),
            (self.principal_id, "principal_id"),
            (self.tenant, "tenant"),
            (self.lane, "lane"),
            (self.scope_id, "scope_id"),
            (self.purpose, "purpose"),
        ):
            _require_text(value, name)
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("session expiry must be after issuance")


@dataclass(frozen=True, slots=True)
class _ClientRecord:
    client_id: str
    principal_id: str
    salt: str
    digest: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _SessionRecord:
    ticket: AuthenticatedSession


class AccessAuditSink(Protocol):
    """Minimal sink used for non-content access evidence."""

    def record_access_event(self, event: AccessAuditEvent) -> int: ...


class AccessRegistry:
    """Credential, session, and revocation authority for one knowledge policy.

    Client registrations are persisted when ``state_path`` is supplied.  Only
    salted password-derived digests and revocation metadata are written; the
    one-time client secret and live sessions never enter the file.
    """

    def __init__(
        self,
        policy: KnowledgePolicy,
        *,
        state_path: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
        session_ttl: timedelta = DEFAULT_SESSION_TTL,
        credential_ttl: timedelta = DEFAULT_CREDENTIAL_TTL,
        audit_sink: AccessAuditSink | None = None,
    ) -> None:
        if audit_sink is not None and not callable(
            getattr(audit_sink, "record_access_event", None)
        ):
            raise TypeError("audit_sink must expose record_access_event")
        if not isinstance(policy, KnowledgePolicy):
            raise TypeError("policy must be a KnowledgePolicy")
        if not isinstance(session_ttl, timedelta) or session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")
        if not isinstance(credential_ttl, timedelta) or credential_ttl <= timedelta(0):
            raise ValueError("credential_ttl must be positive")
        self._policy = policy
        self._state_path = None if state_path is None else Path(state_path).expanduser()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._session_ttl = session_ttl
        self._credential_ttl = credential_ttl
        self._audit_sink = audit_sink
        self._clients: dict[str, _ClientRecord] = {}
        self._sessions: dict[str, _SessionRecord] = {}
        if self._state_path is not None and self._state_path.exists():
            self._load()

    @property
    def policy(self) -> KnowledgePolicy:
        return self._policy

    @property
    def policy_hash(self) -> str:
        return self._policy.policy_hash

    def replace_policy(self, policy: KnowledgePolicy) -> None:
        """Install a new server-owned policy; existing sessions recheck it."""
        if not isinstance(policy, KnowledgePolicy):
            raise TypeError("policy must be a KnowledgePolicy")
        self._policy = policy

    def set_audit_sink(self, audit_sink: AccessAuditSink) -> None:
        """Bind the durable sink used for credential/session lifecycle events."""
        if not callable(getattr(audit_sink, "record_access_event", None)):
            raise TypeError("audit_sink must expose record_access_event")
        self._audit_sink = audit_sink

    def register_client(
        self,
        principal_id: str,
        *,
        client_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> ClientCredential:
        self._policy.employee_for_principal(principal_id)
        now = self._now()
        if client_id is None:
            client_id = f"{principal_id}:client:{secrets.token_urlsafe(8)}"
        _require_text(client_id, "client_id")
        if client_id in self._clients:
            raise AccessStateError("client_id is already registered")
        if expires_at is None:
            expires_at = now + self._credential_ttl
        _require_aware(expires_at, "expires_at")
        if expires_at <= now:
            raise ValueError("client credential must expire in the future")
        secret = secrets.token_urlsafe(32)
        salt = secrets.token_hex(16)
        record = _ClientRecord(
            client_id=client_id,
            principal_id=principal_id,
            salt=salt,
            digest=_derive_secret(secret, salt),
            issued_at=now,
            expires_at=expires_at,
        )
        candidate = dict(self._clients)
        candidate[client_id] = record
        self._persist(candidate)
        self._clients = candidate
        self._record_control_event(
            client_id=client_id,
            session_id=None,
            principal_id=principal_id,
            operation="credential",
            reason_code="registered",
            timestamp=now,
        )
        return ClientCredential(client_id, secret, principal_id, now, expires_at)

    def list_clients(self) -> tuple[ClientInfo, ...]:
        return tuple(
            ClientInfo(
                client_id=record.client_id,
                principal_id=record.principal_id,
                issued_at=record.issued_at,
                expires_at=record.expires_at,
                revoked_at=record.revoked_at,
            )
            for record in sorted(
                self._clients.values(), key=lambda item: item.client_id
            )
        )

    def revoke_client(self, client_id: str, *, at: datetime | None = None) -> bool:
        _require_text(client_id, "client_id")
        record = self._clients.get(client_id)
        if record is None:
            return False
        when = at or self._now()
        _require_aware(when, "at")
        if record.revoked_at is not None:
            return True
        updated = _ClientRecord(
            client_id=record.client_id,
            principal_id=record.principal_id,
            salt=record.salt,
            digest=record.digest,
            issued_at=record.issued_at,
            expires_at=record.expires_at,
            revoked_at=when,
        )
        candidate = dict(self._clients)
        candidate[client_id] = updated
        self._persist(candidate)
        self._clients = candidate
        self._sessions = {
            session_id: session
            for session_id, session in self._sessions.items()
            if session.ticket.client_id != client_id
        }
        self._record_control_event(
            client_id=client_id,
            session_id=None,
            principal_id=record.principal_id,
            operation="credential",
            reason_code="client_revoked",
            timestamp=when,
        )
        return True

    def authenticate(self, client_id: str, client_secret: str) -> AuthenticatedSession:
        """Verify a credential and issue an opaque session bound to its client."""
        if (
            not isinstance(client_id, str)
            or not client_id.strip()
            or not isinstance(client_secret, str)
            or not client_secret.strip()
        ):
            raise AuthenticationError("invalid or revoked client credentials")
        record = self._clients.get(client_id)
        now = self._now()
        if (
            record is None
            or record.revoked_at is not None
            or now >= record.expires_at
            or not hmac.compare_digest(
                record.digest, _derive_secret(client_secret, record.salt)
            )
        ):
            raise AuthenticationError("invalid or revoked client credentials")
        employee = self._policy.employee_for_principal(record.principal_id)
        expires_at = min(record.expires_at, now + self._session_ttl)
        ticket = AuthenticatedSession(
            session_id=secrets.token_urlsafe(32),
            client_id=record.client_id,
            principal_id=employee.principal_id,
            tenant=employee.tenant,
            lane=employee.lane,
            scope_id=employee.scope_id,
            purpose=employee.purpose,
            issued_at=now,
            expires_at=expires_at,
        )
        self._sessions[ticket.session_id] = _SessionRecord(ticket)
        return ticket

    def resolve_session(
        self, session: str | AuthenticatedSession
    ) -> AuthenticatedSession:
        """Resolve a session from server state, ignoring client-supplied claims."""
        if isinstance(session, AuthenticatedSession):
            session_id = session.session_id
        elif isinstance(session, str) and session.strip():
            session_id = session
        else:
            raise AuthenticationError("session is expired or revoked")
        record = self._sessions.get(session_id)
        now = self._now()
        if record is None or now >= record.ticket.expires_at:
            self._sessions.pop(session_id, None)
            raise AuthenticationError("session is expired or revoked")
        client = self._clients.get(record.ticket.client_id)
        if (
            client is None
            or client.revoked_at is not None
            or now >= client.expires_at
            or client.principal_id != record.ticket.principal_id
        ):
            self._sessions.pop(session_id, None)
            raise AuthenticationError("session is expired or revoked")
        try:
            employee = self._policy.employee_for_principal(record.ticket.principal_id)
        except AuthorizationError as error:
            self._sessions.pop(session_id, None)
            raise AuthenticationError(
                "session identity is no longer authorized"
            ) from error
        if (
            record.ticket.tenant != employee.tenant
            or record.ticket.lane != employee.lane
            or record.ticket.scope_id != employee.scope_id
            or record.ticket.purpose != employee.purpose
        ):
            self._sessions.pop(session_id, None)
            raise AuthenticationError("session identity no longer matches policy")
        return record.ticket

    def revoke_session(self, session: str | AuthenticatedSession) -> bool:
        session_id = (
            session.session_id if isinstance(session, AuthenticatedSession) else session
        )
        _require_text(session_id, "session_id")
        record = self._sessions.pop(session_id, None)
        if record is None:
            return False
        self._record_control_event(
            client_id=record.ticket.client_id,
            session_id=record.ticket.session_id,
            principal_id=record.ticket.principal_id,
            operation="session",
            reason_code="session_revoked",
            timestamp=self._now(),
        )
        return True

    def _record_control_event(
        self,
        *,
        client_id: str,
        session_id: str | None,
        principal_id: str,
        operation: str,
        reason_code: str,
        timestamp: datetime,
    ) -> None:
        if self._audit_sink is None:
            return
        try:
            employee = self._policy.employee_for_principal(principal_id)
        except AuthorizationError:
            employee = None
        self._audit_sink.record_access_event(
            _audit_event(
                event_type="lifecycle",
                timestamp=timestamp,
                client_id=client_id,
                session_id=session_id,
                principal=None if employee is None else employee.principal,
                tenant="unknown" if employee is None else employee.tenant,
                project=None,
                operation=operation,
                outcome=AccessAuditOutcome.ALLOWED,
                reason_code=reason_code,
            )
        )

    def _now(self) -> datetime:
        now = self._clock()
        _require_aware(now, "clock")
        return now

    def _load(self) -> None:
        assert self._state_path is not None
        try:
            with self._state_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise AccessStateError("client state could not be read") from error
        if not isinstance(raw, dict) or raw.get("version") != ACCESS_STATE_VERSION:
            raise AccessStateError("unsupported client state version")
        clients = raw.get("clients")
        if not isinstance(clients, list):
            raise AccessStateError("client state clients are invalid")
        loaded: dict[str, _ClientRecord] = {}
        try:
            for value in clients:
                if not isinstance(value, dict):
                    raise ValueError
                record = _ClientRecord(
                    client_id=value["client_id"],
                    principal_id=value["principal_id"],
                    salt=value["salt"],
                    digest=value["digest"],
                    issued_at=datetime.fromisoformat(value["issued_at"]),
                    expires_at=datetime.fromisoformat(value["expires_at"]),
                    revoked_at=(
                        None
                        if value.get("revoked_at") is None
                        else datetime.fromisoformat(value["revoked_at"])
                    ),
                )
                _require_text(record.client_id, "client_id")
                _require_text(record.principal_id, "principal_id")
                _require_text(record.salt, "salt")
                if not re_hex(record.digest, 64):
                    raise ValueError
                _require_aware(record.issued_at, "issued_at")
                _require_aware(record.expires_at, "expires_at")
                if record.revoked_at is not None:
                    _require_aware(record.revoked_at, "revoked_at")
                self._policy.employee_for_principal(record.principal_id)
                if record.client_id in loaded:
                    raise ValueError
                loaded[record.client_id] = record
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise AccessStateError(
                "client state contains invalid registration"
            ) from error
        self._clients = loaded

    def _persist(self, clients: dict[str, _ClientRecord]) -> None:
        if self._state_path is None:
            return
        path = self._state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": ACCESS_STATE_VERSION,
            "clients": [
                {
                    "client_id": record.client_id,
                    "principal_id": record.principal_id,
                    "salt": record.salt,
                    "digest": record.digest,
                    "issued_at": record.issued_at.isoformat(),
                    "expires_at": record.expires_at.isoformat(),
                    "revoked_at": (
                        None
                        if record.revoked_at is None
                        else record.revoked_at.isoformat()
                    ),
                }
                for record in sorted(clients.values(), key=lambda item: item.client_id)
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


class _GrantPermissionEvaluator(PermissionEvaluator):
    def __init__(
        self,
        employee: EmployeeIdentity,
        grants: tuple[KnowledgeGrant, ...],
        *,
        address_for: Callable[[KnowledgeItem], SourceAddress],
        operation: str,
        now: datetime,
    ) -> None:
        self._employee = employee
        self._grants = grants
        self._address_for = address_for
        self._operation = operation
        self._now = now
        self._item_permissions = SingleUserPermissionEvaluator()

    def is_permitted(self, item: KnowledgeItem, principal: Principal) -> bool:
        if principal != self._employee.principal:
            return False
        address = self._address_for(item)
        if not any(
            grant.permits(
                employee=self._employee,
                address=address,
                item=item,
                operation=self._operation,
                now=self._now,
            )
            for grant in self._grants
        ):
            return False
        return self._item_permissions.is_permitted(item, principal)


class AuthenticatedKnowledgeGateway:
    """Lee-kb retrieval facade requiring a verified client session."""

    def __init__(
        self,
        repository: Repository,
        registry: AccessRegistry,
        *,
        address_for: Callable[[KnowledgeItem], SourceAddress] | None = None,
        audit_sink: AccessAuditSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(registry, AccessRegistry):
            raise TypeError("registry must be an AccessRegistry")
        if audit_sink is None:
            record_access_event = getattr(type(repository), "record_access_event", None)
            if record_access_event is not None and (
                record_access_event is not Repository.record_access_event
            ):
                audit_sink = repository  # type: ignore[assignment]
        if audit_sink is None:
            raise AccessStateError("durable access audit sink is required")
        self._repository = repository
        self._registry = registry
        self._address_for = address_for or default_source_address
        self._audit_sink = audit_sink
        self._registry.set_audit_sink(audit_sink)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._local_audit: list[AccessAuditEvent] = []

    @property
    def registry(self) -> AccessRegistry:
        return self._registry

    def authenticate(self, client_id: str, client_secret: str) -> AuthenticatedSession:
        safe_client_id = (
            client_id if isinstance(client_id, str) and client_id.strip() else "unknown"
        )
        try:
            session = self._registry.authenticate(client_id, client_secret)
        except AuthenticationError:
            self._record_audit(
                _audit_event(
                    event_type="authentication",
                    timestamp=self._now(),
                    client_id=safe_client_id,
                    session_id=None,
                    principal=None,
                    tenant="unknown",
                    project=None,
                    operation="session",
                    outcome=AccessAuditOutcome.DENIED,
                    reason_code="invalid_credentials",
                )
            )
            raise
        employee = self._registry.policy.employee_for_principal(session.principal_id)
        self._record_audit(
            _audit_event(
                event_type="authentication",
                timestamp=session.issued_at,
                client_id=session.client_id,
                session_id=session.session_id,
                principal=employee.principal,
                tenant=employee.tenant,
                project=None,
                operation="session",
                outcome=AccessAuditOutcome.ALLOWED,
                reason_code="authenticated",
            )
        )
        return session

    def retrieve(
        self,
        session: str | AuthenticatedSession,
        query: str,
        *,
        project: str,
        top_k: int = 10,
        freshness: FreshnessRequirement | None = None,
    ) -> EvidenceBundle:
        """Retrieve only through a server-resolved session and explicit project."""
        ticket = self._resolve(session)
        _require_text(query, "query")
        if len(query.encode("utf-8")) > _MAX_QUERY_BYTES:
            raise ValueError("query exceeds maximum size")
        _require_text(project, "project")
        now = self._now()
        employee = self._registry.policy.employee_for_principal(ticket.principal_id)
        grants = self._registry.policy.grants_for(
            ticket.principal_id,
            project=project,
            now=now,
            operation="search",
        )
        if not grants:
            self._deny(
                ticket,
                employee,
                project=project,
                operation="search",
                reason_code="project_not_granted",
                query=query,
            )
            raise AuthorizationError("knowledge project is not granted")
        context = RetrievalAuthContext(
            client_id=ticket.client_id,
            session_id=session_reference(ticket.session_id),
            grant_ids=tuple(grant.grant_id for grant in grants),
        )
        try:
            from .governance import retrieve

            bundle = retrieve(
                self._repository,
                query,
                principal=employee.principal,
                project=project,
                top_k=top_k,
                freshness=freshness,
                permission_evaluator=_GrantPermissionEvaluator(
                    employee,
                    grants,
                    address_for=self._address_for,
                    operation="search",
                    now=now,
                ),
                clock=lambda: now,
                auth_context=context,
            )
        except Exception:
            self._record_audit(
                _audit_event(
                    # The client identifier is metadata; normalize invalid input
                    # so audit failure cannot become an information oracle.
                    event_type="retrieval",
                    timestamp=self._now(),
                    client_id=ticket.client_id,
                    session_id=ticket.session_id,
                    principal=employee.principal,
                    tenant=employee.tenant,
                    project=project,
                    operation="search",
                    outcome=AccessAuditOutcome.DENIED,
                    reason_code="retrieval_failed",
                    grant_ids=context.grant_ids,
                    query=query,
                )
            )
            raise
        self._record_audit(
            _audit_event(
                event_type="retrieval",
                timestamp=bundle.retrieval_timestamp,
                client_id=ticket.client_id,
                session_id=ticket.session_id,
                principal=employee.principal,
                tenant=employee.tenant,
                project=project,
                operation="search",
                outcome=AccessAuditOutcome.ALLOWED,
                reason_code="retrieved",
                grant_ids=context.grant_ids,
                query=query,
                freshness_state=("stale" if bundle.freshness.is_stale else "fresh"),
            )
        )
        return bundle

    def audit_events(self) -> tuple[AccessAuditEvent, ...]:
        """Return local non-content audit events for transports without a sink."""
        return tuple(self._local_audit)

    def _resolve(self, session: str | AuthenticatedSession) -> AuthenticatedSession:
        try:
            return self._registry.resolve_session(session)
        except AuthenticationError:
            if isinstance(session, AuthenticatedSession):
                client_id = session.client_id
                session_id = session.session_id
            else:
                client_id = "unknown"
                session_id = (
                    session if isinstance(session, str) and session.strip() else None
                )
            self._record_audit(
                _audit_event(
                    event_type="authentication",
                    timestamp=self._now(),
                    client_id=client_id,
                    session_id=session_id,
                    principal=None,
                    tenant="unknown",
                    project=None,
                    operation="session",
                    outcome=AccessAuditOutcome.DENIED,
                    reason_code="invalid_session",
                )
            )
            raise

    def _deny(
        self,
        ticket: AuthenticatedSession,
        employee: EmployeeIdentity,
        *,
        project: str,
        operation: str,
        reason_code: str,
        query: str,
    ) -> None:
        self._record_audit(
            _audit_event(
                event_type="authorization",
                timestamp=self._now(),
                client_id=ticket.client_id,
                session_id=ticket.session_id,
                principal=employee.principal,
                tenant=employee.tenant,
                project=project,
                operation=operation,
                outcome=AccessAuditOutcome.DENIED,
                reason_code=reason_code,
                query=query,
            )
        )

    def _record_audit(self, event: AccessAuditEvent) -> None:
        self._local_audit.append(event)
        if self._audit_sink is not None:
            self._audit_sink.record_access_event(event)

    def _now(self) -> datetime:
        now = self._clock()
        _require_aware(now, "clock")
        return now


def default_source_address(item: KnowledgeItem) -> SourceAddress:
    """Derive safe source coordinates for shipped connectors."""
    connector_id = item.item_id.connector_id
    source_object_id = item.item_id.source_object_id
    if connector_id == "local_files" and ":" in source_object_id:
        root, path = source_object_id.split(":", 1)
    else:
        root, path = connector_id, source_object_id
    return SourceAddress(connector_id, root, path, str(item.item_id))


def session_reference(session_id: str | None) -> str | None:
    """One-way audit reference for a session bearer token.

    A session id is a bearer credential: whoever holds it can drive governed
    retrieval until it expires.  Persisted audit rows, receipts, and wire
    payloads therefore carry only this collision-resistant reference, never
    the raw token.  Two calls in one session remain correlatable; the stored
    value cannot be replayed as a session.
    """
    if session_id is None:
        return None
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _audit_event(
    *,
    event_type: str,
    timestamp: datetime,
    client_id: str,
    session_id: str | None,
    principal: Principal | None,
    tenant: str,
    project: str | None,
    operation: str,
    outcome: AccessAuditOutcome,
    reason_code: str,
    grant_ids: tuple[str, ...] = (),
    query: str | None = None,
    freshness_state: str | None = None,
) -> AccessAuditEvent:
    return AccessAuditEvent(
        event_type=event_type,
        timestamp=timestamp,
        client_id=client_id,
        session_id=session_reference(session_id),
        principal=principal,
        tenant=tenant,
        project=project,
        operation=operation,
        outcome=outcome,
        reason_code=reason_code,
        grant_ids=grant_ids,
        query_digest=None if query is None else compute_content_hash(query),
        freshness_state=freshness_state,
    )


def _grant_body(grant: KnowledgeGrant) -> dict[str, Any]:
    return {
        "grant_id": grant.grant_id,
        "principal_id": grant.principal_id,
        "tenant": grant.tenant,
        "lane": grant.lane,
        "scope_id": grant.scope_id,
        "purpose": grant.purpose,
        "project": grant.project,
        "source_namespace": grant.source_namespace,
        "root": grant.root,
        "path_prefix": grant.path_prefix,
        "operations": sorted(grant.operations),
        "item_ids": list(grant.item_ids),
        "classification": grant.classification,
        "not_before": (
            None if grant.not_before is None else grant.not_before.isoformat()
        ),
        "expires_at": (
            None if grant.expires_at is None else grant.expires_at.isoformat()
        ),
        "revoked_at": (
            None if grant.revoked_at is None else grant.revoked_at.isoformat()
        ),
        "policy_version": grant.policy_version,
    }


def _grant_probe_item(grant: KnowledgeGrant) -> KnowledgeItem:
    """Unused compatibility helper retained out of the admission hot path."""
    raise RuntimeError(f"grant probe is not a retrieval item: {grant.grant_id}")


def _derive_secret(secret: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ITERATIONS
    ).hex()


def re_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(char in "0123456789abcdef" for char in value)
    )


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(value: object, name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


__all__ = [
    "ACCESS_POLICY_VERSION",
    "ACCESS_STATE_VERSION",
    "AccessError",
    "AccessStateError",
    "AuthenticationError",
    "AuthorizationError",
    "EmployeeIdentity",
    "SourceAddress",
    "KnowledgeGrant",
    "KnowledgePolicy",
    "ClientCredential",
    "ClientInfo",
    "AuthenticatedSession",
    "AccessRegistry",
    "AccessAuditSink",
    "default_source_address",
    "session_reference",
]
