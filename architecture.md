# Lee Knowledge Base (lee-kb)

## Architecture

# Philosophy

lee-kb is a personal-first, governed Second Brain and Knowledge Fabric.

It begins as Lee's local knowledge system and is designed to extend to small
shared projects without making enterprise administration a first-release
requirement.

It is not a database.

It is not a search engine.

It is not a vector store.

It is a platform that connects personal and organizational knowledge sources
and exposes governed retrieval services.

lee-kb is a platform, not a subsystem of any consumer. Lee, the Chief of
Staff, Agent-Orch, Agentflow, Employee Zero, and future small-team consumers
use the same public knowledge platform.

The dependency direction is always: consumers depend on lee-kb, lee-kb depends on connectors. Never the reverse. This keeps lee-kb reusable, consumer-agnostic, and independently evolvable.

---

# High-Level Architecture

```
                   Consumers

    Chief of Staff
    Agentflow
    Agent-Orch
    Employee Zero
    Customer AI Employees
               │
               ▼
        Retrieval API
               │
     Authorization Layer
               │
      Retrieval Engine
               │
   ┌───────────┴────────────┐
   │                        │
Lexical Search      Semantic Search
   │                        │
   └───────────┬────────────┘
               │
       Knowledge Repository
               │
        Ingestion Engine
               │
       Connector Manager
               │
──────────────────────────────────────────
 Outlook
 OneDrive
 Gmail
 OneNote
 Local Files
 GitHub
 Teams
 Telegram
 Agent-Orch
 Agent Board
 Snowflake
 SQL Databases
 Customer Systems
```

---

# Layer Responsibilities

## Connector Manager

Responsible for:

- connector lifecycle
- authentication
- scheduling
- incremental synchronization
- health
- cursor management

Connectors never implement retrieval policy. Authentication credentials and
retrieval authorization remain separate concerns, even when a connector uses
the source provider's access token to discover visibility metadata.

---

## Ingestion Engine

Responsible for:

- normalization
- chunking
- distillation (for conversational sources)
- metadata extraction
- content hashing
- relationship extraction
- embedding requests
- persistence

Atomic updates ensure connector cursors advance only after successful ingestion.

### Office document ingestion

The local-files format registry maps `.docx`, `.xlsx`, and `.pptx` to the
approved deterministic parsers in `src/lee_kb/connectors/office.py`. Parsers
return normalized text plus safe metadata; `main._sync_connector()` then uses
the same `KnowledgeItem`, `Chunk`, SQLite, permission, freshness, citation, and
receipt path as Markdown. Office sections use a versioned structured chunker,
with `Chunk.heading` carrying paragraph, sheet/row, cell, slide, table, or
speaker-note references. There is no parallel Office repository or retrieval
surface.

The parsers read text only and fail closed on encrypted packages, malformed
archives, macros, embedded binaries/media, external links, and parser errors.
Formulas are represented as source formulas with cached displayed values when
present; they are never evaluated. Discovery reports Office candidates that
are outside include scope or protected by exclusions, while temporary read
failures are kept out of deletion diffing. The approved dependency versions
and the deployed narrow include changes are recorded in
`docs/office-ingestion.md`.

Office body text that begins with Markdown heading syntax is escaped before the
shared heading-aware chunker runs. This preserves searchability while keeping
only parser-generated locators in citation metadata. DOCX table extraction is
recursive, including nested cell tables.

For a root-scoped local sync, overlapping files retain the global ownership
rule: the deepest matching resolved root claims the source. The scoped report
and CLI expose candidates claimed by another root instead of duplicating or
silently dropping them. Public `list_changes()` uses the same failure-aware
discovery report as ingestion, so failed roots and subtrees cannot become
tombstones.

Conversational sources are mutable, not append-only: a new reply changes the meaning of the whole thread, so the entire thread is re-ingested. Content hashing is per-artifact so unchanged artifacts are never re-distilled or re-embedded.

---

## Knowledge Repository

Stores:

- knowledge items (including tombstones)
- chunks
- metadata
- permissions
- relationships
- synchronization state
- synchronization journal (append-only)
- retrieval receipts
- query-level retrieval audit events, including empty and denied outcomes

The repository stores a projection.

It is not the authoritative source.

---

## Search Providers

Separate provider interfaces for:

- lexical search
- semantic search
- reranking

Backends remain replaceable.

---

## Retrieval Engine

