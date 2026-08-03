# WHERE_AM_I — Lee Knowledge Base

> **Product-level orientation.** This file tracks progress toward the governed
> knowledge-fabric vision. For session-level detail, see `context.md`.

## Project Health

| Attribute | Value |
|-----------|-------|
| **Project** | Lee Knowledge Base (`lee-kb`) |
| **Profile** | Python package / governed retrieval service |
| **Current Phase** | Phase 1 — Sprint 1 Personal Foundation delivered |
| **Overall Status** | 🟢 First governed retrieval path (local files → SQLite → lexical evidence) delivered; office formats and the curated golden benchmark remain deferred |
| **Last Updated** | 2026-08-03 |

## Progress Against Product Goals

Reference: `product-definition.md` and `architecture.md`.

### First-release criteria

| Criterion | Status | Notes |
|-----------|--------|-------|
| Personal deployment shape is defined | ✅ Done | SQLite, single user, local-first |
| Connector contract is implemented | ✅ Done | `Connector` ABC (`src/lee_kb/connectors/base.py`) covers discovery, changes, fetch, permissions, relationships, refresh, health, and checkpointing; local-file connector implements it. Office-format file types are enumerated but not yet registered (deferred, see below) |
| Local documents synchronize into normalized knowledge | ✅ Done | `lee-kb sync`; verified by `tests/test_local_connector.py` and a manual end-to-end run |
| SQLite repository persists items, chunks, metadata, and sync state | ✅ Done | `src/lee_kb/repository.py`, transactional, with a schema version and an append-only journal; verified by `tests/test_repository.py` |
| Lexical retrieval returns ranked evidence | ✅ Done | BM25-based retrieval in `src/lee_kb/retrieval.py`; verified by `tests/test_retrieval.py` |
| Results cite original sources | ✅ Done | Every `Evidence` carries a `Citation` with source locator; verified by `tests/test_retrieval.py` and `tests/test_cli.py` |
| Results report freshness | ✅ Done | `FreshnessReport` on every `EvidenceBundle`; CLI prints sync age per result |
| Retrieval receipts are recorded | ✅ Done | One `RetrievalReceipt` persisted per evidence item, including the empty-result case; verified by `tests/test_governance.py` |

Office-format parsing (`.docx`, `.xlsx`, `.pptx`) and the curated Chief-of-Staff
golden benchmark are explicitly out of this delivery — see
`sprint-plan.md` ("Sprint closure requirements") and `docs/golden-baseline.md`.

### Current phase goals

| Goal | Status | Notes |
|------|--------|-------|
| Establish product direction | ✅ Done | Product definition is the scope authority |
| Establish system boundaries | ✅ Done | Architecture separates connectors, ingestion, repository, retrieval, and authorization |
| Capture useful research patterns | ✅ Done | See `research/cerebras.kb` |
| Align AgentFlow project memory | ✅ Done | Root docs, roles, and skills are consistent |
| Build the first end-to-end retrieval path | ✅ Done | Sprint 1 — Personal Foundation delivered; office formats and the curated golden benchmark deferred |

## Sprint Position

| Sprint | Focus | Status |
|--------|-------|--------|
| Sprint 1 — Personal Foundation | Local documents → SQLite → lexical evidence | 🟢 Delivered (office formats and curated golden benchmark deferred) |

## Product Risks and Blockers

| Risk or blocker | Impact | Status | Mitigation |
|----------------|--------|--------|------------|
| Permission semantics are not yet specified | Unauthorized evidence could leak | 🟢 Resolved for v1 | Fail-closed `SingleUserPermissionEvaluator` filters candidates before evidence assembly (`src/lee_kb/governance.py`); a multi-user model is a distinct future evaluator, not a `retrieve()` change |
| Connector APIs differ in change tracking and freshness | Sync correctness may vary by source | 🟡 Open | Local-file connector uses content-hash snapshot diffing; the email connector (next) will validate the contract against a source with a native change feed |
| Provider abstractions could become over-designed | Slows first useful release | 🟢 Resolved for v1 | SQLite repository and lexical retriever implemented behind the smallest useful `Repository`/retriever interfaces |
| Research patterns may imply enterprise scale too early | Scope drift | 🟢 Controlled | Sprint 1 stayed scoped to personal deployment, local documents, SQLite, and lexical search; office formats and semantic retrieval were deliberately deferred rather than pulled forward |

## Key Decisions

| Decision | Rationale | Date |
|----------|-----------|------|
| Source systems remain authoritative | lee-kb is a searchable projection, not a migration target | 2026-08-03 |
| First release is personal and SQLite-backed | Enables fast validation without enterprise infrastructure | 2026-08-03 |
| Retrieval and execution governance are separate | Evidence access must not grant permission to act | 2026-08-03 |
| Lexical search is the first retrieval provider | Provides a deterministic baseline before semantic complexity | 2026-08-03 |

## What “Done” Looks Like

- [x] A local document can be discovered, synchronized, normalized, and chunked.
- [x] The SQLite projection can be queried with lexical retrieval.
- [x] Unauthorized content is filtered before evidence assembly.
- [x] Every result includes original-source provenance and freshness metadata.
- [x] Every retrieval creates an auditable receipt.
- [x] The Sprint 1 workflow (local files → SQLite → lexical evidence) is covered by automated and user-path tests. Office-format ingestion is not yet implemented, so it is not yet part of this coverage.

*Update this file when a milestone is reached or product direction changes.*
