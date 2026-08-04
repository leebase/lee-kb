# Code Review — Sprint 3 Repair of the Three High Findings

> Independent re-review, 2026-08-04. Reviewer role per `agents/reviewer.md` and
> `skills/code-review.md`. No implementation file was modified; every write in
> this step is inside `code-reviews/`.
>
> **Nothing below is accepted on the strength of the new regression fixtures.**
> Each of the three prior High findings was re-derived from a corpus I
> constructed for this review, written to disk, discovered and fetched through
> the real `LocalFilesConnector`, projected into a real SQLite database, and
> asked only through the public `answer()` surface (and, for one finding,
> through the shipped `lee-kb sync` / `lee-kb ask` commands). The probe scripts
> and captured output live in this step's scratch space
> (`probeA_contradiction.py`, `probeB_absence.py`, `probeB2_topranked.py`,
> `probeC_reconciliation.py`, `probeD_invariants.py`, `probeE_benchmark_doc.py`,
> plus `.out` files and `clitest/`); every command and exit code is listed under
> **Verification**.

## What This Slice Claimed

`code-reviews/review-sprint-3-governed-answer.md` (verdict `fail`) raised three
High findings. This slice claims all three are repaired with permanent
regression fixtures (benchmark families 4b, 5b, 5c), the suite green at 241
tests, and `docs/answer-benchmark-results.md` rewritten to match.

My independent re-derivation finds **one of the three fully repaired
(S3-R-03), and two repaired only for the exact shape they were reported
against**. Both remaining defects reproduce the original user-visible failure
verbatim on ordinary corpus shapes, one of them through the shipped CLI.

## Findings

