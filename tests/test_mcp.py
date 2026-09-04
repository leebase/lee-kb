"""Contract and user-path tests for the incumbent-compatible MCP surface."""

from __future__ import annotations

import hashlib
import os
import json
import subprocess
import sys
import tomllib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from lee_kb.access import (
    AccessRegistry,
    ClientCredential,
    EmployeeIdentity,
    KnowledgeGrant,
    KnowledgePolicy,
)
from lee_kb.access_store import clients_path_for, policy_path_for, save_policy
from lee_kb.contracts import (
    OWNER_CONTRACT_VERSION,
    OWNER_CORPUS_VERSION,
    OWNER_HISTORICAL_VERSION,
    OWNER_MAPPING_VERSION,
    OWNER_PERMISSION_VERSION,
    OWNER_RECEIPT_VERSION,
    OWNER_SCHEMA_VERSION,
    WHOLE_ROOT_PATH_PREFIX,
    AccessAuditOutcome,
    Principal,
    PrincipalType,
    compute_content_hash,
)
import lee_kb.mcp as mcp
from lee_kb.mcp import (
    ACCESS_DENIED_MESSAGE,
    CLIENT_ID_ENV,
    CLIENT_SECRET_ENV,
    CLIENT_SECRET_FILE_ENV,
    EMPLOYEE_MAPPING_VERSION,
    EMPLOYEE_RECEIPT_VERSION,
    PROJECT_NOT_GRANTED_MESSAGE,
    PROTOCOL_VERSION,
    TOOL_DEFS,
    _read_projection,
)
from lee_kb.owner import OWNER_API_VERSION, load_owner_gateway
from lee_kb.repository import SQLiteRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# Exactly the receipt names leeos/src/leeos/core/adapters.py normalizes.
CONSUMER_RECEIPT_KEYS = frozenset(
    {
        "id",
        "receipt_id",
        "audit_id",
        "mapping_version",
        "mapping_hash",
        "principal_id",
        "project",
        "source_ref",
        "source_namespace",
        "root",
        "path",
        "item_id",
        "current_policy_version",
        "current_policy_hash",
        "current_policy_decision",
        "historical_policy_version",
        "historical_policy_hash",
        "historical_policy_decision",
        "historical_manifest_hash",
        "blob_hash",
        "blob_timestamp",
        "evaluation_time",
        "freshness_state",
        "knowledge_state",
    }
)
INCUMBENT_INPUT_SCHEMAS = {
    "kb_search": {
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
    "kb_status": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "kb_compile_preview": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Briefing topic / search query",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def _environment(
    config_path: Path, extra: dict[str, str] | None = None
) -> dict[str, str]:
    environment = os.environ.copy()
    # Employee mode is opt-in per launch; never inherit it from the test shell.
    for name in (CLIENT_ID_ENV, CLIENT_SECRET_ENV, CLIENT_SECRET_FILE_ENV):
        environment.pop(name, None)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    environment["LEE_KB_CONFIG"] = str(config_path)
    environment.update(extra or {})
    return environment


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    corpus = tmp_path / "notes"
    corpus.mkdir()
    (corpus / "guide.md").write_text(
        "# Parity\n\nThe successor exposes governed retrieval with receipts.\n",
        encoding="utf-8",
    )
    config = tmp_path / "config.toml"
    config.write_text(
        f"""schema = 1
owner = "lee@example.com"

[roots.notes]
path = "{corpus.as_posix()}"
owner = "lee@example.com"
include = ["*.md"]
authority = "derived"
trust = "curated"
visibility = "private"
project = "default"
""",
        encoding="utf-8",
    )
    sync = subprocess.run(
        [sys.executable, "-m", "lee_kb.main", "sync"],
        cwd=PROJECT_ROOT,
        env=_environment(config),
        capture_output=True,
        text=True,
        check=False,
    )
    assert sync.returncode == 0, sync.stdout + sync.stderr
    return {
        "config": config,
        "database": tmp_path / "knowledge.sqlite",
    }


class MCPClient:
    """Small newline JSON-RPC client, matching the incumbent test style."""

    def __init__(
        self, config_path: Path, extra_env: dict[str, str] | None = None
    ) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "lee_kb.mcp"],
            cwd=PROJECT_ROOT,
            env=_environment(config_path, extra_env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._next_id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        assert self.process.stdin
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        assert self.process.stdout
        line = self.process.stdout.readline()
        assert line, self.process.stderr.read() if self.process.stderr else ""
        reply = json.loads(line)
        assert reply.get("id") == self._next_id, reply
        return reply

    def initialize(self) -> dict:
        reply = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test_lee_kb_mcp", "version": "0"},
            },
        )
        assert self.process.stdin
        self.process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        self.process.stdin.flush()
        return reply

    def close(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=10)
        except Exception:
            self.process.kill()


@pytest.fixture
def client(workspace: dict[str, Path]):
    instance = MCPClient(workspace["config"])
    try:
        yield instance
    finally:
        instance.close()


def _tool_payload(reply: dict) -> dict:
    assert "result" in reply, reply
    result = reply["result"]
    assert not result.get("isError"), result
    assert result["content"][0]["type"] == "text"
    return json.loads(result["content"][0]["text"])


def test_tool_surface_matches_kb_index_contract() -> None:
    """The incumbent tools and additive exact-history tool stay explicit."""
    names = [tool["name"] for tool in TOOL_DEFS]
    assert names[:3] == ["kb_search", "kb_status", "kb_compile_preview"]
    assert "kb_history_get" in names
    assert {
        tool["name"]: tool["inputSchema"] for tool in TOOL_DEFS[:3]
    } == INCUMBENT_INPUT_SCHEMAS


