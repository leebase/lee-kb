# Lee Knowledge Base Feedback Log

> **AI review workflow:** One agent builds, another reviews, and actionable
> feedback is recorded here. Keep the newest entry first.

## Current status

The latest Microsoft Graph follow-up is recorded in
`code-reviews/review-microsoft-graph-follow-up-2026-08-05.md` as a conditional
offline pass with no High/Critical/Medium implementation finding. Real mailbox
proof remains operator-gated. Earlier cold-review, Office/answer, audit, and
Sprint 2 advisory records remain historical follow-up context.

### 2026-08-05 - Project review and next-step recommendation

**Status:** 🟡 Offline implementation verified; live proof remains gated

The current tree passes 368 tests plus Black, Ruff, compileall, disclosure,
diff, and CLI smoke checks. The project review found no new offline runtime
finding. Before an external connection, the reviewed Graph work must be frozen
in an immutable snapshot. The strategic `project-plan.md` also needs to be
reconciled with the delivered Sprint 4/Sprint 5 state, and relationship
persistence must be described as deferred or separately approved because the
current repository does not persist connector relationships. The recommended
next product step is the approved one-mailbox Sprint 5 live proof; see
`code-reviews/review-project-next-step-2026-08-05.md`.

### 2026-08-05 - Sprint 5 Graph follow-up hardening

**Status:** 🟢 Conditional offline pass; live mailbox proof pending

**Actioned findings:**

1. Delegated grants are verified against `/me`; verified subject and JWT tenant
   claims persist across refresh, while unverified login/session/token paths are
   private to the Graph client.
2. Graph redirects, non-default ports, unsafe headers, credential-bearing URLs,
   and Outlook token-shaped paths fail closed; retry, pacing, delta, and memory
   limits are bounded.
3. Outlook cursor identity includes project, account, configured/verified
   tenant, credential binding, and provider subject; version-1 cursors are
   rejected and connector IDs are derived.
4. External item/tombstone rounds commit atomically with their cursor; empty
   rounds record synchronized-project state atomically. Post-checkpoint fetches
   use refresh semantics instead of stale-pass validation.

**Verification:** `368` tests pass; Black, Ruff, compileall, disclosure, diff,
and CLI smoke checks are clean. The only explicit availability tradeoff is no
replay of ambiguous refresh network/5xx failures, protecting refresh-token
rotation. See the superseding review artifact for the full disposition.

### 2026-08-05 - BI-003 Outlook review hardening

**Status:** 🟢 Actioned for the bounded offline slice; conditional pass

**Scope:** `src/lee_kb/connectors/outlook.py`,
`tests/test_outlook_connector.py`, `docs/outlook-connector.md`,
`docs/connector-capability-matrix.md`, and the shared Connector/repository
boundary.

**Actioned findings:**

1. Failed fetches and fetch hash/metadata drift now block a pending checkpoint
   until the same object succeeds; checkpoint metadata must match exactly.
2. Modified timestamps and source-locator fingerprints now participate in
   change detection, preserving freshness and citation provenance.
3. Delta events are applied in response order, duplicate/ambiguous page events
   fail closed, and wrong-folder payloads cannot become folder-move changes.
4. Attachment relationship IDs are scoped by immutable parent message.
5. Provider-controlled health/error details and exception causes are not
   disclosed through the adapter.

**Historical verification at the Sprint 4 milestone:** `18` focused Outlook
tests and the post-S5-02 full tree had `324` passing tests; Black, Ruff, compileall,
disclosure, and diff checks were clean. See
`code-reviews/review-2026-08-05.md`.

**Remaining gated work:** Relationship persistence, live Graph authentication,
richer body normalization, and attachment bytes remain outside this offline
slice. Version-1 cursor reuse is rejected, and empty no-op cursor advancement
marks the project synchronized atomically.

### 2026-08-04 - Audit closure and current-documentation cleanup

**Status:** 🟢 Actioned; conditional pass with no High/Critical findings

**Actioned findings:**

1. **Query audit capability:** `_record_retrieval_audit()` no longer swallows a
   repository's unsupported-capability error. A replaceable repository that
   cannot persist the required event fails governed retrieval closed instead of
   returning an unaudited bundle. A regression covers this behavior.
2. **Current documentation accuracy:** current status, baseline counts, Office
   approval state, additive migration wording, and audit-closure state are
   reconciled across project memory and the contract/benchmark documents.

**Verification:** `298` tests and `37` answer benchmarks pass; Black, Ruff,
compileall, disclosure, diff checks, and CLI help/version checks pass.

### 2026-08-04 - Second builder follow-up

**Status:** 🟢 Actioned; superseded by audit-closure review
**Finding actioned:** The follow-up review found a remaining false conflict for
`required` versus `not optional`, then a compound case where that agreement
could hide `approved` versus `denied`. `_negated_value_words_agree()` now
requires complete value-set agreement, and permanent benchmarks cover both
shapes. The golden baseline was also refreshed after the harness measured
`architecture-04` at rank 1: 14/20 hit-at-1 and 0.816 MRR.

**Verification:** The focused golden/answer checks pass (`62` tests before the
final full-suite rerun); the answer benchmark now has `37` passing items.

### 2026-08-04 - Builder follow-up to final cold review

**Status:** 🟢 Actioned; conditional pass
**Scope:** `list_changes()` failure semantics, scoped nested roots, Office edge
cases, deletion-only answer state, stale refusal receipts, and Python floor.

**Actioned findings:**

1. **[CONNECTOR] `FINAL-R-01`** — `list_changes()` now diffs a failure-aware
   discovery report and suppresses deletions for failed IDs and blocked
   prefixes. A root-disappearance regression passes.
2. **[CONNECTOR] `S2-R-15`** — root-scoped discovery documents ownership scope
   and reports `claimed_by_other_root` counts.
