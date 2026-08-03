"""Connector contract shared by every lee-kb source connector.

A connector describes one source system: what objects it holds, what
changed, how to fetch content, and what permissions and health look like.
It does not decide retrieval policy, chunking strategy, or authorization
outcomes — those live in the ingestion and retrieval layers, which are the
only consumers of a connector. See ``skills/connector-development.md`` for
the full contract and the ingestion invariants every connector must uphold.

Every connector implements eight responsibilities, matching the skill
document one-for-one:

- ``discover()``       — identify source objects and assign stable source IDs.
- ``list_changes()``   — return new, changed, and deleted objects since a
                          cursor (or snapshot, for sources with no native
                          change feed).
- ``fetch()``           — retrieve source content and source timestamps.
- ``permissions()``     — expose authorization metadata for one object.
- ``relationships()``   — expose useful source relationships, when the
                          source system has any. Most first-generation
                          connectors have none.
- ``refresh()``         — perform a targeted, synchronous refresh of one
                          object when freshness requires it.
- ``health()``          — report connectivity and source health.
- ``checkpoint()``      — compute the cursor to persist once ingestion of a
                          discovered set has succeeded. The connector never
                          persists this itself; persistence is the
                          repository's job, advanced atomically with the
                          ingested content it describes.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ..contracts import (
    DEFAULT_PROJECT,
    Authority,
    ChangeType,
    DocumentType,
    PermissionSet,
    SourceLocator,
    Trust,
)

__all__ = [
    "ConnectorError",
    "ConnectorConfigError",
    "ConnectorReadError",
    "SourceObject",
    "ObjectChange",
    "FetchedDocument",
    "HealthStatus",
    "Connector",
]

_CHANGE_KINDS = (ChangeType.CREATED, ChangeType.UPDATED, ChangeType.DELETED)
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_optional_text(value: object, name: str) -> None:
    if value is not None:
        _require_text(value, name)


def _require_hash(value: object, name: str) -> None:
    if not isinstance(value, str) or not _HASH_PATTERN.match(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _require_aware(value: object, name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_project(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "project is required on every knowledge record; "
            f"use {DEFAULT_PROJECT!r} for a personal deployment"
        )


class ConnectorError(Exception):
    """Base class for connector failures."""


class ConnectorConfigError(ConnectorError):
    """Raised when a connector's configuration is missing or malformed."""


class ConnectorReadError(ConnectorError):
    """Raised when a known source object cannot be read or decoded.

    Ingestion invariants require a clear, specific error here rather than a
    silently skipped or corrupted item.
    """


@dataclass(frozen=True, slots=True)
class SourceObject:
    """One object identified by :meth:`Connector.discover`.

    Carries just enough metadata to diff against a prior snapshot and to
    cite the object, without paying the cost of a full :meth:`Connector.fetch`.
    """

    source_object_id: str
    source_locator: SourceLocator
    document_type: DocumentType
    content_hash: str
    source_timestamp: datetime
    project: str
    authority: Authority = Authority.DERIVED
    trust: Trust = Trust.CURATED

    def __post_init__(self) -> None:
        _require_text(self.source_object_id, "source_object_id")
        if not isinstance(self.source_locator, SourceLocator):
            raise TypeError("source_locator must be a SourceLocator")
        if not isinstance(self.document_type, DocumentType):
            raise TypeError("document_type must be a DocumentType")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.source_timestamp, "source_timestamp")
        _require_project(self.project)
        if not isinstance(self.authority, Authority):
            raise TypeError("authority must be an Authority")
        if not isinstance(self.trust, Trust):
            raise TypeError("trust must be a Trust")


