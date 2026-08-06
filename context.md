# Lee Knowledge Base Session Context

> **Purpose:** Working memory for session continuity. Read this after
> `AGENTS.md` and before acting.

## Snapshot

| Attribute | Value |
|-----------|-------|
| **Phase** | Personal-first Second Brain foundation complete; Microsoft Graph foundation and live-capable Outlook path delivered; real mailbox proof pending |
| **Mode** | 2 (Collaborative implementation with approval) |
| **Last Updated** | 2026-08-05 |

### Sprint Status

| Sprint | Status | Completion |
|--------|--------|------------|
| Sprint 1 — Personal Foundation | 🟢 Delivered | 7/7 sprint tasks complete for the scoped slice; Office formats and the curated golden benchmark were deferred from Sprint 1 and tracked into later work |
| Sprint 2 — Real-Corpus Parity & Post-Parity Repairs | 🟡 In progress | Real-corpus parity and the Office ingestion slice are measured; Office dependencies, handlers, narrow deployed include changes, failure accounting, and real-corpus sync are complete; the OR-matcher decision and curated golden benchmark remain open |
| Sprint 3 — Governed `answer()` Surface | 🟢 Delivered, review repairs complete for the scoped slice | Contracts, evidence selection, absence/conflict identification, `answer()` assembly, the `lee-kb ask` CLI, permanent regression fixtures for 37 benchmark items across seven families, and S3-R-04/S3-R-05 repairs are complete and verified; S3-R-07/S3-R-09 remain advisory documentation findings; the LLM-backed synthesis provider and live filesystem verification of `ask` are explicit deferrals, not gaps |
| Sprint 4 — Personal Connector Foundation | 🟢 Bounded slice delivered; conditional offline review pass | BI-001 conformance coverage, capability matrix, and hardened offline BI-003 Outlook adapter are implemented |
| Sprint 5 — Microsoft Graph Foundation and Live Outlook Proof | 🟡 Shared foundation delivered; real account operator-gated | One real approved mailbox/folder remains to prove authentication, initial/incremental sync, expired-delta recovery, restart-safe no-change cursors, and governed email answers without enterprise scope |

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
first real-corpus performance and retrieval-quality baseline. An independent
review of that measurement (`code-reviews/review-sprint-2-p1-real-corpus.md`,
verdict `pass`) surfaced correctness and performance findings against the
code it exercised; three (S2-R-04 nested/overlapping-root correctness,
S2-R-03 single-discovery-pass performance, S1-R-16 golden-baseline-as-
contract) are now repaired and re-verified, and the corpus was re-measured
post-repair (see `evidence/real-corpus-parity-report.md`): sync wall-clock
dropped 46.6% (5:20.37 → 2:51.18) with corpus shape and chunk counts
unchanged. Full verification (`pytest`, `black --check`, `ruff check`) is
green. The Next Actions Queue below is re-ranked accordingly; Office dependency
approval and the affected-root `include` rollout are complete. The OR-matcher
decision and curated golden benchmark remain open, pending Lee.

The Office rollout is now implemented through the same local-file connector:
`python-docx==1.2.0`, `openpyxl==3.1.5`, and `python-pptx==1.0.2` are declared;
the six affected roots have narrow extension changes; structured citations,
safe failure classifications, duplicate-root behavior, and deletion/cursor
semantics remain common with Markdown. A final real-corpus projection indexed
10 Office files and explicitly accounted for the other 29 of the 39-file live
inventory. It contains 1,235 live documents and 18,601 chunks; five Office
files fail closed as unsupported and are retried without advancing cursors.
See `docs/office-ingestion.md` and the Office Rollout Measurement in
`evidence/real-corpus-parity-report.md`.

The first final cold review then found one public-contract deletion hazard and
several follow-ups. The builder follow-up now makes `LocalFilesConnector.list_changes()`
failure-aware, reports scoped nested-root ownership, preserves nested DOCX table
text, escapes Office body text that resembles headings, distinguishes
deletion-only projects from never-synced projects, prevents receipts on stale
refusals, and aligns the package floor with `tomllib` at Python 3.11+. Fresh
verification is 298 tests plus the benchmark and static checks. Schema v2 now
persists query-level audit events for empty, denied, mixed, stale-refused, and
provider-failure retrievals, with an additive v1 migration. The post-audit
review is a conditional pass with no High/Critical findings; repositories
without audit persistence now fail governed retrieval closed.