3. **[CODE] `FINAL-R-02`** — `has_synchronized_project()` distinguishes a
   deletion-only project from a never-synchronized project; the CLI regression
   now returns `NOT_FOUND` after deletion.
4. **[CONNECTOR] `FINAL-R-03` / `FINAL-R-04`** — nested DOCX table extraction
   is recursive, and DOCX/PPTX body heading syntax is escaped before chunking.
5. **[GOVERNANCE] `S1-R-13` / `S1-R-15`** — stale refusal receipts are not
   persisted; the supported Python floor is now 3.11+, matching `tomllib`.

**S1-R-12:** Approved and implemented. `RetrievalAuditEvent` records empty,
fully denied, mixed, stale-refused, and provider-failure outcomes; schema v1
databases migrate additively to v2.

**Verification:** `298` tests and `37` answer benchmarks pass; Black, Ruff,
compileall, disclosure, diff checks, and CLI help/version checks pass.

### 2026-08-04 - Final cold review

**Status:** ⚪ Superseded by builder follow-up and audit-closure review
**Scope:** Final Office ingestion, governed `answer()` surface, local-file
connector, sync/ask CLI, project memory, and inherited Sprint 1/2 review items.

**Findings:**

1. **[CONNECTOR] Public change detection can tombstone an inaccessible root.**
   - **Location:** `src/lee_kb/connectors/local_files.py:901-934`
   - **Issue:** `list_changes()` discards discovery failures and emits `DELETED`
     for every object in a temporarily unavailable root.
   - **Recommendation:** Diff from a failure-aware discovery report and add a
     root-disappearance regression.
   - **Priority:** 🔴 High

2. **[CONNECTOR] Scoped overlapping-root sync omits child-owned files.**
   - **Location:** `src/lee_kb/connectors/local_files.py:707-863`
   - **Issue:** Parent-scoped discovery applies the global child-root claim but
     has no accounting for files claimed outside the requested scope.
   - **Recommendation:** Define scope semantics and either reassign the claim
     for that pass or report a `claimed_by_other_root` count.
   - **Priority:** 🟡 Medium

3. **[CODE] Deletion-only projects are reported as unresolved.**
   - **Location:** `src/lee_kb/repository.py:600-612`, `src/lee_kb/main.py:692-695`
   - **Issue:** `has_live_items()` cannot distinguish a searched empty project
     from a never-synchronized project.
   - **Recommendation:** Track successful synchronization separately and add a
     deletion-only `ask` regression.
   - **Priority:** 🟡 Medium

4. **[CONNECTOR] Office edge cases lose or mislabel source text.**
   - **Location:** `src/lee_kb/connectors/office.py:181-191`,
     `src/lee_kb/chunking.py:37,138-155`
   - **Issue:** Nested DOCX tables lose text, and Office body text beginning
     with Markdown heading syntax becomes false citation structure.
   - **Recommendation:** Use recursive table extraction and an explicit
     structured Office chunk representation, with DOCX/PPTX regressions.
   - **Priority:** 🟡 Medium

5. **[GOVERNANCE] Audit and compatibility follow-ups remain open.**
   - **Location:** `src/lee_kb/governance.py:156-213`, `pyproject.toml:10`,
     `src/lee_kb/main.py:23`
   - **Issue:** Stale refusals can leave release receipts, denied/empty queries
     have no query-level record, and the declared Python 3.10 floor imports
     Python 3.11-only `tomllib`.
   - **Recommendation:** Close the inherited S1-R-12, S1-R-13, and S1-R-15
     findings before broad deployment.
   - **Priority:** 🟡 Medium

**Action items:**

- [x] Repair failure-aware public connector diffing (owner: Builder)
- [x] Add the scoped-root, deletion-only, and Office edge-case regressions (owner: Builder)
- [x] Reconcile project memory and release documentation after implementation follow-up (owner: Reviewer + Builder)

**Context and notes:**

Fresh verification passed (`281` tests, Black, Ruff, compileall, disclosure,
and diff checks). The clean checks do not cover the reproduced root-loss,
scoped-root, deletion-only, nested-table, or false-heading cases. No
implementation file was changed during the review.

## Feedback entry template

Copy this section for a new review:

### YYYY-MM-DD — Review by reviewer

**Status:** 🟡 Pending / 🟢 Actioned / 🔴 Declined / ⚪ Superseded  
**Scope:** Files, sprint tasks, or decisions reviewed

**Findings:**

1. **[CATEGORY] Brief description**
   - **Location:** `path/to/file:line` or architecture decision
   - **Issue:** Concrete failure mode or concern
   - **Recommendation:** Specific change
   - **Priority:** 🔴 High / 🟡 Medium / 🟢 Low

**Action items:**

- [ ] Item 1 (owner: @handler)
- [ ] Item 2 (owner: @handler)

**Context and notes:**

Record alternatives considered and why a finding was actioned, declined, or
superseded.

## Review categories

- **[ARCHITECTURE]** — boundaries, contracts, provider choices
- **[GOVERNANCE]** — permissions, provenance, freshness, receipts
- **[CONNECTOR]** — source sync, cursors, idempotency, health
- **[RETRIEVAL]** — ranking, evidence assembly, citations
- **[CODE]** — implementation correctness and maintainability
- **[TEST]** — coverage, edge cases, and realistic workflows
- **[DOCS]** — clarity and consistency with product/architecture
- **[SEC]** — data handling, trust boundaries, and secrets

## Status legend

- 🟡 **Pending** — received but not addressed
- 🟢 **Actioned** — implemented and verified
- 🔴 **Declined** — intentionally not addressed with rationale
- ⚪ **Superseded** — replaced by a later decision

*Keep feedback specific enough that a future builder can act without repeating the review.*
