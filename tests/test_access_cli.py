"""End-to-end `lee-kb access` tests driven through the real entry point.

These drive ``main()`` with argv the way an operator does: provision an
employee principal, issue a client credential, grant bounded access, then run
one genuine authenticated retrieval so ``lee-kb access audit list`` prints the
durable evidence the gateway wrote.  Nothing here reaches into private state:
assertions read the persisted files and the printed output only.
"""

import json
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lee_kb.access import (
    AccessRegistry,
    AuthenticatedKnowledgeGateway,
    AuthenticationError,
    session_reference,
)
from lee_kb.access_store import clients_path_for, load_policy, policy_path_for
from lee_kb.chunking import chunk_document
from lee_kb.contracts import (
    DocumentType,
    KnowledgeItem,
    KnowledgeItemId,
    PermissionSet,
    SourceLocator,
    Visibility,
    compute_content_hash,
)
from lee_kb.main import main
from lee_kb.repository import SQLiteRepository

EMPLOYEE_ID = "employee-cos"
PRINCIPAL = "employee:chief-of-staff"
TENANT = "leebase"
LANE = "knowledge"
SCOPE = "cos-scope"
PURPOSE = "governed-retrieval"
PROJECT = "default"
CLIENT_ID = "cos-client"
GRANT_ID = "grant-notes"
OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR

NOW = datetime.now(timezone.utc)
SOURCE_TIME = NOW - timedelta(days=1)
SYNC_TIME = NOW - timedelta(minutes=5)


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    out: str
    err: str


class AccessCli:
    """Run `lee-kb` argv in-process against a throwaway configuration."""

    def __init__(self, tmp_path: Path, monkeypatch, capsys) -> None:
        self.config_path = tmp_path / "config.toml"
        self.config_path.write_text(
            'schema = 1\nowner = "lee@leebase.com"\n', encoding="utf-8"
        )
        self.database_path = tmp_path / "knowledge.sqlite"
        self._monkeypatch = monkeypatch
        self._capsys = capsys
        monkeypatch.setenv("LEE_KB_CONFIG", str(self.config_path))

    @property
    def policy_path(self) -> Path:
        return policy_path_for(self.config_path)

    @property
    def clients_path(self) -> Path:
        return clients_path_for(self.config_path)

    def run(self, *argv: str) -> CliResult:
        self._monkeypatch.setattr(sys, "argv", ["lee-kb", *argv])
        exit_code = 0
        try:
            main()
        except SystemExit as error:
            exit_code = 0 if error.code is None else int(error.code)
        captured = self._capsys.readouterr()
        return CliResult(exit_code, captured.out, captured.err)

    def add_employee(
        self, employee_id: str = EMPLOYEE_ID, principal: str = PRINCIPAL
    ) -> CliResult:
        return self.run(
            "access",
            "employee",
            "add",
            "--employee-id",
            employee_id,
            "--principal",
            principal,
            "--tenant",
            TENANT,
            "--lane",
            LANE,
            "--scope",
            SCOPE,
            "--purpose",
            PURPOSE,
        )

    def add_grant(self, *extra: str) -> CliResult:
        return self.run(
            "access",
            "grant",
            "add",
            "--principal",
            PRINCIPAL,
            "--project",
            PROJECT,
            "--source-namespace",
            "local_files",
            "--root",
            "notes",
            *extra,
        )

    def register_client(self) -> CliResult:
        return self.run(
            "access",
            "client",
            "register",
            "--principal",
            PRINCIPAL,
            "--client-id",
            CLIENT_ID,
        )

    def grants(self) -> tuple:
        return load_policy(self.policy_path).grants


@pytest.fixture
def cli(tmp_path, monkeypatch, capsys) -> AccessCli:
    return AccessCli(tmp_path, monkeypatch, capsys)


def printed_secret(result: CliResult) -> str:
    """Extract the one-time client secret from register output."""
    for line in result.out.splitlines():
        if line.startswith("client_secret: "):
            return line.split(": ", 1)[1]
    raise AssertionError(f"no client secret was printed: {result.out!r}")


