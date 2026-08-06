# OpenAI Synthesis Decision Package

This is a prepared implementation package, not an implementation. The
deterministic `SynthesisProvider` remains the reference path and no model
client is declared by this change.

## Approval Gate

| Decision | Proposed value | Status |
|---|---|---|
| Client | Official `openai` Python client using the Responses API | Requires explicit dependency approval |
| Model | A currently approved small, low-latency OpenAI model; candidate `gpt-4.1-mini` | Requires model approval and cost review |
| Route | Organization API project with server-side key management; no personal subscription path in the library | Requires operator/security approval |
| Runtime dependency | Exact client version pinned in `pyproject.toml` only after approval | Not added |

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

The eventual provider should record provider ID, model ID, request and response
token counts, duration, finish reason, retry count, and estimated cost without
recording source content in operational logs. The `Answer` must retain
`synthesis_provider_id`; provider errors must produce `UNKNOWN`, never a hidden
fallback or a fabricated answer.

Tests will use a deterministic in-process provider double that records the
claims it received and returns fixed prose. Offline tests will continue to use
`DeterministicSynthesisProvider`; no test will require network access or an API
key. A live-provider test, if approved, will be opt-in and isolated from the
reference suite.

## Decision

Do not implement until Office ingestion, S3-R-04, and S3-R-05 are independently
reviewed with zero unresolved High/Critical findings and the deterministic
suite remains green. Current status: dependency, model, and route approvals
are not yet recorded, so this package is a follow-on decision gate.
