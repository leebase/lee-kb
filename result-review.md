# Lee Knowledge Base Result Review

> **Running log of completed work.** Newest entries are at the top. Each entry
> records what changed, why it matters, and how to verify it.

## 2026-08-05 - Project review and next-step recommendation

### What Was Reviewed

The current project state, active Sprint 5 plan, Microsoft Graph/Outlook
implementation, repository and governance boundaries, latest independent review,
and strategic project memory were reviewed. No Microsoft account, OAuth consent,
mailbox, provider response, or external network request was used.

### Result

The offline implementation remains green: 368 tests pass, Black, Ruff,
compileall, disclosure, diff, and CLI smoke checks pass, and the latest Graph
follow-up remains a conditional offline pass with no High, Critical, or Medium
implementation finding. The next bounded product step is the operator-gated
live Outlook proof, not another connector feature.

Three project-level follow-ups were recorded in
`code-reviews/review-project-next-step-2026-08-05.md`: freeze the currently dirty
worktree before external execution, reconcile the stale Phase 2/connector status
in `project-plan.md`, and clarify that relationship persistence is deferred or
requires a separate schema decision. The live proof remains blocked until the
human operator approves the client, account, consent, and disposable folder.

## 2026-08-05 — Sprint 5 Graph follow-up hardening and conditional offline pass

### What Was Built

The Microsoft Graph/Outlook slice was hardened after the initial independent
review. OAuth grants remain transient until Graph client identity verification;
verified subject and JWT tenant claims are retained and rechecked after token
refresh. Raw device authentication, token loading, and unverified access are
private implementation paths. Graph HTTP disables redirects, restricts the
HTTPS port and security headers, bounds response/delta work, paces identity and
resource requests, and avoids ambiguous refresh-token replay. Outlook locators,
scope/cursor identity, project boundaries, attachment metadata, and one-401
replay are fail-closed. Prepared external item/tombstone rounds now commit with
their cursor in one SQLite transaction; empty rounds atomically record both the
cursor and synchronized-project marker.

The initial review's High owner-binding finding and all follow-up trust-boundary
findings are closed in the current tree. The superseding independent review is
`code-reviews/review-microsoft-graph-follow-up-2026-08-05.md`.

### Why It Matters

The shared foundation now keeps authentication identity, source scope,
checkpoint state, repository projection, and disclosure boundaries aligned in
the offline implementation. It remains deliberately smaller than an
enterprise connector and does not claim a real Microsoft integration.

### How to Verify

- `python3 -m pytest tests/ -q` — **368 passed**.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean; 45 files unchanged.
- `python3 -m ruff check src tests tools` — clean; existing top-level-settings deprecation warning only.
- `python3 -m compileall -q src tests tools` — clean.
- `python3 tools/check_disclosure.py` — clean over tracked and non-ignored repository files.
- `git diff --check` — clean.
- CLI help/version/auth/sync smoke checks — passed.
- No live account, consent, mailbox, network request, commit, or production operation was performed.

### Remaining Gate

The offline verdict is a **conditional pass**. Operator approval and sanitized
live evidence are still required for real consent, token storage, provider JWT
claims, refresh/throttling behavior, immutable IDs, initial/incremental/no-change
sync, restart and expired-delta recovery, attachment/body semantics, and
governed mailbox retrieval. OneDrive remains design-only readiness work and
OneNote remains explicitly unimplemented.

## 2026-08-05 — Sprint 5 S5-02 atomic cursor-only repository advancement

### What Was Built

The approved first Sprint 5 task is implemented without connecting to
Microsoft: `Repository.advance_cursor()` is an additive, fail-closed
capability, and `SQLiteRepository` persists a cursor-only empty-delta advance in
its own transaction. It changes only connector sync state; it does not create a
knowledge item, chunk, permission, journal, receipt, or fabricated tombstone.
Existing alternate repository providers remain instantiable and must explicitly
implement the capability before live ingestion relies on it.

`tests/test_repository.py` now proves an empty-delta cursor advances without
projection rows and that a failure after the cursor write rolls back to the
previous cursor.

### Why It Matters

Live delta synchronization must persist a new opaque cursor even when the
provider reports no changes. This closes the repository boundary gap without
weakening item/tombstone atomicity or changing the normalized connector
contract.

### How to Verify

- `python3 -m pytest tests/test_repository.py -q` — **8 passed**.
- Full Sprint 4 verification remains the baseline before this implementation;
  the full suite and repository checks are re-driven before handoff.
- No Microsoft connection, authentication, token storage, runtime HTTP
  dependency, commit, or production operation was performed.

## 2026-08-05 — Sprint 5 live Outlook proof planning

### What Was Decided

Sprint 4 is now recorded as the delivered, conditionally passed bounded offline
connector slice. Outlook internals are frozen unless a live proof exposes a
contract defect. Proposed Sprint 5 is a personal end-to-end Microsoft Graph
proof using one approved account and one disposable folder.

The scope answers five questions: authentication, initial sync, incremental
sync, expired-delta recovery, and governed email answers with provenance. It
explicitly excludes shared mailboxes, app-only access, multi-folder aggregation,
enterprise administration, background polling, attachment bytes, and LLM
synthesis.

An additive repository capability for atomic cursor-only advancement on an empty
delta is approved in principle. The exact method and transaction shape remain a
Sprint 5 design task. No live connection, OAuth flow, token storage, runtime
HTTP dependency, code change, commit, or production operation was performed by
this planning step.

### Why It Matters

The next sprint will validate the architecture at its actual trust boundary:
one real source account through transport, ingestion, persistence, retrieval,
permissions, freshness, citations, and answer assembly. It avoids mistaking a
well-tested adapter for a proven integration while preserving the personal-
first scope.

### How to Verify

- `sprint-plan.md` records Proposed Sprint 5 tasks S5-01 through S5-07,
  acceptance criteria, approval gates, and non-goals.
- `architecture.md` records the additive atomic cursor-only persistence
  direction without authorizing a live connection or breaking schema change.
- `context.md` and `WHERE_AM_I.md` identify Sprint 4 as delivered and Sprint 5
  as approval-gated planning.
- Existing Sprint 4 verification remains green; that milestone's full suite
  passed 324 tests with static checks, disclosure, diff, and CLI smoke checks
  clean. The current Graph follow-up suite is recorded in the newer entry.

## 2026-08-05 — BI-003 independent review hardening and conditional pass

### Findings and Disposition

The independent review recorded in `code-reviews/review-2026-08-05.md` found
seven concrete offline defects and repaired them in the adapter and focused
tests:

- failed fetches could leave a pending pass checkpointable;
- `lastModifiedDateTime` changes with unchanged body text were invisible to
  hash-only change detection;
- source-locator changes could leave stale citations without an update;
- same-message delta events were biased toward an update instead of response
  order;
- checkpoint inputs could substitute metadata or duplicate source IDs;
- provider-controlled health/error diagnostics could be echoed; and
- attachment relationship IDs could collide across messages.

The bounded offline slice is a **conditional pass** with no High/Critical
finding. New cursors bind connector and mailbox scope, while legacy unbound
version-1 cursors remain an explicit live multi-mailbox versioning decision.

### What Was Built

`OutlookConnector` now fingerprints source locator and modified-time metadata in
its deterministic normalized hash, applies delta events in page order, rejects
ambiguous duplicate events, blocks checkpointing after an unresolved fetch
failure, requires exact completed `SourceObject` metadata, namespaces attachment
relationships by immutable parent message, and suppresses provider-controlled
diagnostic strings and exception causes. Folder moves remain one-folder
semantics: a normal move out must be a deletion marker; an unexpected
wrong-folder message fails closed.

`tests/test_outlook_connector.py` grew from the initial six cases to 18 focused
cases covering pagination, immutable identity, deletion/move behavior,
quoted-history and attachment deduplication, metadata/content/locator drift,
checkpoint safety, permissions, provenance, freshness, error disclosure, and
the shared `Connector` boundary. `docs/outlook-connector.md`,
`docs/connector-capability-matrix.md`, and `architecture.md` now state the
hardened behavior and its limits.

### Why It Matters

The connector can no longer advance its in-memory checkpoint over a known
failed fetch or stale source metadata, and the common repository receives a
change whenever freshness or citation provenance changes. The slice remains
offline and does not infer live Graph, OAuth, ACL, throttling, or attachment
body behavior.

### How to Verify

- `python3 -m pytest tests/test_outlook_connector.py -q` — **18 passed**.
- `python3 -m pytest tests/` — **322 passed**.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean; 36
  files unchanged.
- `python3 -m ruff check src tests tools` — clean; existing top-level-settings
  deprecation warning only.
- `python3 -m compileall -q src tests tools` — clean.
- `python3 tools/check_disclosure.py` — clean.
- `git diff --check` — clean.
- `env PYTHONPATH=src python3 -m lee_kb.main --help`, `--version`, and
  `ask --help` — exit 0.

### Remaining Gated Work

- Graph transport, OAuth/token storage, authenticated mailbox binding, body
  representation, throttling/re-authentication, delta expiry recovery, and
  live immutable-ID request enforcement remain approval-gated.
- Legacy unbound cursor invalidation/versioning, durable no-op cursor
  persistence, and relationship persistence through the common repository are
  live integration design work, not claims of the offline adapter.