| ID | Severity | Category | Location | Problem | Proposed Fix |
|----|----------|----------|----------|---------|--------------|
| S3-R-10 | High | Correctness / conflict detection and claim assembly | `src/lee_kb/answer_conflict.py:58` `_VALUE_WORDS`, `:255` `_value_words_diverge`, `:217` and `:250` inside `_conflict_signal`/`_subject_terms`; `src/lee_kb/answer.py:444` in `_assemble_initial_claims` | Both halves of the S3-R-01 repair — the new conflict signal *and* the merge refusal — are keyed to the same closed 14-word vocabulary (`active, approved, blocked, closed, created, denied, disabled, enabled, inactive, never, not, open, optional, required`). `_value_words_diverge` returns `False` unless **both** sides contribute a term from that set, so a contradiction expressed outside it reproduces the original S3-R-01 failure exactly: one `SYNTHESIZED` claim asserting both sides, zero conflicts. **Independently constructed and proven** (probe A, three corpora, each two same-authority sources synced through the real connector into real SQLite): `"The release gate for Kestrel is enabled."` vs `"… is turned off."` (Jaccard 0.500) → 1 claim, `confidence=synthesized`, text asserting both, **0 conflicts**; `"The export policy for Vega is permitted."` vs `"… is forbidden."` (0.600) → same; `"The retention window for Lyra is 30 days."` vs `"… is 90 days."` (0.667) → same. In each case `_conflict_signal` falls through the value-word check (one side empty), the authority check (equal), and the supersession check (no wording, equal timestamps) and returns `None`. Numeric divergence — the commonest contradiction shape in a policy corpus — is not covered at all, and `_subject_terms` (`answer_conflict.py:250`) discards decimals, so `30` and `90` are invisible to detection *and* count as identical subjects for the similarity merge. **Reproduced end to end through the shipped CLI** (probe A-CLI): `lee-kb sync` then `lee-kb ask "What is the state of the release gate for Kestrel?"` prints one claim under `Confidence: synthesized` reading `"… is enabled. … is turned off."`, cites both files, and shows no Conflicts section. The in-vocabulary shape the fixture covers does work — probe A case A1 yields 2 singly-cited claims and 1 `Conflict`, and the merge is still refused when conflict detection is neutralized entirely — so the repair is real, but its reach is the fourteen words. This violates the invariant asserted at `src/lee_kb/answer.py:23-26` for every contradiction outside them. | Stop treating contradiction as a lexical-membership test. (1) Invert the merge rule in `_assemble_initial_claims`: merge only when the two texts' *differing* meaningful terms are empty or a known synonym set, instead of merging unless a known antonym is seen — over-conservative merging is always safe, since two unmerged agreeing sources cost only one extra cited claim. (2) Add numeric divergence as an explicit conflict signal: when two same-subject statements share a unit or measure context and carry different numeric literals, emit a `Conflict` and refuse the merge; drop the blanket `isdecimal()` discard from `_subject_terms` so figures participate in subject comparison. (3) Extend benchmark family 5 with three fixtures — an out-of-vocabulary antonym pair, a numeric contradiction, and a negation-only pair — each asserting exactly one `Conflict` and two singly-cited claims. |
| S3-R-11 | High | Correctness / answer quality | `src/lee_kb/answer_absence.py:243` `_explicit_absence_evidence` (`:252-254` top-rank gate, `:264` relevance gate); `src/lee_kb/answer.py:239-240` and `:321` `_assemble_evidenced_absence` (`:341` demotion detail) | The S3-R-02 repair narrows the evidenced-absence short-circuit but keeps its shape: when the gate passes, the whole answer is **replaced** by that one claim and every other selected evidence item is demoted to `evidence_omitted` under *"Not part of the explicit statement answering this question."* The two new gates are weak. The relevance gate is the default 0.25 threshold, so one shared term suffices for a four-term question; the top-rank gate is a BM25 ranking accident that short documents win. **Independently constructed and proven as a control/treatment A/B** (probe B2): asking *"What does the aurora readiness review require?"* over two `CANONICAL` sources that answer it returns 2 `DIRECTLY_EVIDENCED` claims citing both. Adding one short `CANONICAL` decision record reading *"The aurora readiness review dossier does not exist."* to the *identical* corpus makes that record rank first in the governed bundle and collapses the answer to **1 claim**, still labelled `DIRECTLY_EVIDENCED`, `absence is None`, citing only the dossier note, with **both substantive canonical sources demoted to `evidence_omitted`**. The reader is told confidently and with a citation that a dossier does not exist when they asked what the review requires, with no signal that the real answer was suppressed. The absence sentence's relevance against the question's four meaningful terms is 0.750, three times the gate. Probe B1 reproduces the prior review's exact construction (an unrelated absence note added to an identical two-source corpus) and confirms **that** shape is genuinely fixed — the substantive claims survive — so this is the residual class, not a regression. | Make the evidenced absence an **additional** claim rather than a replacement: assemble claims from the full selected evidence as normal, then, if `_explicit_absence_evidence` matches, append its cited statement as one more `DIRECTLY_EVIDENCED` claim in rank order. That preserves the family-4 guarantee that an explicit "was never created" is cited rather than silently empty, makes suppression impossible by construction, and removes the need for the top-rank heuristic entirely. If a replacement path is kept, require the absence sentence's subject terms to cover the question's *head* terms rather than 25% of any terms, and add a regression fixture for "absence statement about a different aspect of the same topic, ranked first" asserting the substantive claims survive. |
| S3-R-12 | Medium | Correctness / honest reporting | `src/lee_kb/answer_conflict.py:207` `_conflict_signal` (`:217` value-word branch, `:223` authority branch) | `_conflict_signal` emits a `Conflict` between statements that do not disagree, because both of its non-supersession signals fire on token overlap alone. **Shape A, introduced by the S3-R-01 repair** (probe A case A5): two same-authority sources reading *"The Corvus sign-off is required."* and *"The Corvus sign-off is required and approved."* — which agree, the second merely adding information — produce one `Conflict` detailed *"Competing statements about corvus, sign-off use divergent value words."*, because `_value_words_diverge` compares value-word **sets** and `{required}` ≠ `{required, approved}`. **Shape B, pre-existing but now easier to reach** (probe B1 treatment run): three documents where two `CANONICAL` sources state harbor-readiness requirements and one unrelated `DERIVED` note reads *"The legacy harbor manifest does not exist."* produce **two** conflicts, both detailed *"Competing statements about harbor have different declared authority."* The only thing the statements share is the token `harbor`; neither competes with the other. A reader shown a Conflicts section naming disagreements that do not exist loses the ability to trust the section when it matters, and a machine consumer filtering on `conflicts` gets false positives. Neither shape is covered by benchmark family 5, whose fixtures all contain genuine contradictions. | For the value-word branch, require the divergence to be an **antonym** relationship (or, under the S3-R-10 fix, an actual difference in what the statements assert), not mere set inequality. For the authority branch, require the two statements to be about the same *predicate*, not merely to share a subject token — for example, require that they are otherwise near-duplicates, the same condition assembly already uses to consider merging. Add two negative fixtures to family 5: agreeing sources with asymmetric value words, and same-topic cross-authority sources making unrelated statements — each asserting **zero** conflicts. |
| S3-R-13 | Medium | Documentation accuracy | `docs/answer-benchmark-results.md:8-14`, `:38-40`, `:225-236` (Recommendation) | The benchmark document states without qualification that S3-R-01, S3-R-02, and S3-R-03 "are repaired, each with a permanent regression fixture", and family 5b's description generalizes to "Two sources of the **same** declared authority that directly contradict each other still produce one `Conflict` and two separate, singly-cited claims". My probes contradict the generalization: that guarantee holds only when both sides draw from `_VALUE_WORDS` (S3-R-10), and family 4b's guarantee holds only when the absence sentence is not top-ranked (S3-R-11). The document's *recommendation value* — **"Ready after specific follow-up"** — is inside the declared vocabulary and happens to match my own conclusion, but the text justifies it with a completeness claim that is not true, and its list of what remains open contains no correctness defect at all ("None of these are correctness defects in the repaired slice"). A reader using this document to decide whether to release would be materially misled. Everything else in it that I could re-derive reproduces exactly: the Confidence Distribution (probe E — 9 `DIRECTLY_EVIDENCED` + 1 `SYNTHESIZED` = 10 claims over the five family-7 questions, 0 unresolved citations, so S3-R-06 is genuinely closed), the same-authority Conflict Example (probe E — detail string, `newer=NEITHER`, `more_authoritative=NEITHER`, no `winner` attribute), and the 15 collected benchmark items. | Qualify both fixture descriptions to the shape actually guaranteed ("two sources whose divergence is expressed with a recognized value-word pair"; "an absence-shaped sentence that is not the top-ranked chunk"), and move S3-R-10 and S3-R-11 into the Recommendation's open list as correctness defects, above the honest-reporting and documentation items. Keep the recommendation value; change what it is gated on. |
| S3-R-14 | High | Security / disclosure | `tests/test_contracts.py:62` | A tracked file in a public repository hardcodes an absolute POSIX home path: `uri=f"file:///home/lee/{item_id.source_object_id}"`. This is the class the project deliberately purged from project memory (S2-R-01, S2-R-02, S2-R-12; `context.md` Environment Notes records that the working-directory path is intentionally not recorded because the repository is public). A repository-wide scan over all **94** tracked files for the whole class — `/home/<user>`, `/Users/<user>`, `C:\Users\`, `/root/`, `/var/folders/`, `/private/var/`, `/mnt/…`, `/media/…`, `/opt/…`, `/srv/…`, `~/<a>/<b>` — returns this as the only hit outside `code-reviews/`; the remaining hits are the documented public config contract `~/.config/lee-kb/config.toml`, which is not a host-path leak. Rated **High** under this step's declared disclosure policy that any leak of the class is at least a High finding. Stated plainly for calibration: it discloses the account name `lee`, already public via the repository owner `leebase/lee-kb`, the documented author, and the default principal `lee@leebase.com` in `src/lee_kb/main.py`; it does **not** disclose the checkout location, private corpus content, or anything credential-shaped, and it is pre-existing Sprint 1 test code outside the Sprint 3 slice. On impact alone the rating would be Low. | Replace with a neutral synthetic path — `file:///synthetic/{item_id.source_object_id}` or a `tmp_path`-derived URI — and add the absolute-host-path pattern class to a `tools/` disclosure check that scans `git ls-files`, so the whole repository is checked automatically rather than reviewer-by-reviewer. |

