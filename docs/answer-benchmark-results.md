# Answer Benchmark Results

> Benchmark evidence for the governed `answer()` surface (`src/lee_kb/answer.py`),
> assembled entirely from the synthetic fixtures in `tests/answers/test_answer_benchmarks.py`.
> No content from Lee's private corpus appears anywhere in this document, per the
> publication rule in `skills/documentation.md`.
>
> This revision follows a second repair round. Round one fixed the three High
> findings from `code-reviews/review-sprint-3-governed-answer.md` (S3-R-01,
> S3-R-02, S3-R-03) by keying merge-refusal and conflict detection to a closed
> 14-word value-word vocabulary and requiring an absence-shaped sentence to be
> top-ranked and relevant before it could answer the question. A follow-up
> review, `code-reviews/review-sprint-3-repair.md`, proved both fixes were
> shape-specific rather than general — S3-R-10 (a contradiction phrased outside
> the 14-word vocabulary, e.g. "enabled" vs. "turned off", or a purely numeric
> divergence, still merged into one self-contradictory claim with zero
> conflicts) and S3-R-11 (a top-ranked, relevant absence-shaped sentence still
> **replaced** the whole answer rather than joining it, so a short "X does not
> exist" record could still suppress a correct multi-source answer). This round
> two repair inverts the merge rule — evidence merges only when its differing
> meaningful terms are empty or a known synonym set, instead of merging unless
> a known antonym is seen — adds numeric divergence as an explicit conflict
> signal, and makes evidenced absence an **additional** claim rather than a
> replacement. Both are now covered by permanent regression fixtures, described
> below.

## Benchmark Cases

`tests/answers/test_answer_benchmarks.py` is the permanent regression suite for
`answer()`. It writes synthetic source documents across independent root
directories, syncs each through the real local-file connector and SQLite
repository (not a mock), and asks questions only through the public
`answer()` surface. Three fixture shapes are in play: a twelve-document
primary corpus (`benchmark_repository`), a two-document same-authority corpus
(`same_authority_repository`, added by the round-one S3-R-01 repair), and —
new this round — four two-document, per-case corpora built directly in a test
function under `tmp_path` (one for each of the three out-of-vocabulary/numeric
divergence cases, and one three-document corpus for the additive-absence
case), so each new regression is isolated from the other fixtures rather than
perturbing a shared corpus. It exercises seven distinct benchmark families (19
collected test items; two families now carry a second round of
repair-regression fixtures, and two families are parametrized):

| # | Family | Test function | What it proves |
|---|--------|----------------|-----------------|
| 1 | Cross-repository claim assembly | `test_documentation_steward_shape_combines_three_roots` | A single question pulls grounded claims from three independent source roots and each claim keeps its own citation. |
| 2 | Fuzzy / partial-phrase matching | `test_fuzzy_partial_name_finds_the_full_official_name` | A partial, loosely-worded question still retrieves and cites the document holding the full official name. |
| 3 | Cross-repository attribution breadth | `test_cross_repository_synthesis_attributes_at_least_three_roots` | The same multi-root question attributes claims to at least three distinct source roots and at least three distinct source locators, not one root standing in for the rest. |
| 4 | Authoritative, evidenced absence | `test_authoritative_absence_is_a_cited_evidenced_not_found` | A question about something the corpus explicitly says was never created returns a single cited `DIRECTLY_EVIDENCED` claim, not a silent empty-result absence. |
| 4b | Authoritative, evidenced absence — unresponsive regression | `test_unresponsive_absence_shaped_sentence_does_not_replace_answer` | An absence-shaped sentence elsewhere in the corpus that is **not** responsive to the question asked must not suppress the substantive, cited answer. Closes S3-R-02 (round one). |
| 4c | Authoritative, evidenced absence — additive regression | `test_top_ranked_absence_statement_is_additive_to_substantive_answer` | An absence-shaped sentence that **is** responsive and top-ranked must be **added** to the substantive answer as its own cited claim, not replace it. Closes S3-R-11 (round two): before this fix, a top-ranked, relevant "X does not exist" record demoted both real answer claims to `evidence_omitted`. |
| 5 | Conflict identification without a winner | `test_conflicting_evidence_reports_both_sides_without_a_winner` | Two sources that directly contradict each other ("enabled" vs "disabled") produce exactly one `Conflict` with both sides retained, both cited, and no `winner` field. |
| 5b | Conflict identification — same-authority, in-vocabulary regression | `test_same_authority_value_word_contradiction_stays_as_two_claims` | Two sources of the **same** declared authority whose divergence is expressed with a recognized value-word pair ("enabled"/"disabled") still produce one `Conflict` and two separate, singly-cited claims, never one claim asserting both sides. Closes S3-R-01 (round one). |
| 5c | Conflict identification — reconciliation regression | `test_three_source_conflict_cites_each_chunk_in_exactly_one_claim` | Three same-topic sources (one canonical, two derived with identical text) resolve to exactly one claim per chunk; no chunk is cited by more than one claim, and no resurrected claim asserts both sides after conflict reconciliation. Closes S3-R-03 (round one). |
| 5d | Conflict identification — out-of-vocabulary and numeric divergence regression | `test_same_subject_divergence_outside_value_word_list_is_a_conflict` (parametrized over 3 cases: `enabled-versus-turned-off`, `permitted-versus-forbidden`, `numeric-divergence`) | Same-authority contradictions phrased **outside** any fixed value-word list — including a purely numeric divergence — still produce one `Conflict` and two separate, singly-cited claims. Closes S3-R-10 (round two): before this fix, each of these three shapes merged into one `SYNTHESIZED` claim asserting both sides with zero conflicts, because merge-refusal and conflict detection were both keyed to the same closed 14-word vocabulary. |
| 6 | Duplicate-source suppression | `test_duplicate_source_cannot_dominate_or_repeat_its_claim` | A source with the same statement repeated three times inside one document contributes exactly one citation and one claim occurrence; the two redundant repeats are recorded as accounted-for omissions, not silently dropped. |
| 7 | End-to-end provenance and receipt closure | `test_every_positive_claim_has_resolvable_provenance_and_accounted_omissions` (parametrized over 5 questions) | For every claim in every answer: citations resolve to a real item and chunk in the repository, and `receipt_ids` covers exactly the union of `evidence_used` and `evidence_omitted` — nothing presented without a receipt, nothing released and unaccounted for. |

An additional test, `test_benchmark_corpus_is_entirely_synthetic`, is a
fixture sanity check over the primary corpus (asserts its twelve source roots
are exactly the synthetic set constructed for this suite) rather than a
benchmark family itself. It does not cover the same-authority fixture or the
four round-two ad hoc `tmp_path` corpora, all of which are built by the same
`_write_sources`/inline-source-writing pattern and are synthetic by the same
construction.

## Results

Preserved system-validator evidence (`agent_orch.validators.command_succeeds@1`;
validator rerun is not permitted for this step, so these are reported, not
re-executed):

| Command | Exit | Result | Tied to | Evidence hash |
|---------|-----:|--------|---------|---------------|
| `python3 -m pytest tests/` | 0 | 245 passed in 23.04s | step_01_invert_merge_and_additive_absence acceptance criterion (invert the merge rule, add numeric divergence, make evidenced absence additive), attempt 1 | `5d6ab97a4aeae6981dc60f4d39ba5017c43555796465239a17a4a0c93e0d2290` |
| `python3 -m pytest tests/` | 0 | 245 passed in 23.29s | step_01_invert_merge_and_additive_absence acceptance criterion, attempt 2 | `8a2da7bf6ef0760d2327967cb5d2e53d556517422bd425eb369223dd40df657f` |

Both preserved runs' stdout itemizes `tests/answers/test_answer_benchmarks.py`
at 19 collected items (up from the 15 recorded before this round's repairs).
A fresh, non-preserved rerun of just that file, for this document's
per-family table below, confirms the same shape: `python3 -m pytest
tests/answers/ -v` — 19 passed in 1.10s, exit 0.

Per-family result, all pass:

| # | Family | Items | Result |
|---|--------|------:|--------|
| 1 | Cross-repository claim assembly | 1 | Pass |
| 2 | Fuzzy / partial-phrase matching | 1 | Pass |
| 3 | Cross-repository attribution breadth | 1 | Pass |
| 4 | Authoritative, evidenced absence (original + unresponsive regression + additive regression) | 3 | Pass |
| 5 | Conflict identification without a winner (original + in-vocabulary + reconciliation + out-of-vocabulary/numeric regressions) | 6 | Pass |
| 6 | Duplicate-source suppression | 1 | Pass |
| 7 | End-to-end provenance and receipt closure | 5 (parametrized) | Pass (5/5) |
| — | Fixture sanity check | 1 | Pass |

19/19 collected items pass, matching the preserved evidence above.

This step also drove full verification green ahead of writing this document,
fresh (not preserved validator evidence): `BLACK_NUM_WORKERS=1 python3 -m
black --check src tests tools` (`31 files would be left unchanged`),
`python3 -m ruff check src tests tools` (clean; the pre-existing
`pyproject.toml` linter-settings deprecation warning tracked as S2-R-10
remains, out of scope here), `python3 -m compileall -q src tests tools`
(clean, no output), `python3 tools/check_disclosure.py` (`check_disclosure:
clean — no host paths or credentials in tracked files.`), and `git diff
--check` (clean, no output) — all exit 0, with no repairs needed this time.

## Provenance Examples

Both examples below are reproduced directly from `tests/answers/test_answer_benchmarks.py`'s
synthetic fixtures by calling `answer()` in-process against the same temporary
SQLite projection the test suite builds. Neither example touches conflict
merging or absence assembly, so both are unchanged by this round's repairs.

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
questions), re-measured against the round-two-repaired pipeline:

| Confidence | Claims observed | Where |
|------------|-----------------:|-------|
| `DIRECTLY_EVIDENCED` | 11 | Documentation-steward question (3), fuzzy-name question (3), Orbital Archive absence (1), both sides of the Meridian conflict (2), both harbor-readiness statements (2) |
| `SYNTHESIZED` | 0 | Not exercised by this fixture family after this round's repair (see below) |
| `INFERRED` | 0 | Not exercised by this fixture family |
| `UNKNOWN` | 0 | Not exercised by this fixture family — absence and no-grounded-evidence paths that produce `UNKNOWN` overall confidence are covered separately by `tests/test_answer.py` and `tests/test_answer_absence.py`, not by the benchmark corpus |

This is a genuine behavior change, not a documentation correction: the prior
count (9 `DIRECTLY_EVIDENCED` + 1 `SYNTHESIZED` = 10 claims) reflected the
harbor-readiness question merging its duplicate-repository statement and its
independent-audit statement into one `SYNTHESIZED` claim. The S3-R-10 repair
inverted the merge rule — two evidence items now merge only when their
differing meaningful terms are empty or a known synonym set, rather than
merging whenever their Jaccard similarity clears the threshold and no known
antonym is seen — and those two harbor-readiness statements are not
term-equivalent under that stricter rule, so they now stay two separate
`DIRECTLY_EVIDENCED` claims. Independently re-derived for this step by calling
`answer()` directly against a freshly rebuilt copy of the primary fixture
corpus: 11 claims across the five questions, all `DIRECTLY_EVIDENCED`, 0
unresolved citations.

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
  equinox use divergent value words."* — both sources share the same declared
  authority and the same synthetic timestamp, so neither the
  authority-divergence nor the supersession signal would have fired; only the
  value-word signal catches this case, which is why it needed round two's
  more general fix to cover contradictions phrased outside `enabled`/`disabled`.
- `conflict.more_authoritative` and `conflict.newer` are both `Side.NEITHER`.

**Lyra retention window — same authority, numeric divergence, new in round two**
(family 5d, `test_same_subject_divergence_outside_value_word_list_is_a_conflict[numeric-divergence]`,
reproducing the shape the previous document could not demonstrate, since
Equinox's `enabled`/`disabled` pair was already inside the fixed value-word
list):

- Question: *"What is the retention window for Lyra in days?"*
- Left claim (`Confidence.DIRECTLY_EVIDENCED`): *"The retention window for
  Lyra is 30 days."* — citing `reviewer-left:numeric-divergence-left.md`,
  declared `Authority.DERIVED`.
- Right claim (`Confidence.DIRECTLY_EVIDENCED`): *"The retention window for
  Lyra is 90 days."* — citing `reviewer-right:numeric-divergence-right.md`,
  also declared `Authority.DERIVED`.
- `conflict.detail`: *"Competing statements about days, lyra, retention,
  window use different numeric values."* — the new numeric-divergence signal
  added by the S3-R-10 repair; neither statement contains a recognized value
  word, so the old vocabulary-based signal alone would have missed this
  entirely and the two statements would have merged into one self-
  contradictory `SYNTHESIZED` claim, as the reviewer proved against the
  pre-repair code.
- `conflict.more_authoritative` and `conflict.newer` are both `Side.NEITHER`.
- The sibling cases `enabled-versus-turned-off` (Kestrel release gate) and
  `permitted-versus-forbidden` (Vega export policy) reproduce the same shape
  for antonym pairs outside the fixed vocabulary rather than a numeric one —
  same assertions, same one-`Conflict`-two-claims result.

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

- **Fixture suite wall-clock**: within the full-suite preserved validator
  evidence above, `tests/answers/test_answer_benchmarks.py` accounts for 19 of
  the 245 collected items. A fresh, non-preserved rerun of just that file —
  `python3 -m pytest tests/answers/ -v` — completed in 1.10s, exit 0. This
  includes one module-scoped fixture that syncs all twelve primary-corpus
  documents through the real connector and repository once, amortized across
  11 of the 19 test items, plus a second module-scoped fixture for the
  two-document same-authority corpus, amortized across one further item; the
  four round-two regression items each build and sync their own small,
  function-scoped corpus rather than sharing a fixture.
- **Per-call `answer()` latency** (fresh, ad hoc, not a preserved validator
  command): calling `answer()` directly, in-process, against the already-synced
  primary fixture repository, for the five questions in family 7, three
  repeats each (15 calls) — mean 14.4ms, max 25.5ms, min 4.8ms. This excludes
  CLI process startup and the one-time sync; it isolates the plan → retrieve
  → select → assemble → detect-conflicts → narrate pipeline itself, now
  running the round-two-repaired merge, conflict, and absence-assembly code.

Both figures describe a tiny, deterministic, offline corpus and are useful as
a regression floor, not as a production capacity estimate.

## Recommendation

**Ready after specific follow-up.**

The two High findings from `code-reviews/review-sprint-3-repair.md` that
gated the prior recommendation — S3-R-10 (contradictions phrased outside a
fixed value-word vocabulary, including purely numeric divergence, merged into
one self-contradictory claim with zero conflicts) and S3-R-11 (a top-ranked,
relevant evidenced-absence statement replaced the whole answer instead of
joining it, so a short "X does not exist" record could suppress a correct
multi-source answer) — are repaired, each with permanent regression fixtures
in this benchmark suite (families 4c and 5d above), and the full suite (245
tests, preserved validator evidence, two independent runs, both exit 0) plus
fresh `black`/`ruff`/`compileall`/`check_disclosure.py`/`git diff --check` are
all clean with no repairs needed. This round's fix also changed measured
behavior on the existing corpus, not just added coverage: the harbor-readiness
question's two statements no longer merge into a `SYNTHESIZED` claim (see
Confidence Distribution), because the merge rule is now inverted to merge only
on demonstrated term-equivalence rather than refusing merge only on a known
antonym.

