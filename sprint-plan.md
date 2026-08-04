# Lee Knowledge Base Sprint Plan

> **Sprint 2 — Real-Corpus Parity & Post-Parity Repairs** (active)
>
> Goal: measure the Sprint 1 delivery against Lee's real deployed
> `ai-employee-factory/knowledge/sources.toml` corpus, then repair whatever
> that measurement and its independent review surfaced.
>
> Sprint 1 — Personal Foundation is delivered; its record is preserved below,
> unchanged, under "Sprint 1 (Delivered)".

## Sprint 2 — Real-Corpus Parity & Post-Parity Repairs

### Sprint 2 status

| Field | Value |
|-------|-------|
| **Status** | 🟡 In progress — P1 (real-corpus parity measurement) delivered; review-surfaced repairs S2-R-04, S2-R-03, and S1-R-16 complete and re-verified; office-format dependency approval, the OR-matcher decision, and the curated golden benchmark remain open, pending Lee |
| **Start** | 2026-08-03 |
| **Primary owner** | Human + Builder agent |

### Sprint 2 scope

#### In scope

- Synchronize and query the real deployed `ai-employee-factory/knowledge/sources.toml` corpus (15 roots, ~1,200 documents) with the Sprint 1 delivery, and record findings (P1 — done; `evidence/real-corpus-parity-report.md`).
- Independent review of that measurement and the code it exercised (done; `code-reviews/review-sprint-2-p1-real-corpus.md`, verdict: pass).
- Repair the correctness and performance defects that review surfaced, scoped to what it found — not a general refactor.

#### Out of scope (tracked, not abandoned)

- Office-format (`.docx`/`.xlsx`/`.pptx`) parsing implementation — still unimplemented pending Lee's dependency approval **and** the affected roots' `include`-pattern changes in the deployed configuration. Neither alone closes the gap; see `evidence/real-corpus-parity-report.md`.
- The curated Chief-of-Staff golden benchmark — still does not exist. The generated 20-question corpus in `tests/golden/` proves the evaluation harness only; it is not a substitute.
- The OR-matcher fetch-to-exhaustion heuristic decision (Open Question 5 in `context.md`).
- The Outlook/Microsoft 365 email connector.

### Sprint 2 tasks

| ID | Task | Owner | Status | Done when |
|----|------|-------|--------|-----------|
| S2-P1 | Real-corpus parity measurement | Builder | ✅ Complete | `evidence/real-corpus-parity-report.md` records corpus shape, unindexed content, retrieval behavior, and a performance baseline against the real deployed corpus |
| — | Independent review of the P1 slice | Reviewer | ✅ Complete | `code-reviews/review-sprint-2-p1-real-corpus.md`; verdict `pass` |
| S2-R-01 | Ignore corpus-derived scratch and projection directories | Builder | ✅ Complete | commit `7e74e56` |
| S2-R-02 | Sanitize absolute host paths out of a tracked playbook | Builder | ✅ Complete | commit `d1076b6` |
| S2-R-03 | Single discovery pass per sync (correctness of the performance story: the pre-repair sync ran full corpus discovery twice) | Builder | ✅ Complete | `_sync_connector` now calls `connector.discover_report()` once and derives its change list from that report's objects, instead of `list_changes()` and `discover_report()` each running a full pass; re-measured on the real corpus: wall-clock 5:20.37 → 2:51.18 (−46.6%), user time −47.8%, peak RSS unchanged within noise (−0.4%); regression coverage in `tests/test_local_connector.py` and `tests/test_cli.py` |
| S2-R-04 | Nested/overlapping configured roots can double-count one file as two independently citable knowledge items | Builder | ✅ Complete | `LocalFilesConnector` now has one resolved-root claiming rule: the deepest matching resolved root wins an overlapping file, ties broken by root name; `health()` reports detected nested-root pairs; regression tests added in `tests/test_local_connector.py` |
| S1-R-16 | Golden baseline is enforced by the harness, not only documented | Builder | ✅ Complete | `tests/golden/test_golden_corpus.py::test_recorded_baseline_metrics_are_enforced_by_the_harness` computes hit-at-1/hit-at-10/MRR through the governed `retrieve()` surface and fails (tolerance 0.01, symmetric) if they drift from the recorded gate in `docs/golden-baseline.md` |
| S2-R-05..S2-R-11 | Remaining review advisories: two docstring/partition-accuracy findings, two narrative-count corrections in the evidence report, a traceability gap in one commit message, a stale test-count reference, a `ruff` config deprecation, and two missing regression tests | Builder | ⬜ Open (advisory, not blocking) | See `code-reviews/review-sprint-2-p1-real-corpus.md` Remediation Roadmap ("Fix Soon" / "Fix Later") |
| — | Drive full verification green and refresh project memory for the repaired state | Builder | ✅ Complete | This step: `pytest` preserved-validator evidence for S2-R-04/S2-R-03/S1-R-16 all exit 0 (see `result-review.md`); `black --check` and `ruff check` over `src tests tools` both run clean after this step's fixes |

