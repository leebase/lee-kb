"""Read-only-compatible MCP adapter over the governed lee-kb retrieval path.

The incumbent ``kb-index`` server speaks JSON-RPC 2.0 over newline-delimited
stdio and exposes three tools.  This module keeps that wire contract stable
while routing search and preview through :func:`lee_kb.governance.retrieve`.
The retrieval path persists its normal evidence receipts and the adapter adds
those receipts to the incumbent-compatible result objects.

The adapter never synchronizes sources, rebuilds the projection, or writes
corpus files.  Search and preview do write the receipts and query-audit rows
required by lee-kb's governed retrieval contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import __version__
from .access import (
    AccessError,
    AccessRegistry,
    AuthenticatedKnowledgeGateway,
    AuthenticatedSession,
    AuthorizationError,
    KnowledgeGrant,
)
from .access_store import clients_path_for, load_policy, policy_path_for
from .connectors.base import ConnectorConfigError
from .connectors.local_files import (
    LocalFilesConnector,
    RootConfig,
    _glob_match,
    load_config,
)
from .contracts import (
    DEFAULT_PROJECT,
    SCHEMA_VERSION,
    WHOLE_ROOT_PATH_PREFIX,
    Evidence,
    EvidenceBundle,
    HistoricalLocator,
    HistoricalLookupResult,
    HistoricalReceipt,
    OwnerCurrentReceipt,
    OwnerKnowledgeState,
    Principal,
    RetrievalReceipt,
)
from .governance import (
    MissingPrincipalError,
    RetrievalProviderError,
)
from .governance import retrieve as governed_retrieve
from .main import _load_raw_config, _resolve_database_path, resolve_config_path
from .owner import (
    GitExactObjectResolver,
    OwnerAccessError,
    OwnerConfigurationError,
    OwnerGateway,
    OwnerGatewayConfig,
    load_owner_gateway,
    owner_handshake,
)
from .repository import SQLiteRepository

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "lee-kb"
SERVER_VERSION = __version__
EMPLOYEE_MAPPING_VERSION = "lee-kb.employee.mapping/v1"
EMPLOYEE_RECEIPT_VERSION = "lee-kb.employee.receipt/v1"

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Employee-mode denials are deliberately identical for an unknown client, a
# wrong secret, a revoked client, and an expired credential.
ACCESS_DENIED_MESSAGE = "lee-kb access denied: invalid or revoked client credentials"
PROJECT_NOT_GRANTED_MESSAGE = "lee-kb access denied: knowledge project is not granted"
# Owner-gateway denials never say which basis failed.
OWNER_DENIED_MESSAGE = "lee-kb access denied: owner request is not permitted"

# The one non-enumerating exact-history answer for every withheld body.
UNKNOWN_HISTORY: dict[str, Any] = {
    "knowledge_state": "unknown",
    "freshness_state": "unknown",
    "body": None,
    "receipt": None,
}

# The transport never carries identity: employee credentials reach this server
# only through its own environment, never through a tool argument.
CLIENT_ID_ENV = "LEE_KB_CLIENT_ID"
CLIENT_SECRET_ENV = "LEE_KB_CLIENT_SECRET"
CLIENT_SECRET_FILE_ENV = "LEE_KB_CLIENT_SECRET_FILE"

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "kb_search",
        "description": (
            "Search the governed lee-kb knowledge projection. Returns the "
            "incumbent result fields plus provenance and retrieval receipts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Max hits (1–20, default 5)",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kb_status",
        "description": (
            "Report lee-kb projection and configured-root freshness status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "kb_compile_preview",
        "description": (
            "Return a read-only provenance-stamped Markdown briefing from "
            "governed retrieval (limit=20), with receipt references."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Briefing topic / search query",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kb_history_get",
        "description": (
            "Return one exact governed historical object only when current "
            "and source-owner historical-release policy both allow it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {"type": "string"},
                "commit": {"type": "string"},
                "path": {"type": "string"},
                "classification": {"type": "string"},
            },
            "required": ["repository", "commit", "path", "classification"],
            "additionalProperties": False,
        },
    },
]

# Employee clients get a deliberately narrower advertised surface.  Requiring
# the bound on search avoids an implicit server-selected result volume, and
# exact history remains owner-gateway-only.
EMPLOYEE_TOOL_DEFS: list[dict[str, Any]] = [
    {
        **TOOL_DEFS[0],
        "inputSchema": {
            **TOOL_DEFS[0]["inputSchema"],
            "required": ["query", "limit"],
        },
    },
    *TOOL_DEFS[1:3],
]


class MCPConfigurationError(RuntimeError):
    """Raised when the server cannot resolve a usable lee-kb deployment."""


class MCPToolError(RuntimeError):
    """Carries a client-safe, non-enumerating message for one tool reply."""


@dataclass(frozen=True, slots=True)
class _EmployeeAccess:
    """Server-resolved employee credential material for this MCP process."""

    client_id: str
    secret: str = field(repr=False)
    policy_path: Path
    clients_path: Path


@dataclass(frozen=True, slots=True)
class _Runtime:
    config_path: Path
    raw_config: dict[str, Any]
    database_path: Path
    principal: Principal
    project: str
    roots: tuple[RootConfig, ...]
    owner_gateway: OwnerGatewayConfig | None = None
    employee: _EmployeeAccess | None = None


@dataclass(frozen=True, slots=True)
class _EmployeeCall:
    """One authenticated employee tool call and the state that admitted it.

    ``repository`` and ``gateway`` are absent only when the deployment has no
    projection to retrieve from or to audit into.
    """

    runtime: _Runtime
    session: AuthenticatedSession
    policy: KnowledgePolicy
    repository: SQLiteRepository | None = None
    gateway: AuthenticatedKnowledgeGateway | None = None


@dataclass(frozen=True, slots=True)
class _Projection:
    """Read-only status facts from the SQLite projection."""

    schema_version: int
    cursors: dict[str, dict[str, Any]]
    counts: dict[tuple[str, str], tuple[int, int]]
    source_counts: dict[tuple[str, str, str], int]


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _error(req_id: Any, code: int, message: str, data: Any = None) -> None:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    _write({"jsonrpc": "2.0", "id": req_id, "error": error})


def _result(req_id: Any, result: Any) -> None:
    _write({"jsonrpc": "2.0", "id": req_id, "result": result})


def _tool_text(req_id: Any, text: str, *, is_error: bool = False) -> None:
    payload: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
    }
    if is_error:
        payload["isError"] = True
    _result(req_id, payload)


def _employee_secret() -> str | None:
    """Read the employee client secret from the environment or its file."""
    secret = os.environ.get(CLIENT_SECRET_ENV)
    if secret is not None and secret.strip():
        return secret
    secret_file = os.environ.get(CLIENT_SECRET_FILE_ENV)
    if secret_file is None or not secret_file.strip():
        return None
    try:
        raw = Path(secret_file).expanduser().read_text(encoding="utf-8")
    except OSError:
        return None
    secret = raw.rstrip("\r\n")
    return secret if secret.strip() else None


def _employee_access(config_path: Path) -> _EmployeeAccess | None:
    """Resolve employee credentials from this server's own environment.

    A configured client id switches the process into employee mode for its
    whole lifetime.  Unusable credential material denies every governed call
    rather than falling back to the configured owner principal.
    """
    client_id = os.environ.get(CLIENT_ID_ENV)
    if client_id is None:
        return None
    secret = _employee_secret()
    if not client_id.strip() or secret is None:
        raise MCPToolError(ACCESS_DENIED_MESSAGE)
    return _EmployeeAccess(
        client_id=client_id,
        secret=secret,
        policy_path=policy_path_for(config_path),
        clients_path=clients_path_for(config_path),
    )


def _runtime() -> _Runtime:
    config_path = resolve_config_path(None)
    try:
        raw_config = _load_raw_config(config_path)
    except ConnectorConfigError as error:
        raise MCPConfigurationError(str(error)) from error

    raw_roots = raw_config.get("roots")
    if raw_roots is None:
        roots: tuple[RootConfig, ...] = ()
    else:
        try:
            roots = load_config(config_path)
        except ConnectorConfigError as error:
            raise MCPConfigurationError(str(error)) from error

    try:
        owner_gateway = load_owner_gateway(raw_config)
    except OwnerConfigurationError as error:
        raise MCPConfigurationError(
            f"owner gateway configuration is invalid: {error}"
        ) from error
    if owner_gateway is not None and _employee_mode():
        # Two identity authorities would make the released scope ambiguous.
        raise MCPConfigurationError(
            "employee credentials and owner-gateway configuration cannot both be set"
        )

    owner = raw_config.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        owner = roots[0].owner if roots else "lee@leebase.com"
    try:
        principal = Principal(owner)
    except (TypeError, ValueError) as error:
        raise MCPConfigurationError("configured owner is invalid") from error

    configured_project = os.environ.get("LEE_KB_MCP_PROJECT")
    if configured_project is not None and configured_project.strip():
        project = configured_project.strip()
    else:
        projects = {root.project for root in roots}
        project = next(iter(projects)) if len(projects) == 1 else DEFAULT_PROJECT

    return _Runtime(
        config_path=config_path,
        raw_config=raw_config,
        database_path=_resolve_database_path(config_path, raw_config),
        principal=principal,
        project=project,
        roots=roots,
        employee=_employee_access(config_path),
        owner_gateway=owner_gateway,
    )


def _employee_mode() -> bool:
    """Return whether this process serves one authenticated employee client."""
    return CLIENT_ID_ENV in os.environ


def _load_access(employee: _EmployeeAccess) -> tuple[KnowledgePolicy, AccessRegistry]:
    """Re-read policy and client state so live CLI changes apply per call."""
    try:
        policy = load_policy(employee.policy_path)
        return policy, AccessRegistry(policy, state_path=employee.clients_path)
    except (AccessError, OSError) as error:
        raise MCPToolError(ACCESS_DENIED_MESSAGE) from error


def _authenticate(
    authority: AccessRegistry | AuthenticatedKnowledgeGateway,
    employee: _EmployeeAccess,
) -> AuthenticatedSession:
    try:
        return authority.authenticate(employee.client_id, employee.secret)
    except AccessError as error:
        raise MCPToolError(ACCESS_DENIED_MESSAGE) from error


@contextmanager
def _governed_call() -> Iterator[_EmployeeCall | None]:
    """Yield an authenticated employee call, or ``None`` in owner mode.

    Employee mode verifies its credential once per tool call against policy
    and client state read from disk, so a revoked grant or credential applies
    to an already running server process.
    """
    if not _employee_mode():
        yield None
        return
    try:
        runtime = _runtime()
    except MCPConfigurationError as error:
        # Report a broken deployment exactly as owner mode reports it.
        raise MCPToolError(f"lee-kb status failed: {error}") from error
    employee = runtime.employee
    if employee is None:
        # _runtime() resolves employee mode from the same environment variable,
        # so this only fires if that variable disappeared mid-call.
        raise MCPToolError(ACCESS_DENIED_MESSAGE)
    policy, registry = _load_access(employee)
    if not runtime.database_path.is_file():
        # Without a projection there is no durable audit sink to write into.
        # The credential is still verified here so a denied caller cannot read
        # deployment facts out of a status or search reply.
        yield _EmployeeCall(runtime, _authenticate(registry, employee), policy)
        return
    with SQLiteRepository(runtime.database_path) as repository:
        try:
            gateway = AuthenticatedKnowledgeGateway(repository, registry)
        except AccessError as error:
            raise MCPToolError(ACCESS_DENIED_MESSAGE) from error
        session = _authenticate(gateway, employee)
        yield _EmployeeCall(runtime, session, policy, repository, gateway)


def _root_path(runtime: _Runtime, root: RootConfig) -> str:
    raw_roots = runtime.raw_config.get("roots")
    if isinstance(raw_roots, dict):
        raw_root = raw_roots.get(root.name)
        if isinstance(raw_root, dict) and isinstance(raw_root.get("path"), str):
            return raw_root["path"]
    return str(root.path)


def _source_root(connector_id: str, source_object_id: str) -> str:
    if connector_id == "local_files" and ":" in source_object_id:
        return source_object_id.split(":", 1)[0]
    return connector_id


def _source_path(
    connector_id: str, source_object_id: str, label: str | None, uri: str
) -> str:
    if connector_id == "local_files" and ":" in source_object_id:
        return source_object_id.split(":", 1)[1]
    return label or uri


def _owner_source_scope(
    item: Any,
) -> tuple[str, str, str]:
    """Place one knowledge item in the (namespace, root, path) grant space."""
    locator = item.source_locator
    source_object_id = item.item_id.source_object_id
    return (
        locator.connector_id,
        _source_root(locator.connector_id, source_object_id),
        _source_path(
            locator.connector_id, source_object_id, locator.label, locator.uri
        ),
    )


def _owner_gateway(
    config: OwnerGatewayConfig, repository: SQLiteRepository | None
) -> OwnerGateway:
    """Build the owner gateway this process serves, entirely from configuration."""
    return OwnerGateway(
        repository,
        mapping=config.mapping,
        manifest=config.manifest,
        current_permission=config.current_permission(),
        resolver=GitExactObjectResolver(
            config.repository_paths(), config.classification_for
        ),
        source_mapping=_owner_source_scope,
    )


def _owner_handshake() -> dict[str, str] | None:
    """Return the additive owner handshake, or ``None`` outside owner mode."""
    if _employee_mode():
        return None
    try:
        runtime = _runtime()
    except (MCPConfigurationError, MCPToolError):
        return None
    if runtime.owner_gateway is None:
        return None
    return owner_handshake(runtime.owner_gateway.mapping)


def _read_projection(path: Path) -> _Projection:
    """Read SQLite status metadata without opening it in write mode."""
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:
        raise MCPConfigurationError("projection could not be opened") from error

    try:
        connection.row_factory = sqlite3.Row
        try:
            schema_row = connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if schema_row is None:
                raise MCPConfigurationError("projection schema version is missing")
            schema_version = int(schema_row["value"])
            if schema_version not in (1, SCHEMA_VERSION):
                raise MCPConfigurationError(
                    f"unsupported projection schema version {schema_version}"
                )

            cursors: dict[str, dict[str, Any]] = {}
            for row in connection.execute(
                "SELECT connector_id, cursor FROM connector_sync_state"
            ):
                try:
                    value = json.loads(row["cursor"])
                except (TypeError, json.JSONDecodeError) as error:
                    raise MCPConfigurationError(
                        "projection cursor is invalid"
                    ) from error
                # Each shipped connector persists a JSON object, but their
                # payloads are intentionally different: local files use a
                # flat source-id/hash map, Outlook stores nested object
                # metadata, and Calendar stores a list of nested objects.
                if not isinstance(value, dict):
                    raise MCPConfigurationError("projection cursor is invalid")
                cursors[row["connector_id"]] = value

            counts: dict[tuple[str, str], tuple[int, int]] = {}
            source_counts: dict[tuple[str, str, str], int] = {}
            rows = connection.execute("""
                SELECT i.connector_id, i.source_object_id, i.project,
                       COUNT(c.id) AS chunk_count
                FROM knowledge_items AS i
                LEFT JOIN chunks AS c
                  ON c.connector_id = i.connector_id
                 AND c.source_object_id = i.source_object_id
                WHERE i.tombstone = 0
                GROUP BY i.connector_id, i.source_object_id, i.project
                """)
            for row in rows:
                source_counts[
                    (
                        row["connector_id"],
                        row["source_object_id"],
                        row["project"],
                    )
                ] = int(row["chunk_count"])
                key = (
                    _source_root(row["connector_id"], row["source_object_id"]),
                    row["project"],
                )
                documents, chunks = counts.get(key, (0, 0))
                counts[key] = (documents + 1, chunks + int(row["chunk_count"]))
        except sqlite3.Error as error:
            raise MCPConfigurationError("projection schema is unreadable") from error
        return _Projection(schema_version, cursors, counts, source_counts)
    finally:
        connection.close()


def _status_path_permitted(path: str, prefixes: tuple[str, ...]) -> bool:
    """Return whether a relative source path is inside one active grant."""
    return any(
        prefix == WHOLE_ROOT_PATH_PREFIX
        or path == prefix
        or path.startswith(prefix + "/")
        for prefix in prefixes
    )


def _status_payload(
    runtime: _Runtime | None = None,
    *,
    roots: tuple[RootConfig, ...] | None = None,
    path_scopes: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """Return live projection/source status for the selected roots.

    Owner mode leaves ``roots`` unset and therefore checks every configured
    root. Employee mode supplies only roots covered by active search grants,
    keeping ungranted source existence and drift outside the status path.
    """
    if runtime is None:
        try:
            runtime = _runtime()
        except MCPConfigurationError as error:
            return {
                "state": "error",
                "roots": [],
                "reason": "configuration-error",
                "detail": str(error),
            }
    if roots is None:
        roots = runtime.roots

    root_entries: list[dict[str, Any]] = []
    if not runtime.database_path.is_file():
        for root in roots:
            root_entries.append(
                {
                    "name": root.name,
                    "required": root.required,
                    "path": _root_path(runtime, root),
                    "state": (
                        "rebuild-required"
                        if root.path.is_dir() or root.required
                        else "missing"
                    ),
                    "docs": 0,
                    "chunks": 0,
                }
            )
        return {
            "state": "rebuild-required",
            "reason": "absent-projection",
            "roots": root_entries,
        }

    try:
        projection = _read_projection(runtime.database_path)
    except MCPConfigurationError as error:
        return {
            "state": "rebuild-required",
            "reason": "corrupt-projection",
            "detail": str(error),
            "roots": root_entries,
        }

    if not roots:
        return {
            "state": "fresh",
            "roots": root_entries,
            "projection": {"schema_version": projection.schema_version},
        }

    try:
        connector = LocalFilesConnector(roots)
        health = connector.health()
        report = connector.discover_report()
    except Exception as error:  # noqa: BLE001 - status must stay a JSON response
        return {
            "state": "error",
            "reason": "source-status-failed",
            "detail": str(error),
            "roots": root_entries,
        }

    snapshot = projection.cursors.get("local_files")
    current = {obj.source_object_id: obj.content_hash for obj in report.objects}
    stale_roots: list[str] = []
    missing_required: list[str] = []
    for root in roots:
        stored_all = (
            {}
            if snapshot is None
            else {
                source_id: digest
                for source_id, digest in snapshot.items()
                if source_id.startswith(f"{root.name}:")
            }
        )
        prefixes = (
            None if path_scopes is None else path_scopes.get(root.name, ())
        )
        stored_root = (
            stored_all
            if prefixes is None
            else {
                source_id: digest
                for source_id, digest in stored_all.items()
                if _status_path_permitted(
                    source_id.split(":", 1)[1], prefixes
                )
            }
        )
        if prefixes is None:
            documents, chunks = projection.counts.get(
                (root.name, root.project), (0, 0)
            )
        else:
            chunk_counts = [
                projection.source_counts.get(
                    ("local_files", source_id, root.project)
                )
                for source_id in stored_root
            ]
            documents = sum(count is not None for count in chunk_counts)
            chunks = sum(count or 0 for count in chunk_counts)
        entry: dict[str, Any] = {
            "name": root.name,
            "required": root.required,
            "path": _root_path(runtime, root),
            "docs": documents,
            "chunks": chunks,
        }
        if not root.path.is_dir():
            entry["state"] = "missing"
            if root.required:
                missing_required.append(root.name)
            root_entries.append(entry)
            continue

        if snapshot is None:
            # An existing projection remains searchable even when it was
            # provisioned without a local-files cursor. Report that freshness
            # uncertainty honestly instead of blocking a governed read.
            entry["state"] = "stale"
            stale_roots.append(root.name)
        else:
            current_root = {
                source_id: digest
                for source_id, digest in current.items()
                if source_id.startswith(f"{root.name}:")
            }
            failed_root = any(
                failure.source_object_id.startswith(f"{root.name}:")
                for failure in report.failures
            )
            if stored_root != current_root or failed_root:
                entry["state"] = "stale"
                stale_roots.append(root.name)
            else:
                entry["state"] = "fresh"
        root_entries.append(entry)

    if missing_required:
        state = "error"
        reason = "missing-required-root"
    elif stale_roots:
        state = "stale"
        reason = "source-drift-or-missing-cursor"
    else:
        state = "fresh"
        reason = None

    payload: dict[str, Any] = {
        "state": state,
        "roots": root_entries,
        "projection": {
            "schema_version": projection.schema_version,
            "receipts": "enabled",
        },
    }
    if reason is not None:
        payload["reason"] = reason
    if not health.healthy:
        payload["state"] = "error"
        payload["reason"] = "missing-required-root"
    return payload


def _search_grants(call: _EmployeeCall) -> tuple[KnowledgeGrant, ...]:
    """Return active local-files search grants for one authenticated call."""
    try:
        grants = call.policy.grants_for(
            call.session.principal_id,
            project=call.runtime.project,
            now=datetime.now(timezone.utc),
            operation="search",
        )
    except AccessError as error:
        raise MCPToolError(ACCESS_DENIED_MESSAGE) from error
    return tuple(
        grant for grant in grants if grant.source_namespace == "local_files"
    )


def _active_grant_ids(call: _EmployeeCall) -> frozenset[str]:
    """Return every active grant id for one authenticated call, unfiltered.

    Used only to validate a released receipt's provenance against what
    governed retrieval actually saw: `AuthenticatedKnowledgeGateway.retrieve()`
    computes this identical unfiltered set for `RetrievalAuthContext.grant_ids`
    (`access.py` `grants_for(...)`, never filtered by `source_namespace`) and
    stamps it onto every receipt it builds. `_search_grants` above deliberately
    narrows to `local_files` for the employee-mode attestation/authorization
    surface -- that narrowing is unrelated to, and must not be conflated with,
    this provenance check. Authorization is untouched by this function: the
    coordinate-level grant check in `_employee_receipt_fields` still runs only
    against the local-files grants `_search_grants` returns, and no
    non-local_files evidence is ever released to an employee-mode caller
    (guarded unconditionally, immediately after the call site below).
    """
    try:
        grants = call.policy.grants_for(
            call.session.principal_id,
            project=call.runtime.project,
            now=datetime.now(timezone.utc),
            operation="search",
        )
    except AccessError as error:
        raise MCPToolError(ACCESS_DENIED_MESSAGE) from error
    return frozenset(grant.grant_id for grant in grants)


def _employee_attestation(
    call: _EmployeeCall, grants: tuple[KnowledgeGrant, ...]
) -> dict[str, Any]:
    """Bind one authenticated client to its active local-files grants."""
    active = tuple(sorted(grants, key=lambda grant: grant.grant_id))
    if any(grant.source_namespace != "local_files" for grant in active):
        raise MCPConfigurationError("employee mapping contains an unsupported source")
    context = {
        "tenant": call.session.tenant,
        "lane": call.session.lane,
        "scope_id": call.session.scope_id,
        "purpose": call.session.purpose,
    }
    mapping = {
        "version": EMPLOYEE_MAPPING_VERSION,
        "principal_id": call.session.principal_id,
        "client_id": call.session.client_id,
        "context": context,
        "project": call.runtime.project,
        "grants": [
            {
                "grant_id": grant.grant_id,
                "source_namespace": grant.source_namespace,
                "root": grant.root,
                "path_prefix": grant.path_prefix,
                "item_ids": sorted(grant.item_ids),
                "operations": sorted(grant.operations),
                "classification": grant.classification,
            }
            for grant in active
        ],
    }
    mapping_hash = hashlib.sha256(
        json.dumps(
            mapping,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "principal_id": call.session.principal_id,
        "client_id": call.session.client_id,
        "context": context,
        "policy_version": call.policy.version,
        "policy_hash": call.policy.policy_hash,
        "mapping_version": EMPLOYEE_MAPPING_VERSION,
        "mapping_hash": mapping_hash,
        "receipt_version": EMPLOYEE_RECEIPT_VERSION,
        "grant_ids": [grant.grant_id for grant in active],
    }


def _scope_include_pattern(pattern: str, prefix: str) -> tuple[str, ...]:
    """Intersect one configured glob with a literal grant prefix."""
    pattern_parts = tuple(pattern.split("/"))
    prefix_parts = tuple(prefix.split("/"))
    states: set[int] = {0}
    for component in prefix_parts:
        expanded = set(states)
        changed = True
        while changed:
            changed = False
            for index in tuple(expanded):
                if (
                    index < len(pattern_parts)
                    and pattern_parts[index] == "**"
                    and index + 1 not in expanded
                ):
                    expanded.add(index + 1)
                    changed = True
        states = {
            index
            if index < len(pattern_parts) and pattern_parts[index] == "**"
            else index + 1
            for index in expanded
            if index < len(pattern_parts)
            and (
                pattern_parts[index] == "**"
                or _glob_match(component, pattern_parts[index])
            )
        }
    expanded = set(states)
    changed = True
    while changed:
        changed = False
        for index in tuple(expanded):
            if (
                index < len(pattern_parts)
                and pattern_parts[index] == "**"
                and index + 1 not in expanded
            ):
                expanded.add(index + 1)
                changed = True
    return tuple(
        prefix
        if index == len(pattern_parts)
        else f"{prefix}/{'/'.join(pattern_parts[index:])}"
        for index in sorted(expanded)
    )


def _scoped_employee_roots(
    runtime: _Runtime, grants: tuple[KnowledgeGrant, ...]
) -> tuple[RootConfig, ...]:
    """Bound configured roots to the active grants' path prefixes.

    A grant prefix is translated into include patterns rooted at that prefix,
    while the configured excludes remain in force. Exact-file prefixes are
    admitted only when they already satisfy the configured include/exclude
    rules. Whole-root grants retain the original root unchanged.
    """
    grants_by_root: dict[str, list[KnowledgeGrant]] = {}
    for grant in grants:
        grants_by_root.setdefault(grant.root, []).append(grant)

    scoped: list[RootConfig] = []
    for root in runtime.roots:
        root_grants = grants_by_root.get(root.name)
        if not root_grants:
            continue
        if any(
            grant.path_prefix == WHOLE_ROOT_PATH_PREFIX for grant in root_grants
        ):
            scoped.append(root)
            continue

        include: list[str] = []
        for grant in root_grants:
            include.extend(
                scoped_pattern
                for pattern in root.include
                for scoped_pattern in _scope_include_pattern(
                    pattern, grant.path_prefix
                )
            )
        scoped.append(replace(root, include=tuple(dict.fromkeys(include))))
    return tuple(scoped)


def _employee_status(call: _EmployeeCall) -> dict[str, Any]:
    """Report status to one authenticated employee, granted roots only.

    Both the roots list and the aggregate state describe only the granted
    subset: an ungranted root's drift, absence, or failure detail must be
    unobservable and must not block the employee's own granted scope.
    """
    grants = _search_grants(call)
    granted = frozenset(grant.root for grant in grants)
    granted_roots = _scoped_employee_roots(call.runtime, grants)
    path_scopes = {
        root: tuple(dict.fromkeys(grant.path_prefix for grant in root_grants))
        for root in granted
        if (
            root_grants := tuple(grant for grant in grants if grant.root == root)
        )
    }
    payload = _status_payload(
        call.runtime, roots=granted_roots, path_scopes=path_scopes
    )
    payload["roots"] = [
        entry for entry in payload["roots"] if entry.get("name") in granted
    ]
    # Free-text diagnostics can describe ungranted sources; employees get
    # only the state machine.
    payload.pop("detail", None)
    recomputable = payload.get("state") in {"fresh", "stale"} or (
        payload.get("state") == "error"
        and payload.get("reason") == "missing-required-root"
    )
    if recomputable:
        states = {entry.get("state") for entry in payload["roots"]}
        if states & {"missing", "rebuild-required"}:
            payload["state"] = "error"
            payload["reason"] = "missing-required-root"
        elif "stale" in states:
            payload["state"] = "stale"
            payload["reason"] = "source-drift-or-missing-cursor"
        else:
            payload["state"] = "fresh"
            payload.pop("reason", None)
    payload["access"] = _employee_attestation(call, grants)
    return payload


def _staleness_detail(status: dict[str, Any]) -> dict[str, Any] | None:
    if status.get("state") != "stale":
        return None
    drifted = [
        root.get("name")
        for root in status.get("roots", [])
        if isinstance(root, dict) and root.get("state") == "stale"
    ]
    detail: dict[str, Any] = {"state": "stale"}
    if drifted:
        detail["drifted_roots"] = drifted
    return detail


def _status_preflight(
    call: _EmployeeCall | None = None,
) -> tuple[str, dict[str, Any], str | None]:
    status = _status_payload() if call is None else _employee_status(call)
    state = status.get("state")
    if state in {"fresh", "stale"}:
        return state, status, None
    if state == "rebuild-required":
        return (
            "error",
            status,
            "lee-kb projection rebuild required; remedy: run `lee-kb sync`",
        )
    return (
        "error",
        status,
        "lee-kb status failed: "
        f"{status.get('detail') or status.get('reason') or 'unknown error'}",
    )


def _stored_receipt_ids(
    repository: SQLiteRepository, receipts: tuple[RetrievalReceipt, ...]
) -> dict[RetrievalReceipt, int | None]:
    if not receipts:
        return {}
    identifiers: dict[RetrievalReceipt, int | None] = {}
    for receipt_id, stored in repository.list_receipts():
        if stored in receipts:
            identifiers[stored] = receipt_id
    return {receipt: identifiers.get(receipt) for receipt in receipts}


def _receipt_payload(
    receipt: RetrievalReceipt, receipt_id: int | None
) -> dict[str, Any]:
    locator = receipt.source_locator
    principal = receipt.principal
    payload: dict[str, Any] = {
        "id": receipt_id,
        "knowledge_item_id": str(receipt.knowledge_item_id),
        "chunk_id": str(receipt.chunk_id),
        "content_hash": receipt.content_hash,
        "source_locator": {
            "connector_id": locator.connector_id,
            "uri": locator.uri,
            "label": locator.label,
            "fragment": locator.fragment,
        },
        "retrieval_timestamp": receipt.retrieval_timestamp.isoformat(),
        "principal": {
            "id": principal.principal_id,
            "type": principal.principal_type.value,
            "groups": list(principal.groups),
        },
        "project": receipt.project,
        "query": receipt.query,
    }
    auth_context = receipt.auth_context
    if auth_context is not None:
        payload["auth_context"] = {
            "client_id": auth_context.client_id,
            "session_id": auth_context.session_id,
            "grant_ids": list(auth_context.grant_ids),
        }
    return payload


def _compat_result(
    repository: SQLiteRepository,
    evidence: Evidence,
    receipt: RetrievalReceipt,
    receipt_id: int | None,
) -> dict[str, Any]:
    citation = evidence.citation
    source_id = evidence.item_id.source_object_id
    locator = citation.source_locator
    item = repository.get_item(evidence.item_id)
    version = item.content_hash if item is not None else evidence.content_hash
    receipt_data = _receipt_payload(receipt, receipt_id)
    return {
        # These seven fields are the incumbent kb-index result contract.
        "root": _source_root(locator.connector_id, source_id),
        "path": _source_path(
            locator.connector_id, source_id, locator.label, locator.uri
        ),
        "heading": citation.heading or "",
        "commit": version,
        "text": evidence.text,
        "authority": citation.authority.value,
        "trust": citation.trust.value,
        # Additive lee-kb governance and provenance fields.
        "item_id": str(evidence.item_id),
        "chunk_id": str(evidence.chunk_id),
        "content_hash": evidence.content_hash,
        "source_content_hash": version,
        "source_uri": locator.uri,
        "source_label": locator.label,
        "source_fragment": locator.fragment,
        "title": citation.title,
        "project": evidence.project,
        "source_timestamp": evidence.source_timestamp.isoformat(),
        "sync_timestamp": evidence.sync_timestamp.isoformat(),
        "retrieval_timestamp": receipt.retrieval_timestamp.isoformat(),
        "rank": evidence.fused_rank,
        "score": evidence.fused_score,
        "receipt_id": receipt_id,
        "receipt": receipt_data,
        # Memory semantics (schema v3). None on every field for an
        # ordinary, non-memory document -- only memory_type distinguishes.
        "memory_type": item.memory_type.value if item is not None and item.memory_type is not None else None,
        "subject_principal": item.subject_principal if item is not None else None,
        "memory_confidence": (
            item.memory_confidence.value
            if item is not None and item.memory_confidence is not None
            else None
        ),
        "importance": item.importance if item is not None else None,
        "memory_formed_at": (
            item.memory_formed_at.isoformat()
            if item is not None and item.memory_formed_at is not None
            else None
        ),
        "superseded_by": item.superseded_by if item is not None else None,
    }


def _bundle_payload(
    repository: SQLiteRepository, bundle: EvidenceBundle
) -> tuple[dict[str, Any], tuple[Evidence, ...], tuple[RetrievalReceipt, ...]]:
    receipt_ids = _stored_receipt_ids(repository, bundle.receipts)
    results = [
        _compat_result(repository, evidence, receipt, receipt_ids.get(receipt))
        for evidence, receipt in zip(bundle.evidence, bundle.receipts)
    ]
    payload: dict[str, Any] = {
        "results": results,
        "receipts": [
            _receipt_payload(receipt, receipt_ids.get(receipt))
            for receipt in bundle.receipts
        ],
        "receipt_count": len(bundle.receipts),
        "denied_count": bundle.denied_count,
        "truncated": bundle.truncated,
        "freshness": {
            "is_stale": bundle.freshness.is_stale,
            "requirement_satisfied": bundle.freshness.requirement_satisfied,
            "oldest_sync_timestamp": (
                bundle.freshness.oldest_sync_timestamp.isoformat()
                if bundle.freshness.oldest_sync_timestamp is not None
                else None
            ),
            "newest_source_timestamp": (
                bundle.freshness.newest_source_timestamp.isoformat()
                if bundle.freshness.newest_source_timestamp is not None
                else None
            ),
        },
    }
    return payload, bundle.evidence, bundle.receipts


def _employee_receipt_fields(
    call: _EmployeeCall,
    attestation: dict[str, Any],
    grants: tuple[KnowledgeGrant, ...],
    active_grant_ids: frozenset[str],
    evidence: Evidence,
    receipt: RetrievalReceipt,
) -> dict[str, Any]:
    """Return receipt bindings for one released employee result."""
    locator = evidence.citation.source_locator
    item_id = str(evidence.item_id)
    source_namespace = locator.connector_id
    root = _source_root(source_namespace, evidence.item_id.source_object_id)
    path = _source_path(
        source_namespace,
        evidence.item_id.source_object_id,
        locator.label,
        locator.uri,
    )
    if (
        receipt.knowledge_item_id != evidence.item_id
        or receipt.chunk_id != evidence.chunk_id
        or receipt.project != evidence.project
        or receipt.source_locator != locator
        or receipt.principal.principal_id != call.session.principal_id
        or receipt.auth_context is None
        or receipt.auth_context.client_id != call.session.client_id
        or frozenset(receipt.auth_context.grant_ids) != active_grant_ids
    ):
        raise MCPConfigurationError("employee receipt shape is invalid")
    if source_namespace != "local_files" or not any(
        grant.project == call.runtime.project
        and grant.source_namespace == source_namespace
        and grant.root == root
        and (
            grant.path_prefix == WHOLE_ROOT_PATH_PREFIX
            or path == grant.path_prefix
            or path.startswith(grant.path_prefix + "/")
        )
        and (not grant.item_ids or item_id in grant.item_ids)
        for grant in grants
    ):
        raise MCPConfigurationError("employee receipt coordinates are not granted")
    return {
        "principal_id": attestation["principal_id"],
        "client_id": attestation["client_id"],
        "policy_version": attestation["policy_version"],
        "policy_hash": attestation["policy_hash"],
        "mapping_version": attestation["mapping_version"],
        "mapping_hash": attestation["mapping_hash"],
        "receipt_version": attestation["receipt_version"],
        "source_namespace": source_namespace,
        "root": root,
        "path": path,
        "item_id": item_id,
        "source_ref": locator.uri,
    }


def _employee_bundle(
    call: _EmployeeCall, query: str, limit: int
) -> tuple[dict[str, Any], tuple[Evidence, ...], tuple[RetrievalReceipt, ...]]:
    """Retrieve through the authenticated gateway that admitted this call."""
    repository, gateway = call.repository, call.gateway
    if repository is None or gateway is None:
        raise MCPConfigurationError("lee-kb projection is absent; run `lee-kb sync`")
    grants = _search_grants(call)
    attestation = _employee_attestation(call, grants)
    active_grant_ids = _active_grant_ids(call)
    try:
        bundle = gateway.retrieve(
            call.session, query, project=call.runtime.project, top_k=limit
        )
    except AuthorizationError as error:
        raise MCPToolError(PROJECT_NOT_GRANTED_MESSAGE) from error
    except AccessError as error:
        raise MCPToolError(ACCESS_DENIED_MESSAGE) from error
    except ValueError as error:
        raise MCPToolError(f"lee-kb search failed: {error}") from error
    if len(bundle.evidence) != len(bundle.receipts):
        raise MCPConfigurationError("employee search returned an invalid receipt shape")
    payload, evidence, receipts = _bundle_payload(repository, bundle)
    if (
        len(payload.get("results", ())) != len(evidence)
        or len(payload.get("receipts", ())) != len(receipts)
    ):
        raise MCPConfigurationError("employee search returned an invalid receipt shape")
    for index, (item, receipt) in enumerate(zip(evidence, receipts)):
        fields = _employee_receipt_fields(
            call, attestation, grants, active_grant_ids, item, receipt
        )
        top_level = payload["receipts"][index]
        nested = payload["results"][index].get("receipt")
        if not isinstance(top_level, dict) or not isinstance(nested, dict):
            raise MCPConfigurationError("employee search returned an invalid receipt shape")
        top_level.update(fields)
        nested.update(fields)
        for entry in (top_level, nested):
            auth_context = entry.get("auth_context")
            if not isinstance(auth_context, dict):
                raise MCPConfigurationError(
                    "employee search returned an invalid receipt shape"
                )
            auth_context["grant_ids"] = list(attestation["grant_ids"])
    # denied_count spans the whole projection, so to an employee it is an
    # existence oracle over other principals' content: a probe query that
    # matches only ungranted items flips it from zero. Employees see only
    # what was released; the full denial accounting stays in the owner-side
    # receipts and audit rows.
    payload.pop("denied_count", None)
    return payload, evidence, receipts


def _retrieve_bundle(
    runtime: _Runtime,
    query: str,
    limit: int,
    call: _EmployeeCall | None = None,
) -> tuple[dict[str, Any], tuple[Evidence, ...], tuple[RetrievalReceipt, ...]]:
    if not runtime.database_path.is_file():
        raise MCPConfigurationError("lee-kb projection is absent; run `lee-kb sync`")
    if call is not None:
        return _employee_bundle(call, query, limit)
    with SQLiteRepository(runtime.database_path) as repository:
        if runtime.owner_gateway is not None:
            return _owner_bundle(runtime.owner_gateway, repository, query, limit)
        bundle = governed_retrieve(
            repository,
            query,
            principal=runtime.principal,
            project=runtime.project,
            top_k=limit,
        )
        return _bundle_payload(repository, bundle)


def _owner_receipt_fields(receipt: OwnerCurrentReceipt) -> dict[str, Any]:
    """The additive owner keys, all of them inside the consumer's allowlist."""
    return {
        "audit_id": receipt.audit_id,
        "mapping_version": receipt.mapping_version,
        "mapping_hash": receipt.mapping_hash,
        "principal_id": receipt.principal.principal_id,
        "source_namespace": receipt.source_namespace,
        "root": receipt.root,
        "path": receipt.path,
        "item_id": receipt.item_id,
        "source_ref": receipt.source_locator.uri,
        "current_policy_version": receipt.policy_version,
        "current_policy_hash": receipt.policy_hash,
        "current_policy_decision": receipt.policy_decision,
        "freshness_state": receipt.freshness_state.value,
        "knowledge_state": receipt.knowledge_state.value,
    }


