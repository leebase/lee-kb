# Answer Benchmark Results

> Benchmark evidence for the governed `answer()` surface (`src/lee_kb/answer.py`),
> assembled entirely from the synthetic fixtures in `tests/answers/test_answer_benchmarks.py`.
> No content from Lee's private corpus appears anywhere in this document, per the
> publication rule in `skills/documentation.md`.
>
> This revision follows a fourth repair round. Round one fixed the three High
> findings from `code-reviews/review-sprint-3-governed-answer.md` (S3-R-01,
> S3-R-02, S3-R-03). Round two (`code-reviews/review-sprint-3-repair.md`)
> closed the next shape-specific gaps (S3-R-10 and S3-R-11), and round three
> (`code-reviews/review-sprint-3-repair-2.md`) removed an undiscriminating
> structural-divergence signal (S3-R-15) and corrected its documentation
> (S3-R-16). The independent review of that round,
> `code-reviews/review-sprint-3-repair-3.md`, found the repair had traded one
> direction for the other: negation outside the value-word list could still
> merge contradictory claims (S3-R-17), same-authority substitutions could be
> missed (S3-R-18), cross-authority agreement could still be called a conflict
> (S3-R-19), and emphatic agreement could be misread as negation (S3-R-20).
> This round repairs those four mechanisms and adds S3-R-21's missing
> two-direction measurement. Conflict detection now requires positive evidence
> of disagreement: polarity, numeric or known-value divergence, a recognized
> morphological antonym, or a one-slot substitution after inflection
> normalization. Authority describes a detected disagreement; it never creates
> one by itself. The permanent regression set below covers both false conflicts
> and missed contradictions, including detection-bypass merge refusal.

## Benchmark Cases

`tests/answers/test_answer_benchmarks.py` is the permanent regression suite for
`answer()`. It writes synthetic source documents across independent root
directories, syncs each through the real local-file connector and SQLite
repository (not a mock), and asks questions only through the public
`answer()` surface. Three fixture shapes are in play: a twelve-document
primary corpus (`benchmark_repository`), a two-document same-authority corpus
(`same_authority_repository`, added by the round-one S3-R-01 repair), and a
family of small, per-case corpora built directly in test functions under
`tmp_path` (one two-document corpus per contradiction or non-competing case,
plus one three-document corpus for the additive-absence case), so each
regression is isolated from the other fixtures rather than perturbing a
shared corpus. It exercises seven distinct benchmark families (37 collected
test items; the conflict family now includes both same- and cross-authority
agreeing pairs, 11 contradiction shapes, a detection-bypass case, and a
two-direction rate guard):