The bounded Outlook/Microsoft 365 slice remains implemented and independently
hardened behind an injected transport (`src/lee_kb/connectors/outlook.py`). The
shared Microsoft Graph foundation now lives in `src/lee_kb/microsoft_graph/`:
device-code authentication, token refresh/rotation/revocation, credential
binding, OS-protected or explicit encrypted storage, authenticated HTTP,
retry/throttling/rate limiting, generic pagination, normalized errors, and
expired-delta restart. `GraphOutlookTransport` maps that client to the same
one-folder Outlook adapter; `_sync_external_connector` uses atomic item,
tombstone, and cursor-only repository operations. No real account has been
connected by automated tests. See `docs/microsoft-graph.md` and
`docs/outlook-connector.md`.

OneDrive is a readiness assessment only. OneNote remains explicitly
unimplemented and is not shaping the Graph layer.

### Recently Completed

- ✅ Microsoft Graph follow-up hardening: verified subject/tenant identity is
  retained with tokens and rechecked after refresh, Graph-backed Outlook scopes
  and cursor IDs are bound to the credential, unsafe URL fragments are rejected,
  identity/token requests share pacing and retries, non-idempotent 401s are not
  replayed, and empty-project synchronization state is recorded atomically.
  Offline verification is green at 368 tests; real account proof remains
  operator-gated.
- ✅ Microsoft Graph foundation: `src/lee_kb/microsoft_graph/` provides account
  credentials, device-code auth, refresh/rotation/revocation, secure token
  stores, sanitized Graph errors, retry/throttling/rate limiting, pagination,
  delta-expiry recovery, and the injectable HTTP boundary.
- ✅ Live-capable Outlook mapping and sync wiring: `GraphOutlookTransport` and
  the common external sync path preserve immutable IDs, provenance,
  permissions, citations, freshness, audit flow, and atomic checkpoints. The
  real account proof is still operator-gated.
