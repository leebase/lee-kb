# Connector Capability Matrix

> **Microsoft Graph foundation, reviewed 2026-08-05.** This document separates
> delivered shared Graph plumbing from connector-specific behavior and provider
> evidence. No live Microsoft or Google account, credential, or source-content
> transfer was used by the automated verification.

## Current Boundary

| Source | lee-kb status | Scope of this document |
|--------|---------------|------------------------|
| Local directories | Implemented reference connector | `LocalFilesConnector` and the shared SQLite ingestion path are covered by existing tests and the BI-001 conformance suite. |
| Selected OneDrive folders | Candidate; shared Graph foundation available | Microsoft Graph account, token, HTTP, retry, pacing, pagination, and delta mechanics are reusable; no OneDrive connector exists. |
| Outlook/Microsoft 365 mail | Live-capable transport and CLI wiring; real proof pending | The bounded one-folder, delegated `/me` adapter is exercised offline, and `GraphOutlookTransport` maps scripted Graph response shapes through the shared client. No real mailbox proof is recorded. |
| Gmail | Candidate only | Gmail API capabilities are mapped; no connector or authentication flow exists in this repository. |
| OneNote | Candidate only | Microsoft Graph OneNote capabilities are mapped; incremental and permission gaps remain explicitly unknown. |

## Status Key

- **Implemented** means behavior exists in lee-kb and is covered by tests.
- **Provider evidence** means an official public API documents a mechanism, but
  the lee-kb adapter is not implemented and the mapping is not approved.
- **Partial** means the provider exposes part of the needed fact, while the
  governed mapping or important semantics remain unresolved.
- **Unknown** means the reviewed public documentation is insufficient to make a
  safe implementation claim. It is a question, not a negative capability
  assertion.
- **Offline adapter** means normalized connector behavior is implemented behind
  an injected transport and tested without external credentials; it is not a
  live provider integration.

## Matrix

