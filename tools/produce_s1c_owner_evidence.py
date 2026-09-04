#!/usr/bin/env python3
"""Produce the content-free S1C owner-acceptance artifact for lee-kb.

The LeeOS S1C plan freezes an owner slice in this repository and requires a
content-free owner-acceptance artifact naming the exact owner repository and
version, the commands run, the schema/corpus/identity handshake, the current
and history permission matrices, receipt fields, the no-write result, adapter
candidates and the final handshake.  This generator produces that artifact by
running the owner-native verification commands and probes for real:

    python3 tools/produce_s1c_owner_evidence.py --output evidence/s1c/S1C-lee-kb.json

Nothing is asserted from a table of expectations.  Every matrix row, receipt
field list, handshake fact and no-write result is computed here, and ``status``
is ``accepted`` only when every command passes, every contract row maps and the
no-write proof holds.  Otherwise ``status`` is ``failed`` and the exact reasons
are listed.

The artifact never contains source content, question text, corpus path lists or
evidence bodies.  Only lee-kb's own root-relative file names, symbol names,
test ids, schema key names, digests, counts and booleans are emitted.  The
schema and its determinism rules are documented in ``docs/s1c-owner-contract.md``.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lee_kb import contracts, governance, mcp, owner  # noqa: E402
from lee_kb.access import ACCESS_POLICY_VERSION  # noqa: E402
from lee_kb.repository import SQLiteRepository  # noqa: E402

ARTIFACT_VERSION = "lee-kb.owner.acceptance/v1"
ARTIFACT_ID = "S1C-lee-kb"
OWNER_REPOSITORY = "lee-kb"
CONTRACT_DOCUMENT = "docs/s1c-owner-contract.md"
GENERATOR = "tools/produce_s1c_owner_evidence.py"

# Fields a client or delegate must never be able to send on the wire. Mirrors
# the consumer's forbidden-argument set for the frozen stdio candidate.
FORBIDDEN_CLIENT_FIELDS = frozenset(
    {
        "principal",
        "principal_id",
        "authenticated_principal",
        "groups",
        "grant",
        "grants",
        "permission",
        "permissions",
        "project_ids",
        "projects",
        "source_namespaces",
        "source_namespace",
        "roots",
        "root",
        "path_prefix",
        "item_ids",
        "tenant",
        "lane",
        "scope_id",
        "purpose",
    }
)

# Every field an exact-history receipt must bind (frozen Deliver 4).
REQUIRED_HISTORY_RECEIPT_FIELDS = (
    "audit_id",
    "mapping_version",
    "mapping_hash",
    "mapped_principal_id",
    "mapped_principal_type",
    "authenticated_principal",
    "tenant",
    "lane",
    "scope_id",
    "purpose",
    "project",
    "source_namespace",
    "root",
    "path",
    "item_id",
    "locator",
    "classification",
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
    "contract_version",
    "schema_version",
    "corpus_version",
)

# What a current-release receipt would have to bind for lossless current/history
# receipt parity (frozen Acceptance bullet 3).
REQUIRED_CURRENT_RECEIPT_FIELDS = (
    "knowledge_item_id",
    "chunk_id",
    "content_hash",
    "source_locator",
    "retrieval_timestamp",
    "principal",
    "project",
    "mapping_version",
    "mapping_hash",
    "classification",
    "policy_version",
    "policy_hash",
    "policy_decision",
    "freshness_state",
    "audit_id",
)

# Every name the released exact-history receipt must carry on the wire.
REQUIRED_HISTORY_WIRE_RECEIPT_FIELDS = (
    "receipt_id",
    "audit_id",
    "mapping_version",
    "mapping_hash",
    "principal_id",
    "project",
    "repository",
    "commit",
    "path",
    "classification",
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
)

# Exactly the receipt names the consumer's normalizer keeps
# (leeos/src/leeos/core/adapters.py, KnowledgeNormalizer._receipt_values).
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

# The incumbent-compatible receipt payload keys, unchanged in every mode.
LEGACY_RECEIPT_KEYS = frozenset(
    {
        "id",
        "knowledge_item_id",
        "chunk_id",
        "content_hash",
        "source_locator",
        "retrieval_timestamp",
        "principal",
        "project",
        "query",
        "auth_context",
    }
)

PROBE_NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)
PROBE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
PROBE_OTHER_COMMIT = "1123456789abcdef0123456789abcdef01234567"
PROBE_BODY = "immutable probe body"
WIRE_OWNER = "wire-probe-owner@example.invalid"
WIRE_QUERY = "governed receipts"
WIRE_HISTORY_REPOSITORY = "history"
WIRE_HISTORY_BODY = "immutable released body\n"

# Every version the owner handshake must publish on the wire.
OWNER_HANDSHAKE_FIELDS = (
    "owner",
    "api_version",
    "contract_version",
    "schema_version",
    "corpus_version",
    "mapping_version",
    "mapping_hash",
    "permission_version",
    "receipt_version",
    "historical_version",
)

_DURATION = re.compile(r"\b\d+(?:\.\d+)?s\b")
_SECONDS = re.compile(r"\b\d+(?:\.\d+)?\s+seconds\b")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?"
)
_HEX32 = re.compile(r"\b[0-9a-f]{32,}\b")


# --------------------------------------------------------------------------- #
# digests, canonical serialization and output normalization
# --------------------------------------------------------------------------- #
def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    """Serialize exactly as both repositories canonicalize hashed bodies."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _canonical_sha256(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _normalize_output(text: str, replacements: tuple[tuple[str, str], ...]) -> str:
    """Strip the only nondeterministic parts of a command's own output.

    pytest embeds wall-clock durations and absolute temporary paths.  Those are
    replaced by stable tokens so a second run of this generator reproduces the
    recorded digests on the same toolchain.
    """
    out = text.replace("\r\n", "\n")
    for needle, token in replacements:
        if needle:
            out = out.replace(needle, token)
    out = _TIMESTAMP.sub("<timestamp>", out)
    out = _DURATION.sub("<duration>", out)
    out = _SECONDS.sub("<duration>", out)
    out = _HEX32.sub("<digest>", out)
    out = "\n".join(line.rstrip() for line in out.split("\n")).strip()
    return out + "\n" if out else ""


def _replacements(extra: tuple[Path, ...] = ()) -> tuple[tuple[str, str], ...]:
    values = [(str(path), "<tmp>") for path in extra]
    values.append((tempfile.gettempdir(), "<tmp>"))
    values.append((str(REPO_ROOT), "<repo>"))
    values.append((str(Path.home()), "<home>"))
    values.append((sys.prefix, "<prefix>"))
    # Longest needle first so nested paths collapse to one token.
    return tuple(sorted(values, key=lambda item: len(item[0]), reverse=True))


# --------------------------------------------------------------------------- #
# command execution
# --------------------------------------------------------------------------- #
def _run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    replacements: tuple[tuple[str, str], ...],
    timeout: float = 900.0,
) -> dict[str, Any]:
    """Run one command and return its content-free, normalized record."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable] + argv[1:],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    normalized = _normalize_output(
        (completed.stdout or "") + (completed.stderr or ""), replacements
    )
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "output_sha256": _sha256_text(normalized),
        "output_bytes": len(normalized.encode("utf-8")),
        "output_normalization": "pytest-normalized/v1",
    }


def _repo_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_ROOT)
    env.pop("LEE_KB_CONFIG", None)
    return env


def _child_env(config_path: Path) -> dict[str, str]:
    """Minimal environment matching the frozen stdio candidate's own env."""
    return {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "LEE_KB_CONFIG": str(config_path),
        "PYTHONPATH": str(SRC_ROOT),
    }


# --------------------------------------------------------------------------- #
# repository, versions, identity
# --------------------------------------------------------------------------- #
def _git(*args: str) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=30.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _package_version() -> str | None:
    try:
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    return version if isinstance(version, str) else None


def _console_scripts() -> dict[str, str]:
    try:
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    scripts = data.get("project", {}).get("scripts", {})
    return {k: v for k, v in scripts.items() if isinstance(v, str)}


def _owner_repository() -> dict[str, Any]:
    status = _git("status", "--porcelain")
    changed = (
        None
        if status is None
        else len([row for row in status.splitlines() if row.strip()])
    )
    return {
        "name": OWNER_REPOSITORY,
        "owner_repository_commit": _git("rev-parse", "HEAD"),
        "dirty": None if status is None else bool(status),
        "dirty_file_count": changed,
        "package_version": _package_version(),
        "contract_document": CONTRACT_DOCUMENT,
        "generator": GENERATOR,
        "console_scripts": _console_scripts(),
    }


def _versions() -> dict[str, Any]:
    return {
        "owner_api_version": owner.OWNER_API_VERSION,
        "owner_schema_version": owner.OWNER_SCHEMA_VERSION,
        "owner_corpus_version": owner.OWNER_CORPUS_VERSION,
        "owner_contract_version": contracts.OWNER_CONTRACT_VERSION,
        "owner_mapping_version": contracts.OWNER_MAPPING_VERSION,
        "owner_historical_release_version": contracts.OWNER_HISTORICAL_VERSION,
        "access_policy_version": ACCESS_POLICY_VERSION,
        "projection_schema_version": contracts.SCHEMA_VERSION,
        "mcp_protocol_version": mcp.PROTOCOL_VERSION,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
    }


def _identity_mapping() -> dict[str, Any]:
    """The immutable server-side mapping, hashed exactly as contracts.py does."""
    mapping = contracts.OwnerIdentityMapping()
    body = {
        "version": mapping.version,
        "authenticated_principal": mapping.authenticated_principal,
        "principal_id": mapping.principal_id,
        "tenant": mapping.tenant,
        "lane": mapping.lane,
        "scope_id": mapping.scope_id,
        "purpose": mapping.purpose,
        "grants": [],
    }
    return {
        "authenticated_principal": mapping.authenticated_principal,
        "principal_id": mapping.principal_id,
        "principal_type": contracts.PrincipalType.AI_EMPLOYEE.value,
        "tenant": mapping.tenant,
        "lane": mapping.lane,
        "scope_id": mapping.scope_id,
        "purpose": mapping.purpose,
        "mapping_version": mapping.version,
        "mapping_hash": mapping.mapping_hash,
        "mapping_hash_scope": "identity fields with an empty grant tuple",
        "mapping_hash_body_keys": sorted(body),
        "mapping_hash_algorithm": (
            "sha256(json.dumps(body,sort_keys=True,separators=(',',':'),"
            "ensure_ascii=False))"
        ),
        "mapping_hash_matches_consumer_algorithm": mapping.mapping_hash
        == _canonical_sha256(body),
        "grants_are_deployment_configuration": True,
        "client_supplied_identity_fields": [],
    }