| # | Family | Test function | What it proves |
|---|--------|----------------|-----------------|
| 1 | Cross-repository claim assembly | `test_documentation_steward_shape_combines_three_roots` | A single question pulls grounded claims from three independent source roots and each claim keeps its own citation. |
| 2 | Fuzzy / partial-phrase matching | `test_fuzzy_partial_name_finds_the_full_official_name` | A partial, loosely-worded question still retrieves and cites the document holding the full official name. |
| 3 | Cross-repository attribution breadth | `test_cross_repository_synthesis_attributes_at_least_three_roots` | The same multi-root question attributes claims to at least three distinct source roots and at least three distinct source locators, not one root standing in for the rest. |
| 4 | Authoritative, evidenced absence | `test_authoritative_absence_is_a_cited_evidenced_not_found` | A question about something the corpus explicitly says was never created returns a single cited `DIRECTLY_EVIDENCED` claim, not a silent empty-result absence. |
| 4b | Authoritative, evidenced absence — unresponsive regression | `test_unresponsive_absence_shaped_sentence_does_not_replace_answer` | An absence-shaped sentence elsewhere in the corpus that is **not** responsive to the question asked must not suppress the substantive, cited answer. Closes S3-R-02 (round one). |
| 4c | Authoritative, evidenced absence — additive regression | `test_top_ranked_absence_statement_is_additive_to_substantive_answer` | An absence-shaped sentence that **is** responsive and top-ranked must be **added** to the substantive answer as its own cited claim, not replace it. Closes S3-R-11 (round two). |
| 5 | Conflict identification without a winner | `test_conflicting_evidence_reports_both_sides_without_a_winner` | Two sources that directly contradict each other ("enabled" vs "disabled") produce exactly one `Conflict` with both sides retained, both cited, and no `winner` field. |
| 5b | Conflict identification — same-authority, in-vocabulary regression | `test_same_authority_value_word_contradiction_stays_as_two_claims` | Two sources of the **same** declared authority whose divergence is expressed with a recognized value-word pair ("enabled"/"disabled") still produce one `Conflict` and two separate, singly-cited claims, never one claim asserting both sides. Closes S3-R-01 (round one). |
| 5c | Conflict identification — reconciliation regression | `test_three_source_conflict_cites_each_chunk_in_exactly_one_claim` | Three same-topic sources (one canonical, two derived with identical text) resolve to exactly one claim per chunk; no chunk is cited by more than one claim, and no resurrected claim asserts both sides after conflict reconciliation. Closes S3-R-03 (round one). |
| 5d | Conflict identification — contradicting pairs across authority and vocabulary shapes | `test_contradicting_statement_pairs_produce_one_conflict_with_cited_sides` (parametrized over 11 cases: value-word, numeric, compound-value, authority, morphological-antonym, two negation, proper-noun, weekday, and place substitutions) | Genuine contradictions — including negation outside the value-word list and ordinary same-authority substitutions — produce exactly one `Conflict` and two separate, singly-cited claims. This closes S3-R-17 and S3-R-18 in addition to the earlier S3-R-10 shapes. |
| 5e | Conflict identification — non-competing pairs produce no conflict | `test_non_competing_statement_pairs_produce_no_conflicts` (parametrized over 8 cases: voice change, elaboration, synonym restatement, added detail, cross-root restatement, formatting, and two emphatic-agreement forms) | Agreeing same-authority statements never produce a `Conflict`, including `required` / `required, not optional` and `required` / `not optional`. |
| 5f | Conflict identification — merge refusal independent of detection | `test_negated_non_value_word_refuses_merge_when_conflict_detection_is_bypassed` | A statement and its non-value-word negation remain two singly-cited claims even when conflict detection is neutralized, closing both halves of S3-R-17. |
| 5g | Conflict identification — two-direction regression rate | `test_conflict_detection_has_no_false_conflicts_or_missed_contradictions` | The fixed agreeing and contradicting corpora assert zero false conflicts, zero missed contradictions, and zero merged contradictory claims for both same- and cross-authority agreeing pairs, preventing another one-direction trade. |
| 6 | Duplicate-source suppression | `test_duplicate_source_cannot_dominate_or_repeat_its_claim` | A source with the same statement repeated three times inside one document contributes exactly one citation and one claim occurrence; the two redundant repeats are recorded as accounted-for omissions, not silently dropped. |
| 7 | End-to-end provenance and receipt closure | `test_every_positive_claim_has_resolvable_provenance_and_accounted_omissions` (parametrized over 5 questions) | For every claim in every answer: citations resolve to a real item and chunk in the repository, and `receipt_ids` covers exactly the union of `evidence_used` and `evidence_omitted` — nothing presented without a receipt, nothing released and unaccounted for. |

An additional test, `test_benchmark_corpus_is_entirely_synthetic`, is a
fixture sanity check over the primary corpus (asserts its twelve source roots
are exactly the synthetic set constructed for this suite) rather than a
benchmark family itself. It does not cover the same-authority fixture or the
per-case `tmp_path` corpora, all of which are built by the same
`_write_sources`/inline-source-writing pattern and are synthetic by the same
construction.

## Results

Fresh verification for this repair round:

| Command | Exit | Result |
|---------|-----:|--------|
| `python3 -m pytest tests/` | 0 | 298 passed after conflict, baseline, audit, and fail-closed capability repairs |
| `python3 -m pytest tests/answers/test_answer_benchmarks.py -q` | 0 | 37 passed |
| `BLACK_NUM_WORKERS=1 python3 -m black --check src tests tools` | 0 | 33 files unchanged |
| `python3 -m ruff check src tests tools` | 0 | Clean; existing configuration deprecation warning only |
| `python3 -m compileall -q src tests tools` | 0 | Clean |
| `python3 tools/check_disclosure.py` | 0 | No host paths or credentials |
| `git diff --check` | 0 | Clean |

Per-family result, all pass:

| # | Family | Items | Result |
|---|--------|------:|--------|
| 1 | Cross-repository claim assembly | 1 | Pass |
| 2 | Fuzzy / partial-phrase matching | 1 | Pass |
| 3 | Cross-repository attribution breadth | 1 | Pass |
| 4 | Authoritative, evidenced absence (original + unresponsive regression + additive regression) | 3 | Pass |
| 5 | Conflict identification without a winner (original + in-vocabulary + reconciliation + contradicting-pair + non-competing-pair + merge-refusal + rate regressions) | 24 | Pass |
| 6 | Duplicate-source suppression | 1 | Pass |
| 7 | End-to-end provenance and receipt closure | 5 (parametrized) | Pass (5/5) |
| — | Fixture sanity check | 1 | Pass |

37/37 collected benchmark items pass. The two formatting-only changes in
`tests/test_cli.py` and `tests/test_local_connector.py` restore the repository's
Black check under the installed formatter; they do not change behavior.

## Provenance Examples

Both examples below are reproduced directly from `tests/answers/test_answer_benchmarks.py`'s
synthetic fixtures by calling `answer()` in-process against the same temporary
SQLite projection the test suite builds. Neither example touches conflict
detection or absence assembly, so both are unchanged by this round's repairs.

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

These two examples are unchanged by the conflict repairs; S3-R-07 (claim text
reproduces the raw chunk, heading and line wraps included, and this question
actually produces three claims, not the one shown) remains an open Low
documentation finding — see Recommendation.

## Confidence Distribution

Observed claim-level confidence across the five questions in family 7 (the
parametrized provenance test, which spans all of the corpus's positive-answer
questions), re-measured against the round-four-repaired pipeline:

| Confidence | Claims observed | Where |
|------------|-----------------:|-------|
| `DIRECTLY_EVIDENCED` | 11 | Documentation-steward question (3), fuzzy-name question (3), Orbital Archive absence (1), both sides of the Meridian conflict (2), both harbor-readiness statements (2) |
| `SYNTHESIZED` | 0 | Not exercised by this fixture family after the round-two repair (see below) |
| `INFERRED` | 0 | Not exercised by this fixture family |
| `UNKNOWN` | 0 | Not exercised by this fixture family — absence and no-grounded-evidence paths that produce `UNKNOWN` overall confidence are covered separately by `tests/test_answer.py` and `tests/test_answer_absence.py`, not by the benchmark corpus |

This distribution is unchanged from the round-two-repaired document: the
merge-rule inversion that produced it (harbor-readiness's two statements no
longer merge into one `SYNTHESIZED` claim) is untouched by the conflict repairs.
The round-three re-review's regression set did not change this claim count.
Re-measured against the current, round-four-repaired code, all five family-7
questions together produce **1** conflict total (Meridian only); the
harbor-readiness question reports zero conflicts. Independently re-derived for
this step by calling `answer()` against a freshly rebuilt copy of the primary
fixture corpus: 11 claims across the five questions, all
`DIRECTLY_EVIDENCED`, 1 conflict total, 0 unresolved citations.

`SYNTHESIZED` is not dead: `tests/test_answer.py::test_multi_source_synthesis_attributes_a_claim_to_more_than_one_source`
exercises it directly with a fixture whose two sources remain term-equivalent
after synonym normalization. This benchmark corpus's harbor-readiness fixture
simply no longer qualifies, now that near-duplicate-but-not-quite statements
are held to a stricter merge bar.

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

**Equinox deployment channel — same authority, in-vocabulary** (family 5b,
`test_same_authority_value_word_contradiction_stays_as_two_claims`,
reproducing the shape S3-R-01 was found against in round one):