| Capability | Local directories | Selected OneDrive folders | Outlook/Microsoft 365 mail | Gmail | OneNote |
|------------|-------------------|---------------------------|----------------------------|-------|---------|
| Configuration and scope | **Implemented.** `sources.toml` declares named roots, include/exclude patterns, project, owner, visibility, and required status. Root-scoped sync is supported. | **Provider evidence.** Graph delta can target a drive item and its children, including `/drives/{drive-id}/items/{item-id}/delta` [1]. A selected-folder configuration would need to pin the account, drive, and folder IDs; lee-kb configuration is not implemented. | **Offline adapter.** `OutlookScope` pins one delegated `/me` mailbox owner, one folder ID, and one project per connector instance. Multi-folder aggregation remains outside the slice. | **Provider evidence.** Gmail list methods support a user mailbox and label-filtered message discovery [3]. Account and label scope design is not implemented. | **Provider evidence.** Graph exposes user, group, and site notebooks, sections, and pages [4]. A selected notebook or section scope is plausible, but the lee-kb scope shape is not implemented. |
| Authentication | **Implemented for local use.** The process uses filesystem access. The configured owner is permission metadata, not an external authentication mechanism. | **Shared foundation available.** Microsoft Graph account, device-code, refresh, secure-storage, retry, pacing, and error plumbing is implemented; OneDrive consent/scope mapping remains unresolved. | **Live-capable foundation.** The bounded slice is delegated `/me` with `Mail.Read` plus minimal `User.Read` for account binding; `lee-kb auth login` uses device code, and `GraphClient` owns refresh, retry, throttling, and token-safe errors. A configured account and real consent proof remain pending. | **Provider evidence.** OAuth scopes are documented; `gmail.readonly` is a restricted scope and can trigger verification and security-assessment obligations when restricted data is stored on servers [7]. Approval for a local personal deployment is unresolved. | **Provider evidence.** Graph documents `Notes.Read` for delegated access and `Notes.Read.All` for application access for page reads [8]. The approved flow and consent path are unresolved. |
| Stable source identity | **Implemented with a known limit.** Item identity is `(connector_id, root:relative-path)`; repeated discovery is stable. A file rename is represented as a deletion plus a new object. | **Provider evidence.** Graph exposes `driveItem.id` and its delta guidance says to track items by ID rather than path [1]. Cross-drive, shared-item, and move identity behavior still need adapter tests. | **Offline adapter.** Source identity is `message:<immutable-id>` and the transport contract requires the immutable-ID policy. Attachment relationships are namespaced by their parent message because provider attachment IDs are local to a message. Archive/PST and export/import lifetime exceptions remain live-integration questions. | **Provider evidence.** Gmail exposes opaque message and thread identifiers through its message resources [3]. Account binding, label moves, and the exact lifetime guarantees needed by the item identity contract still require validation. | **Partial.** Pages expose an ID plus parent section/notebook relationships and timestamps [10]. The lifetime and move/copy semantics needed for a durable item ID are not established in the reviewed documentation. |
| Discovery | **Implemented.** Discovery returns typed `SourceObject` values, stable locators, hashes, timestamps, project, authority, and trust. Unsupported and excluded candidates are accounted for by the discovery report. | **Provider evidence.** Initial delta enumeration returns pages through `@odata.nextLink` and completes with `@odata.deltaLink` [1]. Folder ownership, supported file formats, and selected-root accounting are not implemented. | **Offline adapter.** The transport boundary follows one folder's initial and paginated delta pages, requires a final opaque delta link, and returns typed email source objects. | **Provider evidence.** Gmail full sync starts with `messages.list`, followed by `messages.get`; thread-based sync is also documented [11]. Pagination and label-scope accounting are not implemented. | **Provider evidence.** Notebook, section, and page list APIs exist and page listing is paginated with `@odata.nextLink` [4]. Notebook hierarchy traversal and omission accounting are not implemented. |
| Incremental changes | **Implemented.** A JSON snapshot of SHA-256 content hashes detects created, updated, and deleted objects without relying on mtimes. There is no native filesystem change feed. | **Provider evidence plus shared recovery.** Delta links provide opaque incremental state and deleted items use the deleted facet. The shared client can restart a complete round after `410 Gone`; drive scope and reconciliation remain unresolved. | **Live-capable transport.** `GraphClient` follows all pages, handles expired state with a marked full enumeration, and the adapter derives created, updated, and deleted message changes; `@removed` becomes a tombstone change. | **Provider evidence.** `history.list` supports partial sync from a stored `startHistoryId`; unavailable history returns `404` and requires full sync [12]. The adapter's full/partial reconciliation policy is unresolved. | **Unknown.** The reviewed v1.0 OneNote resource and list-page documentation exposes paging and modification timestamps but no OneNote-specific delta contract. Polling may be possible, but its completeness and deletion semantics are unproven. |
| Fetch | **Implemented.** Fetch returns normalized text, document type, source locator, content hash, source timestamp, project, title, authority, and trust. Markdown, plain text, DOCX, XLSX, and PPTX handlers are registered. | **Provider evidence.** Graph provides a drive-item content endpoint for file items [13]. Download redirects, export behavior, and supported-format policy need a connector design. | **Offline adapter.** The transport supplies a complete message; the adapter emits normalized text, `DocumentType.EMAIL`, a stable source locator, the modified timestamp, and a content hash. Hash and locator metadata are checked against the completed delta pass before fetch success is accepted. | **Provider evidence.** Gmail exposes `messages.get` with full or raw content and separate attachment retrieval [3] [11]. MIME decoding and safe attachment handling are unresolved. | **Provider evidence.** Graph page reads expose HTML page content through `/content` or `$value` [14]. HTML, images, resources, and embedded content handling are unresolved. |
| Normalization | **Implemented in the shared path.** The connector supplies source text and safe metadata; common chunking, repository, retrieval, citations, and receipts remain provider-neutral. | **Unknown in lee-kb.** The API supplies bytes and metadata, but cloud-file export, parser coverage, embedded-content rejection, and source locator rules are not implemented. | **Offline adapter.** Subject, participants, conversation ID, sent/received/modified timestamps, and body text are deterministic. The modified timestamp participates in the content hash, common quoted history is removed, attachment metadata is retained once with parent-message-scoped relationship IDs, and attachment bodies are excluded. | **Unknown in lee-kb.** Gmail supplies message, thread, label, MIME, and attachment data [3] [11]. Thread normalization, quoted-history policy, and derived artifacts are not decided. | **Unknown in lee-kb.** Graph supplies HTML and hierarchy metadata [10] [14]. Block parsing, resource treatment, embedded files, and safe normalization are not decided. |
| Permissions | **Implemented with an explicit boundary.** Root `owner` and `visibility` become `PermissionSet` metadata and are evaluated before evidence release. The connector does not introspect operating-system ACLs. | **Partial.** Graph exposes sharing and permission hierarchy information in drive delta responses, but complete permission-change scanning can require elevated permissions [1]. Effective inherited access and safe `PermissionSet` mapping are unresolved. | **Offline adapter, fail-closed.** The configured mailbox owner is the only implicit grant, visibility is private, and the source is classified as delegated mail read. Shared/delegated mailbox ACL mapping is excluded rather than inferred from API success. | **Partial.** OAuth authorizes the mailbox and requested data scope [7]. A governed per-object permission record for labels, delegates, or shared access is not established; caller success must not be treated as a complete ACL. | **Partial.** Graph authorization scopes control notebook/page access [8] [14]. Effective notebook, section, and page sharing metadata and its `PermissionSet` mapping are unresolved. |
| Freshness | **Implemented.** Source timestamps come from the file stat and sync timestamps are recorded in the projection; retrieval reports sync age. | **Provider evidence.** Drive items expose modification metadata and tags suitable for conditional fetches [13]. The source timestamp choice, clock policy, and retrieval freshness behavior are not implemented. | **Offline adapter.** `lastModifiedDateTime` is the source timestamp and is included in the normalized hash; sent and received times remain normalized message metadata. Sync timestamps and retrieval freshness use the common repository path. | **Partial.** Message metadata includes an internal message date and history supplies an ordering cursor [3] [12]. A last-modified timestamp for every relevant body or label change was not established in the reviewed docs. | **Provider evidence.** Pages expose `lastModifiedDateTime` [10]. Sync lag and freshness refusal/refresh behavior are not implemented. |
| Deletion | **Implemented.** A confidently completed discovery pass reports absence as `DELETED`; tombstoning is handled above the connector. Blocked roots, subtrees, and read failures are excluded from deletion diffing. | **Provider evidence.** Delta returns deleted items [1]. Folder deletion, permission loss, and resync reconciliation must be tested before tombstoning is safe. | **Offline adapter.** `@removed` IDs become `ObjectChange(DELETED)` only when the completed page set identifies them; later events for the same ID override earlier events in page order, and transport failures never become deletions. A normal move out of the configured folder must arrive as `@removed`; an unexpected message payload from another folder fails closed. Multi-folder move reconciliation remains outside the slice. | **Partial.** Gmail history reports message change records [12], but the mapping of message deletion, trash, label removal, and unavailable history to tombstones needs provider-specific tests. | **Unknown.** A page delete operation exists, but the reviewed read-side list documentation does not establish a complete deletion feed or absence semantics. |
| Temporary failure | **Implemented.** Temporary inaccessible roots, subtrees, and files are classified as failures, never as deletions. Failed fetches leave the prior cursor entry in place and are retried on a later sync. | **Shared foundation available.** Graph errors, throttling, bounded retry, rate limiting, token loss, and delta reset are normalized; OneDrive-specific permission-loss mapping remains unresolved. | **Live-capable transport.** Transport, malformed-page, wrong-folder, throttling, auth loss, expired-delta recovery, and changed-during-fetch failures are classified without provider diagnostics; unresolved failures block checkpointing until retry. | **Partial.** The provider documents unavailable history and full-sync recovery [12]; transient HTTP failure classification and checkpoint rules are not implemented. | **Unknown in lee-kb.** Graph request failures exist, but retry, access-loss, and checkpoint semantics are not established. |
| Health | **Implemented.** `health()` reports checked time, required missing roots, reachability, and nested-root diagnostics. | **Unknown in lee-kb.** An authenticated API probe could be a health signal, but it would not by itself prove selected-folder completeness or permission coverage. | **Live-capable transport.** `health()` verifies the delegated `/me` identity and selected folder through the shared client, returning only safe status classifications; it does not claim source completeness. | **Unknown in lee-kb.** A Gmail profile or list probe could test access, but source completeness and history availability need separate reporting. | **Unknown in lee-kb.** No source-specific health contract has been selected beyond possible Graph request checks. |
| Checkpointing | **Implemented.** `checkpoint()` produces a deterministic hash snapshot. The sync path persists cursor changes only with successful item/tombstone transactions; failed objects do not advance or disappear from the stored cursor. | **Provider evidence plus shared recovery.** The opaque `@odata.deltaLink` is the natural provider checkpoint [1]. The shared client provides complete paging and reset signaling, but drive-specific mapping does not exist. | **Live-capable transport.** The versioned cursor stores one folder's opaque `@odata.deltaLink`, project, connector/account/tenant/credential binding, verified provider subject/tenant, and metadata-only object snapshot. The common sync path writes it atomically with the final item/tombstone or through `Repository.advance_cursor()` for an empty round, which also marks the project synchronized. Version-1 cursors are rejected. | **Provider evidence.** `historyId` is the partial-sync checkpoint [12]. Full-sync completion, label scope, history expiry, and atomic persistence are unresolved. | **Unknown.** No reviewed incremental token was identified, so a safe checkpoint strategy is not established. |