### Prior High finding confirmed fully repaired

**S3-R-03 (conflict reconciliation) — repaired, verified beyond its fixture.**
Probe C ran five constructed shapes, each three to five same-topic sources
across two authorities, none of them the shipped fixture's corpus: 1 canonical +
2 identical derived; 2 identical canonical + 1 derived; 2+2; 2+3; and a mixed
case where the agreeing pair is cross-authority and merges first. In **all
five**, the maximum number of claims citing any single chunk is **1**, no merged
claim survives reconciliation asserting both sides, and `answer()` never raises.
The transitive `evidence_claims` update at `answer_conflict.py:117-122` does the
work, and the repair additionally added a construction-time invariant —
`answer_contracts.py:548`, *"a chunk may be cited by at most one claim"* — so
this defect class now fails loudly at construction rather than surfacing as
duplicated prose. That is the stronger of the two fixes the prior review
proposed, and it landed.

### Remediation Roadmap

**Fix Now** — S3-R-10 and S3-R-11. Each still produces a confidently-labelled
wrong answer on an ordinary corpus shape, and S3-R-10 still reproduces through
`lee-kb ask`. Both should land with the class-level fixtures named above, since
the current families pass over both.

**Fix Soon** — S3-R-14 (a one-line test change plus the `tools/` scan), then
S3-R-12 and S3-R-13, then the still-open S3-R-04 and S3-R-05.