def parse_events(out: str) -> list[dict[str, str]]:
    """Parse `access audit list` output back into field maps."""
    events = []
    for line in out.strip().splitlines():
        fields = line.split("  ")
        event = {
            "timestamp": fields[0],
            "event_type": fields[1],
            "outcome": fields[2],
        }
        event.update(dict(field.split("=", 1) for field in fields[3:]))
        events.append(event)
    return events


def sync_markdown(
    repository: SQLiteRepository, source_object_id: str, text: str
) -> KnowledgeItem:
    """Persist one deterministic local markdown projection item."""
    item_id = KnowledgeItemId("local_files", source_object_id)
    item = KnowledgeItem(
        item_id=item_id,
        project=PROJECT,
        source_locator=SourceLocator(
            connector_id="local_files",
            uri=f"file:///knowledge/{source_object_id}",
            label=source_object_id,
        ),
        document_type=DocumentType.MARKDOWN,
        content_hash=compute_content_hash(text),
        source_timestamp=SOURCE_TIME,
        sync_timestamp=SYNC_TIME,
        permissions=PermissionSet(
            owner="document-owner",
            visibility=Visibility.PRIVATE,
            allowed_principals=(PRINCIPAL,),
        ),
        title=source_object_id,
    )
    repository.sync_item(
        item,
        chunk_document(
            text,
            item_id=item_id,
            project=PROJECT,
            document_type=DocumentType.MARKDOWN,
        ),
    )
    return item


def test_employee_add_then_list_reports_the_governed_context(cli):
    added = cli.add_employee()

    assert added.exit_code == 0
    assert PRINCIPAL in added.out
    assert stat.S_IMODE(cli.policy_path.stat().st_mode) == OWNER_ONLY

    listed = cli.run("access", "employee", "list")

    assert listed.exit_code == 0
    assert f"{EMPLOYEE_ID}  principal={PRINCIPAL}" in listed.out
    assert "type=ai_employee" in listed.out
    assert f"tenant={TENANT}" in listed.out
    assert f"lane={LANE}" in listed.out
    assert f"scope={SCOPE}" in listed.out
    assert f"purpose={PURPOSE}" in listed.out

    policy = load_policy(cli.policy_path)
    assert [employee.employee_id for employee in policy.employees] == [EMPLOYEE_ID]
    assert policy.employees[0].tenant == TENANT


def test_reading_commands_report_a_missing_policy_without_a_traceback(cli):
    listed = cli.run("access", "employee", "list")

    assert listed.exit_code == 1
    assert "no access policy found" in listed.err
    assert "Traceback" not in listed.err
    assert not cli.policy_path.exists()


def test_duplicate_employee_id_or_principal_is_rejected(cli):
    assert cli.add_employee().exit_code == 0

    duplicate_id = cli.add_employee(principal="employee:analyst")
    duplicate_principal = cli.add_employee(employee_id="employee-analyst")

    assert duplicate_id.exit_code == 2
    assert EMPLOYEE_ID in duplicate_id.err
    assert "already registered" in duplicate_id.err
    assert duplicate_principal.exit_code == 2
    assert PRINCIPAL in duplicate_principal.err
    assert len(load_policy(cli.policy_path).employees) == 1


def test_client_register_prints_the_secret_once_and_persists_only_a_digest(cli):
    cli.add_employee()

    registered = cli.register_client()

    assert registered.exit_code == 0
    assert f"client_id: {CLIENT_ID}" in registered.out
    assert "shown once" in registered.out
    secret = printed_secret(registered)

    state_text = cli.clients_path.read_text(encoding="utf-8")
    record = json.loads(state_text)["clients"][0]
    assert secret not in state_text
    assert record["client_id"] == CLIENT_ID
    assert record["principal_id"] == PRINCIPAL
    assert len(record["digest"]) == 64
    assert "client_secret" not in record
    assert stat.S_IMODE(cli.clients_path.stat().st_mode) == OWNER_ONLY

    listed = cli.run("access", "client", "list")
    assert listed.exit_code == 0
    assert CLIENT_ID in listed.out
    assert "active" in listed.out
    assert secret not in listed.out

    # The one printed secret is the real credential and is never re-derivable.
    registry = AccessRegistry(load_policy(cli.policy_path), state_path=cli.clients_path)
    session = registry.authenticate(CLIENT_ID, secret)
    assert session.principal_id == PRINCIPAL
    assert session.tenant == TENANT
    with pytest.raises(AuthenticationError):
        registry.authenticate(CLIENT_ID, f"{secret}x")


