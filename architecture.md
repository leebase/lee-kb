# Lee Knowledge Base (lee-kb)

## Architecture

# Philosophy

lee-kb is a Governed Knowledge Fabric.

It is not a database.

It is not a search engine.

It is not a vector store.

It is a platform that connects organizational knowledge sources and exposes governed retrieval services.

lee-kb is a platform, not a subsystem of any consumer. Agent-Orch, Agentflow, Chief of Staff, Employee Zero, and customer AI employees are all consumers of the same public knowledge platform.

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

Connectors never implement retrieval policy.

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

MCP Server (Phase 2) → Knowledge Library

Every consumer surface exercises the exact same public retrieval API.

---

# Connector Model

Every connector implements a common contract.

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

Example:

Application Development Connector

- GitHub
- Agent-Orch
- CI
- Releases
- Documentation

Consumers remain unaware of internal composition.

---

# Projects

A project is a named bundle of knowledge sources: specific connectors, repos, mailboxes, channels, and databases relevant to a team, client, or initiative.

Projects are intentionally lightweight — references, not copies.

The same source can belong to multiple projects without duplication.

Queries are scoped to a project by default. "Search everything everywhere" stops being useful as the corpus grows.

Every knowledge item belongs to exactly one project. The project field is required from the first release — a personal deployment uses a single `default` project. Forcing every item through a project boundary from day one makes multi-tenancy, scoping, and selective synchronization clean later, at almost no cost now.

For customer deployments, a project is also the natural tenancy boundary: client Acme's project bundles Acme's sources, and scoping doubles as isolation.

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

Database-specific optimizations remain behind provider interfaces.

The schema carries a stored version number and a migration framework from version 1.

The documented v1 upgrade path is wipe-and-resync: the projection is intentionally disposable because authoritative systems remain the source of truth. Real migrations become mandatory once customer deployments begin.

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

---

# Freshness

Every answer should know:

- source timestamp
- synchronization timestamp
- retrieval timestamp

Retrieval reports staleness honestly ("last synced 3 hours ago") rather than blocking on external systems.

Synchronous connector refresh is opt-in per query, never default. A refresh turns a fast local retrieval into a dependency on an external API's latency and rate limits — callers must ask for that explicitly.

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

## Personal

SQLite

Single user

Periodic polling

Local embeddings

Local search

---

## Team

PostgreSQL

Multiple users

Shared connectors

Central retrieval service

---

## Enterprise

Snowflake or PostgreSQL

Customer-specific connector sets

Multiple retrieval services

Tenant isolation

High availability

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
- Build for evolution from SQLite to PostgreSQL and Snowflake without changing the public architecture.
