"""Contract tests for the normalized domain model.

Coverage: construction of every contract, immutability, required-project
enforcement, retrieval receipt field completeness, and the invariants the
locked architecture decisions depend on.
"""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.contracts import (
    DEFAULT_PROJECT,
    Authority,
    ChangeType,
    Chunk,
    ChunkId,
    ChunkKind,
    Citation,
    DateRange,
    DocumentType,
    Evidence,
    EvidenceBundle,
    FreshnessReport,
    FreshnessRequirement,
    JournalEntry,
    KnowledgeItem,
    KnowledgeItemId,
    MetadataFilters,
    PermissionSet,
    Principal,
    PrincipalType,
    RetrievalReceipt,
    RetrieveRequest,
    RetrieverRank,
    SourceLocator,
    Trust,
    compute_content_hash,
)

SOURCE_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
SYNC_TIME = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
RETRIEVAL_TIME = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)

HASH_A = compute_content_hash("chunk one")
HASH_B = compute_content_hash("chunk two")


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def make_item_id(source_object_id: str = "notes/decisions.md") -> KnowledgeItemId:
    return KnowledgeItemId("local_files", source_object_id)


def make_locator(item_id: KnowledgeItemId) -> SourceLocator:
    return SourceLocator(
        connector_id=item_id.connector_id,
        uri=f"file:///home/lee/{item_id.source_object_id}",
        label=item_id.source_object_id,
    )


def make_permissions() -> PermissionSet:
    return PermissionSet(owner="lee@leebase.com")


def make_item(**overrides) -> KnowledgeItem:
    item_id = overrides.pop("item_id", make_item_id())
    defaults = {
        "item_id": item_id,
        "project": DEFAULT_PROJECT,
        "source_locator": make_locator(item_id),
        "document_type": DocumentType.MARKDOWN,
        "content_hash": HASH_A,
        "source_timestamp": SOURCE_TIME,
        "sync_timestamp": SYNC_TIME,
        "permissions": make_permissions(),
    }
    defaults.update(overrides)
    return KnowledgeItem(**defaults)


def make_chunk_id(item_id: KnowledgeItemId, ordinal: int = 0, digest: str = HASH_A):
    return ChunkId(item_id=item_id, chunk_ordinal=ordinal, content_hash=digest)


def make_principal() -> Principal:
    return Principal(
        principal_id="lee@leebase.com",
        principal_type=PrincipalType.HUMAN,
        display_name="Lee",
    )


def make_request(**overrides) -> RetrieveRequest:
    defaults = {
        "query": "why was the projection made disposable",
        "principal": make_principal(),
        "project": DEFAULT_PROJECT,
        "top_k": 5,
    }
    defaults.update(overrides)
    return RetrieveRequest(**defaults)


def make_evidence(chunk_id: ChunkId, fused_rank: int = 1) -> Evidence:
    citation = Citation(
        item_id=chunk_id.item_id,
        chunk_id=chunk_id,
        source_locator=make_locator(chunk_id.item_id),
        heading="Persistence",
        authority=Authority.CANONICAL,
        trust=Trust.HUMAN_AUTHORED,
    )
    return Evidence(
        chunk_id=chunk_id,
        project=DEFAULT_PROJECT,
        text="The projection is intentionally disposable.",
        citation=citation,
        retriever_ranks=(RetrieverRank("lexical", 1, score=3.2),),
        fused_rank=fused_rank,
        source_timestamp=SOURCE_TIME,
        sync_timestamp=SYNC_TIME,
    )


def make_receipt(item: Evidence, request: RetrieveRequest) -> RetrievalReceipt:
    return RetrievalReceipt(
        knowledge_item_id=item.item_id,
        chunk_id=item.chunk_id,
        content_hash=item.content_hash,
        source_locator=item.citation.source_locator,
        retrieval_timestamp=RETRIEVAL_TIME,
        principal=request.principal,
        project=request.project,
        query=request.query,
    )


