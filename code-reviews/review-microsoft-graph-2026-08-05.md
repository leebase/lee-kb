# Independent Security/Reliability Review - Microsoft Graph Foundation - 2026-08-05

## Scope

Reviewed the Microsoft Graph foundation, authentication and token lifecycle,
Graph HTTP client, live-capable Outlook mapping and sync path, repository cursor
advancement, focused tests, and the requested product/architecture documents.
The reviewed implementation is still offline-tested only; no real Microsoft
account, consent, mailbox, or external request was used.

The shared Graph package has several sound controls: the default token store
fails closed without an OS secret service, the explicit file store uses
AES-GCM and mode 0600, token `repr()` values are redacted, token sets are bound
to a configuration fingerprint, refresh-token rotation is retained, local
revocation deletes stored state, Graph error bodies are not included in normal
error text, and repository cursor-only advancement is transactional.

## Checks Run

| Command or check | Result |
|---|---|
| `python3 -m pytest tests/test_microsoft_graph.py tests/test_outlook_connector.py tests/test_repository.py -q` | 39 passed |
| `python3 -m pytest tests/ -q` | 337 passed |
| Focused Ruff check over Graph, Outlook, sync, repository, and tests | Clean; existing top-level-settings deprecation warning only |
| Focused Black check | Clean; 14 files unchanged |
| Focused `compileall` | Clean |
| `python3 tools/check_disclosure.py` | Clean for tracked-file patterns |
| CLI help/version/auth/sync smoke checks | Passed; version `lee-kb 0.1.0` |
| `git diff --check` | Clean |
| Read-only behavioral probes | Reproduced MG-R-01, MG-R-03, MG-R-04, MG-R-06, MG-R-07, and MG-R-10 below |

## Findings

### MG-R-01 - High - Outlook permission owner is independently configurable

**Location:** `src/lee_kb/main.py:585-604`,
`src/lee_kb/connectors/outlook.py:416-422`, and
`src/lee_kb/connectors/outlook_graph.py:93-105`.

**Reproduction:** Configure the Graph account as `lee@example.test`, but set
the Outlook source's optional `mailbox_owner` to `mallory@example.test`.
`GraphOutlookTransport.health()` verifies only the Graph `/me` identity and
folder, while `OutlookConnector.permissions()` uses the configured
`mailbox_owner`. The sync therefore accepts Lee's Graph mailbox and writes
`PermissionSet(owner="mallory@example.test")`. A read-only probe confirmed that
the configured permission owner and verified Graph user can differ.

**Impact:** The common governance layer can release content fetched from Lee's
mailbox to the Mallory principal. This is an unauthorized-evidence failure at
the live connector boundary, not merely a display-label mismatch.

**Remediation:** Remove the independent owner override or require it to equal a
verified `/me` identity after normalization. Build `OutlookScope` from the
verified Graph identity, and add a CLI/integration regression proving a mismatch
fails before any projection or cursor write.

### MG-R-02 - Medium - Token binding proves configuration identity, not token subject or tenant

**Location:** `src/lee_kb/microsoft_graph/models.py:89-100`,
`src/lee_kb/microsoft_graph/auth.py:263-276`, and
`src/lee_kb/microsoft_graph/client.py:198-210`.

**Reproduction:** `OAuthTokenManager.login()` stores the device-flow token after
only adding the configured fingerprint. It does not call `verify_account()` or
persist a verified provider subject/tenant. `GraphClient.get_json()` also does
not require `verify_account()`; the check is only reached incidentally by the
CLI Outlook health path at `src/lee_kb/main.py:683-688`. A scripted login can
therefore store a token obtained by another user while its configuration binding
matches the configured account.

**Impact:** A wrong-user token is stored as if it belonged to the configured
account, and library callers or future connectors that skip the advisory health
call can query the wrong mailbox. The configured tenant is included in the hash
but is not checked against the provider token or a verified provider identity.
The current CLI rejects many wrong-user cases during health, but the shared
foundation does not enforce the invariant itself.