def _symbol_locations() -> list[dict[str, Any]]:
    """Machine-checked current file/line of every symbol the contract cites."""
    targets: tuple[tuple[str, object], ...] = (
        ("contracts.OwnerIdentityMapping", contracts.OwnerIdentityMapping),
        (
            "contracts.OwnerIdentityMapping.resolve",
            contracts.OwnerIdentityMapping.resolve,
        ),
        (
            "contracts.OwnerIdentityMapping.permits",
            contracts.OwnerIdentityMapping.permits,
        ),
        ("contracts.MappedIdentity", contracts.MappedIdentity),
        ("contracts.SourceGrant", contracts.SourceGrant),
        ("contracts.SourceGrant.permits", contracts.SourceGrant.permits),
        ("contracts.HistoricalLocator", contracts.HistoricalLocator),
        ("contracts.HistoricalReleaseRule", contracts.HistoricalReleaseRule),
        ("contracts.HistoricalReleaseManifest", contracts.HistoricalReleaseManifest),
        (
            "contracts.HistoricalReleaseManifest.evaluate",
            contracts.HistoricalReleaseManifest.evaluate,
        ),
        ("contracts.ImmutableHistoricalObject", contracts.ImmutableHistoricalObject),
        ("contracts.HistoricalReceipt", contracts.HistoricalReceipt),
        ("contracts.HistoricalLookupResult", contracts.HistoricalLookupResult),
        ("contracts.RetrievalReceipt", contracts.RetrievalReceipt),
        ("contracts.PolicyBasis", contracts.PolicyBasis),
        ("governance.ExactHistoricalReader", governance.ExactHistoricalReader),
        (
            "governance.ExactHistoricalReader.lookup",
            governance.ExactHistoricalReader.lookup,
        ),
        ("contracts.OwnerCurrentReceipt", contracts.OwnerCurrentReceipt),
        ("contracts.OwnerCurrentResult", contracts.OwnerCurrentResult),
        ("owner.OwnerGateway", owner.OwnerGateway),
        ("owner.OwnerGateway.map_identity", owner.OwnerGateway.map_identity),
        ("owner.OwnerGateway.retrieve_current", owner.OwnerGateway.retrieve_current),
        ("owner.OwnerGateway.retrieve_history", owner.OwnerGateway.retrieve_history),
        ("owner._MappedPermissionEvaluator", owner._MappedPermissionEvaluator),
        ("owner.GitExactObjectResolver", owner.GitExactObjectResolver),
        ("owner.OwnerGatewayConfig", owner.OwnerGatewayConfig),
        ("owner.load_owner_gateway", owner.load_owner_gateway),
        ("owner.owner_handshake", owner.owner_handshake),
        ("mcp._tool_kb_history_get", mcp._tool_kb_history_get),
        ("mcp._handle_initialize", mcp._handle_initialize),
        ("mcp._owner_bundle", mcp._owner_bundle),
        ("mcp._runtime", mcp._runtime),
    )
    located: list[dict[str, Any]] = []
    for name, target in targets:
        try:
            source_file = Path(inspect.getsourcefile(target) or "")
            line = inspect.getsourcelines(target)[1]
        except (OSError, TypeError):
            located.append({"symbol": name, "file": None, "line": None})
            continue
        try:
            relative = source_file.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            relative = source_file.name
        located.append({"symbol": name, "file": relative, "line": line})
    return located


def _receipt_fields() -> dict[str, Any]:
    def names(cls: Any) -> list[str]:
        return [field.name for field in dataclasses.fields(cls)]

    historical = names(contracts.HistoricalReceipt)
    persisted_current = names(contracts.RetrievalReceipt)
    # The persisted retrieval receipt is unchanged; the owner-mode current
    # receipt is the additive parity carrier that owner-gateway mode emits.
    current = names(contracts.OwnerCurrentReceipt)
    return {
        "historical_receipt": historical,
        "historical_receipt_missing_required": [
            field
            for field in REQUIRED_HISTORY_RECEIPT_FIELDS
            if field not in historical
        ],
        "persisted_retrieval_receipt": persisted_current,
        "current_retrieval_receipt": current,
        "current_retrieval_receipt_missing_required": [
            field for field in REQUIRED_CURRENT_RECEIPT_FIELDS if field not in current
        ],
        "history_receipt_wire_required": list(REQUIRED_HISTORY_WIRE_RECEIPT_FIELDS),
        "consumer_receipt_allowlist": sorted(CONSUMER_RECEIPT_KEYS),
        "current_evidence": names(contracts.Evidence),
        "current_citation": names(contracts.Citation),
        "current_bundle": names(contracts.EvidenceBundle),
        "current_freshness_report": names(contracts.FreshnessReport),
        "current_query_audit_event": names(contracts.RetrievalAuditEvent),
        "access_audit_event": names(contracts.AccessAuditEvent),
        "historical_lookup_result": names(contracts.HistoricalLookupResult),
    }


# --------------------------------------------------------------------------- #
# in-process behaviour probes
# --------------------------------------------------------------------------- #
def _probe_grant(path_prefix: str = "docs") -> contracts.SourceGrant:
    return contracts.SourceGrant(
        "default", "local_files", "notes", path_prefix, ("local_files:docs/fact.md",)
    )


def _probe_locator(commit: str = PROBE_COMMIT, path: str = "docs/fact.md"):
    return contracts.HistoricalLocator("kb", commit, path)


def _probe_basis(
    name: str, decision: str, *, live: bool = True
) -> contracts.PolicyBasis:
    evaluated = PROBE_NOW - timedelta(minutes=1)
    expires = PROBE_NOW + timedelta(hours=1)
    if not live:
        evaluated = PROBE_NOW - timedelta(hours=2)
        expires = PROBE_NOW - timedelta(hours=1)
    return contracts.PolicyBasis(
        f"{name}/v1", contracts.compute_content_hash(name), decision, evaluated, expires
    )


def _probe_object(locator, classification: str = "public"):
    return contracts.ImmutableHistoricalObject(
        locator,
        PROBE_BODY,
        contracts.compute_content_hash(PROBE_BODY),
        PROBE_NOW,
        classification,
    )


class _CountingResolver:
    """Exact-object seam that records whether a denial reached the body."""

    def __init__(self, obj) -> None:
        self._object = obj
        self.calls = 0

    def __call__(self, locator):
        self.calls += 1
        return self._object if locator == self._object.locator else None


def _reader(
    *,
    grants=None,
    manifest_rules=None,
    manifest_expires=None,
    current="allow",
    current_live: bool = True,
    current_permission_present: bool = True,
    resolver: Any = "default",
) -> tuple[governance.ExactHistoricalReader, _CountingResolver | None]:
    locator = _probe_locator()
    grants = grants if grants is not None else (_probe_grant(),)
    mapping = contracts.OwnerIdentityMapping.default(grants)
    if manifest_rules is None:
        manifest_rules = (
            contracts.HistoricalReleaseRule(
                "lee@leebase.com",
                "default",
                locator,
                "public",
                _probe_basis("history", "allow"),
            ),
        )
    manifest = (
        None
        if manifest_rules == ()
        else contracts.HistoricalReleaseManifest.from_rules(
            manifest_rules, expires_at=manifest_expires
        )
    )
    counting: _CountingResolver | None = None
    if resolver == "default":
        counting = _CountingResolver(_probe_object(locator))
        resolver_callable: Any = counting
    else:
        resolver_callable = resolver
    basis = _probe_basis("current", current, live=current_live)
    return (
        governance.ExactHistoricalReader(
            mapping=mapping,
            manifest=manifest,
            current_permission=(
                (lambda *_: basis) if current_permission_present else None
            ),
            resolver=resolver_callable,
            clock=lambda: PROBE_NOW,
        ),
        counting,
    )


def _lookup(reader, **overrides):
    kwargs: dict[str, Any] = {
        "authenticated_principal": "lee",
        "locator": _probe_locator(),
        "classification": "public",
        "source_namespace": "local_files",
        "root": "notes",
        "item_id": "local_files:docs/fact.md",
    }
    kwargs.update(overrides)
    return reader.lookup(**kwargs)


def _state_token(result) -> str:
    body = "body" if result.body is not None else "no-body"
    receipt = "receipt" if result.receipt is not None else "no-receipt"
    reason = "reason" if getattr(result, "error", None) else "no-reason"
    return f"{result.knowledge_state.value}|{body}|{receipt}|{reason}"


def _tool_schema_fields() -> tuple[set[str], bool]:
    """Every client-settable argument name on the wire, and closure of schemas."""
    fields: set[str] = set()
    closed = True
    for tool in mcp.TOOL_DEFS:
        schema = tool.get("inputSchema", {})
        fields.update(schema.get("properties", {}))
        if schema.get("additionalProperties") is not False:
            closed = False
    return fields, closed


def _probe_current() -> dict[str, str]:
    """Behaviour of the mapped current-release path, observed not assumed."""
    observed: dict[str, str] = {}
    mapping = contracts.OwnerIdentityMapping.default((_probe_grant(),))

    identity = mapping.resolve("lee")
    observed["current.mapped_principal_admitted"] = (
        f"{identity.authenticated_principal}->{identity.principal_id}"
        f"|{identity.principal_type.value}|groups={len(identity.principal.groups)}"
    )

    try:
        mapping.resolve("delegate-of-lee")
        observed["current.unmapped_principal_denied"] = "admitted"
    except PermissionError:
        observed["current.unmapped_principal_denied"] = "PermissionError"

    try:
        mapping.resolve("lee", project="ungranted")
        observed["current.widened_project_rejected"] = "admitted"
    except PermissionError:
        observed["current.widened_project_rejected"] = "PermissionError"

    checks = (
        (
            "root",
            dict(source_namespace="local_files", root="other", path="docs/fact.md"),
        ),
        (
            "path",
            dict(source_namespace="local_files", root="notes", path="secret/x.md"),
        ),
        (
            "namespace",
            dict(source_namespace="other_files", root="notes", path="docs/fact.md"),
        ),
    )
    denied = [
        name
        for name, kwargs in checks
        if not mapping.permits(identity, item_id="local_files:docs/fact.md", **kwargs)
    ]
    item_denied = not mapping.permits(
        identity,
        source_namespace="local_files",
        root="notes",
        path="docs/fact.md",
        item_id="local_files:docs/other.md",
    )
    granted = mapping.permits(
        identity,
        source_namespace="local_files",
        root="notes",
        path="docs/fact.md",
        item_id="local_files:docs/fact.md",
    )
    if item_denied:
        denied.append("item")
    observed["current.widened_scope_rejected"] = (
        f"granted={granted}|denied={','.join(sorted(denied))}"
    )

    fields, closed = _tool_schema_fields()
    leaked = sorted(fields & FORBIDDEN_CLIENT_FIELDS)
    observed["current.client_cannot_send_identity_fields"] = (
        f"identity_fields={','.join(leaked) or 'none'}|closed_schemas={closed}"
    )

    multi = contracts.OwnerIdentityMapping.default(
        (
            _probe_grant(),
            contracts.SourceGrant("second", "local_files", "notes", "docs"),
        )
    )
    try:
        multi.resolve("lee")
        ambiguous = "admitted"
    except PermissionError:
        ambiguous = "PermissionError"
    first = multi.resolve("lee", project="default")
    second = multi.resolve("lee", project="second")
    observed["current.multi_project_requires_explicit_grant"] = (
        f"implicit={ambiguous}|projects={first.project},{second.project}"
        f"|grants={len(first.grants)},{len(second.grants)}"
    )

    item = contracts.KnowledgeItem(
        item_id=contracts.KnowledgeItemId("local_files", "docs/fact.md"),
        project="default",
        source_locator=contracts.SourceLocator("local_files", "file:///probe"),
        document_type=contracts.DocumentType.MARKDOWN,
        content_hash=contracts.compute_content_hash(PROBE_BODY),
        source_timestamp=PROBE_NOW,
        sync_timestamp=PROBE_NOW,
        permissions=contracts.PermissionSet("lee@leebase.com"),
    )
    evaluator = owner._MappedPermissionEvaluator(
        identity, lambda _: ("local_files", "notes", "docs/fact.md")
    )
    out_of_grant = owner._MappedPermissionEvaluator(
        identity, lambda _: ("local_files", "notes", "secret/x.md")
    )
    wrong_root = owner._MappedPermissionEvaluator(
        identity, lambda _: ("local_files", "other", "docs/fact.md")
    )
    wrong_principal = contracts.Principal("mallory@example.invalid")
    observed["current.mapped_permission_required_for_release"] = (
        f"in_grant={evaluator.is_permitted(item, identity.principal)}"
        f"|out_of_grant={out_of_grant.is_permitted(item, identity.principal)}"
        f"|out_of_root={wrong_root.is_permitted(item, identity.principal)}"
        f"|other_principal={evaluator.is_permitted(item, wrong_principal)}"
    )

    public_current = [
        name
        for name in dir(owner.OwnerGateway)
        if not name.startswith("_")
        and callable(getattr(owner.OwnerGateway, name, None))
        and name not in {"map_identity", "retrieve_history"}
    ]
    observed["current.public_release_entry_point"] = (
        f"public_current_release={','.join(sorted(public_current)) or 'none'}"
    )

    handshake = owner.owner_handshake(mapping)
    observed["current.owner_handshake"] = (
        f"fields={','.join(sorted(handshake))}"
        f"|mapping_hash_bound={handshake['mapping_hash'] == mapping.mapping_hash}"
    )
    return observed


