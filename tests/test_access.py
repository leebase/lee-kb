"""Focused regression tests for authenticated, governed knowledge access."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.access import (
    AccessRegistry,
    AuthenticatedKnowledgeGateway,
    AuthenticatedSession,
    AuthenticationError,
    AuthorizationError,
    ClientCredential,
    EmployeeIdentity,
    KnowledgeGrant,
    KnowledgePolicy,
    default_source_address,
    session_reference,
)
from lee_kb.chunking import chunk_document
from lee_kb.contracts import (
    AccessAuditEvent,
    AccessAuditOutcome,
    DocumentType,
    FreshnessRequirement,
    KnowledgeItem,
    KnowledgeItemId,
    PermissionSet,
    Principal,
    PrincipalType,
    RetrievalAuditStatus,
    SourceLocator,
    Visibility,
    compute_content_hash,
)
from lee_kb.governance import StaleEvidenceError
from lee_kb.repository import SQLiteRepository

BASE_TIME = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
SOURCE_TIME = BASE_TIME - timedelta(days=1)
SYNC_TIME = BASE_TIME - timedelta(hours=1)
PROJECT = "alpha"
EMPLOYEE_TENANT = "tenant-one"
EMPLOYEE_LANE = "knowledge"
EMPLOYEE_PURPOSE = "governed-retrieval"


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


@dataclass
class AccessWorld:
    repository: SQLiteRepository
    clock: MutableClock
    alice: EmployeeIdentity
    bob: EmployeeIdentity
    policy: KnowledgePolicy
    registry: AccessRegistry
    gateway: AuthenticatedKnowledgeGateway


def sync_markdown(
    repository: SQLiteRepository,
    source_object_id: str,
    text: str,
    *,
    project: str = PROJECT,
    permissions: PermissionSet,
) -> KnowledgeItem:
    """Persist one deterministic local markdown projection item."""
    item_id = KnowledgeItemId("local_files", source_object_id)
    item = KnowledgeItem(
        item_id=item_id,
        project=project,
        source_locator=SourceLocator(
            connector_id="local_files",
            uri=f"file:///knowledge/{source_object_id}",
            label=source_object_id,
        ),
        document_type=DocumentType.MARKDOWN,
        content_hash=compute_content_hash(text),
        source_timestamp=SOURCE_TIME,
        sync_timestamp=SYNC_TIME,
        permissions=permissions,
        title=source_object_id,
    )
    repository.sync_item(
        item,
        chunk_document(
            text,
            item_id=item_id,
            project=project,
            document_type=DocumentType.MARKDOWN,
        ),
    )
    return item


def ai_employee(
    employee_id: str,
    principal_id: str,
    *,
    scope_id: str,
) -> EmployeeIdentity:
    """Build one AI-employee identity inside the shared knowledge lane."""
    return EmployeeIdentity(
        employee_id=employee_id,
        principal=Principal(
            principal_id,
            PrincipalType.AI_EMPLOYEE,
            display_name=employee_id,
        ),
        tenant=EMPLOYEE_TENANT,
        lane=EMPLOYEE_LANE,
        scope_id=scope_id,
        purpose=EMPLOYEE_PURPOSE,
    )


def grant_for(
    employee: EmployeeIdentity,
    grant_id: str,
    *,
    root: str,
    path_prefix: str,
    project: str = PROJECT,
    item_ids: tuple[str, ...] = (),
    operations: frozenset[str] = frozenset({"search", "read", "cite"}),
) -> KnowledgeGrant:
    """Build a grant that already matches its employee's policy context."""
    return KnowledgeGrant(
        grant_id=grant_id,
        principal_id=employee.principal_id,
        tenant=employee.tenant,
        lane=employee.lane,
        scope_id=employee.scope_id,
        purpose=employee.purpose,
        project=project,
        source_namespace="local_files",
        root=root,
        path_prefix=path_prefix,
        operations=operations,
        item_ids=item_ids,
    )


def governed_stack(
    repository: SQLiteRepository,
    policy: KnowledgePolicy,
    clock: MutableClock,
) -> tuple[AccessRegistry, AuthenticatedKnowledgeGateway]:
    """Bind one server-owned policy to a registry and gateway."""
    registry = AccessRegistry(policy, clock=clock)
    gateway = AuthenticatedKnowledgeGateway(repository, registry, clock=clock)
    return registry, gateway


def session_for(
    registry: AccessRegistry,
    gateway: AuthenticatedKnowledgeGateway,
    principal_id: str,
    client_id: str,
) -> tuple[ClientCredential, AuthenticatedSession]:
    """Register one client for a policy principal and authenticate it."""
    credential = registry.register_client(
        principal_id,
        client_id=client_id,
        expires_at=BASE_TIME + timedelta(days=1),
    )
    session = gateway.authenticate(credential.client_id, credential.client_secret)
    return credential, session


def persisted_events(
    repository: SQLiteRepository,
    *,
    event_type: str | None = None,
    since: int = 0,
) -> tuple[AccessAuditEvent, ...]:
    """Return persisted access audit rows written after ``since`` rows."""
    return tuple(
        event
        for _, event in repository.list_access_events()[since:]
        if event_type is None or event.event_type == event_type
    )


