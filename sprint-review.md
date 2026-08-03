# Lee Knowledge Base Sprint Review

> **External AI review.** Use this file for an independent assessment after a
> sprint or meaningful vertical slice. The reviewer should not be the builder.

## How to use this file

1. Give a fresh reviewer `AGENTS.md`, `product-definition.md`,
   `architecture.md`, `sprint-plan.md`, and the delivered changes.
2. Ask the reviewer to run the project checks and inspect correctness,
   governance, security, scope, tests, and documentation.
3. Add a new review entry below the heading, newest first.
4. Curate action items into `feedback.md` or the backlog.

## Reviews

No sprint has been completed yet. Sprint 1 is ready for implementation.

### Review entry template

#### Sprint N — Review by reviewer

**Date:** YYYY-MM-DD  
**Status:** 🟡 Pending / 🟢 Actioned / 🔴 Declined

**What was delivered:**

| Feature | Notes |
|---------|-------|
| Feature | Description and verification status |

**Checks run:**

| Check | Result |
|-------|--------|
| Build / compile | ✅ / ❌ |
| Automated tests | ✅ / ❌ |
| End-to-end user path | ✅ / ❌ |

**Findings:**

1. **[CATEGORY] Brief description**
   - **Issue:** Concrete failure mode or concern
   - **Recommendation:** Specific fix
   - **Priority:** 🔴 High / 🟡 Medium / 🟢 Low

**Action items:**

- [ ] Item 1
- [ ] Item 2

**Overall assessment:**

What is strong, what needs attention, and whether the project is ready for the
next sprint.

## Review categories

- **[ARCHITECTURE]** — structure and contracts
- **[GOVERNANCE]** — permissions, provenance, freshness, receipts
- **[CONNECTOR]** — ingestion correctness and source boundaries
- **[RETRIEVAL]** — evidence quality and ranking
- **[TEST]** — coverage and edge cases
- **[SCOPE]** — alignment with the first release
- **[DOCS]** — handoff quality
- **[RISK]** — security, data loss, or operational risk

*A sprint is not complete until its result and remaining risks are documented.*