def make_bundle(**overrides) -> EvidenceBundle:
    request = overrides.pop("request", make_request())
    evidence = overrides.pop(
        "evidence", (make_evidence(make_chunk_id(make_item_id())),)
    )
    defaults = {
        "request": request,
        "evidence": evidence,
        "citations": tuple(item.citation for item in evidence),
        "receipts": tuple(make_receipt(item, request) for item in evidence),
        "freshness": FreshnessReport(is_stale=False, requirement_satisfied=True),
        "retrieval_timestamp": RETRIEVAL_TIME,
        "retrievers_used": ("lexical",),
    }
    defaults.update(overrides)
    return EvidenceBundle(**defaults)


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def test_knowledge_item_id_is_connector_and_source_object() -> None:
    item_id = make_item_id()

    assert item_id.connector_id == "local_files"
    assert item_id.source_object_id == "notes/decisions.md"
    assert str(item_id) == "local_files:notes/decisions.md"
    assert item_id == make_item_id()


def test_chunk_id_binds_item_ordinal_and_content_hash() -> None:
    item_id = make_item_id()
    chunk_id = make_chunk_id(item_id, ordinal=3)

    assert chunk_id.item_id == item_id
    assert chunk_id.chunk_ordinal == 3
    assert chunk_id.content_hash == HASH_A


def test_chunk_id_changes_when_content_changes() -> None:
    item_id = make_item_id()

    assert make_chunk_id(item_id, 0, HASH_A) != make_chunk_id(item_id, 0, HASH_B)


def test_identity_rejects_empty_parts() -> None:
    with pytest.raises(ValueError):
        KnowledgeItemId("", "notes.md")
    with pytest.raises(ValueError):
        KnowledgeItemId("local_files", "  ")
    with pytest.raises(ValueError):
        make_chunk_id(make_item_id(), digest="not-a-digest")
    with pytest.raises(ValueError):
        make_chunk_id(make_item_id(), ordinal=-1)


def test_compute_content_hash_is_stable_lowercase_sha256() -> None:
    digest = compute_content_hash("chunk one")

    assert digest == compute_content_hash(b"chunk one")
    assert len(digest) == 64
    assert digest == digest.lower()


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


def test_knowledge_item_constructs_with_provenance_and_permissions() -> None:
    item = make_item(title="Decisions", tags=("architecture",))

    assert item.project == DEFAULT_PROJECT
    assert item.document_type is DocumentType.MARKDOWN
    assert item.permissions.owner == "lee@leebase.com"
    assert item.authority is Authority.DERIVED
    assert item.trust is Trust.CURATED
    assert item.tombstone is False
    assert item.is_retrievable is True
    assert item.schema_version == 1


def test_chunk_constructs_and_derives_item_identity() -> None:
    item_id = make_item_id()
    chunk = Chunk(
        chunk_id=make_chunk_id(item_id, ordinal=2),
        project=DEFAULT_PROJECT,
        text="The projection is intentionally disposable.",
        chunker_id="markdown-atx-v1:1",
        heading="Persistence",
        occurrence=1,
        start_offset=1024,
    )

    assert chunk.item_id == item_id
    assert chunk.content_hash == HASH_A
    assert chunk.kind is ChunkKind.SOURCE_SLICE


def test_derived_artifact_chunk_is_expressible() -> None:
    chunk = Chunk(
        chunk_id=make_chunk_id(KnowledgeItemId("outlook", "thread_8f42")),
        project=DEFAULT_PROJECT,
        text="Question: why does restore stall? Resolution: set CKPT_PREFETCH=4.",
        chunker_id="thread-distill-v1:1",
        kind=ChunkKind.DERIVED_ARTIFACT,
    )

    assert chunk.kind is ChunkKind.DERIVED_ARTIFACT


def test_retrieve_request_carries_the_locked_field_set() -> None:
    request = make_request(
        top_k=3,
        filters=MetadataFilters(
            connectors=("local_files",),
            projects=(DEFAULT_PROJECT,),
            document_types=(DocumentType.MARKDOWN,),
            tags=("architecture",),
            date_range=DateRange(start=SOURCE_TIME, end=SYNC_TIME),
        ),
        freshness=FreshnessRequirement(max_staleness=timedelta(hours=6)),
    )

    assert {field.name for field in dataclasses.fields(request)} >= {
        "query",
        "principal",
        "top_k",
        "filters",
        "freshness",
        "project",
    }
    assert request.effective_projects == (DEFAULT_PROJECT,)
    assert request.freshness.allow_refresh is False