@pytest.fixture
def world(tmp_path):
    clock = MutableClock(BASE_TIME)
    repository = SQLiteRepository(tmp_path / "knowledge.sqlite")
    alice = EmployeeIdentity(
        employee_id="employee-alice",
        principal=Principal("principal:alice", display_name="Alice"),
        tenant="tenant-one",
        lane="knowledge",
        scope_id="alice-scope",
        purpose="governed-retrieval",
    )
    bob = EmployeeIdentity(
        employee_id="employee-bob",
        principal=Principal("principal:bob", display_name="Bob"),
        tenant="tenant-one",
        lane="knowledge",
        scope_id="bob-scope",
        purpose="governed-retrieval",
    )

    target_id = str(KnowledgeItemId("local_files", "kb:team/target.md"))
    acl_denied_id = str(KnowledgeItemId("local_files", "kb:team/acl-denied.md"))
    grants = (
        KnowledgeGrant(
            grant_id="grant-alice-alpha-team",
            principal_id=alice.principal_id,
            tenant=alice.tenant,
            lane=alice.lane,
            scope_id=alice.scope_id,
            purpose=alice.purpose,
            project=PROJECT,
            source_namespace="local_files",
            root="kb",
            path_prefix="team",
            operations=frozenset({"search", "read", "cite"}),
            item_ids=(target_id, acl_denied_id),
        ),
        KnowledgeGrant(
            grant_id="grant-bob-beta-notes",
            principal_id=bob.principal_id,
            tenant=bob.tenant,
            project="beta",
            lane=bob.lane,
            scope_id=bob.scope_id,
            purpose=bob.purpose,
            source_namespace="local_files",
            root="bob",
            path_prefix="notes",
            operations=frozenset({"search"}),
        ),
    )
    policy = KnowledgePolicy(employees=(alice, bob), grants=grants)
    registry = AccessRegistry(policy, clock=clock)
    gateway = AuthenticatedKnowledgeGateway(repository, registry, clock=clock)

    sync_markdown(
        repository,
        "kb:team/target.md",
        "sharedgrantprobe scopeprobe",
        permissions=PermissionSet(
            owner="document-owner",
            visibility=Visibility.PRIVATE,
            allowed_principals=(alice.principal_id,),
        ),
    )
    sync_markdown(
        repository,
        "kb:team/sibling.md",
        "scopeprobe",
        permissions=PermissionSet(
            owner="document-owner",
            visibility=Visibility.PRIVATE,
            allowed_principals=(alice.principal_id,),
        ),
    )
    sync_markdown(
        repository,
        "kb:other.md",
        "scopeprobe",
        permissions=PermissionSet(
            owner="document-owner",
            visibility=Visibility.PRIVATE,
            allowed_principals=(alice.principal_id,),
        ),
    )
    sync_markdown(
        repository,
        "kb:team/acl-denied.md",
        "scopeprobe",
        permissions=PermissionSet(
            owner="document-owner",
            visibility=Visibility.PRIVATE,
        ),
    )

    try:
        yield AccessWorld(repository, clock, alice, bob, policy, registry, gateway)
    finally:
        repository.close()


def test_same_employee_clients_share_grants_but_receipts_keep_provenance(world):
    first_credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-client-one",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    second_credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-client-two",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    first_session = world.gateway.authenticate(
        first_credential.client_id, first_credential.client_secret
    )
    second_session = world.gateway.authenticate(
        second_credential.client_id, second_credential.client_secret
    )

    first_grants = world.policy.grants_for(
        first_session.principal_id,
        project=PROJECT,
        now=world.clock(),
    )
    second_grants = world.policy.grants_for(
        second_session.principal_id,
        project=PROJECT,
        now=world.clock(),
    )
    assert first_grants == second_grants
    assert first_session.principal_id == second_session.principal_id
    assert first_session.client_id != second_session.client_id
    assert first_session.session_id != second_session.session_id

    first_bundle = world.gateway.retrieve(
        first_session, "sharedgrantprobe", project=PROJECT
    )
    second_bundle = world.gateway.retrieve(
        second_session, "sharedgrantprobe", project=PROJECT
    )
    first_context = first_bundle.receipts[0].auth_context
    second_context = second_bundle.receipts[0].auth_context
    assert first_context is not None
    assert second_context is not None
    assert first_context.grant_ids == ("grant-alice-alpha-team",)
    assert second_context.grant_ids == first_context.grant_ids
    assert first_context.client_id == first_credential.client_id
    assert second_context.client_id == second_credential.client_id
    assert first_context.session_id == session_reference(first_session.session_id)
    assert second_context.session_id == session_reference(second_session.session_id)
    assert first_context != second_context

    # Provenance survives persistence: one principal, two attributable clients.
    retrieval = persisted_events(world.repository, event_type="retrieval")
    assert [event.client_id for event in retrieval] == [
        first_credential.client_id,
        second_credential.client_id,
    ]
    assert [event.session_id for event in retrieval] == [
        session_reference(first_session.session_id),
        session_reference(second_session.session_id),
    ]
    assert {event.principal.principal_id for event in retrieval} == {
        world.alice.principal_id
    }
    assert all(event.grant_ids == ("grant-alice-alpha-team",) for event in retrieval)
    persisted_receipts = [receipt for _, receipt in world.repository.list_receipts()]
    assert [receipt.auth_context.client_id for receipt in persisted_receipts] == [
        first_credential.client_id,
        second_credential.client_id,
    ]
    assert {receipt.principal.principal_id for receipt in persisted_receipts} == {
        world.alice.principal_id
    }