def test_projection_accepts_nested_graph_cursors(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite"
    synced_at = datetime(2026, 8, 9, 17, 52, tzinfo=timezone.utc)
    outlook_cursor = {
        "version": 1,
        "connector_id": "outlook_mail:personal:inbox",
        "folder_id": "folder-inbox",
        "project": "default",
        "mailbox_owner": "lee@example.com",
        "account_id": "personal",
        "tenant": "tenant-id",
        "credential_binding": "binding",
        "verified_subject": "subject-id",
        "verified_tenant": "tenant-id",
        "delta_link": (
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta"
        ),
        "objects": {
            "message:immutable-1": {
                "content_hash": "content-hash",
                "source_timestamp": "2026-08-09T17:00:00+00:00",
                "uri": "https://graph.microsoft.com/v1.0/me/messages/immutable-1",
                "label": "Subject",
                "fragment": None,
            }
        },
    }
    calendar_cursor = {
        "schema_version": 1,
        "objects": [
            {
                "source_object_id": "event:event-1",
                "content_hash": "calendar-hash",
                "source_timestamp": "2026-08-09T17:00:00+00:00",
                "uri": "https://graph.microsoft.com/v1.0/me/events/event-1",
                "label": "Planning",
            }
        ],
    }

    with SQLiteRepository(database) as repository:
        repository.advance_cursor(
            "local_files",
            json.dumps({"notes:guide.md": "local-hash"}),
            updated_at=synced_at,
        )
        repository.advance_cursor(
            "outlook_mail:personal:inbox",
            json.dumps(outlook_cursor),
            updated_at=synced_at,
        )
        repository.advance_cursor(
            "calendar:calendar-id",
            json.dumps(calendar_cursor),
            updated_at=synced_at,
        )

    projection = _read_projection(database)

    assert projection.cursors["local_files"] == {"notes:guide.md": "local-hash"}
    assert (
        projection.cursors["outlook_mail:personal:inbox"]["objects"][
            "message:immutable-1"
        ]["fragment"]
        is None
    )
    assert (
        projection.cursors["calendar:calendar-id"]["objects"][0]["source_object_id"]
        == "event:event-1"
    )


def test_initialize_and_tools_list_are_mcp_compatible(client: MCPClient) -> None:
    initialized = client.initialize()
    result = initialized["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "lee-kb"
    assert result["serverInfo"]["version"]
    # The owner handshake is additive to owner-gateway mode only.
    assert "owner" not in result["serverInfo"]
    listed = client.request("tools/list")
    assert [tool["name"] for tool in listed["result"]["tools"]][:3] == [
        "kb_search",
        "kb_status",
        "kb_compile_preview",
    ]
    assert "kb_history_get" in [tool["name"] for tool in listed["result"]["tools"]]


def test_kb_status_preserves_status_shape(client: MCPClient) -> None:
    client.initialize()
    payload = _tool_payload(
        client.request("tools/call", {"name": "kb_status", "arguments": {}})
    )

    assert payload["state"] == "fresh"
    assert isinstance(payload["roots"], list)
    root = next(entry for entry in payload["roots"] if entry["name"] == "notes")
    assert {"name", "required", "path", "state", "docs", "chunks"} <= set(root)
    assert root["state"] == "fresh"
    assert root["docs"] == 1
    assert root["chunks"] >= 1


def test_kb_search_preserves_result_shape_and_attaches_receipts(
    client: MCPClient, workspace: dict[str, Path]
) -> None:
    client.initialize()
    payload = _tool_payload(
        client.request(
            "tools/call",
            {"name": "kb_search", "arguments": {"query": "successor"}},
        )
    )

    assert payload["index_state"] == "fresh"
    assert payload["results"]
    result = payload["results"][0]
    assert {
        "root",
        "path",
        "heading",
        "commit",
        "text",
        "authority",
        "trust",
    } <= set(result)
    assert result["root"] == "notes"
    assert result["path"] == "guide.md"
    assert result["heading"] == "Parity"
    assert "The successor" in result["text"]
    assert result["commit"]

    assert (
        payload["receipt_count"] == len(payload["receipts"]) == len(payload["results"])
    )
    receipt = result["receipt"]
    assert receipt["id"] == result["receipt_id"]
    assert receipt["query"] == "successor"
    assert receipt["content_hash"] == result["content_hash"]
    assert receipt["source_locator"]["uri"].startswith("file:")

    with SQLiteRepository(workspace["database"]) as repository:
        stored = repository.list_receipts()
        assert len(stored) == 1
        assert stored[0][0] == receipt["id"]
        assert stored[0][1].query == "successor"


def test_compile_preview_keeps_markdown_shape_and_receipt_reference(
    client: MCPClient,
) -> None:
    client.initialize()
    reply = client.request(
        "tools/call",
        {
            "name": "kb_compile_preview",
            "arguments": {"query": "receipts"},
        },
    )
    result = reply["result"]
    assert not result.get("isError"), result
    text = result["content"][0]["text"]
    assert text.startswith("# KB compile preview\n\nindex_state: fresh")
    assert "[notes:guide.md#Parity @" in text
    assert "receipt: #" in text


def test_invalid_tool_arguments_use_incumbent_json_rpc_error(client: MCPClient) -> None:
    client.initialize()
    reply = client.request(
        "tools/call",
        {"name": "kb_search", "arguments": {"query": "x", "limit": 21}},
    )
    assert reply["error"]["code"] == -32602

    reply = client.request(
        "tools/call",
        {"name": "kb_status", "arguments": {"unexpected": True}},
    )
    assert reply["error"]["code"] == -32602


GOVERNED_PROJECT = "default"
EMPLOYEE_PRINCIPAL = "analyst@lee-kb.example"
GRANTED_ROOT = "notes"
UNGRANTED_ROOT = "private"
# A registration issued under this clock is already expired in real time, which
# exercises credential expiry across the process boundary without sleeping.
EXPIRED_CLOCK = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _employee() -> EmployeeIdentity:
    return EmployeeIdentity(
        employee_id="analyst",
        principal=Principal(
            EMPLOYEE_PRINCIPAL, PrincipalType.AI_EMPLOYEE, display_name="Analyst"
        ),
        tenant="tenant-one",
        lane="knowledge",
        scope_id="scope-notes",
        purpose="governed-retrieval",
    )


def _notes_grant(
    *,
    revoked_at: datetime | None = None,
    path_prefix: str = WHOLE_ROOT_PATH_PREFIX,
) -> KnowledgeGrant:
    """Grant the selected path scope inside the granted root."""
    employee = _employee()
    return KnowledgeGrant(
        grant_id="grant-notes",
        principal_id=employee.principal_id,
        tenant=employee.tenant,
        lane=employee.lane,
        scope_id=employee.scope_id,
        purpose=employee.purpose,
        project=GOVERNED_PROJECT,
        source_namespace="local_files",
        root=GRANTED_ROOT,
        path_prefix=path_prefix,
        operations=frozenset({"search", "read", "cite"}),
        revoked_at=revoked_at,
    )


@pytest.fixture
def governed(tmp_path: Path) -> dict[str, Path]:
    """Two-root corpus whose items are readable by any configured principal.

    Both roots are ``public`` so the item ACL never decides the outcome: the
    knowledge grant is the only boundary these tests can be passing against.
    """
    documents = {
        GRANTED_ROOT: (
            "guide.md",
            "# Parity\n\nThe successor exposes governed retrieval with receipts.\n",
        ),
        UNGRANTED_ROOT: (
            "payroll.md",
            "# Payroll\n\nThe successor payroll ledger stays sealed.\n",
        ),
    }
    sections = []
    for name, (filename, text) in documents.items():
        root = tmp_path / name
        root.mkdir()
        (root / filename).write_text(text, encoding="utf-8")
        sections.append(f"""
[roots.{name}]
path = "{root.as_posix()}"
owner = "lee@example.com"
include = ["*.md"]
authority = "derived"
trust = "curated"
visibility = "public"
project = "{GOVERNED_PROJECT}"
""")
    config = tmp_path / "config.toml"
    config.write_text(
        'schema = 1\nowner = "lee@example.com"\n' + "".join(sections),
        encoding="utf-8",
    )
    sync = subprocess.run(
        [sys.executable, "-m", "lee_kb.main", "sync"],
        cwd=PROJECT_ROOT,
        env=_environment(config),
        capture_output=True,
        text=True,
        check=False,
    )
    assert sync.returncode == 0, sync.stdout + sync.stderr
    return {
        "config": config,
        "database": tmp_path / "knowledge.sqlite",
        "policy": policy_path_for(config),
        "clients": clients_path_for(config),
    }


@pytest.fixture
def launch(governed: dict[str, Path]) -> Any:
    """Start MCP servers against the governed workspace and close them all."""
    started: list[MCPClient] = []

    def start(extra_env: dict[str, str]) -> MCPClient:
        instance = MCPClient(governed["config"], extra_env)
        started.append(instance)
        instance.initialize()
        return instance

    yield start
    for instance in started:
        instance.close()


def _write_policy(
    governed: dict[str, Path], *grants: KnowledgeGrant
) -> KnowledgePolicy:
    policy = KnowledgePolicy(employees=(_employee(),), grants=grants)
    save_policy(governed["policy"], policy)
    return policy


def _register(
    governed: dict[str, Path],
    policy: KnowledgePolicy,
    *,
    client_id: str = "analyst:client:mcp",
    clock: Callable[[], datetime] | None = None,
    expires_at: datetime | None = None,
) -> ClientCredential:
    registry = AccessRegistry(policy, state_path=governed["clients"], clock=clock)
    return registry.register_client(
        EMPLOYEE_PRINCIPAL, client_id=client_id, expires_at=expires_at
    )


def _employee_env(credential: ClientCredential) -> dict[str, str]:
    return {
        CLIENT_ID_ENV: credential.client_id,
        CLIENT_SECRET_ENV: credential.client_secret,
    }


def _recompute_employee_mapping_hash(
    access: dict[str, Any],
    grants: tuple[KnowledgeGrant, ...],
) -> str:
    body = {
        "version": access["mapping_version"],
        "principal_id": access["principal_id"],
        "client_id": access["client_id"],
        "context": access["context"],
        "project": GOVERNED_PROJECT,
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
            for grant in sorted(grants, key=lambda item: item.grant_id)
        ],
    }
    return hashlib.sha256(
        json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()




def _error_text(reply: dict) -> str:
    assert "result" in reply, reply
    result = reply["result"]
    assert result.get("isError") is True, result
    return result["content"][0]["text"]


def _search(client: MCPClient, **arguments: Any) -> dict:
    return client.request(
        "tools/call",
        {"name": "kb_search", "arguments": {"query": "successor", **arguments}},
    )


def _status(client: MCPClient) -> dict:
    return client.request("tools/call", {"name": "kb_status", "arguments": {}})


def _access_events(governed: dict[str, Path]) -> list[Any]:
    with SQLiteRepository(governed["database"]) as repository:
        return [event for _identifier, event in repository.list_access_events()]


def test_employee_tool_surface_excludes_owner_history_and_binds_limit(
    governed: dict[str, Path], launch: Any
) -> None:
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)
    client = launch(_employee_env(credential))

    tools = client.request("tools/list")["result"]["tools"]

    assert [tool["name"] for tool in tools] == [
        "kb_search",
        "kb_status",
        "kb_compile_preview",
    ]
    search = next(tool for tool in tools if tool["name"] == "kb_search")
    assert set(search["inputSchema"]["required"]) == {"query", "limit"}


def test_employee_search_returns_only_granted_root_evidence(
    governed: dict[str, Path], launch: Any
) -> None:
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)

    payload = _tool_payload(_search(launch(_employee_env(credential))))

    assert payload["results"], payload
    assert {result["root"] for result in payload["results"]} == {GRANTED_ROOT}
    assert payload["receipt_count"] == len(payload["results"])
    for receipt in payload["receipts"]:
        context = receipt["auth_context"]
        assert context["client_id"] == credential.client_id
        assert context["session_id"]
        assert context["grant_ids"] == ["grant-notes"]
        assert receipt["principal"]["id"] == EMPLOYEE_PRINCIPAL

    events = _access_events(governed)
    assert ("authentication", AccessAuditOutcome.ALLOWED) in {
        (event.event_type, event.outcome) for event in events
    }
    retrieval = next(event for event in events if event.event_type == "retrieval")
    assert retrieval.outcome is AccessAuditOutcome.ALLOWED
    assert retrieval.client_id == credential.client_id
    assert retrieval.principal is not None
    assert retrieval.principal.principal_id == EMPLOYEE_PRINCIPAL
    assert retrieval.grant_ids == ("grant-notes",)
    assert retrieval.project == GOVERNED_PROJECT