def _probe_history() -> dict[str, str]:
    """Behaviour of the exact-history path, observed not assumed."""
    observed: dict[str, str] = {}
    locator = _probe_locator()

    reader, resolver = _reader()
    observed["history.authorized_release"] = _state_token(_lookup(reader))
    known = _lookup(reader)
    observed["history.receipt_binds_release_basis"] = (
        f"audit={known.receipt.audit_id.startswith('audit-')}"
        f"|manifest_hash={bool(known.receipt.historical_manifest_hash)}"
        f"|blob={known.receipt.blob_hash == contracts.compute_content_hash(PROBE_BODY)}"
        f"|blob_time={known.receipt.blob_timestamp == PROBE_NOW}"
        f"|eval_time={known.receipt.evaluation_time == PROBE_NOW}"
        f"|current={known.receipt.current_policy_decision}"
        f"|history={known.receipt.historical_policy_decision}"
        f"|locator={known.receipt.locator == locator}"
        f"|freshness={known.receipt.freshness_state.value}"
    )

    rejected = []
    for label, args in (
        ("pattern", ("kb", PROBE_COMMIT, "docs/*.md")),
        ("traversal", ("kb", PROBE_COMMIT, "docs/../etc/passwd")),
        ("absolute", ("kb", PROBE_COMMIT, "/etc/passwd")),
        ("short-commit", ("kb", "0123456", "docs/fact.md")),
        ("branch-ref", ("kb", "main", "docs/fact.md")),
    ):
        try:
            contracts.HistoricalLocator(*args)
        except (TypeError, ValueError):
            rejected.append(label)
    observed["history.exact_locator_only"] = f"rejected={','.join(rejected)}"

    history_tool = next(
        (tool for tool in mcp.TOOL_DEFS if tool["name"] == "kb_history_get"), None
    )
    schema = (history_tool or {}).get("inputSchema", {})
    signature = inspect.signature(governance.ExactHistoricalReader.lookup)
    plural = {"locators", "commits", "paths", "repositories", "filters"}
    multi = sorted(set(signature.parameters) & plural)
    observed["history.single_locator_argument"] = (
        f"wire_required={','.join(sorted(schema.get('required', [])))}"
        f"|wire_closed={schema.get('additionalProperties') is False}"
        f"|seam_locator_param={'locator' in signature.parameters}"
        f"|seam_multi_locator_params={','.join(multi) or 'none'}"
    )

    reader, _ = _reader(manifest_rules=())
    observed["history.manifest_required"] = _state_token(_lookup(reader))

    reader, resolver = _reader()
    observed["history.classification_mismatch"] = _state_token(
        _lookup(reader, classification="confidential")
    )

    reader, resolver = _reader()
    observed["history.locator_mismatch"] = _state_token(
        _lookup(reader, locator=_probe_locator(commit=PROBE_OTHER_COMMIT))
    )

    duplicate_rule = contracts.HistoricalReleaseRule(
        "lee@leebase.com",
        "default",
        locator,
        "public",
        _probe_basis("history", "allow"),
    )
    other_rule = contracts.HistoricalReleaseRule(
        "lee@leebase.com",
        "default",
        locator,
        "public",
        _probe_basis("history-second", "allow"),
    )
    reader, _ = _reader(manifest_rules=(duplicate_rule, other_rule))
    observed["history.ambiguous_manifest_rules"] = _state_token(_lookup(reader))

    reader, _ = _reader(manifest_expires=PROBE_NOW - timedelta(minutes=1))
    observed["history.expired_manifest"] = _state_token(_lookup(reader))

    stale_rule = contracts.HistoricalReleaseRule(
        "lee@leebase.com",
        "default",
        locator,
        "public",
        _probe_basis("history", "allow", live=False),
    )
    reader, _ = _reader(manifest_rules=(stale_rule,))
    observed["history.stale_historical_basis"] = _state_token(_lookup(reader))

    denied_rule = contracts.HistoricalReleaseRule(
        "lee@leebase.com", "default", locator, "public", _probe_basis("history", "deny")
    )
    reader, _ = _reader(manifest_rules=(denied_rule,))
    observed["history.denied_historical_basis"] = _state_token(_lookup(reader))

    reader, denied_resolver = _reader(current="deny")
    denied_current = _lookup(reader)
    reader_unknown, unknown_resolver = _reader(current_permission_present=False)
    unknown_current = _lookup(reader_unknown)
    observed["history.current_permission_required"] = (
        f"deny={_state_token(denied_current)}"
        f"|absent={_state_token(unknown_current)}"
        f"|resolver_calls={denied_resolver.calls + unknown_resolver.calls}"
    )

    reader, _ = _reader(resolver=None)
    observed["history.no_resolver_no_body"] = _state_token(_lookup(reader))

    reader, out_of_scope_resolver = _reader()
    out_of_scope = _lookup(reader, locator=_probe_locator(path="secret/x.md"))
    observed["history.widened_path_denied"] = (
        f"{_state_token(out_of_scope)}|resolver_calls={out_of_scope_resolver.calls}"
    )

    reader, unmapped_resolver = _reader()
    unmapped = _lookup(reader, authenticated_principal="delegate-of-lee")
    observed["history.unmapped_principal_denied"] = (
        f"{_state_token(unmapped)}|resolver_calls={unmapped_resolver.calls}"
    )

    try:
        contracts.HistoricalLookupResult(
            contracts.OwnerKnowledgeState.UNKNOWN,
            contracts.OwnerFreshnessState.UNKNOWN,
            PROBE_BODY,
            None,
        )
        structural = "body-allowed"
    except (TypeError, ValueError):
        structural = "body-structurally-blocked"
    observed["history.no_body_on_failure"] = structural

    seam_params = set(
        inspect.signature(governance.ExactHistoricalReader.__init__).parameters
    )
    lookup_params = set(signature.parameters)
    recovery = sorted(
        name
        for name in seam_params | lookup_params
        if "timeout" in name or "cancel" in name
    )
    observed["history.seam_has_no_search_or_timeout"] = (
        f"init={','.join(sorted(seam_params - {'self'}))}"
        f"|timeout_or_cancel={','.join(recovery) or 'none'}"
    )

    history_search_tools = sorted(
        tool["name"]
        for tool in mcp.TOOL_DEFS
        if "history" in tool["name"] and tool["name"] != "kb_history_get"
    )
    observed["history.no_history_search_or_cache_surface"] = (
        f"extra_history_tools={','.join(history_search_tools) or 'none'}"
    )

    with tempfile.TemporaryDirectory(prefix="s1c-exact-object-") as raw_seam:
        worktree, commit = _history_repository(Path(raw_seam))
        exact = contracts.HistoricalLocator(
            WIRE_HISTORY_REPOSITORY, commit, "docs/fact.md"
        )
        seam = owner.GitExactObjectResolver(
            {WIRE_HISTORY_REPOSITORY: worktree}, lambda _: "public"
        )
        bounded = owner.GitExactObjectResolver(
            {WIRE_HISTORY_REPOSITORY: worktree}, lambda _: "public", max_bytes=4
        )
        unclassified = owner.GitExactObjectResolver(
            {WIRE_HISTORY_REPOSITORY: worktree}, lambda _: None
        )
        unlisted = contracts.HistoricalLocator("other", commit, "docs/fact.md")
        unknown = contracts.HistoricalLocator(
            WIRE_HISTORY_REPOSITORY, PROBE_OTHER_COMMIT, "docs/fact.md"
        )
        observed["history.exact_object_seam_bounded"] = (
            f"released={seam.resolve(exact) is not None}"
            f"|unlisted={seam.resolve(unlisted) is None}"
            f"|unknown_commit={seam.resolve(unknown) is None}"
            f"|oversized={bounded.resolve(exact) is None}"
            f"|unclassified={unclassified.resolve(exact) is None}"
        )
    return observed


# --------------------------------------------------------------------------- #
# live stdio handshake and wire probes
# --------------------------------------------------------------------------- #
class _StdioProbe:
    """Bounded newline JSON-RPC client for the frozen stdio candidate."""

    def __init__(self, config_path: Path) -> None:
        self.argv = ["python3", "-m", "lee_kb.mcp"]
        self._env = _child_env(config_path)
        self.process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "lee_kb.mcp"],
            cwd=str(REPO_ROOT),
            env=self._env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._next_id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("owner stdio candidate closed the stream")
        reply = json.loads(line)
        if reply.get("id") != self._next_id:
            raise RuntimeError("owner stdio response correlation mismatch")
        return reply

    def tool(self, name: str, arguments: dict[str, Any]) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> int | None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
            return self.process.wait(timeout=15)
        except Exception:
            self.process.kill()
            return self.process.wait(timeout=15)