def test_client_revoke_disables_the_credential(cli):
    cli.add_employee()
    secret = printed_secret(cli.register_client())

    revoked = cli.run("access", "client", "revoke", "--client-id", CLIENT_ID)

    assert revoked.exit_code == 0
    listed = cli.run("access", "client", "list")
    assert "revoked=" in listed.out
    registry = AccessRegistry(load_policy(cli.policy_path), state_path=cli.clients_path)
    with pytest.raises(AuthenticationError):
        registry.authenticate(CLIENT_ID, secret)

    unknown = cli.run("access", "client", "revoke", "--client-id", "ghost-client")
    assert unknown.exit_code == 2
    assert "not registered" in unknown.err


def test_client_register_for_an_unknown_principal_is_rejected(cli):
    cli.add_employee()

    rejected = cli.run("access", "client", "register", "--principal", "employee:ghost")

    assert rejected.exit_code == 2
    assert "employee:ghost is not a configured employee" in rejected.err
    assert not cli.clients_path.exists()


def test_grant_add_defaults_to_the_whole_root_and_copies_employee_context(cli):
    cli.add_employee()

    added = cli.add_grant("--grant-id", GRANT_ID)

    assert added.exit_code == 0
    assert "path_prefix=*" in added.out
    (grant,) = cli.grants()
    assert grant.grant_id == GRANT_ID
    assert grant.path_prefix == "*"
    assert grant.operations == frozenset({"search", "read", "cite"})
    assert grant.expires_at is None
    assert grant.revoked_at is None
    assert (grant.tenant, grant.lane, grant.scope_id, grant.purpose) == (
        TENANT,
        LANE,
        SCOPE,
        PURPOSE,
    )

    listed = cli.run("access", "grant", "list", "--principal", PRINCIPAL)
    assert listed.exit_code == 0
    assert f"{GRANT_ID}  principal={PRINCIPAL}" in listed.out
    assert "source=local_files:notes/*" in listed.out
    assert "operations=cite,read,search" in listed.out
    assert "expires=never" in listed.out
    assert "active" in listed.out
    assert cli.run("access", "grant", "list", "--principal", "employee:other").out == ""


def test_grant_add_honors_explicit_scope_flags(cli):
    cli.add_employee()

    added = cli.add_grant(
        "--grant-id",
        GRANT_ID,
        "--path-prefix",
        "memos/q3",
        "--operations",
        "search",
        "--expires-days",
        "7",
        "--classification",
        "internal",
    )

    assert added.exit_code == 0
    (grant,) = cli.grants()
    assert grant.path_prefix == "memos/q3"
    assert grant.operations == frozenset({"search"})
    assert grant.classification == "internal"
    assert grant.expires_at is not None
    assert grant.expires_at > datetime.now(timezone.utc)


@pytest.mark.parametrize(
    "flag, value",
    [
        ("--tenant", "other-tenant"),
        ("--lane", "other-lane"),
        ("--scope", "other-scope"),
        ("--purpose", "other-purpose"),
    ],
)
def test_grant_context_cannot_be_set_from_flags(cli, flag, value):
    cli.add_employee()

    rejected = cli.add_grant(flag, value)

    assert rejected.exit_code == 2
    assert "unrecognized arguments" in rejected.err
    assert cli.grants() == ()


def test_grant_for_an_unknown_principal_is_rejected(cli):
    cli.add_employee()

    rejected = cli.run(
        "access",
        "grant",
        "add",
        "--principal",
        "employee:ghost",
        "--project",
        PROJECT,
        "--source-namespace",
        "local_files",
        "--root",
        "notes",
    )

    assert rejected.exit_code == 2
    assert "employee:ghost is not a configured employee" in rejected.err
    assert cli.grants() == ()


