---
id: BI-012
title: Source Permission Change Conformance

source: research/glean-comparison.md
source_insight: >
  Permission-aware search depends on connectors mirroring source permission
  changes independently from content changes, including prompt revocation.

opportunity: >
  Turn lee-kb's fail-closed permission evaluator into a source-ACL-ready
  connector contract before small shared projects or richer external connectors
  rely on group membership and object-level access changes.

why_now: >
  The current live Outlook and Calendar paths prove configured principal grants,
  and permission-only resynchronization works, but general source-native ACL
  snapshots, provenance, revocation, and group-change behavior are not yet a
  connector conformance requirement.

minimal_impl: >
  Define and test an offline source-permission change fixture against the common
  connector and sync path. A source object's ACL can change without content or
  cursor payload changes; synchronization updates only permission facts, and a
  revoked principal immediately receives no evidence. Use synthetic identities
  and no external connection.

definition_of_done:
  - The connector capability matrix distinguishes configured grants, source-native object ACLs, inherited ACLs, user OAuth visibility, and service-credential visibility.
  - Conformance fixtures cover principal addition, removal, group addition, group removal, inherited-policy change, malformed ACL data, and ACL-fetch failure without content changes.
  - Permission facts record provider mode and observed-at time without persisting credentials, tokens, or restricted source names in audit metadata.
  - ACL-fetch failure retains last-known projection state but fails closed for release under a documented freshness policy; it cannot advance a permission checkpoint silently.
  - Revoked principals receive zero evidence and query audit events record denial counts without revealing source identity.
  - Existing personal configured-grant behavior remains unchanged and source authentication is not treated as retrieval authorization.

effort: M
build_recipe: builder_safe
priority: next

dependencies:
  - BI-001

risks: >
  Provider ACL models differ substantially, group membership may be stale, and
  a generic contract can accidentally claim stronger enforcement than the
  source API proves.

mitigations: >
  Model observed permission facts and capability levels rather than universal
  ACL semantics, keep evaluation fail-closed, preserve timestamps and source
  mode, and require provider-specific evidence before claiming conformance.

tags:
  - permissions
  - connector
  - conformance
  - small-group

status: candidate
created_at: 2026-08-11T19:29:15Z
created_by: OhMyPi-GleanReview
token_cost: 0
approved_at: ~
approved_by: ~
notes: ~
implemented_at: ~
implemented_by: ~
pr_url: ~
---

# Additional Context

This candidate does not introduce enterprise RBAC, a tenant administration
service, application permissions, shared mailboxes, or a production connector.
It closes a contract gap with synthetic proof first.

Public pattern source:

- https://docs.glean.com/connectors/about
