# Lee Knowledge Base Sprint Plan

> **Sprint 3 — Governed `answer()` Surface** (delivered)
>
> Goal: layer a governed, cited *answer* surface (claims, confidence,
> conflicts, absences) on top of the already-governed `retrieve()`, with no
> new permission logic and no LLM dependency in this release.
>
> Sprint 2 — Real-Corpus Parity & Post-Parity Repairs remains in progress on
> its own open items (the OR-matcher decision and the curated golden benchmark);
> its record is preserved below, unchanged, under
> "Sprint 2". Sprint 1 — Personal Foundation is delivered; its record is
> preserved below, unchanged, under "Sprint 1 (Delivered)".

## Sprint 4 — Personal Connector Foundation (Delivered 2026-08-05)

**Status:** Bounded offline connector slice delivered and hardened; conditional offline pass; live external integration remains gated

**Goal:** Prove the existing connector boundary against the personal Second
Brain roadmap before implementing an external API connector. Keep the current
single-principal SQLite release intact and make no speculative tenant, RBAC, or
enterprise-service changes.

### Proposed scope

- Build a connector conformance suite around the existing `Connector` contract.
- Record a capability matrix for local directories, OneDrive, Outlook, Gmail,
  and OneNote.
- Specify source/account/scope identity, incremental state, permissions,
  freshness, deletion, temporary failure, health, and checkpoint behavior for
  the first external connector family.
- Use the matrix to select the first external connector for a separate,
  explicitly approved slice.
- Implement the selected Outlook slice behind an injected transport, without
  credentials, network access, or a new runtime dependency.

### Explicitly out of scope

- A tenant column or tenant administration service.
- Enterprise RBAC, centralized operations, or high-availability deployment.
- Live connection to Microsoft or Google systems without explicit approval.
- An LLM-backed synthesis provider.
- Rebuilding the already-delivered generic connector contract.

### Proposed acceptance criteria

- `BI-001-connector-conformance-and-capability-matrix.md` is implemented as
  focused tests and documentation.
- `LocalFilesConnector` passes the conformance suite for discovery, change
  detection, fetch, checkpointing, permissions, health, deletion, and temporary
  failure semantics.
- A capability matrix identifies the first external connector and its blocking
  API/authentication questions without claiming unsupported feasibility.
- The bounded Outlook adapter is deterministic and offline: one delegated
  `/me` folder, immutable message IDs, normalized email text, relationships,
  permissions, delta changes, and fail-closed checkpoint behavior are tested.
- Existing retrieval, answer, audit, Office, disclosure, and CLI checks remain
  green.

### BI-001 delivery status

| ID | Status | Evidence |
|----|--------|----------|
| BI-001 | ✅ Implemented; golden seed reconciled in the current slice | `tests/test_connector_conformance.py` and the existing local connector tests cover the contract; `docs/connector-capability-matrix.md` records official provider evidence, offline Outlook behavior, and live unknowns. No live external connection or new runtime dependency was added. |
| BI-003 bounded offline adapter | ✅ Complete; review hardening complete with conditional pass | `src/lee_kb/connectors/outlook.py`, `tests/test_outlook_connector.py` (18 focused tests), and `docs/outlook-connector.md` define and verify one-folder delta paging, immutable message identity, deterministic normalization, relationships, private owner permissions, freshness, deletion, failure, health, refresh, metadata-only cursors, fetch/locator drift, and checkpoint safety. See `code-reviews/review-2026-08-05.md`. |

The real live Outlook proof remains gated on account/consent approval; the
offline adapter and Graph transport/authentication foundation are implemented.
BI-002 and BI-004 through BI-006 remain unimplemented candidates.
The OR-matcher decision and curated golden benchmark remain open under Sprint
2 and were not changed. At the Sprint 4 milestone, the full test run collected
324 tests and all 324 passed after `tests/golden/corpus.toml` was reconciled with the current
`project-plan.md`; the generated seed baseline is now 80.0% hit-at-1, 100.0%
hit-at-10, and 0.888 MRR. This does not promote the generated seed to the
curated benchmark.

### BI-001 focused verification

