# Project Review - Next Step - 2026-08-05

## Scope

This review assessed the current project state, active Sprint 5 scope, the
Microsoft Graph/Outlook implementation, repository and governance boundaries,
latest independent review results, and project-memory consistency. No Microsoft
account, OAuth consent, mailbox, provider response, or external network request
was used.

## Architecture Summary

The project has two governed retrieval surfaces: `retrieve()` for structured
evidence and `answer()`/`lee-kb ask` for cited claims. Local Markdown, text, and
Office files use the common connector, SQLite, permission, freshness, citation,
receipt, and query-audit path. Sprint 5 adds a credential-bound, live-capable
Outlook adapter over a shared Microsoft Graph foundation. The remaining product
gate is one approved real mailbox proof through authentication, sync,
checkpoint recovery, and governed email answering.

## Checks Run

| Command or check | Result |
|---|---|
| `python3 -m pytest tests/ -q` | 368 passed |
| `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` | Clean; 45 files unchanged |
| `python3 -m ruff check src tests tools` | Clean; existing top-level-settings deprecation warning |
| `python3 -m compileall -q src tests tools` | Clean |
| `python3 tools/check_disclosure.py` | Clean |
| `git diff --check` | Clean |
| CLI help/version smoke checks | Passed |

## Findings

| ID | Severity | Category | Location | Problem | Proposed Fix |
|---|---|---|---|---|---|
| PRJ-R-01 | Medium | Release readiness / traceability | Current worktree status; `git status --short --branch` | The Graph implementation and its tests/docs are not in an immutable review snapshot: the branch is ahead of `origin/main` and the worktree contains many modified and untracked files. Running an external mailbox proof now would make its evidence difficult to attribute to the reviewed tree. | Freeze the reviewed tree in an approved commit, tag, or equivalent clean snapshot, then rerun the verification baseline before any external connection. Do not connect Microsoft from the current dirty tree. |
| PRJ-R-02 | Medium | Project-memory accuracy | `project-plan.md:76-93`, `project-plan.md:166-171` | The strategic plan still says Phase 2 and connector conformance are queued, while Sprint 4 and the Graph foundation are delivered and Sprint 5 is the active gate. This can send the next builder back to already-completed work. | Reconcile the strategic phase and next milestone with `sprint-plan.md`, `context.md`, and `WHERE_AM_I.md` after the live-proof decision. |
| PRJ-R-03 | Medium | Contract/documentation scope | `architecture.md:148-160`, `project-plan.md:140-141`, `src/lee_kb/repository.py:161-252`, `src/lee_kb/main.py:388-496` | The architecture describes relationships as repository-persisted projection data, but the current repository has no relationship table and external sync does not persist `connector.relationships()`. The Outlook connector exposes relationships in memory only; the prior connector review records durable persistence as deferred. | Either correct the architecture/plan wording to state the current connector-level-only behavior, or approve a separate relationship-persistence design and schema task. Do not treat durable relationships as part of the live Outlook proof. |
| PRJ-R-04 | Low | Tooling maintenance | `pyproject.toml:50-53` | Ruff passes but emits a deprecation warning because linter settings remain at the top level. | Move `select` and `ignore` under Ruff's `lint` section in a maintenance change. |

## Residual Risks

- The latest independent Graph review is a conditional offline pass only. Real
  provider behavior for consent, OS Secret Service, JWT identity claims,
  throttling, immutable IDs, no-change cursors, folder moves, expired-delta
  recovery, and mailbox body semantics remains unproven.
- The live acceptance path must exercise `retrieve()` and deterministic
  `answer()` after Graph-backed sync, including citations, freshness,
  permission facts, receipts, and query audit events.
- The curated Chief-of-Staff benchmark and the expanded-corpus OR-matcher
  decision remain valid follow-up work, but neither should displace the live
  Outlook proof once approval is available.

## Remediation Roadmap

### Fix Now

1. Obtain explicit operator approval for one public client, one account, and one
   disposable folder.
2. Freeze the reviewed tree and execute S5-04/S5-06: login, initial and
   incremental sync, restart-safe no-change sync, edit/delete/move behavior,
   expired-delta recovery, and governed email retrieval/answer evidence.

### Fix Soon

1. Reconcile `project-plan.md` with the delivered Sprint 4/Sprint 5 state.
2. Resolve whether relationship persistence is current scope or a deferred
   schema/interface decision.

### Fix Later

1. Re-measure the OR-matcher worst case at the current Office-expanded corpus
   and record the cap/early-exit decision.
2. Curate and run the real Chief-of-Staff benchmark through both governed
   surfaces.
3. Address Ruff configuration deprecation and other advisory documentation
   cleanup.

## Recommendation

The next bounded product step is the operator-gated live Outlook proof, not
another connector feature. Approval is not present in this review request, so
no external connection should be attempted in this session. If approval is
delayed, add only narrow offline composition tests for `GraphClient.login()`, a
fresh-process/reopened-database restart path, and Graph-backed `answer()`; do
not expand scope into LLM synthesis, OneDrive, OneNote, attachment bytes, or
enterprise infrastructure.