Coordinates:

- query planning
- metadata filters
- lexical search
- semantic search
- rank fusion
- reranking
- evidence assembly
- freshness checks
- citations

Produces an Evidence Bundle.

The engine does not detect contradictions. Conflicting evidence is included in the bundle; synthesis surfaces conflicts naturally ("source A says X, source B says Y").

The governed `answer()` surface detects conflicts only from positive evidence of
disagreement: polarity, numeric or opposed value-word divergence, recognized
morphological antonyms, one-slot substitutions in otherwise matching
statements, or explicit supersession. Declared authority describes a detected
conflict but never creates one, so a canonical restatement of a derived source
does not become a false conflict. Claim assembly uses the same signals to
refuse a merge, preventing a self-contradictory synthesized claim when conflict
detection is bypassed.

### Ranking Signals

Hybrid ranking combines complementary signals, each producing its own ranked list:

- lexical search catches exact tokens: error strings, flag names, identifiers
- semantic search catches paraphrase: different vocabulary, same problem
- inverse document frequency weights rare tokens over filler
- age decay breaks ties in favor of newer evidence

Ranked lists are fused with reciprocal rank fusion, so consensus across retrievers beats a single strong vote.

The Evidence Bundle carries per-retriever ranks from day one, even when only lexical retrieval is implemented. Fusion can then be added without schema changes.

After ranking is final, context expansion pulls in neighboring chunks so evidence arrives complete, not as lonely fragments.

---

## Authorization Layer

Responsible for permission enforcement.

Authorization occurs before evidence reaches an LLM.

Retrieval never grants execution authority.

Identity reuses the Agent Board identity model — humans, machine identities, and AI employees are one identity system. lee-kb consumes those identities; it does not define its own.

Every retrieval requires a principal. Surfaces may supply defaults (the personal CLI defaults to Lee), but the API never accepts an anonymous request.

Permission evaluation is fail-closed.

---

# Retrieval Surfaces

The platform exposes two surfaces.

## retrieve()

Returns an Evidence Bundle.

No LLM involved. Cheap, structured, stable inputs and outputs.

This is the surface for AI employees, Agent-Orch, and MCP clients — agents orchestrate their own reasoning over raw evidence.

Request fields:

- query
- principal
- top_k
- metadata filters
- freshness requirement
- project

Supported metadata filters in v1: connector, project, date range, document type, tags. Simple equality and range matching only — no query language.

## answer()

Layers query planning and synthesis on top of retrieve().

Produces an answer with citations, caveats, and cross-source synthesis.

This is the surface for humans who want an answer, not evidence rows.

Permissions enforce at retrieve(). Every surface inherits them.

## Layering

The library is the primary product. Surfaces are thin layers over it:

CLI (v1) → Knowledge Library

MCP Server (KB-R1) → Knowledge Library

Every consumer surface exercises the exact same public retrieval API.

The KB-R1 MCP adapter is stdlib JSON-RPC 2.0 over newline-delimited stdio and
preserves the incumbent `kb_search`, `kb_status`, and `kb_compile_preview`
tool contracts. It is a thin deployment surface: it never synchronizes,
builds, or writes corpus files. Search and preview call governed `retrieve()`
and therefore persist the same release receipts and query audit events as the
CLI. Registration and consumer cutover are deployment work, not part of this
library boundary.

---

# Connector Model

Every connector implements a common contract.

A connector instance represents one configured source and scope: for example,
one local root, one selected OneDrive folder, one Outlook mailbox scope, or one
Gmail label set. Its stable identity is distinct from the source objects it
discovers.

Suggested responsibilities:

- discover()
- list_changes()
- fetch()
- permissions()
- relationships()
- refresh()
- health()
- checkpoint()

Higher-level connectors may aggregate lower-level connectors.

The common contract stays small. Source-specific authentication, message
threading, notebook structure, and content normalization live behind the
connector boundary or in the ingestion layer; retrieval consumers do not learn
provider-specific APIs.

Example:

Application Development Connector

- GitHub
- Agent-Orch
- CI
- Releases
- Documentation

Consumers remain unaware of internal composition.

## Outlook Connector Boundary (BI-003)

The first external connector slice is an offline-ready Outlook/Microsoft 365
adapter behind an injected `OutlookTransport`. One connector instance owns one
delegated `/me` mailbox folder. The adapter does not own OAuth, token storage,
HTTP, or CLI configuration; a future live transport must be approved without
changing the normalized connector contract.

