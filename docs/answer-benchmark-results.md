# Answer Benchmark Results

> Benchmark evidence for the governed `answer()` surface (`src/lee_kb/answer.py`),
> assembled entirely from the synthetic fixtures in `tests/answers/test_answer_benchmarks.py`.
> No content from Lee's private corpus appears anywhere in this document, per the
> publication rule in `skills/documentation.md`.
>
> This revision follows the repair of the three High findings from
> `code-reviews/review-sprint-3-governed-answer.md` (S3-R-01 same-authority
> contradiction merging into one self-contradictory claim, S3-R-02 an
> unrelated absence-shaped sentence short-circuiting a responsive answer,
> S3-R-03 a resurrected merged claim double-citing chunks after conflict
> reconciliation). All three now ship with a permanent regression fixture in
> this benchmark suite, described below.

## Benchmark Cases

`tests/answers/test_answer_benchmarks.py` is the permanent regression suite for
`answer()`. It writes fourteen synthetic source documents across fourteen
distinct root directories, in two isolated fixtures — a twelve-document
primary corpus (`benchmark_repository`) and a two-document same-authority
corpus (`same_authority_repository`, added by the S3-R-01 repair so a
same-authority contradiction can be reproduced without perturbing the primary
corpus's absence and duplicate-suppression fixtures) — syncs each through the
real local-file connector and SQLite repository (not a mock), and asks
questions only through the public `answer()` surface. It exercises seven
distinct benchmark families (15 collected test items; three families now
include a repair-regression fixture, and one family is parametrized over five
questions):

| # | Family | Test function | What it proves |
|---|--------|----------------|-----------------|
| 1 | Cross-repository claim assembly | `test_documentation_steward_shape_combines_three_roots` | A single question pulls grounded claims from three independent source roots and each claim keeps its own citation. |
| 2 | Fuzzy / partial-phrase matching | `test_fuzzy_partial_name_finds_the_full_official_name` | A partial, loosely-worded question still retrieves and cites the document holding the full official name. |
| 3 | Cross-repository attribution breadth | `test_cross_repository_synthesis_attributes_at_least_three_roots` | The same multi-root question attributes claims to at least three distinct source roots and at least three distinct source locators, not one root standing in for the rest. |
| 4 | Authoritative, evidenced absence | `test_authoritative_absence_is_a_cited_evidenced_not_found` | A question about something the corpus explicitly says was never created returns a single cited `DIRECTLY_EVIDENCED` claim, not a silent empty-result absence. |
| 4b | Authoritative, evidenced absence — regression | `test_unresponsive_absence_shaped_sentence_does_not_replace_answer` | An absence-shaped sentence elsewhere in the corpus that is **not** responsive to the question asked must not suppress the substantive, cited answer. Closes S3-R-02, where an unrelated derived note reading "does not exist" replaced a correct two-source answer. |
| 5 | Conflict identification without a winner | `test_conflicting_evidence_reports_both_sides_without_a_winner` | Two sources that directly contradict each other ("enabled" vs. "disabled") produce exactly one `Conflict` with both sides retained, both cited, and no `winner` field. |
| 5b | Conflict identification — same-authority regression | `test_same_authority_value_word_contradiction_stays_as_two_claims` | Two sources of the **same** declared authority that directly contradict each other still produce one `Conflict` and two separate, singly-cited claims, never one claim asserting both sides. Closes S3-R-01. |
| 5c | Conflict identification — reconciliation regression | `test_three_source_conflict_cites_each_chunk_in_exactly_one_claim` | Three same-topic sources (one canonical, two derived with identical text) resolve to exactly one claim per chunk; no chunk is cited by more than one claim, and no resurrected claim asserts both sides after conflict reconciliation. Closes S3-R-03. |
| 6 | Duplicate-source suppression | `test_duplicate_source_cannot_dominate_or_repeat_its_claim` | A source with the same statement repeated three times inside one document contributes exactly one citation and one claim occurrence; the two redundant repeats are recorded as accounted-for omissions, not silently dropped. |
| 7 | End-to-end provenance and receipt closure | `test_every_positive_claim_has_resolvable_provenance_and_accounted_omissions` (parametrized over 5 questions) | For every claim in every answer: citations resolve to a real item and chunk in the repository, and `receipt_ids` covers exactly the union of `evidence_used` and `evidence_omitted` — nothing presented without a receipt, nothing released and unaccounted for. |

An additional test, `test_benchmark_corpus_is_entirely_synthetic`, is a
fixture sanity check over the primary corpus (asserts its twelve source roots
are exactly the synthetic set constructed for this suite) rather than a
benchmark family itself. It does not cover the two-document same-authority
fixture, which is built by the same `_write_sources` helper and is synthetic
by the same construction.

## Results

Preserved system-validator evidence (`agent_orch.validators.command_succeeds@1`;
validator rerun is not permitted for this step, so these are reported, not
re-executed):

| Command | Exit | Result | Tied to | Evidence hash |
|---------|-----:|--------|---------|---------------|
| `python3 -m pytest tests/` | 0 | 241 passed in 21.13s | step_01_repair_three_high_findings acceptance criterion (repair S3-R-01, S3-R-02, S3-R-03), attempt 1 | `33d05eed716953f30f154f470e9b01551162a7d959d7df8a8108add54bddfb10` |
| `python3 -m pytest tests/` | 0 | 241 passed in 21.47s | step_01_repair_three_high_findings acceptance criterion (repair S3-R-01, S3-R-02, S3-R-03), attempt 2 | `53a866fcd140168c1f2584808ee375285e6ebe05b7925f7750fa2a8e66e2c4af` |

Both preserved runs' stdout itemizes `tests/answers/test_answer_benchmarks.py`
at 15 collected items (up from the 12 recorded before this step's repairs).
A fresh, non-preserved rerun of just that file, for this document's
per-family table below, confirms the same shape: `python3 -m pytest
tests/answers/ -v` — 15 passed in 0.59s, exit 0.

Per-family result, all pass:

| # | Family | Items | Result |
|---|--------|------:|--------|
| 1 | Cross-repository claim assembly | 1 | Pass |
| 2 | Fuzzy / partial-phrase matching | 1 | Pass |
| 3 | Cross-repository attribution breadth | 1 | Pass |
| 4 | Authoritative, evidenced absence (original + S3-R-02 regression) | 2 | Pass |
| 5 | Conflict identification without a winner (original + S3-R-01 + S3-R-03 regressions) | 3 | Pass |
| 6 | Duplicate-source suppression | 1 | Pass |
| 7 | End-to-end provenance and receipt closure | 5 (parametrized) | Pass (5/5) |
| — | Fixture sanity check | 1 | Pass |

15/15 collected items pass, matching the preserved evidence above.

This step also drove full verification green ahead of writing this document,
fresh (not preserved validator evidence): `BLACK_NUM_WORKERS=1 python3 -m
black --check src tests tools` (`30 files would be left unchanged`),
`python3 -m ruff check src tests tools` (clean; the pre-existing
`pyproject.toml` linter-settings deprecation warning tracked as S2-R-10
remains, out of scope here), `python3 -m compileall -q src tests tools`
(clean, no output), and `git diff --check` (clean, no output) — all exit 0,
with no repairs needed this time.

## Provenance Examples

Both examples below are reproduced directly from `tests/answers/test_answer_benchmarks.py`'s
synthetic fixtures by calling `answer()` in-process against the same temporary
SQLite projection the test suite builds.

**Example 1 — fuzzy partial-name question, single-source claim**
(family 2, `test_fuzzy_partial_name_finds_the_full_official_name`):

- Question: *"What is the full official name of documentation steward?"*
- Claim (`Confidence.DIRECTLY_EVIDENCED`): *"The full official name is
  Documentation Steward Coordination Service. Its identifiers are DSCS and
  steward-coordinator. The naming decision assigns the steward-manifest work
  package to the Documentation Steward Coordination Service."*
- Citation: `naming-repository:naming-decision.md`

**Example 2 — evidenced absence, single-source claim**
(family 4, `test_authoritative_absence_is_a_cited_evidenced_not_found`):

- Question: *"Was the Orbital Archive dossier created?"*
- Claim (`Confidence.DIRECTLY_EVIDENCED`): *"dossier was never created."*
- Citation: `absence-repository:orbital-archive-decision.md`
- `result.absence` is `None` — this is a cited, evidenced negative statement,
  not a silent empty-result absence.

These two examples are unchanged by this step's repairs; S3-R-07 (claim text
reproduces the raw chunk, heading and line wraps included, and this question
actually produces three claims, not the one shown) remains an open Low
documentation finding — see Recommendation.

## Confidence Distribution

Observed claim-level confidence across the five questions in family 7 (the
parametrized provenance test, which spans all of the corpus's positive-answer
questions), re-measured against the repaired pipeline:

| Confidence | Claims observed | Where |
|------------|-----------------:|-------|
| `DIRECTLY_EVIDENCED` | 9 | Documentation-steward question (3), fuzzy-name question (3), Orbital Archive absence (1), both sides of the Meridian conflict (2) |
| `SYNTHESIZED` | 1 | Harbor-readiness question — the duplicate-repository statement and the independent-audit statement merge into one claim citing both sources |
| `INFERRED` | 0 | Not exercised by this fixture family |
| `UNKNOWN` | 0 | Not exercised by this fixture family — absence and no-grounded-evidence paths that produce `UNKNOWN` overall confidence are covered separately by `tests/test_answer.py` and `tests/test_answer_absence.py`, not by the benchmark corpus |

This corrects the prior count of 12 `DIRECTLY_EVIDENCED` (S3-R-06), which
double-counted the documentation-steward question's three claims because
family 3 re-asks family 1's question over the same fixtures rather than
producing additional claims; the true total across the five questions is 10
claims (9 + 1), independently re-derived for this step by calling `answer()`
directly against a freshly rebuilt copy of the primary fixture corpus.

This distribution is specific to the seven benchmark families' synthetic
corpus — it is not a claim about confidence distribution over any real
corpus, which has not yet been measured through `answer()`.

## Conflict Examples

**Meridian deployment channel — different authority** (family 5,
`test_conflicting_evidence_reports_both_sides_without_a_winner`):

- Question: *"Is the deployment channel for Meridian enabled or disabled?"*
- Left claim (`Confidence.DIRECTLY_EVIDENCED`): *"The deployment channel for
  Meridian is enabled."* — citing `canonical-operations:meridian-channel.md`,
  declared `Authority.CANONICAL`.
- Right claim (`Confidence.DIRECTLY_EVIDENCED`): *"The deployment channel for
  Meridian is disabled."* — citing `field-operations:meridian-field-note.md`,
  declared `Authority.DERIVED`.
- `conflict.newer` is `Side.NEITHER` — both fixtures share the same synthetic
  source timestamp.
- `conflict.more_authoritative` is `Side.LEFT` — the canonical source outranks
  the derived one.
- No `winner` field exists on `Conflict` (`tests/test_answer_contracts.py`
  asserts this structurally); both claims remain in `result.claims` and both
  keep their citations.

**Equinox deployment channel — same authority** (family 5b,
`test_same_authority_value_word_contradiction_stays_as_two_claims`, new in
this step, reproducing the shape S3-R-01 was found against):

- Question: *"Is the deployment channel for Equinox enabled or disabled?"*
- Left claim (`Confidence.DIRECTLY_EVIDENCED`): *"The deployment channel for
  Equinox is enabled."* — citing `same-authority-a:equinox-channel-enabled.md`,
  declared `Authority.DERIVED`.
- Right claim (`Confidence.DIRECTLY_EVIDENCED`): *"The deployment channel for
  Equinox is disabled."* — citing `same-authority-b:equinox-channel-disabled.md`,
  also declared `Authority.DERIVED`.
- `conflict.detail`: *"Competing statements about channel, deployment,
  equinox use divergent value words."* — the new detection signal added to
  repair S3-R-01; both sources share the same declared authority and the same
  synthetic timestamp, so neither the authority-divergence nor the
  supersession signal would have fired.
- `conflict.more_authoritative` and `conflict.newer` are both `Side.NEITHER`.
- Before the repair this fixture shape produced **one** `SYNTHESIZED` claim
  asserting both "enabled" and "disabled" and **zero** conflicts. After the
  repair it produces two separate, singly-cited `DIRECTLY_EVIDENCED` claims
  and one `Conflict` — no merge, both sides visible.

The three-source reconciliation regression (family 5c,
`test_three_source_conflict_cites_each_chunk_in_exactly_one_claim`, closing
S3-R-03) is a third fixture in the same family: one canonical and two derived
sources on the same topic resolve to exactly three claims, one per chunk, and
two conflicts (each derived claim against the canonical claim) — no chunk is
cited by more than one claim, and no merged claim survives reconciliation.

## Performance Observations

Two separate measurements, both against the twelve-document synthetic
`benchmark_repository` corpus (not the real, ~1,213-document corpus measured
for `retrieve()` in `evidence/real-corpus-parity-report.md` — `answer()` has
not yet been latency-tested at that scale):

- **Fixture suite wall-clock**: within the full-suite preserved validator
  evidence above, `tests/answers/test_answer_benchmarks.py` accounts for 15 of
  the 241 collected items. A fresh, non-preserved rerun of just that file —
  `python3 -m pytest tests/answers/ -v` — completed in 0.59s, exit 0. This
  includes one module-scoped fixture that syncs all twelve primary-corpus
  documents through the real connector and repository once, amortized across
  11 of the 15 test items, plus a second module-scoped fixture for the
  two-document same-authority corpus, amortized across the remaining item.
- **Per-call `answer()` latency** (fresh, ad hoc, not a preserved validator
  command): calling `answer()` directly, in-process, against the already-synced
  primary fixture repository, for the five questions in family 7, three
  repeats each (15 calls) — mean 13.7ms, max 24.2ms, min 4.9ms. This excludes
  CLI process startup and the one-time sync; it isolates the plan → retrieve
  → select → assemble → detect-conflicts → narrate pipeline itself, now
  running the repaired conflict-detection and absence-classification code.

Both figures describe a tiny, deterministic, offline corpus and are useful as
a regression floor, not as a production capacity estimate.

## Recommendation

**Ready after specific follow-up.**

The three High findings from `code-reviews/review-sprint-3-governed-answer.md`
that gated the prior recommendation — S3-R-01 (same-authority contradictions
merging into one self-contradictory claim), S3-R-02 (an unrelated
absence-shaped sentence short-circuiting a responsive answer), and S3-R-03 (a
resurrected merged claim double-citing chunks after conflict reconciliation)
— are repaired, each with a permanent regression fixture in this benchmark
suite (families 4b, 5b, 5c above), and the full suite (241 tests, preserved
validator evidence, two independent runs, both exit 0) plus fresh
`black`/`ruff`/`compileall`/`git diff --check` are all clean with no repairs
needed. This document's Confidence Distribution count is also corrected
(S3-R-06) as a byproduct of re-deriving these results against the repaired
pipeline.

The review's Medium and Low findings are **not** addressed by this step and
remain open:

1. **S3-R-04 (Medium)** — `Answer` still carries no equivalent of
   `EvidenceBundle.denied_count` or `.truncated`; withholding is visible only
   through `Absence.withheld_count`, which exists only when the answer has no
   claims.
2. **S3-R-05 (Medium)** — `cmd_ask` (`src/lee_kb/main.py`) still does not pass
   `project_has_synchronized_content`, `corpus_fresh`, or `resolution_failed`
   to `answer()`, so the `UNKNOWN` absence branch purpose-built for an
   unsynchronized project remains unreachable from the CLI, which instead
   reports `NOT_FOUND`.
3. **S3-R-07, S3-R-08, S3-R-09 (Low)** — Provenance Examples still quote
   reformatted claim text rather than the raw chunk and undercount claims for
   Example 1; `docs/answer-architecture.md` still says v1 ships with no
   synthesis provider configured, when `DeterministicSynthesisProvider` is
   actually the default; `OUTSIDE_REQUESTED_PROJECT` omissions still report to
   the reader as `NOT_RELEVANT`.

Independently of the review, the same three items already carried forward
from the prior recommendation are still true and still gate real-world use:

4. **The LLM-backed `SynthesisProvider` is specified but not implemented.**
   `answer()` ships with only `DeterministicSynthesisProvider`, a template
   renderer with no model call — offline and auditable, but not natural
   prose. An LLM-backed provider requires explicit dependency approval per
   `AGENTS.md`'s "Add external runtime dependencies" guardrail.
5. **`answer()` has not been run against the real corpus.** Every result in
   this document comes from the synthetic benchmark fixtures; `retrieve()`
   has a real-corpus baseline (`evidence/real-corpus-parity-report.md`),
   `answer()` does not.
6. **Live filesystem verification remains a deferred extension.** Nothing
   here exercises `answer()` against a live, continuously-synchronized
   filesystem corpus over time.
7. **Two open items inherited from `retrieve()` remain open**: the
   OR-matcher worst-case latency decision (Open Question 5 in `context.md`)
   and permission-basis on receipts (Open Question 2), both of which affect
   `answer()` since it is a strict layer on top of `retrieve()`.

None of these are correctness defects in the repaired slice — the three
correctness defects a reader would notice as a confidently wrong answer are
fixed and regression-tested. What remains are honest-reporting completeness
gaps (S3-R-04, S3-R-05), documentation-accuracy gaps (S3-R-07, S3-R-08,
S3-R-09), and scope boundaries the mission explicitly requires stating
plainly rather than implying completion.
