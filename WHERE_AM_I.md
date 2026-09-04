# WHERE_AM_I — Lee Knowledge Base

> **Product-level orientation.** This file tracks progress toward the governed
> knowledge-fabric vision. For session-level detail, see `context.md`.

## 2026-08-13 — Governed shared knowledge plane for the AI workforce

lee-kb now serves multiple AI-employee principals through multiple
authenticated clients over one identity-free transport. The boundary was
commissioned live: `employee:chief-of-staff` holds explicit
project/operations grants (factory, agent-orch, auto-orch, agent-board,
leeos — all fresh), two revocable client credentials exist
(`chief-of-staff:codex` proven end to end through a real Codex turn;
`chief-of-staff:jarvis` provisioned, container wiring deliberately
deferred), and adversarial proofs cover forged principals, credential
misuse, revocation, cross-employee isolation, and non-enumerating denials.
Mail/Calendar remain granted only to `employee:employee-zero`.

The S1C owner slice for LeeOS is delivered: owner-gateway MCP mode with a
versioned identity mapping, exact-reference history behind a manifest +
bounded git resolver, bound receipts, and the content-free owner acceptance
artifact `evidence/s1c/S1C-lee-kb.json` (computed **accepted**,
deterministic). Provisioning another employee or client is configuration
only: `docs/access-operations.md`.

## 2026-08-09 — Synthesis live-wiring gate review

Sprint 6's source-bounded provider core remains delivered. The highest-ranked
next action cannot enter live implementation because no exact client/version,
model or cost ceiling, route/API project, credential boundary, telemetry policy,
retry policy, or named CLI/library opt-in surface is approved. The approval
worksheet is now explicit in `docs/openai-synthesis-decision.md`; the default
`lee-kb ask` path remains deterministic and offline.

## 2026-08-09 — Employee Zero knowledge adopter commissioned

The first Chief of Staff adopter completed supervised cycle
`20260809T200630Z` and governed run `04e42891c922` with canonical identity,
read-only employee-scoped knowledge access, a passing pinned KB deployment
smoke, independently verified user journeys, and a verified evidence chain.
The mission remains paused; this is commissioning evidence, not autonomous
schedule authorization.

## Project Health

| Attribute | Value |
|-----------|-------|
| **Project** | Lee Knowledge Base (`lee-kb`) |
| **Profile** | Python package / governed retrieval service |
| **Current Phase** | Governed multi-principal knowledge plane delivered and live-commissioned (Chief of Staff + two authenticated clients); S1C owner slice delivered with an accepted owner artifact; all earlier phases (foundation, real-corpus parity, `answer()`, Graph live reads, KB-R1/R2/R3, synthesis core) remain as recorded |
| **Overall Status** | 🟢 lee-kb is the governed shared knowledge plane for Lee's AI workforce: authenticated clients act for server-owned employee principals through the identity-free MCP transport; grants and source ACLs are both Lee-owned and revocable; audit evidence attributes principal and client without protected content. Live synthesis wiring and continuous filesystem `ask` verification remain approval-gated follow-ons |
| **Last Updated** | 2026-08-13 |

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
| Answer synthesis is attributable and auditable | ✅ Done (deterministic default + opt-in bounded core) | `DeterministicSynthesisProvider` remains the default; `OpenAIResponsesSynthesisProvider` accepts only finalized claims through an injected Responses client, preserves ordered citation markers, and fails closed to `UNKNOWN` without fallback. `Answer.freshness` retains the completed retrieval report alongside claims, citations, confidence, and receipt IDs; live client/model/route approval remains open |
| Incumbent MCP surface is available on the successor | ✅ KB-R3 done | `src/lee_kb/mcp.py` preserves `kb_search`, `kb_status`, and `kb_compile_preview` over stdio JSON-RPC with additive governed receipt data; `ai-employee-factory/.mcp.json` registers `lee-kb` / `lee-kb-mcp` |

Office-format parsing is now implemented and documented in
`docs/office-ingestion.md`. The real-corpus rollout accounts for all 39 live
files (32 `.docx`, 5 `.xlsx`, 2 `.pptx`) across six affected roots: 10 are
indexed, 5 fail closed as unsupported embedded content, 1 is Git-ignored, 2
are generated/excluded, and 21 remain outside the deliberate
`ai-employee-book` include scope.