**Fix Later** — S3-R-07, S3-R-08, S3-R-09.

### Test Additions Recommended

- [ ] Family 5: out-of-vocabulary antonym pair → one `Conflict`, two singly-cited claims (S3-R-10).
- [ ] Family 5: numeric contradiction (`30 days` vs `90 days`) → one `Conflict`, two singly-cited claims (S3-R-10).
- [ ] Family 5: negation-only pair (`is enabled` vs `is not enabled`) → one `Conflict`, two singly-cited claims (S3-R-10).
- [ ] Family 4: absence-shaped sentence about a different aspect of the same topic, ranked **first** → substantive claims survive (S3-R-11).
- [ ] Family 5 negatives: agreeing sources with asymmetric value words, and same-topic cross-authority sources making unrelated statements → **zero** conflicts (S3-R-12).
- [ ] `tools/` disclosure check over `git ls-files` covering the absolute-host-path class (S3-R-14).

## Residual Risks

1. **Prior Medium findings that remain open.** `S3-R-04` — `Answer` still
   carries no equivalent of `EvidenceBundle.denied_count` or `.truncated`;
   probe D4 lists `dataclasses.fields(Answer)` and finds no `withheld`,
   `denied`, or `truncated` field, so withholding is visible only through
   `Absence.withheld_count`, which exists only when the answer has no claims.
   `S3-R-05` — `cmd_ask` (`src/lee_kb/main.py:619`) still calls
   `compute_answer()` with only `principal`, `project`, and `top_k`, so
   `project_has_synchronized_content`, `corpus_fresh`, and `resolution_failed`
   keep their defaults and the purpose-built `UNKNOWN` absence branch remains
   unreachable from the only shipped surface.
2. **Prior Low findings that remain open.** `S3-R-07` — the Provenance Examples
   still quote reformatted, heading-free claim text and still present the
   fuzzy-name question as producing one claim, where probe E measures three.
   `S3-R-08` — `docs/answer-architecture.md:241` still reads "v1 ships with no
   provider configured", while `answer()` defaults to
   `DEFAULT_SYNTHESIS_PROVIDER`. `S3-R-09` —
   `answer_evidence.py:111 as_answer_omission` still reports
   `OUTSIDE_REQUESTED_PROJECT` to the reader as `NOT_RELEVANT`.
   `S3-R-06` is **closed**: probe E independently reproduces the corrected
   Confidence Distribution (9 + 1 = 10 claims, 0 unresolved citations).
3. **The LLM-backed `SynthesisProvider` is unimplemented, pending dependency
   approval.** `answer()` ships with only `DeterministicSynthesisProvider`, a
   standard-library template renderer with no model call. An LLM-backed
   provider requires a runtime model-client dependency, which is not approved
   under `AGENTS.md`'s "Add external runtime dependencies" guardrail (Open
   Question 6 in `context.md`). I verified that boundary rather than assuming
   it: `pyproject.toml`'s `project.dependencies` is `[]` (the only extra is
   `dev = [pytest, black, ruff]`); an AST walk over all **30** tracked `*.py`
   files finds exactly one non-stdlib, non-local import across the repository —
   `pytest`, in 13 test files; and a repository-wide scan of all 94 tracked
   files for the model-client class (`anthropic`, `openai`, `langchain`,
   `llama_index`, `litellm`, `cohere`, `mistralai`, `ollama`,
   `google.generativeai`, `transformers`, `huggingface`,
   `sentence_transformers`, `tiktoken`, `vertexai`, `bedrock`, `llama_cpp`,
   `httpx`, `requests`, `aiohttp`, `urllib3`, `torch`, plus `claude-*`/`gpt-N`
   model-id shapes) returns **zero** hits in `src/`, `tests/`, or `tools/`.
   Hits exist only in `playbooks/*.yaml` (Agent-Orch crew model selection, not
   product code), `research/`, `architecture.md`, `evidence/`, and
   `code-reviews/`. Until a provider exists, `lee-kb ask` returns template
   prose, not natural-language synthesis — a reader expecting synthesis gets
   structure instead.
