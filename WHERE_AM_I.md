# WHERE_AM_I — Lee Knowledge Base

> **Product-level orientation.** This file tracks progress toward the governed
> knowledge-fabric vision. For session-level detail, see `context.md`.

## Project Health

| Attribute | Value |
|-----------|-------|
| **Project** | Lee Knowledge Base (`lee-kb`) |
| **Profile** | Python package / governed retrieval service |
| **Current Phase** | Personal-first Second Brain foundation complete; Microsoft Graph foundation and live-capable Outlook path delivered; real mailbox proof remains operator-gated |
| **Overall Status** | 🟡 Two governed surfaces now exist: `retrieve()` and `answer()`/`lee-kb ask`. Office DOCX/XLSX/PPTX handlers use the common connector, repository, retrieval, permission, citation, and receipt path; the 39-file live inventory is explicitly accounted for and the final real projection contains 1,235 documents / 18,601 chunks. The Microsoft Graph foundation now owns delegated auth, verified account binding, secure token lifecycle, HTTP, retry/throttling/rate limiting, pagination, delta recovery, and normalized errors; `GraphOutlookTransport` wires one credential-bound folder into the common SQLite/checkpoint path. No real account was connected by automated tests. Deferred: operator-run mailbox proof, relationship persistence, attachment-body ingestion, an LLM-backed synthesis provider, the curated Chief-of-Staff golden benchmark, live filesystem verification of `ask` over time, and the OR-matcher decision |
| **Last Updated** | 2026-08-05 |

## Progress Against Product Goals

Reference: `product-definition.md` and `architecture.md`.

### First-release criteria

| Criterion | Status | Notes |
|-----------|--------|-------|
| Personal deployment shape is defined | ✅ Done | SQLite, single user, local-first |
| Connector contract is implemented | ✅ Done | `Connector` ABC (`src/lee_kb/connectors/base.py`) covers discovery, changes, fetch, permissions, relationships, refresh, health, and checkpointing; local-file and offline Outlook connectors implement it, including the registered deterministic Office parsers; BI-001 and BI-003 coverage is in `tests/test_connector_conformance.py` and `tests/test_outlook_connector.py` |
| Local documents synchronize into normalized knowledge | ✅ Done | `lee-kb sync`; verified by connector/Office integration tests and a full clean sync of the real deployed corpus (15 roots, 1,235 items, 18,601 chunks; see `evidence/real-corpus-parity-report.md`) |
| SQLite repository persists items, chunks, metadata, and sync state | ✅ Done | `src/lee_kb/repository.py`, transactional, with a schema version and an append-only journal; verified by `tests/test_repository.py` |
| Lexical retrieval returns ranked evidence | ✅ Done | BM25-based retrieval in `src/lee_kb/retrieval.py`; verified by `tests/test_retrieval.py` |
| Results cite original sources | ✅ Done | Every `Evidence` carries a `Citation` with source locator; verified by `tests/test_retrieval.py` and `tests/test_cli.py` |
| Results report freshness | ✅ Done | `FreshnessReport` on every `EvidenceBundle`; CLI prints sync age per result |
| Retrieval receipts are recorded | ✅ Done | One `RetrievalReceipt` persisted per evidence item, including the empty-result case; verified by `tests/test_governance.py` |
| A governed answer surface returns cited claims, not raw evidence | ✅ Done | `answer()` (`src/lee_kb/answer.py`) and `lee-kb ask`; claim assembly, conflict identification without a winner, and absence classification that never collapses `NOT_FOUND`/`INACCESSIBLE`/`UNKNOWN`; verified against seven benchmark families in `tests/answers/test_answer_benchmarks.py` and reported in `docs/answer-benchmark-results.md` |
| Answer synthesis is attributable and auditable | ✅ Done (offline default) | `DeterministicSynthesisProvider` is the default `SynthesisProvider`, template-only and standard-library-only; `synthesis_provider_id` names whichever provider ran. An LLM-backed provider is specified but unimplemented, pending explicit dependency approval — see below |