def test_retrieve_request_defaults_to_the_request_project_scope() -> None:
    assert make_request().effective_projects == (DEFAULT_PROJECT,)


def test_evidence_bundle_carries_ranks_citations_and_timestamps() -> None:
    bundle = make_bundle()
    item = bundle.evidence[0]

    assert item.retriever_ranks[0].retriever == "lexical"
    assert bundle.citations[0] is item.citation
    assert item.source_timestamp == SOURCE_TIME
    assert item.sync_timestamp == SYNC_TIME
    assert bundle.retrieval_timestamp == RETRIEVAL_TIME
    assert bundle.freshness.is_stale is False
    assert bundle.denied_count == 0


def test_journal_entry_records_a_change_between_hashes() -> None:
    entry = JournalEntry(
        connector_id="local_files",
        source_object_id="notes/decisions.md",
        project=DEFAULT_PROJECT,
        change_type=ChangeType.UPDATED,
        sync_timestamp=SYNC_TIME,
        content_hash=HASH_B,
        previous_content_hash=HASH_A,
    )

    assert entry.item_id == make_item_id()
    assert entry.change_type is ChangeType.UPDATED


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instance, attribute, value",
    [
        (make_item_id(), "connector_id", "outlook"),
        (make_chunk_id(make_item_id()), "chunk_ordinal", 9),
        (make_item(), "project", "acme"),
        (make_principal(), "principal_id", "someone_else"),
        (make_permissions(), "owner", "someone_else"),
        (make_request(), "top_k", 100),
        (make_bundle(), "denied_count", 7),
    ],
)
def test_contracts_are_immutable(instance, attribute, value) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, attribute, value)


def test_contracts_are_hashable_value_objects() -> None:
    assert len({make_item_id(), make_item_id()}) == 1
    assert len({make_chunk_id(make_item_id()), make_chunk_id(make_item_id())}) == 1


def test_sequence_fields_reject_mutable_containers() -> None:
    with pytest.raises(TypeError):
        make_item(tags=["architecture"])
    with pytest.raises(TypeError):
        MetadataFilters(connectors=["local_files"])


# --------------------------------------------------------------------------
# Required project
# --------------------------------------------------------------------------


def test_knowledge_item_requires_a_project_argument() -> None:
    item_id = make_item_id()
    with pytest.raises(TypeError):
        KnowledgeItem(
            item_id=item_id,
            source_locator=make_locator(item_id),
            document_type=DocumentType.MARKDOWN,
            content_hash=HASH_A,
            source_timestamp=SOURCE_TIME,
            sync_timestamp=SYNC_TIME,
            permissions=make_permissions(),
        )


@pytest.mark.parametrize("project", [None, "", "   "])
def test_project_must_be_a_non_empty_string(project) -> None:
    with pytest.raises(ValueError):
        make_item(project=project)


def test_every_project_scoped_contract_rejects_a_missing_project() -> None:
    item_id = make_item_id()

    with pytest.raises(ValueError):
        Chunk(
            chunk_id=make_chunk_id(item_id),
            project="",
            text="text",
            chunker_id="markdown-atx-v1:1",
        )
    with pytest.raises(ValueError):
        make_request(project="")
    with pytest.raises(ValueError):
        JournalEntry(
            connector_id="local_files",
            source_object_id="notes/decisions.md",
            project="",
            change_type=ChangeType.CREATED,
            sync_timestamp=SYNC_TIME,
            content_hash=HASH_A,
        )


def test_retrieve_request_scope_must_include_the_request_project() -> None:
    with pytest.raises(ValueError):
        make_request(filters=MetadataFilters(projects=("acme",)))


def test_evidence_outside_the_request_scope_is_rejected() -> None:
    chunk_id = make_chunk_id(make_item_id())
    item = dataclasses.replace(make_evidence(chunk_id), project="acme")

    with pytest.raises(ValueError):
        make_bundle(evidence=(item,))


