# Answer Architecture

> Normative design for the governed `answer()` surface.
> Contracts live in `src/lee_kb/answer_contracts.py`; they are verified by
> `tests/test_answer_contracts.py`. This document is to `answer()` what
> `docs/sprint-1-contracts.md` is to `retrieve()`.

`architecture.md` locks two retrieval surfaces. `retrieve()` returns an
`EvidenceBundle` with no LLM involved: cheap, structured, stable — the surface
for AI employees, Agent-Orch, and MCP clients that orchestrate their own
reasoning. `answer()` layers query planning and synthesis on top of it and
returns an `Answer`: ordered claims, each with its own citations and its own
confidence, plus the conflicts, absences, and receipt identifiers that make the
result auditable. It is the surface for humans who want an answer rather than
evidence rows.

The governing constraint is inherited, not new: **permissions enforce at
`retrieve()`, and every surface inherits them.** `answer()` adds no permission
logic of its own. It cannot widen scope, cannot bypass the evaluator, and
cannot see a chunk the authorization layer withheld. Everything below is
downstream of a bundle that has already been filtered, ranked, and receipted.

## Answer Pipeline

`answer()` is a thin, deterministic composition over the governed retrieval
path. It adds exactly three stages to the pipeline in
`skills/retrieval-development.md`, all of them after evidence assembly:

```text
question → plan → retrieve() → [evidence bundle]
        → claim assembly → conflict detection → confidence assignment
        → optional narration → Answer
```

Stage by stage:

1. **Plan.** Turn the question into a `RetrieveRequest`: query text, principal,
   project, `top_k`, metadata filters, freshness requirement. v1 planning is a
   pass-through — the question becomes the query. Planning never invents a
   principal and never widens `project`.
2. **Retrieve.** Call the existing `retrieve()` in `src/lee_kb/governance.py`
   unchanged. Permission evaluation, freshness evaluation, citation assembly,
   and receipt persistence all happen here and only here.
3. **Claim assembly.** Group the returned evidence into `Claim` objects. Each
   claim carries the citations that support it. Evidence that supports no claim
   is recorded as `OmittedEvidence` with a reason — it is never silently
   dropped.
4. **Conflict detection.** Compare claims pairwise; emit a `Conflict` for each
   disagreement, with no winner selected.
5. **Confidence assignment.** Label each claim, then the answer as a whole.
6. **Narration (optional).** Hand the assembled claims to a
   `SynthesisProvider` for prose. `answer()` defaults to the deterministic
   `DeterministicSynthesisProvider`; a caller may explicitly disable narration,
   in which case the `Answer` carries claims and no prose. A surface may
   explicitly opt into an `UNKNOWN` result when the retrieval provider fails;
   that path has no retry or hidden fallback.

The ordering matters more than the stage count. Claims are assembled from
evidence, so a claim cannot exist before the evidence that grounds it. Prose is
produced last, from claims that are already final, so narration can only
rephrase — it cannot add a claim, drop a citation, resolve a conflict, or
upgrade a confidence level.

## Evidence Model

`answer()` does not define a second evidence type. It references the evidence
`retrieve()` already produced, through two lightweight views:

| Type | Carries | Purpose |
|------|---------|---------|
| `EvidenceRef` | `chunk_id`, `source_locator` | One piece of evidence the answer considered. Derives `item_id` and `content_hash` through the chunk ID, so they can never disagree. |
| `OmittedEvidence` | an `EvidenceRef`, an `OmissionReason`, optional detail | Retrieved and permitted evidence that reached no claim. |
| `ReceiptId` | `knowledge_item_id`, `chunk_id`, `content_hash`, `retrieval_timestamp` | The identifying fields of one persisted `RetrievalReceipt`. |

Every `Answer` carries `evidence_used` and `evidence_omitted` as two disjoint
tuples. Recording omission is the point: an answer that presents three
citations out of ten retrieved chunks is making an editorial decision, and the
reader is entitled to know that seven other chunks were seen and why each was
set aside. `OmissionReason` enumerates `not_relevant`, `redundant`,
`superseded`, `stale`, `lower_authority`, and `budget`.

The answer also carries two aggregate, disclosure-safe governance signals from
the bundle: `withheld_count` reports how many provider candidates were denied
by permission filtering, and `truncated` reports that permitted candidates
exceeded the requested `top_k`. They contain no restricted titles, locators,
or source breakdowns and remain visible when the answer has ordinary claims.

The governed retrieval also persists a query-level `RetrievalAuditEvent`, so
empty, denied, mixed, stale-refused, and provider-failure outcomes remain
auditable even when no evidence receipt is released.

`ReceiptId` copies the four fields that stay resolvable after re-chunking — the
same four that make a `RetrievalReceipt` independently verifiable — and
deliberately omits the principal, project, and query. Those remain in the
durable retrieval receipt and query-audit records; duplicating governance state
onto every answer would create a second place for it to drift.

