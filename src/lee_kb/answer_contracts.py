"""Contracts for the governed ``answer()`` surface.

``retrieve()`` returns an :class:`~lee_kb.contracts.EvidenceBundle` with no LLM
involved. ``answer()`` layers query planning and synthesis on top of it and
returns an :class:`Answer`: an ordered sequence of :class:`Claim` objects, each
carrying its own citations and its own confidence, plus the receipt identifiers
that prove which evidence actually left the platform.

Design rules, unchanged from ``contracts.py``:

- Standard library only. No runtime dependencies. An LLM synthesis provider
  arrives behind :class:`SynthesisProvider`, never as an import here.
- Every value object is frozen and hashable; sequences are tuples.
- Every timestamp is timezone-aware.
- Data, not policy. Validation covers structural invariants only. Ranking,
  planning, permission evaluation, and provider selection live in the layers
  that own them.

Two invariants are specific to this surface and are the reason the module
exists:

- **Provenance closure.** Every citation on every claim must reference evidence
  listed in :attr:`Answer.evidence_used`, and the union of ``evidence_used``
  and :attr:`Answer.evidence_omitted` must be exactly the set of chunks
  covered by :attr:`Answer.receipt_ids`. Nothing is presented without a
  receipt, and nothing that was released goes unaccounted for.
- **Absence never collapses.** :class:`AbsenceKind` keeps "no evidence exists",
  "evidence exists but this principal may not see it", and "the question could
  not be resolved" as three distinct states. Folding them into one would either
  leak the existence of restricted material or silently report a governance
  denial as an empty corpus.

See ``docs/answer-architecture.md`` for the normative design.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from .contracts import (
    AUTHORITY_RANK,
    Authority,
    ChunkId,
    Citation,
    FreshnessReport,
    KnowledgeItemId,
    Principal,
    RetrievalReceipt,
    SourceLocator,
    _require_aware,
    _require_hash,
    _require_optional_text,
    _require_project,
    _require_text,
    _require_tuple,
)

__all__ = [
    "CONFIDENCE_RANK",
    "weakest_confidence",
    "Confidence",
    "AbsenceKind",
    "OmissionReason",
    "Side",
    "ReceiptId",
    "EvidenceRef",
    "OmittedEvidence",
    "Claim",
    "ConflictSide",
    "Conflict",
    "Absence",
    "Answer",
    "SynthesisProvider",
]


class Confidence(str, Enum):
    """How a claim relates to the evidence that produced it.

    The four values are locked. They describe *epistemic basis*, not a
    probability: nothing here is a score, and none of them may be averaged.

    - ``DIRECTLY_EVIDENCED`` — the evidence states the claim.
    - ``SYNTHESIZED`` — the claim combines or restates evidence that says it
      across sources or sections.
    - ``INFERRED`` — the claim goes beyond what the evidence states.
    - ``UNKNOWN`` — the claim could not be grounded at all. This is the only
      value that permits a claim with no citations.
    """

    DIRECTLY_EVIDENCED = "directly_evidenced"
    SYNTHESIZED = "synthesized"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


#: Strength order, strongest first. Used to check that an answer never claims
#: more confidence than the weakest claim it rests on.
CONFIDENCE_RANK = {
    Confidence.DIRECTLY_EVIDENCED: 0,
    Confidence.SYNTHESIZED: 1,
    Confidence.INFERRED: 2,
    Confidence.UNKNOWN: 3,
}


def weakest_confidence(values: tuple[Confidence, ...]) -> Confidence:
    """Return the weakest confidence in ``values``.

    Raises :class:`ValueError` when ``values`` is empty: there is no neutral
    element, because an answer with nothing behind it is an absence, not a
    confident answer.
    """
    if not values:
        raise ValueError("weakest_confidence requires at least one value")
    return max(values, key=lambda value: CONFIDENCE_RANK[value])


class AbsenceKind(str, Enum):
    """Why an answer has no claims. These three never collapse into one state.

    - ``NOT_FOUND`` — the corpus was searched and holds no evidence.
    - ``INACCESSIBLE`` — evidence exists but this principal may not see it.
      Reported as a count only; the withheld content, its titles, and its
      locators never appear in the answer.
    - ``UNKNOWN`` — the question could not be resolved: it was not planned into
      a retrievable query, a provider failed, or the result was uninterpretable.

    Reporting ``INACCESSIBLE`` as ``NOT_FOUND`` tells the principal a lie about
    the corpus. Reporting ``UNKNOWN`` as ``NOT_FOUND`` claims a search
    happened that did not.
    """

    NOT_FOUND = "not_found"
    INACCESSIBLE = "inaccessible"
    UNKNOWN = "unknown"


class OmissionReason(str, Enum):
    """Why retrieved, permitted evidence did not end up supporting a claim."""

    NOT_RELEVANT = "not_relevant"
    REDUNDANT = "redundant"
    SUPERSEDED = "superseded"
    STALE = "stale"
    LOWER_AUTHORITY = "lower_authority"
    BUDGET = "budget"
    SYNTHESIS_FAILURE = "synthesis_failure"


class Side(str, Enum):
    """Which side of a conflict a signal points at.

    ``NEITHER`` is a tie or an unorderable comparison. There is deliberately no
    ``WINNER``.
    """

    LEFT = "left"
    RIGHT = "right"
    NEITHER = "neither"


@dataclass(frozen=True, slots=True)
class ReceiptId:
    """The identifying fields of one persisted :class:`RetrievalReceipt`.

    An answer carries receipt identifiers rather than whole receipts: the
    receipt itself is already durable in the repository, and copying the
    principal and query onto every row of an answer would duplicate governance
    state that must have exactly one home. These four fields are the ones that
    stay resolvable after the projection has been re-chunked.
    """

    knowledge_item_id: KnowledgeItemId
    chunk_id: ChunkId
    content_hash: str
    retrieval_timestamp: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge_item_id, KnowledgeItemId):
            raise TypeError("knowledge_item_id must be a KnowledgeItemId")
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.retrieval_timestamp, "retrieval_timestamp")
        if self.chunk_id.item_id != self.knowledge_item_id:
            raise ValueError("chunk_id.item_id must match knowledge_item_id")
        if self.chunk_id.content_hash != self.content_hash:
            raise ValueError("content_hash must match chunk_id.content_hash")

    @classmethod
    def from_receipt(cls, receipt: RetrievalReceipt) -> ReceiptId:
        """Project a persisted receipt down to its identifying fields."""
        if not isinstance(receipt, RetrievalReceipt):
            raise TypeError("receipt must be a RetrievalReceipt")
        return cls(
            knowledge_item_id=receipt.knowledge_item_id,
            chunk_id=receipt.chunk_id,
            content_hash=receipt.content_hash,
            retrieval_timestamp=receipt.retrieval_timestamp,
        )


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """A reference to one piece of evidence the answer considered."""

    chunk_id: ChunkId
    source_locator: SourceLocator

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, ChunkId):
            raise TypeError("chunk_id must be a ChunkId")
        if not isinstance(self.source_locator, SourceLocator):
            raise TypeError("source_locator must be a SourceLocator")

    @property
    def item_id(self) -> KnowledgeItemId:
        return self.chunk_id.item_id

    @property
    def content_hash(self) -> str:
        return self.chunk_id.content_hash


@dataclass(frozen=True, slots=True)
class OmittedEvidence:
    """Evidence that was retrieved and permitted, but did not reach a claim.

    Omission is recorded, never silent. A reader who sees three citations and
    a claim they doubt can ask what the other seven retrieved chunks said and
    why they were dropped.
    """

    evidence: EvidenceRef
    reason: OmissionReason
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, EvidenceRef):
            raise TypeError("evidence must be an EvidenceRef")
        if not isinstance(self.reason, OmissionReason):
            raise TypeError("reason must be an OmissionReason")
        _require_optional_text(self.detail, "detail")

    @property
    def chunk_id(self) -> ChunkId:
        return self.evidence.chunk_id


@dataclass(frozen=True, slots=True)
class Claim:
    """One assertion in an answer, with the citations that support it.

    A claim cannot be constructed without at least one citation unless its
    confidence is :attr:`Confidence.UNKNOWN`. That is the structural form of
    "no uncited assertion reaches a reader": an ungrounded statement is not
    forbidden, but it must be labelled ``UNKNOWN`` rather than presented at
    the same weight as evidenced text.
    """

    text: str
    citations: tuple[Citation, ...]
    confidence: Confidence

    def __post_init__(self) -> None:
        _require_text(self.text, "text")
        _require_tuple(self.citations, "citations")
        if not isinstance(self.confidence, Confidence):
            raise TypeError("confidence must be a Confidence")
        for citation in self.citations:
            if not isinstance(citation, Citation):
                raise TypeError("citations must contain Citation values")
        chunk_ids = [citation.chunk_id for citation in self.citations]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("a claim must not cite the same chunk twice")
        if not self.citations and self.confidence is not Confidence.UNKNOWN:
            raise ValueError(
                "a claim without citations must declare Confidence.UNKNOWN; "
                f"got {self.confidence.value}"
            )

    @property
    def cited_chunk_ids(self) -> tuple[ChunkId, ...]:
        return tuple(citation.chunk_id for citation in self.citations)

    @property
    def is_grounded(self) -> bool:
        """Whether this claim rests on at least one citation."""
        return bool(self.citations)


@dataclass(frozen=True, slots=True)
class ConflictSide:
    """One side of a disagreement: a claim plus the ordering signals for it.

    The signals are carried explicitly rather than read back through the
    citations, because the side that matters for recency is the *source*
    timestamp of the underlying item, and a claim may cite several.
    """

    claim: Claim
    source_timestamp: datetime
    authority: Authority = Authority.DERIVED

    def __post_init__(self) -> None:
        if not isinstance(self.claim, Claim):
            raise TypeError("claim must be a Claim")
        _require_aware(self.source_timestamp, "source_timestamp")
        if not isinstance(self.authority, Authority):
            raise TypeError("authority must be an Authority")

    @property
    def sources(self) -> tuple[SourceLocator, ...]:
        """The source locators behind this side, in citation order."""
        return tuple(citation.source_locator for citation in self.claim.citations)


@dataclass(frozen=True, slots=True)
class Conflict:
    """Two claims that disagree, presented without a winner.

    The retrieval engine does not detect contradictions and this contract does
    not resolve them. :attr:`newer` and :attr:`more_authoritative` report the
    two ordering signals that exist; both may be :attr:`Side.NEITHER`, and they
    may point at opposite sides — a newer derived note contradicting an older
    canonical policy is a real and common shape. There is deliberately no
    ``winner`` field: choosing one would move a governance judgement out of the
    reader's hands and into a heuristic that cannot see intent.
    """

    left: ConflictSide
    right: ConflictSide
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.left, ConflictSide):
            raise TypeError("left must be a ConflictSide")
        if not isinstance(self.right, ConflictSide):
            raise TypeError("right must be a ConflictSide")
        _require_optional_text(self.detail, "detail")
        if self.left.claim == self.right.claim:
            raise ValueError("a conflict needs two different claims")

    @property
    def claims(self) -> tuple[Claim, ...]:
        """The competing claims, left then right."""
        return (self.left.claim, self.right.claim)

    @property
    def newer(self) -> Side:
        """Which side has the newer source timestamp, or NEITHER on a tie."""
        if self.left.source_timestamp > self.right.source_timestamp:
            return Side.LEFT
        if self.right.source_timestamp > self.left.source_timestamp:
            return Side.RIGHT
        return Side.NEITHER

    @property
    def more_authoritative(self) -> Side:
        """Which side carries the higher declared authority, or NEITHER."""
        left_rank = AUTHORITY_RANK[self.left.authority]
        right_rank = AUTHORITY_RANK[self.right.authority]
        if left_rank < right_rank:
            return Side.LEFT
        if right_rank < left_rank:
            return Side.RIGHT
        return Side.NEITHER

    @property
    def signals_agree(self) -> bool:
        """Whether recency and authority point at the same side.

        ``False`` is the case a reader most needs to see, and the reason no
        automatic winner is picked.
        """
        return self.newer is self.more_authoritative and self.newer is not Side.NEITHER


@dataclass(frozen=True, slots=True)
class Absence:
    """Why an answer carries no claims.

    ``withheld_count`` is the only thing an ``INACCESSIBLE`` absence may say
    about the material it is hiding. It exists so a principal learns that a
    governance boundary — not an empty corpus — produced the silence, without
    learning what sits behind it.
    """

    kind: AbsenceKind
    question: str
    detail: str | None = None
    searched_projects: tuple[str, ...] = ()
    withheld_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AbsenceKind):
            raise TypeError("kind must be an AbsenceKind")
        _require_text(self.question, "question")
        _require_optional_text(self.detail, "detail")
        _require_tuple(self.searched_projects, "searched_projects")
        for project in self.searched_projects:
            _require_project(project)
        if not isinstance(self.withheld_count, int) or isinstance(
            self.withheld_count, bool
        ):
            raise TypeError("withheld_count must be an int")
        if self.withheld_count < 0:
            raise ValueError("withheld_count must be zero or greater")
        if self.kind is AbsenceKind.NOT_FOUND and self.withheld_count:
            raise ValueError(
                "NOT_FOUND means no evidence exists; evidence was withheld, "
                "so this is INACCESSIBLE"
            )
        if self.kind is AbsenceKind.INACCESSIBLE and not self.withheld_count:
            raise ValueError("INACCESSIBLE must report how many items were withheld")
        if self.kind is AbsenceKind.NOT_FOUND and not self.searched_projects:
            raise ValueError(
                "NOT_FOUND must record which projects were searched to find nothing"
            )

    @property
    def is_not_found(self) -> bool:
        return self.kind is AbsenceKind.NOT_FOUND

    @property
    def is_inaccessible(self) -> bool:
        return self.kind is AbsenceKind.INACCESSIBLE

    @property
    def is_unknown(self) -> bool:
        return self.kind is AbsenceKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class Answer:
    """The result of ``answer()``: ordered claims over accounted-for evidence.

    :attr:`claims` is presentation order, not confidence order — the caller
    reads them top to bottom as prose would.

    Either the answer has claims and no :attr:`absence`, or it has no claims,
    an absence, and :attr:`Confidence.UNKNOWN` overall. There is no third
    shape: an answer that says nothing must say why. ``withheld_count`` and
    ``truncated`` carry the governed bundle's aggregate disclosure-safe limits
    even when ordinary claims were available.
    """

    question: str
    principal: Principal
    project: str
    freshness: FreshnessReport | None
    claims: tuple[Claim, ...]
    confidence: Confidence
    receipt_ids: tuple[ReceiptId, ...]
    evidence_used: tuple[EvidenceRef, ...]
    evidence_omitted: tuple[OmittedEvidence, ...]
    conflicts: tuple[Conflict, ...] = ()
    absence: Absence | None = None
    answered_at: datetime | None = None
    prose: str | None = None
    synthesis_provider_id: str | None = None
    withheld_count: int = 0
    truncated: bool = False

    def __post_init__(self) -> None:
        _require_text(self.question, "question")
        if not isinstance(self.principal, Principal):
            raise TypeError("principal must be a Principal")
        _require_project(self.project)
        if self.freshness is not None and not isinstance(
            self.freshness, FreshnessReport
        ):
            raise TypeError("freshness must be a FreshnessReport or None")
        _require_tuple(self.claims, "claims")
        _require_tuple(self.receipt_ids, "receipt_ids")
        _require_tuple(self.evidence_used, "evidence_used")
        _require_tuple(self.evidence_omitted, "evidence_omitted")
        _require_tuple(self.conflicts, "conflicts")
        if not isinstance(self.confidence, Confidence):
            raise TypeError("confidence must be a Confidence")
        for claim in self.claims:
            if not isinstance(claim, Claim):
                raise TypeError("claims must contain Claim values")
        for reference in self.evidence_used:
            if not isinstance(reference, EvidenceRef):
                raise TypeError("evidence_used must contain EvidenceRef values")
        for omitted in self.evidence_omitted:
            if not isinstance(omitted, OmittedEvidence):
                raise TypeError("evidence_omitted must contain OmittedEvidence values")
        for receipt_id in self.receipt_ids:
            if not isinstance(receipt_id, ReceiptId):
                raise TypeError("receipt_ids must contain ReceiptId values")
        for conflict in self.conflicts:
            if not isinstance(conflict, Conflict):
                raise TypeError("conflicts must contain Conflict values")
        if self.absence is not None and not isinstance(self.absence, Absence):
            raise TypeError("absence must be an Absence")
        if self.answered_at is not None:
            _require_aware(self.answered_at, "answered_at")
        _require_optional_text(self.prose, "prose")
        _require_optional_text(self.synthesis_provider_id, "synthesis_provider_id")
        if not isinstance(self.withheld_count, int) or isinstance(
            self.withheld_count, bool
        ):
            raise TypeError("withheld_count must be an int")
        if self.withheld_count < 0:
            raise ValueError("withheld_count must be zero or greater")
        if not isinstance(self.truncated, bool):
            raise TypeError("truncated must be a bool")

        self._check_absence()
        self._check_confidence()
        self._check_provenance()
        self._check_conflicts()
        if self.prose is not None and self.synthesis_provider_id is None:
            raise ValueError("prose must name the synthesis provider that produced it")

    def _check_absence(self) -> None:
        if self.claims:
            if self.absence is not None:
                raise ValueError("an answer with claims must not carry an absence")
            return
        if self.absence is None:
            raise ValueError("an answer without claims must carry an Absence")
        if self.confidence is not Confidence.UNKNOWN:
            raise ValueError("an answer without claims must declare UNKNOWN confidence")
        if self.absence.question != self.question:
            raise ValueError("absence.question must match the answer question")
        if self.absence.kind is AbsenceKind.NOT_FOUND and (
            self.evidence_used or self.evidence_omitted
        ):
            raise ValueError(
                "NOT_FOUND means no evidence exists, but this answer considered "
                "evidence; the honest kind is UNKNOWN"
            )

    def _check_confidence(self) -> None:
        if not self.claims:
            return
        floor = weakest_confidence(tuple(claim.confidence for claim in self.claims))
        if CONFIDENCE_RANK[self.confidence] < CONFIDENCE_RANK[floor]:
            raise ValueError(
                "overall confidence must not exceed the weakest claim's "
                f"confidence ({floor.value})"
            )

    def _check_provenance(self) -> None:
        used = [reference.chunk_id for reference in self.evidence_used]
        omitted = [omission.chunk_id for omission in self.evidence_omitted]
        used_set = set(used)
        omitted_set = set(omitted)
        if len(used_set) != len(used):
            raise ValueError("evidence_used must not repeat a chunk")
        if len(omitted_set) != len(omitted):
            raise ValueError("evidence_omitted must not repeat a chunk")
        overlap = used_set & omitted_set
        if overlap:
            raise ValueError("evidence cannot be both used and omitted")

        claimed_chunk_ids = [
            chunk_id for claim in self.claims for chunk_id in claim.cited_chunk_ids
        ]
        if len(set(claimed_chunk_ids)) != len(claimed_chunk_ids):
            raise ValueError("a chunk may be cited by at most one claim")
        for chunk_id in claimed_chunk_ids:
            if chunk_id not in used_set:
                raise ValueError(
                    f"claim cites {chunk_id} which is not in evidence_used"
                )

        receipted = {receipt_id.chunk_id for receipt_id in self.receipt_ids}
        if len(receipted) != len(self.receipt_ids):
            raise ValueError("receipt_ids must not repeat a chunk")
        considered = used_set | omitted_set
        if receipted != considered:
            raise ValueError(
                "receipt_ids must cover exactly the evidence used and omitted"
            )

    def _check_conflicts(self) -> None:
        for conflict in self.conflicts:
            for claim in conflict.claims:
                if claim not in self.claims:
                    raise ValueError(
                        "a conflict may only reference claims this answer presents"
                    )

    @property
    def is_absent(self) -> bool:
        """Whether this answer reports an absence instead of claims."""
        return self.absence is not None

    @property
    def cited_chunk_ids(self) -> tuple[ChunkId, ...]:
        """Every chunk cited by any claim, in claim then citation order."""
        return tuple(
            chunk_id for claim in self.claims for chunk_id in claim.cited_chunk_ids
        )


@runtime_checkable
class SynthesisProvider(Protocol):
    """Turns assembled claims into prose.

    The single method is the whole seam. Claims, citations, confidence,
    conflicts, and absences are all decided by the pipeline before a provider
    is called, so a provider can only phrase what it is given — it cannot add a
    claim, drop a citation, or resolve a conflict. Adding an LLM-backed
    provider later is therefore a new class implementing this protocol, with no
    change to the pipeline and no new dependency in this module.

    Implementations must be deterministic in their inputs' ordering: the claims
    arrive in presentation order and must be narrated in that order, so a
    citation marker in the prose still maps to the claim it came from.
    """

    def narrate(self, claims: tuple[Claim, ...]) -> str:
        """Return prose for ``claims``, preserving their order."""
        ...