Office-format parsing is now implemented and documented in
`docs/office-ingestion.md`. The real-corpus rollout accounts for all 39 live
files (32 `.docx`, 5 `.xlsx`, 2 `.pptx`) across six affected roots: 10 are
indexed, 5 fail closed as unsupported embedded content, 1 is Git-ignored, 2
are generated/excluded, and 21 remain outside the deliberate
`ai-employee-book` include scope. The curated Chief-of-Staff golden benchmark
and OpenAI-backed synthesis remain deferred.

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
| Build the first end-to-end retrieval path | ✅ Done | Sprint 1 — Personal Foundation delivered; Office formats now run through the same governed path; the curated golden benchmark remains deferred |

## Sprint Position

| Sprint | Focus | Status |
|--------|-------|--------|
| Sprint 1 — Personal Foundation | Local documents → SQLite → lexical evidence | 🟢 Delivered |
| Sprint 2 — Real-Corpus Parity & Post-Parity Repairs | Measure Sprint 1 against the real deployed Employee Zero corpus; repair what the measurement and its review surfaced | 🟡 In progress (real-corpus measurement, Office ingestion, final-review connector/Office repairs, and query-level audit events complete; the OR-matcher decision and curated golden benchmark remain open) |
| Sprint 3 — Governed `answer()` Surface | Layer cited claims, confidence, conflicts, and absences on top of `retrieve()`; ship `lee-kb ask` | 🟢 Delivered (37-item two-direction conflict regression set, S3-R-04/S3-R-05, and round-four repairs complete; LLM-backed synthesis and live filesystem verification of `ask` remain deferred) |
| Sprint 4 — Personal Connector Foundation | Prove the connector boundary and map the first external connector family | 🟢 Bounded offline BI-003 slice delivered and conditionally passed independent review |
| Sprint 5 — Microsoft Graph Foundation and Live Outlook Proof | Build shared Graph plumbing and prove one real mailbox end to end through the governed connector path | 🟡 Foundation delivered offline; live account/consent proof remains gated |

## Product Risks and Blockers