One correctness-adjacent defect from the same review remains open and is not
fixed by this step:

1. **S3-R-12 (Medium)** — `_conflict_signal`'s value-word and authority
   branches can report a `Conflict` between statements that do not actually
   disagree: two same-authority sources reading "The Corvus sign-off is
   required." and "The Corvus sign-off is required and approved." (the second
   simply adds information) still produce one spurious conflict, reproduced
   against the current code for this step
   (`conflict.detail`: *"Competing statements about corvus, sign-off use
   divergent value words."*). This is a false-positive disagreement, not a
   suppressed or merged claim, so it is a distinct defect from S3-R-10/S3-R-11
   and was out of this round's declared scope (round two addressed S3-R-10 and
   S3-R-11 only).

The remaining Medium and Low findings from both reviews are **not** addressed
by this step and remain open:

2. **S3-R-04 (Medium)** — `Answer` still carries no equivalent of
   `EvidenceBundle.denied_count` or `.truncated`; withholding is visible only
   through `Absence.withheld_count`, which exists only when the answer has no
   claims.
3. **S3-R-05 (Medium)** — `cmd_ask` (`src/lee_kb/main.py`) still does not pass
   `project_has_synchronized_content`, `corpus_fresh`, or `resolution_failed`
   to `answer()`, so the `UNKNOWN` absence branch purpose-built for an
   unsynchronized project remains unreachable from the CLI, which instead
   reports `NOT_FOUND`.
