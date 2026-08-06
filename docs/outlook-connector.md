# Outlook/Microsoft 365 Connector Slice

> **Outlook adapter and Graph transport, 2026-08-05.** The normalized adapter
> remains offline-testable, and the reusable Graph/OAuth transport is now
> implemented. A real mailbox proof still requires operator configuration and
> has not been run by the automated suite.

## Scope

One `OutlookConnector` instance represents one delegated `/me` mailbox folder.
The first slice deliberately excludes application permissions, shared
mailboxes, multi-folder aggregation, background polling, and attachment-body
ingestion. Multiple folders can be added later as separate connector instances
without changing the normalized repository contract.

The connector boundary is `OutlookTransport` in
`src/lee_kb/connectors/outlook.py`. The live implementation is
`GraphOutlookTransport` in `src/lee_kb/connectors/outlook_graph.py`; it uses
`GraphClient.delta_round()` so pagination and delta recovery remain in the
shared Microsoft layer. The normalized transport shape is:

- `delta_page(folder_id, request)` maps an initial request or an opaque
  `@odata.nextLink` to `OutlookDeltaPage`.
- `fetch_message(message_id)` returns one complete normalized message.
- `health(folder_id)` verifies the delegated `/me` identity and returns a safe
  reachability result.

Tests inject scripted HTTP or transport seams, so no token, mailbox content, or
external request is needed for the automated suite.

## Locked Decisions

| Concern | Decision | Reason |
|---------|----------|--------|
| Authentication | Delegated access to `/me`; required Graph scopes are `Mail.Read` and minimal `User.Read` for account binding; device-code login and refresh are owned by `microsoft_graph` | The connector indexes message bodies and verifies the `/me` identity. `Mail.ReadBasic` is not sufficient for normalized content; application access and shared mailboxes are outside this slice. |
| Message identity | Request immutable Graph IDs with `Prefer: IdType="ImmutableId"`; source IDs are `message:<id>` | Message IDs are the provider identity. Mutable paths and subjects are never used as item identity. |
| Folder scope | Exactly one configured folder per connector instance | A per-folder delta token is atomic and avoids silently duplicating or losing a message when folder topology changes. |
| Incremental state | Persist the opaque final `@odata.deltaLink` plus a metadata-only source snapshot in a versioned JSON cursor bound to the connector, account, tenant, and credential scope | The current base contract accepts one connector cursor. The snapshot makes unchanged source objects reconstructable after process restart without storing message bodies. |
| Timestamp | `lastModifiedDateTime` becomes `SourceObject.source_timestamp` and `FetchedDocument.source_timestamp`; sent, received, and modified timestamps are normalized metadata | Modified time is included in the normalized hash so metadata-only source changes remain visible through the hash-only `Connector` change contract and freshness is not left stale. |
| Body | Use normalized text body; remove common quoted-history markers (`>`, reply headers, and `Original Message`) | Quoted history is already present in earlier messages and must not be indexed repeatedly. The original source remains fetchable. |
| Attachments | Keep attachment name/type/size/inline metadata in the parent message and expose relationship IDs namespaced by immutable message ID; do not index attachment bytes | This makes attachments explicit without colliding provider-local attachment IDs, duplicating content, or pretending binary parsing is supported. A text-attachment slice is a separate approval. |
| Permissions | Store `PermissionSet(owner=mailbox_owner, visibility=private, classification="delegated-mail-read")` | Successful delegated access is not treated as a complete per-message ACL. Private-by-default is fail-closed for the personal release. |
| Source locator | Prefer an HTTPS web link on an approved Outlook host without userinfo, query parameters, or fragments; otherwise use the canonical `/me/messages/<id>` URI; include a non-secret locator fingerprint in the normalized hash | Every fetched email remains citable back to the authoritative source, and a citation URI change cannot silently advance a stale projection. Unexpected links are canonicalized rather than persisted. |
| Failure and checkpoint | A missing final delta link, malformed page, wrong-folder message, transport failure, expired-delta rebuild failure, or fetch hash/metadata mismatch fails the pass; an unresolved fetch failure also blocks `checkpoint()` until that object succeeds | Pages are applied only in memory and in response order; a later event for the same immutable ID wins. A message moved out of the configured folder must be represented by a removal marker. A reset enumeration derives absent prior IDs as deletions. No partial page or unavailable message may become a deletion or advance synchronization state. |