@dataclass(frozen=True, slots=True)
class ObjectChange:
    """One entry in the diff returned by :meth:`Connector.list_changes`.

    Mirrors the hash invariants of ``JournalEntry`` for the three change
    kinds a connector can observe on its own — a connector never purges,
    since purge is a governance policy applied above it.
    """

    source_object_id: str
    change_type: ChangeType
    content_hash: str | None = None
    previous_content_hash: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_object_id, "source_object_id")
        if self.change_type not in _CHANGE_KINDS:
            raise ValueError(
                "change_type must be created, updated, or deleted "
                "(a connector never purges)"
            )
        if self.content_hash is not None:
            _require_hash(self.content_hash, "content_hash")
        if self.previous_content_hash is not None:
            _require_hash(self.previous_content_hash, "previous_content_hash")

        if self.change_type is ChangeType.CREATED:
            if self.content_hash is None:
                raise ValueError("a created change must record content_hash")
            if self.previous_content_hash is not None:
                raise ValueError(
                    "a created change must not record previous_content_hash"
                )
        elif self.change_type is ChangeType.UPDATED:
            if self.content_hash is None or self.previous_content_hash is None:
                raise ValueError("an updated change must record both content hashes")
            if self.content_hash == self.previous_content_hash:
                raise ValueError("an updated change must record a changed hash")
        else:  # DELETED
            if self.content_hash is not None:
                raise ValueError("a deleted change has no current content_hash")
            if self.previous_content_hash is None:
                raise ValueError("a deleted change must record previous_content_hash")


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """The result of :meth:`Connector.fetch` or :meth:`Connector.refresh`."""

    source_object_id: str
    source_locator: SourceLocator
    document_type: DocumentType
    content: str
    content_hash: str
    source_timestamp: datetime
    project: str
    title: str | None = None
    authority: Authority = Authority.DERIVED
    trust: Trust = Trust.CURATED

    def __post_init__(self) -> None:
        _require_text(self.source_object_id, "source_object_id")
        if not isinstance(self.source_locator, SourceLocator):
            raise TypeError("source_locator must be a SourceLocator")
        if not isinstance(self.document_type, DocumentType):
            raise TypeError("document_type must be a DocumentType")
        if not isinstance(self.content, str):
            raise TypeError("content must be a str")
        _require_hash(self.content_hash, "content_hash")
        _require_aware(self.source_timestamp, "source_timestamp")
        _require_project(self.project)
        _require_optional_text(self.title, "title")
        if not isinstance(self.authority, Authority):
            raise TypeError("authority must be an Authority")
        if not isinstance(self.trust, Trust):
            raise TypeError("trust must be a Trust")


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Connectivity and source health, as reported by :meth:`Connector.health`."""

    healthy: bool
    checked_at: datetime
    detail: str = ""
    missing_required_roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.checked_at, "checked_at")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a str")
        if not isinstance(self.missing_required_roots, tuple):
            raise TypeError("missing_required_roots must be a tuple")


class Connector(ABC):
    """The contract every lee-kb source connector implements."""

    @property
    @abstractmethod
    def connector_id(self) -> str:
        """The stable identifier of this connector instance."""

    @abstractmethod
    def discover(self) -> tuple[SourceObject, ...]:
        """Identify current source objects with stable source IDs."""

    @abstractmethod
    def list_changes(self, cursor: str | None = None) -> tuple[ObjectChange, ...]:
        """Return objects created, changed, or deleted since ``cursor``."""

    @abstractmethod
    def fetch(self, source_object_id: str) -> FetchedDocument:
        """Retrieve source content and source timestamps for one object."""

    @abstractmethod
    def permissions(self, source_object_id: str) -> PermissionSet:
        """Return the authorization facts captured for one object."""

    @abstractmethod
    def relationships(self, source_object_id: str) -> tuple[str, ...]:
        """Return related source object IDs, when the source exposes any."""

    @abstractmethod
    def refresh(self, source_object_id: str) -> FetchedDocument:
        """Perform a targeted, synchronous refresh of one object."""

    @abstractmethod
    def health(self) -> HealthStatus:
        """Report connectivity and source health."""

    @abstractmethod
    def checkpoint(self, objects: Sequence[SourceObject]) -> str:
        """Compute the cursor to persist once ``objects`` is fully ingested.

        The connector only computes the value; persisting it atomically with
        the ingested content is the repository's responsibility.
        """
