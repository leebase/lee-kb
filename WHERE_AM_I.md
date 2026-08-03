# WHERE_AM_I — Lee Knowledge Base

> **Product-level orientation.** This file tracks progress toward the governed
> knowledge-fabric vision. For session-level detail, see `context.md`.

## Project Health

| Attribute | Value |
|-----------|-------|
| **Project** | Lee Knowledge Base (`lee-kb`) |
| **Profile** | Python package / governed retrieval service |
| **Current Phase** | Phase 0 — Product and Architecture Alignment |
| **Overall Status** | 🟢 Direction defined; 🟡 implementation not started |
| **Last Updated** | 2026-08-03 |

## Progress Against Product Goals

Reference: `product-definition.md` and `architecture.md`.

### First-release criteria

| Criterion | Status | Notes |
|-----------|--------|-------|
| Personal deployment shape is defined | ✅ Done | SQLite, single user, local-first |
| Connector contract is implemented | ⬜ Not started | Must cover discovery, changes, fetch, permissions, refresh, health, and checkpointing |
| Local documents synchronize into normalized knowledge | ⬜ Not started | First ingestion vertical slice |
| SQLite repository persists items, chunks, metadata, and sync state | ⬜ Not started | Repository is a projection, not the source of truth |
| Lexical retrieval returns ranked evidence | ⬜ Not started | Semantic search is later |
| Results cite original sources | ⬜ Not started | Provenance is required for every evidence item |
| Results report freshness | ⬜ Not started | Source, synchronization, and retrieval timestamps |
| Retrieval receipts are recorded | ⬜ Not started | Include why and under what permissions evidence was returned |

### Current phase goals

| Goal | Status | Notes |
|------|--------|-------|
| Establish product direction | ✅ Done | Product definition is the scope authority |
| Establish system boundaries | ✅ Done | Architecture separates connectors, ingestion, repository, retrieval, and authorization |
| Capture useful research patterns | ✅ Done | See `research/cerebras.kb` |
| Align AgentFlow project memory | ✅ Done | Root docs, roles, and skills are consistent |
| Build the first end-to-end retrieval path | ⬜ Next | Sprint 1 — Personal Foundation |

## Sprint Position

| Sprint | Focus | Status |
|--------|-------|--------|
| Sprint 1 — Personal Foundation | Local documents → SQLite → lexical evidence | 🟡 Ready for implementation |

## Product Risks and Blockers

| Risk or blocker | Impact | Status | Mitigation |
|----------------|--------|--------|------------|
| Permission semantics are not yet specified | Unauthorized evidence could leak | 🟡 Open | Define the authorization boundary before retrieval reaches an AI model |
| Connector APIs differ in change tracking and freshness | Sync correctness may vary by source | 🟡 Open | Keep lifecycle and cursor behavior in the connector contract |
| Provider abstractions could become over-designed | Slows first useful release | 🟡 Watch | Implement SQLite and lexical providers behind the smallest useful interfaces |
| Research patterns may imply enterprise scale too early | Scope drift | 🟢 Controlled | Keep personal deployment and local documents as the first vertical slice |

## Key Decisions

| Decision | Rationale | Date |
|----------|-----------|------|
| Source systems remain authoritative | lee-kb is a searchable projection, not a migration target | 2026-08-03 |
| First release is personal and SQLite-backed | Enables fast validation without enterprise infrastructure | 2026-08-03 |
| Retrieval and execution governance are separate | Evidence access must not grant permission to act | 2026-08-03 |
| Lexical search is the first retrieval provider | Provides a deterministic baseline before semantic complexity | 2026-08-03 |

## What “Done” Looks Like

- [ ] A local document can be discovered, synchronized, normalized, and chunked.
- [ ] The SQLite projection can be queried with lexical retrieval.
- [ ] Unauthorized content is filtered before evidence assembly.
- [ ] Every result includes original-source provenance and freshness metadata.
- [ ] Every retrieval creates an auditable receipt.
- [ ] The full first-release workflow is covered by automated and user-path tests.

*Update this file when a milestone is reached or product direction changes.*
