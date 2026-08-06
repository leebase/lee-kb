# Sprint 1 Domain Contracts

> Task S1-01. Normative specification for `src/lee_kb/contracts.py`.
> Verified by `tests/test_contracts.py`.

These contracts are the shared vocabulary between connectors, the ingestion
engine, the knowledge repository, the retrieval engine, and every consumer
surface. They are the first artifact of Sprint 1 because the sprint's decision
gate says retrieval may not be implemented before the permission and
provenance fields are defined.

### Scope and rules

- **Standard library only.** No new runtime dependencies (`dataclasses`,
  `datetime`, `enum`, `hashlib`, `re`).
- **Frozen and hashable.** Every contract is a `@dataclass(frozen=True,
  slots=True)`. Sequence fields are tuples; a list or set raises `TypeError`.
- **Data, not policy.** Validation covers structural invariants only. Ranking,
  chunking, permission evaluation, and freshness thresholds live in the layers
  that own them.
- **Timezone-aware timestamps.** Every `datetime` field must carry a UTC
  offset; naive datetimes raise `ValueError`.
- **Canonical content hash.** `compute_content_hash()` returns lowercase
  SHA-256 hex over UTF-8 bytes. Every hash field is validated against
  `^[0-9a-f]{64}$`.
- **Schema version.** `SCHEMA_VERSION = 2`. Version 1 databases migrate
  additively to add query-level retrieval audit events; the projection remains
  disposable and sources remain authoritative.

Shared enumerations:

| Enum | Values | Purpose |
|------|--------|---------|
| `Authority` | `canonical`, `derived` | Declared by config, never inferred from content. `AUTHORITY_RANK` gives canonical=0, derived=1 so canonical outranks derived. |
| `Trust` | `human_authored`, `curated`, `model_produced` | Model-produced text must be flagged wherever it is cited. |
| `Visibility` | `private`, `project`, `public` | Coarse permission class; `private` is the fail-closed default. |
| `PrincipalType` | `human`, `machine`, `ai_employee` | The Agent Board identity kinds. |
| `DocumentType` | `markdown`, `plain_text`, `docx`, `xlsx`, `pptx`, `email`, `other` | The v1 formats plus the selected second connector. |
| `ChunkKind` | `source_slice`, `derived_artifact` | A chunk is a direct slice or an LLM-normalized distillation. |
| `ChangeType` | `created`, `updated`, `deleted`, `purged` | Journal event kinds. |

## Identity

Identity is locked: it must survive re-chunking, re-embedding, and schema
migration, because retrieval receipts refer to it after the projection has
moved on.

### `KnowledgeItemId`

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `connector_id` | `str` | yes | Non-empty. Identifies the connector instance that owns the source object. |
| `source_object_id` | `str` | yes | Non-empty. Stable for the lifetime of the source object, assigned by the connector. |

`str(item_id)` renders `connector_id:source_object_id`. Two items from
different connectors are never the same item, even if their bytes match.

### `ChunkId`

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `item_id` | `KnowledgeItemId` | yes | The owning item. |
| `chunk_ordinal` | `int` | yes | `>= 0`. Position within the item under the declared chunker. `bool` is rejected. |
| `content_hash` | `str` | yes | SHA-256 hex of the chunk text as normalized by the chunker. |

**Chunk IDs intentionally change when chunk contents change.** That is the
reason a receipt records the item ID, the hash, and the source locator as well
as the chunk ID — a chunk ID alone becomes unresolvable after re-ingestion.

### `SourceLocator`

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `connector_id` | `str` | yes | Non-empty. |
| `uri` | `str` | yes | Non-empty. Canonical reference back into the authoritative system (`file://`, `https://`, message URI). |
| `label` | `str \| None` | no | Human-readable path or subject. |
| `fragment` | `str \| None` | no | Heading anchor, sheet name, slide number, or message ID within the object. |

### `Principal`

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `principal_id` | `str` | yes | Non-empty. Consumed from the Agent Board identity model; lee-kb does not mint identities. |
| `principal_type` | `PrincipalType` | no (`human`) | Humans, machine identities, and AI employees share one identity system. |
| `display_name` | `str \| None` | no | Non-empty when present. |
| `groups` | `tuple[str, ...]` | no (`()`) | Group memberships used by the authorization layer. |

