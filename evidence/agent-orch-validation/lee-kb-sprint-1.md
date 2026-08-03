# Agent-Orch Validation Evidence — lee-kb Sprint 1

> First substantial governed software project completed by Agent-Orch under
> realistic conditions: product architecture work, contracts, implementation,
> a mixed multi-model crew, independent verdict-gated review, real repairs,
> human approval, and recovery from an infrastructure failure. Recorded
> 2026-08-03 as reusable evidence for the AI Employee Factory.

## What was built

One governed retrieval path for the lee-kb knowledge fabric: local documents →
normalized SQLite projection → BM25 lexical retrieval with fail-closed
authorization, citations, freshness, and persisted retrieval receipts — plus a
golden evaluation harness with an honestly recorded baseline. 109 tests,
`black`/`ruff` clean, review verdict clean.

## The playbook

`playbooks/sprint_01_personal_foundation.yaml` — 10 steps, validation-first:

- Structural + system gates on every step (pytest with
  `require_collected_tests`, import checks, heading checks).
- A `human_approval` gate after the contracts step (Lee approved).
- A machine-gated review verdict (`review_verdict_clean`, threshold High) so
  review findings block completion instead of being prose.

**Mixed crew, cost-tiered:** claude_code **opus** for the two
judgment-critical steps (contracts design, independent review); claude_code
**sonnet** for governed build steps (connector, governance, CLI,
verification); **codex_cli gpt-5.6-sol high** for three implementation steps
(repository, chunking/retrieval, golden corpus); codex as token-exhaustion
fallback for every claude step.

## Outcome by the numbers

| Measure | Value |
|---|---|
| Final state | `COMPLETED`, review verdict `pass` |
| Build steps (1–9) | All passed; 8 of 9 on first attempt (contracts step passed on attempt 2 after a validation-caught packaging error) |
| Governed review cycles | 3 (fail → fail → pass) |
| Gating (High) findings | 3 — all true positives, all reproduced by the reviewer, all repaired and re-verified |
| False-positive gating findings | 0 |
| Advisory findings carried forward | 11 (5 Medium, 6 Low) |
| Human interventions in code | 0 — repairs were performed by the operator agent from reviewer evidence; the human approved contracts and set priorities |
| Infrastructure failures survived | 1 hard reboot mid-review; no governed work lost |
| Test suite at close | 109 passed; baseline metrics independently recomputed by the reviewer and reproduced exactly |

## The three High findings (all true positives)

1. **S1-R-01 — ungoverned public `retrieve()`** (`retrieval.py`). A second
   public evidence surface bypassed permission evaluation and receipt
   persistence. The reviewer *reproduced* it: principal `mallory` read a
   private item through the ungoverned path while the governed path denied
   it. 100+ passing tests did not catch this; the verdict gate did. Repair:
   ungoverned paths deleted, `LexicalRetriever` reduced to a candidate
   provider, plus a package-wide sweep test asserting the governed surface is
   the only public `EvidenceBundle` producer.
2. **S1-R-10 — discovery/fetch containment disagreement + fragile sync**
   (`connectors/local_files.py`, `main.py`). `discover()` handed out
   symlinked objects that `fetch()` would refuse, and one unfetchable object
   aborted an entire sync pass. Repair: shared containment rule at discovery,
   per-object skip-and-report in the sync loop.
3. **S1-R-11 — AND matcher inflated the retrieval baseline**
   (`repository.py`). Requiring every query token to co-occur made
   extract-style questions look great and paraphrase questions fail. Repair:
   OR-of-content-tokens with stopword stripping, BM25-ranked, strict AND kept
   as an explicit mode; corpus rewritten as paraphrases; baseline honestly
   re-recorded from 85.0% hit-at-1 / 0.925 MRR to **60.0% hit-at-1 / 0.766
   MRR**. The lower number is the valuable one: Phase 2 semantic retrieval
   now has a real target instead of a saturated benchmark.

## The governance loop, as executed

```
Implementation (steps 1–9, mixed crew, all gates green)
  ↓
Independent review  → FAIL (S1-R-01, reproduced)
  ↓
Root cause → repair → commit (operator agent, no human debugging)
  ↓
Independent review  → FAIL (S1-R-10, S1-R-11)
  ↓
Root cause → repair → re-record baseline → commit
  ↓
Independent review  → PASS (verdict clean; 11 advisory findings recorded)
  ↓
COMPLETED
```

## Interruption and recovery

A hard reboot of the Linux host killed the run executor and the reviewer
worker mid-review. The workspace, commits, step evidence, and approval records
all survived; the governed state lived in the run directory, not in any model
session. Recovery was `resume-run` on the failed parent run, which minted a
clean continuation inheriting all passed steps.

**Platform defect found (worth fixing in Agent-Orch):** continuation runs
created by `resume-run` record `launch: null` — no executor pid — so a
continuation whose executor dies uncleanly becomes a permanently stuck
`RUNNING` run that `resume-run` refuses. Recovery required abandoning the
orphaned continuation and re-resuming its parent. Fix: record executor
launch metadata on resume-created runs (the OS1 operator-recovery contract's
gap, hit in the wild).

## Reviewer-side observations

- One reviewer reporting error occurred (cycle 2): the verdict's
  `checks_run` claimed a pytest exit code contradicting the authoritative
  system-validator record. Agent-Orch's validator-authority rule caught it —
  the platform treats worker narration as untrusted even when the worker is
  the reviewer. It did not recur on the passing cycle.
- The default 600s worker timeout was too short for a whole-slice opus
  review; the operator raised it to 1200s for review steps. Future playbooks
  should set review-step timeouts explicitly.

## Operator interventions (the monitor → root-cause → repair → resume loop)

1. Approved-and-resumed past the human gate at Lee's direction.
2. Learned that `resume-run` mints continuation run IDs (a monitor watching
   the parked parent goes blind); monitors must track the newest run.
3. Repaired S1-R-01 and resumed (cycle 2).
4. Recovered from the reboot: abandoned the orphaned continuation, re-resumed
   the parent (cycle 3 setup).
5. Repaired S1-R-10/S1-R-11, re-recorded the baseline, resumed (cycle 3,
   pass).

## What this run did NOT prove

- **Parity with the deployed Employee Zero knowledge base.** This checkout
  never synchronized real data; the connector ran against fixtures and a
  scratch corpus. The Sprint 2 acceptance test is pointing the config at the
  real `sources.toml` (~1,200 documents, 15 roots) and answering Lee's daily
  questions.
- **Office formats.** Contracts and the handler registry support
  .docx/.xlsx/.pptx without redesign, but no parser is registered pending
  dependency approval — such files are currently invisible to sync.
- **The curated golden benchmark.** The committed corpus proves the
  evaluation framework; the benchmark exists only when Lee's real recurring
  Chief of Staff questions are in it.
