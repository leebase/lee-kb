# Governed Multi-Principal Access — Operations Guide

> How to provision AI-employee principals, authenticate clients, grant and
> revoke knowledge sources, and inspect access evidence in lee-kb.

## Concepts

lee-kb separates five states that must never be conflated:

| State | Meaning | Where it is decided |
|-------|---------|---------------------|
| Authenticated | A client credential verified against server state | `AccessRegistry` (`access-clients.json`) |
| Authorized | The employee holds an active grant covering the source | `KnowledgePolicy` (`access-policy.json`) AND the item's source-owner ACL |
| Source available | The source root exists and is reachable | connector health |
| Projection fresh | The projection matches current source content | `kb_status` / `FreshnessReport` |
| Grounded | An answer cites released, receipted evidence | receipts + citations |

And three identities that must never be merged:

- **Principal** — who is acting (`employee:chief-of-staff`, `employee:employee-zero`, `human:lee`). Server-owned; never asserted by a client.
- **Client** — which authenticated runtime acts for that principal (`chief-of-staff:codex`, `chief-of-staff:jarvis`). Each has its own revocable credential; many clients may serve one principal and stay separately attributable in audit evidence.
- **Transport** — how a request arrives (MCP stdio, CLI, library). Transport confers no identity or authority: registering an MCP server grants nothing; every governed call requires a verified credential (employee mode) or the server-owned configuration (owner mode).

## Files (all owner-only, 0600)

| File | Contents |
|------|----------|
| `~/.config/lee-kb/config.toml` | sources, roots, per-root `allowed_principals` source-owner ACLs |
| `~/.config/lee-kb/access-policy.json` | employees + grants (hash-verified) |
| `~/.config/lee-kb/access-clients.json` | client credential verifiers (PBKDF2 digests only, never secrets) |
| `~/.config/lee-kb/knowledge.sqlite` | projection, receipts, `access_audit_events` |

## Provision an employee principal

```bash
lee-kb access employee add \
  --employee-id chief-of-staff \
  --principal employee:chief-of-staff \
  --tenant leebase --lane default --scope operations --purpose knowledge
lee-kb access employee list
```

## Authenticate a client for an employee

```bash
lee-kb access client register \
  --principal employee:chief-of-staff --client-id chief-of-staff:codex
```

The one-time secret is printed once and never stored. Save it to a private
file (`umask 077`) such as
`~/.config/lee-kb/secrets/chief-of-staff-codex.secret`.

Add another client for the same employee the same way with a new
`--client-id` (e.g. `chief-of-staff:jarvis`, `chief-of-staff:phone`). Each
client gets its own secret and its own audit identity.

## Grant a source

Granting requires BOTH layers, each Lee-owned:

1. **Source-owner ACL** — in `config.toml`, add the principal to the root:

   ```toml
   [roots.factory]
   allowed_principals = ["employee:chief-of-staff"]
   ```

   then `lee-kb sync` (a permission-only change propagates without
   re-chunking). Outlook/Calendar scopes use the same `allowed_principals`
   key on their source tables.

2. **Access grant** — bind the employee to the root:

   ```bash
   lee-kb access grant add \
     --principal employee:chief-of-staff \
     --project default --source-namespace local_files --root factory
   ```

   `--path-prefix` defaults to `*` (whole root); pass a directory prefix for a
   narrower grant. `--expires-days` bounds it in time. Grant context
   (tenant/lane/scope/purpose) is copied from the employee record server-side
   and cannot be set from flags.

Evidence is released only when grant AND source ACL both allow it; a grant
never overrides a source ACL, and no employee ever inherits the owner's
authority.

## Revoke

```bash
lee-kb access grant revoke --grant-id grant:chief-of-staff:factory  # one source
lee-kb access client revoke --client-id chief-of-staff:codex        # one client
```

Both take effect on the next request, including for already-running MCP
server processes (policy and credentials are re-read per call). Removing the
principal from a root's `allowed_principals` plus `lee-kb sync` revokes at
the source layer.

## Inspect access evidence

```bash
lee-kb access audit list --limit 50
```