def _owner_bundle(
    config: OwnerGatewayConfig,
    repository: SQLiteRepository,
    query: str,
    limit: int,
) -> tuple[dict[str, Any], tuple[Evidence, ...], tuple[RetrievalReceipt, ...]]:
    """Search under the versioned server mapping; the configured owner is ignored."""
    try:
        result = _owner_gateway(config, repository).retrieve_current(
            query,
            authenticated_principal=config.mapping.authenticated_principal,
            project=config.project,
            top_k=limit,
        )
    except OwnerAccessError as error:
        raise MCPToolError(OWNER_DENIED_MESSAGE) from error
    payload, evidence, receipts = _bundle_payload(repository, result.bundle)
    owner_fields = [_owner_receipt_fields(item) for item in result.receipts]
    for entry, extra in zip(payload["receipts"], owner_fields):
        entry.update(extra)
    for compat, extra in zip(payload["results"], owner_fields):
        attached = compat.get("receipt")
        if isinstance(attached, dict):
            attached.update(extra)
    return payload, evidence, receipts


def _handle_initialize(req_id: Any, _params: Any) -> None:
    server_info: dict[str, Any] = {"name": SERVER_NAME, "version": SERVER_VERSION}
    handshake = _owner_handshake()
    if handshake is not None:
        # Additive: only owner-gateway mode publishes owner versions, so the
        # consumer can see owner-side drift instead of assuming its constants.
        server_info["owner"] = handshake
    _result(
        req_id,
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": server_info,
        },
    )