The adapter requests immutable message identity, uses `message:<id>` as the
source object ID, and maps one folder's opaque Graph delta link into a versioned
metadata-only cursor. It emits a cursor only after all delta pages complete;
fetch or page failures therefore cannot become deletions or advance state. A
failed fetch also blocks the in-memory checkpoint until that object succeeds,
and checkpoint input must match the completed source metadata exactly.
`lastModifiedDateTime` is the source timestamp and participates in the
normalized content hash because the common connector diff contract has no
separate metadata-only change type. Message text is normalized deterministically
with common quoted history removed. Delta events are applied in response order;
a normal move out of the folder must be a removal marker, while an unexpected
message from another folder fails closed. Conversation and attachment
identities are relationships, with attachment IDs scoped by their parent
immutable message, while attachment bytes remain outside the first slice to
avoid duplicate or unsupported content. Provider-controlled diagnostic strings
are not echoed by the adapter's health or read errors.

The bounded permission mapping is private owner access for the configured
mailbox principal, classified as delegated mail read. Successful provider
access is not treated as a complete per-message ACL. App-only access, shared
mailboxes, multi-folder aggregation, live authentication, and attachment
parsing remain separate approval decisions. See `docs/outlook-connector.md` for
the provider evidence and exact transport contract.

## Live Outlook Proof (Sprint 5 Gate)

The remaining connector increment is a personal proof against one approved real
mailbox and one disposable folder, not an enterprise integration. The Graph
transport, delegated authentication, secure token storage, and standard-library
HTTP boundary are implemented offline; account consent and any external
connection still require explicit approval.

The current repository contract advances a connector cursor when an item or
tombstone transaction is written. A live delta round can legitimately contain
no writes, so Sprint 5 uses the smallest additive repository capability for an
atomic cursor-only advance: `Repository.advance_cursor()` defaults closed for
providers that do not support it, and `SQLiteRepository` commits the cursor in
its own transaction. It preserves the previous cursor on failure and does not
weaken the existing `sync_item()`/`tombstone_item()` atomicity. This is not
approval for a breaking schema or a live connection.

The live acceptance path is deliberately narrow: authenticate, initial-sync,
incremental-sync, restart after a no-change round, recover from an expired
delta token through a safe full reconciliation, and answer a known email
question through the existing governed retrieval and deterministic answer path.
Shared mailboxes, app-only access, multi-folder aggregation, attachment bytes,
background polling, and enterprise administration remain out of scope.

---

## Microsoft Graph Foundation (Sprint 5)

The reusable Microsoft boundary is implemented in `src/lee_kb/microsoft_graph/`
and is intentionally provider-resource-neutral:

```text
GraphCredential / MicrosoftAccount
          |
OAuthTokenManager -> TokenStore -> OS secret service or explicit AES-GCM file
          |
GraphClient -> HttpTransport -> HTTPS Graph API
          |
GraphPage / GraphDeltaResult
          |
resource transport (Outlook today; OneDrive later)
```

`GraphClient` owns access-token acquisition through the token manager, verified
`/me` subject/tenant binding, one-time idempotent-read 401 refresh,
authenticated request execution, URL validation, normalized error
classification, bounded retry/backoff, `Retry-After` throttling, shared request
pacing for Graph and identity calls, collection pagination, opaque delta-link
continuation, repeated-link detection, and expired-delta restart. A connector
never adds a second Graph HTTP or retry implementation.

`MicrosoftAccount` is a local account namespace plus provider user identity and
tenant selector. `GraphCredential` contains the public client ID and requested
delegated scopes; client secrets are not persisted in the model. Token sets are
bound to a non-secret fingerprint of account, user, tenant, client, and scopes.
Changing that configuration fails closed rather than reusing a cached token.
The current personal deployment uses one account and delegated `Mail.Read` plus
minimal `User.Read` for account verification, while the model permits multiple
account records and tenant selectors later without adding a tenant
administration schema now. New Outlook cursors bind the project, local account,
configured tenant, credential fingerprint, and verified provider subject/tenant;
legacy version-1 cursors are rejected.