There is no anonymous principal. A surface may supply a default — the personal
CLI defaults to Lee — but the API never accepts a request without one.

## Knowledge Item

`KnowledgeItem` is the normalized projection of one source artifact. The
original system remains authoritative.

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `item_id` | `KnowledgeItemId` | yes | Primary key of the projection. |
| `project` | `str` | **yes, no default** | Non-empty. See [Projects](#projects). |
| `source_locator` | `SourceLocator` | yes | `source_locator.connector_id` must equal `item_id.connector_id`. |
| `document_type` | `DocumentType` | yes | Drives the document-type filter. |
| `content_hash` | `str` | yes | SHA-256 hex over the whole source artifact. Change detection compares this value. |
| `source_timestamp` | `datetime` | yes | When the source object last changed, per the source system. |
| `sync_timestamp` | `datetime` | yes | When lee-kb last synchronized it. |
| `permissions` | `PermissionSet` | yes | No default: an implicit permission set would be an implicit grant. |
| `title` | `str \| None` | no | Non-empty when present. |
| `tags` | `tuple[str, ...]` | no (`()`) | Filterable labels. |
| `authority` | `Authority` | no (`derived`) | Declared, never inferred. |
| `trust` | `Trust` | no (`curated`) | Declared, never inferred. |
| `tombstone` | `bool` | no (`False`) | `True` means the source object was deleted. |
| `tombstoned_at` | `datetime \| None` | no | Must be set when `tombstone` is `True`, and must be absent when it is `False`. |
| `schema_version` | `int` | no (`SCHEMA_VERSION`) | Version of the projection schema that produced the row. |

Derived property: `is_retrievable` is `not tombstone`. Tombstoned items are
excluded from ordinary search but their receipts stay resolvable; purge is an
optional governance policy, not the default.

## Chunk

`Chunk` is the retrievable portion of an item — either a direct slice or a
derived artifact.

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `chunk_id` | `ChunkId` | yes | Carries the item identity and the content hash. |
| `project` | `str` | yes | Non-empty. Must match the owning item's project — enforced by the repository at write time, not by the dataclass, which cannot see the item. |
| `text` | `str` | yes | Non-empty. `chunk_id.content_hash` is the hash of this text as normalized by `chunker_id`. |
| `chunker_id` | `str` | yes | Non-empty, versioned (`markdown-atx-v1:1`). Changing the chunker changes every chunk ID it produces. |
| `kind` | `ChunkKind` | no (`source_slice`) | Documents slice; conversational sources distill. |
| `heading` | `str \| None` | no | Section heading, for citation rendering. |
| `occurrence` | `int` | no (`0`) | `>= 0`. Disambiguates repeated identical headings. |
| `start_offset` | `int \| None` | no | `>= 0` when present. Byte offset into the source artifact. |
| `token_count` | `int \| None` | no | `>= 0` when present. |

Derived properties: `item_id` and `content_hash` read through `chunk_id`, so
the two can never disagree.

Neighbor expansion (pulling in adjacent chunks after ranking) uses
`chunk_ordinal`; no additional field is needed for it in v1.

## Evidence Bundle

`retrieve()` takes a `RetrieveRequest` and returns an `EvidenceBundle`. No LLM
is involved. `answer()` layers planning and synthesis on top and is out of
scope for Sprint 1.

### `RetrieveRequest`

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `query` | `str` | yes | Non-empty. |
| `principal` | `Principal` | yes | The API never accepts an anonymous request. |
| `project` | `str` | yes | Non-empty. The primary query scope. |
| `top_k` | `int` | no (`10`) | `>= 1`. `bool` is rejected. |
| `filters` | `MetadataFilters` | no (empty) | See below. |
| `freshness` | `FreshnessRequirement` | no (default) | See [Freshness](#freshness). |
| `include_tombstoned` | `bool` | no (`False`) | Ordinary search excludes tombstoned items. |

Derived property: `effective_projects` is `filters.projects` when set,
otherwise `(project,)`.

### `MetadataFilters`

Simple equality and range matching only — there is no query language and no
boolean composition. An empty tuple means "no constraint on this dimension".

| Field | Type | Default | Invariant |
|-------|------|---------|-----------|
| `connectors` | `tuple[str, ...]` | `()` | Equality against `item_id.connector_id`. |
| `projects` | `tuple[str, ...]` | `()` | When non-empty it **must contain** `request.project`; it widens the scope, it can never silently replace it. |
| `document_types` | `tuple[DocumentType, ...]` | `()` | Equality against `KnowledgeItem.document_type`. |
| `tags` | `tuple[str, ...]` | `()` | Equality against `KnowledgeItem.tags`. |
| `date_range` | `DateRange \| None` | `None` | Range over `source_timestamp`. |

`DateRange` has `start` and `end`, both optional and both timezone-aware; when
both are set, `start <= end`.

### `RetrieverRank`

Carried from day one, while only lexical retrieval exists, so reciprocal rank
fusion can be added without a schema change.

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `retriever` | `str` | yes | Non-empty (`lexical`, later `semantic`, `rerank`). |
| `rank` | `int` | yes | `>= 1` (1-based). |
| `score` | `float \| None` | no | Retriever-native score; not comparable across retrievers. |

### `Citation`

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `item_id` | `KnowledgeItemId` | yes | Must equal `chunk_id.item_id`. |
| `chunk_id` | `ChunkId` | yes | The cited chunk. |
| `source_locator` | `SourceLocator` | yes | Lets the reader open the original. |
| `title` | `str \| None` | no | Non-empty when present. |
| `heading` | `str \| None` | no | Non-empty when present. |
| `authority` | `Authority` | no (`derived`) | Rendered with the citation. |
| `trust` | `Trust` | no (`curated`) | `model_produced` must be visible on the citation. |

### `Evidence`

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `chunk_id` | `ChunkId` | yes | Identity of the retrieved chunk. |
| `project` | `str` | yes | Must be inside the request's effective project scope. |
| `text` | `str` | yes | Non-empty. |
| `citation` | `Citation` | yes | `citation.chunk_id` must equal `chunk_id`. |
| `retriever_ranks` | `tuple[RetrieverRank, ...]` | yes | Non-empty; at most one entry per retriever name. |
| `fused_rank` | `int` | yes | `>= 1`. Final position after fusion and reranking. |
| `source_timestamp` | `datetime` | yes | When the source last changed. |
| `sync_timestamp` | `datetime` | yes | When it was last synchronized. |
| `fused_score` | `float \| None` | no | Fusion score, when one was computed. |
| `kind` | `ChunkKind` | no (`source_slice`) | Marks distilled artifacts. |

Derived properties: `item_id` and `content_hash` read through `chunk_id`.

### `EvidenceBundle`

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `request` | `RetrieveRequest` | yes | The request that produced the bundle, retained for audit. |
| `evidence` | `tuple[Evidence, ...]` | yes | `len(evidence) <= request.top_k`; ordered by strictly ascending `fused_rank`. |
| `citations` | `tuple[Citation, ...]` | yes | Must equal `tuple(e.citation for e in evidence)` — position for position. |
| `receipts` | `tuple[RetrievalReceipt, ...]` | yes | One per evidence item, same order, same chunk ID, same principal, same retrieval timestamp. |
| `freshness` | `FreshnessReport` | yes | See [Freshness](#freshness). |
| `retrieval_timestamp` | `datetime` | yes | When retrieval ran. |
| `retrievers_used` | `tuple[str, ...]` | no (`()`) | Which retrievers contributed. |
| `denied_count` | `int` | no (`0`) | `>= 0`. Candidates removed by permission filtering — the audit trace of governance actually running. |
| `truncated` | `bool` | no (`False`) | More evidence existed than `top_k` allowed. |

Because citations and receipts mirror evidence position for position, a
consumer can never present a piece of evidence that has no citation or no
receipt. Conflicting evidence is included in the bundle; the engine does not
detect contradictions.

## Retrieval Receipt

`RetrievalReceipt` is the auditable record of one piece of evidence leaving
the platform. It is always on, including in a single-user deployment.

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `knowledge_item_id` | `KnowledgeItemId` | yes | Must equal `chunk_id.item_id`. |
| `chunk_id` | `ChunkId` | yes | Identity of the chunk that was returned. |
| `content_hash` | `str` | yes | Must equal `chunk_id.content_hash`. |
| `source_locator` | `SourceLocator` | yes | Where to verify the evidence in the authoritative system. |
| `retrieval_timestamp` | `datetime` | yes | When the evidence was released. |
| `principal` | `Principal` | yes | Who received it. |
| `project` | `str` | yes | The scope the retrieval ran under. |
| `query` | `str` | yes | Why the evidence was retrieved. |

**None of these fields has a default.** A receipt with a missing field is not
a partial receipt; it is not a receipt. `tests/test_contracts.py` asserts both
the presence of the required field names and the absence of defaults on them.

The receipt stays independently verifiable after the projection evolves: even
once the chunk has been re-chunked and its chunk ID no longer resolves, the
item ID, content hash, and source locator still identify exactly what was
released.

## Retrieval Audit Event

`RetrievalAuditEvent` is the durable query-level audit record. Unlike a
`RetrievalReceipt`, it is present even when no evidence is released, and it
records denied candidates without exposing their source identity.

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `query` | `str` | yes | The governed query. |
| `retrieval_timestamp` | `datetime` | yes | When the query was evaluated. |
| `principal` | `Principal` | yes | Who requested the query. |
| `project` | `str` | yes | The requested scope. |
| `candidate_count` | `int` | yes | All provider candidates before permission filtering. |
| `denied_count` | `int` | yes | Candidates denied by permission filtering; never greater than `candidate_count`. |
| `released_count` | `int` | yes | Evidence released after permission and freshness checks. |
| `truncated` | `bool` | yes | Whether permitted candidates exceeded `top_k`. |
| `status` | `RetrievalAuditStatus` | yes | `completed`, `stale_refused`, or `provider_failed`. |

The event covers empty, fully denied, mixed permitted/denied, stale-refused,
and provider-failure outcomes. It contains counts and request identity only;
per-evidence source locators remain exclusively in release receipts.

## Synchronization Journal

The repository stores a latest-state projection; documents are not versioned.
The append-only journal is what answers "what changed this week?", "when did
this document first change?", and "when was this connector last updated?"

`JournalEntry`:

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `connector_id` | `str` | yes | Non-empty. |
| `source_object_id` | `str` | yes | Non-empty. Together with `connector_id` it forms `item_id`. |
| `project` | `str` | yes | Non-empty. Lets "what changed" be answered per project. |
| `change_type` | `ChangeType` | yes | See the table below. |
| `sync_timestamp` | `datetime` | yes | When the event was observed. |
| `content_hash` | `str \| None` | conditional | Hash after the event. |
| `previous_content_hash` | `str \| None` | conditional | Hash before the event. |
| `sequence` | `int \| None` | no | Repository-assigned append order. |

Hash invariants by change type:

| `change_type` | `content_hash` | `previous_content_hash` | Extra |
|---------------|----------------|-------------------------|-------|
| `created` | required | must be absent | First time this object was seen. |
| `updated` | required | required | The two hashes must differ. |
| `deleted` | must be absent | required | The item is tombstoned, not removed. |
| `purged` | must be absent | required | Optional governance policy removed the projection. |

Unchanged source objects are **not** journaled — a repeated sync over ~1,200
documents must not write ~1,200 no-op rows.

Derived property: `item_id` returns `KnowledgeItemId(connector_id,
source_object_id)`.

## Permissions

`PermissionSet` records permission *facts* captured at ingest. Evaluation is
the authorization layer's job and happens before evidence assembly — never
after, and never after evidence has reached a model.

| Field | Type | Required | Invariant |
|-------|------|----------|-----------|
| `owner` | `str` | yes | Non-empty. The principal that owns the source object. |
| `visibility` | `Visibility` | no (`private`) | Fail-closed default. |
| `allowed_principals` | `tuple[str, ...]` | no (`()`) | Explicit principal grants. |
| `allowed_groups` | `tuple[str, ...]` | no (`()`) | Explicit group grants. |
| `classification` | `str \| None` | no | Non-empty when present. Deployment-defined label. |

Rules this encodes:

- `permissions` is a required field on `KnowledgeItem`, so no item can enter
  the projection without one. A defaulted permission set would be an implicit
  grant.
- The defaults grant nothing beyond the owner: empty allow lists plus
  `private` visibility.
- Retrieval never grants execution authority. lee-kb answers "what evidence
  exists?"; Agent-Orch answers "what actions are authorized?"
- `EvidenceBundle.denied_count` is where permission filtering becomes visible
  to an auditor.

The Employee Zero reference implementation carried `acl`, `audience`, and
`classification` fields that its only producer always set to `None` — present
in the type, never populated, never enforced. The Sprint 1 contract avoids
that by making the field required and the defaults deny-by-default.

## Projects

A project is a named bundle of knowledge sources — lightweight references, not
copies. The same source can belong to more than one project without
duplication.

- **Required, no default, on every knowledge record.** `KnowledgeItem`,
  `Chunk`, `JournalEntry`, `RetrieveRequest`, and `RetrievalReceipt` all take
  `project` as a required constructor argument. Omitting it raises
  `TypeError`; passing an empty or whitespace-only string raises `ValueError`.
- **`DEFAULT_PROJECT = "default"`** is what a personal deployment uses. The
  boundary exists in the data model from day one at near-zero cost.
- **Queries are scoped.** `RetrieveRequest.project` is the primary scope.
  `MetadataFilters.projects` may widen it, but must contain the request
  project, so the scope can never be silently swapped.
- **Evidence cannot escape scope.** `EvidenceBundle` rejects any evidence
  whose project is outside `request.effective_projects`.
- For customer deployments the project is also the tenancy boundary; scoping
  doubles as isolation.

## Freshness

Retrieval reports staleness honestly rather than blocking on external systems.
Synchronous connector refresh is opt-in per query, never the default, because
it converts a fast local retrieval into a dependency on an external API's
latency and rate limits.

Three timestamps travel with every retrieval:

| Timestamp | Where it lives |
|-----------|----------------|
| source | `KnowledgeItem.source_timestamp`, `Evidence.source_timestamp` |
| synchronization | `KnowledgeItem.sync_timestamp`, `Evidence.sync_timestamp` |
| retrieval | `EvidenceBundle.retrieval_timestamp`, `RetrievalReceipt.retrieval_timestamp` |

`FreshnessRequirement` (on the request):

| Field | Type | Default | Invariant |
|-------|------|---------|-----------|
| `max_staleness` | `timedelta \| None` | `None` | Must not be negative. `None` means no requirement. |
| `allow_refresh` | `bool` | `False` | Opt-in synchronous connector refresh. |
| `fail_on_stale` | `bool` | `False` | Default is to report staleness, not to fail. |

`FreshnessReport` (on the bundle):

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `is_stale` | `bool` | — | Whether any returned evidence is older than the requirement. |
| `requirement_satisfied` | `bool` | — | Whether `max_staleness` was met. |
| `oldest_sync_timestamp` | `datetime \| None` | `None` | Drives "last synced 3 hours ago". |
| `newest_source_timestamp` | `datetime \| None` | `None` | Newest source change in the bundle. |
| `staleness` | `timedelta \| None` | `None` | Observed staleness. |
| `refreshed` | `bool` | `False` | Whether a synchronous refresh actually ran. |

## Open Questions

1. **Cross-project retrieval in v1.** `MetadataFilters.projects` can widen a
   query beyond `request.project`. Should v1 allow that at all, or should the
   scope be exactly one project until the authorization layer can prove the
   principal is entitled to each project in the list?
2. **Permission basis on the receipt.** The receipt records the principal but
   not *why* access was granted (owner, explicit grant, group, project
   visibility). Adding a `permission_basis` field would make "under what
   permissions" fully answerable; it is deferred until the authorization layer
   exists and can populate it honestly.
3. **Hash normalization.** `content_hash` is SHA-256 over UTF-8 text for
   chunks and over the source artifact for items. The exact normalization
   applied before hashing (line endings, trailing whitespace, Office
   extraction output) belongs to S1-02/S1-04 and must be pinned there, since
   it silently changes every chunk ID.
4. **Office document types.** `DocumentType` enumerates `docx`, `xlsx`, and
   `pptx`; the approved deterministic parsing libraries are registered in the
   local connector and documented in `docs/office-ingestion.md`.
5. **Chunk-level permissions.** Permissions are modeled at the item level. A
   spreadsheet with per-sheet restrictions or a mail thread with a restricted
   attachment would need chunk-level overrides. Deferred until a connector
   actually needs it.
6. **Journal retention.** The journal is append-only with no stated retention
   policy. At ~1,200 documents this is a non-issue; it needs an answer before
   the email connector's re-ingest-on-every-reply pattern lands.