**Remediation:** Verify the provider subject and tenant before persisting a new
grant, retain the verified provider identifiers in the bound token record, and
make Graph resource use require that verification rather than relying on an
optional health call. Add wrong-user and same-user/different-tenant tests.

### MG-R-03 - Medium - Cursor scope is not bound to the Graph credential and legacy cursors remain accepted

**Location:** `src/lee_kb/connectors/outlook.py:831-860`,
`src/lee_kb/connectors/outlook.py:904-922`, and
`src/lee_kb/connectors/outlook.py:393-397`.

**Reproduction:** Create a current cursor, remove `connector_id` and
`mailbox_owner` while retaining version 1, and pass it to another connector
with the same folder ID. The cursor is accepted. New cursors bind only the
connector string, folder, and mailbox owner; they do not bind account ID, tenant,
client ID, scopes, or the Graph credential fingerprint. An explicitly supplied
connector ID can also collide across account configurations.

**Impact:** Reusing old or colliding state can apply the wrong delta token and
metadata snapshot to another account. Depending on provider response, this can
produce wrong updates/tombstones or stale cross-account projection state. The
current code fails closed for some provider-side token mismatches, but it does
not reject the scope mismatch before making the request. The existing Outlook
review documented this as a deferred legacy-cursor decision; live wiring now
makes the decision operationally relevant.

**Remediation:** Version the cursor format and reject unbound version-1 cursors
before live use. Include a verified account/tenant/credential binding in every
new cursor and derive the connector ID from that binding rather than accepting a
colliding override. Add cross-account, cross-tenant, and restart tests.

### MG-R-04 - Medium - Provider URLs can disclose credentials through citations and cursors

**Location:** `src/lee_kb/connectors/outlook_graph.py:169-201`,
`src/lee_kb/connectors/outlook.py:284-288`,
`src/lee_kb/connectors/outlook.py:816-822`, and
`src/lee_kb/connectors/outlook.py:904-919`.

**Reproduction:** Return a Graph message with
`webLink="https://outlook.office.com/mail?access_token=embedded-secret"`.
The adapter accepts it as the source locator, and the encoded cursor contains
the complete URL. A read-only probe confirmed `access_token=embedded-secret`
was present in the cursor. The sync token-shaped-content scan covers document
content and title in `src/lee_kb/main.py:424-426`, not the source locator.

**Impact:** A provider-controlled or malformed URL containing a session or
credential value is persisted in SQLite cursor state and knowledge-item
metadata, then can be returned in citations, receipts, evidence, or CLI output.
It also permits arbitrary schemes/hosts as source citations. This contradicts
the documented disclosure boundary even though normal Microsoft web links are
usually benign.

**Remediation:** Validate Graph web links as safe HTTPS Outlook URLs with no
userinfo or credential-bearing query parameters; otherwise use the canonical
Graph message URI. Validate the final delta link before cursor persistence and
scan all locator fields for secret-shaped material. Add cursor, citation, and
receipt disclosure regressions.

### MG-R-05 - Medium - Outlook configuration does not enforce least-privilege Mail.Read

**Location:** `src/lee_kb/connectors/outlook.py:59`,
`src/lee_kb/main.py:515-542`, and
`src/lee_kb/microsoft_graph/auth.py:116-122`.

**Reproduction:** Configure scopes as `Mail.ReadWrite`, `Mail.Send`, or
`Files.ReadWrite.All`. `_graph_credential()` accepts them and the device flow
requests them; the exported `GRAPH_DELEGATED_SCOPE = "Mail.Read"` is never
used for validation.

**Impact:** The read-only Outlook connector can prompt for substantially broader
mail, send, or cross-resource privileges than its approved boundary requires.
This widens consent and increases the consequence of a future transport bug,
even though the current mapper issues read requests only.

**Remediation:** Enforce the approved Outlook scope set at the Outlook
composition boundary, at minimum requiring `Mail.Read` and rejecting write,
send, application-wide, or unrelated-resource scopes. Use separately scoped
credentials for a future OneDrive connector and test rejected configurations.

### MG-R-06 - Medium - Retry-After bypasses the configured retry-time bound