def test_other_employee_cannot_authenticate_as_first(world):
    alice_credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    bob_credential = world.registry.register_client(
        world.bob.principal_id,
        client_id="bob-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )

    with pytest.raises(AuthenticationError):
        world.gateway.authenticate(
            alice_credential.client_id, bob_credential.client_secret
        )
    with pytest.raises(AuthenticationError):
        world.gateway.authenticate(
            bob_credential.client_id, alice_credential.client_secret
        )

    bob_session = world.gateway.authenticate(
        bob_credential.client_id, bob_credential.client_secret
    )
    assert bob_session.principal_id == world.bob.principal_id
    assert bob_session.principal_id != alice_credential.principal_id


def test_invalid_credentials_and_revoked_sessions_fail_closed(world):
    credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )

    with pytest.raises(AuthenticationError):
        world.gateway.authenticate(credential.client_id, "not-the-secret")

    session = world.gateway.authenticate(credential.client_id, credential.client_secret)
    assert world.registry.revoke_session(session) is True
    with pytest.raises(AuthenticationError):
        world.gateway.retrieve(
            session,
            "sharedgrantprobe",
            project=PROJECT,
        )

    assert world.repository.list_receipts() == ()
    assert world.gateway.audit_events()[-1].reason_code == "invalid_session"


def test_ungranted_project_expired_and_revoked_grants_release_no_evidence(world):
    credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    session = world.gateway.authenticate(credential.client_id, credential.client_secret)

    with pytest.raises(AuthorizationError):
        world.gateway.retrieve(session, "sharedgrantprobe", project="ungranted")

    expiring = replace(
        world.policy.grants[0],
        expires_at=world.clock.current + timedelta(minutes=1),
    )
    world.registry.replace_policy(
        KnowledgePolicy(
            employees=world.policy.employees,
            grants=(expiring, world.policy.grants[1]),
        )
    )
    world.clock.current += timedelta(minutes=2)
    with pytest.raises(AuthorizationError):
        world.gateway.retrieve(session, "sharedgrantprobe", project=PROJECT)

    revoked = replace(
        world.policy.grants[0],
        expires_at=None,
        revoked_at=world.clock(),
    )
    world.registry.replace_policy(
        KnowledgePolicy(
            employees=world.policy.employees,
            grants=(revoked, world.policy.grants[1]),
        )
    )
    with pytest.raises(AuthorizationError):
        world.gateway.retrieve(session, "sharedgrantprobe", project=PROJECT)

    assert world.repository.list_receipts() == ()


def test_path_item_scope_and_item_permission_set_are_all_enforced(world):
    credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    session = world.gateway.authenticate(credential.client_id, credential.client_secret)

    bundle = world.gateway.retrieve(session, "scopeprobe", project=PROJECT)

    assert [evidence.item_id.source_object_id for evidence in bundle.evidence] == [
        "kb:team/target.md"
    ]
    assert bundle.evidence[0].citation.source_locator.uri.endswith("target.md")
    assert bundle.denied_count == 3
    assert len(bundle.receipts) == 1


def test_policy_replacement_with_identity_change_invalidates_session(world):
    credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    session = world.gateway.authenticate(credential.client_id, credential.client_secret)
    replacement_alice = replace(world.alice, lane="restricted-knowledge")
    replacement_grant = replace(
        world.policy.grants[0],
        lane=replacement_alice.lane,
    )
    world.registry.replace_policy(
        KnowledgePolicy(
            employees=(replacement_alice, world.bob),
            grants=(replacement_grant, world.policy.grants[1]),
        )
    )

    with pytest.raises(AuthenticationError):
        world.gateway.retrieve(session, "sharedgrantprobe", project=PROJECT)

    assert world.repository.list_receipts() == ()
    assert world.gateway.audit_events()[-1].reason_code == "invalid_session"


def test_access_audit_events_persist_digest_outcome_and_reason_without_query_text(
    world,
):
    credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    session = world.gateway.authenticate(credential.client_id, credential.client_secret)
    allowed_query = "sharedgrantprobe"
    world.gateway.retrieve(session, allowed_query, project=PROJECT)

    denied_query = "denied-project-query"
    with pytest.raises(AuthorizationError):
        world.gateway.retrieve(session, denied_query, project="ungranted")

    events = world.repository.list_access_events()
    retrieval = [event for _, event in events if event.event_type == "retrieval"]
    authorization = [
        event for _, event in events if event.event_type == "authorization"
    ]
    assert len(retrieval) == 1
    assert len(authorization) == 1

    allowed_event = retrieval[0]
    denied_event = authorization[0]
    assert not hasattr(allowed_event, "query")
    assert not hasattr(denied_event, "query")
    assert allowed_event.query_digest == compute_content_hash(allowed_query)
    assert allowed_event.outcome is AccessAuditOutcome.ALLOWED
    assert allowed_event.reason_code == "retrieved"
    assert denied_event.query_digest == compute_content_hash(denied_query)
    assert denied_event.outcome is AccessAuditOutcome.DENIED
    assert denied_event.reason_code == "project_not_granted"
    assert allowed_event.client_id == credential.client_id
    assert allowed_event.session_id == session_reference(session.session_id)

    persisted = dict(events)
    allowed_event_id = next(
        event_id for event_id, event in events if event is allowed_event
    )
    assert persisted[allowed_event_id] == allowed_event