- `python3 -m pytest tests/test_connector_conformance.py tests/test_local_connector.py -q` — 42 passed.
- The focused conformance tests cover identity, configured scope, discovery,
  created/updated/deleted changes, repeated no-change snapshots, fetch,
  permissions, source/sync timestamps, health, relationships, refresh, and
  temporary-failure deletion/checkpoint behavior.

### BI-003 offline verification

- `python3 -m pytest tests/test_outlook_connector.py -q` — 18 passed.
- `python3 -m pytest tests/` — 322 passed.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean; 36
  files unchanged.
- `python3 -m ruff check src tests tools` — clean; existing settings
  deprecation warning only.
- `python3 -m compileall -q src tests tools` — clean.
- `python3 tools/check_disclosure.py` — clean.
- `git diff --check` — clean.
- `env PYTHONPATH=src python3 -m lee_kb.main --help`, `--version`, and
  `ask --help` — exit 0.

### BI-003 review disposition

The 2026-08-05 independent review found and repaired checkpoint advancement
after failed fetches, metadata-only freshness drift, source-locator drift,
ordered delete/update handling, weak checkpoint object validation, provider
diagnostic disclosure, and parent-unscoped attachment relationship IDs. The
bounded offline slice is a **conditional pass** with no High/Critical finding.
Relationship persistence through the common repository and richer live
body/attachment semantics remain explicitly gated or deferred; see the review
artifact.

## Sprint 5 — Microsoft Graph Foundation and Live Outlook Proof

**Status:** Graph foundation and live-capable Outlook path implemented offline;
real account proof remains operator-gated

**Goal:** Build one reusable Microsoft Graph foundation for future Microsoft
connectors, then prove the existing Outlook connector against one real mailbox
without turning the first live experiment into an enterprise connector. OneNote
is explicitly not implemented in this sprint.

### Proposed scope

- Implement one approved Microsoft Graph transport behind `OutlookTransport`.
- Centralize delegated authentication, token refresh/storage/revocation, HTTP
  execution, retry/throttling, rate limiting, pagination, delta recovery, and
  normalized errors in the shared Graph package.
- Use one delegated account, one disposable test folder, `Mail.Read`, and the
  minimal `User.Read` identity scope.
- Add the smallest additive repository capability for atomic cursor-only
  advancement when a delta round has no item or tombstone writes.
- Wire the live connector through the existing local SQLite ingestion and
  governed `retrieve()`/`answer()` path.
- Exercise initial sync, incremental sync, deletion/folder-move behavior,
  restart-safe no-change sync, and expired-delta recovery.
- Record sanitized live evidence: counts, timestamps, cursor outcomes, and
  citations, never tokens or raw mailbox content.

### Explicitly out of scope

- Shared mailboxes, app-only permissions, multi-folder aggregation, tenant
  administration, enterprise RBAC, background polling, and high availability.
- Attachment-byte ingestion, HTML/body policy expansion beyond the approved
  transport mapping, thread distillation, and LLM synthesis.
- Gmail, OneDrive, OneNote, and cross-provider abstractions not required by the
  existing connector contract.
- Production deployment or unattended credential refresh.

### Approval gates

| Gate | Decision | Status |
|------|----------|--------|
| Live account and folder | Explicit approval to connect to Lee's account and use a disposable test folder | ⬜ Required before connection |
| Authentication and token storage | Device-code delegated flow, account binding, OS Secret Service/default fail-closed policy, optional externally-keyed AES-GCM store, token-safe disclosure, and local revocation | ✅ Implemented; real account consent remains required |
| Runtime dependency / HTTP transport | Standard-library HTTPS transport and injected test transport; no new required Graph runtime dependency | ✅ Implemented offline; real endpoint proof remains required |
| Atomic no-op cursor advancement | Additive `Repository.advance_cursor()` capability with SQLite transaction, synchronized-project marker, and fail-closed provider default | ✅ Implemented offline |
| Expired delta recovery | Preserve last-known-good projection/cursor, then perform a complete reconciliation before advancing state | ✅ Implemented and tested offline |

### Acceptance criteria

- Authentication succeeds for the approved account without tokens in logs,
  cursors, receipts, or tracked evidence. Offline device flow, refresh,
  rotation, binding, and fail-closed storage tests pass; live account evidence
  remains an operator-run gate.
