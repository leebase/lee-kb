# Lee Knowledge Base Session Context

> **Purpose:** Working memory for session continuity. Read this after
> `AGENTS.md` and before acting.

## Snapshot

| Attribute | Value |
|-----------|-------|
| **Phase** | Phase 1 — Sprint 1 Personal Foundation delivered |
| **Mode** | 2 (Collaborative implementation with approval) |
| **Last Updated** | 2026-08-03 |

### Sprint Status

| Sprint | Status | Completion |
|--------|--------|------------|
| Sprint 1 — Personal Foundation | 🟢 Delivered | 7/7 sprint tasks complete for the scoped slice; office formats and the curated golden benchmark explicitly deferred |

## What's Happening Now

### Current Work Stream

Sprint 1 delivered one governed retrieval path: local documents on disk
synchronize into a normalized SQLite projection and are searchable through
lexical retrieval, with permission filtering, citations, freshness, and
retrieval receipts on every result. Full verification (`pytest`, `black
--check`, `ruff check`) is green. Following delivery, lee-kb was synchronized
and queried against the real deployed
`ai-employee-factory/knowledge/sources.toml` corpus (15 roots, ~1,200
documents) for the first time (see
`evidence/real-corpus-parity-report.md`), resolving Open Question 4. That
measurement sized the office-format gap precisely (39 files: 32 `.docx`, 5
`.xlsx`, 2 `.pptx`, invisible to the connector's own sync summary because
every root's deployed `include` patterns are markdown-only) and produced a
first real-corpus performance and retrieval-quality baseline. The Next
Actions Queue below is re-ranked in light of those findings; the highest
priority is now approving office-format parsing dependencies together with
extending the affected roots' `include` patterns, since the real corpus
proved both are required and neither alone closes the gap.

### Recently Completed

- ✅ Product definition and architecture are established.
- ✅ Cerebras knowledge-base research is available under `research/`.
- ✅ AgentFlow project memory was aligned with the product and architecture.
- ✅ Role instructions were added under `agents/` and domain workflows under `skills/`.
- ✅ Bootstrap CLI metadata and behavior now describe the governed retrieval product.
- ✅ Bootstrap smoke tests pass and generated local metadata is ignored.
- ✅ Public GitHub repository created at `https://github.com/leebase/lee-kb` with `main` as the default branch.
- ✅ S1-01: Normalized domain contracts defined in `src/lee_kb/contracts.py` and `docs/sprint-1-contracts.md`.
- ✅ S1-02: Local-file connector (`src/lee_kb/connectors/local_files.py`) reads `sources.toml`-compatible config; discovery, change detection, fetch, permissions, and checkpointing implemented and tested.
- ✅ S1-03: SQLite repository (`src/lee_kb/repository.py`) persists items, chunks, permissions, sync state, and an append-only journal transactionally, with a stored schema version.
- ✅ S1-04: Deterministic chunking (`src/lee_kb/chunking.py`) and BM25 lexical retrieval (`src/lee_kb/retrieval.py`).
- ✅ S1-05: Governed `retrieve()` (`src/lee_kb/governance.py`): fail-closed authorization, freshness reporting, and one persisted receipt per evidence item.
- ✅ S1-06: Golden evaluation harness (`tests/golden/`, `docs/golden-baseline.md`) runs a 20-question generated corpus plus 3 negative controls and records a lexical baseline over paraphrase questions (60.0% hit-at-1, 100% hit-at-10, 0.766 MRR; re-recorded after S1-R-11). Proves the harness, not the curated Chief-of-Staff benchmark.
- ✅ Independent review PASSED (verdict gate clean): three High findings (S1-R-01 ungoverned retrieve, S1-R-10 connector containment/resilience, S1-R-11 AND-matcher baseline inflation) were found, repaired, and re-verified across three review cycles; 11 advisory findings (5 Medium, 6 Low) remain in `code-reviews/review-sprint-1-personal-foundation.md` as follow-on candidates.
- ✅ S1-07: `lee-kb init`/`sync`/`search` CLI (`src/lee_kb/main.py`) implemented and exercised end to end; full test suite (109 tests, including the golden corpus) passes; `black --check` and `ruff check` pass on `src` and `tests`.
- ✅ Real-corpus parity measurement: `lee-kb sync`/`search` run against the actual deployed `ai-employee-factory/knowledge/sources.toml` (15 roots, ~1,200 documents) for the first time, resolving Open Question 4. Findings recorded in `evidence/real-corpus-parity-report.md`: 1,213 live items / 12,699 chunks synced cleanly (zero fetch failures, all 13 canonical overrides took effect correctly); the office-format gap is real and now sized at 39 files (32 `.docx`, 5 `.xlsx`, 2 `.pptx`), invisible to the sync summary because every root's `include` patterns are markdown-only; OR-matcher worst case measured at ~1.521s on this corpus size; 8/10 category queries returned the correct top citation, 2 returned a topically-adjacent but non-canonical document (a BM25 ranking limitation, not a discovery defect); sync baseline recorded at 5:20.37 wall-clock, ~4.48 GiB peak RSS. Office-format handlers remain unregistered pending dependency approval — no change to that deferral.
- ✅ This step: full verification re-confirmed green (`black --check` and `ruff check` run clean with no fixes needed; `pytest tests/` and `sync --help` reconfirmed via preserved validator evidence from this run, not rerun). `README.md` updated to document the previously-undocumented `--workspace-root` and `--database` flags on `lee-kb sync`.

### In Progress

- None. Sprint 1 is closed for the scoped slice; see Next Actions Queue for follow-on work.

### Recently Decided (2026-08-03 architecture review)

- ✅ Architecture review completed: identity, journal, deletion, migration, retrieve() contract, surfaces, sync, config, evaluation, and projects all locked (see Decisions Locked).
- ✅ Second connector selected: email, Outlook/Microsoft 365 first, Gmail as early follow-on.
- ✅ Derived artifacts, ranking signals, retrieval surfaces, and projects added to `architecture.md` and `product-definition.md`.
- ✅ v1 reframed as a reimplementation of the Employee Zero knowledge system (~1,200 documents, 15 source roots) with the parity acceptance criterion: the Chief of Staff switches off the old `kb` commands without losing capability.
- ✅ Identity consumed from the Agent Board model; principal required on every retrieval; fail-closed.

## Decisions Locked

| Decision | Rationale | Date |
|----------|-----------|------|
| Original systems remain authoritative | Avoids migration, ownership confusion, and stale copies | 2026-08-03 |
| First release targets a personal SQLite deployment | Provides a useful validation path without enterprise infrastructure | 2026-08-03 |
| Connectors feed a normalized knowledge projection | Gives every source the same retrieval and governance path | 2026-08-03 |
| Permission filtering precedes evidence delivery | Prevents unauthorized source content from reaching an AI model | 2026-08-03 |
| Lexical retrieval comes before semantic retrieval | Validates the core evidence path with fewer moving parts | 2026-08-03 |
| lee-kb is a platform, not an Agent-Orch subsystem | Consumers depend on lee-kb, lee-kb depends on connectors — never the reverse | 2026-08-03 |
| Identity: item = (connector, source_object); chunk = (item, ordinal, content_hash) | Receipts store item ID + chunk ID + hash + locator + timestamp, so they stay verifiable after the projection evolves | 2026-08-03 |
| Latest-state projection plus append-only sync journal | Answers "what changed" questions without full document versioning | 2026-08-03 |
| Deletion = tombstone by default, purge as optional policy | Receipts stay resolvable; clients configure governance-driven purge later | 2026-08-03 |
| Stored schema version + migration framework; wipe-and-resync is the v1 upgrade path | The projection is disposable; sources are authoritative | 2026-08-03 |
| retrieve() contract: query, principal, top_k, filters, freshness, project | Filters are simple equality/range on connector, project, date, type, tags — no query language | 2026-08-03 |
| Library is the product; CLI is the v1 surface; MCP server is Phase 2 | All surfaces exercise the same public retrieval API | 2026-08-03 |
| Sync is user-driven (`lee-kb sync [...]`); daemons and watchers deferred | Freshness reporting makes staleness visible instead | 2026-08-03 |
| Configuration is a public contract at `~/.config/lee-kb/config.toml` | Client deployments will depend on it; documented from day one | 2026-08-03 |
| Golden evaluation corpus (~20 real questions) is a Sprint 1 deliverable | Semantic retrieval must measurably beat the lexical baseline before adoption | 2026-08-03 |
| project field is required on every knowledge item; v1 uses `default` | Forces the tenancy/scoping boundary into the data model from day one at near-zero cost | 2026-08-03 |
| Second connector is email, not GitHub | Broader product value: conversational knowledge, threading, distillation; every customer has email | 2026-08-03 |
| Email provider order: Outlook/Microsoft 365 first, Gmail as early follow-on | Personal deployment and expected customer deployments live in the Microsoft ecosystem | 2026-08-03 |
| v1 is a reimplementation of the Employee Zero knowledge system, not a greenfield product | Preserve the `knowledge/sources.toml` source roots and rebuild the projection; the old `.kb/index.sqlite` is not authoritative | 2026-08-03 |
| v1 file formats: Markdown, plain text, .docx, .xlsx, .pptx | Support the formats the deployed Chief of Staff workflow actually uses | 2026-08-03 |
| Identity reuses the Agent Board model; retrieval always requires a principal | One identity system for humans, machine identities, and AI employees; CLI defaults to Lee; evaluation is fail-closed | 2026-08-03 |
| Golden corpus = ~20 real Chief of Staff questions plus negative cases | Measures correct evidence, citations, project scoping, and freshness — not plausible-looking text | 2026-08-03 |
| v1 complete = the Chief of Staff can switch from the old `kb` commands to lee-kb without losing capability | Objective acceptance criterion; prevents drift into architecture astronautics | 2026-08-03 |
| Identity-provider independence: Agent Board identities reused via adapter; the personal `lee` principal never requires Agent Board at runtime | Governance compatibility without a hard runtime dependency for personal deployments | 2026-08-03 |
| Office formats are deferred implementation, not deferred contract | .docx/.xlsx/.pptx stay required v1 scope and parity requirements; contracts and handler registry must support them without redesign | 2026-08-03 |
| Generated corpus proves the evaluation framework only | The curated golden benchmark completes only with Lee's real Chief of Staff questions against Employee Zero sources | 2026-08-03 |

## Document Inventory

### Product and architecture

| File | Purpose | Status |
|------|---------|--------|
| `product-definition.md` | Vision, users, scope, and success criteria | ✅ Source of truth |
| `architecture.md` | Layers, data flow, and provider boundaries | ✅ Source of truth |
| `research/` | Research inputs and patterns to evaluate | ✅ Available |
| `project-plan.md` | Long-term phases and metrics | ✅ Aligned |
| `docs/sprint-1-contracts.md` | Field-by-field domain contract specification | ✅ Available |
| `docs/golden-baseline.md` | Golden evaluation corpus method and recorded lexical baseline | ✅ Available |
| `evidence/real-corpus-parity-report.md` | Measured findings from syncing/querying the real deployed Employee Zero corpus | ✅ Available |

### Session memory

| File | Purpose | Status |
|------|---------|--------|
| `context.md` | Working state and next actions | 🔄 Active |
| `WHERE_AM_I.md` | Product-level orientation | 🔄 Active |
| `result-review.md` | Completed-work log | 🔄 Active |
| `sprint-plan.md` | Tactical execution | 🔄 Active |

### Workflow

| Directory | Purpose | Status |
|-----------|---------|--------|
| `agents/` | Role instructions | ✅ Created |
| `skills/` | Repeatable project workflows | ✅ Aligned |
| `backlog/` | Curated work-item pipeline | ✅ Available |
| `code-reviews/` | Independent review artifacts | ✅ Available |

## Open Questions

1. Which Employee Zero workflow capabilities are in lee-kb's parity scope? KB freshness check, rebuild, FAQ loading, and search clearly are; live mission status and dossier validation may belong to consumers or a future Agent-Orch connector rather than the retrieval platform.
2. Which parsing libraries are approved for .docx/.xlsx/.pptx? Now sized precisely: 39 files (32 `.docx`, 5 `.xlsx`, 2 `.pptx`) sit inside the 15 real configured root paths, concentrated in `ai-employee-book` (21 `.docx`) and `tviq` (9 files); ten of the 15 roots have zero office-format files. Office formats require new runtime dependencies, which need explicit approval per project constraints, **and** the affected roots' `include` patterns must be extended — approving dependencies alone will not surface these files. The contracts and format-handler registry already support adding handlers without redesign.
3. Where does the Agent Board identity model live today, and what does lee-kb consume — a library, a service, or a shared schema? (Not blocking for the personal `lee` principal, which runs with no Agent Board dependency; relevant once a second principal or consumer needs identity.)
4. ~~Does this checkout have access to the real `knowledge/sources.toml`...~~ **Resolved 2026-08-03**: yes. All 15 configured roots resolved to real, present directories; a full clean sync produced 1,213 live items / 12,699 chunks, closely tracking the `research/employee-zero-kb-reference.md` snapshot (1,209 documents / 12,634 chunks). See `evidence/real-corpus-parity-report.md`.
5. Is the OR-matcher's measured worst case (~1.521s for a single ubiquitous token, on the current ~1,213-document corpus) acceptable as-is, or does it need a page-size cap / early-exit heuristic before corpus size grows further via office-format ingestion? (New question raised by the real-corpus measurement; see `evidence/real-corpus-parity-report.md` Performance and Recommended Next Actions.)

## Next Actions Queue

Priority order re-ranked by Lee 2026-08-03 after the real-corpus parity
measurement (`evidence/real-corpus-parity-report.md`): the measurement
resolved Open Question 4 and sized the office-format gap precisely, so
approving those dependencies and extending `include` patterns now leads;
a known correctness defect and the OR-matcher decision follow before
benchmark and connector work.

| Rank | Action | Owner | Done When |
|------|--------|-------|-----------|
| 1 | Approve `.docx`/`.xlsx`/`.pptx` parsing libraries, register format handlers, **and** extend the `include` patterns on the affected roots (real corpus measurement: 39 files, concentrated in `ai-employee-book` and `tviq` — parity is impossible without both dependency approval and the pattern change) | Human approval + Builder | Dependencies approved and added; `FORMAT_HANDLERS` covers office formats; affected roots' `include` patterns updated; unhandled include-matched files are reported, not silently invisible; tests added |
| 2 | Fix S1-R-14: `discover()` and `_resolve()` must share one resolved root base (correctness; fix before office-format ingestion touches more root paths or any customer deployment) | Builder | A directly built `RootConfig` over a symlinked root discovers and fetches consistently; regression test added |
| 3 | Decide whether the OR-matcher's measured ~1.521s worst case (Open Question 5) is acceptable as-is or needs a page-size cap / early-exit heuristic before corpus size grows via office-format ingestion | Human + Builder | Decision recorded in `architecture.md` or a backlog item; if a heuristic is chosen, implemented and re-measured against the real corpus |
| 4 | Assert the retrieval baseline in the harness (S1-R-16): compute hit-at-1/hit-at-10/MRR and fail if they regress from `docs/golden-baseline.md` beyond a stated tolerance | Builder | The benchmark is a contract, not documentation |
| 5 | Curate the real golden benchmark from Lee's recurring Chief of Staff questions, using the two ranking edge cases surfaced by the real-corpus measurement (one job-search, one knowledge-discovery query, each topically-adjacent-but-non-canonical) as concrete starting material | Human + Builder | `docs/golden-baseline.md` reports results against the curated corpus |
| 6 | File the Agent-Orch defect: continuation runs record `launch: null`, making crashed continuations unresumable | Human + Platform | Backlog item exists in agent-orch with the OS1-contract reference |
| 7 | Implement the Outlook/Microsoft 365 email connector | Human + Planner | Connector scoped, approved, and implemented against the `Connector` contract |
| 8 | Resolve Open Question 1 (Employee Zero parity scope for live mission status and dossier validation) | Human + Planner | Parity scope decision recorded in `architecture.md` or `product-definition.md` |

## Working Conventions

### Start of session

1. Read `AGENTS.md`.
2. Read this file, `WHERE_AM_I.md`, `result-review.md`, and `sprint-plan.md`.
3. Read the product, architecture, and relevant research for the task.
4. Execute only the highest-ranked in-scope action.
5. Update this file whenever state changes.

### End of work unit

1. Move completed items into “Recently Completed.”
2. Update the next-actions queue.
3. Record decisions and unresolved risks.
4. Keep open questions short and actionable.

## Environment Notes

- **Working Directory:** `/Volumes/lee-linux-projects/lee-kb`
- **Project Name:** `lee-kb`
- **Profile:** Python package / governed retrieval service
- **Author:** Lee Harrington
- **Public Repository:** `https://github.com/leebase/lee-kb`

*This file is living project memory; keep it factual and current.*