**Location:** `src/lee_kb/microsoft_graph/client.py:38-54`,
`src/lee_kb/microsoft_graph/client.py:337-339`, and
`src/lee_kb/microsoft_graph/client.py:472-485`.

**Reproduction:** Return HTTP 429 with `Retry-After: 999999` and a retry policy
with `max_delay=2`. The client passes `999999.0` directly to its sleep callback.
The retry count is bounded, but the wait is not.

**Impact:** A malformed, malicious, or unexpectedly large provider header can
hold a user-driven sync indefinitely while retaining the process and pending
state. The documentation calls the policy bounded, but only fallback
exponential delay is bounded.

**Remediation:** Parse finite values only, clamp `Retry-After` to a configured
maximum (normally `RetryPolicy.max_delay`), and enforce a total retry deadline.
Add numeric, date, infinite, and oversized-header tests.

### MG-R-07 - Medium - Token refresh requests bypass Graph retry, pacing, and throttling handling

**Location:** `src/lee_kb/microsoft_graph/auth.py:320-361` and
`src/lee_kb/microsoft_graph/client.py:297-305` and `329-335`.

**Reproduction:** Make `OAuthTokenManager._refresh()` receive a network,
429, or 5xx response. The token manager raises a `GraphError` from its single
form request; `GraphClient` obtains the token before its retry loop and only
catches `CredentialError` around forced refresh. A read-only probe of a
throttled token manager recorded no retry sleep.

**Impact:** An expired-token sync fails immediately on a transient identity
endpoint failure instead of using the shared bounded retry and pacing policy.
The same gap affects the one forced refresh after a Graph 401. No cursor is
advanced, so this is fail-safe but unnecessarily unavailable and can make a live
proof fail during normal throttling.

**Remediation:** Give token endpoint calls an explicit bounded retry and limiter
policy, or make token acquisition participate in the client's policy while
preserving non-retryable credential errors. Add refresh 429/5xx/network tests,
including rotation and revocation outcomes.

### MG-R-08 - Medium - Delta expiry on a continuation page does not restart reconciliation

**Location:** `src/lee_kb/microsoft_graph/client.py:221-228`,
`src/lee_kb/microsoft_graph/client.py:244-266`, and
`src/lee_kb/microsoft_graph/client.py:269-287`.

**Reproduction:** Start a cursor delta round with a page containing
`@odata.nextLink`, then return HTTP 410 with a known delta-expiry code for that
continuation request. `reset_url` is cleared after the first page, so the client
raises `DELTA_EXPIRED` and never requests the initial enumeration. The same
limitation exists for the generic collection iterator.

**Impact:** A large or slow round whose continuation state expires fails instead
of performing the documented complete reconciliation. The last cursor and
projection remain safe, but availability and recovery are not guaranteed for
the full paging path.

**Remediation:** Retain the reset URL for the complete delta round and restart
once on expiry from any delta continuation, clearing accumulated values before
the reset. Keep non-delta collection behavior explicit and add a multi-page
continuation-expiry regression.

### MG-R-09 - Medium - Public Graph requests retry non-idempotent methods

**Location:** `src/lee_kb/microsoft_graph/client.py:180-196`,
`src/lee_kb/microsoft_graph/client.py:306-340`, and
`src/lee_kb/microsoft_graph/client.py:38-40`.

**Reproduction:** Call `request_json("POST", ...)` with a body and return a
retryable 503 or 429 followed by success. The client replays the request even
though the retry policy is documented as being for safe GET requests.

**Impact:** The current Outlook path is read-only, but a future OneDrive or
other Graph connector can duplicate a write or action when a server processed
the request before returning a transient response. The shared foundation does
not enforce its stated safety assumption.

**Remediation:** Restrict the retrying client to GET/read operations, or require
an explicit idempotency/replay-safe policy for each method and use provider
idempotency keys where available. Add a test proving non-idempotent methods are
not silently replayed.

### MG-R-10 - Medium - Callers can replace the authenticated Authorization header

**Location:** `src/lee_kb/microsoft_graph/client.py:297-304`.