def _handle_ping(req_id: Any, _params: Any) -> None:
    _result(req_id, {})


def _handle_tools_list(req_id: Any, _params: Any) -> None:
    tools = EMPLOYEE_TOOL_DEFS if _employee_mode() else TOOL_DEFS
    _result(req_id, {"tools": tools})


def _tool_kb_search(req_id: Any, arguments: dict[str, Any]) -> None:
    if set(arguments) - {"query", "limit"}:
        _error(req_id, INVALID_PARAMS, "kb_search only accepts 'query' and 'limit'")
        return
    if "query" not in arguments or not isinstance(arguments["query"], str):
        _error(req_id, INVALID_PARAMS, "kb_search requires string argument 'query'")
        return
    query = arguments["query"]
    limit = arguments.get("limit", 5)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        _error(req_id, INVALID_PARAMS, "kb_search limit must be an integer 1–20")
        return

    try:
        with _governed_call() as call:
            _emit_search(req_id, query, limit, call)
    except MCPToolError as error:
        _tool_text(req_id, str(error), is_error=True)


def _emit_search(
    req_id: Any, query: str, limit: int, call: _EmployeeCall | None
) -> None:
    disposition, status, error = _status_preflight(call)
    if disposition == "error":
        _tool_text(req_id, error or "lee-kb search unavailable", is_error=True)
        return

    if not query.strip():
        payload: dict[str, Any] = {"results": [], "index_state": disposition}
        if disposition == "stale":
            detail = _staleness_detail(status)
            if detail is not None:
                payload["staleness"] = detail
        _tool_text(req_id, json.dumps(payload, indent=2))
        return

    try:
        payload, _evidence, _receipts = _retrieve_bundle(
            runtime=_runtime() if call is None else call.runtime,
            query=query,
            limit=limit,
            call=call,
        )
    except (
        MCPConfigurationError,
        MissingPrincipalError,
        RetrievalProviderError,
    ) as error:
        _tool_text(req_id, f"lee-kb search failed: {error}", is_error=True)
        return
    payload["index_state"] = disposition
    if disposition == "stale":
        detail = _staleness_detail(status)
        if detail is not None:
            payload["staleness"] = detail
    _tool_text(req_id, json.dumps(payload, indent=2))


