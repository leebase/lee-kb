"""Contract tests for the governed answer() surface.

Coverage: construction of every contract, immutability, the three absence
kinds staying distinct, the citation rule on Claim, provenance closure between
claims, evidence, and receipts, conflict reporting without a winner, and the
SynthesisProvider seam.
"""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from lee_kb.answer_contracts import (
    CONFIDENCE_RANK,
    Absence,
    AbsenceKind,
    Answer,
    Claim,
    Confidence,
    Conflict,
    ConflictSide,
    EvidenceRef,
    OmissionReason,
    OmittedEvidence,
    ReceiptId,
    Side,
    SynthesisProvider,
    weakest_confidence,
)
from lee_kb.contracts import (
    DEFAULT_PROJECT,
    Authority,
    ChunkId,
    Citation,
    KnowledgeItemId,
    Principal,
    RetrievalReceipt,
    SourceLocator,
    compute_content_hash,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
PRINCIPAL = Principal(principal_id="lee", display_name="Lee")


def make_chunk_id(name: str, ordinal: int = 0) -> ChunkId:
    return ChunkId(
        item_id=KnowledgeItemId("local_files", name),
        chunk_ordinal=ordinal,
        content_hash=compute_content_hash(f"{name}:{ordinal}"),
    )


def make_locator(name: str) -> SourceLocator:
    return SourceLocator(connector_id="local_files", uri=f"file:///kb/{name}.md")


def make_citation(name: str, ordinal: int = 0) -> Citation:
    chunk_id = make_chunk_id(name, ordinal)
    return Citation(
        item_id=chunk_id.item_id,
        chunk_id=chunk_id,
        source_locator=make_locator(name),
        title=name,
    )


def make_receipt_id(name: str, ordinal: int = 0) -> ReceiptId:
    chunk_id = make_chunk_id(name, ordinal)
    return ReceiptId(
        knowledge_item_id=chunk_id.item_id,
        chunk_id=chunk_id,
        content_hash=chunk_id.content_hash,
        retrieval_timestamp=NOW,
    )


def make_evidence_ref(name: str, ordinal: int = 0) -> EvidenceRef:
    return EvidenceRef(
        chunk_id=make_chunk_id(name, ordinal), source_locator=make_locator(name)
    )


def make_answer(**overrides: object) -> Answer:
    """A minimal well-formed one-claim answer, with fields overridable."""
    citation = make_citation("policy")
    claim = Claim(
        text="Sync is user-driven.",
        citations=(citation,),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )
    fields: dict[str, object] = {
        "question": "How does synchronization run?",
        "principal": PRINCIPAL,
        "project": DEFAULT_PROJECT,
        "claims": (claim,),
        "confidence": Confidence.DIRECTLY_EVIDENCED,
        "receipt_ids": (make_receipt_id("policy"),),
        "evidence_used": (make_evidence_ref("policy"),),
        "evidence_omitted": (),
    }
    fields.update(overrides)
    return Answer(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------


def test_confidence_has_exactly_the_four_locked_values():
    assert [member.name for member in Confidence] == [
        "DIRECTLY_EVIDENCED",
        "SYNTHESIZED",
        "INFERRED",
        "UNKNOWN",
    ]


def test_confidence_rank_orders_strongest_to_weakest():
    assert CONFIDENCE_RANK[Confidence.DIRECTLY_EVIDENCED] == 0
    assert (
        CONFIDENCE_RANK[Confidence.DIRECTLY_EVIDENCED]
        < CONFIDENCE_RANK[Confidence.SYNTHESIZED]
        < CONFIDENCE_RANK[Confidence.INFERRED]
        < CONFIDENCE_RANK[Confidence.UNKNOWN]
    )


def test_weakest_confidence_picks_the_weakest_and_rejects_the_empty_case():
    assert (
        weakest_confidence((Confidence.DIRECTLY_EVIDENCED, Confidence.INFERRED))
        is Confidence.INFERRED
    )
    with pytest.raises(ValueError):
        weakest_confidence(())


# --------------------------------------------------------------------------
# Claim
# --------------------------------------------------------------------------


def test_claim_construction_carries_text_citations_and_confidence():
    citation = make_citation("policy")
    claim = Claim(
        text="Sync is user-driven.",
        citations=(citation,),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )
    assert claim.text == "Sync is user-driven."
    assert claim.citations == (citation,)
    assert claim.confidence is Confidence.DIRECTLY_EVIDENCED
    assert claim.cited_chunk_ids == (citation.chunk_id,)
    assert claim.is_grounded


@pytest.mark.parametrize(
    "confidence",
    [Confidence.DIRECTLY_EVIDENCED, Confidence.SYNTHESIZED, Confidence.INFERRED],
)
def test_claim_without_citations_is_rejected_unless_unknown(confidence):
    with pytest.raises(ValueError, match="UNKNOWN"):
        Claim(text="Probably true.", citations=(), confidence=confidence)


def test_claim_without_citations_is_allowed_only_when_unknown():
    claim = Claim(text="Not determinable.", citations=(), confidence=Confidence.UNKNOWN)
    assert claim.citations == ()
    assert not claim.is_grounded


def test_claim_rejects_a_repeated_citation_of_the_same_chunk():
    citation = make_citation("policy")
    with pytest.raises(ValueError, match="same chunk"):
        Claim(
            text="Sync is user-driven.",
            citations=(citation, citation),
            confidence=Confidence.DIRECTLY_EVIDENCED,
        )


def test_claim_rejects_a_list_of_citations():
    with pytest.raises(TypeError):
        Claim(
            text="Sync is user-driven.",
            citations=[make_citation("policy")],
            confidence=Confidence.DIRECTLY_EVIDENCED,
        )


def test_claim_is_immutable_and_hashable():
    claim = Claim(
        text="Sync is user-driven.",
        citations=(make_citation("policy"),),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        claim.text = "rewritten"
    with pytest.raises(dataclasses.FrozenInstanceError):
        claim.confidence = Confidence.UNKNOWN
    assert hash(claim) == hash(
        Claim(
            text="Sync is user-driven.",
            citations=(make_citation("policy"),),
            confidence=Confidence.DIRECTLY_EVIDENCED,
        )
    )


# --------------------------------------------------------------------------
# Absence
# --------------------------------------------------------------------------


def test_the_three_absence_kinds_are_distinct():
    assert [member.name for member in AbsenceKind] == [
        "NOT_FOUND",
        "INACCESSIBLE",
        "UNKNOWN",
    ]
    values = {member.value for member in AbsenceKind}
    assert len(values) == 3
    assert (
        AbsenceKind.NOT_FOUND is not AbsenceKind.INACCESSIBLE
        and AbsenceKind.INACCESSIBLE is not AbsenceKind.UNKNOWN
        and AbsenceKind.NOT_FOUND is not AbsenceKind.UNKNOWN
    )


def test_absence_kinds_never_collapse_into_one_state():
    question = "What is the escalation policy?"
    not_found = Absence(
        kind=AbsenceKind.NOT_FOUND,
        question=question,
        searched_projects=(DEFAULT_PROJECT,),
    )
    inaccessible = Absence(
        kind=AbsenceKind.INACCESSIBLE, question=question, withheld_count=2
    )
    unknown = Absence(kind=AbsenceKind.UNKNOWN, question=question)

    assert not_found != inaccessible != unknown
    assert not_found != unknown
    assert len({not_found, inaccessible, unknown}) == 3

    flags = [
        (a.is_not_found, a.is_inaccessible, a.is_unknown)
        for a in (not_found, inaccessible, unknown)
    ]
    assert flags == [(True, False, False), (False, True, False), (False, False, True)]


def test_not_found_cannot_report_withheld_evidence():
    with pytest.raises(ValueError, match="INACCESSIBLE"):
        Absence(
            kind=AbsenceKind.NOT_FOUND,
            question="Where is the runbook?",
            searched_projects=(DEFAULT_PROJECT,),
            withheld_count=1,
        )


def test_inaccessible_must_report_a_withheld_count():
    with pytest.raises(ValueError, match="withheld"):
        Absence(kind=AbsenceKind.INACCESSIBLE, question="Where is the runbook?")


def test_not_found_must_record_the_projects_it_searched():
    with pytest.raises(ValueError, match="searched"):
        Absence(kind=AbsenceKind.NOT_FOUND, question="Where is the runbook?")


def test_unknown_absence_needs_neither_scope_nor_count():
    absence = Absence(kind=AbsenceKind.UNKNOWN, question="Where is the runbook?")
    assert absence.withheld_count == 0
    assert absence.searched_projects == ()


def test_absence_is_immutable():
    absence = Absence(kind=AbsenceKind.UNKNOWN, question="Where is the runbook?")
    with pytest.raises(dataclasses.FrozenInstanceError):
        absence.kind = AbsenceKind.NOT_FOUND


# --------------------------------------------------------------------------
# ReceiptId and evidence references
# --------------------------------------------------------------------------


def test_receipt_id_projects_a_persisted_receipt():
    chunk_id = make_chunk_id("policy")
    receipt = RetrievalReceipt(
        knowledge_item_id=chunk_id.item_id,
        chunk_id=chunk_id,
        content_hash=chunk_id.content_hash,
        source_locator=make_locator("policy"),
        retrieval_timestamp=NOW,
        principal=PRINCIPAL,
        project=DEFAULT_PROJECT,
        query="How does synchronization run?",
    )
    receipt_id = ReceiptId.from_receipt(receipt)
    assert receipt_id == make_receipt_id("policy")
    assert receipt_id.retrieval_timestamp == NOW


def test_receipt_id_rejects_a_mismatched_hash():
    chunk_id = make_chunk_id("policy")
    with pytest.raises(ValueError, match="content_hash"):
        ReceiptId(
            knowledge_item_id=chunk_id.item_id,
            chunk_id=chunk_id,
            content_hash=compute_content_hash("other"),
            retrieval_timestamp=NOW,
        )


def test_receipt_id_rejects_a_naive_timestamp():
    chunk_id = make_chunk_id("policy")
    with pytest.raises(ValueError, match="timezone-aware"):
        ReceiptId(
            knowledge_item_id=chunk_id.item_id,
            chunk_id=chunk_id,
            content_hash=chunk_id.content_hash,
            retrieval_timestamp=datetime(2026, 8, 4, 12, 0),
        )


def test_receipt_id_is_immutable():
    receipt_id = make_receipt_id("policy")
    with pytest.raises(dataclasses.FrozenInstanceError):
        receipt_id.content_hash = compute_content_hash("other")


def test_evidence_ref_reads_identity_through_the_chunk_id():
    reference = make_evidence_ref("policy")
    assert reference.item_id == KnowledgeItemId("local_files", "policy")
    assert reference.content_hash == reference.chunk_id.content_hash


def test_omitted_evidence_records_a_reason():
    omitted = OmittedEvidence(
        evidence=make_evidence_ref("older"),
        reason=OmissionReason.SUPERSEDED,
        detail="Replaced by the 2026 revision.",
    )
    assert omitted.reason is OmissionReason.SUPERSEDED
    assert omitted.chunk_id == make_chunk_id("older")
    with pytest.raises(dataclasses.FrozenInstanceError):
        omitted.reason = OmissionReason.BUDGET


# --------------------------------------------------------------------------
# Conflict
# --------------------------------------------------------------------------


def make_conflict() -> Conflict:
    left = ConflictSide(
        claim=Claim(
            text="Retention is 90 days.",
            citations=(make_citation("policy_2024"),),
            confidence=Confidence.DIRECTLY_EVIDENCED,
        ),
        source_timestamp=NOW - timedelta(days=400),
        authority=Authority.CANONICAL,
    )
    right = ConflictSide(
        claim=Claim(
            text="Retention is 30 days.",
            citations=(make_citation("note_2026"),),
            confidence=Confidence.DIRECTLY_EVIDENCED,
        ),
        source_timestamp=NOW,
        authority=Authority.DERIVED,
    )
    return Conflict(left=left, right=right, detail="Retention window disagreement.")


def test_conflict_carries_both_claims_and_their_sources():
    conflict = make_conflict()
    assert conflict.claims == (conflict.left.claim, conflict.right.claim)
    assert conflict.left.sources == (make_locator("policy_2024"),)
    assert conflict.right.sources == (make_locator("note_2026"),)


def test_conflict_reports_recency_and_authority_without_selecting_a_winner():
    conflict = make_conflict()
    assert conflict.newer is Side.RIGHT
    assert conflict.more_authoritative is Side.LEFT
    assert conflict.signals_agree is False
    assert not hasattr(conflict, "winner")
    assert not any(
        field.name in {"winner", "resolution", "resolved"}
        for field in dataclasses.fields(conflict)
    )


def test_conflict_reports_neither_when_a_signal_ties():
    left = ConflictSide(
        claim=Claim(
            text="Retention is 90 days.",
            citations=(make_citation("a"),),
            confidence=Confidence.DIRECTLY_EVIDENCED,
        ),
        source_timestamp=NOW,
        authority=Authority.CANONICAL,
    )
    right = ConflictSide(
        claim=Claim(
            text="Retention is 30 days.",
            citations=(make_citation("b"),),
            confidence=Confidence.DIRECTLY_EVIDENCED,
        ),
        source_timestamp=NOW,
        authority=Authority.CANONICAL,
    )
    conflict = Conflict(left=left, right=right)
    assert conflict.newer is Side.NEITHER
    assert conflict.more_authoritative is Side.NEITHER
    assert conflict.signals_agree is False


def test_conflict_needs_two_different_claims():
    side = ConflictSide(
        claim=Claim(
            text="Retention is 90 days.",
            citations=(make_citation("a"),),
            confidence=Confidence.DIRECTLY_EVIDENCED,
        ),
        source_timestamp=NOW,
    )
    with pytest.raises(ValueError, match="two different claims"):
        Conflict(left=side, right=side)


def test_conflict_is_immutable():
    conflict = make_conflict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        conflict.detail = "rewritten"


# --------------------------------------------------------------------------
# Answer
# --------------------------------------------------------------------------


def test_answer_construction_carries_the_governed_fields():
    answer = make_answer()
    assert answer.question == "How does synchronization run?"
    assert answer.principal == PRINCIPAL
    assert answer.project == DEFAULT_PROJECT
    assert len(answer.claims) == 1
    assert answer.confidence is Confidence.DIRECTLY_EVIDENCED
    assert answer.receipt_ids == (make_receipt_id("policy"),)
    assert answer.evidence_used == (make_evidence_ref("policy"),)
    assert answer.evidence_omitted == ()
    assert answer.cited_chunk_ids == (make_chunk_id("policy"),)
    assert not answer.is_absent


def test_answer_is_immutable():
    answer = make_answer()
    with pytest.raises(dataclasses.FrozenInstanceError):
        answer.confidence = Confidence.UNKNOWN
    with pytest.raises(dataclasses.FrozenInstanceError):
        answer.claims = ()


def test_answer_preserves_claim_order():
    first = Claim(
        text="First.",
        citations=(make_citation("a"),),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )
    second = Claim(
        text="Second.",
        citations=(make_citation("b"),),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )
    answer = make_answer(
        claims=(first, second),
        evidence_used=(make_evidence_ref("a"), make_evidence_ref("b")),
        receipt_ids=(make_receipt_id("a"), make_receipt_id("b")),
    )
    assert [claim.text for claim in answer.claims] == ["First.", "Second."]


def test_answer_records_omitted_evidence_alongside_used_evidence():
    answer = make_answer(
        evidence_omitted=(
            OmittedEvidence(
                evidence=make_evidence_ref("older"), reason=OmissionReason.REDUNDANT
            ),
        ),
        receipt_ids=(make_receipt_id("policy"), make_receipt_id("older")),
    )
    assert len(answer.evidence_omitted) == 1
    assert answer.evidence_omitted[0].reason is OmissionReason.REDUNDANT


def test_answer_rejects_a_citation_that_is_not_in_evidence_used():
    claim = Claim(
        text="Unaccounted.",
        citations=(make_citation("ghost"),),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )
    with pytest.raises(ValueError, match="evidence_used"):
        make_answer(claims=(claim,))


def test_answer_rejects_a_chunk_cited_by_more_than_one_claim():
    citation = make_citation("policy")
    first = Claim(
        text="Sync is user-driven.",
        citations=(citation,),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )
    second = Claim(
        text="Synchronization starts on request.",
        citations=(citation,),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )

    with pytest.raises(ValueError, match="at most one claim"):
        make_answer(claims=(first, second))


def test_answer_rejects_evidence_that_is_both_used_and_omitted():
    with pytest.raises(ValueError, match="both used and omitted"):
        make_answer(
            evidence_omitted=(
                OmittedEvidence(
                    evidence=make_evidence_ref("policy"),
                    reason=OmissionReason.REDUNDANT,
                ),
            )
        )


def test_answer_requires_a_receipt_for_every_considered_chunk():
    with pytest.raises(ValueError, match="receipt_ids must cover"):
        make_answer(
            evidence_omitted=(
                OmittedEvidence(
                    evidence=make_evidence_ref("older"),
                    reason=OmissionReason.REDUNDANT,
                ),
            )
        )


def test_answer_rejects_a_receipt_for_evidence_it_never_lists():
    with pytest.raises(ValueError, match="receipt_ids must cover"):
        make_answer(receipt_ids=(make_receipt_id("policy"), make_receipt_id("ghost")))


def test_answer_confidence_cannot_exceed_the_weakest_claim():
    claims = (
        Claim(
            text="Grounded.",
            citations=(make_citation("policy"),),
            confidence=Confidence.DIRECTLY_EVIDENCED,
        ),
        Claim(
            text="A reading of the above.",
            citations=(make_citation("policy", 1),),
            confidence=Confidence.INFERRED,
        ),
    )
    used = (make_evidence_ref("policy"), make_evidence_ref("policy", 1))
    receipts = (make_receipt_id("policy"), make_receipt_id("policy", 1))
    with pytest.raises(ValueError, match="weakest claim"):
        make_answer(
            claims=claims,
            confidence=Confidence.DIRECTLY_EVIDENCED,
            evidence_used=used,
            receipt_ids=receipts,
        )
    answer = make_answer(
        claims=claims,
        confidence=Confidence.INFERRED,
        evidence_used=used,
        receipt_ids=receipts,
    )
    assert answer.confidence is Confidence.INFERRED


def test_answer_without_claims_must_carry_an_absence():
    with pytest.raises(ValueError, match="must carry an Absence"):
        make_answer(
            claims=(),
            confidence=Confidence.UNKNOWN,
            evidence_used=(),
            receipt_ids=(),
        )


def test_answer_with_claims_must_not_carry_an_absence():
    with pytest.raises(ValueError, match="must not carry an absence"):
        make_answer(
            absence=Absence(
                kind=AbsenceKind.UNKNOWN, question="How does synchronization run?"
            )
        )


def test_absent_answer_is_unknown_and_names_its_absence_kind():
    question = "How does synchronization run?"
    answer = make_answer(
        claims=(),
        confidence=Confidence.UNKNOWN,
        evidence_used=(),
        receipt_ids=(),
        absence=Absence(
            kind=AbsenceKind.INACCESSIBLE, question=question, withheld_count=3
        ),
    )
    assert answer.is_absent
    assert answer.absence.kind is AbsenceKind.INACCESSIBLE
    assert answer.absence.withheld_count == 3
    assert answer.cited_chunk_ids == ()


def test_absent_answer_cannot_claim_confidence():
    with pytest.raises(ValueError, match="UNKNOWN confidence"):
        make_answer(
            claims=(),
            confidence=Confidence.SYNTHESIZED,
            evidence_used=(),
            receipt_ids=(),
            absence=Absence(
                kind=AbsenceKind.UNKNOWN, question="How does synchronization run?"
            ),
        )


def test_not_found_answer_cannot_have_considered_evidence():
    with pytest.raises(ValueError, match="NOT_FOUND"):
        make_answer(
            claims=(),
            confidence=Confidence.UNKNOWN,
            absence=Absence(
                kind=AbsenceKind.NOT_FOUND,
                question="How does synchronization run?",
                searched_projects=(DEFAULT_PROJECT,),
            ),
        )


def test_answer_conflicts_must_reference_presented_claims():
    conflict = make_conflict()
    with pytest.raises(ValueError, match="claims this answer presents"):
        make_answer(conflicts=(conflict,))


def test_answer_accepts_a_conflict_between_its_own_claims():
    conflict = make_conflict()
    answer = make_answer(
        claims=conflict.claims,
        evidence_used=(
            make_evidence_ref("policy_2024"),
            make_evidence_ref("note_2026"),
        ),
        receipt_ids=(make_receipt_id("policy_2024"), make_receipt_id("note_2026")),
        conflicts=(conflict,),
    )
    assert answer.conflicts == (conflict,)
    assert answer.conflicts[0].newer is Side.RIGHT
    assert answer.conflicts[0].more_authoritative is Side.LEFT


def test_answer_prose_must_name_its_synthesis_provider():
    with pytest.raises(ValueError, match="synthesis provider"):
        make_answer(prose="Sync is user-driven.")
    answer = make_answer(
        prose="Sync is user-driven.", synthesis_provider_id="deterministic:1"
    )
    assert answer.synthesis_provider_id == "deterministic:1"


def test_answer_rejects_a_naive_answered_at():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_answer(answered_at=datetime(2026, 8, 4, 12, 0))


def test_answer_rejects_a_list_of_claims():
    with pytest.raises(TypeError):
        make_answer(
            claims=[
                Claim(
                    text="Sync is user-driven.",
                    citations=(make_citation("policy"),),
                    confidence=Confidence.DIRECTLY_EVIDENCED,
                )
            ]
        )


def test_answer_requires_a_principal_and_a_project():
    with pytest.raises(TypeError):
        make_answer(principal="lee")
    with pytest.raises(ValueError):
        make_answer(project="  ")


# --------------------------------------------------------------------------
# SynthesisProvider
# --------------------------------------------------------------------------


class StubSynthesisProvider:
    """A stdlib provider standing in for a future LLM-backed one."""

    provider_id = "stub:1"

    def narrate(self, claims: tuple[Claim, ...]) -> str:
        return " ".join(claim.text for claim in claims)


def test_synthesis_provider_protocol_is_satisfied_by_a_narrate_only_class():
    provider = StubSynthesisProvider()
    assert isinstance(provider, SynthesisProvider)


def test_a_class_without_narrate_does_not_satisfy_the_protocol():
    class NotAProvider:
        def summarize(self, claims: tuple[Claim, ...]) -> str:
            return ""

    assert not isinstance(NotAProvider(), SynthesisProvider)


def test_narrate_receives_assembled_claims_in_order_and_returns_prose():
    first = Claim(
        text="First.",
        citations=(make_citation("a"),),
        confidence=Confidence.DIRECTLY_EVIDENCED,
    )
    second = Claim(
        text="Second.",
        citations=(make_citation("b"),),
        confidence=Confidence.SYNTHESIZED,
    )
    answer = make_answer(
        claims=(first, second),
        confidence=Confidence.SYNTHESIZED,
        evidence_used=(make_evidence_ref("a"), make_evidence_ref("b")),
        receipt_ids=(make_receipt_id("a"), make_receipt_id("b")),
    )
    prose = StubSynthesisProvider().narrate(answer.claims)
    assert prose == "First. Second."
