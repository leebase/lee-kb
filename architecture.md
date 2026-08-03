# Lee Knowledge Base (lee-kb)

## Architecture

# Philosophy

lee-kb is a Governed Knowledge Fabric.

It is not a database.

It is not a search engine.

It is not a vector store.

It is a platform that connects organizational knowledge sources and exposes governed retrieval services.

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
- metadata extraction
- content hashing
- relationship extraction
- embedding requests
- persistence

Atomic updates ensure connector cursors advance only after successful ingestion.

---

## Knowledge Repository

Stores:

- knowledge items
- chunks
- metadata
- permissions
- relationships
- synchronization state
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
- reranking
- evidence assembly
- freshness checks
- contradiction detection
- citations

Produces an Evidence Bundle.

---

## Authorization Layer

Responsible for permission enforcement.

Authorization occurs before evidence reaches an LLM.

Retrieval never grants execution authority.

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

# Normalized Knowledge Model

Knowledge Source

↓

Knowledge Item

↓

Chunk

↓

Embedding (optional)

↓

Evidence

Everything retrieved by the platform is normalized into this model regardless of origin.

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

The retrieval engine may perform targeted connector refreshes before completing a request.

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