def test_client_revocation_invalidates_all_sessions_and_releases_no_evidence(world):
    credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    first_session = world.gateway.authenticate(
        credential.client_id, credential.client_secret
    )
    second_session = world.gateway.authenticate(
        credential.client_id, credential.client_secret
    )

    assert world.registry.revoke_client(credential.client_id) is True
    for session in (first_session, second_session):
        with pytest.raises(AuthenticationError):
            world.gateway.retrieve(session, "sharedgrantprobe", project=PROJECT)

    assert world.repository.list_receipts() == ()
    lifecycle = [
        event
        for _, event in world.repository.list_access_events()
        if event.event_type == "lifecycle"
    ]
    assert any(
        event.reason_code == "client_revoked"
        and event.client_id == credential.client_id
        for event in lifecycle
    )


def test_client_state_round_trip_persists_only_verifier_material(world, tmp_path):
    state_path = tmp_path / "clients.json"
    registry = AccessRegistry(world.policy, state_path=state_path, clock=world.clock)
    credential = registry.register_client(
        world.alice.principal_id,
        client_id="alice-persistent-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )

    state = state_path.read_text(encoding="utf-8")
    assert credential.client_secret not in state
    assert '"digest":"' in state
    assert state_path.stat().st_mode & 0o777 == 0o600

    reloaded = AccessRegistry(
        world.policy,
        state_path=state_path,
        clock=world.clock,
    )
    session = reloaded.authenticate(credential.client_id, credential.client_secret)
    assert session.principal_id == world.alice.principal_id

    assert reloaded.revoke_client(credential.client_id) is True
    reloaded_again = AccessRegistry(
        world.policy,
        state_path=state_path,
        clock=world.clock,
    )
    with pytest.raises(AuthenticationError):
        reloaded_again.authenticate(credential.client_id, credential.client_secret)


def test_grant_context_mismatch_is_rejected_before_gateway_use(world):
    mismatched_grant = replace(
        world.policy.grants[0],
        scope_id="scope-from-another-lane",
    )
    with pytest.raises(ValueError, match="does not match employee context"):
        KnowledgePolicy(
            employees=world.policy.employees,
            grants=(mismatched_grant, world.policy.grants[1]),
        )


def test_expired_session_is_rejected_at_boundary(world):
    credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-expiring-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    session = world.gateway.authenticate(credential.client_id, credential.client_secret)
    world.clock.current = session.expires_at

    with pytest.raises(AuthenticationError):
        world.gateway.retrieve(session, "sharedgrantprobe", project=PROJECT)

    assert world.gateway.audit_events()[-1].reason_code == "invalid_session"


def test_access_audit_preserves_staleness_without_releasing_unaudited_evidence(world):
    credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-stale-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )
    session = world.gateway.authenticate(credential.client_id, credential.client_secret)

    bundle = world.gateway.retrieve(
        session,
        "sharedgrantprobe",
        project=PROJECT,
        freshness=FreshnessRequirement(
            max_staleness=timedelta(minutes=30),
        ),
    )

    assert bundle.freshness.is_stale is True
    assert bundle.freshness.requirement_satisfied is False
    assert len(bundle.receipts) == len(bundle.evidence)
    retrieval_events = [
        event
        for _, event in world.repository.list_access_events()
        if event.event_type == "retrieval"
    ]
    assert retrieval_events[-1].freshness_state == "stale"