def _calendar_grant() -> KnowledgeGrant:
    """A non-local_files grant -- reproduces the real D3/D9 Outlook-calendar shape.

    ``KnowledgeGrant.__post_init__`` never validates ``source_namespace``/
    ``root`` against a real connector, so this grant is constructible and
    active without any calendar connector or content existing.
    """
    employee = _employee()
    return KnowledgeGrant(
        grant_id="grant-calendar",
        principal_id=employee.principal_id,
        tenant=employee.tenant,
        lane=employee.lane,
        scope_id=employee.scope_id,
        purpose=employee.purpose,
        project=GOVERNED_PROJECT,
        source_namespace="calendar",
        root="calendar-test",
        path_prefix=WHOLE_ROOT_PATH_PREFIX,
        operations=frozenset({"search", "read", "cite"}),
    )


def test_employee_search_survives_a_granted_non_local_files_source(
    governed: dict[str, Path], launch: Any
) -> None:
    """D10 regression: a non-local_files grant must not break local_files search.

    Before the fix, holding ANY active grant whose source_namespace was not
    "local_files" made ``_employee_receipt_fields``'s shape check compare a
    receipt's full grant-id list (``access.py``, unfiltered) against the
    employee-mode attestation's local_files-only-filtered list -- the two
    permanently diverge the moment a second grant exists, and every
    kb_search/kb_compile_preview call raised "employee receipt shape is
    invalid", not just ones touching the new source. Reproduced live
    2026-08-14 granting ``employee:chief-of-staff`` Outlook/calendar sources
    (chief-of-staff/decisions.md D10) -- this is that exact failure, isolated.
    """
    policy = _write_policy(governed, _notes_grant(), _calendar_grant())
    credential = _register(governed, policy)
    client = launch(_employee_env(credential))

    payload = _tool_payload(_search(client))

    assert payload["results"], payload
    assert {result["root"] for result in payload["results"]} == {GRANTED_ROOT}
    for receipt in payload["receipts"]:
        # Client-visible attestation stays local_files-scoped even though the
        # employee also holds the calendar grant -- the fix does not widen
        # what's echoed to the client, only the internal shape comparison.
        assert receipt["auth_context"]["grant_ids"] == ["grant-notes"]

    status = _tool_payload(_status(client))
    assert status["access"]["grant_ids"] == ["grant-notes"]