Each row identifies event type, outcome, reason code, principal, client,
session reference, project, grant ids, query digest, and freshness state.
No evidence text or session bearer token is ever persisted in this plane:
queries are stored as SHA-256 digests and sessions as one-way references.

Two audit planes exist deliberately. The **access audit plane**
(`access_audit_events`) is digest-only as described above. The pre-existing
**retrieval receipt plane** (`retrieval_receipts`,
`retrieval_audit_events`) binds the full query text to each released
evidence item by design, so Lee can audit exactly what was asked; those
tables live in the owner-only (0600) projection, carry the same
client/session/grant provenance, and each receipt is echoed only to the
client that issued the query.

## How clients connect

Every client uses the same env contract against `lee-kb-mcp` (stdio MCP):

```
LEE_KB_CONFIG=~/.config/lee-kb/config.toml
LEE_KB_CLIENT_ID=<client id>
LEE_KB_CLIENT_SECRET_FILE=<private secret file>   # or LEE_KB_CLIENT_SECRET
```

Adding another employee or another client is configuration only — no new
transport or application code.

### Codex

```bash
codex mcp add lee-kb-chief-of-staff \
  --env LEE_KB_CONFIG=~/.config/lee-kb/config.toml \
  --env LEE_KB_CLIENT_ID=chief-of-staff:codex \
  --env LEE_KB_CLIENT_SECRET_FILE=~/.config/lee-kb/secrets/chief-of-staff-codex.secret \
  -- lee-kb-mcp
```

Registered and proven live 2026-08-13: a `codex exec` turn called
`kb_search` and produced a grounded, cited answer as
`employee:chief-of-staff`. Note: interactive Codex sessions gate MCP tool
calls behind its own approval UX; that is a Codex client policy, not a lee-kb
boundary property.

### Jarvis / Hermes (chiefofstaff profile)

The credential `chief-of-staff:jarvis` is provisioned and proven over the
wire. To wire the container, register an MCP server in the `chiefofstaff`
Hermes profile that runs `lee-kb-mcp` with the env contract above, mounting
the config, secret, and projection paths read-only into the container. Jarvis
then acts as `employee:chief-of-staff` — never as `employee:employee-zero`
and never with Lee's owner authority. Container wiring was deliberately not
performed in this slice; only the identity, credential, and boundary exist.

### Future phone/voice client

Provision a new client (`chief-of-staff:phone`), store its secret with the
phone bridge, and launch `lee-kb-mcp` with the same env contract. If the
bridge is remote, terminate transport security outside lee-kb; the credential
still identifies the client.

### Another AI employee

```bash
lee-kb access employee add --employee-id analyst --principal employee:analyst \
  --tenant leebase --lane default --scope operations --purpose knowledge
lee-kb access client register --principal employee:analyst --client-id analyst:codex
# add the principal to the roots it may see + lee-kb sync + grant add
```

No code changes, no new transport.

## Private Mail/Calendar (not granted; how to grant later)

The Outlook Inbox and Calendar sources currently list only
`employee:employee-zero` in `allowed_principals`. To later grant, e.g.,
calendar read to the Chief of Staff, Lee explicitly:

1. adds `"employee:chief-of-staff"` to `[calendar.chief_of_staff].allowed_principals`
   in `config.toml` and runs `lee-kb sync` (permission-only update), and
2. runs `lee-kb access grant add --principal employee:chief-of-staff
   --project default --source-namespace calendar:<scope-id> --root <root>`
   matching the calendar connector's namespace.

Both steps are explicit configuration; no application code changes. Until
both exist, calendar/mail evidence is denied to every non-granted principal
— proven by the 2026-08-13 negative wire tests.

## Owner mode and Employee Zero compatibility

A `lee-kb-mcp` process launched with only `LEE_KB_CONFIG` (no
`LEE_KB_CLIENT_ID`) keeps the original single-owner behavior: the configured
`owner` (Lee) is the retrieval principal. The Factory registration in
`ai-employee-factory/.mcp.json` continues to work unchanged. Employee-mode
and owner-mode never mix in one process.
