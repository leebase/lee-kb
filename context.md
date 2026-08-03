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
--check`, `ruff check`) is green and `README.md`, `sprint-plan.md`, and
`WHERE_AM_I.md` reflect the delivered behavior. The next work stream is
choosing between curating the real golden benchmark, approving office-format
dependencies, and starting the email connector (see Next Actions Queue).

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
2. Which parsing libraries are approved for .docx/.xlsx/.pptx? (Office formats require new runtime dependencies, which need explicit approval per project constraints. The contracts and format-handler registry already support adding them without redesign.)
3. Where does the Agent Board identity model live today, and what does lee-kb consume — a library, a service, or a shared schema? (Not blocking for the personal `lee` principal, which runs with no Agent Board dependency; relevant once a second principal or consumer needs identity.)
4. Does this checkout have access to the real `knowledge/sources.toml` and the Employee Zero source roots (~1,200 documents, 15 roots)? Sprint 1's local-file connector was verified against test fixtures and a manual scratch corpus only — the actual import has not run.

## Next Actions Queue

Priority order locked by Lee 2026-08-03 after Sprint 1 review: real-corpus
information first, parity blockers second, correctness third, benchmark
contract fourth, measurement fifth.

| Rank | Action | Owner | Done When |
|------|--------|-------|-----------|
| 1 | Run against the Employee Zero corpus: point config at the real `knowledge/sources.toml` (~1,200 documents, 15 roots), `lee-kb sync`, and answer Lee's daily questions | Human + Builder | The full corpus is synchronized and queryable; findings about realistic load recorded |
| 2 | Approve `.docx`/`.xlsx`/`.pptx` parsing libraries and register format handlers (parity is impossible without them; the real corpus contains office documents) | Human approval + Builder | Dependencies approved and added; `FORMAT_HANDLERS` covers office formats; unhandled include-matched files are reported, not silently invisible; tests added |
| 3 | Fix S1-R-14: `discover()` and `_resolve()` must share one resolved root base (correctness; fix before any customer deployment) | Builder | A directly built `RootConfig` over a symlinked root discovers and fetches consistently; regression test added |
| 4 | Assert the retrieval baseline in the harness (S1-R-16): compute hit-at-1/hit-at-10/MRR and fail if they regress from `docs/golden-baseline.md` beyond a stated tolerance | Builder | The benchmark is a contract, not documentation |
| 5 | Measure OR-search fetch-to-exhaustion on the real corpus (measure before optimizing) | Builder | Latency/volume numbers recorded for common-word queries over ~1,200 documents |
| 6 | File the Agent-Orch defect: continuation runs record `launch: null`, making crashed continuations unresumable | Human + Platform | Backlog item exists in agent-orch with the OS1-contract reference |
| 7 | Curate the real golden benchmark from Lee's recurring Chief of Staff questions (informed by rank 1's experience) | Human + Builder | `docs/golden-baseline.md` reports results against the curated corpus |
| 8 | Implement the Outlook/Microsoft 365 email connector | Human + Planner | Connector scoped, approved, and implemented against the `Connector` contract |
| 9 | Resolve Open Question 1 (Employee Zero parity scope for live mission status and dossier validation) | Human + Planner | Parity scope decision recorded in `architecture.md` or `product-definition.md` |

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