def _tool_kb_status(req_id: Any, arguments: dict[str, Any]) -> None:
    if arguments:
        _error(req_id, INVALID_PARAMS, "kb_status accepts no arguments")
        return
    try:
        with _governed_call() as call:
            payload = _status_payload() if call is None else _employee_status(call)
    except MCPToolError as error:
        _tool_text(req_id, str(error), is_error=True)
        return
    _tool_text(req_id, json.dumps(payload, indent=2))


def _format_provenance_line(result: dict[str, Any]) -> str:
    trust = result.get("trust", "")
    tag = " !model_produced" if trust == "model_produced" else ""
    return (
        f"[{result.get('root', '')}:{result.get('path', '')}"
        f"#{result.get('heading', '')} @{result.get('commit', '')}{tag}]"
    )


def _tool_kb_compile_preview(req_id: Any, arguments: dict[str, Any]) -> None:
    if "query" not in arguments or not isinstance(arguments["query"], str):
        _error(
            req_id,
            INVALID_PARAMS,
            "kb_compile_preview requires string argument 'query'",
        )
        return
    if set(arguments) - {"query"}:
        _error(req_id, INVALID_PARAMS, "kb_compile_preview only accepts 'query'")
        return

    try:
        with _governed_call() as call:
            _emit_compile_preview(req_id, arguments["query"], call)
    except MCPToolError as error:
        _tool_text(req_id, str(error), is_error=True)