- Question: *"Is the deployment channel for Equinox enabled or disabled?"*
- Left claim (`Confidence.DIRECTLY_EVIDENCED`): *"The deployment channel for
  Equinox is enabled."* — citing `same-authority-a:equinox-channel-enabled.md`,
  declared `Authority.DERIVED`.
- Right claim (`Confidence.DIRECTLY_EVIDENCED`): *"The deployment channel for
  Equinox is disabled."* — citing `same-authority-b:equinox-channel-disabled.md`,
  also declared `Authority.DERIVED`.
- `conflict.detail`: *"Competing statements about channel, deployment,
  equinox use divergent value words."*
- `conflict.more_authoritative` and `conflict.newer` are both `Side.NEITHER`.

**Lyra retention window — same authority, numeric divergence** (family 5d,
`test_contradicting_statement_pairs_produce_one_conflict_with_cited_sides[numeric-divergence]`):

- Question: *"What is the retention window for Lyra in days?"*
- Left claim (`Confidence.DIRECTLY_EVIDENCED`): *"The retention window for
  Lyra is 30 days."* — citing `contradicting-left:numeric-divergence-left.md`,
  declared `Authority.DERIVED`.
- Right claim (`Confidence.DIRECTLY_EVIDENCED`): *"The retention window for
  Lyra is 90 days."* — citing `contradicting-right:numeric-divergence-right.md`,
  also declared `Authority.DERIVED`.
- `conflict.detail`: *"Competing statements about days, lyra, retention,
  window use different numeric values."*
- `conflict.more_authoritative` and `conflict.newer` are both `Side.NEITHER`.
- Sibling cases `enabled-versus-turned-off` (Kestrel release gate) and
  `permitted-versus-forbidden` (Vega export policy) reproduce the same
  same-authority, out-of-vocabulary contradiction shape.

**Phoenix deployment — same authority, morphological antonym outside any
fixed word list** (family 5d,
`test_contradicting_statement_pairs_produce_one_conflict_with_cited_sides[morphological-antonym-outside-word-list]`,
the case the previous document could not demonstrate — round two's fixtures
only reached out-of-vocabulary contradictions through the now-removed
undiscriminating similarity branch, which could not be trusted to distinguish
a real antonym from mere paraphrase):

- Question: *"Is the Phoenix deployment restricted?"*
- Left claim (`Confidence.DIRECTLY_EVIDENCED`): *"The Phoenix deployment is
  restricted."* — citing `contradicting-left:morphological-antonym-outside-word-list-left.md`,
  declared `Authority.DERIVED`.
- Right claim (`Confidence.DIRECTLY_EVIDENCED`): *"The Phoenix deployment is
  unrestricted."* — citing `contradicting-right:morphological-antonym-outside-word-list-right.md`,
  also declared `Authority.DERIVED`.
- `conflict.detail`: *"Competing statements about deployment, phoenix use
  opposing terms."* — produced by the new positive morphological-antonym
  signal (`restricted` / `unrestricted`, a recognized `un-` prefix pair),
  neither a value word nor a number, so neither of the two round-two signals
  would have caught it; the sentence pair is a genuine same-authority
  contradiction outside every fixed word list this suite has used so far.
- `conflict.more_authoritative` and `conflict.newer` are both `Side.NEITHER`.
- The sibling case `canonical-versus-derived` (Draco route, eastern vs western
  corridor) reproduces the same-shape declared-authority-divergence branch
  (`conflict.detail`: *"...have different declared authority."*,
  `more_authoritative` is `Side.LEFT`) with a fresh fixture rather than
  reusing Meridian's wording.

**Nimbus archive — same-authority polarity divergence outside the value-word
list** (family 5d, `negated-non-value-word`):

- *"The Nimbus archive is encrypted."* and *"The Nimbus archive is not
  encrypted."* produce one `Conflict` and two singly-cited claims.
- `conflict.detail` reports divergent polarity. The same result holds for the
  `never` variant involving Willow relay outages.
