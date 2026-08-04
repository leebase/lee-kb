# WHERE_AM_I — Lee Knowledge Base

> **Product-level orientation.** This file tracks progress toward the governed
> knowledge-fabric vision. For session-level detail, see `context.md`.

## Project Health

| Attribute | Value |
|-----------|-------|
| **Project** | Lee Knowledge Base (`lee-kb`) |
| **Profile** | Python package / governed retrieval service |
| **Current Phase** | Phase 1 — Sprint 3 (governed `answer()` surface) delivered |
| **Overall Status** | 🟢 Two governed surfaces now exist: `retrieve()` (evidence rows, delivered Sprint 1, measured against the real deployed Employee Zero corpus of 15 roots / 1,213 documents) and `answer()` (cited claims, confidence, conflicts, and absences, delivered Sprint 3, `lee-kb ask`). Sprint 2's review-surfaced repairs (S2-R-04, S2-R-03, S1-R-16) are complete and re-verified. Deferred across both surfaces: office-format parsing, an LLM-backed synthesis provider for `answer()`, the curated Chief-of-Staff golden benchmark, and live filesystem verification of `ask` over time |
| **Last Updated** | 2026-08-04 |

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
| A governed answer surface returns cited claims, not raw evidence | ✅ Done | `answer()` (`src/lee_kb/answer.py`) and `lee-kb ask`; claim assembly, conflict identification without a winner, and absence classification that never collapses `NOT_FOUND`/`INACCESSIBLE`/`UNKNOWN`; verified against seven benchmark families in `tests/answers/test_answer_benchmarks.py` and reported in `docs/answer-benchmark-results.md` |
| Answer synthesis is attributable and auditable | ✅ Done (offline default) | `DeterministicSynthesisProvider` is the default `SynthesisProvider`, template-only and standard-library-only; `synthesis_provider_id` names whichever provider ran. An LLM-backed provider is specified but unimplemented, pending dependency approval — see below |

Office-format parsing (`.docx`, `.xlsx`, `.pptx`) and the curated Chief-of-Staff
golden benchmark are explicitly out of this delivery — see
`sprint-plan.md` ("Sprint closure requirements") and `docs/golden-baseline.md`.
Format handlers for office documents remain entirely unregistered pending
dependency approval; the real-corpus measurement in
`evidence/real-corpus-parity-report.md` now sizes the gap at 39 files (32
`.docx`, 5 `.xlsx`, 2 `.pptx`) inside the 15 deployed root paths, none of
which the connector's own sync summary can see today because every root's
`include` patterns are markdown-only.

The LLM-backed `SynthesisProvider` for `answer()`/`lee-kb ask` is likewise
explicitly out of this delivery: the protocol and pipeline seam exist
(`docs/answer-architecture.md`, Synthesis Providers), but no model-client
dependency is approved, so `ask` currently returns deterministic template
prose over assembled claims, not natural-language synthesis. Live filesystem
verification of `ask` over time (freshness drift, resync during use) is also
deferred — the permanent regression suite runs against a temporary,
synthetic SQLite projection, not a live corpus.

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
| Sprint 3 — Governed `answer()` Surface | Layer cited claims, confidence, conflicts, and absences on top of `retrieve()`; ship `lee-kb ask` | 🟢 Delivered (LLM-backed synthesis provider, real-corpus measurement of `answer()`, and live filesystem verification of `ask` remain deferred, pending Lee) |

## Product Risks and Blockers