def _emit_compile_preview(req_id: Any, query: str, call: _EmployeeCall | None) -> None:
    disposition, status, error = _status_preflight(call)
    if disposition == "error":
        _tool_text(req_id, error or "lee-kb preview unavailable", is_error=True)
        return

    parts: list[str] = ["# KB compile preview", "", f"index_state: {disposition}"]
    if disposition == "stale":
        detail = _staleness_detail(status)
        if detail and detail.get("drifted_roots"):
            parts.append(
                "staleness: " + ", ".join(str(x) for x in detail["drifted_roots"])
            )
    parts.append("")

    if query.strip():
        try:
            payload, _evidence, _receipts = _retrieve_bundle(
                runtime=_runtime() if call is None else call.runtime,
                query=query,
                limit=20,
                call=call,
            )
        except (
            MCPConfigurationError,
            MissingPrincipalError,
            RetrievalProviderError,
        ) as error:
            _tool_text(
                req_id,
                f"kb compile preview search failed: {error}",
                is_error=True,
            )
            return
        results = payload["results"]
    else:
        results = []

    if not results:
        parts.append("(no hits)")
    else:
        blocks: list[str] = []
        for result in results:
            text = str(result.get("text", "")).strip()
            receipt_id = result.get("receipt_id")
            receipt_line = (
                f"receipt: #{receipt_id}"
                if receipt_id is not None
                else "receipt: unavailable"
            )
            blocks.append(
                f"{_format_provenance_line(result)}\n\n{text}\n\n{receipt_line}"
            )
        parts.append("\n\n---\n\n".join(blocks))

    _tool_text(req_id, "\n".join(parts).rstrip() + "\n")