def test_employee_never_inherits_owner_authority(tmp_path):
    """A grant never overrides an item ACL, and the owner cannot be impersonated."""
    clock = MutableClock(BASE_TIME)
    owner_principal_id = "lee@leebase.com"
    chief = ai_employee(
        "employee-chief-of-staff",
        "employee:chief-of-staff",
        scope_id="chief-of-staff-scope",
    )
    # Whole-source grant: every briefing path under the granted root is in scope.
    chief_grant = grant_for(
        chief,
        "grant-chief-of-staff-briefings",
        root="kb",
        path_prefix="briefings",
    )
    policy = KnowledgePolicy(employees=(chief,), grants=(chief_grant,))

    with SQLiteRepository(tmp_path / "owner-only.sqlite") as repository:
        registry, gateway = governed_stack(repository, policy, clock)
        owner_item = sync_markdown(
            repository,
            "kb:briefings/owner-only.md",
            "ownerauthorityprobe morning briefing",
            permissions=PermissionSet(
                owner=owner_principal_id,
                visibility=Visibility.PRIVATE,
            ),
        )
        # The projection answers this query; only the item ACL withholds it.
        assert len(repository.search("ownerauthorityprobe", project=PROJECT)) == 1
        assert (
            chief_grant.permits(
                employee=chief,
                address=default_source_address(owner_item),
                item=owner_item,
                operation="search",
                now=clock(),
            )
            is True
        )

        credential, session = session_for(
            registry, gateway, chief.principal_id, "chief-of-staff-client"
        )
        assert session.principal_id == chief.principal_id

        bundle = gateway.retrieve(session, "ownerauthorityprobe", project=PROJECT)

        assert bundle.evidence == ()
        assert bundle.citations == ()
        assert bundle.receipts == ()
        assert bundle.denied_count == 1
        assert repository.list_receipts() == ()

        retrieval = persisted_events(repository, event_type="retrieval")
        assert len(retrieval) == 1
        assert retrieval[0].outcome is AccessAuditOutcome.ALLOWED
        assert retrieval[0].reason_code == "retrieved"
        assert retrieval[0].freshness_state == "fresh"
        assert retrieval[0].principal.principal_id == chief.principal_id
        assert retrieval[0].grant_ids == (chief_grant.grant_id,)
        query_audit = repository.list_retrieval_events()[-1][1]
        assert (query_audit.released_count, query_audit.denied_count) == (0, 1)

        # Owner authority cannot be minted: the owner is not a policy employee.
        with pytest.raises(AuthorizationError, match="not configured"):
            registry.register_client(
                owner_principal_id,
                client_id="owner-client",
                expires_at=BASE_TIME + timedelta(days=1),
            )
        assert [info.client_id for info in registry.list_clients()] == [
            credential.client_id
        ]
        assert [info.principal_id for info in registry.list_clients()] == [
            chief.principal_id
        ]


def test_employee_zero_and_chief_of_staff_are_isolated(tmp_path):
    """Two provisioned employees share a corpus but never each other's items."""
    clock = MutableClock(BASE_TIME)
    zero = ai_employee(
        "employee-zero",
        "employee:employee-zero",
        scope_id="employee-zero-scope",
    )
    chief = ai_employee(
        "employee-chief-of-staff",
        "employee:chief-of-staff",
        scope_id="chief-of-staff-scope",
    )
    zero_grant = grant_for(
        zero, "grant-employee-zero-lane", root="kb", path_prefix="zero"
    )
    chief_grant = grant_for(
        chief, "grant-chief-of-staff-lane", root="kb", path_prefix="chief"
    )
    # Both employees are granted the same shared address space on purpose, so
    # one item there is separated by its ACL alone.
    zero_shared_grant = grant_for(
        zero, "grant-employee-zero-shared", root="kb", path_prefix="shared"
    )
    chief_shared_grant = grant_for(
        chief, "grant-chief-of-staff-shared", root="kb", path_prefix="shared"
    )
    policy = KnowledgePolicy(
        employees=(zero, chief),
        grants=(zero_grant, zero_shared_grant, chief_grant, chief_shared_grant),
    )

    with SQLiteRepository(tmp_path / "two-employees.sqlite") as repository:
        registry, gateway = governed_stack(repository, policy, clock)
        zero_item = sync_markdown(
            repository,
            "kb:zero/plan.md",
            "isolationprobe employee zero plan",
            permissions=PermissionSet(
                owner="document-owner",
                visibility=Visibility.PRIVATE,
                allowed_principals=(zero.principal_id,),
            ),
        )
        chief_item = sync_markdown(
            repository,
            "kb:chief/brief.md",
            "isolationprobe chief of staff brief",
            permissions=PermissionSet(
                owner="document-owner",
                visibility=Visibility.PRIVATE,
                allowed_principals=(chief.principal_id,),
            ),
        )
        shared_item = sync_markdown(
            repository,
            "kb:shared/roster.md",
            "isolationprobe shared roster",
            permissions=PermissionSet(
                owner="document-owner",
                visibility=Visibility.PRIVATE,
                allowed_principals=(zero.principal_id,),
            ),
        )
        # Every item answers the shared query, so any leak would be visible.
        assert len(repository.search("isolationprobe", project=PROJECT)) == 3
        # The chief's grant does cover the shared address: only the ACL denies.
        assert (
            chief_shared_grant.permits(
                employee=chief,
                address=default_source_address(shared_item),
                item=shared_item,
                operation="search",
                now=clock(),
            )
            is True
        )

        zero_credential, zero_session = session_for(
            registry, gateway, zero.principal_id, "employee-zero-client"
        )
        chief_credential, chief_session = session_for(
            registry, gateway, chief.principal_id, "chief-of-staff-client"
        )

        zero_bundle = gateway.retrieve(zero_session, "isolationprobe", project=PROJECT)
        chief_bundle = gateway.retrieve(
            chief_session, "isolationprobe", project=PROJECT
        )

        assert {item.item_id for item in zero_bundle.evidence} == {
            zero_item.item_id,
            shared_item.item_id,
        }
        assert [item.item_id for item in chief_bundle.evidence] == [chief_item.item_id]
        assert (zero_bundle.denied_count, chief_bundle.denied_count) == (1, 2)
        assert len(zero_bundle.receipts) == 2
        assert len(chief_bundle.receipts) == 1
        assert all(
            receipt.auth_context.client_id == zero_credential.client_id
            for receipt in zero_bundle.receipts
        )
        assert chief_bundle.receipts[0].auth_context.client_id == (
            chief_credential.client_id
        )
        zero_grant_ids = (zero_grant.grant_id, zero_shared_grant.grant_id)
        assert all(
            receipt.auth_context.grant_ids == zero_grant_ids
            for receipt in zero_bundle.receipts
        )
        assert chief_bundle.receipts[0].auth_context.grant_ids == (
            chief_grant.grant_id,
            chief_shared_grant.grant_id,
        )

        zero_receipts = repository.list_receipts(zero_item.item_id)
        chief_receipts = repository.list_receipts(chief_item.item_id)
        shared_receipts = repository.list_receipts(shared_item.item_id)
        assert len(zero_receipts) == 1
        assert len(chief_receipts) == 1
        assert len(shared_receipts) == 1
        assert zero_receipts[0][1].principal.principal_id == zero.principal_id
        assert chief_receipts[0][1].principal.principal_id == chief.principal_id
        # The shared item leaves only for the one principal its ACL admits.
        assert shared_receipts[0][1].principal.principal_id == zero.principal_id
        assert shared_receipts[0][1].auth_context.client_id == (
            zero_credential.client_id
        )
        assert zero_receipts[0][1].auth_context.client_id == zero_credential.client_id
        assert chief_receipts[0][1].auth_context.client_id == (
            chief_credential.client_id
        )

        retrieval = persisted_events(repository, event_type="retrieval")
        assert [
            (event.principal.principal_id, event.client_id, event.grant_ids)
            for event in retrieval
        ] == [
            (
                zero.principal_id,
                zero_credential.client_id,
                (zero_grant.grant_id, zero_shared_grant.grant_id),
            ),
            (
                chief.principal_id,
                chief_credential.client_id,
                (chief_grant.grant_id, chief_shared_grant.grant_id),
            ),
        ]
        assert [event.session_id for event in retrieval] == [
            session_reference(zero_session.session_id),
            session_reference(chief_session.session_id),
        ]