## Cursor Shape

The adapter emits a versioned cursor containing only synchronization state and
safe source metadata:

```json
{
  "version": 2,
  "connector_id": "<connector-instance-id>",
  "folder_id": "<configured-folder-id>",
  "project": "<project>",
  "mailbox_owner": "<delegated-mailbox-owner>",
  "account_id": "<local-account-id>",
  "tenant": "<tenant-selector>",
  "credential_binding": "<sha256>",
  "verified_subject": "<provider-subject>",
  "verified_tenant": "<provider-tenant>",
  "delta_link": "<opaque-provider-link>",
  "objects": {
    "message:<immutable-id>": {
      "content_hash": "<sha256>",
      "source_timestamp": "<iso8601>",
      "uri": "<source-locator>",
      "label": "<subject>",
      "fragment": "<immutable-id>"
    }
  }
}
```

New cursors are bound to the connector instance, delegated mailbox, local
account, tenant selector, and credential fingerprint. Version-1 cursors are
rejected rather than implicitly reused. Graph-backed connector IDs are derived
from the account/folder credential binding, so a caller cannot provide a
colliding live identity. Project scope is part of the connector ID and cursor
binding as well.

The cursor never contains message body text, attachment bytes, access tokens,
or raw provider error responses. Its source metadata must exactly match the
completed pass; it is computed only after a complete delta read and after any
failed fetch in that pass has been retried successfully. Repository persistence
remains the ingestion layer's atomic operation.

## Verification

`tests/test_outlook_connector.py` verifies:

- deterministic text normalization and quoted-history removal;
- attachment relationship metadata without duplicate body content;
- paginated initial discovery and stable message identity;
- opaque cursor encoding without source content;
- created, updated, deleted, repeated, ordered, and failed delta behavior,
  including normal folder-move removals and fail-closed wrong-folder data;
- metadata-only modification timestamps, source-locator drift, and fetch drift;
- checkpoint rejection after a failed fetch or substituted source metadata;
- fetch, refresh, timestamps, permissions, relationships, and health;
- governed SQLite ingestion, citations, and denial of another principal;
- fail-closed behavior when Graph-shaped delta data omits its final cursor or
  exposes provider-controlled diagnostics.

`lee-kb sync outlook <source>` now wires the live transport through the same
SQLite ingestion path. `lee-kb auth login` and `lee-kb auth revoke` manage the
local delegated token lifecycle. A real account still requires a configured
public client, account binding, OS-protected token store, consent, and a
sanitized operator-run proof; the tests do not make an external connection.

## Provider Evidence

- [Microsoft Graph incremental message delta](https://learn.microsoft.com/en-us/graph/delta-query-messages)
- [Microsoft Graph message resource and fetch](https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0)
- [Microsoft Graph authentication concepts](https://learn.microsoft.com/en-us/graph/auth/auth-concepts)
- [Microsoft Graph immutable Outlook IDs](https://learn.microsoft.com/en-us/graph/outlook-immutable-id)

## Remaining Live-Integration Questions

- Which registered public client and disposable mailbox folder should the
  operator approve for the real proof?
- How should archive-mailbox and export/import ID lifetime exceptions be
  surfaced before a live connector is enabled?
- Which Graph body representation and HTML-to-text policy should the live
  transport use when plain text is unavailable?
- Should a later approved slice index text attachments, and which formats can
  be parsed without introducing unsafe or unbounded content?
- Live ingestion invokes the additive `Repository.advance_cursor()` capability
  for a cursor-only no-change delta; providers without that capability fail
  closed rather than fabricate an item or tombstone.