def _history_receipt_payload(receipt: HistoricalReceipt) -> dict[str, Any]:
    """The released exact-history receipt, as the consumer normalizes it."""
    locator = receipt.locator
    return {
        "receipt_id": receipt.audit_id,
        "audit_id": receipt.audit_id,
        "mapping_version": receipt.mapping_version,
        "mapping_hash": receipt.mapping_hash,
        "principal_id": receipt.mapped_principal_id,
        "project": receipt.project,
        "repository": locator.repository,
        "commit": locator.commit,
        "path": receipt.path,
        "source_ref": f"git:{locator.repository}@{locator.commit}:{locator.path}",
        "source_namespace": receipt.source_namespace,
        "root": receipt.root,
        "item_id": receipt.item_id,
        "classification": receipt.classification,
        "current_policy_version": receipt.current_policy_version,
        "current_policy_hash": receipt.current_policy_hash,
        "current_policy_decision": receipt.current_policy_decision,
        "historical_policy_version": receipt.historical_policy_version,
        "historical_policy_hash": receipt.historical_policy_hash,
        "historical_policy_decision": receipt.historical_policy_decision,
        "historical_manifest_hash": receipt.historical_manifest_hash,
        "blob_hash": receipt.blob_hash,
        "blob_timestamp": (
            receipt.blob_timestamp.isoformat()
            if receipt.blob_timestamp is not None
            else None
        ),
        "evaluation_time": receipt.evaluation_time.isoformat(),
        "freshness_state": receipt.freshness_state.value,
        "knowledge_state": receipt.knowledge_state.value,
    }