## Other Contract Surfaces

The contract also exposes `relationships()` and `refresh()` even though they are
not separate columns in the required capability list.

| Contract surface | Local directories | External implications |
|------------------|------------------|-----------------------|
| Relationships | **Implemented as empty.** The local filesystem has no v1 relationship model. | The offline Outlook adapter exposes conversation and attachment relationship IDs; Gmail has thread/message relationships; OneDrive has parent hierarchy; OneNote has notebook/section/page hierarchy. These are normalization inputs, not permission grants. |
| Refresh | **Implemented as `fetch()`.** A live local read is already a targeted refresh. | The offline Outlook adapter delegates targeted message fetch through the transport. Live rate limits, permission changes, and provider refresh policy remain outside this slice. |

## Recommended First External Connector

**Recommendation: Outlook/Microsoft 365 mail remains the first external family.**
The bounded adapter, reusable Graph client, delegated token lifecycle, live
transport mapping, and common SQLite cursor wiring are implemented. A real
account proof is still an operator-run gate, not a claim made by offline tests.

The evidence is stronger for this first bounded experiment than for a generic
mail abstraction:

- Microsoft Graph documents a per-folder message delta flow with opaque
  continuation links and explicit deleted-message markers [2].
- The message resource exposes a stable conversation field, modification
  timestamps, body formats, MIME retrieval, and attachments [6].