**Reproduction:** Pass `headers={"Authorization": "Bearer caller-token"}` to
`request_json()`. The caller headers are merged after the token manager creates
the authenticated header, so the injected value is sent instead. A read-only
probe recorded `Bearer caller-token` on the HTTP request.

**Impact:** The shared Graph client no longer guarantees that requests use the
credential/account selected by its token manager. A connector or future plugin
can accidentally bypass account binding, produce cross-account data, or leak a
caller-provided bearer value to Graph.

**Remediation:** Reject `Authorization` and other reserved security headers from
caller input, or merge caller headers first and set the managed Authorization
header last. Add a case-insensitive reserved-header regression.

### MG-R-11 - Medium - HTTP response and complete-delta memory are unbounded

**Location:** `src/lee_kb/microsoft_graph/http.py:49-69`,
`src/lee_kb/microsoft_graph/client.py:247-267`, and
`src/lee_kb/microsoft_graph/client.py:372-381`.

**Reproduction:** `UrllibHttpTransport` reads each response to EOF, and
`GraphClient.delta_round()` retains every value from every page before returning
it. There is a page-count limit but no response-byte, item-count, or aggregate
byte limit.

**Impact:** A very large message body, error response, or provider response can
consume excessive memory during a user sync. The initial Outlook delta selects
body content and then the adapter also fetches messages, making the aggregate
particularly costly. A remote response can therefore cause a local denial of
service without violating the page-count limit.

**Remediation:** Add bounded response-body and aggregate limits, reject oversized
JSON before parsing, and use a streaming/page callback or bounded reconciliation
strategy for large rounds. Add oversized success/error and aggregate-page tests.

### MG-R-12 - Low - HTTP 410 is classified as delta expiry for every Graph operation

**Location:** `src/lee_kb/microsoft_graph/client.py:413-424`.

**Impact:** A 410 from message fetch, folder health, or another non-delta
resource is reported as `DELTA_EXPIRED`. The Outlook mapper then treats it as a
temporary inaccessible read rather than a resource-specific gone/not-found
condition. This is fail-closed but makes error handling and operator evidence
misleading.

**Remediation:** Pass operation context into error normalization and classify
410 as delta expiry only for delta requests or recognized delta state errors.
Add non-delta 410 mapping tests.

### MG-R-13 - Low - Live Graph mapping does not implement the documented attachment metadata

**Location:** `src/lee_kb/connectors/outlook_graph.py:23-37`,
`src/lee_kb/connectors/outlook_graph.py:71-82`, and
`src/lee_kb/connectors/outlook_graph.py:169-201`.

**Impact:** The offline adapter supports attachment relationship metadata, but
the live Graph select set does not request `hasAttachments` or `attachments`,
and message fetch does not enumerate the attachment relationship. The live path
therefore silently emits no attachment relationships even though the Outlook
documentation describes them as retained. Attachment bytes remain correctly
out of scope; this is a metadata parity gap.

**Remediation:** Either explicitly mark live attachment metadata unsupported for
this sprint or add a bounded metadata-only attachment request and regression
coverage. Do not add attachment bytes without a separate policy review.

## Boundary Review

OneDrive remains a readiness assessment only. No OneDrive connector, drive-item
mapping, download path, or permission implementation was found. The Graph client
is reusable for its basic HTTP/pagination/delta mechanics, but the documented
drive identity, parent/move, permission, content, and resync questions remain
appropriately open.

OneNote remains explicitly unimplemented. No OneNote connector, HTML/resource
parser, or incremental synchronization path was found, and the Graph layer does
not depend on OneNote assumptions. This boundary is correct.

## Verdict

**Fail.** One High finding remains: MG-R-01 can release one verified mailbox's
content under a different configured principal. No Critical finding was found.
The Medium findings are fail-safe in several cases but must be addressed before
calling the foundation production-ready; the real account proof must remain
blocked until the High finding and cursor/account binding decision are closed.

The clean automated checks establish offline behavior only. They do not prove
Microsoft consent, token subject/tenant binding, immutable-ID behavior, real
throttle responses, real delta expiry, or mailbox body/attachment semantics.