- The conservative quoted-history heuristic and attachment-byte parsing remain
  bounded-slice limitations.

## 2026-08-05 — BI-003 bounded Outlook adapter and generated-seed reconciliation (initial delivery)

### What Was Built

The stale generated golden seed was reconciled with the current
`project-plan.md`: the project-management case now asks for the current project
phase status and expects the current `Phase 2 queued` evidence. The generated
baseline was re-derived as 16/20 hit-at-1 (80.0%), 20/20 hit-at-10 (100.0%), and
0.888 MRR. This remains an evaluation-harness seed, not the curated
Chief-of-Staff benchmark; the OR-matcher decision and curated benchmark were
not changed.

BI-003 now has a bounded, offline Outlook/Microsoft 365 adapter in
`src/lee_kb/connectors/outlook.py`. It implements the shared connector contract
over an injected `OutlookTransport` for one delegated `/me` mailbox folder. The
slice locks `Mail.Read` as the body-reading design, immutable message IDs,
per-folder opaque delta links, `lastModifiedDateTime` freshness, deterministic
quoted-history-safe normalization, explicit conversation/attachment
relationships, private owner permissions, targeted refresh, and fail-closed
checkpoint behavior. `tests/test_outlook_connector.py` verifies the adapter
against a scripted transport and a real SQLite/governance projection.

`docs/outlook-connector.md`, `docs/connector-capability-matrix.md`,
`architecture.md`, `context.md`, `sprint-plan.md`, and `WHERE_AM_I.md` now
separate this offline adapter from the still-gated Graph HTTP, OAuth, token
storage, shared-mailbox, multi-folder, and attachment-body work.

### Why It Matters

Email now exercises the connector boundary against a native delta-shaped source
without transmitting source content or weakening the personal SQLite release.
The implementation proves stable identity, provenance, freshness, permissions,
relationships, deletion semantics, and cursor safety before live credentials or
provider operations are considered.

### How to Verify (initial delivery, before review hardening)

- `python3 -m pytest tests/test_outlook_connector.py -q` — **6 passed** (initial delivery).
- `python3 -m pytest tests/` — **310 passed** (initial delivery).
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean; 36
  files unchanged.
- `python3 -m ruff check src tests tools` — clean; existing top-level-settings
  deprecation warning only.
- `python3 -m compileall -q src tests tools` — clean.
- `python3 tools/check_disclosure.py` — clean; no host paths or credentials.
- `env PYTHONPATH=src python3 -m lee_kb.main --help` and `ask --help` — exit 0.
- `git diff --check` — clean.

## 2026-08-05 — BI-001 connector conformance and capability matrix

### What Was Built

The existing local connector boundary now has a focused conformance module at
`tests/test_connector_conformance.py`. It exercises connector identity and
configured scope, typed discovery, snapshot change detection, repeated no-change
sync, fetch and refresh, permissions, source and synchronization timestamps,
health, relationships, deletion behavior, and temporary read failures. The
temporary-failure cases assert both sides of the governance boundary: a failed
discovery cannot become a deletion, and a failed fetch leaves the prior cursor
and projection in place for retry. The existing discovery-failure regression in
`tests/test_local_connector.py` also now asserts cursor preservation.

`docs/connector-capability-matrix.md` compares local directories, selected
OneDrive folders, Outlook/Microsoft 365 mail, Gmail, and OneNote. It separates
implemented local behavior from official provider evidence, partial mappings,
and unknowns. The matrix recommends Outlook/Microsoft 365 mail as the first
external connector experiment because its public Graph documentation covers
per-folder delta, deleted-message markers, immutable IDs, timestamps, fetch
formats, and read permissions. It also records the unresolved API and
authentication questions without implementing or authorizing the connector.

No production interface, persisted schema, runtime dependency, external
connection, live credential, or BI-002 through BI-006 item changed.

### Why It Matters

BI-001 proves that the current source boundary can be tested without widening
the personal SQLite release. It makes deletion versus temporary failure,
checkpoint advancement, permission metadata, freshness, and source identity
explicit before provider-specific code is introduced. It also keeps the current
personal capability distinct from proposed small-group support and enterprise
infrastructure that is not on the active roadmap.

### How to Verify

- `python3 -m pytest tests/test_connector_conformance.py tests/test_local_connector.py -q` — **42 passed**.
- `python3 -m pytest tests/test_local_connector.py tests/test_cli.py -q` — **59 passed**.
- `python3 -m pytest tests/` — **304 collected, 302 passed, 2 failed** in the pre-existing golden seed: `tests/golden/corpus.toml` expects `Active / Sprint 1`, while the already-modified `project-plan.md` now records Phase 1 as complete. This slice did not change the OR-matcher decision, the curated benchmark status, or that project-plan change.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean; 34 files unchanged.
- `python3 -m ruff check src tests tools` — clean; the repository's existing top-level-settings deprecation warning remains.
- `python3 -m compileall -q src tests tools` — clean.
- `python3 tools/check_disclosure.py` — clean; no host paths or credentials.
- `env PYTHONPATH=src python3 -m lee_kb.main --help` — exit 0.
- `env PYTHONPATH=src python3 -m lee_kb.main ask --help` — exit 0.
- `git diff --check` — clean.

The requested static, disclosure, CLI, focused connector, and focused CLI
checks are green. BI-001 behavior itself is covered, but the current tree is
not yet a clean full-suite closure because of the unrelated golden-seed
mismatch.

## 2026-08-05 — Personal Second Brain positioning and connector backlog

### What Was Built

The product charter and architecture now describe lee-kb as a personal-first,
governed Second Brain that is capable of growing into small shared projects
without becoming an enterprise administration product. The strategic roadmap
now queues personal connector expansion after the foundation, and the tactical
sprint plan proposes a bounded connector-conformance slice.

Six candidate backlog items were added under `backlog/candidates/`: connector
conformance and capability mapping, OneDrive, Outlook/Microsoft 365, OneNote
feasibility, Gmail, and a personal corpus scalability baseline. None is
promoted to approved work; human curation remains required.

### Why It Matters

The delivered local connector and governed retrieval path are the foundation,
not the product endpoint. Capturing connector identity, source scope,
incremental state, access metadata, freshness, deletion, and temporary failure
as explicit roadmap concerns prevents each external source from becoming a
one-off ingestion system or forcing speculative tenant infrastructure into the
personal release.

### How to Verify

- `backlog/candidates/` contains BI-001 through BI-006 with required schema fields.
- `sprint-plan.md` marks Sprint 4 as a candidate and keeps Sprint 2's two open closure decisions explicit.
- `architecture.md`, `product-definition.md`, `project-plan.md`, `context.md`, `WHERE_AM_I.md`, and `README.md` distinguish current capability, proposed connector work, small-group future support, and enterprise non-goals.
- No source code or runtime dependencies changed in this work unit.

## 2026-08-04 — Audit capability closure and final verification

### What Was Built

Governed retrieval no longer swallows an unsupported query-audit capability.
`Repository.record_retrieval_event()` remains a concrete provider boundary for
compatibility, but its default raises and `_record_retrieval_audit()` propagates
that failure. A repository that cannot persist the required query event
therefore fails closed instead of returning an unaudited evidence bundle. The
governance suite adds a regression for this behavior.

Current project memory and contract documents were also reconciled: Office
approval and rollout are recorded as complete, schema-v2 additive migration is
distinguished from wipe-and-resync fallback, and current test/baseline counts
match the delivered tree.

### Why It Matters

Query-level audit persistence is part of the governed retrieval contract, not
an optional SQLite feature. This preserves the replaceable repository boundary
without allowing a provider to silently weaken the audit guarantee.

### How to Verify

- `python3 -m pytest tests/` — **298 passed**.
- `python3 -m pytest tests/answers/test_answer_benchmarks.py -q` — **37 passed**.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean; 33 files unchanged.
- `python3 -m ruff check src tests tools` — clean; existing top-level-settings deprecation warning only.
- `python3 -m compileall -q src tests tools` — clean.
- `python3 tools/check_disclosure.py` — clean.
- `git diff --check` — clean.
- CLI `--help`, `--version`, and `ask --help` — all exit 0.

The post-audit independent review is a conditional pass with no High/Critical
findings. Remaining work is limited to tracked low/advisory documentation and
scope follow-ups, the OR-matcher decision, the curated benchmark, and explicit
LLM/live-filesystem deferrals.

## 2026-08-04 — Clause-local conflict polarity repair

### What Was Built

The post-audit review found that a negation in an unrelated conjunction could
make `encrypted` versus `not encrypted` look equivalent when both statements
also said `no external link`. Conflict detection now compares local polarity
for shared non-value terms. Value-word comparisons also require complete
opposition pairings, so `required` versus `required and no owner is assigned`
remains an elaboration while genuine compound disagreements remain conflicts.
Two public `answer()` regressions cover both directions.

### Why It Matters

Negation detection must identify disagreement in the proposition being asked
about, not merely count negation tokens anywhere in a source sentence. The
change prevents both hidden contradictions and false conflicts from unrelated
negative clauses.

### How to Verify

- `python3 -m pytest tests/` — **297 passed**.
- `python3 -m pytest tests/test_answer_conflict.py -q` — **7 passed**.
- Black, Ruff, compileall, disclosure, and `git diff --check` — clean.