The default token store requires an OS-protected secret service. An explicit
AES-GCM file store is permitted only when its 32-byte key is supplied by an
external OS-protected mechanism. No plaintext fallback exists. Access tokens,
refresh tokens, device codes, provider error bodies, and delta links are never
placed in knowledge evidence, receipts, audit events, logs, or source content.
Local revocation deletes the app's stored grant; provider-side consent removal
remains an account-owner operation outside the personal connector.

`GraphOutlookTransport` maps only Graph message resources into the existing
`OutlookTransport`. The Outlook connector continues to own message identity,
normalization, permissions, and provenance. The common sync path owns the
atomic repository boundary: all prepared item/tombstone writes and the final
cursor commit together for a non-empty round, while an empty round requires
`Repository.advance_cursor()`.
That cursor-only operation also marks the connector's project synchronized so
an empty mailbox is distinguishable from a mailbox that has never been synced.
An expired delta triggers a complete Graph enumeration marked as a reset; the
connector derives missing prior IDs as tombstones and advances only after the
complete read and persistence succeed.

OneDrive is not implemented. Its future mapping is `(drive_id, item_id)` with
parent relationships, move/rename semantics, explicit permission facts, and
the same generic delta recovery. OneNote is not implemented or used to shape
this layer; notebook/section/page identity, HTML/resource normalization,
permissions, and incremental semantics remain a separate design review. See
`docs/microsoft-graph.md` for the full readiness assessments.

---

# Projects

A project is a named bundle of knowledge sources: specific connectors, repos, mailboxes, channels, and databases relevant to a team, client, or initiative.

Projects are intentionally lightweight — references, not copies.

The same source can belong to multiple projects without duplication.

Queries are scoped to a project by default. "Search everything everywhere" stops being useful as the corpus grows.

Every knowledge item belongs to exactly one project. The project field is required from the first release — a personal deployment uses a single `default` project. Forcing every item through a project boundary from day one makes multi-tenancy, scoping, and selective synchronization clean later, at almost no cost now.

## Forward-Compatible Domain Boundaries

The personal deployment uses one implicit knowledge domain and one default
principal. The contracts nevertheless keep the boundaries explicit:

- `Principal` identifies who requests retrieval.
- A connector instance identifies the configured source account and scope.
- A source owner and `PermissionSet` describe source-level access policy.
- `(connector_id, source_object_id)` identifies the source artifact.
- A project scopes related sources without copying them.
- Query-level audit events retain request identity and outcome counts.

There is intentionally no tenant column, tenant administration service, or RBAC
control plane in the personal release. If small-group sharing becomes real,
projects and principals provide the first expansion boundary; a separate tenant
model should be introduced only with a concrete deployment requirement.

For a future shared deployment, a project can be the natural knowledge-domain
boundary: one project's sources are scoped together without changing the
retrieval API. Strong tenant isolation remains a later decision, not a personal
release requirement.

---

# Normalized Knowledge Model

Knowledge Source

↓

Knowledge Item

↓

Chunk (raw slice or derived artifact)

↓

Embedding (optional)

↓

Evidence

Everything retrieved by the platform is normalized into this model regardless of origin.

## Derived Artifacts

A chunk is either a direct slice of source content or a derived artifact.

A derived artifact is an LLM-normalized distillation of source content: question, summary, resolution, systems, references.

Conversational sources (email threads, Teams, Telegram, Slack) retrieve poorly as raw transcripts. They retrieve well as derived artifacts.

Document sources typically chunk directly. Conversational sources typically distill.

Distillation costs LLM inference at ingest time and pays for it in retrieval precision.

---

# Identity

Knowledge Item ID = (connector_id, source_object_id)

Stable for the lifetime of the source object.

Chunk ID = (knowledge_item_id, chunk_ordinal, content_hash)

Chunk IDs intentionally change when chunk contents change.

Retrieval receipts therefore never rely on a chunk identifier alone. Every receipt stores:

- knowledge item ID
- chunk ID
- content hash
- source locator
- retrieval timestamp

A receipt remains independently verifiable even after the projection has evolved.

The repository stores the latest projection. Receipts preserve the historical evidence that was actually retrieved.

---

# Synchronization Journal

The repository is a latest-state projection. Documents are not versioned.

An append-only journal records every synchronization event:

- connector
- source object
- content hash
- previous content hash
- change type
- synchronization timestamp

The journal answers "what changed this week?", "when did this document first change?", and "when was this connector last updated?" without full historical reconstruction.

Full document versioning may arrive in a future release if justified.

---

# Deletion

Deletion is an explicit governance policy, not a row removal.

