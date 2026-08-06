---
id: BI-001
title: Connector Conformance And Capability Matrix

source: user-request
source_insight: The personal Second Brain needs several sources without creating one-off ingestion paths for each provider.

opportunity: Prove the existing connector boundary and make source-specific gaps visible before implementing an external API connector.

why_now: Local files and Office ingestion are delivered, and the next product phase is personal connector expansion to `/projects`, OneDrive, Outlook, OneNote, and Gmail.

minimal_impl: Add focused conformance tests for the existing `Connector` contract and document a capability matrix covering identity, discovery, incremental changes, fetch, permissions, freshness, deletion, temporary failure, health, and checkpointing for the local and candidate external sources.

definition_of_done:
  - LocalFilesConnector passes conformance coverage for discovery, changes, fetch, permissions, health, checkpointing, deletion, and temporary failure behavior.
  - A capability matrix compares local directories, OneDrive, Outlook, Gmail, and OneNote without claiming unsupported provider behavior.
  - The first external connector is selected with its blocking API, authentication, identity, permission, and incremental-sync questions recorded.
  - Existing retrieval, answer, audit, Office, disclosure, and CLI checks remain green.

effort: M
build_recipe: builder_safe
priority: now

dependencies: []

risks: Over-generalizing the connector interface could slow the personal release or leak provider-specific policy into retrieval.

mitigations: Keep the common contract small, use capability documentation rather than speculative abstractions, and keep authentication and retrieval authorization separate.

tags:
  - connector
  - architecture
  - personal-second-brain
  - phase-2

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

The existing local connector is the reference implementation. This item does
not add tenant fields, RBAC administration, enterprise persistence, live
external credentials, or an external connector implementation.
