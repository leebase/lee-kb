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

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone

from .contracts import (
    Citation,
    Evidence,
    EvidenceBundle,
    FreshnessRequirement,
    HistoricalLocator,
    HistoricalLookupResult,
    HistoricalReceipt,
    HistoricalReleaseManifest,
    ImmutableHistoricalObject,
    KnowledgeItem,
    MappedIdentity,
    MetadataFilters,
    OwnerFreshnessState,
    OwnerIdentityMapping,
    OwnerKnowledgeState,
    PolicyBasis,
    Principal,
    RetrievalAuditEvent,
    RetrievalAuditStatus,
    RetrievalAuthContext,
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
    "ExactHistoricalReader",
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
    auth_context: RetrievalAuthContext | None = None,
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
    if auth_context is not None and not isinstance(auth_context, RetrievalAuthContext):
        raise TypeError("auth_context must be a RetrievalAuthContext or None")

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
                auth_context=auth_context,
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
            auth_context=auth_context,
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
                auth_context=auth_context,
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
            auth_context=auth_context,
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


class ExactHistoricalReader:
    """Read one exact historical object after both policy bases succeed.

    ``resolver`` is an injected owner-native exact-object seam. It is never a
    repository walker, search provider, or cache: the supported implementation
    (``owner.GitExactObjectResolver``) reads exactly one named object.
    """

    def __init__(
        self,
        *,
        mapping: OwnerIdentityMapping,
        manifest: HistoricalReleaseManifest | None,
        current_permission: (
            Callable[[MappedIdentity, HistoricalLocator, str], PolicyBasis] | None
        ),
        resolver: (
            Callable[[HistoricalLocator], ImmutableHistoricalObject | None]
            | object
            | None
        ),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(mapping, OwnerIdentityMapping):
            raise TypeError("mapping must be an OwnerIdentityMapping")
        if manifest is not None and not isinstance(manifest, HistoricalReleaseManifest):
            raise TypeError("manifest must be a HistoricalReleaseManifest or None")
        self._mapping = mapping
        self._manifest = manifest
        self._current_permission = current_permission
        self._resolver = resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def lookup(
        self,
        *,
        authenticated_principal: str,
        locator: HistoricalLocator,
        classification: str,
        source_namespace: str,
        root: str,
        item_id: str | None = None,
        project: str | None = None,
        freshness: FreshnessRequirement | None = None,
    ) -> HistoricalLookupResult:
        """Return a body only for one exact, doubly-authorized locator."""
        if not isinstance(locator, HistoricalLocator):
            raise TypeError("locator must be a HistoricalLocator")
        if not isinstance(classification, str) or not classification.strip():
            raise ValueError("classification must be a non-empty string")
        if not isinstance(source_namespace, str) or not source_namespace.strip():
            raise ValueError("source_namespace must be a non-empty string")
        if not isinstance(root, str) or not root.strip():
            raise ValueError("root must be a non-empty string")
        if item_id is not None and (
            not isinstance(item_id, str) or not item_id.strip()
        ):
            raise ValueError("item_id must be a non-empty string when supplied")
        evaluated_at = self._clock()
        _require_aware(evaluated_at)
        try:
            identity = self._mapping.resolve(authenticated_principal, project=project)
        except (PermissionError, TypeError, ValueError):
            return HistoricalLookupResult(
                knowledge_state=OwnerKnowledgeState.UNKNOWN,
                freshness_state=OwnerFreshnessState.UNKNOWN,
                body=None,
                receipt=None,
            )

        unknown_policy = PolicyBasis.unknown()
        if not self._mapping.permits(
            identity,
            source_namespace=source_namespace,
            root=root,
            path=locator.path,
            item_id=item_id,
        ):
            current = PolicyBasis(
                self._mapping.version, self._mapping.mapping_hash, "deny"
            )
            receipt = self._receipt(
                identity=identity,
                locator=locator,
                classification=classification,
                source_namespace=source_namespace,
                root=root,
                item_id=item_id,
                current=current,
                historical=unknown_policy,
                state=OwnerKnowledgeState.UNAUTHORIZED,
                freshness_state=OwnerFreshnessState.UNKNOWN,
                evaluated_at=evaluated_at,
                obj=None,
            )
            return HistoricalLookupResult(
                OwnerKnowledgeState.UNAUTHORIZED,
                OwnerFreshnessState.UNKNOWN,
                None,
                receipt,
            )

        current = self._evaluate_current(
            identity, locator, classification, evaluated_at
        )
        if current.decision != "allow":
            state = (
                OwnerKnowledgeState.UNAUTHORIZED
                if current.decision == "deny"
                else OwnerKnowledgeState.UNKNOWN
            )
            receipt = self._receipt(
                identity=identity,
                locator=locator,
                classification=classification,
                source_namespace=source_namespace,
                root=root,
                item_id=item_id,
                current=current,
                historical=unknown_policy,
                state=state,
                freshness_state=OwnerFreshnessState.UNKNOWN,
                evaluated_at=evaluated_at,
                obj=None,
            )
            return HistoricalLookupResult(
                state, OwnerFreshnessState.UNKNOWN, None, receipt
            )

        if self._manifest is None:
            historical = unknown_policy
        else:
            try:
                historical = self._manifest.evaluate(
                    principal_id=identity.principal_id,
                    project=identity.project,
                    locator=locator,
                    classification=classification,
                    at=evaluated_at,
                )
            except (TypeError, ValueError):
                historical = unknown_policy
        if not self._policy_is_live(historical, evaluated_at):
            state = (
                OwnerKnowledgeState.UNAUTHORIZED
                if historical.decision == "deny"
                else OwnerKnowledgeState.UNKNOWN
            )
            receipt = self._receipt(
                identity=identity,
                locator=locator,
                classification=classification,
                source_namespace=source_namespace,
                root=root,
                item_id=item_id,
                current=current,
                historical=historical,
                state=state,
                freshness_state=OwnerFreshnessState.UNKNOWN,
                evaluated_at=evaluated_at,
                obj=None,
            )
            return HistoricalLookupResult(
                state, OwnerFreshnessState.UNKNOWN, None, receipt
            )

        obj = self._resolve(locator)
        if (
            obj is None
            or obj.locator != locator
            or obj.classification != classification
        ):
            receipt = self._receipt(
                identity=identity,
                locator=locator,
                classification=classification,
                source_namespace=source_namespace,
                root=root,
                item_id=item_id,
                current=current,
                historical=historical,
                state=OwnerKnowledgeState.UNKNOWN,
                freshness_state=OwnerFreshnessState.UNKNOWN,
                evaluated_at=evaluated_at,
                obj=None,
            )
            return HistoricalLookupResult(
                OwnerKnowledgeState.UNKNOWN,
                OwnerFreshnessState.UNKNOWN,
                None,
                receipt,
            )

        freshness_state = self._freshness_state(
            freshness or FreshnessRequirement(), evaluated_at, obj
        )
        if freshness_state is not OwnerFreshnessState.FRESH:
            receipt = self._receipt(
                identity=identity,
                locator=locator,
                classification=classification,
                source_namespace=source_namespace,
                root=root,
                item_id=item_id,
                current=current,
                historical=historical,
                state=OwnerKnowledgeState.UNKNOWN,
                freshness_state=freshness_state,
                evaluated_at=evaluated_at,
                obj=None,
            )
            return HistoricalLookupResult(
                OwnerKnowledgeState.UNKNOWN, freshness_state, None, receipt
            )

        receipt = self._receipt(
            identity=identity,
            locator=locator,
            classification=classification,
            source_namespace=source_namespace,
            root=root,
            item_id=item_id,
            current=current,
            historical=historical,
            state=OwnerKnowledgeState.KNOWN,
            freshness_state=freshness_state,
            evaluated_at=evaluated_at,
            obj=obj,
        )
        return HistoricalLookupResult(
            OwnerKnowledgeState.KNOWN, freshness_state, obj.body, receipt
        )

    def _evaluate_current(
        self,
        identity: MappedIdentity,
        locator: HistoricalLocator,
        classification: str,
        evaluated_at: datetime,
    ) -> PolicyBasis:
        if self._current_permission is None:
            return PolicyBasis.unknown()
        try:
            basis = self._current_permission(identity, locator, classification)
        except Exception:
            return PolicyBasis.unknown()
        if not isinstance(basis, PolicyBasis):
            return PolicyBasis.unknown()
        if not self._policy_is_live(basis, evaluated_at):
            return PolicyBasis.unknown(basis.version)
        return basis

    def _resolve(self, locator: HistoricalLocator) -> ImmutableHistoricalObject | None:
        if self._resolver is None:
            return None
        try:
            value = (
                self._resolver(locator)
                if callable(self._resolver)
                else self._resolver.resolve(locator)
            )
        except Exception:
            return None
        return value if isinstance(value, ImmutableHistoricalObject) else None

    @staticmethod
    def _policy_is_live(basis: PolicyBasis, at: datetime) -> bool:
        if basis.decision != "allow":
            return False
        if basis.evaluated_at is not None and basis.evaluated_at > at:
            return False
        return basis.expires_at is None or at < basis.expires_at

    @staticmethod
    def _freshness_state(
        requirement: FreshnessRequirement,
        evaluated_at: datetime,
        obj: ImmutableHistoricalObject | None,
    ) -> OwnerFreshnessState:
        if obj is None:
            return OwnerFreshnessState.UNKNOWN
        if obj.blob_timestamp > evaluated_at:
            return OwnerFreshnessState.UNKNOWN
        if (
            requirement.max_staleness is not None
            and evaluated_at - obj.blob_timestamp > requirement.max_staleness
        ):
            return OwnerFreshnessState.STALE
        return OwnerFreshnessState.FRESH

    def _receipt(
        self,
        *,
        identity: MappedIdentity,
        locator: HistoricalLocator,
        classification: str,
        source_namespace: str,
        root: str,
        item_id: str | None,
        current: PolicyBasis,
        historical: PolicyBasis,
        state: OwnerKnowledgeState,
        freshness_state: OwnerFreshnessState,
        evaluated_at: datetime,
        obj: ImmutableHistoricalObject | None,
    ) -> HistoricalReceipt:
        body = {
            "contract_version": "lee-kb.owner.contract/v1",
            "mapping_version": identity.mapping_version,
            "mapping_hash": identity.mapping_hash,
            "principal_id": identity.principal_id,
            "project": identity.project,
            "locator": locator.as_tuple(),
            "classification": classification,
            "current_policy": (current.version, current.sha256, current.decision),
            "historical_policy": (
                historical.version,
                historical.sha256,
                historical.decision,
            ),
            "historical_manifest_hash": (
                self._manifest.manifest_hash if self._manifest is not None else None
            ),
            "blob_hash": obj.blob_hash if obj else None,
            "blob_timestamp": obj.blob_timestamp.isoformat() if obj else None,
            "evaluation_time": evaluated_at.isoformat(),
            "state": state.value,
        }
        audit_id = (
            "audit-"
            + hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:32]
        )
        return HistoricalReceipt(
            audit_id=audit_id,
            mapping_version=identity.mapping_version,
            mapping_hash=identity.mapping_hash,
            mapped_principal_id=identity.principal_id,
            mapped_principal_type=identity.principal_type,
            authenticated_principal=identity.authenticated_principal,
            tenant=identity.tenant,
            lane=identity.lane,
            scope_id=identity.scope_id,
            purpose=identity.purpose,
            project=identity.project,
            source_namespace=source_namespace,
            root=root,
            path=locator.path,
            item_id=item_id,
            locator=locator,
            classification=classification,
            current_policy_version=current.version,
            current_policy_hash=current.sha256,
            current_policy_decision=current.decision,
            historical_policy_version=historical.version,
            historical_policy_hash=historical.sha256,
            historical_policy_decision=historical.decision,
            historical_manifest_hash=(
                self._manifest.manifest_hash if self._manifest is not None else None
            ),
            blob_hash=obj.blob_hash if obj else None,
            blob_timestamp=obj.blob_timestamp if obj else None,
            evaluation_time=evaluated_at,
            freshness_state=freshness_state,
            knowledge_state=state,
        )
