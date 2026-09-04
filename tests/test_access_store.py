"""Fail-closed persistence tests for the server-owned access policy state.

The policy file is operator state that authorizes every employee principal, so
these tests pin two properties: a saved policy reloads byte-for-byte identical
(including ``policy_hash``), and anything doubtful -- missing, corrupt,
unsupported, or semantically invalid -- raises instead of loading a policy the
operator never wrote.
"""

import json
import stat
from datetime import datetime, timedelta, timezone

import pytest

from lee_kb import access_store
from lee_kb.access import (
    ACCESS_POLICY_VERSION,
    AccessStateError,
    EmployeeIdentity,
    KnowledgeGrant,
    KnowledgePolicy,
)
from lee_kb.access_store import (
    POLICY_STATE_VERSION,
    clients_path_for,
    load_policy,
    policy_path_for,
    save_policy,
)
from lee_kb.contracts import (
    WHOLE_ROOT_PATH_PREFIX,
    Principal,
    PrincipalType,
    SourceGrant,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR


def make_employee(
    employee_id: str = "employee-cos",
    principal_id: str = "employee:chief-of-staff",
    *,
    principal_type: PrincipalType = PrincipalType.AI_EMPLOYEE,
) -> EmployeeIdentity:
    return EmployeeIdentity(
        employee_id=employee_id,
        principal=Principal(principal_id, principal_type),
        tenant="leebase",
        lane="knowledge",
        scope_id=f"{employee_id}-scope",
        purpose="governed-retrieval",
    )


def make_grant(owner: EmployeeIdentity, **overrides) -> KnowledgeGrant:
    """Build a grant whose context matches ``owner``, as the policy requires."""
    fields = {
        "grant_id": "grant-notes",
        "principal_id": owner.principal_id,
        "tenant": owner.tenant,
        "lane": owner.lane,
        "scope_id": owner.scope_id,
        "purpose": owner.purpose,
        "project": "default",
        "source_namespace": "local_files",
        "root": "notes",
        "path_prefix": WHOLE_ROOT_PATH_PREFIX,
        "operations": frozenset({"search", "read", "cite"}),
    }
    fields.update(overrides)
    return KnowledgeGrant(**fields)


def make_source_grant(**overrides) -> SourceGrant:
    fields = {
        "project": "default",
        "source_namespace": "local_files",
        "root": "notes",
        "path_prefix": WHOLE_ROOT_PATH_PREFIX,
    }
    fields.update(overrides)
    return SourceGrant(**fields)


@pytest.fixture
def policy() -> KnowledgePolicy:
    """Two employees and two grants exercising every persisted grant field."""
    cos = make_employee()
    analyst = make_employee(
        "employee-analyst",
        "employee:analyst",
        principal_type=PrincipalType.HUMAN,
    )
    return KnowledgePolicy(
        employees=(cos, analyst),
        grants=(
            make_grant(cos),
            make_grant(
                analyst,
                grant_id="grant-briefs",
                project="alpha",
                source_namespace="local_files",
                root="briefs",
                path_prefix="team/q3",
                operations=frozenset({"search"}),
                item_ids=("local_files:briefs:team/q3/plan.md",),
                classification="internal",
                not_before=NOW,
                expires_at=NOW + timedelta(days=30),
                revoked_at=NOW + timedelta(days=10),
            ),
        ),
    )


@pytest.fixture
def payload(tmp_path, policy) -> dict:
    """The canonical persisted payload, ready to be corrupted field by field."""
    reference = tmp_path / "reference.json"
    save_policy(reference, policy)
    return json.loads(reference.read_text(encoding="utf-8"))


def test_round_trip_preserves_the_policy_hash_and_every_field(tmp_path, policy):
    path = policy_path_for(tmp_path / "config.toml")
    save_policy(path, policy)
    loaded = load_policy(path)

    assert loaded.policy_hash == policy.policy_hash
    assert loaded.version == ACCESS_POLICY_VERSION
    assert loaded.employees == policy.employees
    assert loaded.grants == policy.grants
    assert loaded.employees[0].principal.principal_type is PrincipalType.AI_EMPLOYEE
    assert loaded.employees[1].principal.principal_type is PrincipalType.HUMAN
    assert loaded.grants[0].path_prefix == WHOLE_ROOT_PATH_PREFIX
    assert loaded.grants[1].revoked_at == NOW + timedelta(days=10)


def test_state_paths_sit_beside_the_configuration_file(tmp_path):
    config_path = tmp_path / "nested" / "config.toml"

    assert policy_path_for(config_path) == config_path.parent / "access-policy.json"
    assert clients_path_for(config_path) == config_path.parent / "access-clients.json"


def test_saved_state_is_owner_only_and_leaves_no_temporary_file(tmp_path, policy):
    path = policy_path_for(tmp_path / "config.toml")
    save_policy(path, policy)

    assert stat.S_IMODE(path.stat().st_mode) == OWNER_ONLY
    assert [entry.name for entry in tmp_path.iterdir()] == ["access-policy.json"]
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["version"] == POLICY_STATE_VERSION
    assert stored["policy"]["version"] == ACCESS_POLICY_VERSION
    assert [record["employee_id"] for record in stored["policy"]["employees"]] == [
        "employee-cos",
        "employee-analyst",
    ]


def test_failed_rename_keeps_the_previous_policy(tmp_path, policy, monkeypatch):
    path = policy_path_for(tmp_path / "config.toml")
    save_policy(path, policy)
    original = path.read_bytes()

    def refuse_rename(*_args, **_kwargs):
        raise OSError("rename failed")

    monkeypatch.setattr(access_store.os, "replace", refuse_rename)
    narrower = KnowledgePolicy(employees=policy.employees, grants=())
    with pytest.raises(OSError):
        save_policy(path, narrower)

    assert path.read_bytes() == original
    assert [entry.name for entry in tmp_path.iterdir()] == ["access-policy.json"]
    assert load_policy(path).policy_hash == policy.policy_hash


def test_missing_state_fails_closed(tmp_path):
    with pytest.raises(AccessStateError):
        load_policy(policy_path_for(tmp_path / "config.toml"))


def test_corrupt_state_fails_closed(tmp_path):
    path = policy_path_for(tmp_path / "config.toml")
    path.write_text('{"version": 1, "policy": {', encoding="utf-8")

    with pytest.raises(AccessStateError):
        load_policy(path)


def test_unsupported_state_version_fails_closed(tmp_path, payload):
    path = policy_path_for(tmp_path / "config.toml")
    payload["version"] = POLICY_STATE_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AccessStateError):
        load_policy(path)


