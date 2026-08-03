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
- ⏳ Select the second connector after the local-file connector.

## Decisions Locked

| Decision | Rationale | Date |
|----------|-----------|------|
| Original systems remain authoritative | Avoids migration, ownership confusion, and stale copies | 2026-08-03 |
| First release targets a personal SQLite deployment | Provides a useful validation path without enterprise infrastructure | 2026-08-03 |
| Connectors feed a normalized knowledge projection | Gives every source the same retrieval and governance path | 2026-08-03 |
| Permission filtering precedes evidence delivery | Prevents unauthorized source content from reaching an AI model | 2026-08-03 |
| Lexical retrieval comes before semantic retrieval | Validates the core evidence path with fewer moving parts | 2026-08-03 |

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

1. Which connector should follow local files: Outlook, GitHub, or another source?
2. Which local document formats and filesystem roots belong in the personal release?
3. Should the first user surface be a CLI, a library API, or both?
4. What permission representation is sufficient for the single-user release while remaining extensible?
5. What fields are required in the first retrieval receipt?

## Next Actions Queue

| Rank | Action | Owner | Done When |
|------|--------|-------|-----------|
| 1 | Define source, knowledge-item, chunk, evidence, and receipt contracts | Human + Builder | Contracts and tests are reviewed and documented |
| 2 | Implement the local-file connector and SQLite repository | Builder | A changed file is incrementally synchronized and queryable |
| 3 | Add deterministic chunking and lexical retrieval | Builder | Exact-token queries return ranked chunks |
| 4 | Add provenance, permission checks, freshness, and retrieval receipts | Builder | Every result is filtered and auditable |
| 5 | Choose and implement the second connector | Human + Planner | Connector is explicitly approved and scoped |

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