4. **Live filesystem verification is deferred.** Every result in this review, in
   `docs/answer-benchmark-results.md`, and in the delivered test suite comes
   from temporary synthetic projections built for the test — including my own
   probes, which write throwaway roots under a temporary directory (and, for
   the CLI probe, under this step's scratch space) and sync them through the
   real connector into real SQLite. Nothing exercises `answer()` against a live,
   continuously-synchronized filesystem corpus over time: freshness drift,
   resync during use, tombstoning mid-question, concurrent sync. That
   verification path does not exist yet, so `answer()`'s behavior under a moving
   corpus is unmeasured.
5. **`answer()` has still never been run against the real corpus.** `retrieve()`
   has a real-corpus baseline (`evidence/real-corpus-parity-report.md`, ~1,213
   documents); `answer()` has only the twelve-document synthetic fixture set
   plus a two-document conflict fixture. S3-R-10 and S3-R-11 are both
   corpus-shape sensitive, and a real policy corpus holds far more numeric
   values, out-of-vocabulary antonyms, and absence-shaped sentences than
   fourteen fixtures do, so I expect their incidence there to be materially
   higher than in the suite. This is Open Question 7 in `context.md`.
6. **The benchmark corpus still cannot catch the defects it was written
   beside.** Both remaining High findings survive a green 241-test suite and a
   green 15/15 benchmark run, exactly as the prior three survived a green
   235-test suite. Each new fixture pins the precise shape its finding was
   reported against, not the class. Repairs should land with the class-level
   fixtures listed under Test Additions Recommended, or the next regression will
   pass the same way.
7. **Two Sprint 1/2 open questions are inherited unchanged.** The OR-matcher
   worst-case retrieval latency (~1.521s, Open Question 5) and permission-basis
   on receipts (Open Question 2) both apply to `answer()`, which calls
   `retrieve()` directly.

## Verification

### Preserved system-validator evidence (reported, not re-executed)

Validator rerun is not permitted for this step, so the seven preserved
`agent_orch.validators.command_succeeds@1` records are summarized from the
preserved artifact
(`.../step_03_independent_rereview/attempt-2/preserved-validator-evidence.json`)
— not re-run, and not restated from memory. All seven have exit status 0 and
`passed: true`.

| # | Command | Exit | Recorded result | Tied to |
|---|---------|-----:|-----------------|---------|
| 1 | `python3 -m pytest tests/` | 0 | `241 passed in 21.13s` | step_01 repair of S3-R-01/02/03, criterion 1 (attempt 1) |
| 2 | `python3 -m pytest tests/` | 0 | `241 passed in 21.47s` | step_01 repair of S3-R-01/02/03, criterion 1 (attempt 2) |
| 3 | `python3 -m pytest` | 0 | `241 passed in 21.87s` | step_02 verification/docs, criterion 1 |
| 4 | `python3 -m black --check src tests tools` | 0 | `All done! ✨ 🍰 ✨` / `30 files would be left unchanged.` | step_02, criterion 2 |
| 5 | `python3 -m ruff check src tests tools` | 0 | `All checks passed!`; emits the pre-existing `select`/`ignore` → `lint.*` deprecation warnings | step_02, criterion 3 |
| 6 | `python3 -m compileall -q src tests tools` | 0 | no output | step_02, criterion 4 |
| 7 | `git diff --check` | 0 | no output | step_02, criterion 5 |

The product-verification commands are green. That is a real fact about the
delivered slice, and it is not in tension with this review's verdict: S3-R-10
and S3-R-11 are shapes the suite does not exercise, which is exactly finding
S3-R-13's point and residual risk 6's.

### Independent probes executed for this review

Each built a corpus on disk, discovered and fetched it through the real
`LocalFilesConnector`, and projected it into a real SQLite database — the
governed path was not mocked. All exited 0.

| Probe | Command | Exit | What it establishes |
|-------|---------|-----:|---------------------|
| A | `python3 probeA_contradiction.py` | 0 | **S3-R-10, both halves.** Five two-source same-authority corpora. A1 (in-vocabulary `enabled`/`disabled`): 2 singly-cited `DIRECTLY_EVIDENCED` claims, 1 `Conflict`, max 1 citation per chunk — and with `answer.detect_conflicts` neutralized, **still** 2 claims and 0 merged claims, so the merge refusal genuinely holds independently of detection. A2 (`enabled`/`turned off`), A3 (`permitted`/`forbidden`), A4 (`30 days`/`90 days`): each yields **1 `SYNTHESIZED` claim asserting both sides and 0 conflicts**, both with and without detection neutralized — the merge-refusal half fails on exactly the same inputs as the detection half, so improving detection alone would not close it. A5 (`required` vs `required and approved`, two agreeing sources): 1 spurious `Conflict` → finding S3-R-12 shape A. |
| A-CLI | `python3 -m lee_kb.main sync --config …`, then `python3 -m lee_kb.main ask "What is the state of the release gate for Kestrel?" --config …` | 0, 0 | **S3-R-10 reproduces through the shipped CLI**, not only in-process. `sync` reports `2 created`; `ask` prints one claim under `Confidence: synthesized` reading `"… is enabled. … is turned off."`, cites both files, and shows no Conflicts section. |
| B | `python3 probeB_absence.py` | 0 | **The prior S3-R-02 construction is genuinely fixed.** Control (two `CANONICAL` harbor-readiness sources) → 2 claims. Treatment (identical corpus + one unrelated `DERIVED` "does not exist" note) → **3** claims; both substantive claims survive with their citations. The same run also surfaces S3-R-12 shape B: 2 conflicts detailed "Competing statements about harbor have different declared authority" between statements that do not compete. |
| B2 | `python3 probeB2_topranked.py` | 0 | **S3-R-11.** Control (two `CANONICAL` aurora-readiness sources) → 2 `DIRECTLY_EVIDENCED` claims. Treatment (identical corpus + one short same-topic `CANONICAL` record reading "The aurora readiness review dossier does not exist.") → the record ranks **first** in the governed bundle and the answer collapses to **1 claim**, `absence=None`, both substantive canonical sources demoted to `evidence_omitted`. The absence sentence's relevance against the question's four meaningful terms is 0.750, against a 0.25 gate. |
| C | `python3 probeC_reconciliation.py` | 0 | **S3-R-03 is fully repaired.** Five constructed shapes (3, 3, 4, 5, and 3 same-topic sources across two authorities, including one where the agreeing pair is cross-authority and merges first): in every case the maximum citations of any one chunk is **1**, no surviving merged claim asserts both sides, and no shape makes `answer()` raise. |
| D | `python3 probeD_invariants.py` | 0 | **The sprint invariants hold.** D1: a transparent recording proxy shows the complete set of repository calls during `answer()` is `search` (from `lee_kb.retrieval`) then `record_receipt` ×2 (from `lee_kb.governance`) — **identical to the sequence `retrieve()` alone produces on the same inputs** — with **no** call originating in any `lee_kb.answer*` module; neutralizing `answer.retrieve` makes `answer()` raise rather than fall back, so there is no alternate evidence path. D2: over four questions, 5 claims, **0** uncited claims and **0** unresolved citations (every `item_id`/`chunk_id` resolves to a real item and chunk), and `receipt_ids` covers exactly `evidence_used ∪ evidence_omitted` on all four. D3: a document owned by another principal reports `INACCESSIBLE` with `withheld_count=1` and `UNKNOWN` confidence and is asserted **not** `NOT_FOUND`; silence → `NOT_FOUND`; `project_has_synchronized_content=False` → `UNKNOWN`; `resolution_failed=True` → `UNKNOWN`; each carries a distinct detail string. D4: `answer()`'s signature contains **no** confidence parameter, and the same question over one source yields `directly_evidenced` while over two independent sources it yields `synthesized` — different evidence shape, different confidence, same caller. |
| E | `python3 probeE_benchmark_doc.py` | 0 | **The benchmark document's numbers reproduce.** Rebuilding the twelve-document primary fixture corpus and asking the five family-7 questions gives 9 `directly_evidenced` + 1 `synthesized` = 10 claims with 0 unresolved citations, matching the document exactly (S3-R-06 closed). The same-authority Equinox fixture reproduces as 2 singly-cited claims + 1 `Conflict` with detail "Competing statements about channel, deployment, equinox use divergent value words", `newer=NEITHER`, `more_authoritative=NEITHER`, and no `winner` attribute. |
| — | `python3 -m pytest tests/answers/ --collect-only -q` | 0 | `15 tests collected in 0.07s` — confirms the benchmark suite's claimed item count. Collection only; no test was executed and no preserved validator command was re-run. |

### Repository-wide invariant and disclosure scans

Run over the **class**, not a single pattern, and over **all 94 tracked files**
(`git ls-files`), not the delivered slice alone.

| Scan | Command | Result |
|------|---------|--------|
| Declared runtime dependencies | `python3 -c` reading `pyproject.toml` via `tomllib` | `project.dependencies == []`; the only extra is `dev = [pytest>=7.0, black>=23.0, ruff>=0.1.0]`; build requires `setuptools>=61.0`, `wheel`. **No runtime dependency was added.** |
| Every third-party import | AST walk over all **30** tracked `*.py` files, comparing each top-level import against `sys.stdlib_module_names` | The complete non-stdlib, non-local import set is `{pytest}` (13 test files). Nothing else. |
| LLM / model-client class | `git ls-files -z \| xargs -0 grep -InE '<22-term alternation + claude-*/gpt-N model-id shapes>'` | **Zero** hits in `src/`, `tests/`, or `tools/` (the single hit under the broad alternation is the English word "requests" inside a `governance.py` error string). Hits exist only in `playbooks/*.yaml`, `research/`, `architecture.md`, `evidence/`, and `code-reviews/`. |
| Network / execution capability | `grep -rInE 'socket\|urllib\|http\.client\|smtplib\|ftplib\|subprocess\|os\.system\|popen\|eval(\|exec('` over `src/` | One source: `connectors/local_files.py:556` runs `git check-ignore -z --stdin` with a fixed argv and piped stdin (Sprint 1/2 code; no shell, no user-controlled binary). No network capability anywhere in `src/`. |
| Absolute host paths | `git ls-files -z \| xargs -0 grep -InE '(/home/<u>\|/Users/<u>\|C:\\Users\\\|/root/\|/var/folders/\|/private/var/\|/mnt/<a>\|/media/<a>\|/opt/<a>\|/srv/<a>\|~/<a>/<b>)'` | **One** hit outside `code-reviews/`: `tests/test_contracts.py:62` → finding **S3-R-14**. The other hits are the documented public config contract `~/.config/lee-kb/config.toml` in `README.md`, `architecture.md`, `context.md`, `docs/decisions.md`, and `main.py`. **Zero** hits in any Sprint 3 delivered file. |
| Credential shapes | `git ls-files -z \| xargs -0 grep -InE '(api[_-]?key\|secret[_-]?key\|client[_-]?secret\|access/refresh[_-]?token\|bearer …\|password=\|private[_-]?key\|BEGIN … PRIVATE KEY\|AKIA…\|sk-…\|ghp_…\|xox[baprs]-\|eyJ…\|Authorization:)'` | Four hits, all the connector's own secret **tripwire** and its tests: `research/employee-zero-kb-reference.md:44` (the rule), `connectors/local_files.py:158` (the pattern docstring), `tests/test_local_connector.py:711,713` (assertions exercising it). **No credential value anywhere.** |
| Private corpus content | `grep -IlE 'ai-employee-factory\|ai-employee-book\|employee-zero\|Employee Zero\|tviq\|knowledge/sources\.toml'` over all tracked files; plus `git ls-files \| grep -E '\.(sqlite\|sqlite3\|db\|env\|pem\|key\|p12\|pfx)$\|\.lee-kb\|\.kb/'` | 18 files reference the corpus by **name** (project memory, architecture, playbooks, prior evidence) — root names and counts, no document content. **No** `.sqlite`, `.db`, `.env`, `.pem`, or key artefact is tracked. |
| E-mail addresses | `git ls-files -z \| xargs -0 grep -IonE '<address pattern>'` | Exactly three distinct values across the repository: `intern@example.com`, `someone-else@example.com` (test placeholders), and `lee@leebase.com` (the published owner identity and documented default principal). No third-party address. |

### Review lenses and their outcome

| Lens | Outcome |
|------|---------|
| Governed surface exclusivity (`answer()` composes strictly over `retrieve()`) | Clean — probe D1: call-sequence identity with `retrieve()`, no repository call from any answer module, no fallback path. |
| Citations and receipt closure | Clean — probe D2 (0 uncited claims, 0 unresolved citations, receipts covering exactly used ∪ omitted) and probe E (0 unresolved over the benchmark corpus). |
| Absence states | S3-R-11. The three states remain distinguishable and `INACCESSIBLE` is never reported as `NOT_FOUND` (probe D3); the residual defect is the evidenced-absence path replacing, rather than joining, a responsive answer. |
| Conflict detection and claim assembly | S3-R-10, S3-R-12. Correct for the in-vocabulary shape; incorrect for out-of-vocabulary and numeric contradictions, and over-triggering on non-disagreements. |
| Conflict reconciliation | Clean — probe C over five shapes, plus the new construction-time one-claim-per-chunk invariant (S3-R-03 fully repaired). |
| Confidence model | Clean — derived, not assertable (probe D4). |
| Dependency and LLM boundary | Clean — no runtime dependency added, no model client anywhere in product code (repository-wide). |
| Disclosure and secrets | S3-R-14 — one absolute host path in a pre-existing tracked test file; no credential value, no private corpus content, no tracked projection artefact. |
| Benchmark reproducibility and documentation | S3-R-13. Every number I could re-derive reproduces exactly; the completeness claim around the repairs does not. |
| Tests and documentation | S3-R-13, plus the still-open S3-R-04, S3-R-05, S3-R-07, S3-R-08, S3-R-09 and the class-level fixture gaps under Test Additions Recommended. |

### Readiness criteria

Recorded per this step's commissioning contract. Platform-owned post-execution
attestations (execution identity, executed route, validator authority,
semantic-judge execution, evidence-chain status) are produced after this step
returns and are **not** certified here; where the packet already carries a
record, it is reported, not re-derived.

| Criterion | State | Basis |
|-----------|-------|-------|
| S3-R-01 contradiction repair complete | `verified_false` | Probes A and A-CLI: out-of-vocabulary and numeric contradictions reproduce the original failure in both halves. |
| S3-R-02 absence-suppression repair complete | `verified_false` | Probe B2 control/treatment: a top-ranked same-topic absence sentence still replaces a responsive two-source answer. |
| S3-R-03 reconciliation repair complete | `verified_true` | Probe C over five shapes, plus the construction-time one-claim-per-chunk invariant. |
| `answer()` composes strictly over `governance.retrieve()` | `verified_true` | Probe D1. |
| Every substantive claim carries a resolving citation | `verified_true` | Probes D2 and E: 0 uncited, 0 unresolved. |
| The three absence states remain distinguishable; `INACCESSIBLE` is never `NOT_FOUND` | `verified_true` | Probe D3. |
| Confidence is derived, not asserted | `verified_true` | Probe D4. |
| No runtime dependency added; no LLM client imported | `verified_true` | Repository-wide dependency, AST-import, and model-client scans over all 94 tracked files. |
| No absolute host path, private corpus content, or credential-shaped detail in any tracked file | `verified_false` | `tests/test_contracts.py:62` (S3-R-14); the credential and corpus-content classes are clean. |
| Product verification commands green (per preserved system-validator records) | `verified_true` | Seven preserved records, all exit 0, summarized above. |
| Benchmark document's recommendation matches observed behavior | `verified_false` | S3-R-13: the recommendation value is right; its stated justification is not. |
| Semantic conformance independently judged | `not_evidenced` (`required_evidence`: `semantic_judge_execution`) | This playbook declares no `semantic_check` rule, so the packet marks that evidence class not applicable. |

### Verdict

**fail** — two High correctness findings and one High-by-policy disclosure
finding.

S3-R-03 is genuinely and thoroughly repaired, including a construction-time
invariant that makes its whole defect class unrepresentable. The other two
repairs are real but shape-bound: each fixes the exact corpus the prior review
built and leaves the class open. A contradiction phrased in any words outside a
fourteen-item list — including every numeric disagreement — still produces one
claim asserting both sides, with no conflict, through the shipped `lee-kb ask`
command; and a short absence-shaped sentence that happens to rank first still
replaces a correct, multi-source, canonical answer and demotes it to
`evidence_omitted`.

The governance skeleton continues to hold everywhere I attacked it: governed
exclusivity, fail-closed authorization, citation and receipt closure, absence
distinguishability, and derived confidence all survived independent probing.
The defects remain confined to claim assembly, conflict detection, and absence
short-circuiting, and each has a concrete, bounded fix.

Recommendation: **Ready after specific follow-up**, gated on S3-R-10 and
S3-R-11 landing with class-level rather than shape-level fixtures, and on
S3-R-14. The slice should not be released to a reader as it stands.

*Reviewed 2026-08-04. `tools/validate_verdict.py` was run against the
accompanying verdict before this review was finished.*