Final independent review remains to be run against the audit-schema and this
clause-polarity repair.

## 2026-08-04 — Query-level retrieval audit events (S1-R-12)

### What Was Built

With explicit approval, the repository schema advanced to v2 and now persists a
`RetrievalAuditEvent` for every governed retrieval outcome. Events retain query,
principal, project, retrieval timestamp, candidate count, denied count, released
count, truncation, and status. Empty, fully denied, mixed permitted/denied,
stale-refused, and provider-failure queries are all durable without placing
restricted source identity into the event. Version 1 databases migrate
additively, including normalizing existing item schema versions.

### Why It Matters

Per-evidence receipts correctly describe released evidence, but they cannot
represent an empty or denied query. The query-level event closes that audit gap
without fabricating evidence-shaped receipts or weakening the permission
boundary.

### How to Verify

- `python3 -m pytest tests/` — **295 passed**.
- `python3 -m pytest tests/test_governance.py tests/test_repository.py tests/test_contracts.py -q` — **64 passed**.
- `python3 -m pytest tests/answers/test_answer_benchmarks.py -q` — **37 passed**.
- Black, Ruff, compileall, disclosure, and `git diff --check` — clean.

Post-audit independent review remains to be run; the previous conditional-pass
review found no High or Critical findings before this schema change.

## 2026-08-04 — Conflict edge-case and golden-baseline repair

### What Was Built

The independent follow-up review found one remaining false conflict: a positive
value such as `required` paired with its explicitly negated opposite, `not
optional`, is emphatic agreement rather than disagreement. A second probe then
found that an agreement pair could hide a separate `approved` versus `denied`
disagreement in a compound statement. Conflict detection and merge refusal now
require complete value-set agreement, and the benchmark adds regressions for
both exact shapes.

The golden harness also exposed a genuine rank improvement from the current
projection: `architecture-04` moved from rank 2 to rank 1. The recorded gate
now reflects 14/20 hit-at-1 and 0.816 MRR, with the per-question table updated.

### Why It Matters

The answer layer must not fabricate a conflict from semantically equivalent
positive/negated value phrasing. The baseline remains an enforced measurement
contract, so an observed improvement is recorded rather than silently ignored.

### How to Verify

- `python3 -m pytest tests/golden/test_golden_corpus.py tests/answers/test_answer_benchmarks.py -q` — **62 passed** before the final full-suite rerun.
- `python3 -m pytest tests/answers/test_answer_benchmarks.py -q` — **37 passed**.
- Direct rank probe: 70.0% hit-at-1, 0.815555... MRR; documented as 70.0% and 0.816.

The final independent closure review is a conditional pass; only the
query-level audit-event decision remains open.

## 2026-08-04 — Final cold-review follow-up repairs

### What Was Built

The final cold review (`code-reviews/review-2026-08-04.md`) reproduced one High
connector defect plus related Medium edge cases. The follow-up repaired the
public `LocalFilesConnector.list_changes()` contract to diff a failure-aware
discovery report, so failed roots and subtrees cannot become deletion events.
Root-scoped overlapping ownership is now counted as `claimed_by_other_root`.

Office extraction now recursively retains nested DOCX table text. DOCX and PPTX
body/note text that begins with Markdown heading syntax is escaped before the
common Office chunker runs, preventing user content from becoming citation
structure. `ask` now distinguishes a never-synchronized project from a
previously synchronized project whose items are all tombstoned.

Freshness refusal is evaluated before release receipts are persisted, and the
package/README compatibility floor is aligned to Python 3.11 for unconditional
`tomllib`. A durable query-level audit event for empty or any denied retrieval
remains pending because it requires an approved persisted-schema
change; released evidence continues to use the existing per-evidence receipt
contract.

### Why It Matters

The public connector contract no longer permits a transient filesystem outage
to erase projection state, and Office normalization no longer silently loses
nested content or invents structural citations from user text. Answer absence
and stale-evidence reporting now preserve the distinction between searched,
unresolved, and refused states.

### How to Verify

- `python3 -m pytest tests/` — **292 passed** after the compound-value conflict repair.
- `python3 -m pytest tests/answers/test_answer_benchmarks.py -q` — **37 passed**.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean; 33 files unchanged.
- `python3 -m ruff check src tests tools` — clean; existing configuration deprecation warning only.
- `python3 -m compileall -q src tests tools` — clean.
- `python3 tools/check_disclosure.py` — clean.
- `git diff --check` — clean.
- `env PYTHONPATH=src python3 -m lee_kb.main --help` and `--version` — both exit 0.

The independent follow-up review is a conditional pass with no High or Critical
findings. Only the S1-R-12 query-level audit decision remains open before
release closure.

## 2026-08-04 — Repair of round-three contradiction regressions (S3-R-17 through S3-R-21); two-direction benchmark guard

### What Was Built

The independent round-three review (`code-reviews/review-sprint-3-repair-3.md`,
verdict `fail`) found that the previous conflict repair traded false conflicts
for missed contradictions. This repair addresses all five findings from that
review:

- **S3-R-17 (High)** — conflict detection and merge refusal now share a
  polarity-aware negation signal. `not`, `never`, `no`, `none`, `cannot`, and
  contractions are compared after removing the polarity token; de-negated
  value words must match exactly, so `required` versus `required, not optional`
  remains elaboration. A non-value-word negation such as `encrypted` versus
  `not encrypted` now yields two claims and one conflict, and the merge refusal
  remains correct when `detect_conflicts` is bypassed.
- **S3-R-18 (High)** — ordinary same-authority substitutions now count as
  positive disagreement when canonical term counts differ by exactly one term
  on each side and share an otherwise matching frame. This catches proper-noun,
  weekday, and place substitutions without treating elaboration as conflict.
- **S3-R-19 (Medium)** — declared authority no longer detects a conflict by
  itself. It only changes the detail of a positive substitution signal, so
  cross-authority voice changes and elaborations remain conflict-free.
- **S3-R-20 (Medium)** — the value-word path now requires an opposition rather
  than any unequal value-word set, and polarity handling requires equal
  de-negated value sets. Emphatic agreement is therefore not reported as a
  conflict.
- **S3-R-21 (Medium)** — the benchmark report now describes the actual
  mechanism and current counts. The permanent suite adds five contradiction
  shapes, an emphatic-agreement case, a detection-bypass case, and a fixed
  two-direction rate guard over same- and cross-authority pairs.

`answer.py` and `answer_conflict.py` now share canonical inflection-aware
meaningful-term comparison. No model client or runtime dependency was added;
the answer path remains deterministic and offline, with no Anthropic or other
provider call involved in this repair.

### Why It Matters

The prior round could still return one synthesized claim asserting a statement
and its negation, or silently omit a same-authority substitution. It could also
call cross-authority agreement a conflict. These are opposite-direction
correctness failures, so the new regression guard measures both: 14 fixed
non-competing cases produce zero conflicts, 10 fixed contradicting cases
produce one conflict and two singly-cited claims, and the negated non-value
word case stays split even with conflict detection neutralized.

### How to Verify

- `python3 -m pytest tests/` — **261 passed** in 30.62s.
- `python3 -m pytest tests/answers/test_answer_benchmarks.py -q` — **35 passed** in 4.84s.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean; 31 files unchanged.
- `python3 -m ruff check src tests tools` — clean; only the existing linter-settings deprecation warning remains.
- `python3 -m compileall -q src tests tools` — clean.
- `python3 tools/check_disclosure.py` — clean; no host paths or credentials.
- `git diff --check` — clean.

## 2026-08-04 — Round-three repair of the governed `answer()` surface (S3-R-15, S3-R-12, S3-R-16); full verification re-confirmed green; benchmark results re-derived

### What Was Built

An independent re-review of round two's repair (`code-reviews/review-sprint-3-repair-2.md`,
verdict `fail`) found that round two's fix carried an unmentioned side effect:
an undiscriminating branch in `_conflict_signal` reported a `Conflict`
whenever two same-topic statements' meaningful terms differed above a
similarity floor, with no test that the difference was an actual
disagreement. Three findings from that review are repaired for this step:

- **S3-R-15 (High, correctness / honest reporting)** — the structural-
  divergence branch (`src/lee_kb/answer_conflict.py`, previously the last
  check in `_conflict_signal`) reported agreement as disagreement on ordinary
  paraphrase, elaboration, and voice change: the reviewer measured 5 of 6
  constructed agreeing pairs flagged as conflicts, up from 1 of 6 pre-round-two,
  including the project's own harbor-readiness benchmark fixture (the
  duplicate-repository statement against the independent-audit statement,
  differing only by the word "confirms"). The branch is now removed entirely
  and replaced by two positive-evidence signals: `_morphological_antonyms_diverge`
  (a new `_is_prefixed_antonym` check for recognized `dis-`/`non-`/`un-`
  antonym pairs, e.g. `restricted`/`unrestricted`) ahead of the existing
  authority-divergence branch, and a superset/elaboration rule applied to both
  `_value_words_diverge` and `_statements_mergeable`: when one statement's
  meaningful terms (or value words) are a strict superset of the other's, that
  is elaboration, not disagreement, and no longer flags a conflict or blocks a
  merge. `_numbers_diverge` also gained a `_numeric_quantities` unit-aware
  comparison so a shared unit (days, hours, percent, ad hoc words) is compared
  per-unit rather than by raw numeric-literal overlap alone. Two new
  regression families were added to `tests/answers/test_answer_benchmarks.py`:
  `test_non_competing_statement_pairs_produce_no_conflicts` (6 parametrized
  agreeing-pair cases — voice change, elaboration, synonym restatement, an
  added qualifier, cross-root restatement, formatting-only) asserting
  `result.conflicts == ()`, and two new cases added to the renamed
  `test_contradicting_statement_pairs_produce_one_conflict_with_cited_sides`
  (`canonical-versus-derived`, a fresh authority-divergence fixture, and
  `morphological-antonym-outside-word-list`, the first same-authority
  contradiction proven through the new positive antonym signal rather than
  the removed similarity branch) asserting genuine contradictions still
  produce exactly one `Conflict`. `tests/answers/test_answer_benchmarks.py`
  now collects 27 items, up from 19.