# --------------------------------------------------------------------------
# Receipt completeness
# --------------------------------------------------------------------------


def test_receipt_records_every_required_audit_field() -> None:
    field_names = {field.name for field in dataclasses.fields(RetrievalReceipt)}

    assert field_names >= {
        "knowledge_item_id",
        "chunk_id",
        "content_hash",
        "source_locator",
        "retrieval_timestamp",
        "principal",
    }


def test_receipt_has_no_optional_audit_fields() -> None:
    required = {
        "knowledge_item_id",
        "chunk_id",
        "content_hash",
        "source_locator",
        "retrieval_timestamp",
        "principal",
    }
    for field in dataclasses.fields(RetrievalReceipt):
        if field.name in required:
            assert field.default is dataclasses.MISSING
            assert field.default_factory is dataclasses.MISSING


def test_receipt_stays_verifiable_after_the_projection_changes() -> None:
    request = make_request()
    item = make_evidence(make_chunk_id(make_item_id()))
    receipt = make_receipt(item, request)

    assert receipt.knowledge_item_id == make_item_id()
    assert receipt.content_hash == HASH_A
    assert receipt.source_locator.uri.startswith("file:///")
    assert receipt.principal == request.principal
    assert receipt.retrieval_timestamp == RETRIEVAL_TIME


def test_receipt_hash_must_match_its_chunk() -> None:
    item_id = make_item_id()
    with pytest.raises(ValueError):
        RetrievalReceipt(
            knowledge_item_id=item_id,
            chunk_id=make_chunk_id(item_id, digest=HASH_A),
            content_hash=HASH_B,
            source_locator=make_locator(item_id),
            retrieval_timestamp=RETRIEVAL_TIME,
            principal=make_principal(),
            project=DEFAULT_PROJECT,
            query="anything",
        )


def test_receipt_item_must_match_its_chunk() -> None:
    with pytest.raises(ValueError):
        RetrievalReceipt(
            knowledge_item_id=KnowledgeItemId("outlook", "thread_8f42"),
            chunk_id=make_chunk_id(make_item_id()),
            content_hash=HASH_A,
            source_locator=make_locator(make_item_id()),
            retrieval_timestamp=RETRIEVAL_TIME,
            principal=make_principal(),
            project=DEFAULT_PROJECT,
            query="anything",
        )


def test_every_piece_of_evidence_carries_a_receipt_and_a_citation() -> None:
    request = make_request()
    first = make_evidence(make_chunk_id(make_item_id(), 0, HASH_A), fused_rank=1)
    second = make_evidence(make_chunk_id(make_item_id(), 1, HASH_B), fused_rank=2)
    bundle = make_bundle(request=request, evidence=(first, second))

    assert len(bundle.receipts) == 2
    assert len(bundle.citations) == 2

    with pytest.raises(ValueError):
        make_bundle(
            request=request,
            evidence=(first, second),
            receipts=(make_receipt(first, request),),
        )


def test_bundle_rejects_a_receipt_for_a_different_principal() -> None:
    request = make_request()
    item = make_evidence(make_chunk_id(make_item_id()))
    foreign = dataclasses.replace(
        make_receipt(item, request), principal=Principal("intern@example.com")
    )

    with pytest.raises(ValueError):
        make_bundle(request=request, evidence=(item,), receipts=(foreign,))


# --------------------------------------------------------------------------
# Remaining invariants
# --------------------------------------------------------------------------


def test_tombstone_and_timestamp_travel_together() -> None:
    tombstoned = make_item(tombstone=True, tombstoned_at=SYNC_TIME)

    assert tombstoned.is_retrievable is False

    with pytest.raises(ValueError):
        make_item(tombstone=True)
    with pytest.raises(ValueError):
        make_item(tombstoned_at=SYNC_TIME)


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError):
        make_item(sync_timestamp=datetime(2026, 8, 3, 9, 0))


