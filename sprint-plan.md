# Lee Knowledge Base Sprint Plan

> **Sprint 1 — Personal Foundation**
>
> Goal: prove one governed retrieval path from local documents to cited lexical
> evidence in SQLite.

## Sprint status

| Field | Value |
|-------|-------|
| **Status** | 🟡 Ready for implementation |
| **Start** | 2026-08-03 |
| **Completion** | Project alignment complete; product work not started |
| **Primary owner** | Human + Builder agent |

## Scope

### In scope

- Define the connector, knowledge item, chunk, evidence bundle, and retrieval receipt contracts.
- Apply the locked identity model: item = (connector_id, source_object_id); chunk = (item_id, ordinal, content_hash); receipts store item ID, chunk ID, content hash, source locator, and retrieval timestamp.
- Require a project field on every knowledge item (single `default` project in v1).
- Import the existing `knowledge/sources.toml` source roots and rebuild the projection from sources (the old `.kb/index.sqlite` is reference, not authority).
- Support Markdown, plain text, .docx, .xlsx, and .pptx documents.
- Require a principal on every retrieval (Agent Board identity model; CLI defaults to Lee; fail-closed).
- Implement local-file discovery, change detection, fetch, provenance, and checkpointing.
- Persist normalized items, chunks, metadata, permissions, sync state, and an append-only sync journal in SQLite, with a stored schema version.
- Tombstone deleted source objects instead of hard-deleting them.
- Add deterministic chunking and lexical retrieval.
- Enforce permission filtering before evidence assembly.
- Return citations, freshness metadata, and retrieval receipts.
- Build a golden evaluation corpus (~20 real questions with expected evidence, source, and citation) as the lexical baseline.

### Golden corpus guidance

Draw questions from real Chief of Staff usage across five areas: operational status ("what happened during last night's Auto-Orch run?"), project management ("what are the highest-priority open decisions?"), architecture ("why was this design decision made?"), job search ("which applications require follow-up?"), and knowledge discovery ("what proposal mentioned this customer?").

Include negative cases: no evidence exists; evidence exists but is outside the current project scope; evidence exists but is not visible to the requesting principal.

Success is correct evidence retrieval, correct citations, correct project scoping, and freshness reporting — not plausible-looking text.
- Add automated tests and a realistic end-to-end user workflow.

### Out of scope

- Semantic embeddings, reranking, and LLM synthesis.
- Multi-user or tenant authorization.
- PostgreSQL, Snowflake, or enterprise deployment.
- External connectors beyond the one selected after local files.
- Execution, workflow, or action authorization.

## Tasks

| ID | Task | Owner | Status | Done when |
|----|------|-------|--------|-----------|
| S1-00 | Align AgentFlow project memory and roles | Human + AI | ✅ Complete | Root docs, agents, and skills describe this product |
| S1-01 | Define normalized domain contracts, grounded in an inventory of the existing Employee Zero kb implementation | Planner + Builder | ⬜ Not started | Reference behaviors and parity scope are documented; interfaces and schemas are documented and tested |
| S1-02 | Implement local-file connector | Builder | ⬜ Not started | New and changed files sync with stable cursors and provenance |
| S1-03 | Implement SQLite repository | Builder | ⬜ Not started | Items, chunks, metadata, permissions, and sync state persist transactionally |
| S1-04 | Add chunking and lexical retrieval | Builder | ⬜ Not started | Exact-token query returns deterministic ranked evidence |
| S1-05 | Add governance and receipts | Builder | ⬜ Not started | Permission filtering, freshness, citations, and receipt fields are verified |
| S1-06 | Build the golden evaluation corpus | Human + Builder | ⬜ Not started | ~20 real questions with expected evidence run against lexical retrieval and record a baseline |
| S1-07 | Validate the full workflow and document it | Reviewer + Builder | ⬜ Not started | Automated tests and user-path checks pass; docs match behavior |

## Decision gates

1. Do not implement retrieval before the permission and provenance fields are defined.
2. The second connector is email (decided); do not begin implementing it until the local-file path is tested end to end.
3. Do not add semantic infrastructure until lexical retrieval establishes a measurable baseline via the golden corpus.
4. Escalate any schema or public-interface change that would make future providers incompatible.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Local-file permission model is underspecified | Start with explicit single-user assumptions and keep the field extensible |
| File changes are missed or duplicated | Use content hashes, stable source IDs, and atomic checkpoints |
| Retrieval returns stale or untraceable text | Store source and sync timestamps plus canonical source references |
| Sprint grows into a general search platform | Hold the scope to local files, SQLite, lexical search, and receipts |
| Office formats pull in new runtime dependencies | Get explicit approval for .docx/.xlsx/.pptx parsing libraries before adding them |
| Parity scope creeps to non-retrieval features | Live mission status and dossier validation stay with consumers unless explicitly pulled in |

## Sprint definition of done

- [ ] The existing `knowledge/sources.toml` roots import and synchronize into the new projection.
- [ ] A local document can be synchronized twice without duplicate projection rows.
- [ ] A changed document updates its normalized projection, checkpoint, and journal entry.
- [ ] A deleted document is tombstoned and excluded from ordinary search.
- [ ] A lexical query returns ranked chunks with original-source citations.
- [ ] The golden evaluation corpus runs and records a lexical baseline.
- [ ] Permission filtering occurs before evidence is assembled.
- [ ] Freshness status and a retrieval receipt are emitted for each retrieval.
- [ ] Automated tests cover happy paths, empty input, changes, repeated sync, and denied evidence.
- [ ] `README.md`, `context.md`, `WHERE_AM_I.md`, and `result-review.md` reflect the delivered behavior.

*Update task status as work is completed; keep new ideas in `backlog/candidates/`.*
