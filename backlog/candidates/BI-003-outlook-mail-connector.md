---
id: BI-003
title: Outlook Microsoft 365 Mail Connector

source: user-request
source_insight: Email is a high-value personal knowledge source whose thread and permission semantics need a governed connector rather than raw transcript import.

opportunity: Answer questions about personal Outlook mail with stable thread/message provenance, incremental synchronization, and honest access boundaries.

why_now: Outlook/Microsoft 365 is the planned first external connector family and can share Microsoft authentication research with OneDrive and OneNote.

minimal_impl: Define and implement a read-only, scope-configured Outlook connector that models mailbox/folder scope, thread and message identity, timestamps, attachments as explicit related artifacts, quoted history policy, incremental state, deletion, and permission metadata. Keep message normalization behind the connector/ingestion boundary.

definition_of_done:
  - Source/API evidence records supported mailbox scope, message/thread identity, change detection, deletion, and permission behavior.
  - A deterministic normalized email model is documented and tested without exposing quoted history or attachments twice.
  - Incremental synchronization preserves cursors across repeated, changed, deleted, and temporarily unavailable messages.
  - Governed retrieval returns citations to resolvable message/thread source locations and never releases unauthorized mail.

effort: L
build_recipe: builder_safe
priority: next

dependencies:
  - BI-001
  - External: Microsoft Graph Mail API and authentication approval

risks: Mail threads, quoted history, attachments, provider retention, and per-message permissions can produce misleading duplicate or partial evidence.

mitigations: Start with explicit folder scope and read-only messages, preserve message IDs and parent relationships, classify unsupported attachment/content states, and test duplicate suppression.

tags:
  - connector
  - email
  - outlook
  - microsoft-graph

status: candidate
created_at: 2026-08-05T00:00:00Z
created_by: OpenCode
token_cost: 0
approved_at: ~
approved_by: ~
notes: The bounded offline adapter is implemented in src/lee_kb/connectors/outlook.py and verified by tests/test_outlook_connector.py. It uses one delegated /me folder, Mail.Read design, immutable message IDs, metadata-only delta cursors, deterministic text normalization, private owner permissions, and explicit conversation/attachment relationships. Live Graph transport, OAuth/token storage, shared mailboxes, multi-folder aggregation, and attachment-body parsing remain gated on external approval.
implemented_at: ~
implemented_by: ~
pr_url: ~
---

# Additional Context

This item is the likely first external content connector, but it should not
start until BI-001 records the provider capability and authentication gaps.
