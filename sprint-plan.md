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
- Implement local-file discovery, change detection, fetch, provenance, and checkpointing.
- Persist normalized items, chunks, metadata, permissions, and sync state in SQLite.
- Add deterministic chunking and lexical retrieval.
- Enforce permission filtering before evidence assembly.
- Return citations, freshness metadata, and retrieval receipts.
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
| S1-01 | Define normalized domain contracts | Planner + Builder | ⬜ Not started | Interfaces and schemas are documented and tested |
| S1-02 | Implement local-file connector | Builder | ⬜ Not started | New and changed files sync with stable cursors and provenance |
| S1-03 | Implement SQLite repository | Builder | ⬜ Not started | Items, chunks, metadata, permissions, and sync state persist transactionally |
| S1-04 | Add chunking and lexical retrieval | Builder | ⬜ Not started | Exact-token query returns deterministic ranked evidence |
| S1-05 | Add governance and receipts | Builder | ⬜ Not started | Permission filtering, freshness, citations, and receipt fields are verified |
| S1-06 | Validate the full workflow and document it | Reviewer + Builder | ⬜ Not started | Automated tests and user-path checks pass; docs match behavior |

## Decision gates

1. Do not implement retrieval before the permission and provenance fields are defined.
2. Do not select the second connector until the local-file path is tested end to end.
3. Do not add semantic infrastructure until lexical retrieval establishes a measurable baseline.
4. Escalate any schema or public-interface change that would make future providers incompatible.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Local-file permission model is underspecified | Start with explicit single-user assumptions and keep the field extensible |
| File changes are missed or duplicated | Use content hashes, stable source IDs, and atomic checkpoints |
| Retrieval returns stale or untraceable text | Store source and sync timestamps plus canonical source references |
| Sprint grows into a general search platform | Hold the scope to local files, SQLite, lexical search, and receipts |

## Sprint definition of done

- [ ] A local document can be synchronized twice without duplicate projection rows.
- [ ] A changed document updates its normalized projection and checkpoint.
- [ ] A lexical query returns ranked chunks with original-source citations.
- [ ] Permission filtering occurs before evidence is assembled.
- [ ] Freshness status and a retrieval receipt are emitted for each retrieval.
- [ ] Automated tests cover happy paths, empty input, changes, repeated sync, and denied evidence.
- [ ] `README.md`, `context.md`, `WHERE_AM_I.md`, and `result-review.md` reflect the delivered behavior.

*Update task status as work is completed; keep new ideas in `backlog/candidates/`.*
