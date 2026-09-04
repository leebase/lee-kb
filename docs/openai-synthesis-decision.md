# OpenAI Synthesis Decision Package

This package now contains the source-bounded provider core, not a live
integration. The deterministic `SynthesisProvider` remains the reference path;
`lee_kb.synthesis.OpenAIResponsesSynthesisProvider` is opt-in and receives an
already-approved client through dependency injection. No model client is
declared by this package.

## Approval Gate

| Decision | Required value before live wiring | Status |
|---|---|---|
| Client | Exact client or adapter name, pinned version, and installation source; official SDK or standard-library HTTP must be an explicit choice | ⬜ Not approved |
| Model | Exact model ID | ⬜ Not approved |
| Cost ceiling | Per-request and aggregate ceiling, with input/output token bounds and cap-exhaustion behavior | ⬜ Not approved |
| Route / API project | Exact API route, organization/project boundary, and permitted egress | ⬜ Not approved |
| Credential / secret boundary | Exact secret store and resolution path; plaintext file and environment fallback policy | ⬜ Not approved |
| Telemetry | Metadata-only fields, sink, retention, and access policy; no source content, prompts, credentials, or sensitive diagnostics | ⬜ Not approved |
| Retry policy | Maximum attempts, request deadline, backoff, and eligible failure classes | ⬜ Not approved |
| Opt-in surface | Library-only injection or an explicitly named CLI/configuration opt-in; default behavior must remain unchanged | ⬜ Not approved |
| Runtime dependency | No dependency is added to `lee-kb` until the client decision is recorded | ✅ None added |


## Live-wiring approval worksheet

This is a decision package, not an approval. A blank or unchecked row is a
blocker. Existing Microsoft Graph approvals do not authorize a synthesis client,
model, route, credential path, telemetry sink, or retry policy.

Before any live wiring, the operator must record:

- **Client and version:** the exact package or adapter, pinned version, and
  installation source; choose the official SDK or a standard-library HTTP
  adapter.
- **Model and cost:** the exact model ID, input/output token bounds,
  per-request and aggregate cost ceilings, and the behavior when a ceiling is
  reached.
- **Route and project:** the exact API route, organization/project identifier,
  allowed egress boundary, and whether the caller-owned client enforces them.
- **Secret boundary:** the exact secret store and lookup operation, process
  access policy, rotation/revocation owner, and whether any file or environment
  fallback is prohibited. The live implementation must not invent a fallback.
- **Telemetry:** the approved metadata-only fields, sink, retention, access
  controls, and redaction behavior. Prompts, claim text, source locators,
  credentials, response bodies, and sensitive diagnostics are excluded.
- **Retries:** maximum attempts, total deadline, backoff, and the exact
  retryable response/error classes. No unbounded or hidden retry is permitted.
- **Opt-in surface:** whether the approved path is library-only dependency
  injection or includes a named CLI/configuration opt-in. The existing
  deterministic `lee-kb ask` path is not replaced.
- **Approver and date:** the human approver, decision date, and any controlled
  endpoint evidence required before release.

The Builder may implement the smallest injected wrapper only after every
required row has a recorded value and approval. The wrapper must retain the
existing source-bounded prompt, ordered-marker validation, `UNKNOWN` failure
semantics, freshness closure, receipt accounting, permission-before-synthesis
ordering, and no-fallback rule.

## Contract

The provider will implement only `SynthesisProvider.narrate(claims)`. It will
receive finalized, permission-filtered claims in presentation order, not raw
repository access. The source-bounded prompt must require:

- use only the supplied claim text;
- preserve claim order and citation markers;
- state both sides of every conflict without selecting a winner;
- preserve an authoritative `NOT_FOUND` claim only when the deterministic
  absence classifier supplied it;
- never invent a citation, source, permission, freshness value, or resolution;
- return a bounded failure rather than silently falling back to another model
  or to uncited prose.

Conflict detection, claim assembly, absence classification, authorization,
and citation closure remain deterministic and complete before generation.

## Telemetry and Tests

The provider core records no source content, credentials, or operational
telemetry. A live client wrapper must record only provider ID, model ID, request
and response token counts, duration, finish reason, retry count, and estimated
cost, subject to operator approval.

The `Answer` retains `synthesis_provider_id`, claims, confidence, citations,
freshness, and retrieval receipt IDs independently of provider prose. Provider
errors become `UNKNOWN` with explicit `SYNTHESIS_FAILURE` omissions and no
fallback.

Tests use a deterministic in-process Responses client double that records the
bounded claim request and returns fixed prose. No offline test requires network
access, an API key, or an external dependency. A live-provider test, if
approved, remains opt-in and isolated from the reference suite.

## Decision

The product behavior is approved with these constraints: retrieval stays
deterministic and permission-filtered; the provider receives finalized claims
only; generated prose must preserve ordered citation markers; claims,
confidence, freshness, and retrieval receipts remain on `Answer`; and any
provider failure is `UNKNOWN` with no hidden fallback or fabricated prose.

The source-bounded provider core is implemented. Live runtime wiring remains
gated on the exact client/version, model and cost ceiling, organization route,
credential/secret path, telemetry, and retry policy.

## 2026-08-09 Core implementation

`src/lee_kb/synthesis.py` implements
`OpenAIResponsesSynthesisProvider` without importing the OpenAI SDK. It formats
the finalized claim tuple into a bounded request, excludes source locators and
permission facts, validates bounded ordered markers in the response, and raises
`SynthesisProviderError` when the response cannot be grounded. `answer()` turns
that error into an `UNKNOWN` answer while preserving the retrieval freshness
report and receipt accounting.


## 2026-08-09 Approval Review

The package was rechecked against the current `SynthesisProvider` seam and the
official Responses API references. The safe implementation boundary is still
the finalized `Claim` tuple: the provider receives no repository, raw
evidence, permission facts, or source locators beyond the citation markers
already represented in the claims.

Live runtime wiring remains blocked on these explicit operator decisions:

- [ ] approve the exact client and pinned version, or choose a standard-library
  HTTP implementation instead;
- [ ] approve a specific model ID and cost ceiling;
- [ ] approve the organization API project and server-side key-management path;
- [ ] approve OS-protected secret resolution, with no file or environment
  fallback;
- [ ] approve metadata-only telemetry and bounded retry values;
- [x] use a deterministic in-process provider double and keep live tests
  opt-in and isolated from the reference suite.

### Blocking state confirmed 2026-08-09

No exact client/version, model ID, cost ceiling, route/API project, secret
resolution path, telemetry sink, retry policy, or live opt-in surface is
recorded in the current package or sprint/project memory. The only approved
test path is the deterministic in-process Responses client double. Therefore
this work unit adds no SDK, credential loader, network call, live CLI flag, or
production route.


Official references:

- <https://platform.openai.com/docs/api-reference/responses>
- <https://platform.openai.com/docs/quickstart?api-mode=responses&lang=python>

Until the live-wiring boxes are checked, the deterministic provider remains the
default and the injected provider is available only to callers that supply an
approved client. No dependency, credential loader, model selection, or live
integration is added by this package.