def _payload(reply: dict) -> dict | None:
    result = reply.get("result")
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return None
    text = content[0].get("text") if isinstance(content[0], dict) else None
    if not isinstance(text, str):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _wire_probe(
    config_path: Path, mapping: contracts.OwnerIdentityMapping, history: dict[str, str]
) -> dict[str, Any]:
    """Perform the consumer's own handshake, then probe identity and history."""
    probe = _StdioProbe(config_path)
    facts: dict[str, Any] = {
        "candidate": "lee-kb-mcp stdio",
        "executable_token": "lee-kb-mcp",
        "probe_argv": probe.argv,
        "probe_env_keys": sorted(_child_env(config_path)),
        "console_script_declared": "lee-kb-mcp" in _console_scripts(),
    }
    try:
        initialize = probe.request(
            "initialize",
            {
                "protocolVersion": mcp.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "leeos-core", "version": "s1c"},
            },
        )
        result = initialize.get("result", {})
        server_info = result.get("serverInfo", {})
        handshake = server_info.get("owner")
        handshake = handshake if isinstance(handshake, dict) else {}
        expected_handshake = owner.owner_handshake(mapping)
        listed = probe.request("tools/list").get("result", {})
        tools = sorted(
            tool.get("name")
            for tool in listed.get("tools", [])
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        )
        facts.update(
            {
                "protocol_version": result.get("protocolVersion"),
                "capabilities": sorted(result.get("capabilities", {})),
                "server_name": server_info.get("name"),
                "server_version": server_info.get("version"),
                "tools": tools,
                "required_tools": ["kb_history_get", "kb_search"],
                "required_tools_present": {"kb_search", "kb_history_get"}.issubset(
                    tools
                ),
                "owner_handshake_fields_exposed": sorted(
                    key for key in OWNER_HANDSHAKE_FIELDS if key in handshake
                ),
                "owner_handshake_fields_required": sorted(OWNER_HANDSHAKE_FIELDS),
                # Values, not just names: a drifted owner version is visible.
                "owner_handshake_matches_owner_versions": handshake
                == expected_handshake,
            }
        )

        first = _payload(probe.tool("kb_search", {"query": WIRE_QUERY, "limit": 1}))
        second = _payload(probe.tool("kb_search", {"query": WIRE_QUERY, "limit": 1}))
        receipts = (first or {}).get("receipts") or []
        principal = receipts[0].get("principal", {}) if receipts else {}
        facts["current"] = {
            "payload_keys": sorted(first or {}),
            "result_keys": (
                sorted((first or {}).get("results", [{}])[0])
                if (first or {}).get("results")
                else []
            ),
            "receipt_keys": sorted(receipts[0]) if receipts else [],
            "receipt_count": (first or {}).get("receipt_count"),
            "principal_is_mapped_principal_id": principal.get("id")
            == mapping.principal_id,
            "principal_type_is_mapped_type": principal.get("type")
            == contracts.PrincipalType.AI_EMPLOYEE.value,
            "principal_is_configured_owner": principal.get("id") == WIRE_OWNER,
            "receipt_binds_mapping": bool(receipts)
            and receipts[0].get("mapping_version") == contracts.OWNER_MAPPING_VERSION
            and receipts[0].get("mapping_hash") == mapping.mapping_hash,
            "repeat_query_returns_new_receipt": bool(receipts)
            and bool((second or {}).get("receipts"))
            and receipts[0].get("id") != (second or {}).get("receipts")[0].get("id"),
            "additive_receipt_keys_outside_consumer_allowlist": sorted(
                (set(receipts[0]) if receipts else set())
                - LEGACY_RECEIPT_KEYS
                - CONSUMER_RECEIPT_KEYS
            ),
        }

        history_reply = probe.tool("kb_history_get", dict(history))
        history_payload = _payload(history_reply)
        receipt = (history_payload or {}).get("receipt") or {}
        listed_receipts = (history_payload or {}).get("receipts") or []
        facts["history"] = {
            "payload_keys": sorted(history_payload or {}),
            "knowledge_state": (history_payload or {}).get("knowledge_state"),
            "freshness_state": (history_payload or {}).get("freshness_state"),
            "body_released": (history_payload or {}).get("body") is not None,
            "receipt_present": bool(receipt),
            "receipt_keys": sorted(receipt),
            "receipt_missing_required": [
                name
                for name in REQUIRED_HISTORY_WIRE_RECEIPT_FIELDS
                if receipt.get(name) in (None, "")
            ],
            "listed_receipt_keys_outside_consumer_allowlist": sorted(
                key
                for entry in listed_receipts
                if isinstance(entry, dict)
                for key in entry
                if key not in CONSUMER_RECEIPT_KEYS
            ),
            "is_error": bool(history_reply.get("result", {}).get("isError")),
            "release_capable": (history_payload or {}).get("knowledge_state")
            == "known",
        }

        # One denial per basis the release depends on; all must be identical.
        denied = [
            _payload(probe.tool("kb_history_get", dict(history, **override)))
            for override in (
                {"classification": "confidential"},
                {"path": "docs/other.md"},
                {"commit": PROBE_OTHER_COMMIT},
                {"repository": "unlisted"},
            )
        ]
        facts["history"]["denied_states"] = sorted(
            {(answer or {}).get("knowledge_state") for answer in denied}
        )
        facts["history"]["denials_release_no_body"] = all(
            (answer or {}).get("body") is None and (answer or {}).get("receipt") is None
            for answer in denied
        )
        facts["history"]["denials_are_indistinguishable"] = (
            len({_canonical_json(answer) for answer in denied}) == 1
        )

        rejected = probe.tool("kb_history_get", dict(history, principal="someone-else"))
        facts["history"]["identity_argument_rejected"] = (
            rejected.get("error", {}).get("code") == mcp.INVALID_PARAMS
        )
        facts["probe_ok"] = True
        facts["probe_error"] = None
    except Exception as error:  # noqa: BLE001 - the probe result is evidence
        facts["probe_ok"] = False
        facts["probe_error"] = type(error).__name__
    finally:
        facts["exit_code"] = probe.close()
    return facts


# --------------------------------------------------------------------------- #
# no-write proof (source corpus is byte-identical across a full cycle)
# --------------------------------------------------------------------------- #
def _snapshot(root: Path) -> tuple[int, str]:
    entries = [
        f"{path.relative_to(root).as_posix()}:"
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in sorted(path for path in root.rglob("*") if path.is_file())
    ]
    return len(entries), _sha256_text("\n".join(entries))


def _history_repository(root: Path) -> tuple[Path, str]:
    """One real commit, so the frozen route can be probed against real history."""
    worktree = root / "history"
    (worktree / "docs").mkdir(parents=True)
    (worktree / "docs" / "fact.md").write_text(WIRE_HISTORY_BODY, encoding="utf-8")
    (worktree / "docs" / "other.md").write_text("unreleased\n", encoding="utf-8")
    identity = ("-c", "user.name=probe", "-c", "user.email=probe@example.invalid")

    def git(*arguments: str) -> str:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *arguments],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return completed.stdout.strip()

    git("init", "-q", "-b", "main", str(worktree))
    git("-C", str(worktree), *identity, "add", "docs")
    git("-C", str(worktree), *identity, "commit", "-q", "-m", "release")
    return worktree, git("-C", str(worktree), "rev-parse", "HEAD")


def _build_workspace(root: Path) -> tuple[Path, Path, dict[str, str]]:
    """Corpus, history repository and the owner-gateway configuration for both."""
    corpus = root / "notes"
    corpus.mkdir(parents=True)
    (corpus / "fact.md").write_text(
        "# Governed\n\nThe governed retrieval path attaches receipts.\n",
        encoding="utf-8",
    )
    (corpus / "second.md").write_text(
        "# Receipts\n\nEvery released chunk carries a receipt.\n", encoding="utf-8"
    )
    worktree, commit = _history_repository(root)
    mapped_principal = contracts.OwnerIdentityMapping().principal_id
    config = root / "config.toml"
    config.write_text(
        f"""schema = 1
owner = "{WIRE_OWNER}"

[roots.notes]
path = "{corpus.as_posix()}"
owner = "{mapped_principal}"
include = ["*.md"]
authority = "derived"
trust = "curated"
visibility = "private"
project = "default"

[owner_gateway]
project = "default"

[owner_gateway.mapping]
authenticated_principal = "lee"
principal_id = "{mapped_principal}"

[[owner_gateway.mapping.grants]]
project = "default"
source_namespace = "local_files"
root = "notes"
path_prefix = "{contracts.WHOLE_ROOT_PATH_PREFIX}"

[owner_gateway.historical_release]
version = "{contracts.OWNER_HISTORICAL_VERSION}"

[[owner_gateway.historical_release.rules]]
repository = "{WIRE_HISTORY_REPOSITORY}"
commit = "{commit}"
path = "docs/fact.md"
classification = "public"
principals = ["{mapped_principal}"]
projects = ["default"]
source_namespace = "local_files"
root = "notes"

[owner_gateway.repositories]
{WIRE_HISTORY_REPOSITORY} = "{worktree.as_posix()}"
""",
        encoding="utf-8",
    )
    return (
        config,
        corpus,
        {
            "repository": WIRE_HISTORY_REPOSITORY,
            "commit": commit,
            "path": "docs/fact.md",
            "classification": "public",
        },
    )


def _owner_history_cycle() -> dict[str, Any]:
    """Exercise the supported owner history seam through OwnerGateway."""
    locator = _probe_locator()
    mapping = contracts.OwnerIdentityMapping.default((_probe_grant(),))
    manifest = contracts.HistoricalReleaseManifest.from_rules(
        (
            contracts.HistoricalReleaseRule(
                "lee@leebase.com",
                "default",
                locator,
                "public",
                _probe_basis("history", "allow"),
            ),
        )
    )
    gateway = owner.OwnerGateway(
        repository=None,
        mapping=mapping,
        manifest=manifest,
        current_permission=lambda *_: _probe_basis("current", "allow"),
        resolver=lambda _: _probe_object(locator),
        clock=lambda: PROBE_NOW,
    )
    result = gateway.retrieve_history(
        authenticated_principal="lee",
        locator=locator,
        classification="public",
        source_namespace="local_files",
        root="notes",
        item_id="local_files:docs/fact.md",
    )
    return {
        "seam": "owner.OwnerGateway.retrieve_history",
        "knowledge_state": result.knowledge_state.value,
        "receipt_bound": result.receipt is not None,
    }


def _no_write_proof(
    root: Path, config: Path, corpus: Path, history_locator: dict[str, str]
) -> dict[str, Any]:
    before_count, before_digest = _snapshot(corpus)
    steps: list[dict[str, Any]] = []
    env = _child_env(config)

    sync = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "lee_kb.main", "sync"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    steps.append(
        {
            "step": "cli_sync",
            "argv": ["python3", "-m", "lee_kb.main", "sync"],
            "returncode": sync.returncode,
        }
    )
    search = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "lee_kb.main",
            "search",
            WIRE_QUERY,
            "--project",
            "default",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    steps.append(
        {
            "step": "cli_search",
            "argv": [
                "python3",
                "-m",
                "lee_kb.main",
                "search",
                "<query>",
                "--project",
                "default",
            ],
            "returncode": search.returncode,
        }
    )
    # The handshake is compared against the mapping this deployment configures,
    # so an owner-side version or grant change shows up as drift, not silence.
    configured = owner.load_owner_gateway(tomllib.loads(config.read_text("utf-8")))
    wire = _wire_probe(config, configured.mapping, history_locator)
    steps.append(
        {
            "step": "mcp_stdio_probe",
            "argv": wire["probe_argv"],
            "returncode": wire.get("exit_code"),
        }
    )
    history = _owner_history_cycle()
    steps.append(
        {
            "step": "owner_retrieve_history",
            "argv": ["<in-process>", history["seam"]],
            "returncode": 0 if history["knowledge_state"] == "known" else 1,
        }
    )

    after_count, after_digest = _snapshot(corpus)
    database = root / "knowledge.sqlite"
    persisted_receipts = None
    if database.exists():
        try:
            with SQLiteRepository(database) as repository:
                persisted_receipts = len(repository.list_receipts())
        except Exception:  # noqa: BLE001 - evidence, not control flow
            persisted_receipts = None
    return {
        "proof": {
            "corpus_file_count": before_count,
            "corpus_unchanged": before_count == after_count
            and before_digest == after_digest,
            "digest_algorithm": "sha256 over sorted 'relative-name:sha256' lines",
            "corpus_digest_stable": before_digest == after_digest,
            "corpus_digest": before_digest,
        },
        "cycle_steps": steps,
        "persisted_current_receipts": persisted_receipts,
        "owner_history": history,
        "wire": wire,
    }


# --------------------------------------------------------------------------- #
# focused test runs and mutation probes
# --------------------------------------------------------------------------- #
def _focused_test(
    test_id: str, replacements: tuple[tuple[str, str], ...]
) -> dict[str, Any]:
    record = _run(
        ["python3", "-m", "pytest", test_id, "-q"],
        cwd=REPO_ROOT,
        env=_repo_env(),
        replacements=replacements,
    )
    return {"test_id": test_id, "returncode": record["returncode"]}


_FIXTURE = """
from datetime import datetime, timedelta, timezone
from lee_kb.contracts import (
    HistoricalLocator,
    HistoricalReleaseManifest,
    HistoricalReleaseRule,
    ImmutableHistoricalObject,
    OwnerIdentityMapping,
    PolicyBasis,
    SourceGrant,
    compute_content_hash,
)
from lee_kb.governance import ExactHistoricalReader

NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)
GRANT = SourceGrant("default", "local_files", "notes", "docs")
MAPPING = OwnerIdentityMapping.default((GRANT,))
COMMIT = "0123456789abcdef0123456789abcdef01234567"
LOCATOR = HistoricalLocator("kb", COMMIT, "docs/fact.md")


def basis(name, decision):
    return PolicyBasis(
        name + "/v1",
        compute_content_hash(name),
        decision,
        NOW - timedelta(minutes=1),
        NOW + timedelta(hours=1),
    )


def manifest(classification="public", locator=LOCATOR):
    return HistoricalReleaseManifest.from_rules(
        (
            HistoricalReleaseRule(
                "lee@leebase.com",
                "default",
                locator,
                classification,
                basis("history", "allow"),
            ),
        )
    )


def reader(current="allow"):
    body = "immutable probe body"
    return ExactHistoricalReader(
        mapping=MAPPING,
        manifest=manifest(),
        current_permission=lambda *_: basis("current", current),
        resolver=lambda _: ImmutableHistoricalObject(
            LOCATOR, body, compute_content_hash(body), NOW, "public"
        ),
        clock=lambda: NOW,
    )
"""