The curated Chief-of-Staff benchmark is now implemented as a local-only
operator runner over a copied SQLite projection. It exercises 20 canonical
questions through both `retrieve()` and deterministic `answer()` and emits
aggregate, disclosure-safe metrics; no question text or source locator is
published.

The source-bounded `SynthesisProvider` core is implemented in
`src/lee_kb/synthesis.py`. It uses an injected OpenAI-compatible Responses
client, includes only finalized claim text and ordered markers, rejects output
that cannot be bounded to those markers, and leaves the default CLI path
deterministic and offline. `answer()` preserves the retrieval freshness report,
citations, confidence, receipt IDs, and explicit `UNKNOWN` failure semantics.
The exact live client/model/route/secret policy and continuous filesystem
verification of `ask` remain deferred.

### Current phase goals

| Goal | Status | Notes |
|------|--------|-------|
| Establish product direction | ✅ Done | Product definition is the scope authority |
| Establish system boundaries | ✅ Done | Architecture separates connectors, ingestion, repository, retrieval, and authorization |
| Capture useful research patterns | ✅ Done | See `research/cerebras.kb` |
| Align AgentFlow project memory | ✅ Done | Root docs, roles, and skills are consistent |
| Build the first end-to-end retrieval path | ✅ Done | Sprint 1 — Personal Foundation delivered; Office formats and the curated local-only benchmark now run through the same governed path |

## Sprint Position

| Sprint | Focus | Status |
|--------|-------|--------|
| Sprint 1 — Personal Foundation | Local documents → SQLite → lexical evidence | 🟢 Delivered |
| Sprint 2 — Real-Corpus Parity & Post-Parity Repairs | Measure Sprint 1 against the real deployed Employee Zero corpus; repair what the measurement and its review surfaced | 🟢 Delivered — parity, Office ingestion, review repairs, the OR decision, and the curated benchmark are complete |
| Sprint 3 — Governed `answer()` Surface | Layer cited claims, confidence, conflicts, and absences on top of `retrieve()`; ship `lee-kb ask` | 🟢 Delivered (37-item two-direction conflict regression set, S3-R-04/S3-R-05, and round-four repairs complete; LLM-backed synthesis and live filesystem verification of `ask` remain deferred) |
| Sprint 4 — Personal Connector Foundation | Prove the connector boundary and map the first external connector family | 🟢 Bounded offline BI-003 slice delivered and conditionally passed independent review |
| Sprint 5 — Microsoft Graph Foundation and Live Outlook Proof | Build shared Graph plumbing and prove one real mailbox end to end through the governed connector path | 🟡 Foundation delivered offline; live account/consent proof remains gated |
| Sprint KB-R1 — MCP parity surface | Preserve the incumbent MCP contract over lee-kb's governed retrieval | 🟢 Delivered |
| Sprint KB-R2 — MCP benchmark vs incumbent | Benchmark kb-index vs lee-kb MCP servers on the real corpus; decide on KB-R3 | 🟢 Go — see `evidence/kb-r2-mcp-benchmark-report.md`: found and fixed a 27× `kb_status`/`kb_search` regression (unpruned `os.walk` directory descent) same-day; fixed lee-kb now beats kb-index on every measured call (4.0–4.2s vs 5.5–5.5s) |
| Sprint KB-R3 — MCP registration/cutover | Register `lee-kb` as the live MCP server in `ai-employee-factory/.mcp.json`, replacing `kb-index` | 🟢 Delivered — `../ai-employee-factory/decisions.md` 2026-08-08; live-command smoke test passed (init, tools/list, search, status, compile_preview, empty query, missing-param error); `kb-index` untouched, `.mcp.json.kb-index-backup` + git history give instant rollback |

## Product Risks and Blockers

KB-R2 benchmarked the MCP envelope against the incumbent
(`evidence/kb-r2-mcp-benchmark-report.md`) and found a real 27×
`kb_status`/`kb_search` regression at real-corpus scale. The cause was
unpruned `os.walk` descent into denied directories; `.agent-orch-scratch/`
alone contributed 1.16M unnecessarily walked files. The pruning fix was
re-measured live at 3.9–4.2s per call, faster than `kb-index`.