- `test_negated_non_value_word_refuses_merge_when_conflict_detection_is_bypassed`
  neutralizes `detect_conflicts` and still gets two claims, proving the merge
  refusal is independent of conflict reporting.

**Juniper escalation — same-authority one-slot substitution** (family 5d,
`same-authority-proper-noun-substitution`):

- *"The Juniper escalation is owned by the escalation desk."* and *"The
  Juniper escalation is owned by the vendor desk."* produce one `Conflict` and
  two singly-cited claims.
- The substitution signal uses canonical term counts, so repeated subject
  words cannot hide the replaced slot. Rowan weekday and Cedar place
  substitutions exercise the same signal.

**Fennel gate — emphatic agreement is not a conflict** (family 5e,
`emphatic-agreement`):

- *"The Fennel gate is required."* and *"The Fennel gate is required, not
  optional."* produce `result.conflicts == ()`.
- The de-negated value sets differ (`required` versus `required` plus
  `optional`), so the second statement is treated as elaboration rather than
  a polarity contradiction.

**Non-conflict regression — agreeing statements produce no conflict** (family
5e,
`test_non_competing_statement_pairs_produce_no_conflicts`, closing S3-R-15 and
its narrower pre-existing instance S3-R-12):

- Question: *"What does the Halcyon policy retain?"* (case
  `elaboration-by-added-clause`)
- Left source: *"The Halcyon policy retains audit logs."*
- Right source: *"Audit logs are retained by the Halcyon policy under section
  4."* — a strict elaboration of the left statement, not a competing one.
- Result: `result.conflicts == ()`; the two sources merge into one
  `Confidence.SYNTHESIZED` claim citing both, exactly as an agreeing pair
  should. Before this round's fix, `code-reviews/review-sprint-3-repair-2.md`
  (finding S3-R-15) measured this same shape reported as a spurious
  `Conflict` on 5 of 6 constructed agreeing pairs, reproduced against a
  pre-repair copy of the tree, including this exact elaboration case and the
  project's own harbor-readiness fixture (see Confidence Distribution above).
   The six sibling cases (`paraphrase-by-voice`, `synonym-restatement`,
   `differing-detail-level`, `same-fact-from-two-roots`, `formatting-only`,
   `emphatic-agreement`)
  cover voice change, synonym restatement, an added qualifier, a
  cross-root restatement, and formatting-only differences — each asserting
  the same `result.conflicts == ()` outcome.

The three-source reconciliation regression (family 5c,
`test_three_source_conflict_cites_each_chunk_in_exactly_one_claim`, closing
S3-R-03 in round one) is a further fixture in the same family: one canonical
and two derived sources on the same topic resolve to exactly three claims,
one per chunk, and two conflicts (each derived claim against the canonical
claim) — no chunk is cited by more than one claim, and no merged claim
survives reconciliation.

## Performance Observations

Two separate measurements, both against the twelve-document synthetic
`benchmark_repository` corpus (not the real, ~1,213-document corpus measured
for `retrieve()` in `evidence/real-corpus-parity-report.md` — `answer()` has
not yet been latency-tested at that scale):

- **Fixture suite wall-clock**: the full suite accounts for 298 collected
  items, including 37 from `tests/answers/test_answer_benchmarks.py`. A fresh
  rerun of that file — `python3 -m pytest
  tests/answers/test_answer_benchmarks.py -q` — completed in 11.09s, exit 0.
  The extra time is the two-direction rate guard: it rebuilds the fixed
  agreeing and contradicting corpora through the real connector and SQLite
  projection rather than calling private predicates directly.
- **Per-call `answer()` latency** (fresh, ad hoc, not a preserved validator
  command): calling `answer()` directly, in-process, against the already-synced
  primary fixture repository, for the five questions in family 7, three
  repeats each (15 calls) — mean 14.3ms, max 26.3ms, min 4.5ms. This excludes
  CLI process startup and the one-time sync; it isolates the plan → retrieve
  → select → assemble → detect-conflicts → narrate pipeline itself, now
  running the round-four-repaired conflict-detection code.

Both figures describe a tiny, deterministic, offline corpus and are useful as
a regression floor, not as a production capacity estimate.

