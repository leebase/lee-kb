"""Contract and user-path tests for the incumbent-compatible MCP surface."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lee_kb.mcp import PROTOCOL_VERSION, TOOL_DEFS
from lee_kb.repository import SQLiteRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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


def _environment(config_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    environment["LEE_KB_CONFIG"] = str(config_path)
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

    def __init__(self, config_path: Path) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "lee_kb.mcp"],
            cwd=PROJECT_ROOT,
            env=_environment(config_path),
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
    """The structural contract mirrors kb-index/src/kb/mcp.py exactly."""
    names = [tool["name"] for tool in TOOL_DEFS]
    assert names == ["kb_search", "kb_status", "kb_compile_preview"]
    assert {
        tool["name"]: tool["inputSchema"] for tool in TOOL_DEFS
    } == INCUMBENT_INPUT_SCHEMAS


def test_initialize_and_tools_list_are_mcp_compatible(client: MCPClient) -> None:
    initialized = client.initialize()
    result = initialized["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "lee-kb"
    assert result["serverInfo"]["version"]

    listed = client.request("tools/list")
    assert [tool["name"] for tool in listed["result"]["tools"]] == [
        "kb_search",
        "kb_status",
        "kb_compile_preview",
    ]


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
