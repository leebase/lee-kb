# Governed AI Delivery: A Worked Example

Every AI vendor now says some version of "our AI writes the code." That claim
answers nothing a buyer needs answered. It doesn't say who checked the AI's
work, what happened when the check found a real problem, or what record
exists afterward for someone who wasn't in the room. This document answers
those questions using one real project — **lee-kb**, a governed
knowledge-retrieval system — as the worked example, reporting the numbers
that came out of it, including the ones that aren't flattering.

Nothing here is a demo built to look good. It is a build, reviewed under a
verdict that could block it, run against a real ~1,200-document corpus, and
interrupted by a real hardware failure mid-review. What follows is what
actually happened.

## The problem with "AI wrote our code"

That sentence says nothing about risk. It doesn't say whether anyone
independent checked the result, whether the check could actually stop a bad
outcome from shipping, or whether a durable record exists for a client's own
engineers to audit later. "It works" and "it should exist this way" are
different questions. Passing tests answer the first. They did not answer the
second here — and that gap is exactly where the most serious finding below
was found.

## What governed delivery means, concretely

- **Validation gates on every step.** Structural and system checks run
  before a step counts as done. A worker's own claim that "it passed" is
  never the authority; a separate validator's recorded result is.
- **Human approval before implementation begins.** The design contracts for
  what will be built are reviewed and approved by a person before any code
  is written against them.
- **Independent review with a verdict that blocks.** A separate reviewer
  role — not the builder — re-derives the system's behavior from the
  delivered code and its own probes, not from the builder's claims, and
  issues a verdict. A "fail" verdict halts completion; it is not advisory
  prose filed and ignored.
- **An evidence trail that outlives the session.** Validator results, review
  verdicts, findings and their repairs, and human approvals are written to a
  durable run record, not held in a model's conversational memory.

The rest of this document is what those four commitments produced.

## The worked example: lee-kb

lee-kb is a governed knowledge fabric: it connects to knowledge that already
lives somewhere else, builds a searchable projection of it, and answers
questions through a retrieval path that checks permissions before any
content reaches a model, records a citation and a receipt for every piece of
evidence released, and reports how fresh that evidence is. It does not move
or own the underlying data, and it grants no AI system the authority to act
— only to see, and to prove what it saw and why it was allowed to.

The first governed slice — local document sync, permission-checked
retrieval, citations, freshness, and an evaluation harness — was built
end to end under the process above, then pointed at a real ~1,200-document
corpus.

**Outcome, by the numbers:**

| Measure | Result |
|---|---|
| Independent review verdict | Clean — zero Critical/High findings — after 3 review cycles |
| Gating-severity findings surfaced | 3, all confirmed real by reproduction, all repaired and re-verified, 0 false positives |
| Human code fixes required | 0 |
| Infrastructure failures survived mid-review | 1 hard host reboot; zero governed work lost |
| First real-data run | ~1,200 documents, 15 source locations, zero fetch failures, zero unauthorized disclosures |

A second, independent review — run after the system was pointed at that real
corpus for the first time — again returned zero Critical or High findings.
Both reviews left advisory findings open on the record; those are addressed
below, not hidden.

## Four moments that matter

### 1. The authorization catch

The system's contract is that no evidence reaches anyone without a
permission check first. The build's own test suite — over 100 passing tests
— agreed the contract held. It didn't. Independent review found a second,
unguarded code path into the same retrieval data that skipped the
permission check entirely and wrote no audit record when used. The reviewer
reproduced the failure directly, with a test principal holding no access
rights, and confirmed that principal could read private content through the
unguarded path while the governed path correctly refused the same request.

This is the clearest evidence here of why independent review is a different
instrument than testing. The tests asked "does retrieval return correct
results." Nobody had asked "is this the *only* way to get results." The
review asked that, on its own initiative, and it was a real defect. The
unguarded path was deleted, and a permanent regression check now asserts
that exactly one code path in the system can produce retrievable evidence
at all.

### 2. The honest baseline

The evaluation harness that scores retrieval quality initially reported
85.0% hit-at-1 accuracy (0.925 mean reciprocal rank). That number was
flattering itself: the matching logic underneath required every word of a
query to appear literally in the matched document, which makes questions
phrased as document extracts look artificially easy and questions phrased
the way people actually ask fail. Independent review caught this. The fix
was not to keep the old number with a caveat — the matcher was corrected,
the benchmark questions were rewritten as honest paraphrases instead of
lifted extracts, and the baseline was re-recorded, in the same document that
had reported 85%, at **60.0% hit-at-1 (0.766 MRR)**.

A 25-point drop in a headline number is not a story most vendors tell
voluntarily. It's told here because it is the point: the system reports what
is true, not what looks good, and a lower honest number gives the next phase
of work a real target to beat — a saturated benchmark cannot.

### 3. The reboot

Partway through the second independent review cycle, the machine running the
work suffered a hard, uncontrolled reboot. Everything running in that
moment, including the reviewer's own process, was killed outright.

No governed work was lost. Code commits, the record of every completed
step's validation, and the earlier human approval decision all survived,
because none of it lived inside a chat session or an agent's working memory
— it lived in the run's own durable record on disk. Recovery meant resuming
that record from where it left off; the review picked back up and, one cycle
later, passed clean. (Recovery did surface one real gap in the underlying
platform's own resilience — a follow-on run created mid-recovery didn't
record which process was running it, which could strand it if that process
also died. That gap is now a tracked defect against the platform itself,
found by hitting it, not by inspection.)