- Initial sync persists at least one known test message with normalized chunks,
  private permission facts, source locator, source timestamp, sync timestamp,
  and an atomically persisted cursor.
- A repeated initial/no-change round advances the delta cursor atomically and
  survives process restart without duplicating items.
- A controlled message create, edit, deletion, and move-out of the test folder
  produce the expected projection and journal outcomes; immutable IDs remain
  stable across edits and moves represented by deletion markers.
- An expired delta token is classified safely, leaves the last good projection
  and cursor intact on failed recovery, and advances only after successful full
  reconciliation.
- `retrieve()` and deterministic `answer()` return a known email answer with
  source citation, provenance, freshness, permission enforcement, and receipts.
- Offline tests cover Graph response/error mapping, throttling classification,
  token expiry/refresh/rotation/revocation, restart behavior, expired-delta
  recovery, and atomic repository failure; live evidence is recorded separately
  from the automated suite.
- An independent review finds no High/Critical issue and all repository checks
  remain green.

### Sprint 5 tasks

| ID | Task | Owner | Status | Done when |
|----|------|-------|--------|-----------|
| S5-01 | Graph auth, account, storage, and dependency decision | Builder + Human | ✅ Foundation implemented; live account approval pending | Account model, device flow, secure storage, disclosure policy, and exact transport boundary are recorded |
| S5-02 | Atomic cursor-only repository operation | Builder | ✅ Complete (offline) | `Repository.advance_cursor()` is additive, SQLite commits the empty-delta cursor and synchronized-project marker atomically, and rollback regression coverage passes |
| S5-03 | Shared Graph client and Outlook transport | Builder | ✅ Implemented offline; live smoke pending | Immutable-ID request, pagination, fetch, safe errors, throttling, rate limiting, auth binding, and health mapping are covered offline |
| S5-04 | Live initial and incremental sync | Builder | ⬜ Operator-gated | One approved folder syncs, restarts, updates, deletes, and reports provenance/freshness without duplicate rows |
| S5-05 | Expired-delta recovery | Builder + Reviewer | ✅ Implemented offline; live proof pending | Expired-token test and safe full-reconciliation path preserve the last good cursor until success |
| S5-06 | Governed email retrieval proof | Reviewer + Builder | ⬜ Operator-gated | `retrieve()`/`answer()` returns a cited, permission-checked known email answer with receipts |
| S5-07 | Independent review and live evidence | Reviewer | ✅ Conditional offline pass; live evidence pending | Dated review artifact, sanitized evidence, focused/full checks, and explicit residual risks are recorded |

### Future Microsoft connector assessments

- **OneDrive:** design-only readiness is recorded in `docs/microsoft-graph.md`;
  drive/folder identity, moves, permissions, Office content, and provider
  delta reconciliation need a separate connector slice.
- **OneNote:** no connector implementation, normalization code, or incremental
  path was added. Notebook/section/page identity, HTML/resources, permissions,
  and incremental semantics remain a later design task.

### S5-02 offline verification

- `python3 -m pytest tests/test_repository.py -q` — 8 passed.
- `python3 -m pytest tests/` — 368 passed.
- Black, Ruff, compileall, disclosure, diff, and CLI smoke checks remain clean;
  Ruff emits only the existing top-level-settings deprecation warning.

## Sprint 3 — Governed `answer()` Surface

### Sprint 3 status

| Field | Value |
|-------|-------|
| **Status** | 🟢 Delivered — contracts, evidence selection, absence/conflict identification, `answer()` assembly, the `lee-kb ask` CLI, 37 permanent regression fixtures across seven benchmark families, and full verification are complete; round-four repairs S3-R-17 through S3-R-21 are included; the LLM-backed synthesis provider and live filesystem verification of `ask` are explicit deferrals |
| **Start** | 2026-08-04 |
| **Primary owner** | Human + Builder agents (mixed crew: opus, codex, sonnet across steps) |

### Sprint 3 scope

#### In scope

