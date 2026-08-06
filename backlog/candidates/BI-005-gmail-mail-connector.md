---
id: BI-005
title: Gmail Mail Connector

source: user-request
source_insight: Gmail should be a second email provider behind the same governed email model rather than a separate ingestion pipeline.

opportunity: Extend personal email coverage while keeping thread, message, attachment, provenance, and permission behavior consistent with Outlook.

why_now: Gmail is a stated personal connector goal and is a follow-on to the first email-provider contract.

minimal_impl: Implement a read-only, label/scoped Gmail connector behind the common connector and normalized email model proven by the first email connector. Preserve opaque Gmail IDs, incremental history state, deletion, and authorization metadata.

definition_of_done:
  - Gmail account, label scope, message/thread identity, history/change behavior, deletion, and permission limitations are documented from provider evidence.
  - The connector produces the common normalized email representation and source citations.
  - Repeated, changed, deleted, and temporarily unavailable messages are covered by offline provider-double tests.
  - Retrieval and answer behavior remains governed and provider-agnostic.

effort: L
build_recipe: builder_safe
priority: next

dependencies:
  - BI-001
  - BI-003
  - External: Gmail API authentication and scope approval

risks: Gmail history and label semantics may differ from Outlook enough to create hidden provider-specific behavior.

mitigations: Reuse only the normalized email contract, keep provider adapters separate, and require a capability comparison before implementation.

tags:
  - connector
  - email
  - gmail

status: candidate
created_at: 2026-08-05T00:00:00Z
created_by: OpenCode
token_cost: 0
approved_at: ~
approved_by: ~
notes: ~
implemented_at: ~
implemented_by: ~
pr_url: ~
---

# Additional Context

Gmail should follow the first email-provider implementation so the common
thread/message model is tested once before a second provider is added.