@dataclasses.dataclass(frozen=True, slots=True)
class _Mutation:
    """One semantic break of an owner rule, plus proof that it took effect.

    ``patch`` is appended to a private copy of the module, so it survives any
    refactor of the implementation's internal lines.  ``verify`` must exit zero
    only when the rule really is broken; otherwise the probe is reported as
    ineffective instead of silently accusing the test suite.
    """

    name: str
    module: str
    patch: str
    verify: str


MUTATIONS: tuple[_Mutation, ...] = (
    _Mutation(
        "mapping_admits_any_authenticated_principal",
        "contracts.py",
        """

_s1c_resolve = OwnerIdentityMapping.resolve


def _s1c_mutated_resolve(self, authenticated_principal, *, project=None):
    return _s1c_resolve(self, self.authenticated_principal, project=project)


OwnerIdentityMapping.resolve = _s1c_mutated_resolve
""",
        "assert MAPPING.resolve('mallory').principal_id == 'lee@leebase.com'",
    ),
    _Mutation(
        "mapping_admits_ungranted_project",
        "contracts.py",
        """

_s1c_resolve_project = OwnerIdentityMapping.resolve


def _s1c_mutated_project_resolve(self, authenticated_principal, *, project=None):
    granted = {grant.project for grant in self.grants}
    identity = _s1c_resolve_project(
        self, authenticated_principal, project=project if project in granted else None
    )
    if project and project not in granted:
        identity = dataclasses.replace(identity, project=project)
    return identity


OwnerIdentityMapping.resolve = _s1c_mutated_project_resolve
""",
        "assert MAPPING.resolve('lee', project='ungranted').project == 'ungranted'",
    ),
    _Mutation(
        "grant_ignores_path_prefix",
        "contracts.py",
        """

_s1c_grant_permits = SourceGrant.permits


def _s1c_mutated_grant_permits(self, *, project, source_namespace, root, path, item_id):
    return _s1c_grant_permits(
        self,
        project=project,
        source_namespace=source_namespace,
        root=root,
        path=self.path_prefix,
        item_id=item_id,
    )


SourceGrant.permits = _s1c_mutated_grant_permits
""",
        "assert MAPPING.permits(MAPPING.resolve('lee'), source_namespace='local_files',"
        " root='notes', path='secret/x.md', item_id=None)",
    ),
    _Mutation(
        "manifest_ignores_classification",
        "contracts.py",
        """

_s1c_covers_classification = HistoricalReleaseRule.covers


def _s1c_mutated_covers_classification(
    self, *, principal_id, project, locator, classification, at
):
    return _s1c_covers_classification(
        self,
        principal_id=principal_id,
        project=project,
        locator=locator,
        classification=self.classification,
        at=at,
    )


HistoricalReleaseRule.covers = _s1c_mutated_covers_classification
""",
        "assert manifest().evaluate(principal_id='lee@leebase.com', project='default',"
        " locator=LOCATOR, classification='confidential', at=NOW).decision == 'allow'",
    ),
    _Mutation(
        "manifest_ignores_locator",
        "contracts.py",
        """

_s1c_covers_locator = HistoricalReleaseRule.covers


def _s1c_mutated_covers_locator(
    self, *, principal_id, project, locator, classification, at
):
    return _s1c_covers_locator(
        self,
        principal_id=principal_id,
        project=project,
        locator=self.locator,
        classification=classification,
        at=at,
    )


HistoricalReleaseRule.covers = _s1c_mutated_covers_locator
""",
        "other = HistoricalLocator('kb', '1123456789abcdef0123456789abcdef01234567',"
        " 'docs/fact.md')\n"
        "assert manifest().evaluate(principal_id='lee@leebase.com', project='default',"
        " locator=other, classification='public', at=NOW).decision == 'allow'",
    ),
    _Mutation(
        "history_skips_current_permission_gate",
        "governance.py",
        """


def _s1c_mutated_evaluate_current(
    self, identity, locator, classification, evaluated_at
):
    return PolicyBasis(
        "current/v1",
        compute_content_hash("mutated-current"),
        "allow",
        evaluated_at - timedelta(minutes=1),
        evaluated_at + timedelta(hours=1),
    )


ExactHistoricalReader._evaluate_current = _s1c_mutated_evaluate_current
""",
        "result = reader(current='deny').lookup(authenticated_principal='lee',"
        " locator=LOCATOR, classification='public', source_namespace='local_files',"
        " root='notes', item_id=None)\n"
        "assert result.knowledge_state.value == 'known' and result.body is not None",
    ),
    _Mutation(
        "mapped_current_evaluator_always_permits",
        "owner.py",
        """


def _s1c_mutated_is_permitted(self, item, principal):
    return True


_MappedPermissionEvaluator.is_permitted = _s1c_mutated_is_permitted
""",
        "from lee_kb.owner import _MappedPermissionEvaluator\n"
        "from lee_kb.contracts import (\n"
        "    DocumentType,\n"
        "    KnowledgeItem,\n"
        "    KnowledgeItemId,\n"
        "    PermissionSet,\n"
        "    Principal,\n"
        "    SourceLocator,\n"
        ")\n"
        "item = KnowledgeItem(\n"
        "    item_id=KnowledgeItemId('local_files', 'secret/x.md'),\n"
        "    project='default',\n"
        "    source_locator=SourceLocator('local_files', 'file:///probe'),\n"
        "    document_type=DocumentType.MARKDOWN,\n"
        "    content_hash=compute_content_hash('probe'),\n"
        "    source_timestamp=NOW,\n"
        "    sync_timestamp=NOW,\n"
        "    permissions=PermissionSet('someone-else@example.invalid'),\n"
        ")\n"
        "evaluator = _MappedPermissionEvaluator(\n"
        "    MAPPING.resolve('lee'),\n"
        "    lambda _: ('local_files', 'notes', 'secret/x.md'),\n"
        ")\n"
        "assert evaluator.is_permitted(item, Principal('mallory@example.invalid'))",
    ),
)

_MUTATION_IMPORTS = {
    "contracts.py": "\nimport dataclasses\n",
    "governance.py": (
        "\nfrom datetime import timedelta\n"
        "from .contracts import PolicyBasis, compute_content_hash\n"
    ),
    "owner.py": "\n",
}


def _mutation_probes() -> list[dict[str, Any]]:
    """Ask the owner-native suite whether it actually defends each rule.

    Each mutation is appended to a private copy of the package, never to the
    working tree.  ``effective`` proves the rule is broken in that copy;
    ``detected`` means ``tests/test_owner.py`` then failed, which is the only
    evidence that an owner-native test defends the rule.
    """
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="s1c-mutation-") as raw_root:
        root = Path(raw_root)
        package = root / "src" / "lee_kb"
        shutil.copytree(SRC_ROOT / "lee_kb", package)
        (root / "tests").mkdir()
        shutil.copy2(
            REPO_ROOT / "tests" / "test_owner.py", root / "tests" / "test_owner.py"
        )
        pristine = {
            mutation.module: (package / mutation.module).read_text("utf-8")
            for mutation in MUTATIONS
        }
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("LEE_KB_CONFIG", None)
        suite = [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_owner.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]

        def run(argv: list[str]) -> int:
            return subprocess.run(  # noqa: S603 - fixed argv, no shell
                argv,
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            ).returncode

        baseline = run(suite)
        for mutation in MUTATIONS:
            target = package / mutation.module
            source = pristine[mutation.module]
            target.write_text(
                source + _MUTATION_IMPORTS[mutation.module] + mutation.patch,
                encoding="utf-8",
            )
            check = root / "verify.py"
            check.write_text(_FIXTURE + "\n" + mutation.verify + "\n", encoding="utf-8")
            effective = run([sys.executable, "verify.py"]) == 0
            returncode = run(suite) if effective else None
            target.write_text(source, encoding="utf-8")
            check.unlink()
            results.append(
                {
                    "mutation": mutation.name,
                    "file": f"src/lee_kb/{mutation.module}",
                    "applied": effective,
                    "effective": effective,
                    "suite": "tests/test_owner.py",
                    "suite_returncode": returncode,
                    "detected": bool(effective and returncode not in (None, 0)),
                }
            )
    return [
        {
            "mutation": "baseline",
            "file": None,
            "applied": True,
            "effective": True,
            "suite": "tests/test_owner.py",
            "suite_returncode": baseline,
            "detected": baseline == 0,
        },
        *results,
    ]


# --------------------------------------------------------------------------- #
# permission matrices
# --------------------------------------------------------------------------- #
_T_MAPPING = (
    "tests/test_owner.py::"
    "test_mapping_is_server_owned_and_client_identity_cannot_widen"
)
_T_BASES = (
    "tests/test_owner.py::" "test_history_requires_current_and_historical_policy_bases"
)
_T_EXACT = (
    "tests/test_owner.py::" "test_exact_success_has_complete_receipt_and_immutable_hash"
)
_T_MANIFEST = (
    "tests/test_owner.py::"
    "test_missing_manifest_and_mismatched_classification_release_no_body"
)
_T_SURFACE = "tests/test_mcp.py::" "test_tool_surface_matches_kb_index_contract"
_T_SEARCH = (
    "tests/test_mcp.py::" "test_kb_search_preserves_result_shape_and_attaches_receipts"
)
_OWNER = "tests/test_owner.py::"
_T_PROJECT = _OWNER + "test_ungranted_project_is_rejected_before_retrieval"
_T_SCOPE = _OWNER + "test_grants_narrow_namespace_root_path_and_item"
_T_MULTI = _OWNER + "test_multi_project_requires_one_explicit_granted_project"
_T_CURRENT = _OWNER + "test_current_release_requires_the_mapped_permission"
_T_LOCATOR = _OWNER + "test_exact_locator_rejects_patterns_traversal_and_refs"
_T_MISMATCH = _OWNER + "test_locator_outside_the_manifest_releases_no_body"
_T_AMBIGUOUS = _OWNER + "test_ambiguous_manifest_rules_release_no_body"
_T_EXPIRED = _OWNER + "test_expired_manifest_releases_no_body"
_T_STALE = _OWNER + "test_stale_historical_basis_releases_no_body"
_T_RESOLVER = _OWNER + "test_absent_resolver_releases_no_body"
_T_WIDENED = _OWNER + "test_widened_path_is_denied_before_the_object_seam"
_T_UNMAPPED = _OWNER + "test_unmapped_principal_is_denied_before_the_object_seam"
_T_HANDSHAKE = _OWNER + "test_owner_handshake_names_every_version"
_T_GIT = _OWNER + "test_git_exact_object_resolver_reads_exactly_one_named_object"
_T_WIRE_HANDSHAKE = (
    "tests/test_mcp.py::"
    "test_initialize_publishes_the_owner_handshake_in_owner_gateway_mode"
)
_T_WIRE_IDENTITY = (
    "tests/test_mcp.py::"
    "test_owner_gateway_search_identity_comes_from_the_server_mapping"
)
_T_WIRE_HISTORY = (
    "tests/test_mcp.py::"
    "test_owner_gateway_releases_one_exact_history_object_with_its_receipt"
)
_T_WIRE_DENIAL = (
    "tests/test_mcp.py::"
    "test_owner_gateway_history_denials_are_identical_and_release_no_body"
)