**Result: Go.** KB-R3 then registered `lee-kb` / `lee-kb-mcp` in the Factory,
and the combined deployment smoke passed. The successor-specific server name,
configured principal/project, content-hash version stamp, and additive receipt
fields are documented in `docs/kb-r1-mcp-parity.md`.

| Risk or blocker | Impact | Status | Mitigation |
|----------------|--------|--------|------------|
| Permission semantics are not yet specified | Unauthorized evidence could leak | 🟢 Resolved for v1 | Fail-closed `SingleUserPermissionEvaluator` filters candidates before evidence assembly (`src/lee_kb/governance.py`); a multi-user model is a distinct future evaluator, not a `retrieve()` change |
| Connector APIs differ in change tracking and freshness | Sync correctness may vary by source | 🟡 Controlled for Outlook offline slice | Local-file connector uses content-hash snapshots; the offline Outlook adapter validates a native delta-shaped transport with immutable IDs, modified timestamps, and opaque cursors |
| External connector capabilities and API semantics are not fully resolved | Live OneDrive, Outlook, Gmail, and OneNote integrations could require incompatible identity, cursor, or permission assumptions | 🟡 Controlled for Outlook; open for OneDrive/OneNote | `docs/microsoft-graph.md` and `docs/connector-capability-matrix.md` separate shared Graph plumbing, Outlook mapping, provider evidence, and future connector questions |
| Provider abstractions could become over-designed | Slows first useful release | 🟢 Resolved for v1 | SQLite repository and lexical retriever implemented behind the smallest useful `Repository`/retriever interfaces |
| Research patterns may imply enterprise scale too early | Scope drift | 🟢 Controlled | Sprint 1 stayed scoped to personal deployment, local documents, SQLite, and lexical search; Office support stayed deterministic and did not pull in semantic or enterprise infrastructure |
| OR-matcher fetch-to-exhaustion could degrade further as corpus size grows | Slow retrieval on common-word queries | 🟡 Controlled for current scale; open at larger scale | Three fresh runs on 1,314 items / 20,438 chunks measured 1.7220s, 1.7617s, and 1.7257s; the personal release accepts the behavior and will revisit with growth |
| Nested/overlapping configured roots could double-count one file as two independently citable knowledge items | Duplicate, inconsistent evidence for one source document | 🟢 Resolved (S2-R-04) | `LocalFilesConnector` now claims each overlapping file with exactly one root — the deepest matching resolved root, ties broken by root name; `health()` reports detected nested-root pairs; regression tests added (`tests/test_local_connector.py`) |
| No approved LLM dependency for `answer()`'s synthesis provider | `lee-kb ask` returns template prose over claims, not natural-language answers | 🟡 Open | `SynthesisProvider` is a one-method protocol; `DeterministicSynthesisProvider` proves the pipeline offline; an LLM-backed implementation is a new class behind the same seam once a model client is approved (`docs/answer-architecture.md`, Synthesis Providers) |
| `answer()` is not benchmarked comprehensively against the real Employee Zero corpus | Latency, claim-assembly, and conflict/absence rates at real scale are unknown | 🟡 Partially resolved | The local-only operator benchmark now measures 20 canonical questions against a copied projection and records aggregate results; live continuously synchronized `ask` verification remains open |
| Office parser package features may contain unsupported content | Partial extraction could mislead retrieval or leak embedded data | 🟢 Controlled | Parsers reject encrypted, malformed, macro, media, external-link, and embedded-object packages; the real 39-file inventory and failure counts are recorded in `docs/office-ingestion.md` |
| Query-level retrieval audit events need a post-change review | Schema v2 must preserve empty, denied, mixed, stale-refused, and provider-failure audit facts | 🟢 Resolved for current slice | `RetrievalAuditEvent` and additive v1 migration are implemented; post-audit review found no High/Critical findings and missing provider capability fails closed |
| `kb_status`/`kb_search` recomputed full corpus freshness on every call via an unpruned `os.walk` (visited every file under `.agent-orch-scratch/`, `artifacts/`, `.git/`, etc. before rejecting them) | Was 148s per call vs kb-index's 5.5s (27×); broke the "seconds" session-start contract Employee Zero's `CLAUDE.md` documents | 🟢 Resolved (same day) | `_dir_denied()` (ported from `kb.cli`) now prunes denied directories before `os.walk` descends; `_claiming_root()` also switched from pathlib containment checks to cached string prefixes. Re-measured live at 3.9–4.2s per call — faster than kb-index. `evidence/kb-r2-mcp-benchmark-report.md` |
| `kb.cli`'s `validate_faq_pointers` build-time gate (every FAQ `Source:` pointer must resolve) has no lee-kb equivalent | A cutover would silently drop FAQ-integrity enforcement | 🟢 Resolved | `ai-employee-factory/scripts/faq_lint.py` reimplements the same check as a standalone, engine-independent tool (zero dependency on either KB package); verified against the live 29-entry FAQ and a synthetic dangling-pointer fixture |

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
| KB-R1 MCP is a thin stdlib adapter over governed `retrieve()` | Preserve the incumbent three-tool wire contract while retaining lee-kb permission filtering, provenance, freshness, receipts, and query audit; do not couple registration or cutover to the library | 2026-08-06 |
| KB-R2 benchmark found and fixed a 27× status/search latency regression at real-corpus scale; result is Go | Root cause was an unpruned `os.walk` directory descent (`.agent-orch-scratch/` alone contributed 1.16M unnecessarily-walked files); fixed and re-measured same day, now faster than the incumbent on every call | 2026-08-08 |
| KB-R3: `lee-kb` registered as the live `ai-employee-factory` MCP server, replacing `kb-index` | Go decision from KB-R2 plus a passing live-command smoke test (all three tools, empty query, missing-param error); `kb-index` kept installed and untouched for instant rollback | 2026-08-08 |
| Current-scale OR-matcher exhaustive retrieval is accepted for the personal release | Three fresh runs measured the single-common-word case at 1.7220s, 1.7617s, and 1.7257s (1.7365s mean); revisit at larger corpus scale rather than hide permitted results behind an arbitrary cap | 2026-08-09 |
| The curated real-corpus answer benchmark is local-only and disclosure-safe | Run canonical questions against a copied projection and publish aggregate metrics only; never serialize live question text, source locators, or evidence | 2026-08-09 |
| Live synthesis wiring remains opt-in and approval-gated | Prevents an unreviewed model client, network route, secret path, telemetry sink, or retry policy from entering the deterministic release; all governed answer metadata and failure semantics stay unchanged | 2026-08-09 |

