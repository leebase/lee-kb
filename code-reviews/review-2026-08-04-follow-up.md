# Code Review - Final Follow-up - 2026-08-04

Independent review of the working tree after the final cold-review repairs,
the negated-value conflict repair, and the golden-baseline refresh. No files
were modified during this review.

## Verdict

**Conditional pass.** No High or Critical findings remain. Release closure is
conditional on disposition of S1-R-12, the query-level audit event for empty or
any denied retrieval.

## Verified Repairs

- `FINAL-R-01`: failure-aware `LocalFilesConnector.list_changes()` does not
  tombstone unavailable roots or subtrees.
- `S2-R-15`: scoped overlapping-root discovery reports
  `claimed_by_other_root` ownership counts.
- `FINAL-R-02`: deletion-only projects report `NOT_FOUND`; never-synced
  projects remain `UNKNOWN`.
- `FINAL-R-03` / `FINAL-R-04`: nested DOCX tables are retained and DOCX/PPTX
  body heading syntax cannot create citation headings.
- `S1-R-13`: stale refusal persists no release receipts.
- `S1-R-15`: package support is Python 3.11+, matching `tomllib`.
- Conflict edge cases: `required` versus `not optional` does not conflict, and
  `required and approved` versus `not optional and denied` retains the genuine
  approved/denied conflict.
- Golden baseline: `architecture-04` is rank 1; hit-at-1 is 14/20 and MRR is
  0.815555..., documented as 70.0% and 0.816.

## Remaining Findings

- **Medium - S1-R-12:** no durable query-level audit event exists for empty,
  fully denied, or mixed permitted/denied retrievals. The existing
  per-evidence receipt contract remains correct for released evidence. A new
  persisted record requires an explicit schema decision.
- **Low - S3-R-07:** benchmark provenance example still undercounts claims.
- **Low - S3-R-09:** out-of-project omissions still use `NOT_RELEVANT`.
- **Low - S1-R-17:** direct `Repository.search()` remains a principal-free
  internal provider boundary; shipped surfaces use governed retrieval.
- **Advisory:** S2-R-05 and S2-R-07 through S2-R-11 remain tracked in project
  memory.

## Checks

- `python3 -m pytest tests/` - 292 passed.
- `python3 -m pytest tests/golden/test_golden_corpus.py -q` - 25 passed.
- `python3 -m pytest tests/answers/test_answer_benchmarks.py -q` - 37 passed.
- Combined golden and answer checks - 62 passed.
- Black, Ruff, compileall, disclosure, and `git diff --check` - clean.
- CLI `--help` and `--version` - passed.