- ✅ OneDrive and OneNote readiness assessments are recorded in
  `docs/microsoft-graph.md`; no OneNote implementation was added.

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
- ✅ S1-06: Golden evaluation harness (`tests/golden/`, `docs/golden-baseline.md`) runs a 20-question generated corpus plus 3 negative controls and records a lexical baseline over paraphrase questions (80.0% hit-at-1, 100% hit-at-10, 0.888 MRR after reconciling the generated project-plan seed). Proves the harness, not the curated Chief-of-Staff benchmark.
- ✅ Independent review PASSED (verdict gate clean): three High findings (S1-R-01 ungoverned retrieve, S1-R-10 connector containment/resilience, S1-R-11 AND-matcher baseline inflation) were found, repaired, and re-verified across three review cycles; 11 advisory findings (5 Medium, 6 Low) remain in `code-reviews/review-sprint-1-personal-foundation.md` as follow-on candidates.
- ✅ S1-07: `lee-kb init`/`sync`/`search` CLI (`src/lee_kb/main.py`) implemented and exercised end to end; the initial delivery's 109-test suite passed (the current suite is 298 tests); `black --check` and `ruff check` pass on `src` and `tests`.
- ✅ Real-corpus parity measurement: the historical pre-Office `lee-kb sync`/`search` run against the deployed `ai-employee-factory/knowledge/sources.toml` (15 roots, ~1,200 documents) is recorded in `evidence/real-corpus-parity-report.md`; it measured 1,213 live items / 12,699 chunks and sized the 39-file Office gap. The subsequent Office rollout resolved that deferral and is recorded below.
- ✅ This step: full verification re-confirmed green (`black --check` and `ruff check` run clean with no fixes needed; `pytest tests/` and `sync --help` reconfirmed via preserved validator evidence from this run, not rerun). `README.md` updated to document the previously-undocumented `--workspace-root` and `--database` flags on `lee-kb sync`.
- ✅ Independent review of the real-corpus parity slice (`code-reviews/review-sprint-2-p1-real-corpus.md`, verdict `pass`) found no Critical or High finding; three findings from it are now repaired (below).
- ✅ S2-R-04 (nested/overlapping-root correctness): `LocalFilesConnector` now claims each overlapping file with exactly one root — the deepest matching resolved root, ties broken by root name (`_claiming_root`, `_find_nested_roots` in `src/lee_kb/connectors/local_files.py`); `health()` reports detected nested-root pairs; a parent-repository ignore rule that would otherwise suppress an entire configured root is now surfaced as unresolved rather than silently dropping the root. Regression tests added to `tests/test_local_connector.py`.
- ✅ S2-R-03 (single discovery pass per sync): `_sync_connector` (`src/lee_kb/main.py`) now calls `connector.discover_report()` once and derives its change list from that report, instead of running a full discovery-and-hash pass twice per sync. Re-measured on the real corpus: wall-clock 5:20.37 → 2:51.18 (−46.6%), user time −47.8%, peak RSS unchanged within noise (−0.4%); document/chunk totals unchanged (1,213 / 12,699). See `evidence/real-corpus-parity-report.md` Performance.
- ✅ S1-R-16 (golden baseline enforced as a contract): `tests/golden/test_golden_corpus.py::test_recorded_baseline_metrics_are_enforced_by_the_harness` computes hit-at-1/hit-at-10/MRR through the governed `retrieve()` surface and fails (tolerance 0.01, symmetric) if they drift from the recorded gate in `docs/golden-baseline.md` in either direction.
- ✅ This step: full verification driven green. `pytest` was not rerun (validator rerun not permitted for this step; see `result-review.md` for the four preserved validator records this reports from, all exit 0, tied to S2-R-04, S2-R-03, S1-R-16, and the post-repair real-corpus re-measurement). `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` and `python3 -m ruff check src tests tools` were run fresh: both initially failed (2 files needed `black` reformatting; a resulting `ruff` line-length finding was fixed by hand); both are clean as of this step, no behavioral change.
- ✅ Sprint 3 (governed `answer()` surface): `docs/answer-architecture.md` locks the design; `src/lee_kb/answer_contracts.py` defines `Confidence`, `AbsenceKind`, `OmissionReason`, `Claim`, `Conflict`, `Absence`, `Answer`, and `SynthesisProvider` with construction-time provenance, disjointness, and absence invariants; `src/lee_kb/answer_evidence.py` selects source-diverse evidence with every rejection reasoned; `src/lee_kb/answer_absence.py` classifies `NOT_FOUND`/`INACCESSIBLE`/`UNKNOWN` without collapsing them, including a cited evidenced-absence path; `src/lee_kb/answer_conflict.py` detects pairwise conflicts with `newer`/`more_authoritative` signals and no winner; `src/lee_kb/answer.py` assembles `answer()` strictly on top of the unmodified `retrieve()`, with `DeterministicSynthesisProvider` as the offline, standard-library-only default narrator; `lee-kb ask` (`src/lee_kb/main.py`) is the CLI surface.
- ✅ `tests/answers/test_answer_benchmarks.py` is a permanent, offline regression suite for seven benchmark families (cross-repository claim assembly, fuzzy matching, cross-repository attribution breadth, authoritative evidenced absence, conflict identification without a winner, duplicate-source suppression, and end-to-end provenance/receipt closure), synced through the real connector and repository against a synthetic corpus — 37/37 collected items pass. Results, concrete provenance/conflict examples, confidence distribution, and latency observations are recorded in `docs/answer-benchmark-results.md`; recommendation: **Ready after specific follow-up**.
- ✅ This step: full verification driven green (`black --check`, `ruff check`, `compileall`, and `git diff --check` all run fresh and clean over `src tests tools`; `pytest` not rerun — validator rerun not permitted for this step; see `result-review.md` for the nine preserved validator records this reports from). Two pre-existing, unrelated issues were fixed to get there: `tests/test_local_connector.py` had drifted out of `black` formatting, and a stray gitignored `tests/._test_bootstrap_cli.py` macOS metadata file broke `compileall` and was removed. `README.md` now documents `lee-kb ask`.
- ✅ Repair of the three High findings from the Sprint 3 review
  (`code-reviews/review-sprint-3-governed-answer.md`, verdict `fail`):
  **S3-R-01** (same-authority contradictions merged into one
  self-contradictory `SYNTHESIZED` claim with no conflict shown) —
  `_conflict_signal` now also fires on value-word divergence between
  same-subject statements, and claim assembly refuses to merge evidence whose
  value words diverge; **S3-R-02** (an unrelated absence-shaped sentence
  could short-circuit a responsive, evidenced answer) — the evidenced-absence
  path now runs only over already-selected evidence and requires the
  matched sentence to clear the same relevance threshold and be top-ranked;
  **S3-R-03** (a merged claim split by one conflicting pair could be
  resurrected by a later pair, double-citing chunks) — `detect_conflicts` now
  updates its evidence-to-claim map transitively the moment a merge is split.
  Each fix ships with its own permanent regression fixture in
  `tests/answers/test_answer_benchmarks.py` (now 15 collected items, up from
  12). Full suite: 241 passed (preserved validator evidence, two independent
  runs, both exit 0); `black --check`, `ruff check`, `compileall`, and `git
  diff --check` all re-driven fresh and clean, no repairs needed.
  `docs/answer-benchmark-results.md` rewritten to reflect the repaired
  behavior, including a corrected Confidence Distribution (S3-R-06 fixed as a
  byproduct) and a new same-authority Conflict Example. The review's five
  Medium/Low findings (S3-R-04, S3-R-05, S3-R-07, S3-R-08, S3-R-09) are
  **not** addressed by this step and remain open — see Next Actions Queue.
