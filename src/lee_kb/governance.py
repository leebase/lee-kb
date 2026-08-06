"""The governed retrieve() surface: permission evaluation, retrieval,
evidence assembly, and receipt persistence composed into one call.

Authorization is fail-closed: every call requires a principal, permission
filtering happens against provider candidates before any evidence is
assembled, and a receipt is persisted to the repository for every piece of
evidence released -- including the empty case, where zero evidence means
zero receipts and no evidence-shaped record is fabricated.

The v1 permission model is single-user (see :class:`SingleUserPermissionEvaluator`)
but is expressed behind :class:`PermissionEvaluator` so a multi-user
evaluator can replace it without touching this module's composition.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone

from .contracts import (
    Citation,
    Evidence,
    EvidenceBundle,
    FreshnessRequirement,
    KnowledgeItem,
    MetadataFilters,
    Principal,
    RetrievalAuditEvent,
    RetrievalAuditStatus,
    RetrievalReceipt,
    RetrieveRequest,
    RetrieverRank,
    Visibility,
)
from .repository import Repository
from .retrieval import (
    LEXICAL_RETRIEVER,
    LexicalRetriever,
    StaleEvidenceError,
    _freshness_report,
)

__all__ = [
    "MissingPrincipalError",
    "PermissionEvaluator",
    "SingleUserPermissionEvaluator",
    "RetrievalProviderError",
    "StaleEvidenceError",
    "retrieve",
]


class MissingPrincipalError(TypeError):
    """Raised when retrieve() is called without a principal.

    There is no anonymous principal in lee-kb. A surface may supply a
    default (the personal CLI defaults to Lee), but this API never accepts
    an unscoped request.
    """


class RetrievalProviderError(RuntimeError):
    """Raised when the retrieval provider cannot resolve a governed query."""


class PermissionEvaluator(ABC):
    """Decides whether a principal may see one knowledge item's evidence.

    Evaluation runs against provider candidates before evidence assembly,
    so a denial here means the item's chunks never become evidence.
    """

    @abstractmethod
    def is_permitted(self, item: KnowledgeItem, principal: Principal) -> bool:
        """Return whether ``principal`` may see evidence from ``item``."""


class SingleUserPermissionEvaluator(PermissionEvaluator):
    """The v1 permission model: the owner is allowed, everyone else is denied
    unless explicitly granted.

    This is deliberately conservative rather than a full multi-tenant
    evaluator. ``PROJECT`` visibility is not treated as an implicit grant to
    every principal, because lee-kb does not yet model which principals are
    entitled to which projects -- that basis is deferred (see Sprint 1
    Open Question 1). Extending this to a real multi-user model means
    implementing a new :class:`PermissionEvaluator`, not changing
    :func:`retrieve`.
    """

    def is_permitted(self, item: KnowledgeItem, principal: Principal) -> bool:
        permissions = item.permissions
        if principal.principal_id == permissions.owner:
            return True
        if principal.principal_id in permissions.allowed_principals:
            return True
        if permissions.allowed_groups and set(principal.groups) & set(
            permissions.allowed_groups
        ):
            return True
        if permissions.visibility is Visibility.PUBLIC:
            return True
        return False


_DEFAULT_EVALUATOR = SingleUserPermissionEvaluator()


def retrieve(
    repository: Repository,
    query: str,
    *,
    principal: Principal | None = None,
    project: str,
    top_k: int = 10,
    filters: MetadataFilters | None = None,
    freshness: FreshnessRequirement | None = None,
    include_tombstoned: bool = False,
    permission_evaluator: PermissionEvaluator | None = None,
    clock: Callable[[], datetime] | None = None,
) -> EvidenceBundle:
    """Run the governed retrieval pipeline and return an EvidenceBundle.

    Pipeline order: permission evaluation over provider candidates, evidence
    assembly, freshness evaluation, per-evidence receipt persistence, and
    query-level audit persistence. A principal is mandatory; omitting one raises
    :class:`MissingPrincipalError` before any repository access happens. A
    repository that cannot persist the query event fails closed instead of
    returning an unaudited bundle.
    """
    if not isinstance(principal, Principal):
        raise MissingPrincipalError(
            "retrieve() requires a principal; anonymous requests are rejected"
        )

    request = RetrieveRequest(
        query=query,
        principal=principal,
        project=project,
        top_k=top_k,
        filters=filters if filters is not None else MetadataFilters(),
        freshness=freshness if freshness is not None else FreshnessRequirement(),
        include_tombstoned=include_tombstoned,
    )

    evaluator = permission_evaluator or _DEFAULT_EVALUATOR
    resolved_clock = clock or (lambda: datetime.now(timezone.utc))
    retrieval_timestamp = resolved_clock()
    _require_aware(retrieval_timestamp)

    try:
        candidates = LexicalRetriever(
            repository, clock=lambda: retrieval_timestamp
        ).search(request)
    except Exception as error:
        _record_retrieval_audit(
            repository,
            RetrievalAuditEvent(
                query=request.query,
                retrieval_timestamp=retrieval_timestamp,
                principal=request.principal,
                project=request.project,
                candidate_count=0,
                denied_count=0,
                released_count=0,
                truncated=False,
                status=RetrievalAuditStatus.PROVIDER_FAILED,
            ),
        )
        raise RetrievalProviderError("the retrieval provider failed") from error

    permitted = []
    denied_count = 0
    for hit in candidates:
        if evaluator.is_permitted(hit.item, request.principal):
            permitted.append(hit)
        else:
            denied_count += 1

    selected = permitted[: request.top_k]
    evidence: list[Evidence] = []
    receipts: list[RetrievalReceipt] = []

    for rank, hit in enumerate(selected, start=1):
        citation = Citation(
            item_id=hit.item.item_id,
            chunk_id=hit.chunk.chunk_id,
            source_locator=hit.item.source_locator,
            title=hit.item.title,
            heading=hit.chunk.heading,
            authority=hit.item.authority,
            trust=hit.item.trust,
        )
        evidence.append(
            Evidence(
                chunk_id=hit.chunk.chunk_id,
                project=hit.chunk.project,
                text=hit.chunk.text,
                citation=citation,
                retriever_ranks=(
                    RetrieverRank(
                        retriever=LEXICAL_RETRIEVER, rank=rank, score=hit.score
                    ),
                ),
                fused_rank=rank,
                source_timestamp=hit.item.source_timestamp,
                sync_timestamp=hit.item.sync_timestamp,
                kind=hit.chunk.kind,
            )
        )
        receipt = RetrievalReceipt(
            knowledge_item_id=hit.item.item_id,
            chunk_id=hit.chunk.chunk_id,
            content_hash=hit.chunk.content_hash,
            source_locator=hit.item.source_locator,
            retrieval_timestamp=retrieval_timestamp,
            principal=request.principal,
            project=hit.chunk.project,
            query=request.query,
        )
        receipts.append(receipt)

    evidence_tuple = tuple(evidence)
    report = _freshness_report(
        evidence_tuple, request=request, retrieved_at=retrieval_timestamp
    )
    if request.freshness.fail_on_stale and report.is_stale:
        _record_retrieval_audit(
            repository,
            RetrievalAuditEvent(
                query=request.query,
                retrieval_timestamp=retrieval_timestamp,
                principal=request.principal,
                project=request.project,
                candidate_count=len(candidates),
                denied_count=denied_count,
                released_count=0,
                truncated=len(permitted) > request.top_k,
                status=RetrievalAuditStatus.STALE_REFUSED,
            ),
        )
        raise StaleEvidenceError("retrieved evidence does not meet freshness")

    for receipt in receipts:
        repository.record_receipt(receipt)

    _record_retrieval_audit(
        repository,
        RetrievalAuditEvent(
            query=request.query,
            retrieval_timestamp=retrieval_timestamp,
            principal=request.principal,
            project=request.project,
            candidate_count=len(candidates),
            denied_count=denied_count,
            released_count=len(evidence_tuple),
            truncated=len(permitted) > request.top_k,
        ),
    )

    return EvidenceBundle(
        request=request,
        evidence=evidence_tuple,
        citations=tuple(item.citation for item in evidence_tuple),
        receipts=tuple(receipts),
        freshness=report,
        retrieval_timestamp=retrieval_timestamp,
        retrievers_used=(LEXICAL_RETRIEVER,),
        denied_count=denied_count,
        truncated=len(permitted) > request.top_k,
    )


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError("retrieval clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retrieval clock must return a timezone-aware datetime")


def _record_retrieval_audit(repository: Repository, event: RetrievalAuditEvent) -> None:
    """Persist the query event required by the governed retrieval contract."""
    repository.record_retrieval_event(event)