def test_employee_status_and_receipts_bind_one_attestation(
    governed: dict[str, Path], launch: Any
) -> None:
    grants = (_notes_grant(),)
    policy = _write_policy(governed, *grants)
    credential = _register(governed, policy)
    client = launch(_employee_env(credential))

    status = _tool_payload(_status(client))
    access = status["access"]
    assert set(access) == {
        "principal_id",
        "client_id",
        "context",
        "policy_version",
        "policy_hash",
        "mapping_version",
        "mapping_hash",
        "receipt_version",
        "grant_ids",
    }
    assert access["principal_id"] == EMPLOYEE_PRINCIPAL
    assert access["client_id"] == credential.client_id
    assert access["context"] == {
        "tenant": "tenant-one",
        "lane": "knowledge",
        "scope_id": "scope-notes",
        "purpose": "governed-retrieval",
    }
    assert access["policy_version"] == policy.version
    assert access["policy_hash"] == policy.policy_hash
    assert access["mapping_version"] == EMPLOYEE_MAPPING_VERSION
    assert access["receipt_version"] == EMPLOYEE_RECEIPT_VERSION
    assert access["grant_ids"] == ["grant-notes"]
    assert access["mapping_hash"] == _recompute_employee_mapping_hash(
        access, grants
    )
    assert access["policy_hash"] != access["mapping_hash"]

    payload = _tool_payload(_search(client))
    for result, top_level in zip(payload["results"], payload["receipts"]):
        nested = result["receipt"]
        coordinates = {
            "source_namespace": "local_files",
            "root": result["root"],
            "path": result["path"],
            "item_id": result["item_id"],
            "source_ref": result["source_uri"],
        }
        bound = {
            "principal_id": access["principal_id"],
            "client_id": access["client_id"],
            "policy_version": access["policy_version"],
            "policy_hash": access["policy_hash"],
            "mapping_version": access["mapping_version"],
            "mapping_hash": access["mapping_hash"],
            "receipt_version": access["receipt_version"],
            **coordinates,
        }
        assert {key: top_level[key] for key in bound} == bound
        assert {key: nested[key] for key in bound} == bound
        assert top_level["auth_context"]["grant_ids"] == access["grant_ids"]


def test_employee_mapping_hash_is_bound_to_client_id(
    governed: dict[str, Path], launch: Any
) -> None:
    grants = (_notes_grant(),)
    policy = _write_policy(governed, *grants)
    first = _register(governed, policy, client_id="analyst:client:first")
    second = _register(governed, policy, client_id="analyst:client:second")
    first_status = _tool_payload(_status(launch(_employee_env(first))))
    second_status = _tool_payload(_status(launch(_employee_env(second))))
    first_access = first_status["access"]
    second_access = second_status["access"]

    assert first_access["policy_hash"] == second_access["policy_hash"]
    assert first_access["mapping_hash"] != second_access["mapping_hash"]
    assert first_access["mapping_hash"] == _recompute_employee_mapping_hash(
        first_access, grants
    )
    assert second_access["mapping_hash"] == _recompute_employee_mapping_hash(
        second_access, grants
    )