- ✅ Round-two repair of the governed `answer()` surface
  (`code-reviews/review-sprint-3-repair.md`, verdict `fail`): a follow-up
  review proved round one's fixes were shape-specific. **S3-R-10** (a
  contradiction phrased outside the closed 14-word value-word vocabulary —
  `"enabled"`/`"turned off"`, `"permitted"`/`"forbidden"`, or a purely
  numeric divergence — still merged into one self-contradictory
  `SYNTHESIZED` claim with zero conflicts) — the merge rule in
  `_assemble_initial_claims` is now inverted to merge only on demonstrated
  term-equivalence (`_statements_mergeable`) rather than refusing merge only
  on a known antonym, and `_conflict_signal` gained an explicit
  numeric-divergence signal. **S3-R-11** (a top-ranked, relevant
  evidenced-absence statement still replaced the whole answer instead of
  joining it) — `answer()` now assembles the evidenced-absence claim as an
  **additional** claim in rank order rather than a replacement, and the
  top-rank requirement in `classify_absence` was removed as no longer
  needed. Each fix ships with its own permanent regression fixture (a
  3-case parametrized out-of-vocabulary/numeric test for S3-R-10, one
  additive-absence test for S3-R-11), bringing
  `tests/answers/test_answer_benchmarks.py` to 19 collected items, up from
  15. Full suite: 245 passed (preserved validator evidence, two independent
  runs, both exit 0); `black --check`, `ruff check`, `compileall`,
  `tools/check_disclosure.py`, and `git diff --check` all re-driven fresh and
  clean, no repairs needed. `docs/answer-benchmark-results.md` rewritten
  again: the harbor-readiness question's confidence distribution genuinely
  changed (its two statements no longer merge, so the corpus now yields 11
  `DIRECTLY_EVIDENCED` claims and 0 `SYNTHESIZED` across family 7, not 9+1),
  and a new Conflict Example uses the numeric-divergence fixture — the case
  the round-one document could not demonstrate. One correctness-adjacent
  finding from the same review, **S3-R-12** (Medium: `_conflict_signal` can
  report a spurious `Conflict` between non-competing statements, e.g. two
  sources that agree but one adds information), is confirmed still open and
  was out of this round's declared scope. The review's own S3-R-13
  (documentation-accuracy) and S3-R-14 (disclosure, an absolute host path in
  a test fixture) findings are already repaired — S3-R-14 before this step,
  S3-R-13 by this step's rewrite qualifying each fixture's guarantee to the
  shape actually proven. The five earlier Medium/Low findings (S3-R-04,
  S3-R-05, S3-R-07, S3-R-08, S3-R-09) remain open, unchanged — see Next
  Actions Queue.
