"""Deterministic lexical candidate retrieval.

The provider consumes the repository's SQLite FTS5/BM25 search boundary but
does not depend on SQLite directly.  It is a candidate provider only: it
returns ranked :class:`SearchHit` rows, never evidence.  The one public
evidence-producing surface is :func:`lee_kb.governance.retrieve`, which
permission-filters these candidates before any evidence is assembled and
persists a receipt for every evidence item it releases (S1-R-01).
"""

import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from .contracts import (
    AUTHORITY_RANK,
    Evidence,
    FreshnessReport,
    MetadataFilters,
    RetrieveRequest,
)
from .repository import Repository, SearchHit

__all__ = ["LEXICAL_RETRIEVER", "LexicalRetriever", "StaleEvidenceError"]

LEXICAL_RETRIEVER = "lexical"
_ROOT_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


class StaleEvidenceError(RuntimeError):
    """Raised when a request explicitly rejects stale local evidence."""


class LexicalRetriever:
    """Retrieve deterministic BM25-ranked evidence from a repository."""

    def __init__(
        self,
        repository: Repository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def search(self, request: RetrieveRequest) -> tuple[SearchHit, ...]:
        """Return all matching provider hits in final lexical order.

        Fetching to exhaustion is intentional: metadata filtering and the
        recency tie-break must not be biased by the repository's preliminary
        stable-ID ordering at an arbitrary SQL LIMIT boundary.
        """
        if not isinstance(request, RetrieveRequest):
            raise TypeError("request must be a RetrieveRequest")

        hits: list[SearchHit] = []
        for project in request.effective_projects:
            hits.extend(self._search_project(request, project))

        filtered = [hit for hit in hits if _matches_filters(hit, request.filters)]
        named_roots = _query_named_roots(request.query, filtered)
        if named_roots:
            filtered.sort(
                key=lambda hit: _metadata_ranking_key(
                    hit, named_roots=named_roots
                )
            )
        else:
            # Keep generic-query ordering byte-for-byte compatible with the
            # provider's existing BM25/recency/stable-ID semantics.
            filtered.sort(key=_ranking_key)
        return tuple(filtered)

    def _search_project(
        self, request: RetrieveRequest, project: str
    ) -> tuple[SearchHit, ...]:
        return self._repository.search_all(
            request.query,
            project=project,
            include_tombstoned=request.include_tombstoned,
        )


def _normalized_root_tokens(value: str) -> tuple[str, ...]:
    """Return case-folded alphanumeric root/query tokens."""
    return tuple(token.casefold() for token in _ROOT_TOKEN_RE.findall(value))


def _normalized_root(value: str) -> str:
    """Normalize a root name without allowing substring matches."""
    return "".join(_normalized_root_tokens(value))


def _query_mentions_root(query: str, root: str) -> bool:
    """Whether query tokens contain the complete normalized root name."""
    root_token = _normalized_root(root)
    if not root_token:
        return False

    query_tokens = _normalized_root_tokens(query)
    for start in range(len(query_tokens)):
        joined = ""
        for token in query_tokens[start:]:
            joined += token
            if joined == root_token:
                return True
            if len(joined) >= len(root_token):
                break
    return False


def _local_files_root(hit: SearchHit) -> str | None:
    """Extract the configured root from a local-files source object ID."""
    item_id = hit.item.item_id
    if item_id.connector_id != "local_files":
        return None
    root, separator, _path = item_id.source_object_id.partition(":")
    return root if separator and root else None


def _query_named_roots(
    query: str, hits: list[SearchHit]
) -> frozenset[str]:
    """Return normalized local-files roots explicitly named by the query."""
    named_roots: set[str] = set()
    for hit in hits:
        root = _local_files_root(hit)
        if root is None:
            continue
        normalized = _normalized_root(root)
        if normalized and _query_mentions_root(query, root):
            named_roots.add(normalized)
    return frozenset(named_roots)


def _metadata_ranking_key(
    hit: SearchHit, *, named_roots: frozenset[str]
) -> tuple[int, int, float, float, str, str, int]:
    """Rank explicitly named local roots before the unchanged lexical order."""
    root = _local_files_root(hit)
    normalized_root = None if root is None else _normalized_root(root)
    is_named_root = normalized_root in named_roots
    return (
        0 if is_named_root else 1,
        AUTHORITY_RANK[hit.item.authority] if is_named_root else 0,
        *_ranking_key(hit),
    )


def _matches_filters(hit: SearchHit, filters: MetadataFilters) -> bool:
    item = hit.item
    if filters.connectors and item.item_id.connector_id not in filters.connectors:
        return False
    if filters.document_types and item.document_type not in filters.document_types:
        return False
    if filters.tags and not all(tag in item.tags for tag in filters.tags):
        return False
    if filters.date_range is not None:
        if (
            filters.date_range.start is not None
            and item.source_timestamp < filters.date_range.start
        ):
            return False
        if (
            filters.date_range.end is not None
            and item.source_timestamp > filters.date_range.end
        ):
            return False
    return True


def _ranking_key(hit: SearchHit) -> tuple[float, float, str, str, int]:
    # SQLite FTS5 bm25() uses lower values for stronger matches.  Exact score
    # ties prefer newer source artifacts, then stable chunk identity.
    return (
        hit.score,
        -hit.item.source_timestamp.timestamp(),
        hit.item.item_id.connector_id,
        hit.item.item_id.source_object_id,
        hit.chunk.chunk_id.chunk_ordinal,
    )


def _freshness_report(
    evidence: tuple[Evidence, ...],
    *,
    request: RetrieveRequest,
    retrieved_at: datetime,
) -> FreshnessReport:
    if not evidence:
        return FreshnessReport(is_stale=False, requirement_satisfied=True)

    oldest_sync = min(item.sync_timestamp for item in evidence)
    newest_source = max(item.source_timestamp for item in evidence)
    observed_staleness = max(retrieved_at - oldest_sync, timedelta(0))
    maximum = request.freshness.max_staleness
    is_stale = maximum is not None and observed_staleness > maximum
    return FreshnessReport(
        is_stale=is_stale,
        requirement_satisfied=not is_stale,
        oldest_sync_timestamp=oldest_sync,
        newest_source_timestamp=newest_source,
        staleness=observed_staleness,
        refreshed=False,
    )