def test_employee_compile_preview_is_grant_scoped(
    governed: dict[str, Path], launch: Any
) -> None:
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)
    client = launch(_employee_env(credential))

    reply = client.request(
        "tools/call",
        {"name": "kb_compile_preview", "arguments": {"query": "successor"}},
    )

    result = reply["result"]
    assert not result.get("isError"), result
    text = result["content"][0]["text"]
    assert f"[{GRANTED_ROOT}:guide.md#Parity @" in text
    assert f"{UNGRANTED_ROOT}:" not in text
    assert "payroll" not in text


def test_owner_mode_still_reads_every_configured_root(
    governed: dict[str, Path], launch: Any
) -> None:
    """The grant, not the item ACL, is what narrows the employee's evidence."""
    _write_policy(governed, _notes_grant())
    client = launch({})

    payload = _tool_payload(_search(client))
    status = _tool_payload(_status(client))

    assert {result["root"] for result in payload["results"]} == {
        GRANTED_ROOT,
        UNGRANTED_ROOT,
    }
    assert all(
        "auth_context" not in receipt for receipt in payload["receipts"]
    ), payload["receipts"]
    employee_only = {"client_id", "policy_version", "receipt_version"}
    assert all(employee_only.isdisjoint(receipt) for receipt in payload["receipts"])
    assert all(
        isinstance(result.get("receipt"), dict)
        and employee_only.isdisjoint(result["receipt"])
        for result in payload["results"]
    )
    assert "access" not in status
    assert {root["name"] for root in status["roots"]} == {GRANTED_ROOT, UNGRANTED_ROOT}
    assert _access_events(governed) == []


@pytest.mark.parametrize(
    ("failure", "audited"),
    [
        ("wrong_secret", True),
        ("unknown_client", True),
        ("revoked_client", True),
        ("expired_credential", True),
        ("missing_clients", True),
        # Neither of these can reach a durable sink: without a secret there is
        # no credential to verify, and without a policy there is no identity
        # the audit row could name.
        ("missing_secret", False),
        ("missing_policy", False),
    ],
)
def test_employee_credential_failures_are_non_enumerating(
    governed: dict[str, Path], launch: Any, failure: str, audited: bool
) -> None:
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)
    environment = _employee_env(credential)

    if failure == "wrong_secret":
        environment[CLIENT_SECRET_ENV] = credential.client_secret + "tamper"
    elif failure == "unknown_client":
        environment[CLIENT_ID_ENV] = "analyst:client:not-registered"
    elif failure == "revoked_client":
        registry = AccessRegistry(policy, state_path=governed["clients"])
        assert registry.revoke_client(credential.client_id)
    elif failure == "expired_credential":
        environment = _employee_env(
            _register(
                governed,
                policy,
                client_id="analyst:client:expired",
                clock=lambda: EXPIRED_CLOCK,
                expires_at=EXPIRED_CLOCK + timedelta(days=1),
            )
        )
    elif failure == "missing_secret":
        environment.pop(CLIENT_SECRET_ENV)
    elif failure == "missing_policy":
        governed["policy"].unlink()
    else:
        governed["clients"].unlink()

    client = launch(environment)

    assert _error_text(_search(client)) == ACCESS_DENIED_MESSAGE
    assert _error_text(_search(client, query="")) == ACCESS_DENIED_MESSAGE
    assert _error_text(_status(client)) == ACCESS_DENIED_MESSAGE
    with SQLiteRepository(governed["database"]) as repository:
        assert repository.list_receipts() == ()
    events = _access_events(governed)
    assert all(event.outcome is AccessAuditOutcome.DENIED for event in events)
    if audited:
        assert [event.reason_code for event in events] == ["invalid_credentials"] * 3
    else:
        assert events == []


def test_employee_without_grants_is_denied_without_owner_fallback(
    governed: dict[str, Path], launch: Any
) -> None:
    policy = _write_policy(governed)
    credential = _register(governed, policy)

    text = _error_text(_search(launch(_employee_env(credential))))

    assert text == PROJECT_NOT_GRANTED_MESSAGE
    with SQLiteRepository(governed["database"]) as repository:
        assert repository.list_receipts() == ()
    denied = [
        event
        for event in _access_events(governed)
        if event.outcome is AccessAuditOutcome.DENIED
    ]
    assert [event.reason_code for event in denied] == ["project_not_granted"]
    assert denied[0].principal is not None
    assert denied[0].principal.principal_id == EMPLOYEE_PRINCIPAL


def test_forged_identity_arguments_are_rejected_at_the_wire(
    governed: dict[str, Path], launch: Any
) -> None:
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)
    client = launch(_employee_env(credential))

    for arguments in (
        {"query": "successor", "principal": "lee@example.com"},
        {"query": "successor", "client_id": "analyst:client:other"},
        {"query": "successor", "session": "forged-session"},
    ):
        reply = client.request(
            "tools/call", {"name": "kb_search", "arguments": arguments}
        )
        assert reply["error"]["code"] == -32602, reply

    reply = client.request(
        "tools/call",
        {"name": "kb_status", "arguments": {"principal": "lee@example.com"}},
    )
    assert reply["error"]["code"] == -32602, reply


def test_employee_kb_status_lists_only_granted_roots(
    governed: dict[str, Path], launch: Any
) -> None:
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)
    client = launch(_employee_env(credential))

    payload = _tool_payload(_status(client))

    assert payload["state"] == "fresh"
    assert "detail" not in payload
    assert [root["name"] for root in payload["roots"]] == [GRANTED_ROOT]
    authentications = [
        event
        for event in _access_events(governed)
        if event.event_type == "authentication"
    ]
    assert [event.client_id for event in authentications] == [credential.client_id]
    assert authentications[0].outcome is AccessAuditOutcome.ALLOWED