| Risk or blocker | Impact | Status | Mitigation |
|----------------|--------|--------|------------|
| Permission semantics are not yet specified | Unauthorized evidence could leak | 🟢 Resolved for v1 | Fail-closed `SingleUserPermissionEvaluator` filters candidates before evidence assembly (`src/lee_kb/governance.py`); a multi-user model is a distinct future evaluator, not a `retrieve()` change |
| Connector APIs differ in change tracking and freshness | Sync correctness may vary by source | 🟡 Open | Local-file connector uses content-hash snapshot diffing; the email connector (next) will validate the contract against a source with a native change feed |
| Provider abstractions could become over-designed | Slows first useful release | 🟢 Resolved for v1 | SQLite repository and lexical retriever implemented behind the smallest useful `Repository`/retriever interfaces |
| Research patterns may imply enterprise scale too early | Scope drift | 🟢 Controlled | Sprint 1 stayed scoped to personal deployment, local documents, SQLite, and lexical search; office formats and semantic retrieval were deliberately deferred rather than pulled forward |
| OR-matcher fetch-to-exhaustion could degrade further as corpus size grows | Slow retrieval on common-word queries | 🟡 Open | Measured at ~1.521s worst case on the real ~1,213-document corpus (`evidence/real-corpus-parity-report.md`); carried forward unchanged in the post-repair re-measurement (the S2-R-03 repair improved sync performance, not retrieval latency); not yet measured at larger corpus size (e.g. after office-format ingestion); a page-size cap or early-exit heuristic is an open decision, not yet built |
| Nested/overlapping configured roots could double-count one file as two independently citable knowledge items | Duplicate, inconsistent evidence for one source document | 🟢 Resolved (S2-R-04) | `LocalFilesConnector` now claims each overlapping file with exactly one root — the deepest matching resolved root, ties broken by root name; `health()` reports detected nested-root pairs; regression tests added (`tests/test_local_connector.py`) |
| No approved LLM dependency for `answer()`'s synthesis provider | `lee-kb ask` returns template prose over claims, not natural-language answers | 🟡 Open | `SynthesisProvider` is a one-method protocol; `DeterministicSynthesisProvider` proves the pipeline offline; an LLM-backed implementation is a new class behind the same seam once a model client is approved (`docs/answer-architecture.md`, Synthesis Providers) |
| `answer()` is unmeasured against the real Employee Zero corpus | Latency, claim-assembly, and conflict/absence rates at real scale are unknown | 🟡 Open | `docs/answer-benchmark-results.md` benchmarks `answer()` only against a synthetic eight-document fixture corpus; a real-corpus measurement is Next Actions Queue rank 5 (paired with the curated golden benchmark) |

## Key Decisions

| Decision | Rationale | Date |
|----------|-----------|------|
| Source systems remain authoritative | lee-kb is a searchable projection, not a migration target | 2026-08-03 |
| First release is personal and SQLite-backed | Enables fast validation without enterprise infrastructure | 2026-08-03 |
| Retrieval and execution governance are separate | Evidence access must not grant permission to act | 2026-08-03 |
| Lexical search is the first retrieval provider | Provides a deterministic baseline before semantic complexity | 2026-08-03 |
| Real-corpus measurement precedes further optimization | Employee Zero corpus sync/search findings (`evidence/real-corpus-parity-report.md`) now drive Next Actions Queue priority instead of assumption | 2026-08-03 |
| `answer()` adds no permission logic and calls `retrieve()` unmodified | Every governance guarantee (fail-closed authorization, freshness, receipts) is inherited, never reimplemented, at the higher-level surface | 2026-08-04 |
| Confidence is an epistemic basis (four fixed labels), never a probability score | A numeric score would invite a threshold, quietly converting "reasoned past its sources" into "confident enough to act on" | 2026-08-04 |
| `Conflict` has no `winner` field | Picking a side would move a governance judgement out of the reader's hands into a heuristic that cannot see intent | 2026-08-04 |
| `answer()` ships with a deterministic, offline default synthesis provider; the LLM-backed one is deferred | Keeps the release LLM-free until a model-client dependency is explicitly approved, consistent with the office-format guardrail | 2026-08-04 |

## What “Done” Looks Like

- [x] A local document can be discovered, synchronized, normalized, and chunked.
- [x] The SQLite projection can be queried with lexical retrieval.
- [x] Unauthorized content is filtered before evidence assembly.
- [x] Every result includes original-source provenance and freshness metadata.
- [x] Every retrieval creates an auditable receipt.
- [x] The Sprint 1 workflow (local files → SQLite → lexical evidence) is covered by automated and user-path tests. Office-format ingestion is not yet implemented, so it is not yet part of this coverage.
- [x] A question can be answered as cited claims with confidence, conflicts, and absences (`answer()` / `lee-kb ask`), covered by seven permanent benchmark families (`tests/answers/`) against a real connector/repository sync. An LLM-backed synthesis provider, a real-corpus measurement of `answer()`, and live filesystem verification of `ask` over time are not yet implemented, so they are not yet part of this coverage.

*Update this file when a milestone is reached or product direction changes.*
