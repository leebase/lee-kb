# Microsoft Graph Foundation

> **Sprint 5 foundation, 2026-08-05.** This document describes the shared
> Microsoft Graph integration layer and the live-capable Outlook path. It does
> not implement a OneDrive or OneNote connector, and no credential or mailbox
> content is stored in this repository.

## Boundary

```text
CLI/configuration
      |
MicrosoftAccount + GraphCredential
      |
OAuthTokenManager ---- OS secret service / encrypted file store
      |
GraphClient --------- HTTPS transport, retry, throttle, pacing, errors
      |
GraphOutlookTransport -- Graph resource mapping only
      |
OutlookConnector ----- common connector contract
      |
common ingestion -> SQLite repository -> governed retrieve()/answer()
```

`src/lee_kb/microsoft_graph/` owns the Microsoft-specific plumbing shared by
future connectors:

- delegated authentication through the device authorization grant;
- access-token expiry checks, refresh, refresh-token rotation, and local
  revocation;
- authenticated HTTP execution through an injectable transport;
- normalized errors without provider response bodies;
- bounded retries with `Retry-After` handling for throttling and transient
  responses;
- process-local request pacing shared by Graph and identity requests;
- generic OData collection pagination and opaque delta-link handling; and
- expired-delta recovery through a complete initial enumeration marked as a
  reset.

`GraphOutlookTransport` in `src/lee_kb/connectors/outlook_graph.py` only maps
Graph message resources to the existing `OutlookTransport` shape. It does not
refresh tokens, retry requests, follow links, or decide cursor persistence.
The normalized `OutlookConnector` and the common repository remain responsible
for source identity, normalization, permissions, provenance, and checkpoint
ordering.

## Credential Model

`MicrosoftAccount` is a local account binding, not a token:

| Field | Meaning |
|-------|---------|
| `account_id` | Local storage namespace, such as `personal`; never a token or mailbox content |
| `user_id` | Verified provider identity or sign-in name used to bind `/me` |
| `tenant` | `common`, `consumers`, `organizations`, or a tenant identifier |

`GraphCredential` adds a public/native client ID, Graph scopes, and the fixed
Microsoft identity authority. Client secrets are not accepted in this model.
The current CLI uses one account and delegated `Mail.Read` plus minimal
`User.Read` for `/me` account verification; the account table
and explicit account binding do not assume that account is permanent. A future
deployment can add account records without changing connector or repository
identity. A SHA-256 fingerprint of the non-secret account/client/tenant/scope
configuration is stored with a token set to prevent configuration drift from
reusing the wrong token. After `/me` verification, the token set also retains
the verified provider subject and tenant selector. A changed access token is
re-verified before resource use, including after a 401 refresh.

Enterprise tenant administration, app-only access, shared mailboxes, RBAC, and
centralized account provisioning are deliberately not implemented.

## Authentication And Lifecycle

`lee-kb auth login` uses the Microsoft device authorization flow:

1. Request a device code for `offline_access` and the configured Graph scopes.
2. Present only the verification URL, user code, and provider instructions.
3. Poll at the server-provided interval until authorization completes or the
   device code expires.
4. Verify `/me` against the configured account, then retain the returned access
   and refresh tokens plus the verified subject/tenant binding in the secure
   store.

Every Graph request checks the access-token expiry with a safety skew. An
expired or near-expiry token is refreshed before use and its `/me` identity is
rechecked. A single HTTP 401 on an idempotent read causes one forced refresh,
identity check, and replay; non-idempotent methods are never replayed. A second
authentication failure is returned as a normalized authentication error.
Refresh responses replace the old refresh token when Microsoft rotates it; if
no replacement is returned, the prior refresh token is retained.

`lee-kb auth revoke` deletes the local token grant. This prevents further use
by lee-kb and is idempotent at the storage boundary. Removing the user's app
consent in the Microsoft account is the separate provider-side revocation
operation; enterprise consent administration is outside this release.

## Token Storage And Disclosure