def _history_payload(result: HistoricalLookupResult) -> dict[str, Any]:
    """Release the body only on KNOWN; every other state is the same shape."""
    if (
        result.knowledge_state is not OwnerKnowledgeState.KNOWN
        or result.receipt is None
    ):
        return dict(UNKNOWN_HISTORY)
    receipt = _history_receipt_payload(result.receipt)
    # The receipts array carries only names the consumer's normalizer allows;
    # the receipt object additionally names the exact locator it is bound to.
    allowlisted = {
        key: value
        for key, value in receipt.items()
        if key not in {"repository", "commit", "classification"}
    }
    return {
        "knowledge_state": result.knowledge_state.value,
        "freshness_state": result.freshness_state.value,
        "body": result.body,
        "receipt": receipt,
        "receipts": [allowlisted],
    }


def _tool_kb_history_get(req_id: Any, arguments: dict[str, Any]) -> None:
    required = {"repository", "commit", "path", "classification"}
    if set(arguments) != required or any(
        not isinstance(arguments.get(name), str) or not arguments[name].strip()
        for name in required
    ):
        _error(
            req_id,
            INVALID_PARAMS,
            "kb_history_get requires exact repository, commit, path, and "
            "classification",
        )
        return
    try:
        locator = HistoricalLocator(
            arguments["repository"], arguments["commit"], arguments["path"]
        )
    except (TypeError, ValueError):
        _tool_text(req_id, json.dumps(dict(UNKNOWN_HISTORY), indent=2))
        return

    # Outside owner-gateway mode this process has no source-owner release
    # authority and no exact-object seam, so it answers the required
    # non-enumerating UNKNOWN instead of pretending current files are history.
    config = None
    if not _employee_mode():
        try:
            config = _runtime().owner_gateway
        except (MCPConfigurationError, MCPToolError):
            config = None
    if config is None:
        _tool_text(req_id, json.dumps(dict(UNKNOWN_HISTORY), indent=2))
        return

    # The wire never carries the governed source scope: it is resolved from the
    # source-owner release declaration for this exact locator, or not at all.
    scope = config.scope_for(locator)
    if scope is None:
        _tool_text(req_id, json.dumps(dict(UNKNOWN_HISTORY), indent=2))
        return
    result = _owner_gateway(config, None).retrieve_history(
        authenticated_principal=config.mapping.authenticated_principal,
        locator=locator,
        classification=arguments["classification"],
        source_namespace=scope.source_namespace,
        root=scope.root,
        item_id=scope.item_id,
        project=config.project,
    )
    _tool_text(req_id, json.dumps(_history_payload(result), indent=2))


