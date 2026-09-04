"""Persisted server-owned access policy for the multi-principal access plane.

The knowledge policy is operator state, never client input.  It lives beside
the lee-kb configuration file, is written atomically with owner-only file
permissions, and is reloaded verbatim by every transport that has to authorize
an employee principal.  Every failure path is fail-closed: a missing, corrupt,
or unsupported state file raises :class:`~lee_kb.access.AccessStateError`
rather than degrading to an emptier -- or wider -- policy.

The persisted ``policy`` object is exactly the body
:class:`~lee_kb.access.KnowledgePolicy` hashes, so ``load_policy`` of a saved
policy reproduces the original ``policy_hash``.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .access import (
    ACCESS_POLICY_VERSION,
    AccessStateError,
    EmployeeIdentity,
    KnowledgeGrant,
    KnowledgePolicy,
)
from .contracts import Principal, PrincipalType

#: Version of the persisted policy envelope written by :func:`save_policy`.
POLICY_STATE_VERSION = 1

#: Policy state file name, resolved beside the configuration file.
POLICY_FILENAME = "access-policy.json"

#: Client-credential state file name, resolved beside the configuration file.
CLIENTS_FILENAME = "access-clients.json"


def policy_path_for(config_path: str | Path) -> Path:
    """Return the knowledge-policy state path beside ``config_path``."""
    return Path(config_path).expanduser().parent / POLICY_FILENAME


def clients_path_for(config_path: str | Path) -> Path:
    """Return the client-credential state path beside ``config_path``."""
    return Path(config_path).expanduser().parent / CLIENTS_FILENAME


def load_policy(path: str | Path) -> KnowledgePolicy:
    """Load the server-owned knowledge policy, failing closed on any doubt."""
    state_path = Path(path).expanduser()
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise AccessStateError("access policy state is missing") from error
    except (OSError, ValueError) as error:
        raise AccessStateError("access policy state could not be read") from error
    if not isinstance(raw, dict) or raw.get("version") != POLICY_STATE_VERSION:
        raise AccessStateError("unsupported access policy state version")
    body = raw.get("policy")
    if not isinstance(body, dict):
        raise AccessStateError("access policy state is invalid")
    if body.get("version") != ACCESS_POLICY_VERSION:
        raise AccessStateError("unsupported access policy version")
    employees = body.get("employees")
    grants = body.get("grants")
    if not isinstance(employees, list) or not isinstance(grants, list):
        raise AccessStateError("access policy state is invalid")
    try:
        return KnowledgePolicy(
            employees=tuple(_employee(value) for value in employees),
            grants=tuple(_grant(value) for value in grants),
            version=ACCESS_POLICY_VERSION,
        )
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise AccessStateError(
            "access policy state contains an invalid record"
        ) from error


def save_policy(path: str | Path, policy: KnowledgePolicy) -> None:
    """Write ``policy`` atomically with owner-only permissions."""
    if not isinstance(policy, KnowledgePolicy):
        raise TypeError("policy must be a KnowledgePolicy")
    state_path = Path(path).expanduser()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": POLICY_STATE_VERSION, "policy": _policy_body(policy)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    fd, temporary = tempfile.mkstemp(
        prefix=f".{state_path.name}.", dir=state_path.parent
    )
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, state_path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _policy_body(policy: KnowledgePolicy) -> dict[str, Any]:
    return {
        "version": policy.version,
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
            for employee in policy.employees
        ],
        "grants": [
            {
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
                "not_before": _isoformat(grant.not_before),
                "expires_at": _isoformat(grant.expires_at),
                "revoked_at": _isoformat(grant.revoked_at),
                "policy_version": grant.policy_version,
            }
            for grant in policy.grants
        ],
    }


def _employee(value: object) -> EmployeeIdentity:
    if not isinstance(value, dict):
        raise TypeError("employee record must be an object")
    return EmployeeIdentity(
        employee_id=value["employee_id"],
        principal=Principal(
            principal_id=value["principal_id"],
            principal_type=PrincipalType(value["principal_type"]),
        ),
        tenant=value["tenant"],
        lane=value["lane"],
        scope_id=value["scope_id"],
        purpose=value["purpose"],
    )


def _grant(value: object) -> KnowledgeGrant:
    if not isinstance(value, dict):
        raise TypeError("grant record must be an object")
    operations = value["operations"]
    item_ids = value.get("item_ids", [])
    if not isinstance(operations, list) or not isinstance(item_ids, list):
        raise TypeError("grant operations and item_ids must be arrays")
    return KnowledgeGrant(
        grant_id=value["grant_id"],
        principal_id=value["principal_id"],
        tenant=value["tenant"],
        lane=value["lane"],
        scope_id=value["scope_id"],
        purpose=value["purpose"],
        project=value["project"],
        source_namespace=value["source_namespace"],
        root=value["root"],
        path_prefix=value["path_prefix"],
        operations=frozenset(operations),
        item_ids=tuple(item_ids),
        classification=value.get("classification"),
        not_before=_timestamp(value.get("not_before"), "not_before"),
        expires_at=_timestamp(value.get("expires_at"), "expires_at"),
        revoked_at=_timestamp(value.get("revoked_at"), "revoked_at"),
        policy_version=value.get("policy_version", ACCESS_POLICY_VERSION),
    )


def _isoformat(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _timestamp(value: object, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO 8601 string")
    return datetime.fromisoformat(value)


__all__ = [
    "POLICY_STATE_VERSION",
    "POLICY_FILENAME",
    "CLIENTS_FILENAME",
    "policy_path_for",
    "clients_path_for",
    "load_policy",
    "save_policy",
]