Evidence text is not copied onto the `Answer`. A claim quotes or paraphrases;
the citation is how a reader reaches the original. This keeps `Answer` small,
keeps the projection the single place source text lives, and avoids a stale
second copy of content that the next sync may have already changed.

## Confidence Model

Confidence is an **epistemic basis**, not a score. The four values are locked:

| Value | Meaning | Citations |
|-------|---------|-----------|
| `DIRECTLY_EVIDENCED` | The evidence states the claim. | ≥ 1 required |
| `SYNTHESIZED` | The claim combines or restates evidence that says it across sources or sections. | ≥ 1 required |
| `INFERRED` | The claim goes beyond what the evidence states. | ≥ 1 required |
| `UNKNOWN` | The claim could not be grounded at all. | none required |

Nothing here is a probability and nothing may be averaged. A 0.87 would invite
a threshold, and a threshold would quietly convert "the model reasoned past its
sources" into "confident enough to act on." These four labels answer a
different and more useful question: *what would I have to check to falsify
this?*

Two structural rules enforce the model:

- **A claim cannot be constructed without at least one citation unless its
  confidence is `UNKNOWN`.** Ungrounded assertions are not forbidden — they are
  sometimes the honest output — but they must be labelled, never presented at
  the same weight as evidenced text. This is the contract-level form of "no
  uncited assertion reaches a reader."
- **An answer is never more confident than its weakest claim.**
  `CONFIDENCE_RANK` orders the four values strongest to weakest, and `Answer`
  rejects an overall confidence stronger than the weakest claim it presents. An
  answer built from four directly-evidenced facts and one inference is an
  inferred answer.

`SYNTHESIZED` typically spans two or more citations, but the contract does not
require it: restating a single document across two of its sections is
legitimately synthesis, and a count-based rule would push honest labelling
toward whichever value passed validation.

## Conflict Handling

`architecture.md` is explicit: the retrieval engine does not detect
contradictions, and conflicting evidence is included in the bundle so synthesis
can surface it naturally — "source A says X, source B says Y." This contract
carries that decision one layer up and hardens it.