- Define the `answer()` contracts: `Confidence`, `AbsenceKind`, `OmissionReason`, `Side`, `ReceiptId`, `EvidenceRef`, `OmittedEvidence`, `Claim`, `ConflictSide`, `Conflict`, `Absence`, `Answer`, `SynthesisProvider` (`src/lee_kb/answer_contracts.py`, `docs/answer-architecture.md`).
- Deterministic, source-diverse evidence selection over a governed `EvidenceBundle`, with every rejected item retained and reasoned (`src/lee_kb/answer_evidence.py`).
- Authoritative absence classification (`NOT_FOUND` / `INACCESSIBLE` / `UNKNOWN`) that never collapses the three states, including a cited evidenced-absence path (`src/lee_kb/answer_absence.py`).
- Pairwise conflict identification with positive disagreement signals, descriptive `newer`/`more_authoritative` signals, and no `winner` field (`src/lee_kb/answer_conflict.py`).
- `answer()` itself: plan (pass-through) → the unmodified `retrieve()` → selection → absence classification → claim assembly → conflict detection → confidence assignment → optional narration (`src/lee_kb/answer.py`).
- `DeterministicSynthesisProvider`: an offline, standard-library-only template renderer as the default `SynthesisProvider` — no LLM call.
- The `lee-kb ask` CLI command, fail-closed exactly like `search` (`src/lee_kb/main.py`).
- Permanent, offline regression fixtures for seven benchmark families against a synthetic corpus synced through the real connector and repository (`tests/answers/test_answer_benchmarks.py`), including a two-direction false-conflict/missed-contradiction guard.
- Full verification and a benchmark-results report (`docs/answer-benchmark-results.md`).

#### Out of scope (tracked, not abandoned)

- An LLM-backed `SynthesisProvider` implementation — blocked on the same runtime-dependency approval guardrail that gates office-format parsing. `SynthesisProvider` is the entire integration seam; adding one later touches no pipeline code.
- Live filesystem verification of `ask` over time (freshness drift, resync during use) — the benchmark suite runs against a temporary, synthetic SQLite projection, not a live corpus.
- Measuring `answer()` against the real Employee Zero corpus, the way `retrieve()` was in `evidence/real-corpus-parity-report.md`.
- The curated Chief-of-Staff golden benchmark for `answer()` — still does not exist, same as for `retrieve()`.
- Permission basis on receipts (Sprint 1 Open Question 2) and real query planning (`docs/answer-architecture.md`, Deferred Extensions) — neither changes `Answer`'s shape when added later.

### Sprint 3 tasks

| ID | Task | Owner | Status | Done when |
|----|------|-------|--------|-----------|
| S3-01 | Answer architecture and contracts | Builder (opus) | ✅ Complete | `docs/answer-architecture.md` and `src/lee_kb/answer_contracts.py`; `tests/test_answer_contracts.py` verifies construction-time invariants; `python3 -m pytest tests/` and `env PYTHONPATH=src python3 -c "from lee_kb import answer_contracts"` both exit 0 |
| S3-02 | Evidence selection and provenance | Builder (codex) | ✅ Complete | `src/lee_kb/answer_evidence.py`; `tests/test_answer_evidence.py`; `python3 -m pytest tests/` exit 0 |
| S3-03 | Authoritative absence and conflict identification | Builder (codex) | ✅ Complete | `src/lee_kb/answer_absence.py` and `src/lee_kb/answer_conflict.py`; `tests/test_answer_absence.py` and `tests/test_answer_conflict.py`; `python3 -m pytest tests/` exit 0 |
| S3-04 | `answer()` assembly, deterministic synthesis provider, and the `lee-kb ask` CLI | Builder (sonnet) | ✅ Complete | `src/lee_kb/answer.py`, `DeterministicSynthesisProvider`, and `cmd_ask` in `src/lee_kb/main.py`; `tests/test_answer.py`; `python3 -m pytest tests/` and `env PYTHONPATH=src python3 -m lee_kb.main ask --help` both exit 0 |
| S3-05 | Permanent regression fixtures for the seven benchmark families | Builder (codex) | ✅ Complete | `tests/answers/test_answer_benchmarks.py`; 37 collected items and `python3 -m pytest tests/` both exit 0 |
| S3-06 | Full verification, benchmark results, and project memory | Builder (sonnet) | ✅ Complete | `black --check`, `ruff check`, `compileall`, and `git diff --check` are clean over `src tests tools`; `docs/answer-benchmark-results.md` reports current per-family results, provenance/conflict examples, confidence distribution, and latency, with a `Ready after specific follow-up` recommendation; project memory is updated |

