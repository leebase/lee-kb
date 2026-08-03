# Lee Knowledge Base Session Context

> **Purpose:** Working memory for session continuity. Read this after
> `AGENTS.md` and before acting.

## Snapshot

| Attribute | Value |
|-----------|-------|
| **Phase** | Phase 0 — Product and Architecture Alignment |
| **Mode** | 2 (Collaborative implementation with approval) |
| **Last Updated** | 2026-08-03 |

### Sprint Status

| Sprint | Status | Completion |
|--------|--------|------------|
| Sprint 1 — Personal Foundation | 🟡 Ready for implementation | 1 planning task complete; 0% product functionality |

## What's Happening Now

### Current Work Stream

The project is aligned around the governed knowledge fabric defined in
`product-definition.md` and `architecture.md`. The next implementation target
is one end-to-end personal retrieval path: local documents → normalized items
and chunks → SQLite → lexical evidence with citations, freshness, and receipts.

### Recently Completed

- ✅ Product definition and architecture are established.
- ✅ Cerebras knowledge-base research is available under `research/`.
- ✅ AgentFlow project memory was aligned with the product and architecture.
- ✅ Role instructions were added under `agents/` and domain workflows under `skills/`.
- ✅ Bootstrap CLI metadata and behavior now describe the governed retrieval product.
- ✅ Bootstrap smoke tests pass and generated local metadata is ignored.
- ✅ Public GitHub repository created at `https://github.com/leebase/lee-kb` with `main` as the default branch.

### In Progress

- ⏳ Define the first vertical slice's domain contracts and acceptance tests.

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
2. Which parsing libraries are approved for .docx/.xlsx/.pptx? (Office formats require new runtime dependencies, which need explicit approval per project constraints.)
3. Where does the Agent Board identity model live today, and what does lee-kb consume — a library, a service, or a shared schema?

## Next Actions Queue

| Rank | Action | Owner | Done When |
|------|--------|-------|-----------|
| 1 | Inventory the existing Employee Zero kb implementation (`knowledge/sources.toml`, `python -m kb build`, consumers) as the v1 reference | Human + Planner | Reference behaviors and parity scope are documented |
| 2 | Define source, knowledge-item, chunk, evidence, and receipt contracts | Human + Builder | Contracts and tests are reviewed and documented |
| 3 | Implement the local-file connector and SQLite repository | Builder | A changed file is incrementally synchronized and queryable |
| 4 | Add deterministic chunking and lexical retrieval | Builder | Exact-token queries return ranked chunks |
| 5 | Add provenance, permission checks, freshness, and retrieval receipts | Builder | Every result is filtered and auditable |
| 6 | Build the golden evaluation corpus and record the lexical baseline | Human + Builder | ~20 real Chief of Staff questions (plus negative cases) run as a test fixture with a recorded baseline |
| 7 | Implement the Outlook/Microsoft 365 email connector (after local-file path is tested end to end) | Human + Planner | Connector scoped and approved |

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