A `Conflict` holds two `ConflictSide` values. Each side carries its `Claim`
(and therefore that claim's citations and source locators), the
`source_timestamp` of the underlying material, and its declared `Authority`.
From those it derives exactly two read-only signals:

- `newer` — which side has the later source timestamp, or `NEITHER` on a tie.
- `more_authoritative` — which side carries the higher declared authority
  (`AUTHORITY_RANK` ranks canonical above derived), or `NEITHER`.

Both return a `Side` enum of `LEFT`, `RIGHT`, or `NEITHER`. **There is
deliberately no `winner`, `resolution`, or `resolved` field**, and
`tests/test_answer_contracts.py` asserts none exists. The two signals routinely
point in opposite directions — a newer derived note contradicting an older
canonical policy is the single most common real shape — and `signals_agree`
exists precisely to make that case visible. Picking a side automatically would
move a governance judgement out of the reader's hands and into a heuristic that
cannot see intent, cannot see which document the organization actually
operates by, and cannot be audited after the fact.

Conflict detection is deliberately positive, not authority-driven. The v1
deterministic implementation emits a conflict only when it sees polarity,
numeric or opposed value-word divergence, a recognized morphological antonym,
an otherwise-matching one-slot substitution, or explicit supersession. Declared
authority may describe an already-detected disagreement but cannot create one;
otherwise a canonical restatement of a derived statement would be reported as
conflict. Claim assembly uses the same signals to refuse a merge, so conflict
detection cannot be the only thing preventing a self-contradictory synthesized
claim.

A conflict may only reference claims the answer actually presents; `Answer`
rejects a conflict about a claim the reader never sees. Conflicts are reported
alongside the claims, not instead of them: both sides stay in `claims`, both
keep their citations, and the reader resolves the disagreement with the sources
in front of them.

## Provenance Guarantees

Four invariants are enforced at construction, so a malformed `Answer` cannot be
built at all — the failure surfaces where the answer is assembled, not in a
consumer's rendering code:

1. **Citation closure.** Every citation on every claim must reference a chunk
   listed in `evidence_used`. A claim cannot cite evidence the answer does not
   account for.
2. **Receipt closure.** The chunks covered by `receipt_ids` must be exactly the
   union of `evidence_used` and `evidence_omitted` — no more, no less. Every
   piece of evidence `retrieve()` released is accounted for as either used or
   omitted, and nothing is presented without a receipt behind it.
3. **Disjointness.** `evidence_used` and `evidence_omitted` cannot overlap, and
   neither may repeat a chunk. Evidence is used or omitted, never both.
4. **Attributed prose.** If `prose` is set, `synthesis_provider_id` must name
   the provider that produced it. Model-produced text is identifiable wherever
   it appears, consistent with `Trust.MODEL_PRODUCED` on citations.

Together these give the property the platform is built for: from any published
answer, a reader can walk every sentence back to a chunk, that chunk back to a
receipt, and that receipt back to the authoritative source object via its item
ID, content hash, and source locator — even after the projection has been
re-chunked and the chunk ID no longer resolves.

Two things `Answer` deliberately does **not** carry: source text (the citation
is the path to it) and the permission basis for each grant. The latter is
Sprint 1 Open Question 2 and stays deferred until the authorization layer can
populate it honestly rather than plausibly.

## Absence Semantics

An answer with no claims must say why. `Answer` enforces the shape: either it
has claims and no `absence`, or it has no claims, an `Absence`, and `UNKNOWN`
overall confidence. There is no third state, and no silent empty answer.

`AbsenceKind` has exactly three values, and **they must never collapse into
one**:

| Kind | Meaning | Constraint |
|------|---------|------------|
| `NOT_FOUND` | The corpus was searched and holds no evidence. | Must record `searched_projects`; `withheld_count` must be 0; the answer must have considered no evidence at all. |
| `INACCESSIBLE` | Evidence exists, but this principal may not see it. | Must report `withheld_count ≥ 1`. |
| `UNKNOWN` | The question could not be resolved — not planned into a retrievable query, a provider failed, or the result was uninterpretable. | No scope or count required. |

The collapse is what makes this a governance requirement rather than a
usability nicety. Reporting `INACCESSIBLE` as `NOT_FOUND` tells the principal a
lie about the corpus and hides that a permission boundary is the reason for the
silence. Reporting `UNKNOWN` as `NOT_FOUND` claims a search happened that never
did — the most dangerous of the three, because "we looked and there is nothing"
is the answer people act on. And reporting `NOT_FOUND` as `UNKNOWN` throws away
a real, useful negative result.

`INACCESSIBLE` walks a deliberate line: it says *that* something was withheld
without saying *what*. `withheld_count` is the only thing it may report — no
titles, no locators, no counts broken down by source, since a per-source
breakdown reconstructs the existence of specific restricted material. The count
maps directly onto `EvidenceBundle.denied_count`, which is where permission
filtering already becomes visible to an auditor.

## Synthesis Providers

`SynthesisProvider` is a `typing.Protocol` with a single method:

```python
def narrate(self, claims: tuple[Claim, ...]) -> str: ...
```

That single method is the whole seam, and its narrowness is the design. Claims,
citations, confidence levels, conflicts, and absences are all decided by the
pipeline *before* a provider is called. A provider receives finished claims in
presentation order and returns prose. It structurally cannot add a claim, drop
a citation, resolve a conflict, upgrade a confidence label, or reach evidence
the authorization layer withheld — because none of those are reachable from its
one argument.

This is what lets an LLM-backed provider be added later without touching the
pipeline: a new class implementing `narrate()`, registered by the caller. The
`Answer` records which one ran via `synthesis_provider_id`, so model-produced
prose stays attributable. No LLM dependency enters `answer_contracts.py`, which
remains standard-library-only in line with the project's dependency-approval
guardrail.

Implementations must preserve claim order, so a citation marker in the prose
still maps to the claim it came from. v1 ships with
`DeterministicSynthesisProvider` as its default provider: `answer()` returns
claims, citations, and deterministic template prose unless narration is
explicitly disabled. That keeps the first release LLM-free and consistent with
the locked decision to validate the evidence path with the fewest moving parts.

## Deferred Extensions

Explicitly out of scope for this contract, with the reason each can be added
later without redesign:

- **LLM synthesis provider.** Blocked on dependency approval, the same
  guardrail that gates the office-format parsers. The `SynthesisProvider`
  protocol is the entire integration point; nothing else changes.
- **Real query planning.** v1 planning is a pass-through. Decomposition,
  multi-query retrieval, and follow-up questions change how the
  `RetrieveRequest` is built, not what an `Answer` looks like.
- **Permission basis on receipts.** Sprint 1 Open Question 2. When the
  authorization layer can report *why* access was granted, the field is added
  to `RetrievalReceipt` and flows into `ReceiptId` without touching `Answer`.
- **Multi-way conflicts.** `Conflict` is pairwise. Three sources disagreeing
  three ways is representable today as three pairwise conflicts; a clustered
  n-way type is a later convenience, not a missing capability.
- **Answer-level receipts.** Today the audit trail is the per-evidence
  retrieval receipts. A distinct "an answer was produced" record — with the
  provider, prose hash, and claim count — belongs with the same governance work
  that adds permission basis.
- **Cross-project answers.** `MetadataFilters.projects` can widen a query and
  `Answer` carries a single `project`. Whether v1 permits this at all is Sprint
  1 Open Question 1, and it stays open here rather than being settled by a
  contract detail.
- **Streaming and caching.** `Answer` is a complete, immutable value.
  Incremental delivery and reuse are transport and performance concerns for the
  surfaces, and neither changes the contract.