### Sprint 3 post-delivery repairs

| ID | Finding | Status | Evidence |
|----|---------|--------|----------|
| S3-R-17 | Non-value-word negation could merge a statement and its negation | ✅ Complete | Polarity-aware conflict and merge signals; detection-bypass regression |
| S3-R-18 | Same-authority ordinary substitutions could be missed | ✅ Complete | Canonical term-count substitution signal; proper-noun, weekday, and place regressions |
| S3-R-19 | Cross-authority agreement could be reported as conflict | ✅ Complete | Authority is descriptive only; same and cross-authority non-competing rate cases |
| S3-R-20 | Emphatic agreement could be reported as conflict | ✅ Complete | Exact de-negated value-set comparison; `required` / `not optional` regression |
| S3-R-21 | Benchmark documentation and one-direction measurement were incomplete | ✅ Complete | `docs/answer-benchmark-results.md`; two-direction rate guard |
| S3-R-04 | Claim-bearing answers did not disclose withheld or truncated evidence | ✅ Complete | `Answer.withheld_count` / `Answer.truncated`; permitted-plus-denied and top-k regressions |
| S3-R-05 | `lee-kb ask` could report `NOT_FOUND` for an unsynchronized project | ✅ Complete | Repository live-item preflight, provider-failure `UNKNOWN` fallback, CLI regression |

### Sprint 3 verification

