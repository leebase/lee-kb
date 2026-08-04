# WHERE_AM_I — Lee Knowledge Base

> **Product-level orientation.** This file tracks progress toward the governed
> knowledge-fabric vision. For session-level detail, see `context.md`.

## Project Health

| Attribute | Value |
|-----------|-------|
| **Project** | Lee Knowledge Base (`lee-kb`) |
| **Profile** | Python package / governed retrieval service |
| **Current Phase** | Phase 1 — Sprint 1 Personal Foundation delivered |
| **Overall Status** | 🟢 First governed retrieval path (local files → SQLite → lexical evidence) delivered and measured against the real deployed Employee Zero corpus (15 roots, 1,213 documents); the independent review of that measurement is repaired (S2-R-04 nested-root correctness, S2-R-03 single-discovery-pass performance, S1-R-16 baseline-as-contract) and re-verified, with sync wall-clock down 46.6% post-repair; office formats and the curated golden benchmark remain unimplemented, deferred |
| **Last Updated** | 2026-08-03 |

## Progress Against Product Goals

Reference: `product-definition.md` and `architecture.md`.

### First-release criteria

| Criterion | Status | Notes |
|-----------|--------|-------|
| Personal deployment shape is defined | ✅ Done | SQLite, single user, local-first |
| Connector contract is implemented | ✅ Done | `Connector` ABC (`src/lee_kb/connectors/base.py`) covers discovery, changes, fetch, permissions, relationships, refresh, health, and checkpointing; local-file connector implements it. Office-format file types are enumerated but not yet registered (deferred, see below) |
| Local documents synchronize into normalized knowledge | ✅ Done | `lee-kb sync`; verified by `tests/test_local_connector.py`, a manual end-to-end run, and a full clean sync of the real deployed corpus (15 roots, 1,213 items, 12,699 chunks; see `evidence/real-corpus-parity-report.md`) |
| SQLite repository persists items, chunks, metadata, and sync state | ✅ Done | `src/lee_kb/repository.py`, transactional, with a schema version and an append-only journal; verified by `tests/test_repository.py` |
| Lexical retrieval returns ranked evidence | ✅ Done | BM25-based retrieval in `src/lee_kb/retrieval.py`; verified by `tests/test_retrieval.py` |
| Results cite original sources | ✅ Done | Every `Evidence` carries a `Citation` with source locator; verified by `tests/test_retrieval.py` and `tests/test_cli.py` |
| Results report freshness | ✅ Done | `FreshnessReport` on every `EvidenceBundle`; CLI prints sync age per result |
| Retrieval receipts are recorded | ✅ Done | One `RetrievalReceipt` persisted per evidence item, including the empty-result case; verified by `tests/test_governance.py` |

Office-format parsing (`.docx`, `.xlsx`, `.pptx`) and the curated Chief-of-Staff
golden benchmark are explicitly out of this delivery — see
`sprint-plan.md` ("Sprint closure requirements") and `docs/golden-baseline.md`.
Format handlers for office documents remain entirely unregistered pending
dependency approval; the real-corpus measurement in
`evidence/real-corpus-parity-report.md` now sizes the gap at 39 files (32
`.docx`, 5 `.xlsx`, 2 `.pptx`) inside the 15 deployed root paths, none of
which the connector's own sync summary can see today because every root's
`include` patterns are markdown-only.

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
| Sprint 2 — Real-Corpus Parity & Post-Parity Repairs | Measure Sprint 1 against the real deployed Employee Zero corpus; repair what the measurement and its review surfaced | 🟡 In progress (real-corpus measurement and S2-R-04/S2-R-03/S1-R-16 repairs complete; office-format approval, the OR-matcher decision, and the curated golden benchmark remain open, pending Lee) |

## Product Risks and Blockers

| Risk or blocker | Impact | Status | Mitigation |
|----------------|--------|--------|------------|
| Permission semantics are not yet specified | Unauthorized evidence could leak | 🟢 Resolved for v1 | Fail-closed `SingleUserPermissionEvaluator` filters candidates before evidence assembly (`src/lee_kb/governance.py`); a multi-user model is a distinct future evaluator, not a `retrieve()` change |
| Connector APIs differ in change tracking and freshness | Sync correctness may vary by source | 🟡 Open | Local-file connector uses content-hash snapshot diffing; the email connector (next) will validate the contract against a source with a native change feed |
| Provider abstractions could become over-designed | Slows first useful release | 🟢 Resolved for v1 | SQLite repository and lexical retriever implemented behind the smallest useful `Repository`/retriever interfaces |
| Research patterns may imply enterprise scale too early | Scope drift | 🟢 Controlled | Sprint 1 stayed scoped to personal deployment, local documents, SQLite, and lexical search; office formats and semantic retrieval were deliberately deferred rather than pulled forward |
| OR-matcher fetch-to-exhaustion could degrade further as corpus size grows | Slow retrieval on common-word queries | 🟡 Open | Measured at ~1.521s worst case on the real ~1,213-document corpus (`evidence/real-corpus-parity-report.md`); carried forward unchanged in the post-repair re-measurement (the S2-R-03 repair improved sync performance, not retrieval latency); not yet measured at larger corpus size (e.g. after office-format ingestion); a page-size cap or early-exit heuristic is an open decision, not yet built |
| Nested/overlapping configured roots could double-count one file as two independently citable knowledge items | Duplicate, inconsistent evidence for one source document | 🟢 Resolved (S2-R-04) | `LocalFilesConnector` now claims each overlapping file with exactly one root — the deepest matching resolved root, ties broken by root name; `health()` reports detected nested-root pairs; regression tests added (`tests/test_local_connector.py`) |

## Key Decisions

| Decision | Rationale | Date |
|----------|-----------|------|
| Source systems remain authoritative | lee-kb is a searchable projection, not a migration target | 2026-08-03 |
| First release is personal and SQLite-backed | Enables fast validation without enterprise infrastructure | 2026-08-03 |
| Retrieval and execution governance are separate | Evidence access must not grant permission to act | 2026-08-03 |
| Lexical search is the first retrieval provider | Provides a deterministic baseline before semantic complexity | 2026-08-03 |
| Real-corpus measurement precedes further optimization | Employee Zero corpus sync/search findings (`evidence/real-corpus-parity-report.md`) now drive Next Actions Queue priority instead of assumption | 2026-08-03 |

## What “Done” Looks Like

- [x] A local document can be discovered, synchronized, normalized, and chunked.
- [x] The SQLite projection can be queried with lexical retrieval.
- [x] Unauthorized content is filtered before evidence assembly.
- [x] Every result includes original-source provenance and freshness metadata.
- [x] Every retrieval creates an auditable receipt.
- [x] The Sprint 1 workflow (local files → SQLite → lexical evidence) is covered by automated and user-path tests. Office-format ingestion is not yet implemented, so it is not yet part of this coverage.

*Update this file when a milestone is reached or product direction changes.*