def _handle_tools_call(req_id: Any, params: Any) -> None:
    if not isinstance(params, dict):
        _error(req_id, INVALID_PARAMS, "tools/call params must be an object")
        return
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not name:
        _error(req_id, INVALID_PARAMS, "tools/call requires string 'name'")
        return
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        _error(req_id, INVALID_PARAMS, "tools/call 'arguments' must be an object")
        return

    if name == "kb_search":
        _tool_kb_search(req_id, arguments)
    elif name == "kb_status":
        _tool_kb_status(req_id, arguments)
    elif name == "kb_compile_preview":
        _tool_kb_compile_preview(req_id, arguments)
    elif name == "kb_history_get":
        _tool_kb_history_get(req_id, arguments)
    else:
        _error(req_id, INVALID_PARAMS, f"unknown tool: {name}")


HANDLERS = {
    "initialize": _handle_initialize,
    "ping": _handle_ping,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


def _dispatch(message: dict[str, Any]) -> None:
    if message.get("jsonrpc") != "2.0":
        if "id" in message:
            _error(message.get("id"), INVALID_REQUEST, "jsonrpc must be '2.0'")
        return

    method = message.get("method")
    if not isinstance(method, str) or not method:
        if "id" in message:
            _error(message.get("id"), INVALID_REQUEST, "method must be a string")
        return

    if "id" not in message:
        return
    req_id = message["id"]
    if method == "notifications/initialized":
        return

    handler = HANDLERS.get(method)
    if handler is None:
        _error(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        return
    handler(req_id, message.get("params"))


def main() -> int:
    """Run the MCP JSON-RPC stdio server."""
    while True:
        line_bytes = sys.stdin.buffer.readline()
        if not line_bytes:
            break
        raw = line_bytes.decode("utf-8", errors="replace").strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            _error(None, PARSE_ERROR, "Parse error")
            continue
        if not isinstance(message, dict):
            _error(None, INVALID_REQUEST, "Request must be a JSON object")
            continue
        try:
            _dispatch(message)
        except Exception as error:  # noqa: BLE001 - keep a client session alive
            req_id = message.get("id")
            if req_id is not None:
                _error(req_id, INTERNAL_ERROR, f"internal error: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