### Sprint 2 verification

- `python3 -m pytest tests/` and `python3 -m pytest tests/golden/` — preserved system-validator evidence tied to the S2-R-04, S2-R-03, and S1-R-16 acceptance criteria; all exit 0. Not rerun by this step (validator rerun not permitted); see `result-review.md` for the exact records.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` and `python3 -m ruff check src tests tools` — run fresh in this step, both clean after repairs (two files needed `black` reformatting and one over-length docstring line needed manual wrapping; no behavioral change).

### Sprint 2 definition of done (not yet reached)

- [x] The Sprint 1 delivery is measured against the real deployed corpus, not only test fixtures.
- [x] S2-R-04, S2-R-03, and S1-R-16 are repaired and re-verified.
- [ ] Office-format parsing dependencies are approved and the affected roots' `include` patterns are extended.
- [ ] The OR-matcher decision (Open Question 5) is recorded.
- [ ] The curated golden benchmark exists (real Chief-of-Staff questions against the Employee Zero sources).

---

## Sprint 1 — Personal Foundation (Delivered 2026-08-03)

> Goal: prove one governed retrieval path from local documents to cited lexical
> evidence in SQLite.

### Sprint 1 status

| Field | Value |
|-------|-------|
| **Status** | 🟢 Delivered (personal foundation slice); two explicit deferrals remain |
| **Start** | 2026-08-03 |
| **Completion** | All 7 sprint tasks complete for the scoped slice. Office formats (.docx/.xlsx/.pptx) and the curated golden benchmark are explicitly deferred — see Sprint closure requirements. |
| **Primary owner** | Human + Builder agent |

### Sprint 1 scope

#### In scope

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

#### Golden corpus guidance

Draw questions from real Chief of Staff usage across five areas: operational status ("what happened during last night's Auto-Orch run?"), project management ("what are the highest-priority open decisions?"), architecture ("why was this design decision made?"), job search ("which applications require follow-up?"), and knowledge discovery ("what proposal mentioned this customer?").

Include negative cases: no evidence exists; evidence exists but is outside the current project scope; evidence exists but is not visible to the requesting principal.

Success is correct evidence retrieval, correct citations, correct project scoping, and freshness reporting — not plausible-looking text.
- Add automated tests and a realistic end-to-end user workflow.

#### Out of scope

- Semantic embeddings, reranking, and LLM synthesis.
- Multi-user or tenant authorization.
- PostgreSQL, Snowflake, or enterprise deployment.
- External connectors beyond the one selected after local files.
- Execution, workflow, or action authorization.

### Sprint 1 tasks

| ID | Task | Owner | Status | Done when |
|----|------|-------|--------|-----------|
| S1-00 | Align AgentFlow project memory and roles | Human + AI | ✅ Complete | Root docs, agents, and skills describe this product |
| S1-01 | Define normalized domain contracts, grounded in an inventory of the existing Employee Zero kb implementation | Planner + Builder | ✅ Complete | `src/lee_kb/contracts.py` and `docs/sprint-1-contracts.md`; verified by `tests/test_contracts.py` |
| S1-02 | Implement local-file connector | Builder | ✅ Complete | `src/lee_kb/connectors/local_files.py` syncs new and changed files with stable content-hash cursors and provenance; verified by `tests/test_local_connector.py` |
| S1-03 | Implement SQLite repository | Builder | ✅ Complete | `src/lee_kb/repository.py` persists items, chunks, metadata, permissions, and sync state transactionally; verified by `tests/test_repository.py` |
| S1-04 | Add chunking and lexical retrieval | Builder | ✅ Complete | `src/lee_kb/chunking.py` and `src/lee_kb/retrieval.py`; deterministic ranked evidence verified by `tests/test_retrieval.py` |
| S1-05 | Add governance and receipts | Builder | ✅ Complete | `src/lee_kb/governance.py`; fail-closed permission filtering, freshness, citations, and receipts verified by `tests/test_governance.py` |
| S1-06 | Build the golden evaluation corpus | Human + Builder | ✅ Complete (framework proof only) | `tests/golden/` and `docs/golden-baseline.md` run 20 generated questions plus 3 negative controls and record a lexical baseline; this proves the evaluation harness, not the curated benchmark — see Sprint closure requirements |
| S1-07 | Validate the full workflow and document it | Reviewer + Builder | ✅ Complete | Full suite passes (`pytest tests/`); `black --check` and `ruff check` pass; `lee-kb init/sync/search` exercised end to end; docs updated to match delivered behavior |

### Sprint 1 decision gates

1. Do not implement retrieval before the permission and provenance fields are defined.
2. The second connector is email (decided); do not begin implementing it until the local-file path is tested end to end.
3. Do not add semantic infrastructure until lexical retrieval establishes a measurable baseline via the golden corpus.
4. Escalate any schema or public-interface change that would make future providers incompatible.

### Sprint 1 risks and mitigations

| Risk | Mitigation |
|------|------------|
| Local-file permission model is underspecified | Start with explicit single-user assumptions and keep the field extensible |
| File changes are missed or duplicated | Use content hashes, stable source IDs, and atomic checkpoints |
| Retrieval returns stale or untraceable text | Store source and sync timestamps plus canonical source references |
| Sprint grows into a general search platform | Hold the scope to local files, SQLite, lexical search, and receipts |
| Office formats pull in new runtime dependencies | Get explicit approval for .docx/.xlsx/.pptx parsing libraries before adding them |
| Parity scope creeps to non-retrieval features | Live mission status and dossier validation stay with consumers unless explicitly pulled in |

### Sprint 1 closure requirements (locked 2026-08-03, binding on verification and review steps)

The closing review must distinguish these two limitations clearly — they are different kinds of gap:

1. **Office formats (.docx/.xlsx/.pptx) are required v1 product scope and deployed-reference parity requirements.** Their implementation is deferred from this run pending dependency approval only. The review must verify the contracts and format-handler registry support them without redesign — deferral of implementation, never deferral of the contract.
2. **The generated twenty-question corpus proves the evaluation framework only.** It does not complete the curated golden benchmark until it includes Lee's real recurring Chief of Staff questions against the Employee Zero knowledge sources. The review and docs must not claim the golden benchmark is done.

Identity: reuse Agent Board identities through an adapter where appropriate, but lee-kb must not be runtime-dependent on Agent Board for the personal `lee` principal.

### Sprint 1 definition of done

- [x] The existing `knowledge/sources.toml` roots import and synchronize into the new projection. *(Done 2026-08-03: the real deployed `ai-employee-factory/knowledge/sources.toml` (15 roots, ~1,200 documents) was synced and queried — 1,213 live items / 12,699 chunks, zero fetch failures, all 15 roots reachable. See `evidence/real-corpus-parity-report.md` and `result-review.md`. Office-format files inside those roots remain unindexed pending dependency approval and `include`-pattern extension — a separate, tracked gap, not a failure of this item.)*
- [x] A local document can be synchronized twice without duplicate projection rows.
- [x] A changed document updates its normalized projection, checkpoint, and journal entry.
- [x] A deleted document is tombstoned and excluded from ordinary search.
- [x] A lexical query returns ranked chunks with original-source citations.
- [x] The golden evaluation corpus runs and records a lexical baseline. *(Generated seed corpus proving the evaluation harness — not the curated benchmark; see Sprint closure requirements and `docs/golden-baseline.md`.)*
- [x] Permission filtering occurs before evidence is assembled.
- [x] Freshness status and a retrieval receipt are emitted for each retrieval.
- [x] Automated tests cover happy paths, empty input, changes, repeated sync, and denied evidence.
- [x] `README.md`, `context.md`, `WHERE_AM_I.md`, and `result-review.md` reflect the delivered behavior.

*Update task status as work is completed; keep new ideas in `backlog/candidates/`.*