- Graph documents immutable message IDs and their lifetime boundary within a
  mailbox [9]. That gives the identity decision a concrete provider mechanism
  to test rather than requiring a content- or path-derived ID.
- Graph documents delegated and application access, including least-privileged
  read permissions for message retrieval [5] [6]. The same identity platform is
  relevant to the later OneDrive and OneNote candidates, without implying that
  their permission or incremental semantics are solved.

Gmail is the strongest early follow-on. Its `historyId` partial-sync mechanism
is real and documented [12], but its restricted read scope, verification, and
security-assessment implications [7] should be resolved before it becomes the
first external implementation.

### Outlook And Graph Decisions

The adapter and shared foundation resolve the design questions needed for
deterministic implementation:

- Delegated `/me` with `Mail.Read` plus minimal `User.Read` for account
  verification; no app-only or shared-mailbox access.
- One explicit folder per connector instance; no implicit folder traversal.
- Immutable message IDs are the source identity; folder-move and archive/PST
  exceptions remain outside the first slice.
- Private owner-based permission facts are stored; API success is not treated
  as a complete per-message ACL.
- Normalized text body plus metadata, including `lastModifiedDateTime`, is
  hashed; common quoted history is removed; attachment bytes are not indexed
  and relationship IDs are retained with parent-message scoping. A non-secret
  source-locator fingerprint also participates in the hash so citation drift is
  not silent.
- `@odata.nextLink` pages must complete to an opaque `@odata.deltaLink` before
  a metadata-only cursor can be emitted.
- `lastModifiedDateTime` drives source freshness; targeted refresh delegates to
  the transport and still passes through the common `FetchedDocument` shape.