@pytest.mark.parametrize("path_prefix", ["memos/*", "../escape", "/absolute"])
def test_grant_add_revalidates_the_path_prefix_before_saving(cli, path_prefix):
    cli.add_employee()

    rejected = cli.add_grant("--path-prefix", path_prefix)

    assert rejected.exit_code == 2
    assert "path_prefix" in rejected.err
    assert cli.grants() == ()


def test_grant_add_rejects_unknown_operations(cli):
    cli.add_employee()

    rejected = cli.add_grant("--operations", "search,delete")

    assert rejected.exit_code == 2
    assert "operations" in rejected.err
    assert cli.grants() == ()


def test_grant_revoke_keeps_the_record_and_refuses_a_second_revocation(cli):
    cli.add_employee()
    cli.add_grant("--grant-id", GRANT_ID)

    revoked = cli.run("access", "grant", "revoke", "--grant-id", GRANT_ID)

    assert revoked.exit_code == 0
    (grant,) = cli.grants()
    assert grant.grant_id == GRANT_ID
    assert grant.revoked_at is not None
    listed = cli.run("access", "grant", "list")
    assert "revoked=" in listed.out

    again = cli.run("access", "grant", "revoke", "--grant-id", GRANT_ID)
    unknown = cli.run("access", "grant", "revoke", "--grant-id", "ghost-grant")

    assert again.exit_code == 2
    assert "already revoked" in again.err
    assert unknown.exit_code == 2
    assert "not registered" in unknown.err
    assert len(cli.grants()) == 1


def test_audit_list_prints_evidence_from_a_real_gateway_retrieval(cli):
    cli.add_employee()
    secret = printed_secret(cli.register_client())
    assert cli.add_grant("--grant-id", GRANT_ID).exit_code == 0

    without_database = cli.run("access", "audit", "list")
    assert without_database.exit_code == 1
    assert "no synchronized knowledge found" in without_database.err

    query = "auditprobe"
    with SQLiteRepository(cli.database_path) as repository:
        sync_markdown(repository, "notes:memos/plan.md", "auditprobe retention rule")
        sync_markdown(repository, "briefs:memos/plan.md", "auditprobe other root")
        registry = AccessRegistry(
            load_policy(cli.policy_path), state_path=cli.clients_path
        )
        gateway = AuthenticatedKnowledgeGateway(repository, registry)
        session = gateway.authenticate(CLIENT_ID, secret)
        bundle = gateway.retrieve(session, query, project=PROJECT)

    # The whole-root sentinel admits the granted root only.
    assert [str(item.item_id) for item in bundle.evidence] == [
        "local_files:notes:memos/plan.md"
    ]

    listed = cli.run("access", "audit", "list")

    assert listed.exit_code == 0
    authentication, retrieval = parse_events(listed.out)
    assert authentication["event_type"] == "authentication"
    assert authentication["outcome"] == "allowed"
    assert authentication["reason"] == "authenticated"
    assert authentication["principal"] == PRINCIPAL
    assert authentication["client"] == CLIENT_ID
    assert authentication["session"] == session_reference(session.session_id)
    assert authentication["project"] == "-"
    assert authentication["grants"] == "-"
    assert authentication["query_digest"] == "-"
    assert retrieval["event_type"] == "retrieval"
    assert retrieval["outcome"] == "allowed"
    assert retrieval["reason"] == "retrieved"
    assert retrieval["principal"] == PRINCIPAL
    assert retrieval["client"] == CLIENT_ID
    assert retrieval["session"] == session_reference(session.session_id)
    assert retrieval["project"] == PROJECT
    assert retrieval["grants"] == GRANT_ID
    assert retrieval["query_digest"] == compute_content_hash(query)
    assert retrieval["freshness"] in {"fresh", "stale"}

    # Audit evidence carries no query text and no credential material.
    assert query not in listed.out
    assert secret not in listed.out

    newest = cli.run("access", "audit", "list", "--limit", "1")
    assert [event["event_type"] for event in parse_events(newest.out)] == ["retrieval"]
    assert cli.run("access", "audit", "list", "--limit", "0").exit_code == 2