The relevant fact for a buyer is narrower than "the system is resilient." A
mid-review hardware failure is exactly the event that would silently erase
an unaudited AI session and leave no trace it had happened correctly. Here,
it left a trace, because the record never depended on the session surviving.

### 4. The blind instrument

The first time this system touched real data — roughly 1,200 documents
across 15 source locations — its own counter for "files found but unreadable
by any parser" reported zero, everywhere. A zero that clean, on a corpus of
real business documents, should make anyone suspicious.

It made the system suspicious of itself. The measurement record doesn't
report the zero as a clean bill of health — it explains why the zero isn't
trustworthy: the counter can only flag a file after that file already
matched a source's search pattern, and none of the 15 configured search
patterns ever requested Word, Excel, or PowerPoint files — those files are
filtered out a step earlier and never reach the counter. The instrument was
structurally blind to the exact gap it existed to measure, and the system
said so instead of reporting the convenient zero.

A separate, independent count — done by directly counting files on disk,
outside the connector's own logic — found the real number: **39
office-format files** (32 Word, 5 Excel, 2 PowerPoint) sitting inside those
same 15 locations, invisible to the sync process today. The gap was already
known and planned for; what this moment demonstrates is that the system
doesn't let one measurement quietly stand in for a question it can't
actually answer.

## The review does not spare the operator

Across both review cycles, the independent reviewer also caught mistakes in
the human-facing narrative about the system — made by the project's own
operator, not by an AI worker's code. A written claim that a test count of
"109" reconciled from two smaller preserved counts was arithmetically wrong
(the two numbers add to 106, and the preserved validator result was 106). A
status claim that "ten of fifteen" locations held no office-format files was
off by one; the real figure was nine. A report describing "twelve queries"
run against the real corpus undercounted what the system's own audit trail
showed had executed. A project file committed to this public repository was
found to contain personal machine file paths that shouldn't have been
published.

None of these were software defects — they were narrative and
record-keeping errors, the kind any busy operator makes. They're listed here
because they show the review checks the operator's claims against the same
evidence standard as everything else. It does not go easy on the people
running it.

## What the human actually did

Across this project, the human made exactly two kinds of decisions, and did
zero hands-on code debugging:

1. **Approved the design contracts** before implementation began — a gate
   that blocked further progress until given.
2. **Set priorities** among the independent review's findings — which
   defects to repair immediately, which advisory findings to defer, and in
   what order.

Every finding's root cause, repair, and re-verification was carried out by
the AI system doing the work, using the reviewer's own reproduction evidence
as its starting point — not by a person reading a stack trace and editing a
file.

## What this does not prove

This is one project. Read the results above with these limits in mind — the
honest boundary of what has been demonstrated so far, not a hedge added for
appearances.

- **Single project, single domain.** Everything above happened on one
  system, in one technical domain (knowledge retrieval). It has not been
  demonstrated on a different kind of system — a transactional application,
  an integration-heavy service, or anything outside this shape of problem.
- **One operator, throughout.** Every decision above — approvals,
  priorities, monitoring, recovering from the reboot — was made by the same
  person who has run this process from the start. It has not been exercised
  by a team unfamiliar with it, or across a handoff between people.
- **Not yet run inside a client's environment.** The real-corpus run
  described here was against the project owner's own personal and business
  document corpus, on the project owner's own machine. No client
  infrastructure, data, identity system, or access controls have been
  involved yet.
- **Office-format support is a known, sized, open gap.** 39 real files (32
  Word, 5 Excel, 2 PowerPoint) are already identified as invisible to the
  system today. Closing the gap requires approving new parsing dependencies
  and changing which files each source location asks for — neither has
  happened yet.
- **The evaluation benchmark is still self-authored, not client-derived.**
  The 60.0% hit-at-1 baseline is measured against a question set paraphrased
  from the project's own documents, not a real client's recurring questions.
  Two of ten real-corpus test queries already surfaced ranking behavior
  worth folding into a future, more honest benchmark; that curation hasn't
  happened yet.
- **Clean reviews are not zero-defect reviews.** Both independent cycles
  found zero Critical or High findings, but each left a double-digit number
  of lower-severity advisory findings on record — real gaps (for example: a
  denied or empty retrieval currently leaves no durable audit row of its
  own) that are tracked and prioritized, not resolved by the verdict
  passing. A clean verdict means no defect judged severe enough to block; it
  does not mean no remaining work.

## What a client engagement would look like

The mechanism demonstrated here — validation gates, a human approval point
before code is written, an independent review with a verdict that can block
completion, and a durable evidence record that survives session and
infrastructure failure — is the operating model being offered, not a
one-time exercise built for this document.

In a client engagement, the same loop applies to the client's own delivery:
the client's stakeholder approves design contracts before implementation
starts; an independent reviewer — a separate role from the builder, on this
same verdict-gated standard — checks delivered work against the client's own
requirements and reproduces any finding it raises rather than asserting it;
every review cycle, finding, repair, and approval is written to a record the
client's own engineers can read and audit afterward, not summarized after
the fact. The client's role mirrors the one described above: approve
direction, set priorities among what gets fixed first, and review the
evidence — not debug code line by line.

The lee-kb record above is offered as the reference example of what that
evidence actually looks like when something goes wrong along the way,
because something did.