@dataclasses.dataclass(frozen=True, slots=True)
class _Case:
    """One permission-matrix case and the evidence its contract row demands.

    ``evidence`` is ``behavioural`` when a rule can regress silently and must
    therefore be defended by an owner-native test, or ``structural`` when the
    case asserts the shape of an API, a wire schema or a live route, for which
    this generator's own probe is the evidence.
    """

    case_id: str
    matrix: str
    expectation: str
    probe: str
    expected: str
    test_id: str | None = None
    mutation: str | None = None
    evidence: str = "behavioural"


CASES: tuple[_Case, ...] = (
    _Case(
        "current.mapped_principal_admitted",
        "current",
        "authenticated principal lee maps server-side to lee@leebase.com with no "
        "client groups",
        "current.mapped_principal_admitted",
        "lee->lee@leebase.com|ai_employee|groups=0",
        _T_MAPPING,
        "mapping_admits_any_authenticated_principal",
    ),
    _Case(
        "current.unmapped_principal_denied",
        "current",
        "any principal other than the mapped one is denied without enumeration",
        "current.unmapped_principal_denied",
        "PermissionError",
        _T_MAPPING,
        "mapping_admits_any_authenticated_principal",
    ),
    _Case(
        "current.client_cannot_send_identity_fields",
        "current",
        "no wire argument can carry principal, groups, grants or scope; every tool "
        "schema is closed",
        "current.client_cannot_send_identity_fields",
        "identity_fields=none|closed_schemas=True",
        _T_SURFACE,
    ),
    _Case(
        "current.widened_project_rejected",
        "current",
        "a request cannot select a project that is not explicitly granted",
        "current.widened_project_rejected",
        "PermissionError",
        _T_PROJECT,
        "mapping_admits_ungranted_project",
    ),
    _Case(
        "current.widened_scope_rejected",
        "current",
        "source namespace, root, path and item outside the server grant are refused",
        "current.widened_scope_rejected",
        "granted=True|denied=item,namespace,path,root",
        _T_SCOPE,
        "grant_ignores_path_prefix",
    ),
    _Case(
        "current.multi_project_requires_explicit_grant",
        "current",
        "multi-project mapping needs an explicit project and yields per-project grants",
        "current.multi_project_requires_explicit_grant",
        "implicit=PermissionError|projects=default,second|grants=1,1",
        _T_MULTI,
        "mapping_admits_ungranted_project",
    ),
    _Case(
        "current.mapped_permission_required_for_release",
        "current",
        "current release requires the mapped principal plus the granted "
        "source, root, path, and item",
        "current.mapped_permission_required_for_release",
        "in_grant=True|out_of_grant=False|out_of_root=False|other_principal=False",
        _T_CURRENT,
        "mapped_current_evaluator_always_permits",
    ),
    _Case(
        "current.public_release_entry_point",
        "current",
        "the owner slice exposes a supported current-release entry point the adapter "
        "can call",
        "current.public_release_entry_point",
        "public_current_release=retrieve_current",
        _T_CURRENT,
        None,
        "structural",
    ),
    _Case(
        "current.owner_handshake_complete",
        "current",
        "the owner slice publishes every version, the mapping hash, and the "
        "permission and receipt versions the consumer compares",
        "current.owner_handshake",
        "fields=api_version,contract_version,corpus_version,historical_version,"
        "mapping_hash,mapping_version,owner,permission_version,receipt_version,"
        "schema_version|mapping_hash_bound=True",
        _T_HANDSHAKE,
    ),
    _Case(
        "history.exact_locator_only",
        "history",
        "only an exact (repository, commit, path) locator is accepted; patterns and "
        "refs are refused",
        "history.exact_locator_only",
        "rejected=pattern,traversal,absolute,short-commit,branch-ref",
        _T_LOCATOR,
    ),
    _Case(
        "history.single_locator_argument",
        "history",
        "exactly one governed locator per call, with a closed wire schema",
        "history.single_locator_argument",
        "wire_required=classification,commit,path,repository|wire_closed=True"
        "|seam_locator_param=True|seam_multi_locator_params=none",
        None,
        None,
        "structural",
    ),
    _Case(
        "history.authorized_release",
        "history",
        "a doubly authorized exact locator releases the immutable body with a receipt",
        "history.authorized_release",
        "known|body|receipt|no-reason",
        _T_EXACT,
    ),
    _Case(
        "history.receipt_binds_release_basis",
        "history",
        "the exact-history receipt binds bases, versions, hashes, locator, blob "
        "hash/time, evaluation time and audit id",
        "history.receipt_binds_release_basis",
        "audit=True|manifest_hash=True|blob=True|blob_time=True|eval_time=True"
        "|current=allow|history=allow|locator=True|freshness=fresh",
        _T_EXACT,
    ),
    _Case(
        "history.manifest_required",
        "history",
        "no versioned historical-release manifest means non-enumerating UNKNOWN and no "
        "body",
        "history.manifest_required",
        "unknown|no-body|receipt|no-reason",
        _T_MANIFEST,
    ),
    _Case(
        "history.classification_mismatch",
        "history",
        "a classification the manifest does not cover returns UNKNOWN and no body",
        "history.classification_mismatch",
        "unknown|no-body|receipt|no-reason",
        _T_MANIFEST,
        "manifest_ignores_classification",
    ),
    _Case(
        "history.locator_mismatch",
        "history",
        "a locator the manifest does not cover returns UNKNOWN and no body",
        "history.locator_mismatch",
        "unknown|no-body|receipt|no-reason",
        _T_MISMATCH,
        "manifest_ignores_locator",
    ),
    _Case(
        "history.ambiguous_manifest_rules",
        "history",
        "ambiguous manifest coverage fails closed to UNKNOWN",
        "history.ambiguous_manifest_rules",
        "unknown|no-body|receipt|no-reason",
        _T_AMBIGUOUS,
    ),
    _Case(
        "history.expired_manifest",
        "history",
        "an expired manifest fails closed to UNKNOWN",
        "history.expired_manifest",
        "unknown|no-body|receipt|no-reason",
        _T_EXPIRED,
    ),
    _Case(
        "history.stale_historical_basis",
        "history",
        "a stale historical basis fails closed to UNKNOWN",
        "history.stale_historical_basis",
        "unknown|no-body|receipt|no-reason",
        _T_STALE,
    ),
    _Case(
        "history.denied_historical_basis",
        "history",
        "a denied historical basis returns the unauthorized state with no body",
        "history.denied_historical_basis",
        "unauthorized|no-body|receipt|no-reason",
        _T_BASES,
    ),
    _Case(
        "history.current_permission_required",
        "history",
        "current permission is required for history and the body seam is never touched "
        "without it",
        "history.current_permission_required",
        "deny=unknown|no-body|receipt|no-reason"
        "|absent=unknown|no-body|receipt|no-reason|resolver_calls=0",
        _T_BASES,
        "history_skips_current_permission_gate",
    ),
    _Case(
        "history.no_resolver_no_body",
        "history",
        "repository reachability cannot substitute: without the exact-object seam "
        "there is no body",
        "history.no_resolver_no_body",
        "unknown|no-body|receipt|no-reason",
        _T_RESOLVER,
    ),
    _Case(
        "history.exact_object_seam_bounded",
        "history",
        "the supported exact-object seam reads one allowlisted named object and "
        "refuses everything else",
        "history.exact_object_seam_bounded",
        "released=True|unlisted=True|unknown_commit=True|oversized=True"
        "|unclassified=True",
        _T_GIT,
    ),
    _Case(
        "history.widened_path_denied",
        "history",
        "a locator path outside the server grant is unauthorized before the body seam",
        "history.widened_path_denied",
        "unauthorized|no-body|receipt|no-reason|resolver_calls=0",
        _T_WIDENED,
        "grant_ignores_path_prefix",
    ),
    _Case(
        "history.unmapped_principal_denied",
        "history",
        "an unmapped principal gets UNKNOWN with no receipt and no body seam call",
        "history.unmapped_principal_denied",
        "unknown|no-body|no-receipt|no-reason|resolver_calls=0",
        _T_UNMAPPED,
        "mapping_admits_any_authenticated_principal",
    ),
    _Case(
        "history.no_body_on_failure",
        "history",
        "a non-KNOWN result cannot structurally carry a body",
        "history.no_body_on_failure",
        "body-structurally-blocked",
        _T_MANIFEST,
    ),
    _Case(
        "history.seam_has_no_search_or_timeout",
        "history",
        "the history seam has no search or cache input; timeout/cancel are not "
        "owner-side concerns",
        "history.seam_has_no_search_or_timeout",
        "init=clock,current_permission,manifest,mapping,resolver"
        "|timeout_or_cancel=none",
        None,
        None,
        "structural",
    ),
    _Case(
        "history.no_history_search_or_cache_surface",
        "history",
        "no historical search or cache tool exists beside the exact-reference tool",
        "history.no_history_search_or_cache_surface",
        "extra_history_tools=none",
        _T_SURFACE,
    ),
    _Case(
        "history.wire_release_capable",
        "history",
        "the frozen stdio route releases an authorized exact-history body with a "
        "complete receipt",
        "wire.history_release_capable",
        "release_capable=True|receipt=True|receipt_complete=True",
        _T_WIRE_HISTORY,
        None,
        "structural",
    ),
    _Case(
        "history.wire_denials_are_non_enumerating",
        "history",
        "every withheld basis answers identically over the frozen route, with no "
        "body and no receipt",
        "wire.history_denials",
        "states=unknown|no_body=True|identical=True",
        _T_WIRE_DENIAL,
        None,
        "structural",
    ),
    _Case(
        "history.wire_rejects_identity_arguments",
        "history",
        "the frozen stdio route rejects any extra client argument, so transport cannot "
        "confer identity",
        "wire.history_identity_argument",
        "extra_identity_argument_rejected=True",
        None,
        None,
        "structural",
    ),
    _Case(
        "current.wire_identity_is_mapped",
        "current",
        "the frozen stdio route derives identity from the server mapping, not from "
        "configuration",
        "wire.current_identity",
        "mapped_principal=True|mapped_type=True|binds_mapping=True"
        "|configured_owner=False",
        _T_WIRE_IDENTITY,
        None,
        "structural",
    ),
    _Case(
        "current.wire_owner_handshake",
        "current",
        "initialize publishes the owner handshake, so the frozen route can see "
        "owner-side version drift",
        "wire.owner_handshake",
        "fields=api_version,contract_version,corpus_version,historical_version,"
        "mapping_hash,mapping_version,owner,permission_version,receipt_version,"
        "schema_version|matches_owner_versions=True",
        _T_WIRE_HANDSHAKE,
        None,
        "structural",
    ),
    _Case(
        "current.wire_repeated_query_rereads",
        "current",
        "a repeated current query re-reads lee-kb and produces a new receipt",
        "wire.repeat_receipt",
        "new_receipt=True",
        _T_SEARCH,
    ),
)


def _matrices(
    observed: dict[str, str],
    tests: dict[str, dict[str, Any]],
    mutations: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    matrices: dict[str, list[dict[str, Any]]] = {"current": [], "history": []}
    for case in CASES:
        seen = observed.get(case.probe)
        reasons: list[str] = []
        if seen is None:
            reasons.append("behaviour probe produced no observation")
        elif seen != case.expected:
            reasons.append(
                f"behaviour probe '{case.probe}' observed '{seen}', "
                f"contract requires '{case.expected}'"
            )
        test = tests.get(case.test_id) if case.test_id else None
        if case.test_id is None and case.evidence != "structural":
            reasons.append("no owner-native test names this case")
        elif case.test_id is not None and test is None:
            reasons.append(f"focused test {case.test_id} was not run")
        elif test is not None and test["returncode"] != 0:
            reasons.append(f"focused test {case.test_id} returned {test['returncode']}")
        mutation = mutations.get(case.mutation) if case.mutation else None
        if case.mutation is not None:
            if mutation is None or not mutation["applied"]:
                reasons.append(
                    f"mutation probe {case.mutation} was ineffective on a copy of the "
                    "package, so test defence of this rule is unproven"
                )
            elif not mutation["detected"]:
                reasons.append(
                    f"tests/test_owner.py still passes with {case.mutation} applied, "
                    "so no owner-native test defends this rule"
                )
        matrices[case.matrix].append(
            {
                "case_id": case.case_id,
                "expectation": case.expectation,
                "outcome": "satisfied" if not reasons else "unsatisfied",
                "observed": seen,
                "expected": case.expected,
                "evidence": case.evidence,
                "test_id": case.test_id,
                "test_returncode": None if test is None else test["returncode"],
                "mutation": case.mutation,
                "mutation_detected": None if mutation is None else mutation["detected"],
                "reasons": reasons,
            }
        )
    return matrices


# --------------------------------------------------------------------------- #
# frozen contract rows
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True, slots=True)
class _Row:
    row_id: str
    source: str
    requirement: str
    cases: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()