- `python3 -m pytest tests/` — fresh final verification: 298 passed, including the missing-audit-capability regression.
- `python3 -m pytest tests/answers/test_answer_benchmarks.py -q` — fresh final-review follow-up verification: 37 passed.
- `env PYTHONPATH=src python3 -c "from lee_kb import answer_contracts"` and `env PYTHONPATH=src python3 -m lee_kb.main ask --help` — preserved system-validator evidence tied to S3-01 and S3-04 respectively, both exit 0.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools`, `python3 -m ruff check src tests tools`, `python3 -m compileall -q src tests tools`, `python3 tools/check_disclosure.py`, and `git diff --check` — run fresh in round four, all clean. Two formatting-only changes in `tests/test_cli.py` and `tests/test_local_connector.py` restore the current Black check; no behavior changed.

### Sprint 3 final-review follow-up

| Finding | Status | Evidence |
|---------|--------|----------|
| Public connector diffing could tombstone an inaccessible root | ✅ Repaired | `LocalFilesConnector.list_changes()` diffs a failure-aware discovery report; root-disappearance regression in `tests/test_local_connector.py` |
| Scoped overlapping-root accounting | ✅ Repaired | Root ownership semantics and `claimed_by_other_root` reporting; scoped-overlap regression in `tests/test_local_connector.py` |
| Deletion-only project absence state | ✅ Repaired | `has_synchronized_project()` and CLI deletion-only regression in `tests/test_cli.py` |
| Nested DOCX tables and Office false headings | ✅ Repaired | Recursive extraction and escaped body headings; `tests/test_office_ingestion.py` |
| Stale refusal receipts | ✅ Repaired | Freshness is evaluated before receipt persistence; `tests/test_governance.py` |
| Python compatibility floor | ✅ Repaired | Package and README target Python 3.11+, matching unconditional `tomllib` |
| Query-level audit event for empty/denied retrievals | ✅ Complete | Schema v2 persists empty, denied, mixed, stale-refused, and provider-failure events; v1 databases migrate additively; governance/repository regressions pass |

### Sprint 3 definition of done

- [x] `answer()` contracts are defined with construction-time provenance, disjointness, and absence invariants.
- [x] Evidence selection is deterministic, source-diverse, and accounts for every rejection.
- [x] Absence classification never collapses `NOT_FOUND` / `INACCESSIBLE` / `UNKNOWN`.
- [x] Conflict identification reports both sides with no winner.
- [x] `answer()` adds no permission logic of its own and calls the unmodified `retrieve()`.
- [x] `lee-kb ask` is implemented, fail-closed, and documented in `README.md`.
- [x] Permanent regression fixtures cover seven distinct benchmark families against a real connector/repository sync.
- [x] Full verification (`pytest`, `black --check`, `ruff check`, `compileall`, `git diff --check`) is green.
- [x] Benchmark results are recorded in `docs/answer-benchmark-results.md`, including a plain statement that the LLM-backed synthesis provider is specified but unimplemented (pending dependency approval) and that live filesystem verification of `ask` remains a deferred extension.

---

## Sprint 2 — Real-Corpus Parity & Post-Parity Repairs

### Sprint 2 status

| Field | Value |
|-------|-------|
| **Status** | 🟡 In progress — P1 (real-corpus parity measurement), the Office ingestion slice, and review-surfaced repairs S2-R-04, S2-R-03, and S1-R-16 are delivered and re-verified; the OR-matcher decision and curated golden benchmark remain open |
| **Start** | 2026-08-03 |
| **Primary owner** | Human + Builder agent |

### Sprint 2 scope

#### In scope

- Synchronize and query the real deployed `ai-employee-factory/knowledge/sources.toml` corpus (15 roots, ~1,200 documents) with the Sprint 1 delivery, and record findings (P1 — done; `evidence/real-corpus-parity-report.md`).
- Independent review of that measurement and the code it exercised (done; `code-reviews/review-sprint-2-p1-real-corpus.md`, verdict: pass).
- Repair the correctness and performance defects that review surfaced, scoped to what it found — not a general refactor.

#### Out of scope (tracked, not abandoned)

- Office-format (`.docx`/`.xlsx`/`.pptx`) failure/accounting follow-up beyond the delivered deterministic parser slice — unsupported embedded content remains explicitly classified rather than partially extracted; see `docs/office-ingestion.md`.
- The curated Chief-of-Staff golden benchmark — still does not exist. The generated 20-question corpus in `tests/golden/` proves the evaluation harness only; it is not a substitute.
- The OR-matcher fetch-to-exhaustion heuristic decision (Open Question 5 in `context.md`).
- The Outlook/Microsoft 365 email connector.

### Sprint 2 tasks

| ID | Task | Owner | Status | Done when |
|----|------|-------|--------|-----------|
| S2-P1 | Real-corpus parity measurement | Builder | ✅ Complete | `evidence/real-corpus-parity-report.md` records corpus shape, unindexed content, retrieval behavior, and a performance baseline against the real deployed corpus |
| S2-OFFICE | Office-format ingestion and deployed discovery parity | Builder | ✅ Complete | `python-docx==1.2.0`, `openpyxl==3.1.5`, and `python-pptx==1.0.2` are declared; handlers, narrow include changes, structured citations, failure accounting, focused tests, and a fresh real-corpus sync are complete (`docs/office-ingestion.md`) |
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
- [x] Office-format parsing dependencies are approved and the affected roots' `include` patterns are extended; all 39 live files are indexed or explicitly accounted for.
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
| **Completion** | All 7 sprint tasks complete for the scoped slice. Office formats (.docx/.xlsx/.pptx) and the curated golden benchmark were deferred from Sprint 1; Office formats were delivered in the subsequent Sprint 2 slice. |
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

1. **Office formats (.docx/.xlsx/.pptx) are required v1 product scope and deployed-reference parity requirements.** Their implementation was deferred from Sprint 1 pending dependency approval and was delivered in the subsequent Office slice on 2026-08-04; the review verified the contracts and format-handler registry without redesign.
2. **The generated twenty-question corpus proves the evaluation framework only.** It does not complete the curated golden benchmark until it includes Lee's real recurring Chief of Staff questions against the Employee Zero knowledge sources. The review and docs must not claim the golden benchmark is done.

Identity: reuse Agent Board identities through an adapter where appropriate, but lee-kb must not be runtime-dependent on Agent Board for the personal `lee` principal.

### Sprint 1 definition of done

- [x] The existing `knowledge/sources.toml` roots import and synchronize into the new projection. *(The initial 2026-08-03 parity run produced 1,213 live items / 12,699 chunks; the subsequent Office rollout produced 1,235 live items / 18,601 chunks and explicitly accounted for the 39-file Office inventory. See `evidence/real-corpus-parity-report.md` and `result-review.md`.)*
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