def test_unsupported_policy_version_fails_closed(tmp_path, payload):
    path = policy_path_for(tmp_path / "config.toml")
    payload["policy"]["version"] = "lee-kb.access.policy/v99"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AccessStateError):
        load_policy(path)


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(lambda state: state.pop("policy"), id="no-policy"),
        pytest.param(lambda state: state["policy"].pop("grants"), id="no-grants-key"),
        pytest.param(
            lambda state: state["policy"]["employees"].clear(), id="no-employees"
        ),
        pytest.param(
            lambda state: state["policy"]["employees"][0].pop("principal_type"),
            id="missing-principal-type",
        ),
        pytest.param(
            lambda state: state["policy"]["employees"][0].update(
                principal_type="robot"
            ),
            id="unknown-principal-type",
        ),
        pytest.param(
            lambda state: state["policy"]["employees"][0].update(tenant=""),
            id="empty-tenant",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][0].update(
                operations=["search", "delete"]
            ),
            id="unknown-operation",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][0].update(operations=[]),
            id="no-operations",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][0].update(path_prefix="../secrets"),
            id="traversal-prefix",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][0].update(path_prefix="memos/*"),
            id="partial-wildcard-prefix",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][0].update(
                principal_id="employee:ghost"
            ),
            id="unknown-principal",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][0].update(tenant="other-tenant"),
            id="cross-tenant",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][0].update(lane="other-lane"),
            id="context-mismatch",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][1].update(
                expires_at="not-a-timestamp"
            ),
            id="unparsable-timestamp",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][1].update(
                not_before="2026-08-13T12:00:00"
            ),
            id="naive-timestamp",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"].append("not-an-object"),
            id="grant-not-an-object",
        ),
        pytest.param(
            lambda state: state["policy"]["grants"][0].update(
                grant_id=state["policy"]["grants"][1]["grant_id"]
            ),
            id="duplicate-grant-id",
        ),
    ],
)
def test_invalid_records_fail_closed(tmp_path, payload, corrupt):
    corrupt(payload)
    path = policy_path_for(tmp_path / "config.toml")
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AccessStateError):
        load_policy(path)


def test_whole_root_sentinel_permits_every_path_in_its_own_root():
    grant = make_source_grant()

    for path in ("plan.md", "memos/q3/plan.md", "memos/a*b.md"):
        assert grant.permits(
            project="default",
            source_namespace="local_files",
            root="notes",
            path=path,
            item_id=None,
        )
    for mismatch in (
        {"root": "briefs"},
        {"project": "alpha"},
        {"source_namespace": "outlook"},
    ):
        address = {
            "project": "default",
            "source_namespace": "local_files",
            "root": "notes",
            "path": "plan.md",
            "item_id": None,
        }
        address.update(mismatch)
        assert not grant.permits(**address)


def test_whole_root_sentinel_still_enforces_the_item_allow_list():
    grant = make_source_grant(item_ids=("local_files:notes:plan.md",))

    assert grant.permits(
        project="default",
        source_namespace="local_files",
        root="notes",
        path="plan.md",
        item_id="local_files:notes:plan.md",
    )
    assert not grant.permits(
        project="default",
        source_namespace="local_files",
        root="notes",
        path="secret.md",
        item_id="local_files:notes:secret.md",
    )


def test_knowledge_grant_accepts_the_sentinel_and_forwards_it():
    grant = make_grant(make_employee())

    assert grant.path_prefix == WHOLE_ROOT_PATH_PREFIX
    assert grant.source_grant.path_prefix == WHOLE_ROOT_PATH_PREFIX
    assert grant.source_grant.permits(
        project="default",
        source_namespace="local_files",
        root="notes",
        path="memos/q3/plan.md",
        item_id=None,
    )


@pytest.mark.parametrize("path_prefix", ["a*", "*/x", "*a", "memos/*", "**", "*.md"])
def test_partial_wildcards_are_rejected_by_both_grant_contracts(path_prefix):
    with pytest.raises(ValueError):
        make_source_grant(path_prefix=path_prefix)
    with pytest.raises(ValueError):
        make_grant(make_employee(), path_prefix=path_prefix)


@pytest.mark.parametrize(
    "path_prefix", ["/absolute/path", "../escape", "memos//plan.md", ".", ".."]
)
def test_relative_path_rules_still_apply_to_literal_prefixes(path_prefix):
    with pytest.raises(ValueError):
        make_source_grant(path_prefix=path_prefix)
    with pytest.raises(ValueError):
        make_grant(make_employee(), path_prefix=path_prefix)