ROWS: tuple[_Row, ...] = (
    _Row(
        "D1.owner_native_tests",
        "Deliver 1",
        "owner-native tests complete before the Core adapter",
        checks=(
            "tests_test_owner_passes",
            "tests_test_mcp_passes",
            "owner_module_compiles",
        ),
    ),
    _Row(
        "D1.handshake_complete",
        "Deliver 1",
        "version/schema/corpus/identity/permission handshake complete before the Core "
        "adapter",
        cases=(
            "current.owner_handshake_complete",
            "current.wire_owner_handshake",
        ),
        checks=("wire_required_tools_present", "wire_owner_handshake_exposed"),
    ),
    _Row(
        "D1.field_receipt_freshness_parity",
        "Deliver 1",
        "field/receipt/freshness/recovery parity for current and exact history",
        cases=("history.wire_release_capable",),
        checks=(
            "history_receipt_complete",
            "current_receipt_complete",
            "wire_receipt_keys_within_consumer_allowlist",
        ),
    ),
    _Row(
        "D2.immutable_server_mapping",
        "Deliver 2",
        "exact immutable server-side mapping of Core principal lee to lee-kb "
        "lee@leebase.com",
        cases=(
            "current.mapped_principal_admitted",
            "current.unmapped_principal_denied",
        ),
        checks=("mapping_hash_matches_consumer_algorithm",),
    ),
    _Row(
        "D2.clients_cannot_send_identity",
        "Deliver 2",
        "clients and delegates cannot send principal or groups",
        cases=(
            "current.client_cannot_send_identity_fields",
            "history.wire_rejects_identity_arguments",
        ),
    ),
    _Row(
        "D2.clients_cannot_widen_scope",
        "Deliver 2",
        "clients cannot widen project, source, root, path or item, or broaden filters",
        cases=("current.widened_project_rejected", "current.widened_scope_rejected"),
    ),
    _Row(
        "D2.multi_project_requires_grant",
        "Deliver 2",
        "multi-project access requires an explicit grant and separate receipts",
        cases=("current.multi_project_requires_explicit_grant",),
    ),
    _Row(
        "D2.wire_identity_is_server_derived",
        "Deliver 2",
        "the frozen route derives identity from the server mapping only",
        cases=("current.wire_identity_is_mapped",),
    ),
    _Row(
        "D3.current_requires_mapped_permission",
        "Deliver 3",
        "current release requires the mapped current "
        "principal, project, source, root, path, item permission",
        cases=(
            "current.mapped_permission_required_for_release",
            "current.public_release_entry_point",
        ),
    ),
    _Row(
        "D3.history_single_governed_locator",
        "Deliver 3",
        "exact history accepts only one governed (repository, commit, path) locator",
        cases=("history.exact_locator_only", "history.single_locator_argument"),
    ),
    _Row(
        "D3.history_requires_versioned_manifest",
        "Deliver 3",
        "exact history additionally requires a versioned historical-release manifest "
        "covering principal/project, exact locator and classification",
        cases=(
            "history.manifest_required",
            "history.classification_mismatch",
            "history.locator_mismatch",
            "history.ambiguous_manifest_rules",
            "history.expired_manifest",
        ),
    ),
    _Row(
        "D3.no_substitution_for_manifest",
        "Deliver 3",
        "current visibility, repository reachability, a current receipt or semantic "
        "match cannot substitute",
        cases=(
            "history.current_permission_required",
            "history.no_resolver_no_body",
            "history.exact_object_seam_bounded",
            "history.no_history_search_or_cache_surface",
        ),
    ),
    _Row(
        "D4.receipt_binds_everything",
        "Deliver 4",
        "exact-history receipts bind bases/versions/hashes, decisions, mapped "
        "identity/scope, locator, classification, blob hash/time, evaluation time and "
        "audit id",
        cases=("history.authorized_release", "history.receipt_binds_release_basis"),
        checks=("history_receipt_complete",),
    ),
    _Row(
        "D4.non_enumerating_failure_states",
        "Deliver 4",
        "missing, ambiguous, drifted, stale, denied or mismatched bases return "
        "non-enumerating UNKNOWN/unauthorized before body release",
        cases=(
            "history.manifest_required",
            "history.classification_mismatch",
            "history.locator_mismatch",
            "history.ambiguous_manifest_rules",
            "history.expired_manifest",
            "history.stale_historical_basis",
            "history.denied_historical_basis",
            "history.unmapped_principal_denied",
            "history.no_body_on_failure",
            "history.wire_denials_are_non_enumerating",
        ),
    ),
    _Row(
        "D5.frozen_candidate_full_contract",
        "Deliver 5",
        "the frozen persistent-MCP candidate satisfies the full identity/mapping, "
        "receipt and exact-history contract on the wire",
        cases=(
            "current.wire_identity_is_mapped",
            "current.wire_owner_handshake",
            "history.wire_release_capable",
            "history.wire_denials_are_non_enumerating",
            "current.wire_repeated_query_rereads",
        ),
        checks=(
            "wire_required_tools_present",
            "wire_history_release_capable",
            "wire_identity_is_mapped",
            "wire_receipt_keys_within_consumer_allowlist",
        ),
    ),
    _Row(
        "D7.artifact_fields",
        "Deliver 7",
        "content-free artifact names owner repository/version, commands, "
        "schema/corpus/identity, matrices, receipt fields, no-write result, adapter "
        "candidates and final handshake",
        checks=("artifact_sections_present", "artifact_is_content_free"),
    ),
    _Row(
        "A1.owner_artifact_validates",
        "Acceptance 1",
        "owner artifact validates independently and owner-native tests pass",
        checks=(
            "tests_test_owner_passes",
            "tests_test_mcp_passes",
            "artifact_sections_present",
        ),
    ),
    _Row(
        "A2.denial_before_body",
        "Acceptance 2",
        "permission denial occurs before evidence/body work and produces the safe "
        "non-enumerating state",
        cases=(
            "history.current_permission_required",
            "history.widened_path_denied",
            "history.unmapped_principal_denied",
            "history.wire_denials_are_non_enumerating",
        ),
    ),
    _Row(
        "A3.receipts_map_losslessly_or_fail_closed",
        "Acceptance 3",
        "current/history, time, freshness, role/basis and exact-reference receipts map "
        "losslessly or fail closed",
        checks=(
            "history_receipt_complete",
            "current_receipt_complete",
            "wire_receipt_keys_within_consumer_allowlist",
        ),
    ),
    _Row(
        "A4.deterministic_recovery_cases",
        "Acceptance 4",
        "REC-08 crash/version/schema/corpus/timeout/cancel cases behave "
        "deterministically",
        cases=("history.seam_has_no_search_or_timeout",),
        checks=("owner_seam_recovery_surface",),
    ),
    _Row(
        "A5.repeated_queries_reread",
        "Acceptance 5",
        "repeated current queries re-read lee-kb; an older observation cannot satisfy "
        "them",
        cases=("current.wire_repeated_query_rereads",),
        checks=("current_receipts_persisted_per_call",),
    ),
    _Row(
        "A6.one_route_no_fallback",
        "Acceptance 6",
        "one production route is live; direct-store fallback, dual-route code and "
        "historical search/cache are absent",
        cases=("history.no_history_search_or_cache_surface",),
        checks=("no_write_holds",),
    ),
)


def _checks(
    commands: dict[str, dict[str, Any]],
    receipts: dict[str, Any],
    identity: dict[str, Any],
    no_write: dict[str, Any],
    observed: dict[str, str],
) -> dict[str, dict[str, Any]]:
    wire = no_write["wire"]
    current_wire = wire.get("current", {})
    history_wire = wire.get("history", {})
    missing_history = receipts["historical_receipt_missing_required"]
    missing_current = receipts["current_retrieval_receipt_missing_required"]
    missing_history_wire = history_wire.get("receipt_missing_required")
    outside_allowlist = sorted(
        set(history_wire.get("listed_receipt_keys_outside_consumer_allowlist") or [])
        | set(
            current_wire.get("additive_receipt_keys_outside_consumer_allowlist") or []
        )
    )
    handshake_exposed = wire.get("owner_handshake_fields_exposed") or []
    handshake_missing = [
        name for name in OWNER_HANDSHAKE_FIELDS if name not in handshake_exposed
    ]
    persisted = no_write.get("persisted_current_receipts")
    seam = observed.get("history.seam_has_no_search_or_timeout", "")
    return {
        "tests_test_owner_passes": {
            "value": commands["pytest_test_owner"]["returncode"] == 0,
            "detail": "python3 -m pytest tests/test_owner.py -q",
        },
        "tests_test_mcp_passes": {
            "value": commands["pytest_test_mcp"]["returncode"] == 0,
            "detail": "python3 -m pytest tests/test_mcp.py -q",
        },
        "owner_module_compiles": {
            "value": commands["compileall_owner"]["returncode"] == 0,
            "detail": "python3 -m compileall -q src/lee_kb/owner.py",
        },
        "wire_required_tools_present": {
            "value": bool(wire.get("required_tools_present"))
            and wire.get("protocol_version") == mcp.PROTOCOL_VERSION,
            "detail": "initialize + tools/list expose kb_search and kb_history_get",
        },
        "wire_owner_handshake_exposed": {
            "value": not handshake_missing
            and bool(wire.get("owner_handshake_matches_owner_versions")),
            "detail": (
                "initialize serverInfo.owner publishes every owner version and the "
                "mapping hash, so wire-side drift is detectable; missing fields: "
                f"{handshake_missing or 'none'}"
            ),
        },
        "history_receipt_complete": {
            "value": not missing_history,
            "detail": f"missing history receipt fields: {missing_history or 'none'}",
        },
        "current_receipt_complete": {
            "value": not missing_current,
            "detail": f"missing current receipt fields: {missing_current or 'none'}",
        },
        "mapping_hash_matches_consumer_algorithm": {
            "value": bool(identity["mapping_hash_matches_consumer_algorithm"]),
            "detail": (
                "owner mapping hash equals the consumer's canonical sha256 of the same "
                "body"
            ),
        },
        "no_write_holds": {
            "value": bool(no_write["proof"]["corpus_unchanged"]),
            "detail": (
                "source corpus digests identical across sync + retrieve + history"
            ),
        },
        "current_receipts_persisted_per_call": {
            "value": isinstance(persisted, int) and persisted >= 2,
            "detail": (
                "persisted current receipts after two identical wire queries: "
                f"{persisted}"
            ),
        },
        "owner_seam_recovery_surface": {
            "value": "timeout_or_cancel=none" in seam,
            "detail": (
                "the owner seams expose no timeout/cancel surface; REC-08 timeout, "
                "cancel "
                "and process recovery remain consumer-side and unproven in this "
                "repository"
            ),
        },
        "artifact_sections_present": {
            "value": True,
            "detail": "filled in after assembly",
        },
        "artifact_is_content_free": {
            "value": True,
            "detail": "filled in after assembly",
        },
        "wire_history_release_capable": {
            "value": bool(history_wire.get("release_capable"))
            and not missing_history_wire
            and bool(history_wire.get("denials_are_indistinguishable"))
            and bool(history_wire.get("denials_release_no_body")),
            "detail": (
                "kb_history_get releases one exact object with a complete receipt and "
                "answers every withheld basis identically; missing wire receipt "
                f"fields: {missing_history_wire if missing_history_wire else 'none'}"
            ),
        },
        "wire_receipt_keys_within_consumer_allowlist": {
            "value": not outside_allowlist,
            "detail": (
                "every additive receipt name the wire emits is normalized by the "
                f"consumer; outside the allowlist: {outside_allowlist or 'none'}"
            ),
        },
        "wire_identity_is_mapped": {
            "value": bool(current_wire.get("principal_is_mapped_principal_id"))
            and bool(current_wire.get("principal_type_is_mapped_type"))
            and bool(current_wire.get("receipt_binds_mapping"))
            and not current_wire.get("principal_is_configured_owner"),
            "detail": (
                "kb_search identity is the versioned OwnerIdentityMapping, and the "
                "receipt binds its version and hash; the configured owner is ignored"
            ),
        },
    }