def test_grant_revoked_after_session_establishment_denies_next_request(world):
    """Revoking a grant mid-session denies the next request without unmaking it."""
    credential, session = session_for(
        world.registry, world.gateway, world.alice.principal_id, "alice-live-client"
    )
    granted = world.gateway.retrieve(session, "sharedgrantprobe", project=PROJECT)
    assert len(granted.evidence) == 1
    assert len(granted.receipts) == 1
    receipts_before = world.repository.list_receipts()
    assert len(receipts_before) == 1
    events_before = len(world.repository.list_access_events())

    revoked = replace(world.policy.grants[0], revoked_at=world.clock.current)
    world.registry.replace_policy(
        KnowledgePolicy(
            employees=world.policy.employees,
            grants=(revoked, world.policy.grants[1]),
        )
    )

    with pytest.raises(AuthorizationError, match="knowledge project is not granted"):
        world.gateway.retrieve(session, "sharedgrantprobe", project=PROJECT)

    # Actual behaviour: an authorization denial, not a session invalidation.
    denials = persisted_events(world.repository, since=events_before)
    assert [
        (event.event_type, event.outcome, event.reason_code) for event in denials
    ] == [("authorization", AccessAuditOutcome.DENIED, "project_not_granted")]
    assert denials[0].client_id == credential.client_id
    assert denials[0].session_id == session_reference(session.session_id)
    assert denials[0].principal.principal_id == world.alice.principal_id
    assert denials[0].grant_ids == ()
    assert world.repository.list_receipts() == receipts_before

    resolved = world.registry.resolve_session(session)
    assert resolved == session
    assert (
        resolved.principal_id,
        resolved.tenant,
        resolved.lane,
        resolved.scope_id,
        resolved.purpose,
    ) == (
        world.alice.principal_id,
        world.alice.tenant,
        world.alice.lane,
        world.alice.scope_id,
        world.alice.purpose,
    )