def test_locator_connector_must_match_the_item_connector() -> None:
    item_id = make_item_id()
    with pytest.raises(ValueError):
        make_item(
            source_locator=SourceLocator(connector_id="outlook", uri="file:///x"),
            item_id=item_id,
        )


def test_evidence_requires_at_least_one_retriever_rank() -> None:
    chunk_id = make_chunk_id(make_item_id())
    with pytest.raises(ValueError):
        dataclasses.replace(make_evidence(chunk_id), retriever_ranks=())


def test_evidence_rejects_duplicate_retriever_entries() -> None:
    chunk_id = make_chunk_id(make_item_id())
    with pytest.raises(ValueError):
        dataclasses.replace(
            make_evidence(chunk_id),
            retriever_ranks=(RetrieverRank("lexical", 1), RetrieverRank("lexical", 2)),
        )


def test_bundle_is_ordered_by_ascending_fused_rank() -> None:
    first = make_evidence(make_chunk_id(make_item_id(), 0, HASH_A), fused_rank=2)
    second = make_evidence(make_chunk_id(make_item_id(), 1, HASH_B), fused_rank=1)

    with pytest.raises(ValueError):
        make_bundle(evidence=(first, second))


def test_bundle_never_exceeds_the_requested_top_k() -> None:
    request = make_request(top_k=1)
    first = make_evidence(make_chunk_id(make_item_id(), 0, HASH_A), fused_rank=1)
    second = make_evidence(make_chunk_id(make_item_id(), 1, HASH_B), fused_rank=2)

    with pytest.raises(ValueError):
        make_bundle(request=request, evidence=(first, second))


def test_created_entry_has_no_previous_hash() -> None:
    entry = JournalEntry(
        connector_id="local_files",
        source_object_id="notes/new.md",
        project=DEFAULT_PROJECT,
        change_type=ChangeType.CREATED,
        sync_timestamp=SYNC_TIME,
        content_hash=HASH_A,
    )

    assert entry.previous_content_hash is None

    with pytest.raises(ValueError):
        JournalEntry(
            connector_id="local_files",
            source_object_id="notes/new.md",
            project=DEFAULT_PROJECT,
            change_type=ChangeType.CREATED,
            sync_timestamp=SYNC_TIME,
            content_hash=HASH_A,
            previous_content_hash=HASH_B,
        )


def test_updated_entry_requires_two_different_hashes() -> None:
    for content_hash, previous in [(HASH_A, None), (None, HASH_A), (HASH_A, HASH_A)]:
        with pytest.raises(ValueError):
            JournalEntry(
                connector_id="local_files",
                source_object_id="notes/decisions.md",
                project=DEFAULT_PROJECT,
                change_type=ChangeType.UPDATED,
                sync_timestamp=SYNC_TIME,
                content_hash=content_hash,
                previous_content_hash=previous,
            )


@pytest.mark.parametrize("change_type", [ChangeType.DELETED, ChangeType.PURGED])
def test_removal_entry_keeps_only_the_previous_hash(change_type) -> None:
    entry = JournalEntry(
        connector_id="local_files",
        source_object_id="notes/gone.md",
        project=DEFAULT_PROJECT,
        change_type=change_type,
        sync_timestamp=SYNC_TIME,
        previous_content_hash=HASH_A,
    )

    assert entry.content_hash is None

    with pytest.raises(ValueError):
        JournalEntry(
            connector_id="local_files",
            source_object_id="notes/gone.md",
            project=DEFAULT_PROJECT,
            change_type=change_type,
            sync_timestamp=SYNC_TIME,
            content_hash=HASH_A,
            previous_content_hash=HASH_A,
        )


def test_date_range_rejects_an_inverted_window() -> None:
    with pytest.raises(ValueError):
        DateRange(start=SYNC_TIME, end=SOURCE_TIME)


def test_permission_set_defaults_are_fail_closed() -> None:
    permissions = make_permissions()

    assert permissions.visibility.value == "private"
    assert permissions.allowed_principals == ()
    assert permissions.allowed_groups == ()


def test_retrieve_request_rejects_a_non_positive_top_k() -> None:
    with pytest.raises(ValueError):
        make_request(top_k=0)