def _rows(
    matrices: dict[str, list[dict[str, Any]]], checks: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    by_case = {row["case_id"]: row for matrix in matrices.values() for row in matrix}
    rows: list[dict[str, Any]] = []
    for row in ROWS:
        reasons: list[str] = []
        for case_id in row.cases:
            case = by_case.get(case_id)
            if case is None:
                reasons.append(f"matrix case {case_id} was not evaluated")
            elif case["outcome"] != "satisfied":
                reasons.extend(f"{case_id}: {reason}" for reason in case["reasons"])
        for check in row.checks:
            record = checks.get(check)
            if record is None:
                reasons.append(f"check {check} was not evaluated")
            elif not record["value"]:
                reasons.append(f"{check}: {record['detail']}")
        rows.append(
            {
                "row_id": row.row_id,
                "source": row.source,
                "requirement": row.requirement,
                "cases": list(row.cases),
                "checks": list(row.checks),
                "satisfied": not reasons,
                "reasons": reasons,
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
ADAPTER_CANDIDATES = [
    {"candidate": "lee-kb-mcp stdio", "dependency": "none", "status": "selected"},
    {
        "candidate": "python-api import",
        "dependency": "lee-kb package import into consumer runtime",
        "status": "not-evaluated",
        "reason": (
            "no satisfied GATE-DEP-001 entry exists; candidate never installed or "
            "trialled"
        ),
    },
]

REQUIRED_SECTIONS = (
    "version",
    "artifact_id",
    "status",
    "failure_reasons",
    "generated_at",
    "owner_repository",
    "versions",
    "identity_mapping",
    "commands",
    "handshake",
    "permission_matrices",
    "receipt_fields",
    "no_write",
    "adapter_candidates",
    "contract_rows",
    "checks",
    "symbol_locations",
    "mutation_probes",
    "determinism",
    "provenance",
)

VOLATILE_FIELDS = (
    "generated_at",
    "artifact_sha256",
    "stable_body_sha256",
    "owner_repository.owner_repository_commit",
    "owner_repository.dirty",
    "owner_repository.dirty_file_count",
)

FORBIDDEN_CONTENT_KEYS = ("body", "text", "query", "question", "snippet", "paths")


def _content_free(node: Any, path: str = "") -> list[str]:
    """Reject any leaked payload key. Booleans and counts are allowed."""
    problems: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key in FORBIDDEN_CONTENT_KEYS and isinstance(value, str):
                problems.append(f"{child} carries a payload string")
            problems.extend(_content_free(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            problems.extend(_content_free(value, f"{path}[{index}]"))
    elif isinstance(node, str):
        leaked = (PROBE_BODY, WIRE_QUERY, WIRE_HISTORY_BODY.strip())
        if any(value in node for value in leaked):
            problems.append(f"{path} echoes probe payload text")
    return problems


def _strip(body: dict[str, Any]) -> dict[str, Any]:
    reduced = json.loads(json.dumps(body))
    for dotted in VOLATILE_FIELDS:
        target = reduced
        parts = dotted.split(".")
        for part in parts[:-1]:
            target = target.get(part) if isinstance(target, dict) else None
            if target is None:
                break
        if isinstance(target, dict):
            target.pop(parts[-1], None)
    return reduced


def build_artifact() -> dict[str, Any]:
    """Run every command and probe, then compute the artifact and its status."""
    replacements = _replacements()
    commands = {
        "pytest_test_owner": _run(
            ["python3", "-m", "pytest", "tests/test_owner.py", "-q"],
            cwd=REPO_ROOT,
            env=_repo_env(),
            replacements=replacements,
        ),
        "pytest_test_mcp": _run(
            ["python3", "-m", "pytest", "tests/test_mcp.py", "-q"],
            cwd=REPO_ROOT,
            env=_repo_env(),
            replacements=replacements,
        ),
        "compileall_owner": _run(
            ["python3", "-m", "compileall", "-q", "src/lee_kb/owner.py"],
            cwd=REPO_ROOT,
            env=_repo_env(),
            replacements=replacements,
        ),
    }

    with tempfile.TemporaryDirectory(prefix="s1c-no-write-") as raw_root:
        root = Path(raw_root)
        config, corpus, history_locator = _build_workspace(root)
        no_write = _no_write_proof(root, config, corpus, history_locator)

    wire = no_write["wire"]
    commands["mcp_stdio_handshake"] = {
        "argv": wire["probe_argv"],
        "returncode": 0 if wire.get("required_tools_present") else 1,
        "output_sha256": _canonical_sha256(
            {
                "protocol_version": wire.get("protocol_version"),
                "tools": wire.get("tools"),
            }
        ),
        "output_bytes": None,
        "output_normalization": "content-free-handshake/v1",
    }

    observed = {**_probe_current(), **_probe_history()}
    current_wire = wire.get("current", {})
    history_wire = wire.get("history", {})
    observed["wire.current_identity"] = (
        f"mapped_principal={bool(current_wire.get('principal_is_mapped_principal_id'))}"
        f"|mapped_type={bool(current_wire.get('principal_type_is_mapped_type'))}"
        f"|binds_mapping={bool(current_wire.get('receipt_binds_mapping'))}"
        f"|configured_owner={bool(current_wire.get('principal_is_configured_owner'))}"
    )
    observed["wire.owner_handshake"] = (
        "fields="
        f"{','.join(wire.get('owner_handshake_fields_exposed') or []) or 'none'}"
        "|matches_owner_versions="
        f"{bool(wire.get('owner_handshake_matches_owner_versions'))}"
    )
    observed["wire.history_release_capable"] = (
        f"release_capable={bool(history_wire.get('release_capable'))}"
        f"|receipt={bool(history_wire.get('receipt_present'))}"
        f"|receipt_complete={not history_wire.get('receipt_missing_required', True)}"
    )
    denied_states = ",".join(
        str(state) for state in history_wire.get("denied_states") or []
    )
    observed["wire.history_denials"] = (
        f"states={denied_states or 'none'}"
        f"|no_body={bool(history_wire.get('denials_release_no_body'))}"
        f"|identical={bool(history_wire.get('denials_are_indistinguishable'))}"
    )
    observed["wire.repeat_receipt"] = (
        f"new_receipt={bool(current_wire.get('repeat_query_returns_new_receipt'))}"
    )
    observed["wire.history_identity_argument"] = (
        "extra_identity_argument_rejected="
        f"{bool(history_wire.get('identity_argument_rejected'))}"
    )

    test_ids = sorted({case.test_id for case in CASES if case.test_id})
    tests = {test_id: _focused_test(test_id, replacements) for test_id in test_ids}
    mutation_probes = _mutation_probes()
    mutations = {probe["mutation"]: probe for probe in mutation_probes}
    matrices = _matrices(observed, tests, mutations)

    identity = _identity_mapping()
    receipts = _receipt_fields()
    checks = _checks(commands, receipts, identity, no_write, observed)

    artifact: dict[str, Any] = {
        "version": ARTIFACT_VERSION,
        "artifact_id": ARTIFACT_ID,
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "owner_repository": _owner_repository(),
        "versions": _versions(),
        "identity_mapping": identity,
        "commands": [commands[name] | {"name": name} for name in sorted(commands)],
        "handshake": wire,
        "permission_matrices": matrices,
        "receipt_fields": receipts,
        "no_write": {key: value for key, value in no_write.items() if key != "wire"},
        "adapter_candidates": ADAPTER_CANDIDATES,
        "checks": checks,
        "symbol_locations": _symbol_locations(),
        "mutation_probes": mutation_probes,
        "determinism": {
            "normalized_command_output": (
                "command digests hash normalized output: wall-clock durations, "
                "absolute temporary/repository/home paths, timestamps and 32+ hex "
                "digests are replaced with stable tokens"
            ),
            "volatile_fields": list(VOLATILE_FIELDS),
            "stable_body_scope": (
                "stable_body_sha256 covers the artifact minus volatile_fields and is "
                "reproducible on the same toolchain; pytest and Python versions are "
                "part of it, so it is machine-specific"
            ),
        },
        "provenance": {
            "content_free": (
                "no source content, question text, corpus path lists or evidence "
                "bodies "
                "are included; only lee-kb's own root-relative file names, symbol "
                "names, "
                "test ids, schema key names, digests, counts and booleans"
            ),
            "generator": GENERATOR,
            "contract_document": CONTRACT_DOCUMENT,
            "evidence_basis": (
                "every matrix row is computed from an in-process behaviour probe, a "
                "focused pytest run and, where a rule must be test-defended, a "
                "mutation "
                "probe applied to a private copy of the package"
            ),
        },
    }

    # The self-checks close over the evidence sections only; contract rows,
    # failure reasons, status and the digests are derived from them afterwards.
    missing_sections = [
        name
        for name in REQUIRED_SECTIONS
        if name not in artifact
        and name not in {"status", "failure_reasons", "contract_rows"}
    ]
    leaks = _content_free(artifact)
    checks["artifact_sections_present"] = {
        "value": not missing_sections,
        "detail": f"missing evidence sections: {missing_sections or 'none'}",
    }
    checks["artifact_is_content_free"] = {
        "value": not leaks,
        "detail": f"payload leaks: {leaks or 'none'}",
    }

    rows = _rows(matrices, checks)
    failure_reasons = [
        f"command {name} returned {commands[name]['returncode']}"
        for name in sorted(commands)
        if commands[name]["returncode"] != 0
    ]
    if not no_write["proof"]["corpus_unchanged"]:
        failure_reasons.append("no-write proof failed: source corpus changed")
    failure_reasons.extend(
        f"{row['row_id']} ({row['source']}) unsatisfied: {reason}"
        for row in rows
        if not row["satisfied"]
        for reason in row["reasons"]
    )

    artifact["contract_rows"] = rows
    artifact["failure_reasons"] = failure_reasons
    artifact["status"] = "accepted" if not failure_reasons else "failed"
    artifact["stable_body_sha256"] = _canonical_sha256(_strip(artifact))
    artifact["artifact_sha256"] = _canonical_sha256(
        {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    )
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Produce the content-free S1C owner-acceptance artifact for lee-kb."
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write the artifact here instead of stdout.",
    )
    arguments = parser.parse_args(argv)

    artifact = build_artifact()
    rendered = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if arguments.output:
        destination = Path(arguments.output).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        print(
            f"{ARTIFACT_ID}: {artifact['status']} "
            f"({len(artifact['failure_reasons'])} reasons) -> {destination}"
        )
    else:
        sys.stdout.write(rendered)
    return 0 if artifact["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