def test_granted_item_handle_cannot_be_reused_by_other_principal(tmp_path):
    """An item handle named by the wrong root stays unreachable, ACL or not."""
    clock = MutableClock(BASE_TIME)
    alpha = ai_employee("employee-alpha", "employee:alpha", scope_id="alpha-scope")
    beta = ai_employee("employee-beta", "employee:beta", scope_id="beta-scope")
    handle_id = KnowledgeItemId("local_files", "kb:team/handle.md")
    alpha_grant = grant_for(alpha, "grant-alpha-team", root="kb", path_prefix="team")
    # Beta names alpha's exact item handle, but under a root it does not hold.
    beta_grant = grant_for(
        beta,
        "grant-beta-vault",
        root="vault",
        path_prefix="handles",
        item_ids=(str(handle_id),),
    )
    policy = KnowledgePolicy(employees=(alpha, beta), grants=(alpha_grant, beta_grant))

    with SQLiteRepository(tmp_path / "handles.sqlite") as repository:
        registry, gateway = governed_stack(repository, policy, clock)
        # The item ACL deliberately admits both principals: only the address differs.
        handle_item = sync_markdown(
            repository,
            handle_id.source_object_id,
            "handleprobe shared team note",
            permissions=PermissionSet(
                owner="document-owner",
                visibility=Visibility.PRIVATE,
                allowed_principals=(alpha.principal_id, beta.principal_id),
            ),
        )
        assert handle_item.item_id == handle_id

        alpha_credential, alpha_session = session_for(
            registry, gateway, alpha.principal_id, "alpha-client"
        )
        _, beta_session = session_for(
            registry, gateway, beta.principal_id, "beta-client"
        )

        alpha_bundle = gateway.retrieve(alpha_session, "handleprobe", project=PROJECT)
        assert [item.item_id for item in alpha_bundle.evidence] == [handle_id]
        leaked_handle = str(alpha_bundle.evidence[0].item_id)

        # Beta's grant is active and names the handle; only the address fails.
        assert registry.policy.grants_for(
            beta.principal_id, project=PROJECT, now=clock()
        ) == (beta_grant,)
        assert (
            beta_grant.permits(
                employee=beta,
                address=default_source_address(handle_item),
                item=handle_item,
                operation="search",
                now=clock(),
            )
            is False
        )

        beta_bundle = gateway.retrieve(beta_session, "handleprobe", project=PROJECT)
        assert beta_bundle.evidence == ()
        assert beta_bundle.receipts == ()
        assert beta_bundle.denied_count == 1

        # Replaying the leaked handle as the query changes nothing.
        assert len(repository.search(leaked_handle, project=PROJECT)) == 1
        replayed = gateway.retrieve(beta_session, leaked_handle, project=PROJECT)
        assert replayed.evidence == ()
        assert replayed.receipts == ()
        assert replayed.denied_count == 1

        receipts = repository.list_receipts(handle_id)
        assert len(receipts) == 1
        assert receipts[0][1].principal.principal_id == alpha.principal_id
        assert receipts[0][1].auth_context.client_id == alpha_credential.client_id

        beta_retrievals = [
            event
            for event in persisted_events(repository, event_type="retrieval")
            if event.principal.principal_id == beta.principal_id
        ]
        assert len(beta_retrievals) == 2
        assert all(
            event.outcome is AccessAuditOutcome.ALLOWED
            and event.reason_code == "retrieved"
            and event.grant_ids == (beta_grant.grant_id,)
            for event in beta_retrievals
        )


def test_authentication_authorization_availability_freshness_are_distinct(world):
    """One session drives four separable states with four distinct reason codes."""
    credential = world.registry.register_client(
        world.alice.principal_id,
        client_id="alice-four-state-client",
        expires_at=BASE_TIME + timedelta(days=1),
    )

    # (a) authentication: the credential itself is not usable.
    before = len(world.repository.list_access_events())
    with pytest.raises(AuthenticationError, match="invalid or revoked client"):
        world.gateway.authenticate(credential.client_id, "not-the-secret")
    authentication = persisted_events(world.repository, since=before)
    assert [
        (event.event_type, event.outcome, event.reason_code) for event in authentication
    ] == [("authentication", AccessAuditOutcome.DENIED, "invalid_credentials")]
    assert authentication[0].principal is None
    assert authentication[0].client_id == credential.client_id
    assert world.repository.list_receipts() == ()

    session = world.gateway.authenticate(credential.client_id, credential.client_secret)

    # (b) authorization: authenticated, but the project carries no grant.
    before = len(world.repository.list_access_events())
    with pytest.raises(AuthorizationError, match="knowledge project is not granted"):
        world.gateway.retrieve(session, "sharedgrantprobe", project="ungranted")
    authorization = persisted_events(world.repository, since=before)
    assert [
        (event.event_type, event.outcome, event.reason_code) for event in authorization
    ] == [("authorization", AccessAuditOutcome.DENIED, "project_not_granted")]
    assert authorization[0].principal.principal_id == world.alice.principal_id
    assert authorization[0].grant_ids == ()
    assert world.repository.list_receipts() == ()

    # (c) freshness: granted and permitted, but the projection is too old.
    before = len(world.repository.list_access_events())
    with pytest.raises(StaleEvidenceError):
        world.gateway.retrieve(
            session,
            "sharedgrantprobe",
            project=PROJECT,
            freshness=FreshnessRequirement(
                max_staleness=timedelta(minutes=30),
                fail_on_stale=True,
            ),
        )
    refused = persisted_events(world.repository, since=before)
    assert [
        (event.event_type, event.outcome, event.reason_code) for event in refused
    ] == [("retrieval", AccessAuditOutcome.DENIED, "retrieval_failed")]
    assert refused[0].freshness_state is None
    assert world.repository.list_receipts() == ()
    stale_query_audit = world.repository.list_retrieval_events()[-1][1]
    assert stale_query_audit.status is RetrievalAuditStatus.STALE_REFUSED
    assert stale_query_audit.released_count == 0

    # (c') the same staleness, reported instead of refused, still marks the row.
    before = len(world.repository.list_access_events())
    reported = world.gateway.retrieve(
        session,
        "sharedgrantprobe",
        project=PROJECT,
        freshness=FreshnessRequirement(max_staleness=timedelta(minutes=30)),
    )
    assert reported.freshness.is_stale is True
    assert reported.freshness.requirement_satisfied is False
    assert len(reported.evidence) == 1
    assert len(reported.receipts) == 1
    stale_row = persisted_events(
        world.repository, event_type="retrieval", since=before
    )[-1]
    assert stale_row.reason_code == "retrieved"
    assert stale_row.freshness_state == "stale"

    # (d) fresh and granted: evidence with receipts.
    before = len(world.repository.list_access_events())
    fresh = world.gateway.retrieve(
        session,
        "sharedgrantprobe",
        project=PROJECT,
        freshness=FreshnessRequirement(max_staleness=timedelta(hours=2)),
    )
    assert fresh.freshness.is_stale is False
    assert fresh.freshness.requirement_satisfied is True
    assert len(fresh.evidence) == 1
    assert len(fresh.receipts) == 1
    fresh_row = persisted_events(
        world.repository, event_type="retrieval", since=before
    )[-1]
    assert fresh_row.reason_code == "retrieved"
    assert fresh_row.freshness_state == "fresh"
    assert len(world.repository.list_receipts()) == 2

    reason_codes = {
        authentication[0].reason_code,
        authorization[0].reason_code,
        refused[0].reason_code,
        fresh_row.reason_code,
    }
    assert len(reason_codes) == 4
    assert (stale_row.freshness_state, fresh_row.freshness_state) == (
        "stale",
        "fresh",
    )


