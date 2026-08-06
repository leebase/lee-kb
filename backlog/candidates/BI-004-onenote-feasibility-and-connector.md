---
id: BI-004
title: OneNote Connector Feasibility And Scope

source: user-request
source_insight: OneNote is a desired personal source, but notebook/page structure and content limitations need evidence before implementation.

opportunity: Decide whether OneNote can enter the personal Second Brain through the common connector path without promising unsupported content or stale synchronization.

why_now: OneNote shares Microsoft identity context with the planned OneDrive and Outlook work but has different page/content and incremental-change semantics.

minimal_impl: Research the supported Microsoft Graph OneNote surfaces and produce a bounded connector design covering notebook, section, page, block, HTML/content normalization, embedded files/images, permission inheritance, and incremental limitations.

definition_of_done:
  - Official provider sources document supported identities, content surfaces, change tracking, permissions, and known limitations.
  - A proposed normalized source identity and citation locator model is written.
  - A clear go/no-go decision identifies whether OneNote belongs in the first external connector release or a later phase.
  - Any implementation dependency and live-connection approval requirement is explicit.

effort: M
build_recipe: planner_only
priority: next

dependencies:
  - BI-001
  - External: Microsoft Graph OneNote API evidence

risks: HTML, embedded media, and limited change notifications could make partial extraction misleading.

mitigations: Treat this as feasibility research first, fail closed on unsupported content, and do not implement a parallel OneNote retrieval path.

tags:
  - connector
  - onenote
  - microsoft-graph
  - research

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

This candidate deliberately asks for feasibility evidence rather than claiming
that OneNote is ready for implementation.
