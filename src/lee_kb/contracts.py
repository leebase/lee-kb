"""Normalized domain contracts for the Lee Knowledge Base.

These frozen dataclasses are the shared vocabulary between connectors, the
ingestion engine, the knowledge repository, the retrieval engine, and every
consumer surface. They are declarative: validation covers structural
invariants only. Policy — permission evaluation, ranking, chunking, freshness
thresholds — lives in the layers that own it.

Design rules:

- Standard library only. No runtime dependencies.
- Every value object is frozen and hashable; sequences are tuples.
- Every timestamp is timezone-aware.
- ``project`` is required on every knowledge item, chunk, journal entry, and
  retrieval request. Personal deployments use :data:`DEFAULT_PROJECT`.
- Identity follows the locked model: an item is ``(connector_id,
  source_object_id)``; a chunk is ``(item_id, chunk_ordinal, content_hash)``.

See ``docs/sprint-1-contracts.md`` for the field-by-field specification.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_PROJECT",
    "WHOLE_ROOT_PATH_PREFIX",
    "AUTHORITY_RANK",
    "compute_content_hash",
    "OWNER_CONTRACT_VERSION",
    "OWNER_SCHEMA_VERSION",
    "OWNER_MAPPING_VERSION",
    "OWNER_HISTORICAL_VERSION",
    "OWNER_CORPUS_VERSION",
    "OWNER_PERMISSION_VERSION",
    "OWNER_RECEIPT_VERSION",
    "OwnerKnowledgeState",
    "OwnerFreshnessState",
    "HistoricalLocator",
    "SourceGrant",
    "MappedIdentity",
    "OwnerIdentityMapping",
    "PolicyBasis",
    "HistoricalReleaseRule",
    "HistoricalReleaseManifest",
    "ImmutableHistoricalObject",
    "HistoricalReceipt",
    "HistoricalLookupResult",
    "OwnerCurrentReceipt",
    "OwnerCurrentResult",
    "Authority",
    "Trust",
    "Visibility",
    "MemoryType",
    "MemoryConfidence",
    "PrincipalType",
    "DocumentType",
    "ChunkKind",
    "ChangeType",
    "Principal",
    "PermissionSet",
    "SourceLocator",
    "KnowledgeItemId",
    "ChunkId",
    "KnowledgeItem",
    "Chunk",
    "DateRange",
    "MetadataFilters",
    "FreshnessRequirement",
    "RetrieveRequest",
    "RetrieverRank",
    "Citation",
    "Evidence",
    "FreshnessReport",
    "RetrievalAuthContext",
    "RetrievalReceipt",
    "RetrievalAuditStatus",
    "RetrievalAuditEvent",
    "AccessAuditOutcome",
    "AccessAuditEvent",
    "JournalEntry",
]
#: Version of the persisted projection schema these contracts describe.
SCHEMA_VERSION = 3

#: The single project used by a personal deployment.
DEFAULT_PROJECT = "default"

#: ``SourceGrant.path_prefix`` sentinel admitting every path under the root.
WHOLE_ROOT_PATH_PREFIX = "*"

# Owner/Core handshakes. These are additive to the persisted projection schema.
OWNER_CONTRACT_VERSION = "lee-kb.owner.contract/v1"
OWNER_SCHEMA_VERSION = "lee-kb.owner.schema/v1"
OWNER_MAPPING_VERSION = "lee-kb.owner.mapping/v1"
OWNER_HISTORICAL_VERSION = "lee-kb.owner.historical-release/v1"
OWNER_CORPUS_VERSION = "lee-kb.owner.corpus/v1"
OWNER_PERMISSION_VERSION = "lee-kb.owner.permission/v1"
OWNER_RECEIPT_VERSION = "lee-kb.owner.receipt/v1"


_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def compute_content_hash(content: str | bytes) -> str:
    """Return the canonical content hash: lowercase SHA-256 hex."""
    data = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_optional_text(value: object, name: str) -> None:
    if value is not None:
        _require_text(value, name)


def _require_project(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "project is required on every knowledge record; "
            f"use {DEFAULT_PROJECT!r} for a personal deployment"
        )


def _require_hash(value: object, name: str) -> None:
    if not isinstance(value, str) or not _HASH_PATTERN.match(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _require_aware(value: object, name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_tuple(value: object, name: str) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{name} must be a tuple, not {type(value).__name__}")


class Authority(str, Enum):
    """Declared authority of a source root or item. Never inferred from text."""

    CANONICAL = "canonical"
    DERIVED = "derived"


#: Canonical evidence outranks derived evidence during ranking.
AUTHORITY_RANK = {Authority.CANONICAL: 0, Authority.DERIVED: 1}


class Trust(str, Enum):
    """Declared provenance of the content. Model-produced text is flagged."""

    HUMAN_AUTHORED = "human_authored"
    CURATED = "curated"
    MODEL_PRODUCED = "model_produced"


class Visibility(str, Enum):
    """Coarse visibility class. Evaluation is fail-closed, so PRIVATE is the default."""

    PRIVATE = "private"
    PROJECT = "project"
    PUBLIC = "public"


class MemoryType(str, Enum):
    """Closed classification of a durable memory record.

    ``None`` on :class:`KnowledgeItem` means "not a distinguished memory
    record" -- the existing default for ordinary organizational knowledge
    (docs, architecture notes, status files). These four values name the
    memory classes this substrate distinguishes beyond that default.
    """

    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    EPISODIC = "episodic"
    LESSON = "lesson"


class MemoryConfidence(str, Enum):
    """How a memory was learned -- provenance class, not a probability.

    Lets a consumer distinguish "Lee said this" from "I inferred this" when
    deciding how much authority to give a recalled memory.
    """

    STATED = "stated"
    OBSERVED = "observed"
    INFERRED = "inferred"
    REPORTED = "reported"
    DERIVED = "derived"

class PrincipalType(str, Enum):
    """Identity kinds consumed from the Agent Board identity model."""

    HUMAN = "human"
    MACHINE = "machine"
    AI_EMPLOYEE = "ai_employee"


class DocumentType(str, Enum):
    """Normalized document types supported in v1, plus conversational sources."""

    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    EMAIL = "email"
    CALENDAR = "calendar"
    OTHER = "other"


class ChunkKind(str, Enum):
    """A chunk is either a direct slice of source content or a derived artifact."""

    SOURCE_SLICE = "source_slice"
    DERIVED_ARTIFACT = "derived_artifact"


class ChangeType(str, Enum):
    """Synchronization events recorded in the append-only journal.

    Unchanged source objects are not journaled.
    """

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    PURGED = "purged"


@dataclass(frozen=True, slots=True)
class Principal:
    """The identity a retrieval is performed on behalf of. Never anonymous."""

    principal_id: str
    principal_type: PrincipalType = PrincipalType.HUMAN
    display_name: str | None = None
    groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.principal_id, "principal_id")
        _require_optional_text(self.display_name, "display_name")
        _require_tuple(self.groups, "groups")


@dataclass(frozen=True, slots=True)
class PermissionSet:
    """Permission facts captured at ingest, evaluated by the authorization layer.

    This is data, not policy. It carries no default grant: an item with an
    empty allow list and PRIVATE visibility is reachable only by its owner.
    """

    owner: str
    visibility: Visibility = Visibility.PRIVATE
    allowed_principals: tuple[str, ...] = ()
    allowed_groups: tuple[str, ...] = ()
    classification: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.owner, "owner")
        _require_tuple(self.allowed_principals, "allowed_principals")
        _require_tuple(self.allowed_groups, "allowed_groups")
        _require_optional_text(self.classification, "classification")


@dataclass(frozen=True, slots=True)
class SourceLocator:
    """A reference back to the authoritative source object."""

    connector_id: str
    uri: str
    label: str | None = None
    fragment: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.connector_id, "connector_id")
        _require_text(self.uri, "uri")
        _require_optional_text(self.label, "label")
        _require_optional_text(self.fragment, "fragment")


@dataclass(frozen=True, slots=True)
class KnowledgeItemId:
    """Knowledge Item ID = (connector_id, source_object_id).

    Stable for the lifetime of the source object.
    """

    connector_id: str
    source_object_id: str

    def __post_init__(self) -> None:
        _require_text(self.connector_id, "connector_id")
        _require_text(self.source_object_id, "source_object_id")

    def __str__(self) -> str:
        return f"{self.connector_id}:{self.source_object_id}"


@dataclass(frozen=True, slots=True)
class ChunkId:
    """Chunk ID = (item_id, chunk_ordinal, content_hash).

    Chunk IDs intentionally change when chunk contents change, so receipts
    never rely on a chunk identifier alone.
    """

    item_id: KnowledgeItemId
    chunk_ordinal: int
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, KnowledgeItemId):
            raise TypeError("item_id must be a KnowledgeItemId")
        if not isinstance(self.chunk_ordinal, int) or isinstance(
            self.chunk_ordinal, bool
        ):
            raise TypeError("chunk_ordinal must be an int")
        if self.chunk_ordinal < 0:
            raise ValueError("chunk_ordinal must be zero or greater")
        _require_hash(self.content_hash, "content_hash")

    def __str__(self) -> str:
        return f"{self.item_id}#{self.chunk_ordinal}@{self.content_hash[:12]}"


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    """The normalized projection of one source artifact.

    ``project`` has no default: every item must be placed in a project at
    construction time. Deletion is a tombstone, not a row removal.
    """

    item_id: KnowledgeItemId
    project: str
    source_locator: SourceLocator
    document_type: DocumentType
    content_hash: str
    source_timestamp: datetime
    sync_timestamp: datetime
    permissions: PermissionSet
    title: str | None = None
    tags: tuple[str, ...] = ()
    authority: Authority = Authority.DERIVED
    trust: Trust = Trust.CURATED
    tombstone: bool = False
    tombstoned_at: datetime | None = None
    schema_version: int = SCHEMA_VERSION
    #: Memory semantics (all optional, additive, schema v3). ``None`` on
    #: ``memory_type`` means "not a distinguished memory record" -- the
    #: default for ordinary organizational knowledge. When ``memory_type``
    #: is set, these carry the relationship/episodic/lesson/preference
    #: metadata described in chief-of-staff's memory architecture decision.
    memory_type: MemoryType | None = None
    subject_principal: str | None = None
    memory_confidence: MemoryConfidence | None = None
    importance: float | None = None
    memory_formed_at: datetime | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, KnowledgeItemId):
            raise TypeError("item_id must be a KnowledgeItemId")
        _require_project(self.project)
        if not isinstance(self.source_locator, SourceLocator):
            raise TypeError("source_locator must be a SourceLocator")
        if not isinstance(self.document_type, DocumentType):
            raise TypeError("document_type must be a DocumentType")
        if not isinstance(self.permissions, PermissionSet):
            raise TypeError("permissions must be a PermissionSet")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.source_timestamp, "source_timestamp")
        _require_aware(self.sync_timestamp, "sync_timestamp")
        _require_optional_text(self.title, "title")
        _require_tuple(self.tags, "tags")
        if self.source_locator.connector_id != self.item_id.connector_id:
            raise ValueError(
                "source_locator.connector_id must match item_id.connector_id"
            )
        if self.tombstone and self.tombstoned_at is None:
            raise ValueError("a tombstoned item must record tombstoned_at")
        if not self.tombstone and self.tombstoned_at is not None:
            raise ValueError("tombstoned_at is only valid on a tombstoned item")
        if self.tombstoned_at is not None:
            _require_aware(self.tombstoned_at, "tombstoned_at")
        if self.memory_type is not None and not isinstance(self.memory_type, MemoryType):
            raise TypeError("memory_type must be a MemoryType")
        _require_optional_text(self.subject_principal, "subject_principal")
        if self.memory_confidence is not None and not isinstance(
            self.memory_confidence, MemoryConfidence
        ):
            raise TypeError("memory_confidence must be a MemoryConfidence")
        if self.importance is not None:
            if isinstance(self.importance, bool) or not isinstance(
                self.importance, (int, float)
            ):
                raise TypeError("importance must be a number")
            if not (0.0 <= float(self.importance) <= 1.0):
                raise ValueError("importance must be between 0.0 and 1.0")
        if self.memory_formed_at is not None:
            _require_aware(self.memory_formed_at, "memory_formed_at")
        _require_optional_text(self.superseded_by, "superseded_by")
        if self.memory_type is None and (
            self.subject_principal is not None
            or self.memory_confidence is not None
            or self.importance is not None
            or self.memory_formed_at is not None
            or self.superseded_by is not None
        ):
            raise ValueError(
                "memory metadata requires memory_type to be set"
            )

    @property
    def is_retrievable(self) -> bool:
        """Tombstoned items are excluded from ordinary search."""
        return not self.tombstone


@dataclass(frozen=True, slots=True)
class Chunk:
    """A retrievable portion of a knowledge item.

    ``chunk_id.content_hash`` is the hash of :attr:`text` as normalized by the
    chunker identified by :attr:`chunker_id`.
    """

    chunk_id: ChunkId
    project: str
    text: str
    chunker_id: str
    kind: ChunkKind = ChunkKind.SOURCE_SLICE
    heading: str | None = None
    occurrence: int = 0
    start_offset: int | None = None
    token_count: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        _require_project(self.project)
        _require_text(self.text, "text")
        _require_text(self.chunker_id, "chunker_id")
        if not isinstance(self.kind, ChunkKind):
            raise TypeError("kind must be a ChunkKind")
        _require_optional_text(self.heading, "heading")
        if self.occurrence < 0:
            raise ValueError("occurrence must be zero or greater")
        if self.start_offset is not None and self.start_offset < 0:
            raise ValueError("start_offset must be zero or greater")
        if self.token_count is not None and self.token_count < 0:
            raise ValueError("token_count must be zero or greater")

    @property
    def item_id(self) -> KnowledgeItemId:
        return self.chunk_id.item_id

    @property
    def content_hash(self) -> str:
        return self.chunk_id.content_hash


@dataclass(frozen=True, slots=True)
class DateRange:
    """Inclusive range filter over source timestamps."""

    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        if self.start is not None:
            _require_aware(self.start, "start")
        if self.end is not None:
            _require_aware(self.end, "end")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("start must not be later than end")


@dataclass(frozen=True, slots=True)
class MetadataFilters:
    """The v1 filter surface: simple equality and range matching only.

    An empty tuple means "no constraint on this dimension". There is no query
    language and no boolean composition.
    """

    connectors: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    document_types: tuple[DocumentType, ...] = ()
    tags: tuple[str, ...] = ()
    date_range: DateRange | None = None

    def __post_init__(self) -> None:
        _require_tuple(self.connectors, "connectors")
        _require_tuple(self.projects, "projects")
        _require_tuple(self.document_types, "document_types")
        _require_tuple(self.tags, "tags")
        if self.date_range is not None and not isinstance(self.date_range, DateRange):
            raise TypeError("date_range must be a DateRange")


@dataclass(frozen=True, slots=True)
class FreshnessRequirement:
    """How fresh the caller needs the evidence to be.

    Synchronous connector refresh is opt-in per query and never the default;
    by default retrieval reports staleness rather than blocking on an external
    system.
    """

    max_staleness: timedelta | None = None
    allow_refresh: bool = False
    fail_on_stale: bool = False

    def __post_init__(self) -> None:
        if self.max_staleness is not None:
            if not isinstance(self.max_staleness, timedelta):
                raise TypeError("max_staleness must be a timedelta")
            if self.max_staleness < timedelta(0):
                raise ValueError("max_staleness must not be negative")


@dataclass(frozen=True, slots=True)
class RetrieveRequest:
    """The public retrieve() request. Every surface builds one of these.

    ``principal`` and ``project`` are both required: the API never accepts an
    anonymous or unscoped request.
    """

    query: str
    principal: Principal
    project: str
    top_k: int = 10
    filters: MetadataFilters = field(default_factory=MetadataFilters)
    freshness: FreshnessRequirement = field(default_factory=FreshnessRequirement)
    include_tombstoned: bool = False

    def __post_init__(self) -> None:
        _require_text(self.query, "query")
        if not isinstance(self.principal, Principal):
            raise TypeError("principal must be a Principal")
        _require_project(self.project)
        if not isinstance(self.top_k, int) or isinstance(self.top_k, bool):
            raise TypeError("top_k must be an int")
        if self.top_k < 1:
            raise ValueError("top_k must be at least 1")
        if not isinstance(self.filters, MetadataFilters):
            raise TypeError("filters must be a MetadataFilters")
        if not isinstance(self.freshness, FreshnessRequirement):
            raise TypeError("freshness must be a FreshnessRequirement")
        if self.filters.projects and self.project not in self.filters.projects:
            raise ValueError(
                "filters.projects must include the request project when set"
            )

    @property
    def effective_projects(self) -> tuple[str, ...]:
        """The projects this request may read from."""
        return self.filters.projects or (self.project,)


@dataclass(frozen=True, slots=True)
class RetrieverRank:
    """One retriever's opinion of one piece of evidence.

    Carried from day one — while only lexical retrieval exists — so rank
    fusion can be added without a schema change.
    """

    retriever: str
    rank: int
    score: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.retriever, "retriever")
        if not isinstance(self.rank, int) or isinstance(self.rank, bool):
            raise TypeError("rank must be an int")
        if self.rank < 1:
            raise ValueError("rank must be 1-based")


@dataclass(frozen=True, slots=True)
class Citation:
    """Everything a reader needs to open the original source."""

    item_id: KnowledgeItemId
    chunk_id: ChunkId
    source_locator: SourceLocator
    title: str | None = None
    heading: str | None = None
    authority: Authority = Authority.DERIVED
    trust: Trust = Trust.CURATED

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        if not isinstance(self.source_locator, SourceLocator):
            raise TypeError("source_locator must be a SourceLocator")
        if self.chunk_id.item_id != self.item_id:
            raise ValueError("chunk_id.item_id must match item_id")
        _require_optional_text(self.title, "title")
        _require_optional_text(self.heading, "heading")


@dataclass(frozen=True, slots=True)
class Evidence:
    """One ranked, permitted, cited piece of evidence."""

    chunk_id: ChunkId
    project: str
    text: str
    citation: Citation
    retriever_ranks: tuple[RetrieverRank, ...]
    fused_rank: int
    source_timestamp: datetime
    sync_timestamp: datetime
    fused_score: float | None = None
    kind: ChunkKind = ChunkKind.SOURCE_SLICE

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        _require_project(self.project)
        _require_text(self.text, "text")
        if not isinstance(self.citation, Citation):
            raise TypeError("citation must be a Citation")
        if self.citation.chunk_id != self.chunk_id:
            raise ValueError("citation.chunk_id must match chunk_id")
        _require_tuple(self.retriever_ranks, "retriever_ranks")
        if not self.retriever_ranks:
            raise ValueError("evidence must record at least one retriever rank")
        names = [entry.retriever for entry in self.retriever_ranks]
        if len(set(names)) != len(names):
            raise ValueError("retriever_ranks must have one entry per retriever")
        if not isinstance(self.fused_rank, int) or isinstance(self.fused_rank, bool):
            raise TypeError("fused_rank must be an int")
        if self.fused_rank < 1:
            raise ValueError("fused_rank must be 1-based")
        _require_aware(self.source_timestamp, "source_timestamp")
        _require_aware(self.sync_timestamp, "sync_timestamp")

    @property
    def item_id(self) -> KnowledgeItemId:
        return self.chunk_id.item_id

    @property
    def content_hash(self) -> str:
        return self.chunk_id.content_hash


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    """Honest staleness reporting for one retrieval."""

    is_stale: bool
    requirement_satisfied: bool
    oldest_sync_timestamp: datetime | None = None
    newest_source_timestamp: datetime | None = None
    staleness: timedelta | None = None
    refreshed: bool = False

    def __post_init__(self) -> None:
        if self.oldest_sync_timestamp is not None:
            _require_aware(self.oldest_sync_timestamp, "oldest_sync_timestamp")
        if self.newest_source_timestamp is not None:
            _require_aware(self.newest_source_timestamp, "newest_source_timestamp")
        if self.staleness is not None and not isinstance(self.staleness, timedelta):
            raise TypeError("staleness must be a timedelta")


@dataclass(frozen=True, slots=True)
class RetrievalAuthContext:
    """Server-derived client/session provenance attached to a retrieval."""

    client_id: str
    session_id: str
    grant_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.client_id, "client_id")
        # Session ids are bearer credentials; only the one-way sha256
        # reference may be attached to durable provenance.
        _require_hash(self.session_id, "session_id")
        _require_tuple(self.grant_ids, "grant_ids")
        if any(
            not isinstance(value, str) or not value.strip() for value in self.grant_ids
        ):
            raise ValueError("grant_ids must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class RetrievalReceipt:
    """The auditable record of one piece of evidence leaving the platform.

    A receipt stays independently verifiable after the projection evolves,
    because it stores the item ID, the chunk ID, the content hash, the source
    locator, and the retrieval timestamp — not just a chunk identifier.
    """

    knowledge_item_id: KnowledgeItemId
    chunk_id: ChunkId
    content_hash: str
    source_locator: SourceLocator
    retrieval_timestamp: datetime
    principal: Principal
    project: str
    query: str
    auth_context: RetrievalAuthContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge_item_id, KnowledgeItemId):
            raise TypeError("knowledge_item_id must be a KnowledgeItemId")
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        if not isinstance(self.source_locator, SourceLocator):
            raise TypeError("source_locator must be a SourceLocator")
        if not isinstance(self.principal, Principal):
            raise TypeError("principal must be a Principal")
        if self.auth_context is not None and not isinstance(
            self.auth_context, RetrievalAuthContext
        ):
            raise TypeError("auth_context must be a RetrievalAuthContext or None")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.retrieval_timestamp, "retrieval_timestamp")
        _require_project(self.project)
        _require_text(self.query, "query")
        if self.chunk_id.item_id != self.knowledge_item_id:
            raise ValueError("chunk_id.item_id must match knowledge_item_id")
        if self.chunk_id.content_hash != self.content_hash:
            raise ValueError("content_hash must match chunk_id.content_hash")


class RetrievalAuditStatus(str, Enum):
    """Outcome recorded for one governed retrieval query."""

    COMPLETED = "completed"
    STALE_REFUSED = "stale_refused"
    PROVIDER_FAILED = "provider_failed"


@dataclass(frozen=True, slots=True)
class RetrievalAuditEvent:
    """Durable query-level governance facts, including empty results."""

    query: str
    retrieval_timestamp: datetime
    principal: Principal
    project: str
    candidate_count: int
    denied_count: int
    released_count: int
    truncated: bool
    status: RetrievalAuditStatus = RetrievalAuditStatus.COMPLETED
    auth_context: RetrievalAuthContext | None = None

    def __post_init__(self) -> None:
        _require_text(self.query, "query")
        _require_aware(self.retrieval_timestamp, "retrieval_timestamp")
        if not isinstance(self.principal, Principal):
            raise TypeError("principal must be a Principal")
        if self.auth_context is not None and not isinstance(
            self.auth_context, RetrievalAuthContext
        ):
            raise TypeError("auth_context must be a RetrievalAuthContext or None")
        _require_project(self.project)
        for value, name in (
            (self.candidate_count, "candidate_count"),
            (self.denied_count, "denied_count"),
            (self.released_count, "released_count"),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int")
            if value < 0:
                raise ValueError(f"{name} must be zero or greater")
        if self.denied_count > self.candidate_count:
            raise ValueError("denied_count cannot exceed candidate_count")
        if self.released_count + self.denied_count > self.candidate_count:
            raise ValueError(
                "released_count plus denied_count cannot exceed candidate_count"
            )
        if not isinstance(self.truncated, bool):
            raise TypeError("truncated must be a bool")
        if not isinstance(self.status, RetrievalAuditStatus):
            raise TypeError("status must be a RetrievalAuditStatus")


class AccessAuditOutcome(str, Enum):
    """Non-content access decision recorded by the authenticated gateway."""

    ALLOWED = "allowed"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class AccessAuditEvent:
    """Audit evidence that identifies the actor and client without query text."""

    event_type: str
    timestamp: datetime
    client_id: str
    session_id: str | None
    principal: Principal | None
    tenant: str
    project: str | None
    operation: str
    outcome: AccessAuditOutcome
    reason_code: str
    grant_ids: tuple[str, ...] = ()
    query_digest: str | None = None
    freshness_state: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.event_type, "event_type"),
            (self.client_id, "client_id"),
            (self.tenant, "tenant"),
            (self.operation, "operation"),
            (self.reason_code, "reason_code"),
        ):
            _require_text(value, name)
        _require_aware(self.timestamp, "timestamp")
        if self.session_id is not None:
            # Only the one-way sha256 session reference may be audited.
            _require_hash(self.session_id, "session_id")
        _require_optional_text(self.project, "project")
        if self.principal is not None and not isinstance(self.principal, Principal):
            raise TypeError("principal must be a Principal or None")
        if not isinstance(self.outcome, AccessAuditOutcome):
            raise TypeError("outcome must be an AccessAuditOutcome")
        _require_tuple(self.grant_ids, "grant_ids")
        if any(
            not isinstance(value, str) or not value.strip() for value in self.grant_ids
        ):
            raise ValueError("grant_ids must contain non-empty strings")
        if self.query_digest is not None:
            _require_hash(self.query_digest, "query_digest")
        _require_optional_text(self.freshness_state, "freshness_state")


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """The result of retrieve(). No LLM involved.

    Citations and receipts mirror :attr:`evidence` position for position, so a
    consumer can never present evidence that has no citation or no receipt.
    """

    request: RetrieveRequest
    evidence: tuple[Evidence, ...]
    citations: tuple[Citation, ...]
    receipts: tuple[RetrievalReceipt, ...]
    freshness: FreshnessReport
    retrieval_timestamp: datetime
    retrievers_used: tuple[str, ...] = ()
    denied_count: int = 0
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, RetrieveRequest):
            raise TypeError("request must be a RetrieveRequest")
        _require_tuple(self.evidence, "evidence")
        _require_tuple(self.citations, "citations")
        _require_tuple(self.receipts, "receipts")
        _require_tuple(self.retrievers_used, "retrievers_used")
        if not isinstance(self.freshness, FreshnessReport):
            raise TypeError("freshness must be a FreshnessReport")
        _require_aware(self.retrieval_timestamp, "retrieval_timestamp")
        if self.denied_count < 0:
            raise ValueError("denied_count must be zero or greater")
        if len(self.evidence) > self.request.top_k:
            raise ValueError("evidence must not exceed the requested top_k")
        if tuple(item.citation for item in self.evidence) != self.citations:
            raise ValueError("citations must mirror evidence position for position")
        if len(self.receipts) != len(self.evidence):
            raise ValueError("every piece of evidence needs exactly one receipt")

        scope = self.request.effective_projects
        previous_rank = 0
        for item, receipt in zip(self.evidence, self.receipts):
            if item.project not in scope:
                raise ValueError(
                    f"evidence project {item.project!r} is outside the request scope"
                )
            if item.fused_rank <= previous_rank:
                raise ValueError("evidence must be ordered by ascending fused_rank")
            previous_rank = item.fused_rank
            if receipt.chunk_id != item.chunk_id:
                raise ValueError("receipts must mirror evidence position for position")
            if receipt.principal != self.request.principal:
                raise ValueError("receipt principal must match the request principal")
            if receipt.retrieval_timestamp != self.retrieval_timestamp:
                raise ValueError(
                    "receipt retrieval_timestamp must match the bundle timestamp"
                )


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One append-only synchronization event.

    The repository stores a latest-state projection; the journal is what
    answers "what changed this week?" without full document versioning.
    Unchanged source objects are not journaled.
    """

    connector_id: str
    source_object_id: str
    project: str
    change_type: ChangeType
    sync_timestamp: datetime
    content_hash: str | None = None
    previous_content_hash: str | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.connector_id, "connector_id")
        _require_text(self.source_object_id, "source_object_id")
        _require_project(self.project)
        if not isinstance(self.change_type, ChangeType):
            raise TypeError("change_type must be a ChangeType")
        _require_aware(self.sync_timestamp, "sync_timestamp")
        if self.content_hash is not None:
            _require_hash(self.content_hash, "content_hash")
        if self.previous_content_hash is not None:
            _require_hash(self.previous_content_hash, "previous_content_hash")

        if self.change_type is ChangeType.CREATED:
            if self.content_hash is None:
                raise ValueError("a created entry must record content_hash")
            if self.previous_content_hash is not None:
                raise ValueError(
                    "a created entry must not record previous_content_hash"
                )
        elif self.change_type is ChangeType.UPDATED:
            if self.content_hash is None or self.previous_content_hash is None:
                raise ValueError("an updated entry must record both content hashes")
            if self.content_hash == self.previous_content_hash:
                raise ValueError("an updated entry must record a changed hash")
        else:  # DELETED or PURGED
            if self.content_hash is not None:
                raise ValueError(
                    f"a {self.change_type.value} entry has no current content_hash"
                )
            if self.previous_content_hash is None:
                raise ValueError(
                    f"a {self.change_type.value} entry must record "
                    "previous_content_hash"
                )

    @property
    def item_id(self) -> KnowledgeItemId:
        return KnowledgeItemId(self.connector_id, self.source_object_id)


