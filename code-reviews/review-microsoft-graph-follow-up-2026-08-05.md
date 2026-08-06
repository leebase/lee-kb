# Independent Follow-up Review - Microsoft Graph Foundation - 2026-08-05

## Scope

This review re-checked the Microsoft Graph foundation, delegated token
lifecycle, authenticated HTTP boundary, live-capable Outlook transport and
connector, repository cursor/project persistence, disclosure check, and the
related project documentation after the initial Graph review.

No Microsoft account, OAuth consent, mailbox, provider response, or external
network request was used. All provider behavior remains scripted/offline.

## Checks Run

| Command or check | Result |
|---|---|
| `python3 -m pytest tests/ -q` | 368 passed |
| `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` | Clean; 45 files unchanged |
| `python3 -m ruff check src tests tools` | Clean; existing settings deprecation warning only |
| `python3 -m compileall -q src tests tools` | Clean |
| `python3 tools/check_disclosure.py` | Clean over tracked and non-ignored repository files |
| `git diff --check` | Clean |
| CLI help/version/auth/sync smoke checks | Passed |

## Review Disposition

No open High, Critical, or Medium implementation finding remains in the
offline slice.

| Finding | Disposition |
|---|---|
| MG-R-01 | Mailbox owner is derived from the verified Graph account; mismatches and live connector identity overrides fail closed. |
| MG-R-02 | Subject and JWT tenant claims are verified, persisted only after verification, rechecked after refresh, and cached identity is invalidated on credential revocation or verification failure. |
| MG-R-03 | Version-1 cursors are rejected. Version-2 cursors bind project, account, configured tenant, credential fingerprint, verified subject, verified tenant, folder, and derived connector identity. |
| MG-R-04 | Graph URLs reject unsafe hosts, ports, fragments, redirects, and credential query parameters. Outlook locators use approved paths, reject query/fragment/userinfo/token-shaped paths, and fall back to the canonical Graph URI. |
| MG-R-05 | The CLI and Graph Outlook composition boundary require exactly delegated `Mail.Read` and `User.Read`. |
| MG-R-06 | Numeric/date retry hints are finite-checked and clamped to the retry policy. Jitter is bounded as well. |
| MG-R-07 | Token requests share pacing and retry only explicit throttling responses. Ambiguous network/5xx refresh failures are deliberately not replayed because replay can invalidate a rotated refresh grant; this is an availability tradeoff, not a production-readiness claim. |
| MG-R-08 | Delta continuation expiry retains the initial URL and restarts complete reconciliation once. |
| MG-R-09 | Retry and 401 replay are restricted to idempotent methods; one forced 401 replay is allowed even when the normal attempt count is one. |
| MG-R-10 | Caller-controlled authorization, host, cookie, proxy, user-agent, and content-length headers are rejected. |
| MG-R-11 | Response bodies, delta item counts, and aggregate delta bytes are bounded without quadratic aggregate-size recomputation. |
| MG-R-12 | HTTP 410 and known sync-state codes become `DELTA_EXPIRED` only in delta operations. |
| MG-R-13 | Attachment metadata is requested and mapped as parent-scoped relationships; attachment bytes remain out of scope. |
| MG-R-14 | Credential revocation and identity-binding failures clear cached trust; raw device authentication, token loading, and unverified access are private implementation paths. |
| MG-R-15 | Non-empty external rounds apply all prepared item/tombstone writes and the final cursor in one SQLite transaction; empty rounds atomically record the cursor and synchronized-project marker. |

## Boundary And Residual Risk

OneDrive remains a readiness assessment only. No drive-item connector,
download/export path, permission mapping, or OneDrive delta reconciliation was
implemented.

OneNote remains explicitly unimplemented and did not shape the Graph layer.

Live proof is still required for real consent, OS Secret Service behavior,
provider-issued JWT claims, refresh rotation, throttling, 401 handling,
immutable IDs, initial/incremental/no-change sync, restart behavior,
expired-delta recovery, folder moves, body and attachment semantics, and a
governed retrieval/answer over an actual mailbox.

## Verdict

**Conditional pass for the offline Microsoft Graph foundation and Outlook
path.** No High, Critical, or Medium implementation finding remains. This is
not a live Microsoft release sign-off; the operator-gated mailbox proof and
sanitized evidence remain outstanding.