The default store is the operating system's Secret Service through
`secret-tool` on Linux. If no supported OS-protected store is available, the
default fails closed; it never writes a plaintext token file. An explicit
`EncryptedFileTokenStore` is available for a deployment that can supply its
32-byte master key from an OS-protected source. It uses AES-GCM, mode `0600`,
atomic replacement, authenticated account-associated data, and rejects broad
file permissions.

Token material is excluded from:

- Git and TOML configuration;
- `repr()` output and normalized exceptions;
- Graph error bodies, provider diagnostics, and logs;
- connector cursors and delta snapshots;
- knowledge items, chunks, citations, receipts, and query audit events; and
- live evidence captured for verification.

The token store is replaceable through `TokenStore` and `SecretStore`. Tests
use an injected in-memory store only; it is never selected by production
configuration.

## Request And Error Policy

`GraphClient` accepts an injected `HttpTransport`, so tests do not need network
access and future connectors do not implement their own HTTP stack. URLs are
restricted to HTTPS `graph.microsoft.com`, including continuation and delta
links; userinfo, credential-bearing query parameters, and fragments are
rejected. Outlook web locators use an even stricter no-query/no-fragment policy
and fall back to the canonical Graph message URI. Response bodies are parsed
only to extract bounded machine error codes; provider messages and raw bodies
are discarded.

The default retry policy is bounded and applies to network errors, 408, 409,
5xx responses, and 429/509 throttling. `Retry-After` is preferred and clamped
to the configured retry bound; otherwise exponential backoff is used. Token
endpoint calls use the same request pacing and bounded throttling retry policy;
ambiguous refresh failures are not replayed.
A 401 refreshes once for idempotent reads, 403 is authorization failure, 404 is
not-found, and 410 or known sync-state codes are `DELTA_EXPIRED` only in delta
operations. Malformed collections, missing links, repeated continuation links,
credential-bearing fragments, and invalid JSON fail closed.

The limiter runs before every request, including retries. It is deliberately a
small process-local spacing limiter for the personal, user-driven sync path;
it is not a claim about a tenant-wide quota or a background service.

## Delta And Checkpoint Safety

`GraphClient.delta_round()` follows every `@odata.nextLink` and returns only
after a final `@odata.deltaLink`. The link remains opaque and is passed back
unchanged on the next round. If Graph reports an expired delta, the client
starts a complete initial enumeration and marks the result `reset=True`.

The Outlook adapter compares that complete result with its metadata-only
cursor snapshot. Missing prior IDs become tombstones, current IDs are compared
for updates, and no cursor is emitted until the full enumeration and all
message fetches succeed. A failure leaves the last-known-good cursor and
projection available for retry.

For a non-empty round, the common sync path writes the final cursor in the same
transaction as the final item or tombstone. For an empty round it calls the
additive `Repository.advance_cursor()` operation and records the synchronized
project marker atomically. Unsupported repository providers fail closed instead
of fabricating an item or tombstone.

## Live Outlook Configuration

The CLI reads the normal config path. Tokens are not placed in this file:

```toml
schema = 1
owner = "lee@example.com"
database = "knowledge.sqlite"

[microsoft_graph]
client_id = "public-native-app-client-id"
tenant = "common"
scopes = ["Mail.Read", "User.Read"]

[microsoft_graph.accounts.personal]
user_id = "lee@example.com"

[outlook.inbox]
account = "personal"
folder_id = "<mail-folder-id>"
folder_name = "Inbox"
project = "default"
allowed_principals = ["employee:employee-zero"]
```

The operator flow is:

```bash
lee-kb auth login --account personal
lee-kb sync outlook inbox
lee-kb search "known email terms" --principal lee@example.com
lee-kb ask "what did I say about the launch review?" --principal lee@example.com
lee-kb auth revoke --account personal
```

The implementation is live-capable, but this repository's automated tests use
scripted HTTP and no real account. A real mailbox proof still requires the
operator to register/approve the public client, consent to `Mail.Read` and
`User.Read`, use an
OS secret service, and record sanitized synchronization evidence only.

## Read-Only Calendar Configuration