def test_employee_preflight_never_inspects_an_ungranted_root(
    governed: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hostile ungranted root cannot enter employee status discovery."""
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)
    monkeypatch.setenv("LEE_KB_CONFIG", str(governed["config"]))
    for name in (CLIENT_ID_ENV, CLIENT_SECRET_ENV, CLIENT_SECRET_FILE_ENV):
        monkeypatch.delenv(name, raising=False)

    runtime = mcp._runtime()

    class ExplosivePath:
        def is_dir(self) -> bool:
            raise AssertionError("ungranted root was inspected")

        def resolve(self) -> Path:
            raise AssertionError("ungranted root was resolved")

    runtime = replace(
        runtime,
        roots=tuple(
            replace(root, path=ExplosivePath())
            if root.name == UNGRANTED_ROOT
            else root
            for root in runtime.roots
        ),
    )
    registry = AccessRegistry(policy, state_path=governed["clients"])
    session = registry.authenticate(credential.client_id, credential.client_secret)
    call = mcp._EmployeeCall(runtime, session, policy)

    disposition, status, error = mcp._status_preflight(call)

    assert error is None
    assert disposition == "fresh"
    assert "detail" not in status
    assert [root["name"] for root in status["roots"]] == [GRANTED_ROOT]


def test_employee_status_live_checks_granted_root(
    governed: dict[str, Path], launch: Any
) -> None:
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)
    client = launch(_employee_env(credential))
    config = tomllib.loads(governed["config"].read_text(encoding="utf-8"))
    granted_path = Path(config["roots"][GRANTED_ROOT]["path"])

    (granted_path / "guide.md").write_text(
        "# Parity\n\nThe granted source has drifted.\n", encoding="utf-8"
    )
    stale = _tool_payload(_status(client))

    assert stale["state"] == "stale"
    assert [root["name"] for root in stale["roots"]] == [GRANTED_ROOT]
    assert stale["roots"][0]["state"] == "stale"

    (granted_path / "guide.md").unlink()
    granted_path.rmdir()
    missing = _tool_payload(_status(client))

    assert missing["state"] == "error"
    assert missing["reason"] == "missing-required-root"
    assert [root["name"] for root in missing["roots"]] == [GRANTED_ROOT]
    assert missing["roots"][0]["state"] == "missing"

def test_employee_status_exact_file_grant_bounds_live_discovery(
    governed: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exact grant checks its file without reading unrelated siblings."""
    policy = _write_policy(governed, _notes_grant(path_prefix="guide.md"))
    credential = _register(governed, policy)
    monkeypatch.setenv("LEE_KB_CONFIG", str(governed["config"]))
    for name in (CLIENT_ID_ENV, CLIENT_SECRET_ENV, CLIENT_SECRET_FILE_ENV):
        monkeypatch.delenv(name, raising=False)
    config = tomllib.loads(governed["config"].read_text(encoding="utf-8"))
    granted_path = Path(config["roots"][GRANTED_ROOT]["path"])
    (granted_path / "expensive.md").write_text(
        "# Must not be read\n", encoding="utf-8"
    )
    sync = subprocess.run(
        [sys.executable, "-m", "lee_kb.main", "sync"],
        cwd=PROJECT_ROOT,
        env=_environment(governed["config"]),
        capture_output=True,
        text=True,
        check=False,
    )
    assert sync.returncode == 0, sync.stdout + sync.stderr

    runtime = mcp._runtime()
    registry = AccessRegistry(policy, state_path=governed["clients"])
    session = registry.authenticate(credential.client_id, credential.client_secret)
    call = mcp._EmployeeCall(runtime, session, policy)
    discovered: list[str] = []
    describe = mcp.LocalFilesConnector._describe

    def record_describe(
        connector: Any, root: Any, relative: str, file_path: Path, handler: Any
    ) -> Any:
        discovered.append(relative)
        if relative == "expensive.md":
            raise AssertionError("ungranted sibling was discovered")
        return describe(connector, root, relative, file_path, handler)

    monkeypatch.setattr(mcp.LocalFilesConnector, "_describe", record_describe)

    disposition, status, error = mcp._status_preflight(call)

    assert error is None
    assert disposition == "fresh"
    assert discovered == ["guide.md"]
    assert [root["name"] for root in status["roots"]] == [GRANTED_ROOT]
    assert status["roots"][0]["docs"] == 1

    (granted_path / "guide.md").write_text(
        "# Parity\n\nThe granted source has drifted.\n", encoding="utf-8"
    )
    disposition, status, error = mcp._status_preflight(call)

    assert error is None
    assert disposition == "stale"
    assert status["roots"][0]["state"] == "stale"
    assert discovered == ["guide.md", "guide.md"]


def test_employee_status_prefix_grant_bounds_discovery_to_subtree(
    governed: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _write_policy(governed, _notes_grant(path_prefix="nested"))
    credential = _register(governed, policy)
    monkeypatch.setenv("LEE_KB_CONFIG", str(governed["config"]))
    for name in (CLIENT_ID_ENV, CLIENT_SECRET_ENV, CLIENT_SECRET_FILE_ENV):
        monkeypatch.delenv(name, raising=False)
    config = tomllib.loads(governed["config"].read_text(encoding="utf-8"))
    granted_path = Path(config["roots"][GRANTED_ROOT]["path"])
    nested_path = granted_path / "nested"
    nested_path.mkdir()
    (nested_path / "granted.md").write_text(
        "# Nested grant\n", encoding="utf-8"
    )
    (granted_path / "unrelated.md").write_text(
        "# Must not be read\n", encoding="utf-8"
    )

    runtime = mcp._runtime()
    runtime = replace(
        runtime,
        roots=tuple(
            replace(root, include=(*root.include, "nested/*.md"))
            if root.name == GRANTED_ROOT
            else root
            for root in runtime.roots
        ),
    )
    registry = AccessRegistry(policy, state_path=governed["clients"])
    session = registry.authenticate(credential.client_id, credential.client_secret)
    call = mcp._EmployeeCall(runtime, session, policy)
    discovered: list[str] = []
    describe = mcp.LocalFilesConnector._describe

    def record_describe(
        connector: Any, root: Any, relative: str, file_path: Path, handler: Any
    ) -> Any:
        discovered.append(relative)
        if relative != "nested/granted.md":
            raise AssertionError("outside-prefix sibling was discovered")
        return describe(connector, root, relative, file_path, handler)

    monkeypatch.setattr(mcp.LocalFilesConnector, "_describe", record_describe)

    disposition, status, error = mcp._status_preflight(call)

    assert error is None
    assert disposition == "stale"
    assert status["roots"][0]["state"] == "stale"
    assert discovered == ["nested/granted.md"]

def test_grant_revocation_applies_to_a_live_server_process(
    governed: dict[str, Path], launch: Any
) -> None:
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)
    client = launch(_employee_env(credential))

    assert _tool_payload(_search(client))["results"]

    _write_policy(
        governed,
        _notes_grant(revoked_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
    )

    assert _error_text(_search(client)) == PROJECT_NOT_GRANTED_MESSAGE
    assert _tool_payload(_status(client))["roots"] == []


def test_employee_secret_file_credential_is_accepted(
    governed: dict[str, Path], launch: Any, tmp_path: Path
) -> None:
    policy = _write_policy(governed, _notes_grant())
    credential = _register(governed, policy)
    secret_file = tmp_path / "client.secret"
    secret_file.write_text(credential.client_secret + "\n", encoding="utf-8")

    payload = _tool_payload(
        _search(
            launch(
                {
                    CLIENT_ID_ENV: credential.client_id,
                    CLIENT_SECRET_FILE_ENV: str(secret_file),
                }
            )
        )
    )

    assert {result["root"] for result in payload["results"]} == {GRANTED_ROOT}


# --------------------------------------------------------------------------- #
# owner-gateway mode: the frozen consumer route
# --------------------------------------------------------------------------- #
OWNER_PRINCIPAL = "lee@leebase.com"
LEGACY_OWNER = "legacy-owner@example.invalid"


def _git(*arguments: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=None if cwd is None else str(cwd),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return completed.stdout.strip()


@pytest.fixture
def owner_workspace(tmp_path: Path) -> dict[str, Any]:
    """A corpus plus a one-commit history repository, in owner-gateway mode."""
    corpus = tmp_path / "notes"
    corpus.mkdir()
    (corpus / "guide.md").write_text(
        "# Parity\n\nThe successor exposes governed retrieval with receipts.\n",
        encoding="utf-8",
    )
    worktree = tmp_path / "history"
    (worktree / "docs").mkdir(parents=True)
    (worktree / "docs" / "fact.md").write_text("released body\n", encoding="utf-8")
    (worktree / "docs" / "other.md").write_text("unreleased body\n", encoding="utf-8")
    identity = ("-c", "user.name=probe", "-c", "user.email=probe@example.invalid")
    _git("init", "-q", "-b", "main", str(worktree))
    _git("-C", str(worktree), *identity, "add", "docs")
    _git("-C", str(worktree), *identity, "commit", "-q", "-m", "release")
    commit = _git("-C", str(worktree), "rev-parse", "HEAD")

    config = tmp_path / "config.toml"
    config.write_text(
        f"""schema = 1
owner = "{LEGACY_OWNER}"

[roots.notes]
path = "{corpus.as_posix()}"
owner = "{OWNER_PRINCIPAL}"
include = ["*.md"]
authority = "derived"
trust = "curated"
visibility = "private"
project = "default"

[owner_gateway]
project = "default"

[owner_gateway.mapping]
authenticated_principal = "lee"
principal_id = "{OWNER_PRINCIPAL}"

[[owner_gateway.mapping.grants]]
project = "default"
source_namespace = "local_files"
root = "notes"
path_prefix = "{WHOLE_ROOT_PATH_PREFIX}"

[owner_gateway.historical_release]
version = "lee-kb.owner.historical-release/v1"

[[owner_gateway.historical_release.rules]]
repository = "history"
commit = "{commit}"
path = "docs/fact.md"
classification = "public"
principals = ["{OWNER_PRINCIPAL}"]
projects = ["default"]
source_namespace = "local_files"
root = "notes"

[owner_gateway.repositories]
history = "{worktree.as_posix()}"
""",
        encoding="utf-8",
    )
    sync = subprocess.run(
        [sys.executable, "-m", "lee_kb.main", "sync"],
        cwd=PROJECT_ROOT,
        env=_environment(config),
        capture_output=True,
        text=True,
        check=False,
    )
    assert sync.returncode == 0, sync.stdout + sync.stderr
    return {
        "config": config,
        "commit": commit,
        "database": tmp_path / "knowledge.sqlite",
    }


@pytest.fixture
def owner_client(owner_workspace: dict[str, Any]):
    instance = MCPClient(owner_workspace["config"])
    try:
        yield instance
    finally:
        instance.close()


def _history(client: MCPClient, **arguments: str) -> dict:
    return client.request(
        "tools/call", {"name": "kb_history_get", "arguments": arguments}
    )


def test_initialize_publishes_the_owner_handshake_in_owner_gateway_mode(
    owner_client: MCPClient, owner_workspace: dict[str, Any]
) -> None:
    result = owner_client.initialize()["result"]
    mapping = load_owner_gateway(
        tomllib.loads(owner_workspace["config"].read_text(encoding="utf-8"))
    ).mapping

    assert result["serverInfo"]["name"] == "lee-kb"
    assert result["serverInfo"]["owner"] == {
        "owner": "lee-kb",
        "api_version": OWNER_API_VERSION,
        "contract_version": OWNER_CONTRACT_VERSION,
        "schema_version": OWNER_SCHEMA_VERSION,
        "corpus_version": OWNER_CORPUS_VERSION,
        "mapping_version": OWNER_MAPPING_VERSION,
        "mapping_hash": mapping.mapping_hash,
        "permission_version": OWNER_PERMISSION_VERSION,
        "receipt_version": OWNER_RECEIPT_VERSION,
        "historical_version": OWNER_HISTORICAL_VERSION,
    }


def test_owner_gateway_search_identity_comes_from_the_server_mapping(
    owner_client: MCPClient,
) -> None:
    owner_client.initialize()
    payload = _tool_payload(
        owner_client.request(
            "tools/call", {"name": "kb_search", "arguments": {"query": "successor"}}
        )
    )

    assert payload["results"]
    receipt = payload["receipts"][0]
    # The configured `owner` is ignored: identity is the versioned mapping.
    assert receipt["principal"]["id"] == OWNER_PRINCIPAL
    assert receipt["principal"]["type"] == PrincipalType.AI_EMPLOYEE.value
    assert receipt["principal_id"] == OWNER_PRINCIPAL
    assert receipt["mapping_version"] == OWNER_MAPPING_VERSION
    assert len(receipt["mapping_hash"]) == 64
    assert receipt["current_policy_version"] == OWNER_PERMISSION_VERSION
    assert receipt["current_policy_decision"] == "allow"
    assert receipt["freshness_state"] == "fresh"
    assert receipt["audit_id"].startswith("audit-")
    assert (receipt["source_namespace"], receipt["root"]) == ("local_files", "notes")
    assert payload["results"][0]["receipt"]["mapping_hash"] == receipt["mapping_hash"]


def test_owner_gateway_releases_one_exact_history_object_with_its_receipt(
    owner_client: MCPClient, owner_workspace: dict[str, Any]
) -> None:
    owner_client.initialize()
    commit = owner_workspace["commit"]

    payload = _tool_payload(
        _history(
            owner_client,
            repository="history",
            commit=commit,
            path="docs/fact.md",
            classification="public",
        )
    )

    assert payload["knowledge_state"] == "known"
    assert payload["freshness_state"] == "fresh"
    assert payload["body"] == "released body\n"
    receipt = payload["receipt"]
    assert receipt["repository"] == "history"
    assert receipt["commit"] == commit
    assert receipt["path"] == "docs/fact.md"
    assert receipt["classification"] == "public"
    assert receipt["principal_id"] == OWNER_PRINCIPAL
    assert receipt["project"] == "default"
    assert receipt["mapping_version"] == OWNER_MAPPING_VERSION
    assert receipt["current_policy_version"] == OWNER_PERMISSION_VERSION
    assert receipt["current_policy_decision"] == "allow"
    assert receipt["historical_policy_version"] == OWNER_HISTORICAL_VERSION
    assert receipt["historical_policy_decision"] == "allow"
    assert len(receipt["historical_manifest_hash"]) == 64
    assert receipt["blob_hash"] == compute_content_hash("released body\n")
    assert receipt["blob_timestamp"] and receipt["evaluation_time"]
    assert receipt["audit_id"] == receipt["receipt_id"]
    # The receipts array carries only names the consumer's normalizer allows.
    assert set(payload["receipts"][0]) <= CONSUMER_RECEIPT_KEYS
    assert payload["receipts"][0]["audit_id"] == receipt["audit_id"]


def test_owner_gateway_history_denials_are_identical_and_release_no_body(
    owner_client: MCPClient, owner_workspace: dict[str, Any]
) -> None:
    owner_client.initialize()
    commit = owner_workspace["commit"]
    withheld = {
        "classification": dict(
            repository="history",
            commit=commit,
            path="docs/fact.md",
            classification="confidential",
        ),
        "unreleased_path": dict(
            repository="history",
            commit=commit,
            path="docs/other.md",
            classification="public",
        ),
        "unknown_commit": dict(
            repository="history",
            commit="1" * 40,
            path="docs/fact.md",
            classification="public",
        ),
        "unlisted_repository": dict(
            repository="elsewhere",
            commit=commit,
            path="docs/fact.md",
            classification="public",
        ),
        "branch_reference": dict(
            repository="history",
            commit="main",
            path="docs/fact.md",
            classification="public",
        ),
    }
    answers = {
        name: _tool_payload(_history(owner_client, **arguments))
        for name, arguments in withheld.items()
    }

    assert list(answers.values()) == [
        {
            "knowledge_state": "unknown",
            "freshness_state": "unknown",
            "body": None,
            "receipt": None,
        }
    ] * len(withheld)
    forged = _history(
        owner_client,
        repository="history",
        commit=commit,
        path="docs/fact.md",
        classification="public",
        principal="someone-else",
    )
    assert forged["error"]["code"] == -32602


def test_employee_credentials_and_owner_gateway_config_fail_closed(
    owner_workspace: dict[str, Any],
) -> None:
    client = MCPClient(
        owner_workspace["config"],
        {CLIENT_ID_ENV: "analyst:client:mcp", CLIENT_SECRET_ENV: "s" * 32},
    )
    try:
        initialized = client.initialize()["result"]
        search = client.request(
            "tools/call", {"name": "kb_search", "arguments": {"query": "successor"}}
        )["result"]
        history = _tool_payload(
            _history(
                client,
                repository="history",
                commit=owner_workspace["commit"],
                path="docs/fact.md",
                classification="public",
            )
        )
    finally:
        client.close()

    assert "owner" not in initialized["serverInfo"]
    assert search["isError"] is True
    assert "cannot both be set" in search["content"][0]["text"]
    assert history["body"] is None
    with SQLiteRepository(owner_workspace["database"]) as repository:
        assert repository.list_receipts() == ()