4. **S3-R-07, S3-R-08, S3-R-09 (Low)** — Provenance Examples still quote
   reformatted claim text rather than the raw chunk and undercount claims for
   Example 1; `docs/answer-architecture.md` still says v1 ships with no
   synthesis provider configured, when `DeterministicSynthesisProvider` is
   actually the default; `OUTSIDE_REQUESTED_PROJECT` omissions still report to
   the reader as `NOT_RELEVANT`.

Independently of both reviews, the same three items already carried forward
from the prior recommendations are still true and still gate real-world use:

5. **The LLM-backed `SynthesisProvider` is specified but not implemented.**
   `answer()` ships with only `DeterministicSynthesisProvider`, a template
   renderer with no model call — offline and auditable, but not natural
   prose. An LLM-backed provider requires explicit dependency approval per
   `AGENTS.md`'s "Add external runtime dependencies" guardrail.
6. **`answer()` has not been run against the real corpus.** Every result in
   this document comes from the synthetic benchmark fixtures; `retrieve()`
   has a real-corpus baseline (`evidence/real-corpus-parity-report.md`),
   `answer()` does not.
7. **Live filesystem verification remains a deferred extension.** Nothing
   here exercises `answer()` against a live, continuously-synchronized
   filesystem corpus over time.
8. **Two open items inherited from `retrieve()` remain open**: the
   OR-matcher worst-case latency decision (Open Question 5 in `context.md`)
   and permission-basis on receipts (Open Question 2), both of which affect
   `answer()` since it is a strict layer on top of `retrieve()`.

None of these are the confidently-wrong-answer class of defect this benchmark
suite specifically targets — the correctness defects a reader would notice as
a confidently wrong answer (S3-R-01, S3-R-02, S3-R-03, S3-R-10, S3-R-11) are
fixed and regression-tested. What remains is one narrower correctness-adjacent
defect (S3-R-12, a false-positive conflict rather than a wrong or suppressed
claim), honest-reporting completeness gaps (S3-R-04, S3-R-05),
documentation-accuracy gaps (S3-R-07, S3-R-08, S3-R-09), and scope boundaries
the mission explicitly requires stating plainly rather than implying
completion.
