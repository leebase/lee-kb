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

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import __version__
from .connectors.base import ConnectorConfigError
from .connectors.local_files import LocalFilesConnector, RootConfig, load_config
from .contracts import (
    DEFAULT_PROJECT,
    SCHEMA_VERSION,
    Evidence,
    Principal,
    RetrievalReceipt,
)
from .governance import MissingPrincipalError, RetrievalProviderError
from .governance import retrieve as governed_retrieve
from .main import _load_raw_config, _resolve_database_path, resolve_config_path
from .repository import SQLiteRepository

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "lee-kb"
SERVER_VERSION = __version__

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

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
]


class MCPConfigurationError(RuntimeError):
    """Raised when the server cannot resolve a usable lee-kb deployment."""


@dataclass(frozen=True, slots=True)
class _Runtime:
    config_path: Path
    raw_config: dict[str, Any]
    database_path: Path
    principal: Principal
    project: str
    roots: tuple[RootConfig, ...]


@dataclass(frozen=True, slots=True)
class _Projection:
    """Read-only status facts from the SQLite projection."""

    schema_version: int
    cursors: dict[str, dict[str, str]]
    counts: dict[tuple[str, str], tuple[int, int]]


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
    )


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

            cursors: dict[str, dict[str, str]] = {}
            for row in connection.execute(
                "SELECT connector_id, cursor FROM connector_sync_state"
            ):
                try:
                    value = json.loads(row["cursor"])
                except (TypeError, json.JSONDecodeError) as error:
                    raise MCPConfigurationError(
                        "projection cursor is invalid"
                    ) from error
                if not isinstance(value, dict) or not all(
                    isinstance(key, str) and isinstance(item, str)
                    for key, item in value.items()
                ):
                    raise MCPConfigurationError("projection cursor is invalid")
                cursors[row["connector_id"]] = value

            counts: dict[tuple[str, str], tuple[int, int]] = {}
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
                key = (
                    _source_root(row["connector_id"], row["source_object_id"]),
                    row["project"],
                )
                documents, chunks = counts.get(key, (0, 0))
                counts[key] = (documents + 1, chunks + int(row["chunk_count"]))
        except sqlite3.Error as error:
            raise MCPConfigurationError("projection schema is unreadable") from error
        return _Projection(schema_version, cursors, counts)
    finally:
        connection.close()


def _status_payload() -> dict[str, Any]:
    try:
        runtime = _runtime()
    except MCPConfigurationError as error:
        return {
            "state": "error",
            "roots": [],
            "reason": "configuration-error",
            "detail": str(error),
        }

    root_entries: list[dict[str, Any]] = []
    if not runtime.database_path.is_file():
        for root in runtime.roots:
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

    if not runtime.roots:
        return {
            "state": "fresh",
            "roots": root_entries,
            "projection": {"schema_version": projection.schema_version},
        }

    try:
        connector = LocalFilesConnector(runtime.roots)
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
    for root in runtime.roots:
        documents, chunks = projection.counts.get((root.name, root.project), (0, 0))
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
            stored_root = {
                source_id: digest
                for source_id, digest in snapshot.items()
                if source_id.startswith(f"{root.name}:")
            }
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


def _status_preflight() -> tuple[str, dict[str, Any], str | None]:
    status = _status_payload()
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
    return {
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
    }


def _retrieve_bundle(
    runtime: _Runtime, query: str, limit: int
) -> tuple[dict[str, Any], tuple[Evidence, ...], tuple[RetrievalReceipt, ...]]:
    if not runtime.database_path.is_file():
        raise MCPConfigurationError("lee-kb projection is absent; run `lee-kb sync`")
    with SQLiteRepository(runtime.database_path) as repository:
        bundle = governed_retrieve(
            repository,
            query,
            principal=runtime.principal,
            project=runtime.project,
            top_k=limit,
        )
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


def _handle_initialize(req_id: Any, _params: Any) -> None:
    _result(
        req_id,
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    )


def _handle_ping(req_id: Any, _params: Any) -> None:
    _result(req_id, {})


def _handle_tools_list(req_id: Any, _params: Any) -> None:
    _result(req_id, {"tools": TOOL_DEFS})


def _tool_kb_search(req_id: Any, arguments: dict[str, Any]) -> None:
    if "query" not in arguments or not isinstance(arguments["query"], str):
        _error(req_id, INVALID_PARAMS, "kb_search requires string argument 'query'")
        return
    query = arguments["query"]
    limit = arguments.get("limit", 5)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        _error(req_id, INVALID_PARAMS, "kb_search limit must be an integer 1–20")
        return

    disposition, status, error = _status_preflight()
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
            runtime=_runtime(), query=query, limit=limit
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
    _tool_text(req_id, json.dumps(_status_payload(), indent=2))


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
    query = arguments["query"]

    disposition, status, error = _status_preflight()
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
                runtime=_runtime(), query=query, limit=20
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