def test_cross_tenant_grant_cannot_enter_a_policy(world):
    """Policy construction is the only tenant boundary, so it must hold.

    ``KnowledgeGrant.permits`` re-checks lane, scope, and purpose but not
    tenant, which makes this construction-time rejection load-bearing for any
    caller that builds a grant evaluator from a policy's grants.
    """
    other_tenant = replace(world.alice, tenant="tenant-two")
    with pytest.raises(ValueError, match="crosses tenant boundary"):
        KnowledgePolicy(
            employees=(other_tenant, world.bob),
            grants=(world.policy.grants[0], world.policy.grants[1]),
        )

    # The same rejection applies when the grant, not the employee, is moved.
    with pytest.raises(ValueError, match="crosses tenant boundary"):
        KnowledgePolicy(
            employees=world.policy.employees,
            grants=(
                replace(world.policy.grants[0], tenant="tenant-two"),
                world.policy.grants[1],
            ),
        )

    # No credential, session, or receipt may come from a rejected policy.
    assert world.registry.policy is world.policy
    assert world.registry.list_clients() == ()
    assert world.repository.list_receipts() == ()
    assert world.repository.list_access_events() == ()


def test_operator_grant_alone_cannot_release_private_mail_shaped_items(tmp_path):
    """A grant naming a mail connector's namespace/root is not the second key.

    Non-local connectors map to ``SourceAddress(connector_id, connector_id,
    source_object_id, item_id)``, so an operator COULD write a grant whose
    namespace/root equal an ``outlook_mail:...`` connector id. That grant must
    still release nothing when the item's source-owner ACL names a different
    principal — private Mail/Calendar stays two-key.
    """
    connector_id = "outlook_mail:personal:folder-inbox:default"
    clock = MutableClock(BASE_TIME)
    repository = SQLiteRepository(tmp_path / "knowledge.sqlite")
    try:
        item_id = KnowledgeItemId(connector_id, "message:abc123")
        text = "quarterly payroll approval thread"
        item = KnowledgeItem(
            item_id=item_id,
            project=PROJECT,
            source_locator=SourceLocator(
                connector_id=connector_id,
                uri="https://graph.example.invalid/messages/abc123",
                label="message:abc123",
            ),
            document_type=DocumentType.PLAIN_TEXT,
            content_hash=compute_content_hash(text),
            source_timestamp=SOURCE_TIME,
            sync_timestamp=SYNC_TIME,
            permissions=PermissionSet(
                owner="owner@example.invalid",
                visibility=Visibility.PRIVATE,
                allowed_principals=("employee:employee-zero",),
            ),
            title="message:abc123",
        )
        repository.sync_item(
            item,
            chunk_document(
                text,
                item_id=item_id,
                project=PROJECT,
                document_type=DocumentType.PLAIN_TEXT,
            ),
        )

        chief = ai_employee(
            "chief-of-staff", "employee:chief-of-staff", scope_id="ops-scope"
        )
        mail_grant = KnowledgeGrant(
            grant_id="grant:chief:mail-connector",
            principal_id=chief.principal_id,
            tenant=chief.tenant,
            lane=chief.lane,
            scope_id=chief.scope_id,
            purpose=chief.purpose,
            project=PROJECT,
            source_namespace=connector_id,
            root=connector_id,
            path_prefix="*",
            operations=frozenset({"search", "read", "cite"}),
        )
        policy = KnowledgePolicy(employees=(chief,), grants=(mail_grant,))
        registry, gateway = governed_stack(repository, policy, clock)
        _credential, session = session_for(
            registry, gateway, chief.principal_id, "chief:probe-client"
        )

        bundle = gateway.retrieve(session, "quarterly payroll", project=PROJECT)

        assert bundle.evidence == ()
        assert bundle.receipts == ()
        assert bundle.denied_count == 1
        retrievals = persisted_events(repository, event_type="retrieval")
        assert [event.outcome.value for event in retrievals] == ["allowed"]
        assert retrievals[0].principal.principal_id == "employee:chief-of-staff"
    finally:
        repository.close()