## What “Done” Looks Like

- [x] A local document can be discovered, synchronized, normalized, and chunked.
- [x] The SQLite projection can be queried with lexical retrieval.
- [x] Unauthorized content is filtered before evidence assembly.
- [x] Every result includes original-source provenance and freshness metadata.
- [x] Every retrieval creates an auditable receipt.
- [x] The local-files workflow (Markdown and Office files → SQLite → lexical evidence) is covered by automated, user-path, safety, and real-corpus sync tests.
- [x] A question can be answered as cited claims with confidence, conflicts, and absences (`answer()` / `lee-kb ask`), covered by seven permanent benchmark families (`tests/answers/`) and a local-only 20-question real-corpus operator benchmark. The LLM-backed synthesis provider and live filesystem verification of `ask` over time remain explicit follow-ons.
- [x] The existing connector boundary is exercised by focused local and Outlook suites; the shared Graph client and transport are tested without external credentials, and the capability matrix records implemented behavior separately from live provider evidence.
- [ ] One approved real Outlook mailbox can authenticate, initial-sync, incremental-sync, recover from an expired delta token, and answer a known email question with governed provenance. The live-capable path exists; account, consent, and sanitized operator evidence are still required.

- [x] The successor speaks the incumbent MCP tool contract over stdio and attaches governed receipt data without changing incumbent result fields. KB-R2 benchmark: Go (post-fix). KB-R3 registration/cutover: delivered — `lee-kb` is the live MCP server in `ai-employee-factory/.mcp.json` as of 2026-08-08.

*Update this file when a milestone is reached or product direction changes.*
