# Lee Knowledge Base Project Plan

> **Strategic roadmap** — stable, long-term planning for the governed
> knowledge fabric. For tactical execution, see `sprint-plan.md`.

## Project Overview

Lee Knowledge Base (`lee-kb`) connects distributed knowledge sources to a
permission-aware retrieval service. It synchronizes enough information to make
it searchable while leaving each source system authoritative.

## Objectives

### Primary objective

Deliver a trustworthy retrieval substrate through which humans and AI employees
can find evidence without knowing where the original information lives.

### Secondary objectives

- Preserve source ownership, provenance, permissions, and freshness.
- Make connectors, search providers, embeddings, rerankers, and persistence replaceable.
- Provide an auditable retrieval receipt for every governed evidence request.
- Grow from a useful personal deployment to small-group profiles without
  changing the public architecture. Enterprise administration is not an active
  product goal.

## Non-negotiable constraints

- Original systems remain authoritative; lee-kb stores a projection.
- Permission filtering happens before evidence reaches an AI model.
- Retrieval never grants execution authority.
- The first release is personal, local-first, SQLite-backed, and lexical.
- No external runtime dependency or enterprise infrastructure is added without explicit approval.
- Every major subsystem must be independently testable.

## Development Phases

### Phase 0 — Product, architecture, and research alignment

**Status:** Complete

**Deliverables:**

- Product definition with first-release scope and success criteria.
- Architecture with connector, ingestion, repository, retrieval, authorization, and provider boundaries.
- Research notes capturing useful ingestion, normalization, hybrid retrieval, and audit patterns.
- AgentFlow project memory, roles, and skills aligned with those sources of truth.

### Phase 1 — Personal foundation

**Status:** Complete

**Goal:** Reimplement the existing Employee Zero knowledge system on the lee-kb architecture — one complete local-document retrieval path proven against the real deployed corpus (~1,200 documents, 15 source roots).

**Migration principle:** Preserve the existing `knowledge/sources.toml` source-root configuration and rebuild the knowledge projection from sources. The existing `.kb/index.sqlite` is a reference, not an authority. The current `python -m kb build` process already demonstrates configurable roots, deterministic chunking, provenance, content hashes, atomic rebuild, and SQLite FTS5 — lee-kb evolves this workflow rather than replacing it.

**Core components:**

1. Connector contract and local-file connector.
2. Normalized knowledge-item and chunk model with required project field.
3. SQLite repository with sync state, append-only sync journal, schema version, and transactions.
4. Deterministic chunking and lexical search.
5. Provenance, freshness metadata, authorization filtering, and retrieval receipts.
6. Golden evaluation corpus (~20 real questions) establishing the lexical baseline.

**Success criteria:**

- A changed local document is incrementally synchronized.
- Exact-token queries return ranked chunks with source citations.
- Results are filtered before evidence assembly and carry freshness data.
- The golden corpus runs as a test fixture and records a measurable baseline.
- The workflow is covered by automated and end-to-end user-path tests.
- **Acceptance:** the Chief of Staff can switch from the old `kb` commands to lee-kb without losing capability.

### Phase 2 — Personal connector expansion

**Status:** Next / proposed; Sprint 2 closure decisions remain separately tracked

**Goal:** Extend Lee's Second Brain to the places his personal knowledge lives,
while preserving the first-release contracts and avoiding enterprise
infrastructure.

**Potential components:**

- Connector conformance tests and a source capability matrix.
- Local project directories, including `/projects`.
- Selected OneDrive folders.
- Outlook/Microsoft 365 mail, followed by Gmail.
- OneNote feasibility and, if supported cleanly, a notebook/page connector.
- MCP server exposing the same public retrieval API as the CLI.
- Metadata filters and relationship extraction.
- Optional semantic search provider and hybrid ranking — must demonstrate measurable improvement over the lexical golden-corpus baseline.
- Targeted refresh (opt-in per query) when a freshness requirement cannot be met from the projection.

### Phase 3 — Small-group sharing (conditional)

**Status:** Parked until a concrete second-user workflow exists

**Goal:** Support shared projects and additional principals without changing the
governed retrieval contract.

**Potential components:**

- PostgreSQL persistence provider.
- Explicit tenant and permission models.
- Central retrieval service and connector health operations.
- Expanded retrieval audit reporting.

### Phase 4 — Enterprise infrastructure

**Status:** Not on the active roadmap

**Potential components:**

- Snowflake persistence profile.
- Customer-specific connector sets and tenant isolation.
- High availability and multiple retrieval services.
- Integrations for Agentflow, Agent-Orch, Employee Zero, and customer AI employees.

These are retained as architectural possibilities, not commitments. They
require a concrete product need before planning or implementation.

## Architecture Principles

1. Connect instead of migrate.
2. Normalize instead of duplicate.
3. Retrieve evidence before reasoning.
4. Preserve provenance and freshness.
5. Enforce authorization before model access.
6. Keep execution governance separate from retrieval.
7. Prefer small, replaceable provider interfaces.
8. Build the smallest useful vertical slice before scaling.

## Core Components

| Component | Responsibility |
|-----------|----------------|
| Connector Manager | Lifecycle, authentication, scheduling, changes, health, and cursors |
| Ingestion Engine | Normalization, chunking, metadata, relationships, embeddings, and persistence |
| Knowledge Repository | Projection of items, chunks, permissions, relationships, sync state, and receipts |
| Search Providers | Lexical, semantic, and reranking implementations behind interfaces |
| Retrieval Engine | Planning, filtering, retrieval, ranking, freshness, evidence, and citations |
| Authorization Layer | Permission enforcement before evidence reaches an AI model |
| Retrieval API | Stable consumer-facing access for humans and AI employees |

## Risks

| Risk | Mitigation |
|------|------------|
| Permission mistakes expose source content | Define and test authorization before evidence assembly |
| Stale projections produce misleading answers | Track source/sync/retrieval timestamps and support targeted refresh |
| Connector-specific behavior leaks into retrieval | Keep connector lifecycle and source semantics behind the common contract |
| Early semantic infrastructure slows validation | Start with SQLite and lexical retrieval |
| Scope expands toward enterprise too soon | Gate each phase on first-release success criteria |

## Success Metrics

- Users can answer representative questions without naming the source system.
- Every returned evidence item has inspectable provenance.
- Unauthorized source content never enters an evidence bundle.
- Freshness status and retrieval receipts are available for every request.
- A connector can be added without changing retrieval consumers.
- Personal-release tests remain fast and deterministic.

## Current Status

**Phase:** Phase 0 complete; Phase 1 complete; Phase 2 queued
**Mode:** Collaborative implementation with human approval
**Next milestone:** Prove the connector boundary and capability matrix for the
personal connector expansion

*Keep this document strategic; put task-level changes in `sprint-plan.md`.*
