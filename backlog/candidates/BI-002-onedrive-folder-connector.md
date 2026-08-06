---
id: BI-002
title: OneDrive Selected-Folder Connector

source: user-request
source_insight: Selected OneDrive folders would extend the personal Second Brain beyond local files while keeping scope intentionally narrow.

opportunity: Search governed evidence from selected OneDrive folders without importing an entire account or weakening source ownership.

why_now: OneDrive is a named personal connector goal and shares Microsoft identity infrastructure with Outlook and OneNote.

minimal_impl: Implement a read-only connector for explicitly configured drive/folder scopes, using stable drive and item identities, incremental change state, permission metadata, and the existing Office normalization and repository path. Use provider test doubles for automated tests; live access requires separate approval.

definition_of_done:
  - Official provider behavior for selected-folder discovery, delta changes, moves/renames, permissions, and deletion is documented before implementation claims are made.
  - A configured folder scope synchronizes files through the common `KnowledgeItem`, chunk, citation, freshness, and audit path.
  - Temporary API or permission failures cannot tombstone source items or advance cursors incorrectly.
  - Tests cover stable identity, incremental changes, deletion, temporary failure, Office files, and unauthorized evidence.

effort: L
build_recipe: builder_safe
priority: next

dependencies:
  - BI-001
  - External: Microsoft Graph authentication and drive API approval

risks: Provider permissions, delta semantics, shared items, and moves may not map cleanly to local-file assumptions.

mitigations: Start read-only and folder-scoped, preserve opaque provider IDs, fail closed on unsupported permission states, and keep live verification separate from offline tests.

tags:
  - connector
  - onedrive
  - microsoft-graph
  - personal-second-brain

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

The first implementation should not become a general OneDrive mirror. The
configured scope and source permissions are part of the connector contract.