## Recommendation

**Ready after specific follow-up.**

The independent review's S3-R-17 and S3-R-18 High findings, plus S3-R-19,
S3-R-20, and S3-R-21, are repaired in this round. Negation is now treated as
polarity rather than an added vocabulary term, so a non-value-word negation
cannot merge into a self-contradictory claim. Same-authority ordinary
substitutions are detected from one-for-one canonical term-count differences;
inflection normalization keeps voice changes and cross-authority restatements
mergeable. Authority is only an attribute of a positive substitution signal,
not a conflict detector. The value-word check requires an opposition rather
than mere set difference, so emphatic agreement remains conflict-free.

The 37-item benchmark slice includes eight non-competing fixtures. Its
two-direction rate guard runs 16 non-competing probes across same and differing
authorities with zero false conflicts; 11 contradiction probes produce one
conflict and two singly-cited claims; and a detection-bypass test proves the
negated non-value-word merge refusal independently. The full suite (298 tests)
and fresh
`black`/`ruff`/`compileall`/`check_disclosure.py`/`git diff --check` are clean.
S3-R-12, S3-R-15, S3-R-17, S3-R-18, S3-R-19, S3-R-20, and S3-R-21 are closed
by these implementation and regression changes. The subsequent Office,
connector, answer-state, and query-audit hardening also closes S3-R-04,
S3-R-05, and S1-R-12; it adds failure-safe public change diffing, distinguishes
deletion-only projects from never-synced projects, and persists query-level
events for denied and empty retrievals.

The remaining findings and release boundaries are:

1. **S3-R-07 and S3-R-09 (Low)** — Provenance Examples still quote
   reformatted claim text rather than the raw chunk and undercount claims for
   Example 1; `OUTSIDE_REQUESTED_PROJECT` omissions still report to the reader
   as `NOT_RELEVANT`. The provider wording is now reconciled.
2. **S1-R-17 (Low)** — the direct repository search method remains an internal
   provider boundary without principal enforcement; shipped surfaces use the
   governed path.

Independently of all three reviews, the same items already carried forward
from the prior recommendations are still true and still gate real-world use:

4. **The LLM-backed `SynthesisProvider` is specified but not implemented.**
   `answer()` ships with only `DeterministicSynthesisProvider`, a template
   renderer with no model call — offline and auditable, but not natural
   prose. An LLM-backed provider requires explicit dependency approval per
   `AGENTS.md`'s "Add external runtime dependencies" guardrail.
5. **`answer()` has not been run against the real corpus.** Every result in
   this document comes from the synthetic benchmark fixtures; `retrieve()`
   has a real-corpus baseline (`evidence/real-corpus-parity-report.md`),
   `answer()` does not. This matters specifically for conflict detection: a
    real corpus holds far more near-duplicate restatements, elaborations, and
    negated statements than these fixtures do, so the heuristic's behavior at
    real-corpus scale remains unmeasured even though both directions are now
    covered by fixed synthetic rates.
6. **Live filesystem verification remains a deferred extension.** Nothing
   here exercises `answer()` against a live, continuously-synchronized
   filesystem corpus over time.
7. **Two open items inherited from `retrieve()` remain open**: the
   OR-matcher worst-case latency decision (Open Question 5 in `context.md`)
   and permission-basis on receipts (Open Question 2), both of which affect
   `answer()` since it is a strict layer on top of `retrieve()`.

None of these are an untested confidently-wrong-answer path in the current
synthetic suite. The correctness defects a reader would notice as a
confidently wrong or falsely-flagged answer (S3-R-01, S3-R-02, S3-R-03,
S3-R-10, S3-R-11, S3-R-12, S3-R-15, S3-R-17, S3-R-18, S3-R-19, and S3-R-20)
are now covered by four repair rounds, including a two-direction rate guard.
The result is still a synthetic regression floor, not a real-corpus release
claim. What remains is documentation accuracy (S3-R-07, S3-R-09) and scope
boundaries the mission explicitly requires stating plainly rather than implying
completion.