Default behavior when a source object is deleted:

- the knowledge item is tombstoned
- source metadata is retained
- retrieval receipts remain resolvable
- the item no longer appears in ordinary search

Optional purge policies permanently remove the projection.

Client deployments configure deletion policy to their governance requirements.

---

# Persistence

Persistence is configurable.

Initial targets:

- SQLite
- PostgreSQL
- Snowflake

The persistence abstraction provides:

- durable storage
- transactions
- upserts
- cursor persistence
- metadata
- lifecycle
- receipts
- query-level retrieval audit events

Database-specific optimizations remain behind provider interfaces.

The schema carries a stored version number and a migration framework. Version 2
adds the query-level retrieval audit event table and migrates version 1
projections additively.

The projection remains disposable and wipe-and-resync is still the fallback
v1 upgrade path because authoritative systems remain the source of truth. The
v2 audit-table change demonstrates the additive migration path; broader schema
migrations become mandatory once customer deployments begin.

Governed retrieval requires repository providers to persist the query-level
audit event for every outcome. The default repository capability fails closed
when a provider does not implement it; governed retrieval never silently
returns an unaudited bundle.

---

# Synchronization

Version 1 synchronization is explicitly user-driven:

- `lee-kb sync`
- `lee-kb sync <connector>`
- `lee-kb sync <connector> <source>`

Freshness reporting informs users when indexed knowledge may be stale.

Filesystem watchers and background services are intentionally deferred.

---

# Configuration

Configuration is a documented public contract.

Location: `~/.config/lee-kb/config.toml`

Contents:

- connectors
- roots
- include patterns
- exclude patterns
- projects
- retrieval defaults
- schedules (future)

Project-specific configuration may later override global settings.

Migration: the existing Employee Zero `knowledge/sources.toml` source roots import into this contract. The old compiled index (`.kb/index.sqlite`) is not authoritative — the projection is rebuilt from sources.

---

# Retrieval Pipeline

Question

↓

Permission evaluation

↓

Metadata filtering

↓

Lexical retrieval

↓

Semantic retrieval

↓

Hybrid ranking

↓

Reranking

↓

Freshness evaluation

↓

Targeted refresh (if required)

↓

Evidence Bundle

↓

LLM

↓

Answer with citations

↓

Retrieval Receipt

Every governed retrieval also appends a query-level retrieval audit event. The
event records request identity, candidate/denial/release counts, truncation,
and outcome status even when the evidence bundle is empty or freshness refuses
release; it never duplicates source locators.

---

# Freshness

Every answer should know:

- source timestamp
- synchronization timestamp
- retrieval timestamp

Retrieval reports staleness honestly ("last synced 3 hours ago") rather than blocking on external systems.

Synchronous connector refresh is opt-in per query, never default. A refresh turns a fast local retrieval into a dependency on an external API's latency and rate limits — callers must ask for that explicitly.

When a caller explicitly rejects stale evidence, freshness is evaluated before
release receipts are persisted. A refusal therefore cannot leave receipts that
claim evidence was released.

---

# Governance

Knowledge retrieval and execution governance remain separate systems.

lee-kb answers:

"What evidence exists?"

Agent-Orch answers:

"What actions are authorized?"

The two systems complement one another without being tightly coupled.

---

# Deployment Profiles

## Personal (current)

SQLite

Single user

Periodic polling

Local embeddings

Local search

---

## Small Group (future, not enterprise)

SQLite or PostgreSQL if needed

Multiple users

Shared projects and connectors

Additional principals and source policies

Central retrieval service only if local deployment no longer suffices

---

## Enterprise (not on the active roadmap)

Snowflake or PostgreSQL

Customer-specific connector sets

Multiple retrieval services

Tenant isolation

High availability only if a concrete product need justifies it

---

# Architectural Principles

- Connect instead of migrate.
- Normalize instead of duplicate.
- Retrieve evidence before reasoning.
- Preserve provenance.
- Preserve freshness.
- Keep execution governance separate from retrieval.
- Prefer simple, replaceable provider interfaces.
- Make every major subsystem independently testable.
- Keep the platform consumer-agnostic.
- Keep a path from SQLite to another persistence provider without changing the
  public retrieval architecture; do not build enterprise infrastructure ahead
  of evidence.
- Design for one principal now and keep principal, source, and project
  boundaries explicit for later small-group use.