Calendar ingestion uses a separate Graph account binding with exactly
`Calendars.Read` and `User.Read`; `Mail.Read`, write scopes, and send scopes are
refused. The account binding therefore has its own token-store key even when it
resolves to the same Microsoft user:

```toml
[microsoft_graph.accounts.chief_of_staff_calendar]
user_id = "lee@example.com"
scopes = ["Calendars.Read", "User.Read"]

[calendar.chief_of_staff]
account = "chief_of_staff_calendar"
calendar_id = "<calendar-id>"
calendar_name = "Calendar"
start = "2026-08-08T00:00:00Z"
end = "2026-11-06T00:00:00Z"
project = "default"
allowed_principals = ["employee:employee-zero"]
```

The view window is fixed and is part of the connector identity. Each pass
enumerates that complete bounded view, compares deterministic normalized event
hashes with the metadata-only cursor, and emits created, updated, and deleted
events. The connector refuses duplicate IDs, events outside the declared
calendar/window, non-UTC Graph responses, malformed cursors, and checkpointing
after an incomplete pass. Event text includes schedule, organizer, attendees,
location, and body text; online-meeting and join URLs are not indexed.

```bash
lee-kb auth login --account chief_of_staff_calendar
lee-kb sync calendar chief_of_staff
lee-kb search "project review" --principal lee@example.com
lee-kb auth revoke --account chief_of_staff_calendar
```

`allowed_principals` is an explicit delegated knowledge grant; it does not
change the Graph token, mailbox/calendar scope, or owner. Private evidence is
released to the owner and only the listed stable employee principals. A later
sync applies a changed grant even when every source object is content-unchanged,
without re-chunking or exposing content. Other employees remain denied.

Automated coverage uses scripted transports and parser fixtures. A live proof
requires an operator-approved public client, delegated consent, and an actual
calendar ID; sanitized evidence must not include event content, tokens, device
codes, or join URLs.

## OneDrive Readiness Assessment

The shared layer is sufficient for a future selected-folder OneDrive
connector's authentication, request, pagination, throttling, and delta
mechanics. No OneDrive connector is implemented.

The future connector design should record:

- source identity as `(drive_id, item_id)`; drive identity is part of the
  connector scope and `driveItem.id` is the stable source object ID;
- parent folder identity as a relationship and locator, not as item identity;
- renames as metadata/source-locator changes on the same item ID;
- moves within a drive as parent relationship changes on the same item ID;
- cross-drive moves or copies as a new source identity unless provider
  evidence proves continuity;
- one opaque per-drive/folder delta link, with complete `410 Gone` resync and
  safe missing-item reconciliation;
- permissions from explicit sharing/inheritance facts, never inferred from a
  successful API call; and
- Office documents as bytes or provider exports passed to the existing
  deterministic parser policy, with unsupported embedded content failing
  closed.

Required follow-up before implementation is permission-change completeness,
selected-drive/folder scope accounting, download/export and format policy,
move/copy tests, and a real delta-expiry proof. Recommendation: **Ready after
the live Outlook proof and a OneDrive-specific permission/delta design review.**

## OneNote Readiness Assessment

OneNote remains design-only in this sprint. No OneNote connector, HTML parser,
resource downloader, or incremental synchronizer was added.

The future design should keep these identities explicit:

- notebook identity;
- section identity;
- page identity; and
- parent relationships between notebook, section, and page.

Page HTML must be normalized separately from Outlook mail text. The policy must
define safe HTML-to-text structure, headings and locators, embedded images and
files, resource size/type limits, and whether resources become relationships
or separately retrievable knowledge items. Raw HTML should not be passed to a
generic document parser without those decisions.

The reviewed Graph surface does not establish a OneNote-native delta feed with
complete deletion semantics. An implementation must prove a safe incremental
strategy, likely timestamp/polling or a provider mechanism discovered later,
before emitting a checkpoint. Permission inheritance and page-level sharing
also need an explicit fail-closed mapping. Recommendation: **Not ready for a
OneNote connector; design and provider evidence are the next required work.**