class OwnerKnowledgeState(str, Enum):
    """Safe owner outcome; UNKNOWN never discloses why a body was withheld."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    UNAUTHORIZED = "unauthorized"


class OwnerFreshnessState(str, Enum):
    """Freshness state carried by current and exact-history owner results."""

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


def _owner_hash(value: object) -> str:
    """Hash an immutable JSON-shaped owner contract value."""
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class HistoricalLocator:
    """One exact immutable source locator: repository, commit, and path."""

    repository: str
    commit: str
    path: str

    def __post_init__(self) -> None:
        _require_text(self.repository, "repository")
        _require_text(self.commit, "commit")
        _require_text(self.path, "path")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", self.commit):
            raise ValueError("commit must be a full lowercase hexadecimal hash")
        if "\x00" in self.path or self.path.startswith("/"):
            raise ValueError("path must be a relative exact source path")
        components = self.path.split("/")
        if any(component in {"", ".", ".."} for component in components):
            raise ValueError("path must not contain empty or traversal components")
        if any(char in self.path for char in "*?[]{}"):
            raise ValueError("path must be an exact path, not a pattern")

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.repository, self.commit, self.path)


@dataclass(frozen=True, slots=True)
class SourceGrant:
    """Server-owned project, source, root, path, and item scope grant.

    ``path_prefix`` is a relative path prefix evaluated inside ``root``.  The
    single character :data:`WHOLE_ROOT_PATH_PREFIX` (``"*"``) is the only
    wildcard form: it admits every path under the granted root.  Any other
    ``path_prefix`` containing ``*`` is rejected so a partial pattern can
    never be silently evaluated as a literal prefix.
    """

    project: str
    source_namespace: str
    root: str
    path_prefix: str
    item_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_project(self.project)
        for value, name in (
            (self.source_namespace, "source_namespace"),
            (self.root, "root"),
            (self.path_prefix, "path_prefix"),
        ):
            _require_text(value, name)
        _require_tuple(self.item_ids, "item_ids")
        if any(not isinstance(item, str) or not item.strip() for item in self.item_ids):
            raise ValueError("item_ids must contain non-empty strings")
        if "\x00" in self.path_prefix or self.path_prefix.startswith("/"):
            raise ValueError("path_prefix must be relative")
        if self.path_prefix == WHOLE_ROOT_PATH_PREFIX:
            return
        if "*" in self.path_prefix:
            raise ValueError("path_prefix must not contain wildcards")
        if any(part in {"", ".", ".."} for part in self.path_prefix.split("/")):
            raise ValueError("path_prefix must not contain traversal components")

    def permits(
        self,
        *,
        project: str,
        source_namespace: str,
        root: str,
        path: str,
        item_id: str | None,
    ) -> bool:
        if (project, source_namespace, root) != (
            self.project,
            self.source_namespace,
            self.root,
        ):
            return False
        if self.path_prefix != WHOLE_ROOT_PATH_PREFIX and not (
            path == self.path_prefix or path.startswith(self.path_prefix + "/")
        ):
            return False
        return not self.item_ids or (item_id is not None and item_id in self.item_ids)


@dataclass(frozen=True, slots=True)
class MappedIdentity:
    """Immutable server-derived identity and scope for one owner request."""

    mapping_version: str
    mapping_hash: str
    authenticated_principal: str
    principal_id: str
    principal_type: PrincipalType
    tenant: str
    lane: str
    scope_id: str
    purpose: str
    project: str
    source_namespaces: tuple[str, ...]
    grants: tuple[SourceGrant, ...]

    def __post_init__(self) -> None:
        _require_text(self.mapping_version, "mapping_version")
        _require_hash(self.mapping_hash, "mapping_hash")
        for value, name in (
            (self.authenticated_principal, "authenticated_principal"),
            (self.principal_id, "principal_id"),
            (self.tenant, "tenant"),
            (self.lane, "lane"),
            (self.scope_id, "scope_id"),
            (self.purpose, "purpose"),
        ):
            _require_text(value, name)
        if not isinstance(self.principal_type, PrincipalType):
            raise TypeError("principal_type must be a PrincipalType")
        _require_project(self.project)
        _require_tuple(self.source_namespaces, "source_namespaces")
        _require_tuple(self.grants, "grants")
        if any(not isinstance(item, SourceGrant) for item in self.grants):
            raise TypeError("grants must contain SourceGrant values")

    @property
    def principal(self) -> Principal:
        return Principal(self.principal_id, self.principal_type)


@dataclass(frozen=True, slots=True)
class OwnerIdentityMapping:
    """The only supported Core-principal to lee-kb identity mapping.

    The mapping is server-owned. A request may select one already configured
    project, but it cannot replace the principal, groups, tenant, lane, scope,
    purpose, source namespace, root, path, or item grants.
    """

    authenticated_principal: str = "lee"
    principal_id: str = "lee@leebase.com"
    tenant: str = "leebase"
    lane: str = "default"
    scope_id: str = "leeos"
    purpose: str = "knowledge"
    grants: tuple[SourceGrant, ...] = ()
    version: str = OWNER_MAPPING_VERSION
    mapping_hash: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.authenticated_principal, "authenticated_principal"),
            (self.principal_id, "principal_id"),
            (self.tenant, "tenant"),
            (self.lane, "lane"),
            (self.scope_id, "scope_id"),
            (self.purpose, "purpose"),
            (self.version, "version"),
        ):
            _require_text(value, name)
        _require_tuple(self.grants, "grants")
        if any(not isinstance(grant, SourceGrant) for grant in self.grants):
            raise TypeError("grants must contain SourceGrant values")
        body = {
            "version": self.version,
            "authenticated_principal": self.authenticated_principal,
            "principal_id": self.principal_id,
            "tenant": self.tenant,
            "lane": self.lane,
            "scope_id": self.scope_id,
            "purpose": self.purpose,
            "grants": [
                {
                    "project": grant.project,
                    "source_namespace": grant.source_namespace,
                    "root": grant.root,
                    "path_prefix": grant.path_prefix,
                    "item_ids": grant.item_ids,
                }
                for grant in self.grants
            ],
        }
        expected = _owner_hash(body)
        if self.mapping_hash:
            _require_hash(self.mapping_hash, "mapping_hash")
            if self.mapping_hash != expected:
                raise ValueError("mapping_hash does not match mapping contents")
        else:
            object.__setattr__(self, "mapping_hash", expected)

    @classmethod
    def default(cls, grants: tuple[SourceGrant, ...]) -> "OwnerIdentityMapping":
        """Build the frozen Lee mapping from explicit configured grants."""
        return cls(grants=grants)

    def resolve(
        self, authenticated_principal: str, *, project: str | None = None
    ) -> MappedIdentity:
        if authenticated_principal != self.authenticated_principal:
            raise PermissionError("owner identity is not authorized")
        projects = tuple(dict.fromkeys(grant.project for grant in self.grants))
        selected_project = project
        if selected_project is None:
            if len(projects) != 1:
                raise PermissionError("owner project scope is ambiguous")
            selected_project = projects[0]
        if selected_project not in projects:
            raise PermissionError("owner project is not granted")
        grants = tuple(
            grant for grant in self.grants if grant.project == selected_project
        )
        namespaces = tuple(dict.fromkeys(grant.source_namespace for grant in grants))
        return MappedIdentity(
            mapping_version=self.version,
            mapping_hash=self.mapping_hash,
            authenticated_principal=self.authenticated_principal,
            principal_id=self.principal_id,
            principal_type=PrincipalType.AI_EMPLOYEE,
            tenant=self.tenant,
            lane=self.lane,
            scope_id=self.scope_id,
            purpose=self.purpose,
            project=selected_project,
            source_namespaces=namespaces,
            grants=grants,
        )

    def permits(
        self,
        identity: MappedIdentity,
        *,
        source_namespace: str,
        root: str,
        path: str,
        item_id: str | None,
    ) -> bool:
        return any(
            grant.permits(
                project=identity.project,
                source_namespace=source_namespace,
                root=root,
                path=path,
                item_id=item_id,
            )
            for grant in identity.grants
        )


@dataclass(frozen=True, slots=True)
class PolicyBasis:
    """Versioned and hashed policy decision bound to a governed release."""

    version: str
    sha256: str
    decision: str
    evaluated_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.version, "version")
        _require_hash(self.sha256, "sha256")
        if self.decision not in {"allow", "deny", "unknown"}:
            raise ValueError("policy decision must be allow, deny, or unknown")
        if self.evaluated_at is not None:
            _require_aware(self.evaluated_at, "evaluated_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
        if (
            self.evaluated_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.evaluated_at
        ):
            raise ValueError("policy expiry must be after policy evaluation")

    @classmethod
    def unknown(cls, version: str = "unknown") -> "PolicyBasis":
        return cls(version, compute_content_hash(f"{version}:unknown"), "unknown")


@dataclass(frozen=True, slots=True)
class HistoricalReleaseRule:
    """One exact source-owner historical-release authorization rule."""

    principal_id: str
    project: str
    locator: HistoricalLocator
    classification: str
    basis: PolicyBasis
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.principal_id, "principal_id")
        _require_project(self.project)
        if not isinstance(self.locator, HistoricalLocator):
            raise TypeError("locator must be a HistoricalLocator")
        _require_text(self.classification, "classification")
        if not isinstance(self.basis, PolicyBasis):
            raise TypeError("basis must be a PolicyBasis")
        if self.valid_from is not None:
            _require_aware(self.valid_from, "valid_from")
        if self.valid_until is not None:
            _require_aware(self.valid_until, "valid_until")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("historical rule validity interval is empty")

    def covers(
        self,
        *,
        principal_id: str,
        project: str,
        locator: HistoricalLocator,
        classification: str,
        at: datetime,
    ) -> bool:
        return (
            self.principal_id == principal_id
            and self.project == project
            and self.locator == locator
            and self.classification == classification
            and (self.valid_from is None or at >= self.valid_from)
            and (self.valid_until is None or at < self.valid_until)
        )


@dataclass(frozen=True, slots=True)
class HistoricalReleaseManifest:
    """Versioned source-owner rules; absent/ambiguous rules fail closed."""

    version: str
    rules: tuple[HistoricalReleaseRule, ...]
    manifest_hash: str = ""
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.version, "version")
        _require_tuple(self.rules, "rules")
        if not self.rules:
            raise ValueError("historical release manifest must contain rules")
        if any(not isinstance(rule, HistoricalReleaseRule) for rule in self.rules):
            raise TypeError("rules must contain HistoricalReleaseRule values")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
        body = {
            "version": self.version,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "rules": [
                {
                    "principal_id": rule.principal_id,
                    "project": rule.project,
                    "locator": rule.locator.as_tuple(),
                    "classification": rule.classification,
                    "basis_version": rule.basis.version,
                    "basis_hash": rule.basis.sha256,
                    "basis_decision": rule.basis.decision,
                    "valid_from": (
                        rule.valid_from.isoformat() if rule.valid_from else None
                    ),
                    "valid_until": (
                        rule.valid_until.isoformat() if rule.valid_until else None
                    ),
                }
                for rule in self.rules
            ],
        }
        expected = _owner_hash(body)
        if self.manifest_hash:
            _require_hash(self.manifest_hash, "manifest_hash")
            if self.manifest_hash != expected:
                raise ValueError("manifest_hash does not match manifest contents")
        else:
            object.__setattr__(self, "manifest_hash", expected)

    @classmethod
    def from_rules(
        cls,
        rules: tuple[HistoricalReleaseRule, ...],
        *,
        version: str = OWNER_HISTORICAL_VERSION,
        expires_at: datetime | None = None,
    ) -> "HistoricalReleaseManifest":
        return cls(version=version, rules=rules, expires_at=expires_at)

    def evaluate(
        self,
        *,
        principal_id: str,
        project: str,
        locator: HistoricalLocator,
        classification: str,
        at: datetime,
    ) -> PolicyBasis:
        if self.expires_at is not None and at >= self.expires_at:
            return PolicyBasis.unknown(self.version)
        matches = tuple(
            rule
            for rule in self.rules
            if rule.covers(
                principal_id=principal_id,
                project=project,
                locator=locator,
                classification=classification,
                at=at,
            )
        )
        if len(matches) != 1:
            return PolicyBasis.unknown(self.version)
        return matches[0].basis


@dataclass(frozen=True, slots=True)
class ImmutableHistoricalObject:
    """Body returned by an injected exact-object source seam, never by search."""

    locator: HistoricalLocator
    body: str | bytes
    blob_hash: str
    blob_timestamp: datetime
    classification: str

    def __post_init__(self) -> None:
        if not isinstance(self.locator, HistoricalLocator):
            raise TypeError("locator must be a HistoricalLocator")
        if not isinstance(self.body, (str, bytes)):
            raise TypeError("body must be str or bytes")
        _require_hash(self.blob_hash, "blob_hash")
        _require_aware(self.blob_timestamp, "blob_timestamp")
        _require_text(self.classification, "classification")
        if compute_content_hash(self.body) != self.blob_hash:
            raise ValueError("blob_hash must match immutable body")


@dataclass(frozen=True, slots=True)
class HistoricalReceipt:
    audit_id: str
    mapping_version: str
    mapping_hash: str
    mapped_principal_id: str
    mapped_principal_type: PrincipalType
    authenticated_principal: str
    tenant: str
    lane: str
    scope_id: str
    purpose: str
    project: str
    source_namespace: str
    root: str
    path: str
    item_id: str | None
    locator: HistoricalLocator
    classification: str
    current_policy_version: str
    current_policy_hash: str
    current_policy_decision: str
    historical_policy_version: str
    historical_policy_hash: str
    historical_policy_decision: str
    historical_manifest_hash: str | None
    blob_hash: str | None
    blob_timestamp: datetime | None
    evaluation_time: datetime
    freshness_state: OwnerFreshnessState
    knowledge_state: OwnerKnowledgeState
    contract_version: str = OWNER_CONTRACT_VERSION
    schema_version: str = OWNER_SCHEMA_VERSION
    corpus_version: str = OWNER_CORPUS_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.audit_id, "audit_id"),
            (self.mapping_version, "mapping_version"),
            (self.mapped_principal_id, "mapped_principal_id"),
            (self.authenticated_principal, "authenticated_principal"),
            (self.tenant, "tenant"),
            (self.lane, "lane"),
            (self.scope_id, "scope_id"),
            (self.purpose, "purpose"),
            (self.project, "project"),
            (self.source_namespace, "source_namespace"),
            (self.root, "root"),
            (self.classification, "classification"),
            (self.current_policy_version, "current_policy_version"),
            (self.historical_policy_version, "historical_policy_version"),
            (self.current_policy_decision, "current_policy_decision"),
            (self.historical_policy_decision, "historical_policy_decision"),
            (self.contract_version, "contract_version"),
            (self.schema_version, "schema_version"),
            (self.corpus_version, "corpus_version"),
        ):
            _require_text(value, name)
        if not isinstance(self.mapped_principal_type, PrincipalType):
            raise TypeError("mapped_principal_type must be a PrincipalType")
        _require_hash(self.mapping_hash, "mapping_hash")
        if self.historical_manifest_hash is not None:
            _require_hash(self.historical_manifest_hash, "historical_manifest_hash")
        if self.blob_hash is not None:
            _require_hash(self.blob_hash, "blob_hash")
        if self.blob_timestamp is not None:
            _require_aware(self.blob_timestamp, "blob_timestamp")
        _require_project(self.project)
        if not isinstance(self.locator, HistoricalLocator):
            raise TypeError("locator must be a HistoricalLocator")
        _require_hash(self.current_policy_hash, "current_policy_hash")
        _require_hash(self.historical_policy_hash, "historical_policy_hash")
        _require_aware(self.evaluation_time, "evaluation_time")
        if self.current_policy_decision not in {"allow", "deny", "unknown"}:
            raise ValueError("invalid current policy decision")
        if self.historical_policy_decision not in {"allow", "deny", "unknown"}:
            raise ValueError("invalid historical policy decision")
        if not isinstance(self.freshness_state, OwnerFreshnessState):
            raise TypeError("freshness_state must be an OwnerFreshnessState")
        if not isinstance(self.knowledge_state, OwnerKnowledgeState):
            raise TypeError("knowledge_state must be an OwnerKnowledgeState")
        if self.path != self.locator.path:
            raise ValueError("receipt path must match locator")
        if self.mapping_version != OWNER_MAPPING_VERSION:
            raise ValueError("unsupported mapping version")
        if self.knowledge_state is OwnerKnowledgeState.KNOWN:
            if (
                self.current_policy_decision != "allow"
                or self.historical_policy_decision != "allow"
                or self.historical_manifest_hash is None
                or self.blob_hash is None
                or self.blob_timestamp is None
            ):
                raise ValueError("known receipt lacks complete release basis")
        if self.knowledge_state is not OwnerKnowledgeState.KNOWN and (
            self.blob_hash is not None or self.blob_timestamp is not None
        ):
            raise ValueError("non-known receipt must not carry blob details")
        audit_body = {
            "contract_version": self.contract_version,
            "mapping_version": self.mapping_version,
            "mapping_hash": self.mapping_hash,
            "principal_id": self.mapped_principal_id,
            "project": self.project,
            "locator": self.locator.as_tuple(),
            "classification": self.classification,
            "current_policy": (
                self.current_policy_version,
                self.current_policy_hash,
                self.current_policy_decision,
            ),
            "historical_policy": (
                self.historical_policy_version,
                self.historical_policy_hash,
                self.historical_policy_decision,
            ),
            "historical_manifest_hash": self.historical_manifest_hash,
            "blob_hash": self.blob_hash,
            "blob_timestamp": (
                self.blob_timestamp.isoformat()
                if self.blob_timestamp is not None
                else None
            ),
            "evaluation_time": self.evaluation_time.isoformat(),
            "state": self.knowledge_state.value,
        }
        expected_audit_id = (
            "audit-"
            + hashlib.sha256(
                json.dumps(audit_body, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()[:32]
        )
        if self.audit_id != expected_audit_id:
            raise ValueError("audit_id does not bind receipt fields")


@dataclass(frozen=True, slots=True)
class HistoricalLookupResult:
    """Exact-history result; body is structurally impossible on safe failure."""

    knowledge_state: OwnerKnowledgeState
    freshness_state: OwnerFreshnessState
    body: str | bytes | None
    receipt: HistoricalReceipt | None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge_state, OwnerKnowledgeState):
            raise TypeError("knowledge_state must be an OwnerKnowledgeState")
        if not isinstance(self.freshness_state, OwnerFreshnessState):
            raise TypeError("freshness_state must be an OwnerFreshnessState")
        if self.body is not None and not isinstance(self.body, (str, bytes)):
            raise TypeError("body must be str, bytes, or None")
        if self.receipt is not None and not isinstance(self.receipt, HistoricalReceipt):
            raise TypeError("receipt must be a HistoricalReceipt or None")
        if (
            self.knowledge_state is not OwnerKnowledgeState.KNOWN
            and self.body is not None
        ):
            raise ValueError("unknown or unauthorized history cannot contain a body")
        if self.knowledge_state is OwnerKnowledgeState.KNOWN and (
            self.body is None or self.receipt is None
        ):
            raise ValueError("known history requires body and receipt")


@dataclass(frozen=True, slots=True)
class OwnerCurrentReceipt:
    """Owner-mode current-release receipt, at parity with the history receipt.

    The persisted :class:`RetrievalReceipt` stays exactly as it is: this is the
    additive owner-contract projection of one released chunk, binding the
    versioned mapping, the mapped scope, the classification, the current
    permission basis, the freshness state and a re-derivable audit id.
    """

    audit_id: str
    mapping_version: str
    mapping_hash: str
    principal: Principal
    project: str
    knowledge_item_id: KnowledgeItemId
    chunk_id: ChunkId
    content_hash: str
    source_locator: SourceLocator
    source_namespace: str
    root: str
    path: str
    item_id: str
    classification: str
    policy_version: str
    policy_hash: str
    policy_decision: str
    freshness_state: OwnerFreshnessState
    knowledge_state: OwnerKnowledgeState
    retrieval_timestamp: datetime
    contract_version: str = OWNER_CONTRACT_VERSION
    schema_version: str = OWNER_SCHEMA_VERSION
    corpus_version: str = OWNER_CORPUS_VERSION
    receipt_version: str = OWNER_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.audit_id, "audit_id"),
            (self.mapping_version, "mapping_version"),
            (self.source_namespace, "source_namespace"),
            (self.root, "root"),
            (self.path, "path"),
            (self.item_id, "item_id"),
            (self.classification, "classification"),
            (self.policy_version, "policy_version"),
            (self.policy_decision, "policy_decision"),
            (self.contract_version, "contract_version"),
            (self.schema_version, "schema_version"),
            (self.corpus_version, "corpus_version"),
            (self.receipt_version, "receipt_version"),
        ):
            _require_text(value, name)
        if not isinstance(self.principal, Principal):
            raise TypeError("principal must be a Principal")
        if not isinstance(self.knowledge_item_id, KnowledgeItemId):
            raise TypeError("knowledge_item_id must be a KnowledgeItemId")
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        if not isinstance(self.source_locator, SourceLocator):
            raise TypeError("source_locator must be a SourceLocator")
        if not isinstance(self.freshness_state, OwnerFreshnessState):
            raise TypeError("freshness_state must be an OwnerFreshnessState")
        if not isinstance(self.knowledge_state, OwnerKnowledgeState):
            raise TypeError("knowledge_state must be an OwnerKnowledgeState")
        _require_project(self.project)
        _require_hash(self.mapping_hash, "mapping_hash")
        _require_hash(self.policy_hash, "policy_hash")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.retrieval_timestamp, "retrieval_timestamp")
        if self.policy_decision not in {"allow", "deny", "unknown"}:
            raise ValueError("invalid current policy decision")
        if self.mapping_version != OWNER_MAPPING_VERSION:
            raise ValueError("unsupported mapping version")
        if self.chunk_id.item_id != self.knowledge_item_id:
            raise ValueError("chunk_id.item_id must match knowledge_item_id")
        if self.chunk_id.content_hash != self.content_hash:
            raise ValueError("content_hash must match chunk_id.content_hash")
        if (
            self.knowledge_state is OwnerKnowledgeState.KNOWN
            and self.policy_decision != "allow"
        ):
            raise ValueError("known current receipt lacks an allow decision")
        expected_audit_id = (
            "audit-"
            + hashlib.sha256(
                json.dumps(
                    {
                        "contract_version": self.contract_version,
                        "receipt_version": self.receipt_version,
                        "mapping_version": self.mapping_version,
                        "mapping_hash": self.mapping_hash,
                        "principal_id": self.principal.principal_id,
                        "project": self.project,
                        "item_id": self.item_id,
                        "chunk_id": str(self.chunk_id),
                        "content_hash": self.content_hash,
                        "source_namespace": self.source_namespace,
                        "root": self.root,
                        "path": self.path,
                        "classification": self.classification,
                        "current_policy": (
                            self.policy_version,
                            self.policy_hash,
                            self.policy_decision,
                        ),
                        "freshness_state": self.freshness_state.value,
                        "retrieval_timestamp": self.retrieval_timestamp.isoformat(),
                        "state": self.knowledge_state.value,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:32]
        )
        if self.audit_id != expected_audit_id:
            raise ValueError("audit_id does not bind receipt fields")


@dataclass(frozen=True, slots=True)
class OwnerCurrentResult:
    """One owner-mode current retrieval: mapped identity, bundle and receipts."""

    knowledge_state: OwnerKnowledgeState
    freshness_state: OwnerFreshnessState
    identity: MappedIdentity
    policy: PolicyBasis
    bundle: EvidenceBundle
    receipts: tuple[OwnerCurrentReceipt, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge_state, OwnerKnowledgeState):
            raise TypeError("knowledge_state must be an OwnerKnowledgeState")
        if not isinstance(self.freshness_state, OwnerFreshnessState):
            raise TypeError("freshness_state must be an OwnerFreshnessState")
        if not isinstance(self.identity, MappedIdentity):
            raise TypeError("identity must be a MappedIdentity")
        if not isinstance(self.policy, PolicyBasis):
            raise TypeError("policy must be a PolicyBasis")
        if not isinstance(self.bundle, EvidenceBundle):
            raise TypeError("bundle must be an EvidenceBundle")
        _require_tuple(self.receipts, "receipts")
        if any(not isinstance(item, OwnerCurrentReceipt) for item in self.receipts):
            raise TypeError("receipts must contain OwnerCurrentReceipt values")
        if len(self.receipts) != len(self.bundle.receipts):
            raise ValueError("owner receipts must mirror the bundle receipts")