- New cursors bind the connector instance, mailbox, account, tenant, and
  credential fingerprint; version-1 cursors are rejected before live use.
- Device-code authentication, refresh-token rotation, secure local storage,
  401 re-authentication, throttling, retry, request pacing, generic paging, and
  expired-delta full reconciliation live in `src/lee_kb/microsoft_graph/`.

### Remaining Live-Proof Questions

- Which registered public client and disposable mailbox folder should the real
  proof use?
- Does the approved mailbox return the expected plain-text body and immutable
  IDs through the selected Graph permissions?
- Does the operator-run proof confirm initial, incremental, no-change, move,
  and expired-delta recovery behavior against one real folder?
- Live ingestion uses the additive `Repository.advance_cursor()` transaction
  for an empty-delta cursor; providers without that capability remain
  fail-closed until they implement an equivalent atomic operation.
- Should a later approved slice index text attachments, and which formats are
  safe to parse?

## Evidence Sources

The provider claims above are limited to these official public documents,
reviewed on 2026-08-05:

1. [Microsoft Graph `driveItem: delta`](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0)
2. [Microsoft Graph incremental message delta](https://learn.microsoft.com/en-us/graph/delta-query-messages)
3. [Gmail `users.messages` resource](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages)
4. [Microsoft Graph OneNote resource](https://learn.microsoft.com/en-us/graph/api/resources/onenote?view=graph-rest-1.0) and [list pages](https://learn.microsoft.com/en-us/graph/api/onenote-list-pages?view=graph-rest-1.0)
5. [Microsoft Graph authentication concepts](https://learn.microsoft.com/en-us/graph/auth/auth-concepts)
6. [Microsoft Graph message resource](https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0) and [get message](https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0)
7. [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
8. [Microsoft Graph OneNote page permissions](https://learn.microsoft.com/en-us/graph/api/onenote-list-pages?view=graph-rest-1.0)
9. [Microsoft Graph immutable Outlook IDs](https://learn.microsoft.com/en-us/graph/outlook-immutable-id)
10. [Microsoft Graph OneNote page resource](https://learn.microsoft.com/en-us/graph/api/resources/page?view=graph-rest-1.0)
11. [Gmail synchronization and full sync](https://developers.google.com/workspace/gmail/api/guides/sync)
12. [Gmail history-based partial sync](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list) and [sync guide](https://developers.google.com/workspace/gmail/api/guides/sync)
13. [Microsoft Graph drive-item content](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0)
14. [Microsoft Graph get OneNote page content](https://learn.microsoft.com/en-us/graph/api/page-get?view=graph-rest-1.0)

Local and offline adapter behavior is evidenced by
[`Connector`](../src/lee_kb/connectors/base.py),
[`LocalFilesConnector`](../src/lee_kb/connectors/local_files.py),
[`test_local_connector.py`](../tests/test_local_connector.py), and
[`test_connector_conformance.py`](../tests/test_connector_conformance.py), plus
[`OutlookConnector`](../src/lee_kb/connectors/outlook.py),
[`test_outlook_connector.py`](../tests/test_outlook_connector.py), and
[`outlook-connector.md`](outlook-connector.md).

The matrix does not promote BI-002 through BI-006, add a new runtime dependency,
connect to an external system, or authorize a live external connector.

[1]: https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0
[2]: https://learn.microsoft.com/en-us/graph/delta-query-messages
[3]: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages
[4]: https://learn.microsoft.com/en-us/graph/api/onenote-list-pages?view=graph-rest-1.0
[5]: https://learn.microsoft.com/en-us/graph/auth/auth-concepts
[6]: https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0
[7]: https://developers.google.com/workspace/gmail/api/auth/scopes
[8]: https://learn.microsoft.com/en-us/graph/api/onenote-list-pages?view=graph-rest-1.0
[9]: https://learn.microsoft.com/en-us/graph/outlook-immutable-id
[10]: https://learn.microsoft.com/en-us/graph/api/resources/page?view=graph-rest-1.0
[11]: https://developers.google.com/workspace/gmail/api/guides/sync
[12]: https://developers.google.com/workspace/gmail/api/guides/sync
[13]: https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0
[14]: https://learn.microsoft.com/en-us/graph/api/page-get?view=graph-rest-1.0