- **S3-R-12 (Medium, correctness)** — the pre-existing narrower instance of
  the same defect (`_conflict_signal`'s value-word branch reporting a
  `Conflict` on elaboration, e.g. "required" vs. "required and approved") is
  closed by the same superset rule that fixes S3-R-15, since it is a special
  case of the same underlying bug.
- **S3-R-16 (Medium, documentation accuracy)** — the round-two benchmark
  document described that round's conflict-detection work as two changes
  (inverting the merge rule, adding a numeric-divergence signal) without
  naming the third, undiscriminating branch, and did not report its effect on
  the harbor-readiness question's conflict count. Corrected by this step's
  rewrite of `docs/answer-benchmark-results.md`, which now names the removed
  branch, its replacement signals, and states the harbor-readiness
  conflict-count change explicitly in Confidence Distribution.

This step additionally re-drove full verification and updated documentation
to match the repaired behavior: `docs/answer-benchmark-results.md` now
reports 27 collected benchmark items, a re-verified Confidence Distribution
(11 `DIRECTLY_EVIDENCED`, 0 `SYNTHESIZED`, 1 conflict total across the five
family-7 questions — the spurious harbor-readiness conflict introduced by
round two's regression is gone), and two new Conflict Examples entries: the
`morphological-antonym-outside-word-list` (Phoenix) same-authority
contradiction — the shape the previous document could not demonstrate,
since round two's out-of-vocabulary examples were only proven through the
now-removed undiscriminating branch — and a non-conflict regression example
(Halcyon elaboration) demonstrating the fixed false-positive directly. The
Recommendation remains **Ready after specific follow-up** — S3-R-12,
S3-R-15, and S3-R-16 are fixed and regression-tested; the carried-forward
Medium findings (S3-R-04, S3-R-05) and Low findings (S3-R-07, S3-R-08,
S3-R-09, all documentation accuracy) remain open, alongside the pre-existing
deferrals (LLM-backed synthesis provider, real-corpus measurement, live
filesystem verification, and the two inherited `retrieve()` open questions).

### Why It Matters

S3-R-15 is a false-positive-in-the-opposite-direction defect: unlike S3-R-01/
S3-R-02/S3-R-03/S3-R-10/S3-R-11, which suppressed or merged a correct answer,
S3-R-15 fabricated disagreement between sources that agreed, on the project's
own benchmark corpus and visible through the shipped `lee-kb ask` command's
`Conflicts:` section. A reader cannot use a `Conflicts:` section that reports
noise, and a machine consumer filtering on `conflicts` would receive mostly
false positives. The fix is a genuine tightening, not a narrower patch: it
requires *positive* evidence of disagreement (a recognized antonym or a
diverging number/value-word pair) rather than *mere difference*, and the new
5e family specifically asserts the direction the suite had never pinned
before — that agreeing statements produce zero conflicts — closing the gap
`code-reviews/review-sprint-3-repair-2.md`'s residual risk 6 named: each of
the first three repair rounds pinned the shape it was found against while
leaving the opposite direction unpinned.

### How to Verify

Preserved system-validator evidence for this step
(`agent_orch.validators.command_succeeds@1`; validator rerun not permitted,
so these are reported, not re-executed):

| # | Command | Exit | Result | Tied to | Evidence hash |
|---|---------|-----:|--------|---------|---------------|
| 1 | `python3 -m pytest tests/` | 0 | 253 passed in 25.64s | step_01_positive_contradiction_signal acceptance criterion, attempt 1 | `b66fa8133905c8aea3007eb76a589e2fe8f6967ce72a8ce24743dffeacc3482c` |
| 2 | `python3 -m pytest tests/` | 0 | 253 passed in 26.61s | step_01_positive_contradiction_signal acceptance criterion, attempt 2 | `b7d7b1184f5ff5cb051aebd1b4cd743dbdfb3c256ad925a0573be57430de4123` |

Fresh in this step (not preserved evidence):

- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean,
  `31 files would be left unchanged`, exit 0, no reformatting needed.
- `python3 -m ruff check src tests tools` — clean, exit 0 (the same
  pre-existing `pyproject.toml` linter-settings deprecation warning tracked
  as S2-R-10 remains, out of this step's scope).
- `python3 -m compileall -q src tests tools` — clean, exit 0, no output.
- `python3 tools/check_disclosure.py` — clean, exit 0: `check_disclosure:
  clean — no host paths or credentials in tracked files.`
- `git diff --check` — clean, exit 0, no output.
- `python3 -m pytest tests/answers/ -v` — 27 passed in 1.84s, exit 0
  (supplementary, not preserved evidence — used to confirm the new and
  expanded regression fixtures collect and pass, and to derive the
  per-family table in `docs/answer-benchmark-results.md`).
- `docs/answer-benchmark-results.md` — rewritten to reflect the round-three
  repaired behavior: updated Benchmark Cases (27 items, two families
  changed), a Confidence Distribution that now states the family-7
  conflict-count change explicitly, two new Conflict Examples entries
  (a same-authority morphological-antonym contradiction and a non-conflict
  elaboration regression), and a Recommendation that states the still-open
  Medium and Low findings plainly rather than implying full resolution.

## 2026-08-04 — Round-two repair of the governed `answer()` surface (S3-R-10, S3-R-11); full verification re-confirmed green; benchmark results re-derived

### What Was Built

A follow-up independent review (`code-reviews/review-sprint-3-repair.md`)
proved that round one's repair of S3-R-01/S3-R-02 (previous entry below)
narrowed each defect's shape without fixing its class. Two new High findings
were repaired for this step:

- **S3-R-10 (High, correctness/conflict detection and claim assembly)** —
  both halves of the round-one fix (the conflict signal and the merge
  refusal) were keyed to the same closed 14-word value-word vocabulary, so a
  contradiction phrased outside it (`"enabled"` vs `"turned off"`,
  `"permitted"` vs `"forbidden"`, or any purely numeric divergence such as
  `"30 days"` vs `"90 days"`) reproduced the original merge-into-one-claim
  failure exactly. `_assemble_initial_claims` (`src/lee_kb/answer.py`) now
  merges two evidence items only when their differing meaningful terms are
  empty or a known synonym set (`_statements_mergeable` in
  `src/lee_kb/answer_conflict.py`), inverting the previous rule of merging
  unless a known antonym was seen. `_conflict_signal`
  (`src/lee_kb/answer_conflict.py`) gained an explicit numeric-divergence
  signal (same-subject statements carrying different numeric literals) ahead
  of the value-word check, and `_subject_terms` no longer discards decimals.
  A parametrized regression fixture
  (`test_same_subject_divergence_outside_value_word_list_is_a_conflict`, 3
  cases) was added to `tests/answers/test_answer_benchmarks.py`.
- **S3-R-11 (High, correctness/answer quality)** — the evidenced-absence path
  still **replaced** the whole answer when its relevance-and-top-rank gate
  passed, demoting every other selected evidence item to `evidence_omitted`,
  so a short, top-ranked, genuinely relevant "X does not exist" record could
  still suppress a correct multi-source answer. `answer()`
  (`src/lee_kb/answer.py`) now assembles claims from the full selected
  evidence as normal and, when the explicit-absence gate passes, appends that
  cited statement as one more `DIRECTLY_EVIDENCED` claim in rank order
  instead of replacing the answer; the top-rank requirement in
  `classify_absence`/`_explicit_absence_evidence`
  (`src/lee_kb/answer_absence.py`) was removed since it is no longer needed
  to prevent suppression. A regression fixture
  (`test_top_ranked_absence_statement_is_additive_to_substantive_answer`) was
  added.

This step additionally re-drove full verification and updated documentation
to match the repaired behavior: `docs/answer-benchmark-results.md` now
reports 19 collected benchmark items (four new regression fixtures across two
families), a corrected Confidence Distribution reflecting a genuine behavior
change (the harbor-readiness question's two statements no longer merge into
one `SYNTHESIZED` claim now that the merge rule is inverted: 11
`DIRECTLY_EVIDENCED` claims, 0 `SYNTHESIZED`, across the five family-7
questions), and a new Conflict Examples entry drawn from the numeric-
divergence fixture (the case the previous document could not demonstrate,
since the round-one same-authority example used an in-vocabulary antonym
pair). The Recommendation remains **Ready after specific follow-up** —
S3-R-10 and S3-R-11 are fixed, but one correctness-adjacent finding from the
same review, S3-R-12 (Medium: `_conflict_signal` can report a `Conflict`
between statements that do not actually disagree, reproduced against the
current code for this step), plus the carried-forward Medium findings
(S3-R-04, S3-R-05) and Low findings (S3-R-07, S3-R-08, S3-R-09, all
documentation accuracy) remain open, alongside the pre-existing deferrals
(LLM-backed synthesis provider, real-corpus measurement, live filesystem
verification, and the two inherited `retrieve()` open questions). S3-R-14
(High, disclosure: an absolute host path in a test fixture) and S3-R-13
(Medium, documentation accuracy: the round-one benchmark document overclaimed
completeness) from the same follow-up review were already repaired before
this step — S3-R-14 by removing the host path and adding
`tools/check_disclosure.py`, and S3-R-13 by this step's rewrite itself, which
now qualifies each fixture's guarantee to the shape actually proven rather
than generalizing.

### Why It Matters

Each of the two repaired findings produced a confidently-labelled wrong
answer that survived a green 245-test suite before this step: S3-R-10, a
single claim asserting both "enabled" and "turned off" (or "30 days" and "90
days") with no conflict shown, reproduced through the shipped CLI in the
follow-up review; S3-R-11, a responsive two-source answer replaced entirely
by an unrelated-looking but technically relevant and top-ranked "does not
exist" statement. Both are now bounded by permanent regression fixtures that
reproduce the reviewer's exact constructed inputs, so a future change that
reintroduces either class fails the suite rather than passing it silently.
The fix is also demonstrably more general than round one's, not merely
patched around the reviewer's specific examples: it inverts the underlying
rule (merge only on demonstrated equivalence) rather than extending a word
list, which is why it closes all three reviewer-proven out-of-vocabulary
shapes (two antonym pairs plus a numeric one) with one change.

### How to Verify

Preserved system-validator evidence for this step
(`agent_orch.validators.command_succeeds@1`; validator rerun not permitted,
so these are reported, not re-executed):

| # | Command | Exit | Result | Tied to | Evidence hash |
|---|---------|-----:|--------|---------|---------------|
| 1 | `python3 -m pytest tests/` | 0 | 245 passed in 23.04s | step_01_invert_merge_and_additive_absence acceptance criterion, attempt 1 | `5d6ab97a4aeae6981dc60f4d39ba5017c43555796465239a17a4a0c93e0d2290` |
| 2 | `python3 -m pytest tests/` | 0 | 245 passed in 23.29s | step_01_invert_merge_and_additive_absence acceptance criterion, attempt 2 | `8a2da7bf6ef0760d2327967cb5d2e53d556517422bd425eb369223dd40df657f` |

Fresh in this step (not preserved evidence):

- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean,
  `31 files would be left unchanged`, exit 0, no reformatting needed.
- `python3 -m ruff check src tests tools` — clean, exit 0 (the same
  pre-existing `pyproject.toml` linter-settings deprecation warning tracked
  as S2-R-10 remains, out of this step's scope).
- `python3 -m compileall -q src tests tools` — clean, exit 0, no output.
- `python3 tools/check_disclosure.py` — clean, exit 0: `check_disclosure:
  clean — no host paths or credentials in tracked files.`
- `git diff --check` — clean, exit 0, no output.
- `python3 -m pytest tests/answers/ -v` — 19 passed in 1.10s, exit 0
  (supplementary, not preserved evidence — used to confirm the four new
  regression fixtures collect and pass, and to derive the per-family table in
  `docs/answer-benchmark-results.md`).
- `docs/answer-benchmark-results.md` — rewritten to reflect the round-two
  repaired behavior: updated Benchmark Cases (19 items across two further
  expanded families), a corrected Confidence Distribution reflecting the
  genuine merge-rule behavior change, a new numeric-divergence Conflict
  Example, and a Recommendation that states S3-R-12 and the still-open
  Medium/Low findings plainly rather than implying full resolution.

## 2026-08-04 — Repair of the three High findings from the Sprint 3 review (S3-R-01, S3-R-02, S3-R-03); full verification re-confirmed green; benchmark results re-derived

### What Was Built

The independent review of the governed `answer()` surface
(`code-reviews/review-sprint-3-governed-answer.md`, verdict `fail`, three
High findings) is repaired for the three findings it gated on:

- **S3-R-01 (High, correctness/conflict detection)** — two sources of the
  **same** declared authority that directly contradicted each other produced
  no `Conflict` and were merged into one self-contradictory `SYNTHESIZED`
  claim, because `_conflict_signal` (`src/lee_kb/answer_conflict.py`) only
  fired on differing authority or explicit supersession wording.
  `_conflict_signal` now also fires on value-word divergence between
  same-subject statements (reusing the existing `_VALUE_WORDS` set), and
  `_assemble_initial_claims` (`src/lee_kb/answer.py`) refuses to merge two
  evidence items whose value words diverge, whatever their text similarity.
  A regression fixture (`test_same_authority_value_word_contradiction_stays_as_two_claims`)
  and a new two-document `same_authority_repository` fixture were added to
  `tests/answers/test_answer_benchmarks.py`.
- **S3-R-02 (High, correctness/answer quality)** — the evidenced-absence path
  ran before evidence selection and could short-circuit the whole pipeline on
  any unrelated sentence matching a generic absence pattern, bypassing the
  relevance threshold entirely. `classify_absence`
  (`src/lee_kb/answer_absence.py`) now evaluates `_explicit_absence_evidence`
  only over already-selected evidence, requires the absence-bearing sentence
  to clear the same question-term relevance threshold `_relevance()` applies
  elsewhere, and requires the matched chunk to be top-ranked in the governed
  bundle. A regression fixture
  (`test_unresponsive_absence_shaped_sentence_does_not_replace_answer`) was
  added.
- **S3-R-03 (High, correctness/conflict reconciliation)** — `detect_conflicts`
  built its evidence-to-claim map once, before reconstitution, so a later
  conflicting pair could resolve to an already-displaced merged claim and
  resurrect it, double-citing chunks. `detect_conflicts`
  (`src/lee_kb/answer_conflict.py`) now updates that map transitively the
  moment a merged claim is split, so every subsequent pair resolves to the
  reconstituted single-evidence claims. A regression fixture
  (`test_three_source_conflict_cites_each_chunk_in_exactly_one_claim`) was
  added.

This step additionally re-drove full verification and updated documentation
to match the repaired behavior: `docs/answer-benchmark-results.md` now
reports 15 collected benchmark items (three new regression fixtures across
two families), a corrected Confidence Distribution (10 claims: 9
`DIRECTLY_EVIDENCED` + 1 `SYNTHESIZED`, fixing the double-counted 12 from
S3-R-06 as a byproduct of re-deriving the numbers), and a new Conflict
Examples entry drawn from the same-authority fixture. The Recommendation
remains **Ready after specific follow-up** — the three High findings are
fixed, but the review's Medium findings (S3-R-04 no withholding signal on
`Answer`; S3-R-05 `cmd_ask` cannot reach the CLI's own `UNKNOWN` absence
branch) and Low findings (S3-R-07, S3-R-08, S3-R-09, all documentation
accuracy) remain open, alongside the pre-existing deferrals (LLM-backed
synthesis provider, real-corpus measurement, live filesystem verification,
and the two inherited `retrieve()` open questions).

### Why It Matters

Each of the three repaired findings produced a confidently-labelled wrong
answer that survived a green 12/12 benchmark run and a green 235-test suite
before this step: a single claim asserting both "enabled" and "disabled"
with no conflict shown (S3-R-01, reproduced through `lee-kb ask` in the
review), a responsive two-source answer replaced by an unrelated sentence
(S3-R-02), and a resurrected merged claim double-citing two chunks after
conflict resolution (S3-R-03). All three are now bounded by their own
permanent regression fixture, so a future change that reintroduces any of
them fails the suite rather than passing it silently, as the review's
Residual Risk 5 warned would otherwise happen.

### How to Verify

Preserved system-validator evidence for this step
(`agent_orch.validators.command_succeeds@1`; validator rerun not permitted,
so these are reported, not re-executed):

| # | Command | Exit | Result | Tied to | Evidence hash |
|---|---------|-----:|--------|---------|---------------|
| 1 | `python3 -m pytest tests/` | 0 | 241 passed in 21.13s | step_01_repair_three_high_findings acceptance criterion, attempt 1 | `33d05eed716953f30f154f470e9b01551162a7d959d7df8a8108add54bddfb10` |
| 2 | `python3 -m pytest tests/` | 0 | 241 passed in 21.47s | step_01_repair_three_high_findings acceptance criterion, attempt 2 | `53a866fcd140168c1f2584808ee375285e6ebe05b7925f7750fa2a8e66e2c4af` |

Fresh in this step (not preserved evidence):

- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean,
  `30 files would be left unchanged`, exit 0, no reformatting needed.
- `python3 -m ruff check src tests tools` — clean, exit 0 (the same
  pre-existing `pyproject.toml` linter-settings deprecation warning tracked
  as S2-R-10 remains, out of this step's scope).
- `python3 -m compileall -q src tests tools` — clean, exit 0, no output.
- `git diff --check` — clean, exit 0, no output.
- `python3 -m pytest tests/answers/ -v` — 15 passed in 0.59s, exit 0
  (supplementary, not preserved evidence — used to confirm the three new
  regression fixtures collect and pass, and to derive the per-family table in
  `docs/answer-benchmark-results.md`).
- `docs/answer-benchmark-results.md` — rewritten to reflect the repaired
  behavior: updated Benchmark Cases (15 items across three expanded
  families), corrected Confidence Distribution, a new same-authority Conflict
  Example, and a Recommendation that states the open Medium/Low findings and
  pre-existing deferrals plainly rather than implying full resolution.

## 2026-08-04 — Sprint 3: the governed `answer()` surface and `lee-kb ask`; full verification green; benchmark results recorded

### What Was Built

Sprint 3 delivered a second retrieval surface, layered strictly on top of the
already-governed `retrieve()`: `answer()` returns an `Answer` — ordered
claims, each with its own citations and confidence, plus conflicts,
absences, and receipt identifiers — instead of raw evidence rows. This was
built across five prior steps in this run and this step closes it out:

- `docs/answer-architecture.md` — the normative design (evidence model,
  confidence model, conflict handling, provenance guarantees, absence
  semantics, synthesis providers, deferred extensions).
- `src/lee_kb/answer_contracts.py` — `Confidence`, `AbsenceKind`,
  `OmissionReason`, `Side`, `ReceiptId`, `EvidenceRef`, `OmittedEvidence`,
  `Claim`, `ConflictSide`, `Conflict`, `Absence`, `Answer`, and
  `SynthesisProvider`, with construction-time invariants for citation
  closure, receipt closure, evidence disjointness, and attributed prose.
- `src/lee_kb/answer_evidence.py` — deterministic, source-diverse evidence
  selection over a governed `EvidenceBundle`, with every rejected item kept
  and reasoned (`SelectionOmissionReason`).
- `src/lee_kb/answer_absence.py` — classifies `NOT_FOUND`, `INACCESSIBLE`,
  and `UNKNOWN` without ever collapsing them into one state, including the
  evidenced-absence path (a cited statement that something was never
  created).
- `src/lee_kb/answer_conflict.py` — pairwise conflict detection with two
  read-only ordering signals (`newer`, `more_authoritative`) and no `winner`.
- `src/lee_kb/answer.py` — `answer()` itself: plan (pass-through) → the
  unmodified `retrieve()` → evidence selection → absence classification →
  claim assembly → conflict detection → confidence assignment → optional
  narration. `DeterministicSynthesisProvider` is the default
  `SynthesisProvider`: an offline, standard-library-only template renderer,
  not a model call.
- `src/lee_kb/main.py` — the `lee-kb ask` CLI command, printing claims (or
  deterministic prose), confidence, citations, conflicts, omitted-evidence
  counts, and a receipt reference; fails closed on a missing/invalid
  principal exactly like `search`.
- `tests/answers/test_answer_benchmarks.py` — permanent, offline regression
  fixtures for seven distinct benchmark families (cross-repository claim
  assembly, fuzzy matching, cross-repository attribution breadth,
  authoritative evidenced absence, conflict identification without a
  winner, duplicate-source suppression, and end-to-end provenance/receipt
  closure), against a synthetic eight-document corpus synced through the
  real connector and repository.
- `docs/answer-benchmark-results.md` (this step) — per-family pass/fail,
  concrete provenance and conflict examples drawn from the fixtures,
  confidence distribution, latency observations, and a
  `Ready after specific follow-up` recommendation.

This step additionally drove full verification to green.
`BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools`, `python3 -m
ruff check src tests tools`, `python3 -m compileall -q src tests tools`, and
`git diff --check` were all run fresh. Two pre-existing issues, unrelated to
the `answer()` code itself, were fixed to get there:
`tests/test_local_connector.py` had drifted out of `black` formatting and was
reformatted with no behavioral change; a stray `tests/._test_bootstrap_cli.py`
file (macOS `AppleDouble` metadata, already covered by the `._*` rule in
`.gitignore` and never tracked by git) broke `compileall` and was removed as
local cruft. `python3 -m pytest tests/` was not rerun — validator rerun is
not permitted for this step; see How to Verify for the preserved evidence
this reports from.

**Explicitly not implemented by this step or any prior Sprint 3 step:** the
LLM-backed `SynthesisProvider` is specified in `docs/answer-architecture.md`
(Synthesis Providers) but not implemented — it requires a runtime dependency
that has not been approved, the same guardrail that gates office-format
parsing. Live filesystem verification of `ask` over time (freshness drift,
resync during use) remains a deferred extension: the benchmark suite runs
against a temporary, synthetic SQLite projection, not a live corpus. The
curated Chief-of-Staff golden benchmark still does not exist for either
`retrieve()` or `answer()`.

### Why It Matters

`ask` gives a human a governed, cited *answer* instead of evidence rows to
interpret themselves, without adding any permission logic of its own —
every guarantee `retrieve()` already provides (fail-closed authorization,
freshness, receipts) is inherited unchanged. The construction-time
invariants on `Answer` (citation closure, receipt closure, disjointness,
attributed prose) make a malformed answer impossible to build, not just
discouraged by convention, and the absence and conflict models are
structurally incapable of collapsing three distinct governance states
(no evidence / withheld evidence / unresolved question) or picking a
silent winner between two contradicting sources.

### How to Verify

Preserved system-validator evidence for this step
(`agent_orch.validators.command_succeeds@1`; validator rerun not permitted,
so these are reported, not re-executed):

| # | Command | Exit | Duration (s) | Result | Tied to | Evidence hash |
|---|---------|-----:|--------------:|--------|---------|---------------|
| 1 | `python3 -m pytest tests/` | 0 | 14.413172 | 186 passed | step_01 (answer architecture and contracts) | `1a3d21ca90580a931d16f5468c2c1cffc53bd5c8ec55bcac4c139779711faf4d` |
| 2 | `env PYTHONPATH=src python3 -c "from lee_kb import answer_contracts"` | 0 | 0.04469 | imports cleanly | step_01 | `8991457bea9d1925aae665efbcd33826801eff38ae39465f0056f49eafaff5ab` |
| 3 | `python3 -m pytest tests/` | 0 | 15.37891 | 193 passed | step_02 (evidence selection and provenance) | `cf8a35c6528fad7fbac770cdf38284b78138d4c2b476a01811b79ce2367bc291` |
| 4 | `python3 -m pytest tests/` | 0 | 16.399417 | 204 passed | step_03 (absence and conflict) | `e33a6281ac0f31f98e6a0bff873331b374a4c94e89c62f9e00055621b8be940e` |
| 5 | `python3 -m pytest tests/` | 0 | 16.707464 | 204 passed | step_03 | `5b333f0285429175ee518be0479266a37145485e055d1a7b71fccf3cf2f9f3e8` |
| 6 | `python3 -m pytest tests/` | 0 | 19.619283 | 223 passed | step_04 (answer assembly and CLI) | `730c832389ed31aa68aa75ff88caf4fd79066a4c80de00cd299a6b466d5ff031` |
| 7 | `env PYTHONPATH=src python3 -m lee_kb.main ask --help` | 0 | 0.07238 | prints usage | step_04 | `d978c0437a98a3aa503c145496994d4bf3b959de742774434859fd1be2015d10` |
| 8 | `python3 -m pytest tests/answers/` | 0 | 0.992751 | 12 passed | step_05 (regression fixtures, seven benchmark families) | `48c1a51c2f83ee304d657ec09d6b7de7529854b20e9100c68c989066c3260401` |
| 9 | `python3 -m pytest tests/` | 0 | 19.621162 | 235 passed | step_05 | `e60b728ee811d2970d9cdc595aca93815b5a38c903188043b9d987e740792999` |

Fresh in this step (not preserved evidence):

- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean
  after reformatting `tests/test_local_connector.py`, exit 0.
- `python3 -m ruff check src tests tools` — clean, exit 0 (the same
  pre-existing `pyproject.toml` linter-settings deprecation warning tracked
  as S2-R-10 remains, out of this step's scope).
- `python3 -m compileall -q src tests tools` — clean, exit 0, after removing
  the stray gitignored `._test_bootstrap_cli.py` file.
- `git diff --check` — clean, exit 0.
- `docs/answer-benchmark-results.md` — per-family results, concrete
  provenance and conflict examples, confidence distribution, and latency
  observations, all drawn from `tests/answers/test_answer_benchmarks.py`'s
  synthetic fixtures (never Lee's private corpus).

## 2026-08-03 — Sprint 2 correctness and performance repairs (S2-R-04, S2-R-03, S1-R-16); full verification green

### What Was Built

Three findings from the independent review of the real-corpus parity slice
(`code-reviews/review-sprint-2-p1-real-corpus.md`, verdict `pass`) were
repaired and re-verified:

- **S2-R-04 (Medium, correctness)** — nested/overlapping configured roots
  could silently double-count one on-disk file as two independently citable
  knowledge items, because identity is `(connector, "root:relative")` and
  nothing detected root overlap. `LocalFilesConnector` now resolves every
  root's absolute path once at construction and, at discovery time, has each
  candidate file claimed by exactly one root: the deepest matching resolved
  root wins, with root name as the tiebreaker for equal-depth ties
  (`_claiming_root`, `_find_nested_roots` in
  `src/lee_kb/connectors/local_files.py`). `health()` now reports detected
  nested-root pairs. A related edge case in the same area was hardened at the
  same time: `_git_ignored_relatives` now also checks the configured root
  path itself, so a parent-repository ignore rule that would otherwise
  suppress an entire root is surfaced as unresolved rather than silently
  dropping the root's files. Regression tests were added to
  `tests/test_local_connector.py`.
- **S2-R-03 (Medium, efficiency)** — one sync pass discovered and hashed the
  whole corpus twice: `list_changes()` (called by `_sync_connector`) ran a
  full `discover()` → `discover_report()` pass, and `_sync_connector` then
  called `discover_report()` a second time purely to obtain counters. On the
  real corpus this was the largest contributor to the recorded 5:20.37
  wall-clock and ~4.48 GiB peak RSS baseline. `_sync_connector` now calls
  `connector.discover_report()` exactly once per sync and derives the change
  list from that single report's objects via a new `_changes_from_objects`
  helper (`src/lee_kb/main.py`). Regression coverage was added to
  `tests/test_local_connector.py` and `tests/test_cli.py`.
- **S1-R-16 (baseline-as-contract)** — the golden evaluation baseline
  (60.0% hit-at-1 / 100% hit-at-10 / 0.766 MRR, `docs/golden-baseline.md`)
  was previously documentation only; nothing failed if retrieval quality
  regressed. `tests/golden/test_golden_corpus.py` now adds
  `test_recorded_baseline_metrics_are_enforced_by_the_harness`, which
  computes hit-at-1/hit-at-10/MRR over the golden corpus through the governed
  `retrieve()` surface and asserts each metric is within 0.01 (symmetric
  `math.isclose`, so an unrecorded *improvement* fails just as loudly as a
  regression) of the value parsed live out of `docs/golden-baseline.md`.

This step also drove full verification to green. `pytest` was not rerun —
validator rerun is not permitted for this step; see How to Verify below for
the preserved evidence this report is based on. `BLACK_NUM_WORKERS=1
python3 -m black --check src tests tools` and `python3 -m ruff check src
tests tools` were run fresh: both initially failed (`black` wanted to
reformat `tests/golden/test_golden_corpus.py` and `tools/validate_verdict.py`;
after reformatting, `ruff` still flagged one over-length docstring line in
`tests/golden/test_golden_corpus.py`, wrapped by hand). Both commands are
clean as of this step, with no behavioral change.

### Why It Matters

S2-R-04 closes a real correctness gap before office-format ingestion touches
more root paths: the deployed config already has two overlapping root pairs
(confirmed via `health()`), and without this fix an environment where
git-ignore resolution fails on the overlap (already true for 2 of 15 roots
in the real corpus, `git_unresolved = 5`) would index the overlapping files
twice, each independently citable. S2-R-03 removes redundant work from the
sync path measured, on the real ~1,213-document corpus, as a 149.19s
(−46.6%) wall-clock drop (5:20.37 → 2:51.18) and a 128.91s (−47.8%) user-time
drop, with peak memory unchanged within noise (−0.4%) — consistent with
eliminating a duplicate discovery pass rather than reducing data held in
memory at any one time; document and chunk totals (1,213 / 12,699) are
unchanged. S1-R-16 turns the retrieval baseline into an executable contract,
per the Sprint 1 closure requirement that the benchmark must be a contract,
not documentation.

**Explicitly not implemented by this step or any prior step:** office-format
(`.docx`/`.xlsx`/`.pptx`) parsing remains unregistered, pending both Lee's
approval of new parsing dependencies and extending the affected roots'
`include` patterns in the deployed configuration — neither alone closes the
gap, per `evidence/real-corpus-parity-report.md`. The curated Chief-of-Staff
golden benchmark also still does not exist; the 20-question generated corpus
in `tests/golden/` proves the evaluation harness only.

### How to Verify

Preserved system-validator evidence for this step (`agent_orch.validators.command_succeeds@1`; validator rerun not permitted, so these are reported, not re-executed):

| # | Command | Exit | Duration (s) | Tied to | Evidence hash |
|---|---------|-----:|--------------:|---------|---------------|
| 1 | `python3 -m pytest tests/` | 0 | 11.098397 | S2-R-04 (nested-root duplicate evidence) | `2fbcb7284519f032d351a931c3902d9d16b03b1c39d5fd4d68b6ffb75bbce4d1` |
| 2 | `python3 -m pytest tests/` | 0 | 11.557784 | S2-R-03 (single discovery pass) | `665641ffa5949a4d0bbafa130108b0de65993142825b8e8c879af3be55537737` |
| 3 | `python3 -m pytest tests/golden/` | 0 | 8.119346 | S1-R-16 (baseline as contract) | `4af5f782bb8f9b7c29f81412903cb402dc4da2c00401d803fae9d7036c1f868e` |
| 4 | `python3 -m pytest tests/` | 0 | 12.598738 | Real-corpus re-measurement after the repairs | `f36ac9565b571ee3e4949e2c1b0939ee57fbef26d3c7127d4d5f5b435414db1e` |

Fresh in this step (not preserved evidence):

- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` — clean: `All done! ... 19 files would be left unchanged.`, exit 0.
- `python3 -m ruff check src tests tools` — clean: `All checks passed!`, exit 0 (one pre-existing deprecation warning about `pyproject.toml`'s top-level linter settings, tracked as S2-R-10, out of this step's scope).
- `evidence/real-corpus-parity-report.md` — the post-repair sync re-measurement (Performance section) and `code-reviews/review-sprint-2-p1-real-corpus.md` — the independent review these repairs respond to (verdict `pass`).

## 2026-08-03 — Real-corpus parity measurement (P1c) and verification (P1d)

### What Was Built

Next Actions Queue rank 1 (run against the real Employee Zero corpus) was
executed and its findings recorded in
`evidence/real-corpus-parity-report.md`. No source files changed in this
step; this was a measurement and documentation pass. Full verification was
re-driven: `python3 -m black --check src tests` and `python3 -m ruff check
src tests` both ran clean with no fixes required (`python3 -m pytest
tests/` and `sync --help` are preserved validator evidence from earlier in
this run and were not rerun per this step's mandate). `README.md` was
updated to document the `--workspace-root` and `--database` flags on
`lee-kb sync`, which existed in `src/lee_kb/main.py` but were previously
undocumented.

### Why It Matters

This resolves Open Question 4 and closes Next Actions Queue rank 1: lee-kb
has now synchronized and queried the actual deployed
`ai-employee-factory/knowledge/sources.toml` (15 roots, ~1,200 documents),
not just test fixtures and a manual scratch corpus. The measured findings
materially re-rank the remaining backlog (see `context.md`):

- **Corpus shape matches the reference.** 1,213 live items / 12,699 chunks
  across all 15 configured roots, closely tracking the
  `research/employee-zero-kb-reference.md` snapshot (1,209 documents /
  12,634 chunks); all 13 declared canonical-override promotions took effect
  correctly; zero fetch failures; zero token-shaped-secret hits.
- **The office-format gap is real and now sized precisely, not theorized.**
  39 office-format files (32 `.docx`, 5 `.xlsx`, 2 `.pptx`) sit inside the
  15 configured root paths, concentrated in `ai-employee-book` (21 `.docx`)
  and `tviq` (9 files). The connector's own sync summary reports an *empty*
  unhandled-format histogram across all 15 roots — a structural artifact,
  because every root's deployed `include` glob list is markdown-only and
  office files never match `include` before the handler-lookup step runs.
  Closing this gap requires **both** approving parsing dependencies **and**
  extending the affected roots' `include` patterns; office-format handlers
  remain entirely unregistered pending that dependency approval.
  `FORMAT_HANDLERS` and `DocumentType` still support adding them without
  redesign, per the Sprint 1 closure requirement — this is unchanged, still
  deferred implementation, not a deferred contract.
- **OR-matcher fetch-to-exhaustion is now measured.** The worst-case query
  ("the", a single ubiquitous token) took ~1.521s against the ~1,213
  document corpus, roughly 3.4x the category-query mean (0.443s over 10
  queries, range 0.286s–0.766s). Not yet measured: how this scales once
  office-format ingestion grows the corpus.
- **Retrieval quality: 8/10 category queries returned the correct top
  citation**; 2 (one job-search, one knowledge-discovery query) returned a
  topically-adjacent but non-canonical document, outranked by literal
  vocabulary overlap — a BM25 ranking limitation, not a discovery or
  indexing defect, and a concrete input for curating the real golden
  benchmark (Next Actions Queue rank 7, formerly rank 7/unranked).
  No result was denied by permissions in this run (search principal
  matched every root's declared `owner`).
- **Sync performance baseline recorded:** full clean sync wall-clock
  5:20.37 (320.37s), peak RSS ~4.48 GiB, 97% CPU utilization, no swaps.
  This is now the baseline for future full-resync performance work.

### How to Verify

- `evidence/real-corpus-parity-report.md` — full measurement detail
  (configuration, corpus shape, unindexed content, retrieval behavior,
  performance, parity gaps, recommended next actions).
- `python3 -m pytest tests/` — preserved validator evidence from this run
  (three independent executions, all exit 0; most recent duration
  8.967189s); not rerun by this step.
- `env PYTHONPATH=src python3 -m lee_kb.main sync --help` — preserved
  validator evidence from this run (two independent executions, both exit
  0); not rerun by this step.
- `BLACK_NUM_WORKERS=1 python3 -m black --check src tests` and `python3 -m
  ruff check src tests` — both run fresh in this step: `All done! ✨ 🍰 ✨
  18 files would be left unchanged.` and `All checks passed!`, exit 0, no
  changes required.

## 2026-08-03 — Review repairs: S1-R-01, S1-R-10, S1-R-11

The independent review's verdict gate rejected the delivered slice; each
finding was repaired and verified:

- **S1-R-01 (High)** — the ungoverned public `retrieve()` paths were removed
  from `src/lee_kb/retrieval.py`; `LexicalRetriever` is now a candidate
  provider (`search()` only) and `governance.retrieve()` is the sole public
  evidence surface. A package-wide sweep test
  (`test_governed_retrieve_is_the_only_public_evidence_surface`) now fails if
  any public callable other than the governed surface returns an
  `EvidenceBundle`.
- **S1-R-10 (High)** — discovery and fetch now share one containment rule: a
  symlink whose resolved target escapes its declared root is skipped at
  `discover()` time, and `_sync_connector` skips (and reports) unfetchable
  objects instead of aborting the pass. `SyncSummary` gained
  `skipped`/`skipped_objects` and the CLI prints them.
- **S1-R-11 (High)** — lexical matching ORs content tokens (stopwords
  stripped) and ranks by BM25; strict AND remains as `match="all"`. The
  golden corpus questions were rewritten as paraphrases and the baseline
  honestly re-recorded: 60.0% hit-at-1 / 100% hit-at-10 / 0.766 MRR
  (previously 85.0%/0.925 over extract-style questions, which flattered the
  matcher).

Verify: `python3 -m pytest` (109 passed), `BLACK_NUM_WORKERS=1 python3 -m
black --check src tests`, `python3 -m ruff check src tests`.

## 2026-08-03 — Sprint 1 (Personal Foundation) delivered: full verification green, docs updated

### What Was Built

Sprint 1 tasks S1-01 through S1-06 were implemented in prior steps of this
run; this step (S1-07) drove full verification to green and brought
documentation in line with delivered behavior:

- `src/lee_kb/contracts.py` — normalized domain contracts (S1-01), specified
  field-by-field in `docs/sprint-1-contracts.md`.
- `src/lee_kb/connectors/base.py` and `src/lee_kb/connectors/local_files.py`
  — the connector contract and the local-file connector (S1-02):
  content-hash change detection, fetch, permissions, health, and
  checkpointing. `DocumentType` enumerates `.docx`/`.xlsx`/`.pptx` and
  `FORMAT_HANDLERS` is structured to accept handlers for them, but no
  office-format parsing library is registered — that implementation, not the
  contract, is deferred pending explicit dependency approval.
- `src/lee_kb/repository.py` — the SQLite repository (S1-03): transactional
  item/chunk/permission persistence, a stored schema version, and an
  append-only journal; deletion is a tombstone, never a hard delete.
- `src/lee_kb/chunking.py` and `src/lee_kb/retrieval.py` — deterministic
  chunking and BM25 lexical retrieval (S1-04).
- `src/lee_kb/governance.py` — the governed `retrieve()` surface (S1-05):
  fail-closed authorization via `MissingPrincipalError` and
  `SingleUserPermissionEvaluator`, freshness reporting, and one persisted
  `RetrievalReceipt` per evidence item, including the empty-result case.
- `tests/golden/` and `docs/golden-baseline.md` — the golden evaluation
  harness (S1-06): 20 generated questions plus 3 negative controls run
  through `governance.retrieve()` against a temporary SQLite projection,
  recording a 60.0% hit-at-1 / 100% hit-at-10 / 0.766 MRR lexical baseline over paraphrase questions (re-recorded after S1-R-11 replaced the AND matcher and extract-style seed questions).
  **This is the generated seed corpus proving the evaluation harness, not
  Lee's curated golden benchmark** — it draws questions from this
  repository's own documents, not real recurring Chief of Staff questions
  against the Employee Zero sources.
- `src/lee_kb/main.py` — the `lee-kb init`/`sync`/`search` CLI (S1-07 carry-in
  from the prior step), exercised end to end in this step.

This step's own changes: reformatted 10 files with `black` and fixed all
`ruff` findings (import ordering, a lambda-assignment in `retrieval.py`
rewritten as a nested `def`, and several over-length lines wrapped) in
`src/lee_kb/{governance,main,retrieval,repository,connectors/local_files}.py`
and their corresponding test files — no behavioral changes. Updated
`README.md`, `sprint-plan.md`, `context.md`, and `WHERE_AM_I.md` to describe
delivered behavior only.

### Why It Matters

This closes Sprint 1 (Personal Foundation): lee-kb now proves one real
governed retrieval path — local documents to cited, permission-filtered,
freshness-reported, receipted lexical evidence in SQLite — matching the
sprint goal. The two explicit deferrals (office-format parsing and the
curated golden benchmark) are documented as deferred implementation, not
abandoned scope, per the locked Sprint 1 closure requirements.

### How to Verify

Full-suite and targeted `pytest` results below are preserved system-validator
evidence from this run (`agent_orch.validators.command_succeeds@1`), not
re-executed by this step:

- `python3 -m pytest tests/` — most recent full run (step S1-07 CLI surface,
  before the golden corpus existed): **82 passed** in 3.07s, exit 0.
- `python3 -m pytest tests/golden/` (step S1-06): **24 passed** in 1.98s, exit 0.
- `python3 -m pytest tests/test_repository.py tests/test_contracts.py`,
  `tests/test_local_connector.py tests/test_repository.py`,
  `tests/test_retrieval.py tests/test_local_connector.py`,
  `tests/test_governance.py tests/test_retrieval.py` — all passed at their
  respective steps.
- `env PYTHONPATH=src python3 -m lee_kb.main --help` — exit 0, prints the
  `init`/`sync`/`search` usage.

This step additionally ran, as noted:

- `python3 -m black --check src tests` and `python3 -m ruff check src tests`
  — both failed on first run (10 files needed reformatting; 8 ruff findings).
  After applying `black` and `ruff --fix` plus two manual fixes, both commands
  report clean: `All done!` / `All checks passed!`.
- `python3 -m pytest tests/` — rerun once, as an exception to verify the
  black/ruff edits introduced no regression (not a re-validation of the
  preserved acceptance-criterion evidence above): **109 passed** (re-run after the S1-R-01/10/11 repairs),
  exactly the 82 + 24 already-preserved counts combined.
- `env PYTHONPATH=src python3 -m lee_kb.main --help` — rerun once for the same
  reason: unchanged, exit 0.
- A manual end-to-end pass in a scratch corpus (outside governed write scope):
  `lee-kb init`, then `lee-kb sync` (`1 created, 0 updated, 0 deleted, 0
  unchanged`), `lee-kb sync` again (`0 created, ..., 1 unchanged` — idempotent),
  `lee-kb search "governed retrieval"` (returned the expected chunk with
  citation, sync age, and a receipt number), and `lee-kb search` against a
  fresh directory with no prior sync (`no synchronized knowledge found ...;
  run lee-kb sync first`, exit 1 — a clear error, not a traceback).

Known gap, tracked in `context.md` and left unchecked in `sprint-plan.md`:
this checkout has no real `knowledge/sources.toml` or Employee Zero source
roots, so the "existing sources.toml roots import and synchronize" item in
the sprint definition of done has not actually run against real data.

## 2026-08-03 — Public repository initialized

### What Was Built

The project was committed under `6ccb8de`, published as the public GitHub
repository `leebase/lee-kb`, and pushed to both `main` and
`agent/initial-public-repo`. The repository includes the MIT license.

### Why It Matters

The project now has a public, reproducible starting point with a conventional
default branch and an explicit open-source license.

### How to Verify

```bash
gh repo view leebase/lee-kb --json nameWithOwner,isPrivate,defaultBranchRef,url
git remote -v
git status -sb
```

Expected: `isPrivate` is `false`, the default branch is `main`, and the working
tree is clean.

## 2026-08-03 — AgentFlow project alignment

### What Was Built

The generated project-memory files were rewritten around the Lee Knowledge Base
product definition, architecture, and research. The repository now has a
concrete first sprint, aligned project guidance, role instructions under
`agents/`, and domain workflows under `skills/`.

The bootstrap package metadata and CLI description were also aligned with the
governed knowledge-fabric product instead of the generic greeting scaffold, and
two smoke tests now protect the help and version surface.

### Why It Matters

Future agents can now distinguish implemented behavior from planned behavior,
follow the connector and retrieval invariants, and hand work between research,
planning, building, and review without re-discovering project scope.

### How to Verify

```bash
test -f product-definition.md && test -f architecture.md && test -f sprint-plan.md
find agents skills -type f | sort
python3 -m compileall -q src/lee-kb/*.py
pytest
```

The project guidance and role/workflow files should be present, the Python
sources should compile, and the bootstrap smoke tests should pass (`2 passed`).

## 2026-08-03 — Initial repository scaffold

The repository was initialized with Python packaging and AgentFlow control
documents. The product-specific definition, architecture, and research were
then used as the source of truth for the alignment work above.

*Add new entries above this line. Keep entries factual and verifiable.*
