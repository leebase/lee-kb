"""Owner-native tests for the S1C owner contract.

Every rule the frozen contract names is asserted here, including the denial
paths, because the acceptance artifact mutates the implementation and requires
this suite to notice. The file is deliberately self-contained: the mutation
probe copies it next to a private copy of the package and nothing else.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lee_kb.chunking import chunk_document
from lee_kb.contracts import (
    OWNER_CONTRACT_VERSION,
    OWNER_CORPUS_VERSION,
    OWNER_HISTORICAL_VERSION,
    OWNER_MAPPING_VERSION,
    OWNER_PERMISSION_VERSION,
    OWNER_RECEIPT_VERSION,
    OWNER_SCHEMA_VERSION,
    DocumentType,
    HistoricalLocator,
    HistoricalReleaseManifest,
    HistoricalReleaseRule,
    ImmutableHistoricalObject,
    KnowledgeItem,
    KnowledgeItemId,
    OwnerFreshnessState,
    OwnerIdentityMapping,
    OwnerKnowledgeState,
    PermissionSet,
    PolicyBasis,
    Principal,
    SourceGrant,
    SourceLocator,
    Visibility,
    compute_content_hash,
)
from lee_kb.governance import ExactHistoricalReader
from lee_kb.owner import (
    OWNER_ACCESS_DENIED,
    OWNER_API_VERSION,
    OWNER_NAME,
    GitExactObjectResolver,
    OwnerAccessError,
    OwnerConfigurationError,
    OwnerGateway,
    _MappedPermissionEvaluator,
    load_owner_gateway,
    owner_handshake,
)
from lee_kb.repository import SQLiteRepository

NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)
COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "1123456789abcdef0123456789abcdef01234567"
BODY = "immutable body"
ITEM_ID = "local_files:docs/fact.md"


def _grant(path_prefix: str = "docs") -> SourceGrant:
    return SourceGrant("default", "local_files", "notes", path_prefix, (ITEM_ID,))


def _locator(commit: str = COMMIT, path: str = "docs/fact.md") -> HistoricalLocator:
    return HistoricalLocator("kb", commit, path)


def _basis(name: str, decision: str, *, live: bool = True) -> PolicyBasis:
    evaluated = NOW - timedelta(minutes=1)
    expires = NOW + timedelta(hours=1)
    if not live:
        evaluated = NOW - timedelta(hours=2)
        expires = NOW - timedelta(hours=1)
    return PolicyBasis(
        f"{name}/v1", compute_content_hash(name), decision, evaluated, expires
    )


class _CountingResolver:
    """Exact-object seam that records whether a denial reached the body."""

    def __init__(self, obj: ImmutableHistoricalObject) -> None:
        self._object = obj
        self.calls = 0

    def __call__(self, locator: HistoricalLocator):
        self.calls += 1
        return self._object if locator == self._object.locator else None


def _reader(
    *,
    grants: tuple[SourceGrant, ...] | None = None,
    manifest_rules: tuple[HistoricalReleaseRule, ...] | None = None,
    manifest_expires: datetime | None = None,
    current: str = "allow",
    current_permission_present: bool = True,
    resolver: object = "default",
    object_classification: str = "public",
) -> tuple[ExactHistoricalReader, _CountingResolver | None]:
    locator = _locator()
    mapping = OwnerIdentityMapping.default(grants or (_grant(),))
    if manifest_rules is None:
        manifest_rules = (
            HistoricalReleaseRule(
                "lee@leebase.com",
                "default",
                locator,
                "public",
                _basis("history", "allow"),
            ),
        )
    manifest = (
        None
        if manifest_rules == ()
        else HistoricalReleaseManifest.from_rules(
            manifest_rules, expires_at=manifest_expires
        )
    )
    counting: _CountingResolver | None = None
    if resolver == "default":
        counting = _CountingResolver(
            ImmutableHistoricalObject(
                locator,
                BODY,
                compute_content_hash(BODY),
                NOW,
                object_classification,
            )
        )
        seam: object = counting
    else:
        seam = resolver
    basis = _basis("current", current)
    return (
        ExactHistoricalReader(
            mapping=mapping,
            manifest=manifest,
            current_permission=(
                (lambda *_: basis) if current_permission_present else None
            ),
            resolver=seam,
            clock=lambda: NOW,
        ),
        counting,
    )


def _lookup(reader: ExactHistoricalReader, **overrides):
    arguments = {
        "authenticated_principal": "lee",
        "locator": _locator(),
        "classification": "public",
        "source_namespace": "local_files",
        "root": "notes",
        "item_id": ITEM_ID,
    }
    arguments.update(overrides)
    return reader.lookup(**arguments)


def _knowledge_item(path: str = "docs/fact.md", owner: str = "lee@leebase.com"):
    return KnowledgeItem(
        item_id=KnowledgeItemId("local_files", path),
        project="default",
        source_locator=SourceLocator("local_files", f"file:///probe/{path}"),
        document_type=DocumentType.MARKDOWN,
        content_hash=compute_content_hash(BODY),
        source_timestamp=NOW,
        sync_timestamp=NOW,
        permissions=PermissionSet(owner, Visibility.PRIVATE),
    )


# --------------------------------------------------------------------------- #
# identity mapping and mapped scope
# --------------------------------------------------------------------------- #
def test_mapping_is_server_owned_and_client_identity_cannot_widen():
    mapping = OwnerIdentityMapping.default(
        (SourceGrant("default", "local_files", "notes", "docs"),)
    )
    identity = mapping.resolve("lee")
    assert identity.principal_id == "lee@leebase.com"
    assert identity.principal.groups == ()
    try:
        mapping.resolve("other")
    except PermissionError:
        pass
    else:
        raise AssertionError("client principal widened mapping")


def test_ungranted_project_is_rejected_before_retrieval():
    mapping = OwnerIdentityMapping.default((_grant(),))
    with pytest.raises(PermissionError):
        mapping.resolve("lee", project="ungranted")
    gateway = OwnerGateway(
        None, mapping=mapping, source_mapping=lambda item: ("local_files", "notes", "x")
    )
    with pytest.raises(OwnerAccessError) as denied:
        gateway.retrieve_current(
            "anything", authenticated_principal="lee", project="ungranted"
        )
    # Retrieval never ran: the repository handle was never touched.
    assert str(denied.value) == OWNER_ACCESS_DENIED


def test_grants_narrow_namespace_root_path_and_item():
    mapping = OwnerIdentityMapping.default((_grant(),))
    identity = mapping.resolve("lee")
    permitted = dict(
        source_namespace="local_files",
        root="notes",
        path="docs/fact.md",
        item_id=ITEM_ID,
    )
    assert mapping.permits(identity, **permitted)
    for widened in (
        dict(permitted, source_namespace="other_files"),
        dict(permitted, root="other"),
        dict(permitted, path="secret/x.md"),
        dict(permitted, item_id="local_files:docs/other.md"),
    ):
        assert not mapping.permits(identity, **widened), widened


def test_multi_project_requires_one_explicit_granted_project():
    mapping = OwnerIdentityMapping.default(
        (_grant(), SourceGrant("second", "local_files", "notes", "docs"))
    )
    with pytest.raises(PermissionError):
        mapping.resolve("lee")
    first = mapping.resolve("lee", project="default")
    second = mapping.resolve("lee", project="second")
    assert (first.project, second.project) == ("default", "second")
    assert len(first.grants) == 1 and len(second.grants) == 1
    assert first.grants[0].project == "default"
    assert second.grants[0].project == "second"

    gateway = OwnerGateway(
        None, mapping=mapping, source_mapping=lambda item: ("local_files", "notes", "x")
    )

    # Ambiguous, ungranted and unmapped selections are refused identically,
    # before any retrieval, so no answer says which one failed.
    def refusal(**arguments) -> str:
        with pytest.raises(OwnerAccessError) as denied:
            gateway.retrieve_current("anything", **arguments)
        return str(denied.value)

    assert {
        refusal(authenticated_principal="lee"),
        refusal(authenticated_principal="lee", project="third"),
        refusal(authenticated_principal="delegate-of-lee", project="default"),
    } == {OWNER_ACCESS_DENIED}


def test_current_release_requires_the_mapped_permission():
    identity = OwnerIdentityMapping.default((_grant(),)).resolve("lee")
    item = _knowledge_item()
    in_grant = _MappedPermissionEvaluator(
        identity, lambda _: ("local_files", "notes", "docs/fact.md")
    )
    out_of_grant = _MappedPermissionEvaluator(
        identity, lambda _: ("local_files", "notes", "secret/x.md")
    )
    wrong_root = _MappedPermissionEvaluator(
        identity, lambda _: ("local_files", "other", "docs/fact.md")
    )
    unmapped_source = _MappedPermissionEvaluator(identity, None)
    assert in_grant.is_permitted(item, identity.principal)
    assert not out_of_grant.is_permitted(item, identity.principal)
    assert not wrong_root.is_permitted(item, identity.principal)
    assert not unmapped_source.is_permitted(item, identity.principal)
    assert not in_grant.is_permitted(item, Principal("mallory@example.invalid"))
    # An item the mapped principal cannot read is denied even inside the grant.
    assert not in_grant.is_permitted(
        _knowledge_item(owner="someone-else@example.invalid"), identity.principal
    )


def test_retrieve_current_binds_the_owner_receipt_to_mapping_and_policy(tmp_path):
    text = "# Governed\n\nzephyrgrove receipts stay bound to the mapping.\n"
    item_id = KnowledgeItemId("local_files", "notes:fact.md")
    item = KnowledgeItem(
        item_id=item_id,
        project="default",
        source_locator=SourceLocator(
            "local_files", "file:///probe/notes/fact.md", label="fact.md"
        ),
        document_type=DocumentType.MARKDOWN,
        content_hash=compute_content_hash(text),
        source_timestamp=NOW,
        sync_timestamp=NOW,
        permissions=PermissionSet("lee@leebase.com", Visibility.PRIVATE),
    )
    grant = SourceGrant("default", "local_files", "notes", "*")
    with SQLiteRepository(tmp_path / "knowledge.sqlite") as repository:
        repository.sync_item(
            item,
            chunk_document(
                text,
                item_id=item_id,
                project="default",
                document_type=DocumentType.MARKDOWN,
            ),
        )
        gateway = OwnerGateway(
            repository,
            mapping=OwnerIdentityMapping.default((grant,)),
            source_mapping=lambda value: (
                "local_files",
                value.item_id.source_object_id.split(":", 1)[0],
                value.item_id.source_object_id.split(":", 1)[1],
            ),
        )
        result = gateway.retrieve_current("zephyrgrove", authenticated_principal="lee")

    assert result.knowledge_state is OwnerKnowledgeState.KNOWN
    assert result.identity.principal_id == "lee@leebase.com"
    assert len(result.receipts) == len(result.bundle.receipts) >= 1
    receipt = result.receipts[0]
    assert receipt.mapping_version == OWNER_MAPPING_VERSION
    assert receipt.mapping_hash == result.identity.mapping_hash
    assert receipt.policy_version == OWNER_PERMISSION_VERSION
    assert receipt.policy_decision == "allow"
    assert (receipt.source_namespace, receipt.root, receipt.path) == (
        "local_files",
        "notes",
        "fact.md",
    )
    assert receipt.classification == Visibility.PRIVATE.value
    assert receipt.freshness_state is OwnerFreshnessState.FRESH
    assert receipt.audit_id.startswith("audit-")
    assert receipt.receipt_version == OWNER_RECEIPT_VERSION


# --------------------------------------------------------------------------- #
# exact-history locator, manifest and release
# --------------------------------------------------------------------------- #
def test_exact_locator_rejects_patterns_traversal_and_refs():
    for arguments in (
        ("kb", COMMIT, "docs/*.md"),
        ("kb", COMMIT, "docs/../etc/passwd"),
        ("kb", COMMIT, "/etc/passwd"),
        ("kb", COMMIT, "docs//fact.md"),
        ("kb", "0123456", "docs/fact.md"),
        ("kb", "main", "docs/fact.md"),
        ("kb", COMMIT.upper(), "docs/fact.md"),
    ):
        with pytest.raises((TypeError, ValueError)):
            HistoricalLocator(*arguments)
    assert _locator().as_tuple() == ("kb", COMMIT, "docs/fact.md")


def test_history_requires_current_and_historical_policy_bases():
    denied_history = HistoricalReleaseRule(
        "lee@leebase.com", "default", _locator(), "public", _basis("history", "deny")
    )
    reader, resolver = _reader(manifest_rules=(denied_history,))
    result = _lookup(reader)
    assert result.knowledge_state is OwnerKnowledgeState.UNAUTHORIZED
    assert result.body is None
    assert resolver.calls == 0

    reader, resolver = _reader(current="deny")
    result = _lookup(reader)
    assert result.knowledge_state in {
        OwnerKnowledgeState.UNKNOWN,
        OwnerKnowledgeState.UNAUTHORIZED,
    }
    assert result.body is None
    assert resolver.calls == 0

    reader, resolver = _reader(current_permission_present=False)
    result = _lookup(reader)
    assert result.knowledge_state is OwnerKnowledgeState.UNKNOWN
    assert result.body is None
    assert resolver.calls == 0


def test_exact_success_has_complete_receipt_and_immutable_hash():
    reader, _ = _reader()
    result = _lookup(reader)
    assert result.knowledge_state is OwnerKnowledgeState.KNOWN
    assert result.freshness_state is OwnerFreshnessState.FRESH
    assert result.body == BODY
    receipt = result.receipt
    assert receipt is not None
    assert receipt.locator == _locator()
    assert receipt.classification == "public"
    assert receipt.mapped_principal_id == "lee@leebase.com"
    assert receipt.current_policy_decision == "allow"
    assert receipt.historical_policy_decision == "allow"
    assert receipt.historical_manifest_hash
    assert receipt.blob_hash == compute_content_hash(BODY)
    assert receipt.blob_timestamp == NOW
    assert receipt.evaluation_time == NOW
    assert receipt.audit_id.startswith("audit-")


def test_missing_manifest_and_mismatched_classification_release_no_body():
    reader, _ = _reader(manifest_rules=())
    missing = _lookup(reader)
    assert missing.knowledge_state is OwnerKnowledgeState.UNKNOWN
    assert missing.body is None
    assert missing.error is None

    # A classification the manifest does not name is never covered, even when
    # the object itself carries exactly that classification.
    reader, resolver = _reader(object_classification="confidential")
    mismatched = _lookup(reader, classification="confidential")
    assert mismatched.knowledge_state is OwnerKnowledgeState.UNKNOWN
    assert mismatched.body is None
    assert mismatched.error is None
    assert resolver.calls == 0
    manifest = HistoricalReleaseManifest.from_rules(
        (
            HistoricalReleaseRule(
                "lee@leebase.com",
                "default",
                _locator(),
                "public",
                _basis("history", "allow"),
            ),
        )
    )
    covered = dict(
        principal_id="lee@leebase.com",
        project="default",
        locator=_locator(),
        at=NOW,
    )
    assert manifest.evaluate(classification="public", **covered).decision == "allow"
    mismatched_rule = manifest.evaluate(classification="confidential", **covered)
    assert mismatched_rule.decision != "allow"
    # The two withheld answers are indistinguishable on the wire.
    assert (missing.knowledge_state, missing.freshness_state, missing.body) == (
        mismatched.knowledge_state,
        mismatched.freshness_state,
        mismatched.body,
    )


def test_locator_outside_the_manifest_releases_no_body():
    """The grant admits these locators; only the manifest does not cover them."""
    reader, resolver = _reader()
    for locator in (
        _locator(commit=OTHER_COMMIT),
        _locator(path="docs/other.md"),
    ):
        result = _lookup(reader, locator=locator)
        assert result.knowledge_state is OwnerKnowledgeState.UNKNOWN
        assert result.body is None
        assert result.receipt is not None
        assert result.receipt.current_policy_decision == "allow"
    assert resolver.calls == 0


def test_ambiguous_manifest_rules_release_no_body():
    locator = _locator()
    reader, resolver = _reader(
        manifest_rules=(
            HistoricalReleaseRule(
                "lee@leebase.com",
                "default",
                locator,
                "public",
                _basis("history", "allow"),
            ),
            HistoricalReleaseRule(
                "lee@leebase.com",
                "default",
                locator,
                "public",
                _basis("history-second", "allow"),
            ),
        )
    )
    result = _lookup(reader)
    assert result.knowledge_state is OwnerKnowledgeState.UNKNOWN
    assert result.body is None
    assert resolver.calls == 0


def test_expired_manifest_releases_no_body():
    reader, resolver = _reader(manifest_expires=NOW - timedelta(minutes=1))
    result = _lookup(reader)
    assert result.knowledge_state is OwnerKnowledgeState.UNKNOWN
    assert result.body is None
    assert resolver.calls == 0


def test_stale_historical_basis_releases_no_body():
    reader, resolver = _reader(
        manifest_rules=(
            HistoricalReleaseRule(
                "lee@leebase.com",
                "default",
                _locator(),
                "public",
                _basis("history", "allow", live=False),
            ),
        )
    )
    result = _lookup(reader)
    assert result.knowledge_state is OwnerKnowledgeState.UNKNOWN
    assert result.body is None
    assert resolver.calls == 0


def test_absent_resolver_releases_no_body():
    """Repository reachability cannot substitute for the exact-object seam."""
    reader, _ = _reader(resolver=None)
    result = _lookup(reader)
    assert result.knowledge_state is OwnerKnowledgeState.UNKNOWN
    assert result.body is None
    assert result.receipt is not None

    def failing(_locator_value):
        raise RuntimeError("source unavailable")

    reader, _ = _reader(resolver=failing)
    degraded = _lookup(reader)
    assert degraded.knowledge_state is OwnerKnowledgeState.UNKNOWN
    assert degraded.body is None


def test_widened_path_is_denied_before_the_object_seam():
    reader, resolver = _reader()
    result = _lookup(reader, locator=_locator(path="secret/x.md"), item_id=None)
    assert result.knowledge_state is OwnerKnowledgeState.UNAUTHORIZED
    assert result.body is None
    assert result.receipt is not None
    assert result.receipt.current_policy_decision == "deny"
    assert resolver.calls == 0


def test_unmapped_principal_is_denied_before_the_object_seam():
    reader, resolver = _reader()
    result = _lookup(reader, authenticated_principal="delegate-of-lee")
    assert result.knowledge_state is OwnerKnowledgeState.UNKNOWN
    assert result.body is None
    assert result.receipt is None
    assert result.error is None
    assert resolver.calls == 0


# --------------------------------------------------------------------------- #
# handshake, exact-object resolver and deployment configuration
# --------------------------------------------------------------------------- #
def test_owner_handshake_names_every_version():
    mapping = OwnerIdentityMapping.default((_grant(),))
    handshake = owner_handshake(mapping)
    assert handshake == {
        "owner": OWNER_NAME,
        "api_version": OWNER_API_VERSION,
        "contract_version": OWNER_CONTRACT_VERSION,
        "schema_version": OWNER_SCHEMA_VERSION,
        "corpus_version": OWNER_CORPUS_VERSION,
        "mapping_version": mapping.version,
        "mapping_hash": mapping.mapping_hash,
        "permission_version": OWNER_PERMISSION_VERSION,
        "receipt_version": OWNER_RECEIPT_VERSION,
        "historical_version": OWNER_HISTORICAL_VERSION,
    }
    assert handshake["mapping_hash"] != OwnerIdentityMapping().mapping_hash


def _git_repository(root: Path, *, body: str = "released body\n") -> tuple[Path, str]:
    worktree = root / "history"
    (worktree / "docs").mkdir(parents=True)
    (worktree / "docs" / "fact.md").write_text(body, encoding="utf-8")
    (worktree / "docs" / "other.md").write_text("unreleased\n", encoding="utf-8")
    identity = ["-c", "user.name=probe", "-c", "user.email=probe@example.invalid"]
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(worktree)], check=True, timeout=30
    )
    subprocess.run(
        ["git", "-C", str(worktree), *identity, "add", "docs"], check=True, timeout=30
    )
    subprocess.run(
        ["git", "-C", str(worktree), *identity, "commit", "-q", "-m", "release"],
        check=True,
        timeout=30,
    )
    commit = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    return worktree, commit


def test_git_exact_object_resolver_reads_exactly_one_named_object(tmp_path):
    worktree, commit = _git_repository(tmp_path)
    locator = HistoricalLocator("history", commit, "docs/fact.md")
    resolver = GitExactObjectResolver({"history": worktree}, lambda _: "public")

    obj = resolver.resolve(locator)
    assert obj is not None
    assert obj.locator == locator
    assert obj.body == "released body\n"
    assert obj.blob_hash == compute_content_hash("released body\n")
    assert obj.blob_timestamp.tzinfo is not None
    assert obj.classification == "public"
    assert resolver.repositories == ("history",)


def test_git_exact_object_resolver_refuses_everything_outside_one_object(tmp_path):
    worktree, commit = _git_repository(tmp_path)
    resolver = GitExactObjectResolver({"history": worktree}, lambda _: "public")

    # Repository names outside the allowlist are unreadable, even when the
    # path on disk is right there.
    assert resolver.resolve(HistoricalLocator("other", commit, "docs/fact.md")) is None
    # A commit that does not exist, and a path that does not exist in it.
    assert (
        resolver.resolve(HistoricalLocator("history", OTHER_COMMIT, "docs/fact.md"))
        is None
    )
    assert (
        resolver.resolve(HistoricalLocator("history", commit, "docs/missing.md"))
        is None
    )
    # A tree is not a blob.
    assert resolver.resolve(HistoricalLocator("history", commit, "docs")) is None
    # No declared classification means no release.
    unclassified = GitExactObjectResolver({"history": worktree}, lambda _: None)
    assert (
        unclassified.resolve(HistoricalLocator("history", commit, "docs/fact.md"))
        is None
    )
    # Oversized objects are refused before the body is returned.
    bounded = GitExactObjectResolver(
        {"history": worktree}, lambda _: "public", max_bytes=4
    )
    assert bounded.resolve(HistoricalLocator("history", commit, "docs/fact.md")) is None
    # A hung or missing git binary degrades to no object, never an exception.
    absent = GitExactObjectResolver(
        {"history": worktree}, lambda _: "public", git="git-that-does-not-exist"
    )
    assert absent.resolve(HistoricalLocator("history", commit, "docs/fact.md")) is None
    impatient = GitExactObjectResolver(
        {"history": worktree}, lambda _: "public", timeout=0.000001
    )
    assert (
        impatient.resolve(HistoricalLocator("history", commit, "docs/fact.md")) is None
    )


def _config(commit: str, worktree: Path) -> dict:
    return {
        "owner_gateway": {
            "project": "default",
            "mapping": {
                "authenticated_principal": "lee",
                "principal_id": "lee@leebase.com",
                "grants": [
                    {
                        "project": "default",
                        "source_namespace": "local_files",
                        "root": "notes",
                        "path_prefix": "docs",
                    }
                ],
            },
            "historical_release": {
                "version": OWNER_HISTORICAL_VERSION,
                "rules": [
                    {
                        "repository": "history",
                        "commit": commit,
                        "path": "docs/fact.md",
                        "classification": "public",
                        "principals": ["lee@leebase.com"],
                        "projects": ["default"],
                        "source_namespace": "local_files",
                        "root": "notes",
                    }
                ],
            },
            "repositories": {"history": str(worktree)},
        }
    }


def test_owner_gateway_configuration_builds_the_mapping_and_manifest(tmp_path):
    worktree, commit = _git_repository(tmp_path)
    config = load_owner_gateway(_config(commit, worktree))
    assert config is not None
    assert load_owner_gateway({"schema": 1}) is None

    assert config.mapping.principal_id == "lee@leebase.com"
    assert config.mapping.version == OWNER_MAPPING_VERSION
    assert config.mapping.mapping_hash
    assert config.projects() == ("default",)
    assert config.manifest is not None
    assert config.manifest.version == OWNER_HISTORICAL_VERSION
    assert config.manifest.manifest_hash

    locator = HistoricalLocator("history", commit, "docs/fact.md")
    scope = config.scope_for(locator)
    assert scope is not None
    assert (scope.source_namespace, scope.root) == ("local_files", "notes")
    assert config.classification_for(locator) == "public"
    assert config.scope_for(HistoricalLocator("history", OTHER_COMMIT, "d.md")) is None
    assert config.repository_paths() == {"history": str(worktree)}

    identity = config.mapping.resolve("lee", project="default")
    permission = config.current_permission()
    assert permission(identity, locator, "public").decision == "allow"
    assert permission(identity, locator, "confidential").decision == "unknown"
    assert (
        permission(
            identity, HistoricalLocator("history", commit, "docs/other.md"), "public"
        ).decision
        == "unknown"
    )


def test_owner_gateway_configuration_fails_closed_on_drift(tmp_path):
    worktree, commit = _git_repository(tmp_path)
    drifted = _config(commit, worktree)
    drifted["owner_gateway"]["mapping"]["mapping_hash"] = compute_content_hash("wrong")
    with pytest.raises(OwnerConfigurationError):
        load_owner_gateway(drifted)

    drifted = _config(commit, worktree)
    drifted["owner_gateway"]["historical_release"]["manifest_hash"] = (
        compute_content_hash("wrong")
    )
    with pytest.raises(OwnerConfigurationError):
        load_owner_gateway(drifted)

    for mutate in (
        lambda section: section["mapping"].__setitem__("grants", []),
        lambda section: section.__setitem__("project", "ungranted"),
        lambda section: section["repositories"].__setitem__("history", "relative/path"),
        lambda section: section["historical_release"]["rules"][0].__setitem__(
            "commit", "main"
        ),
        lambda section: section["historical_release"]["rules"][0].__setitem__(
            "principals", []
        ),
        lambda section: section["historical_release"].__setitem__("rules", []),
        lambda section: section["historical_release"]["rules"][0].__setitem__(
            "not_after", "2027-01-01T00:00:00"
        ),
    ):
        broken = _config(commit, worktree)
        mutate(broken["owner_gateway"])
        with pytest.raises(OwnerConfigurationError):
            load_owner_gateway(broken)


def test_configured_gateway_releases_one_exact_object_and_denies_the_rest(tmp_path):
    worktree, commit = _git_repository(tmp_path)
    config = load_owner_gateway(_config(commit, worktree))
    gateway = OwnerGateway(
        None,
        mapping=config.mapping,
        manifest=config.manifest,
        current_permission=config.current_permission(),
        resolver=GitExactObjectResolver(
            config.repository_paths(), config.classification_for
        ),
    )

    def release(path: str = "docs/fact.md", classification: str = "public"):
        locator = HistoricalLocator("history", commit, path)
        scope = config.scope_for(locator)
        return gateway.retrieve_history(
            authenticated_principal="lee",
            locator=locator,
            classification=classification,
            source_namespace="local_files" if scope is None else scope.source_namespace,
            root="notes" if scope is None else scope.root,
            item_id=None if scope is None else scope.item_id,
            project="default",
        )

    released = release()
    assert released.knowledge_state is OwnerKnowledgeState.KNOWN
    assert released.body == "released body\n"
    receipt = released.receipt
    assert receipt is not None
    assert receipt.historical_manifest_hash == config.manifest.manifest_hash
    assert receipt.current_policy_version == OWNER_PERMISSION_VERSION
    assert receipt.historical_policy_version == OWNER_HISTORICAL_VERSION
    assert receipt.blob_hash == compute_content_hash("released body\n")

    for withheld in (release(classification="confidential"), release("docs/other.md")):
        assert withheld.knowledge_state is not OwnerKnowledgeState.KNOWN
        assert withheld.body is None