| Risk or blocker | Impact | Status | Mitigation |
|----------------|--------|--------|------------|
| Permission semantics are not yet specified | Unauthorized evidence could leak | 🟢 Resolved for v1 | Fail-closed `SingleUserPermissionEvaluator` filters candidates before evidence assembly (`src/lee_kb/governance.py`); a multi-user model is a distinct future evaluator, not a `retrieve()` change |
| Connector APIs differ in change tracking and freshness | Sync correctness may vary by source | 🟡 Controlled for Outlook offline slice | Local-file connector uses content-hash snapshots; the offline Outlook adapter validates a native delta-shaped transport with immutable IDs, modified timestamps, and opaque cursors |
| External connector capabilities and API semantics are not fully resolved | Live OneDrive, Outlook, Gmail, and OneNote integrations could require incompatible identity, cursor, or permission assumptions | 🟡 Controlled for Outlook; open for OneDrive/OneNote | `docs/microsoft-graph.md` and `docs/connector-capability-matrix.md` separate shared Graph plumbing, Outlook mapping, provider evidence, and future connector questions |
| Provider abstractions could become over-designed | Slows first useful release | 🟢 Resolved for v1 | SQLite repository and lexical retriever implemented behind the smallest useful `Repository`/retriever interfaces |
| Research patterns may imply enterprise scale too early | Scope drift | 🟢 Controlled | Sprint 1 stayed scoped to personal deployment, local documents, SQLite, and lexical search; Office support stayed deterministic and did not pull in semantic or enterprise infrastructure |
| OR-matcher fetch-to-exhaustion could degrade further as corpus size grows | Slow retrieval on common-word queries | 🟡 Open | The prior ~1.521s worst case is carried forward; the Office rollout measured sync at 1,235 documents / 18,601 chunks but did not re-run the retrieval stress set; a page-size cap or early-exit heuristic is an open decision |
| Nested/overlapping configured roots could double-count one file as two independently citable knowledge items | Duplicate, inconsistent evidence for one source document | 🟢 Resolved (S2-R-04) | `LocalFilesConnector` now claims each overlapping file with exactly one root — the deepest matching resolved root, ties broken by root name; `health()` reports detected nested-root pairs; regression tests added (`tests/test_local_connector.py`) |
| No approved LLM dependency for `answer()`'s synthesis provider | `lee-kb ask` returns template prose over claims, not natural-language answers | 🟡 Open | `SynthesisProvider` is a one-method protocol; `DeterministicSynthesisProvider` proves the pipeline offline; an LLM-backed implementation is a new class behind the same seam once a model client is approved (`docs/answer-architecture.md`, Synthesis Providers) |
| `answer()` is not benchmarked comprehensively against the real Employee Zero corpus | Latency, claim-assembly, and conflict/absence rates at real scale are unknown | 🟡 Open | Real-corpus `ask` smoke queries now resolve Office citations; the controlled benchmark remains synthetic and should be paired with the curated golden benchmark |
| Office parser package features may contain unsupported content | Partial extraction could mislead retrieval or leak embedded data | 🟢 Controlled | Parsers reject encrypted, malformed, macro, media, external-link, and embedded-object packages; the real 39-file inventory and failure counts are recorded in `docs/office-ingestion.md` |
| Query-level retrieval audit events need a post-change review | Schema v2 must preserve empty, denied, mixed, stale-refused, and provider-failure audit facts | 🟢 Resolved for current slice | `RetrievalAuditEvent` and additive v1 migration are implemented; post-audit review found no High/Critical findings and missing provider capability fails closed |

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
| Conflict detection requires positive disagreement evidence; authority is descriptive, not causal | Prevents the round-to-round see-saw between false conflicts and missed contradictions; fixed synthetic rates cover both directions | 2026-08-04 |
| Office parsers use normalized structured text and common citations | Keeps Office documents in the same governed path and makes sheet/slide/paragraph references stable without a parallel ingestion system | 2026-08-04 |
| Personal-first Second Brain, small-group capable, not enterprise-first | Keeps the useful personal deployment small while preserving explicit principal, project, connector, provenance, and access boundaries for later shared work | 2026-08-05 |
| BI-001 recommends Outlook/Microsoft 365 mail first | Graph documents per-folder message delta, deleted markers, immutable IDs, timestamps, fetch formats, and read permissions; the recommendation led to the shared Graph foundation and remains subject to a real account proof | 2026-08-05 |
| BI-003 Outlook slice uses one delegated folder and shared Graph transport | Proves email identity, normalization, relationships, permissions, freshness, delta, token-safe failure, and checkpoint semantics without hard-coding Graph plumbing into the connector | 2026-08-05 |
| Microsoft Graph foundation is resource-neutral | Account/token lifecycle, HTTP, retry/throttling, pacing, pagination, delta expiry, and error normalization are shared; OneDrive can reuse them and OneNote is not used to shape them | 2026-08-05 |
| Sprint 5 uses `Repository.advance_cursor()` for atomic cursor-only advancement | Empty delta rounds need restart-safe cursor persistence without fabricating knowledge items; SQLite implements the capability transactionally, records synchronized-project state atomically, and unsupported providers fail closed | 2026-08-05 |

## What “Done” Looks Like

- [x] A local document can be discovered, synchronized, normalized, and chunked.
- [x] The SQLite projection can be queried with lexical retrieval.
- [x] Unauthorized content is filtered before evidence assembly.
- [x] Every result includes original-source provenance and freshness metadata.
- [x] Every retrieval creates an auditable receipt.
- [x] The local-files workflow (Markdown and Office files → SQLite → lexical evidence) is covered by automated, user-path, safety, and real-corpus sync tests.
- [x] A question can be answered as cited claims with confidence, conflicts, and absences (`answer()` / `lee-kb ask`), covered by seven permanent benchmark families (`tests/answers/`) against a real connector/repository sync. An LLM-backed synthesis provider, a real-corpus measurement of `answer()`, and live filesystem verification of `ask` over time are not yet implemented, so they are not yet part of this coverage.
- [x] The existing connector boundary is exercised by focused local and Outlook suites; the shared Graph client and transport are tested without external credentials, and the capability matrix records implemented behavior separately from live provider evidence.
- [ ] One approved real Outlook mailbox can authenticate, initial-sync, incremental-sync, recover from an expired delta token, and answer a known email question with governed provenance. The live-capable path exists; account, consent, and sanitized operator evidence are still required.

*Update this file when a milestone is reached or product direction changes.*