- ✅ Round-three repair of the governed `answer()` surface
  (`code-reviews/review-sprint-3-repair-2.md`, verdict `fail`): a further
  independent re-review found that round two's fix carried an unmentioned
  side effect. **S3-R-15** (High: an undiscriminating branch in
  `_conflict_signal` reported a `Conflict` whenever two same-topic
  statements' meaningful terms differed above a similarity floor, with no
  test that the difference was an actual disagreement — measured at 5 of 6
  constructed agreeing pairs flagged, including the project's own
  harbor-readiness fixture) — that branch is removed and replaced with two
  positive-evidence signals: a morphological-antonym check
  (`_morphological_antonyms_diverge`, recognizing `dis-`/`non-`/`un-` antonym
  pairs such as `restricted`/`unrestricted`) and a superset/elaboration rule
  applied to both value words and meaningful terms, so a statement that only
  adds information is treated as elaboration, not disagreement, in both
  `_value_words_diverge` and `_statements_mergeable`. Two new regression
  families were added: `test_non_competing_statement_pairs_produce_no_conflicts`
  (6 agreeing-pair cases) and two new cases in the renamed
  `test_contradicting_statement_pairs_produce_one_conflict_with_cited_sides`,
  bringing `tests/answers/test_answer_benchmarks.py` to 27 collected items, up
  from 19. **S3-R-12** (Medium, the pre-existing narrower instance of the
  same defect) is closed by the same superset rule. **S3-R-16** (Medium,
  documentation accuracy: the round-two benchmark document did not name the
  undiscriminating branch or report its effect on the harbor-readiness
  question's conflict count) is corrected by this step's rewrite of
  `docs/answer-benchmark-results.md`. Full suite: 253 passed (preserved
  validator evidence, two independent runs, both exit 0); `black --check`,
  `ruff check`, `compileall`, `tools/check_disclosure.py`, and `git diff
  --check` all re-driven fresh and clean, no repairs needed.
  `docs/answer-benchmark-results.md` rewritten again: the Confidence
  Distribution now states the family-7 conflict-count change explicitly (the
  spurious harbor-readiness conflict is gone; 1 conflict total, not 2), and
  two new Conflict Examples entries were added — a same-authority
  morphological-antonym contradiction (the shape the previous document could
  not demonstrate) and a non-conflict elaboration regression demonstrating
  the fixed false positive directly. The remaining advisory findings are
  S3-R-07, S3-R-08, and S3-R-09 — see Next Actions Queue.

- ✅ Round-four repair of the governed `answer()` conflict heuristics
  (`code-reviews/review-sprint-3-repair-3.md`, verdict `fail`): S3-R-17 and
  S3-R-18 (High) plus S3-R-19, S3-R-20, and S3-R-21 (Medium) are repaired.
  Negation is polarity-aware, ordinary substitutions use inflection-normalized
  term counts, authority only describes a positive disagreement, and value
  words require an opposition rather than set inequality. Permanent coverage
  now has 35 collected benchmark items: 14 non-competing cases across same and
  cross authority, 10 contradiction cases, a detection-bypass merge-refusal
  case, and a two-direction rate guard. Full verification is green at 261
  tests; the LLM-backed provider remains unimplemented and no model client was
  added.

- ✅ Office ingestion and deterministic answer hardening: the approved Office
  dependencies are declared and registered; DOCX headings/paragraphs/tables,
  XLSX workbook/sheet/row/cell/formula data, and PPTX slide/body/table/speaker
  notes are normalized through the common chunk, repository, retrieval, and
  citation path. Encrypted, malformed, unreadable, temporarily inaccessible,
  and unsupported embedded content fail closed without raw paths or source
  content in error evidence. `Answer` now reports `withheld_count` and
  `truncated`; `cmd_ask` passes live-project sync state and explicitly returns
   `UNKNOWN` on provider failure without fallback. Focused Office and answer
   regressions pass; the real-corpus rollout is recorded in
   `evidence/real-corpus-parity-report.md`.
- ✅ Final-review follow-up repairs: public connector change diffing now
  protects failed roots/subtrees, scoped overlapping-root discovery reports
  child ownership, deletion-only `ask` reports `NOT_FOUND`, nested DOCX tables
  retain text, Office body headings cannot create false citation sections,
  stale refusals leave no release receipts, and the declared Python floor is
  Python 3.11+. The pre-BI-001 suite was 298 tests; schema v2 now persists the
  query-level empty/denied audit event and migrates v1 projections additively.

### In Progress

- Sprint 1, Sprint 2's P1 and Office slices, and Sprint 3 are delivered for
  their scoped work. The remaining product decisions are the OR-matcher
  tradeoff and the curated golden benchmark; the LLM provider and live `ask`
  verification remain explicit deferrals.
- `BI-001` is implemented as a bounded, local-only slice: the conformance suite
  exercises the existing connector boundary and
  `docs/connector-capability-matrix.md` records provider evidence and unknowns.
  The generated golden seed is reconciled and its offline baseline is enforced.
  The bounded Outlook adapter is implemented separately; the current release
  has a live-capable Graph transport and external authentication flow, but no
  live account connection or operator evidence.
- Sprint 5 planning is bounded to one real mailbox proof. Its live account,
  authentication/token storage, and transport dependency gates remain open;
  S5-02 now implements atomic cursor-only advancement as an additive repository
  capability with SQLite rollback coverage.

### BI-003 Bounded Slice

- ✅ `src/lee_kb/connectors/outlook.py` implements the shared connector contract
  over `OutlookTransport`, including one-folder discovery, paginated delta
  changes, immutable message IDs, normalized email text, relationships,
  private owner permissions, freshness, health, refresh, and metadata-only
  cursors.
- ✅ `tests/test_outlook_connector.py` covers quoted-history and attachment
  deduplication, created/updated/deleted messages, ordered and repeated delta
  reads, folder moves, fetch and locator drift, checkpoint safety, citations,
  and denied retrieval (18 focused cases).
- ✅ `docs/outlook-connector.md` and the capability matrix record the locked
  offline decisions, safe error behavior, and the remaining live-integration
  questions.
- ✅ Independent review hardening is complete with a conditional offline pass
  and no High/Critical finding. Relationship persistence and richer live
  body/attachment semantics remain explicitly gated or deferred.
- ✅ S5-02 atomic cursor-only repository advancement: `Repository.advance_cursor()`
  is a fail-closed additive capability; `SQLiteRepository` persists empty-delta
  cursors transactionally and regression coverage proves rollback preserves the
  prior cursor.

### BI-001 Completion Note

- ✅ `BI-001`: `tests/test_connector_conformance.py` covers connector identity,
  configured scope, discovery, snapshot changes, repeated no-change sync,
  fetch, permissions, freshness, health, relationships, refresh, deletion,
  and temporary-failure checkpoint behavior. The existing discovery-failure
  regression now also asserts that the repository cursor is unchanged.
   `docs/connector-capability-matrix.md` compares local directories, selected
   OneDrive folders, Outlook/Microsoft 365 mail, Gmail, and OneNote using
   official provider documentation where available. The bounded offline Outlook
   adapter is documented separately; no live Graph connection or authentication
   flow was added. Focused conformance, Outlook, and full-tree coverage pass.

### Recently Decided (2026-08-03 architecture review)

- ✅ Architecture review completed: identity, journal, deletion, migration, retrieve() contract, surfaces, sync, config, evaluation, and projects all locked (see Decisions Locked).
- ✅ Connector expansion direction recorded 2026-08-05: local project
  directories, selected OneDrive folders, Outlook/Microsoft 365, OneNote, and
  Gmail; email remains the first external connector family candidate.
- ✅ BI-001 evidence-backed recommendation recorded 2026-08-05:
  Outlook/Microsoft 365 mail is the recommended first external connector
  experiment because Graph documents per-folder delta, deletion markers,
  immutable message IDs, message timestamps, and read permissions.
- ✅ BI-003 bounded offline design recorded 2026-08-05: one delegated `/me`
  folder, `Mail.Read` plus minimal `User.Read`, immutable IDs, metadata-only per-folder cursors,
  deterministic text normalization, private owner permissions, and explicit
  relationship IDs. Review hardening adds new connector/mailbox cursor binding,
  locator/freshness fingerprints, and failed-fetch checkpoint protection. Live
  Graph transport and token handling remain gated.
- ✅ Sprint 5 live Outlook proof bounded 2026-08-05: one approved mailbox and
  disposable folder, initial/incremental sync, expired-delta recovery,
  restart-safe no-change cursor advancement, and governed email provenance;
  enterprise features and live auth remain approval gates.
- ✅ Derived artifacts, ranking signals, retrieval surfaces, and projects added to `architecture.md` and `product-definition.md`.
- ✅ v1 reframed as a reimplementation of the Employee Zero knowledge system (~1,200 documents, 15 source roots) with the parity acceptance criterion: the Chief of Staff switches off the old `kb` commands without losing capability.
- ✅ Identity consumed from the Agent Board model; principal required on every retrieval; fail-closed.
- ✅ Product direction reframed 2026-08-05: personal-first governed Second
  Brain, small-group capable, and not enterprise-first; connector expansion is
  the next product phase.

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
| Stored schema version + migration framework; additive migrations are used when possible and wipe-and-resync remains the fallback | The projection is disposable; sources are authoritative | 2026-08-03 |
| retrieve() contract: query, principal, top_k, filters, freshness, project | Filters are simple equality/range on connector, project, date, type, tags — no query language | 2026-08-03 |
| Library is the product; CLI is the v1 surface; MCP server is Phase 2 | All surfaces exercise the same public retrieval API | 2026-08-03 |
| Sync is user-driven (`lee-kb sync [...]`); daemons and watchers deferred | Freshness reporting makes staleness visible instead | 2026-08-03 |
| Configuration is a public contract at `~/.config/lee-kb/config.toml` | Client deployments will depend on it; documented from day one | 2026-08-03 |
| Golden evaluation corpus (~20 real questions) is a Sprint 1 deliverable | Semantic retrieval must measurably beat the lexical baseline before adoption | 2026-08-03 |
| project field is required on every knowledge item; v1 uses `default` | Forces the tenancy/scoping boundary into the data model from day one at near-zero cost | 2026-08-03 |
| Personal connector expansion is source-driven, not enterprise-driven | Local project directories, selected OneDrive folders, Outlook/Microsoft 365, OneNote, and Gmail are candidate sources; each must pass the common connector and governance boundary | 2026-08-05 |
| Email provider order: Outlook/Microsoft 365 first, Gmail as early follow-on | Email exercises conversational knowledge, threading, and distillation; provider-specific APIs remain behind one normalized email model | 2026-08-03 |
| v1 is a reimplementation of the Employee Zero knowledge system, not a greenfield product | Preserve the `knowledge/sources.toml` source roots and rebuild the projection; the old `.kb/index.sqlite` is not authoritative | 2026-08-03 |
| v1 file formats: Markdown, plain text, .docx, .xlsx, .pptx | Support the formats the deployed Chief of Staff workflow actually uses | 2026-08-03 |
| Identity reuses the Agent Board model; retrieval always requires a principal | One identity system for humans, machine identities, and AI employees; CLI defaults to Lee; evaluation is fail-closed | 2026-08-03 |
| Golden corpus = ~20 real Chief of Staff questions plus negative cases | Measures correct evidence, citations, project scoping, and freshness — not plausible-looking text | 2026-08-03 |
| v1 complete = the Chief of Staff can switch from the old `kb` commands to lee-kb without losing capability | Objective acceptance criterion; prevents drift into architecture astronautics | 2026-08-03 |
| Identity-provider independence: Agent Board identities reused via adapter; the personal `lee` principal never requires Agent Board at runtime | Governance compatibility without a hard runtime dependency for personal deployments | 2026-08-03 |
| Office formats were deferred implementation, not deferred contract | .docx/.xlsx/.pptx stayed required v1 scope and parity requirements; approved deterministic handlers were delivered without redesign on 2026-08-04 | 2026-08-03 / 2026-08-04 |
| Generated corpus proves the evaluation framework only | The curated golden benchmark completes only with Lee's real Chief of Staff questions against Employee Zero sources | 2026-08-03 |
| Office parsers remain behind the local-file handler registry | Structured text, safe metadata, and stable section references use the common ingestion/retrieval path; unsupported package content fails closed instead of being partially indexed | 2026-08-04 |
| Office discovery is narrow and explicit | Only six affected roots gain exact Office extension patterns; out-of-scope, excluded, ignored, and parser-failure counts remain visible | 2026-08-04 |
| `Answer` reports aggregate withheld and truncation signals | Permission denial and top-k limits remain visible without exposing restricted source identity, including on claim-bearing answers | 2026-08-04 |
| Personal-first Second Brain with small-group forward compatibility | Keeps the current release useful and local while preserving explicit principal, project, connector, provenance, and access boundaries for later shared work; enterprise administration is not an active goal | 2026-08-05 |
| Outlook BI-003 stays offline behind an injected transport | Proves normalized email, delta, permission, provenance, freshness, and failure semantics without credentials or a live external connection; Graph HTTP and OAuth remain separate approval work | 2026-08-05 |
| Outlook Graph cursors bind checkpoints to connector, account, tenant, and credential scope | Prevents cross-scope reuse for newly emitted cursors; version-1 cursors are rejected before live use and Graph connector IDs are derived from the binding | 2026-08-05 |
| Sprint 5 uses an additive atomic cursor-only repository operation | Empty delta rounds advance state without fabricating an item or weakening item/tombstone transactions; providers without the capability fail closed | 2026-08-05 |

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
| `docs/connector-capability-matrix.md` | BI-001 provider evidence plus BI-003 capability and live-integration questions | ✅ Available |
| `docs/outlook-connector.md` | BI-003 bounded offline design and verification contract | ✅ Available |
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
2. Which parsing libraries are approved for .docx/.xlsx/.pptx? **Resolved 2026-08-04**: the bundled capability uses `python-docx==1.2.0`, `openpyxl==3.1.5`, and `python-pptx==1.0.2`; handlers and narrow include changes are deployed. The 39-file live inventory is explicitly accounted for in `docs/office-ingestion.md`; 10 are indexed and the remaining 29 are classified as unsupported, ignored, excluded, or outside deliberate root scope.
3. Where does the Agent Board identity model live today, and what does lee-kb consume — a library, a service, or a shared schema? (Not blocking for the personal `lee` principal, which runs with no Agent Board dependency; relevant once a second principal or consumer needs identity.)
4. ~~Does this checkout have access to the real `knowledge/sources.toml`...~~ **Resolved 2026-08-03**: yes. All 15 configured roots resolved to real, present directories; a full clean sync produced 1,213 live items / 12,699 chunks, closely tracking the `research/employee-zero-kb-reference.md` snapshot (1,209 documents / 12,634 chunks). See `evidence/real-corpus-parity-report.md`.
5. Is the OR-matcher's measured worst case (~1.521s for a single ubiquitous token, on the prior ~1,213-document corpus) acceptable as-is, or does it need a page-size cap / early-exit heuristic at the current 1,235-document / 18,601-chunk scale? Still open: Office rollout measured sync performance, not a new retrieval stress baseline. `answer()` inherits this unresolved question unchanged, since it calls `retrieve()` directly. (See `evidence/real-corpus-parity-report.md` Performance and Recommended Next Actions.)
6. Which model client is approved for the LLM-backed `SynthesisProvider`? **Still open**: `docs/openai-synthesis-decision.md` prepares the official OpenAI Responses client, model, route, source-bounded prompt, telemetry, and deterministic test-double decision, but no model dependency has been approved. `lee-kb ask` remains deterministic and offline.
7. What would it take to measure `answer()` against the real Employee Zero corpus, the way `retrieve()` was in `evidence/real-corpus-parity-report.md`? `docs/answer-benchmark-results.md` benchmarks `answer()` only against synthetic fixture corpora (a twelve-document primary corpus, a two-document same-authority corpus, and isolated per-case corpora); latency, claim-assembly behavior, and conflict/absence rates at real corpus scale (~1,235 documents) are unmeasured.
8. BI-003's normalized decisions and the shared Graph foundation are resolved:
     delegated `/me` with `Mail.Read` plus minimal `User.Read`, one folder per connector, immutable
    message IDs, private owner permission facts, deterministic text
    normalization, explicit relationships, secure token lifecycle, shared
    retries/throttling/pagination, and metadata-only delta cursors. The real
     account/client/folder approval, live consent, attachment-body parsing, and
     relationship persistence through the common repository remain out of this
    proof. Atomic no-op cursor advancement and live sync wiring are implemented
    offline. OneDrive is a future connector; OneNote remains unimplemented.

## Next Actions Queue

Re-ranked 2026-08-05 after the personal-first Second Brain reframing.
S3-R-04/S3-R-05,
the public connector deletion hazard, scoped-root accounting, deletion-only
absence semantics, Office edge cases, stale-refusal receipts, and S1-R-15 are
implemented and regression-tested. S1-R-12 is implemented through schema v2
and an additive v1 migration; the post-audit review found no High/Critical
findings, and missing audit capability now fails closed. S3-R-07/S3-R-09 and
S1-R-17 remain advisory. See
`result-review.md`, `docs/answer-benchmark-results.md`, and
`docs/office-ingestion.md`.

| Rank | Action | Owner | Done When |
|------|--------|-------|-----------|
| 1 | Approve and execute the Sprint 5 live Outlook proof | Human + Planner + Builder | Public client/account/folder consent is approved; initial/incremental sync, atomic no-op cursors, expired-delta recovery, governed email answers, and sanitized live evidence pass review |
| 2 | Decide whether the OR-matcher's ~1.5s common-token retrieval worst case needs a page-size cap or early exit at the expanded corpus scale | Human + Builder | Decision recorded and, if needed, implemented and re-measured |
| 3 | Curate the real golden benchmark from Lee's recurring Chief of Staff questions and run it through both `retrieve()` and `answer()` | Human + Builder | `docs/golden-baseline.md` and `docs/answer-benchmark-results.md` report results against the curated corpus |
| 4 | Approve the OpenAI client/model/route and implement the source-bounded `SynthesisProvider` package | Human approval + Builder | `docs/openai-synthesis-decision.md` approved; exact dependency/model/route recorded; provider reviewed without weakening deterministic offline behavior |
| 5 | File the Agent-Orch defect: continuation runs record `launch: null`, making crashed continuations unresumable | Human + Platform | Backlog item exists in agent-orch with the OS1-contract reference |
| 6 | Resolve Open Question 1 (Employee Zero parity scope for live mission status and dossier validation) | Human + Planner | Parity scope decision recorded in `architecture.md` or `product-definition.md` |

Also open, advisory (not ranked — lower severity): S2-R-05 through S2-R-11 in
`code-reviews/review-sprint-2-p1-real-corpus.md` (docstring/partition-accuracy
fixes, two narrative-count corrections in the evidence report, a
commit-message traceability gap, a stale test-count reference, a `ruff`
 config deprecation, and two missing regression tests); and S3-R-07, S3-R-09
 in `code-reviews/review-sprint-3-governed-answer.md` (Provenance Examples
 quote reformatted claim text and undercount claims, and
 `OUTSIDE_REQUESTED_PROJECT` omissions collapse to `NOT_RELEVANT` for
 readers). S3-R-06 (the Confidence Distribution
double-count) was corrected as a byproduct of rewriting
`docs/answer-benchmark-results.md` after round one and is no longer open.
S3-R-13 (`code-reviews/review-sprint-3-repair.md`: the round-one benchmark
document overclaimed completeness) is corrected as a byproduct of this
step's rewrite and is no longer open. S3-R-14 (an absolute host path in
`tests/test_contracts.py`) was repaired before this step, together with
`tools/check_disclosure.py`, and is no longer open. S3-R-12 (spurious
conflicts between non-competing statements) and S3-R-15 (High: the same
defect, widened by round two's own fix to fire on mere textual difference)
from `code-reviews/review-sprint-3-repair-2.md` are repaired by the
round-three fix and are no longer open; S3-R-16 (documentation accuracy: the
round-two document did not name the branch causing S3-R-15 or its effect on
the harbor-readiness conflict count) is corrected as a byproduct of this
step's rewrite and is no longer open.

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

- **Working Directory:** a local checkout of this repository (path intentionally
  not recorded — this repository is public; see S2-R-01, S2-R-02, S2-R-12)
- **Project Name:** `lee-kb`
- **Profile:** Python package / governed retrieval service
- **Author:** Lee Harrington
- **Public Repository:** `https://github.com/leebase/lee-kb`

*This file is living project memory; keep it factual and current.*
