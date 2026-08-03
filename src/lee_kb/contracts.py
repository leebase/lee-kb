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
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_PROJECT",
    "AUTHORITY_RANK",
    "compute_content_hash",
    "Authority",
    "Trust",
    "Visibility",
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
    "RetrievalReceipt",
    "EvidenceBundle",
    "JournalEntry",
]

#: Version of the persisted projection schema these contracts describe.
SCHEMA_VERSION = 1

#: The single project used by a personal deployment.
DEFAULT_PROJECT = "default"

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

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge_item_id, KnowledgeItemId):
            raise TypeError("knowledge_item_id must be a KnowledgeItemId")
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        if not isinstance(self.source_locator, SourceLocator):
            raise TypeError("source_locator must be a SourceLocator")
        if not isinstance(self.principal, Principal):
            raise TypeError("principal must be a Principal")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.retrieval_timestamp, "retrieval_timestamp")
        _require_project(self.project)
        _require_text(self.query, "query")
        if self.chunk_id.item_id != self.knowledge_item_id:
            raise ValueError("chunk_id.item_id must match knowledge_item_id")
        if self.chunk_id.content_hash != self.content_hash:
            raise ValueError("content_hash must match chunk_id.content_hash")


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
