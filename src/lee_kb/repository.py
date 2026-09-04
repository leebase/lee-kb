"""Persistence interfaces and the SQLite projection for lee-kb.

The source systems remain authoritative.  This module stores only the latest
searchable projection, plus the append-only synchronization journal and
retrieval receipts needed to audit how that projection has changed and been
used.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .contracts import (
    SCHEMA_VERSION,
    AccessAuditEvent,
    AccessAuditOutcome,
    Authority,
    ChangeType,
    Chunk,
    ChunkId,
    ChunkKind,
    DocumentType,
    JournalEntry,
    KnowledgeItem,
    KnowledgeItemId,
    MemoryConfidence,
    MemoryType,
    PermissionSet,
    Principal,
    PrincipalType,
    RetrievalAuditEvent,
    RetrievalAuditStatus,
    RetrievalAuthContext,
    RetrievalReceipt,
    SourceLocator,
    Trust,
    Visibility,
    compute_content_hash,
)

__all__ = ["Repository", "SQLiteRepository", "SearchHit"]


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One FTS match with its current item projection."""

    item: KnowledgeItem
    chunk: Chunk
    score: float


class Repository(ABC):
    """Small persistence boundary shared by repository providers."""

    @property
    @abstractmethod
    def schema_version(self) -> int:
        """Return the stored projection schema version."""

    @abstractmethod
    def sync_item(
        self,
        item: KnowledgeItem,
        chunks: Sequence[Chunk],
        *,
        cursor: str | None = None,
    ) -> JournalEntry | None:
        """Atomically persist one current item and optionally advance a cursor."""

    @abstractmethod
    def tombstone_item(
        self,
        item_id: KnowledgeItemId,
        *,
        sync_timestamp: datetime,
        cursor: str | None = None,
    ) -> JournalEntry | None:
        """Mark an existing item deleted without discarding its metadata."""

    def sync_permissions(
        self, item_id: KnowledgeItemId, permissions: PermissionSet
    ) -> bool:
        """Apply a changed access grant without re-chunking unchanged content."""
        raise NotImplementedError(
            "this repository does not expose permission-only synchronization"
        )

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        project: str,
        limit: int = 10,
        include_tombstoned: bool = False,
        match: str = "any",
    ) -> tuple[SearchHit, ...]:
        """Return lexical matches from the current projection.

        ``match="any"`` ORs content tokens (paraphrase-friendly, BM25-ranked);
        ``match="all"`` requires every token (strict exact-token mode).
        """
    def search_all(
        self,
        query: str,
        *,
        project: str,
        include_tombstoned: bool = False,
        match: str = "any",
    ) -> tuple[SearchHit, ...]:
        """Return every lexical match without repeated provider allocations.

        Backends may override this with one exhaustive query.  The default
        preserves compatibility for repository implementations that expose
        only the bounded ``search`` primitive.
        """
        limit = 32
        while True:
            hits = self.search(
                query,
                project=project,
                limit=limit,
                include_tombstoned=include_tombstoned,
                match=match,
            )
            if len(hits) < limit:
                return hits
            limit *= 2



    @abstractmethod
    def record_receipt(self, receipt: RetrievalReceipt) -> int:
        """Append a retrieval receipt and return its repository identifier."""

    @abstractmethod
    def get_receipt(self, receipt_id: int) -> RetrievalReceipt | None:
        """Resolve a previously stored retrieval receipt."""

    def record_retrieval_event(self, event: RetrievalAuditEvent) -> int:
        """Persist one query-level retrieval audit event or fail closed."""
        raise NotImplementedError(
            "this repository does not expose retrieval audit events"
        )

    def record_access_event(self, event: AccessAuditEvent) -> int:
        """Persist non-content authentication/authorization evidence."""
        raise NotImplementedError("this repository does not expose access audit events")

    def list_access_events(self) -> tuple[tuple[int, AccessAuditEvent], ...]:
        """List non-content access evidence when supported."""
        raise NotImplementedError("this repository does not expose access audit events")

    def has_live_items(self, project: str) -> bool:
        """Return whether a project has any live item when supported.

        The CLI uses this capability on :class:`SQLiteRepository` to
        distinguish an unsynchronized project from a searched empty project.
        It is deliberately concrete so existing replaceable repository
        implementations do not become uninstantiable when the capability is
        added.
        """
        raise NotImplementedError("this repository does not expose live-item state")

    def has_synchronized_project(self, project: str) -> bool:
        """Return whether a project has ever had a synchronized item.

        This remains concrete so replaceable repository implementations do not
        become uninstantiable when the CLI needs to distinguish an empty
        synchronized project from one that has never been synchronized.
        """
        raise NotImplementedError(
            "this repository does not expose synchronized-project state"
        )

    def advance_cursor(
        self,
        connector_id: str,
        cursor: str,
        *,
        updated_at: datetime,
        project: str | None = None,
    ) -> None:
        """Atomically advance a cursor without fabricating a projection row.

        This additive capability is used when a source reports a completed
        delta round with no item or tombstone writes. Existing repository
        providers remain instantiable and must opt in before a live connector
        relies on the capability.
        """
        raise NotImplementedError(
            "this repository does not expose cursor-only advancement"
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_items (
    connector_id TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    project TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    source_label TEXT,
    source_fragment TEXT,
    document_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_timestamp TEXT NOT NULL,
    sync_timestamp TEXT NOT NULL,
    title TEXT,
    tags_json TEXT NOT NULL,
    authority TEXT NOT NULL,
    trust TEXT NOT NULL,
    tombstone INTEGER NOT NULL CHECK (tombstone IN (0, 1)),
    tombstoned_at TEXT,
    schema_version INTEGER NOT NULL,
    memory_type TEXT,
    subject_principal TEXT,
    memory_confidence TEXT,
    importance REAL,
    memory_formed_at TEXT,
    superseded_by TEXT,
    PRIMARY KEY (connector_id, source_object_id)
);

CREATE TABLE IF NOT EXISTS permissions (
    connector_id TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    visibility TEXT NOT NULL,
    allowed_principals_json TEXT NOT NULL,
    allowed_groups_json TEXT NOT NULL,
    classification TEXT,
    PRIMARY KEY (connector_id, source_object_id),
    FOREIGN KEY (connector_id, source_object_id)
        REFERENCES knowledge_items(connector_id, source_object_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    connector_id TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    chunk_ordinal INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    project TEXT NOT NULL,
    text TEXT NOT NULL,
    chunker_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    heading TEXT,
    occurrence INTEGER NOT NULL,
    start_offset INTEGER,
    token_count INTEGER,
    UNIQUE (connector_id, source_object_id, chunk_ordinal),
    FOREIGN KEY (connector_id, source_object_id)
        REFERENCES knowledge_items(connector_id, source_object_id)
        ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text)
    VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_after_update AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text)
    VALUES ('delete', old.id, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS connector_sync_state (
    connector_id TEXT PRIMARY KEY,
    cursor TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS synchronization_journal (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_id TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    project TEXT NOT NULL,
    change_type TEXT NOT NULL,
    sync_timestamp TEXT NOT NULL,
    content_hash TEXT,
    previous_content_hash TEXT
);

CREATE TABLE IF NOT EXISTS retrieval_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_id TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    chunk_ordinal INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    source_connector_id TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    source_label TEXT,
    source_fragment TEXT,
    retrieval_timestamp TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    principal_type TEXT NOT NULL,
    principal_display_name TEXT,
    principal_groups_json TEXT NOT NULL,
    project TEXT NOT NULL,
    query TEXT NOT NULL,
    client_id TEXT,
    session_id TEXT,
    grant_ids_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS retrieval_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    retrieval_timestamp TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    principal_type TEXT NOT NULL,
    principal_display_name TEXT,
    principal_groups_json TEXT NOT NULL,
    project TEXT NOT NULL,
    candidate_count INTEGER NOT NULL,
    denied_count INTEGER NOT NULL,
    released_count INTEGER NOT NULL,
    truncated INTEGER NOT NULL CHECK (truncated IN (0, 1)),
    status TEXT NOT NULL,
    client_id TEXT,
    session_id TEXT,
    grant_ids_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS access_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    client_id TEXT NOT NULL,
    session_id TEXT,
    principal_id TEXT,
    principal_type TEXT,
    principal_display_name TEXT,
    principal_groups_json TEXT NOT NULL DEFAULT '[]',
    tenant TEXT NOT NULL,
    project TEXT,
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    grant_ids_json TEXT NOT NULL DEFAULT '[]',
    query_digest TEXT,
    freshness_state TEXT
);
"""


class SQLiteRepository(Repository):
    """SQLite-backed latest-state projection using only the standard library."""

    def __init__(
        self, database: str | Path, *, initialize_schema: bool = True
    ) -> None:
        if not isinstance(initialize_schema, bool):
            raise TypeError("initialize_schema must be a bool")
        database_path = Path(database)
        if initialize_schema:
            self._connection = sqlite3.connect(str(database_path))
        else:
            database_uri = f"{database_path.resolve().as_uri()}?mode=rw"
            self._connection = sqlite3.connect(database_uri, uri=True)
        if initialize_schema:
            try:
                # The projection stores private evidence, receipts, and access
                # audit rows; keep database files owner-only. Existing files with
                # wider modes are tightened when this process owns them.
                info = database_path.stat()
                group_other = stat.S_IRWXG | stat.S_IRWXO
                if info.st_uid == os.geteuid() and info.st_mode & group_other:
                    os.chmod(database_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        if initialize_schema:
            self._create_schema()
        else:
            self._require_current_schema()

    def __enter__(self) -> SQLiteRepository:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    def _create_schema(self) -> None:
        try:
            with self._connection:
                self._connection.executescript(_SCHEMA)
                self._ensure_column("retrieval_receipts", "client_id", "TEXT")
                self._ensure_column("retrieval_receipts", "session_id", "TEXT")
                self._ensure_column(
                    "retrieval_receipts",
                    "grant_ids_json",
                    "TEXT NOT NULL DEFAULT '[]'",
                )
                self._ensure_column("retrieval_audit_events", "client_id", "TEXT")
                self._ensure_column("retrieval_audit_events", "session_id", "TEXT")
                self._ensure_column(
                    "retrieval_audit_events",
                    "grant_ids_json",
                    "TEXT NOT NULL DEFAULT '[]'",
                )
                self._ensure_column("knowledge_items", "memory_type", "TEXT")
                self._ensure_column("knowledge_items", "subject_principal", "TEXT")
                self._ensure_column("knowledge_items", "memory_confidence", "TEXT")
                self._ensure_column("knowledge_items", "importance", "REAL")
                self._ensure_column("knowledge_items", "memory_formed_at", "TEXT")
                self._ensure_column("knowledge_items", "superseded_by", "TEXT")
                row = self._connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()
                stored_version = None if row is None else int(row["value"])
                if stored_version not in (None, 1, 2, SCHEMA_VERSION):
                    raise RuntimeError(
                        "unsupported repository schema version "
                        f"{row['value']}; expected {SCHEMA_VERSION}"
                    )
                if stored_version in (1, 2):
                    self._connection.execute(
                        "UPDATE knowledge_items SET schema_version = ?",
                        (SCHEMA_VERSION,),
                    )
                self._connection.execute(
                    """
                    INSERT INTO meta(key, value) VALUES ('schema_version', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (str(SCHEMA_VERSION),),
                )
        except sqlite3.OperationalError as error:
            if "fts5" in str(error).lower():
                raise RuntimeError("this SQLite build does not provide FTS5") from error
            raise

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def _require_current_schema(self) -> None:
        """Validate an existing projection without creating or migrating it."""
        try:
            version = self.schema_version
        except sqlite3.DatabaseError as error:
            raise RuntimeError(
                "existing repository projection is not initialized"
            ) from error
        if version != SCHEMA_VERSION:
            raise RuntimeError(
                f"repository schema version {version} requires migration; "
                "run `lee-kb sync` with write access first"
            )

    @property
    def schema_version(self) -> int:
        row = self._connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            raise RuntimeError("repository schema version is missing")
        return int(row["value"])

    def get_schema_version(self) -> int:
        """Compatibility method for callers that prefer a named read."""
        return self.schema_version

    def sync_item(
        self,
        item: KnowledgeItem,
        chunks: Sequence[Chunk],
        *,
        cursor: str | None = None,
    ) -> JournalEntry | None:
        if item.tombstone:
            raise ValueError("use tombstone_item() to persist a source deletion")
        normalized_chunks = tuple(chunks)
        self._validate_chunks(item, normalized_chunks)

        with self._connection:
            entry = self._sync_item_in_transaction(item, normalized_chunks)
            if cursor is not None:
                self._upsert_cursor(
                    item.item_id.connector_id, cursor, item.sync_timestamp
                )
        return entry

    def tombstone_item(
        self,
        item_id: KnowledgeItemId,
        *,
        sync_timestamp: datetime,
        cursor: str | None = None,
    ) -> JournalEntry | None:
        _require_aware(sync_timestamp, "sync_timestamp")
        with self._connection:
            entry = self._tombstone_in_transaction(item_id, sync_timestamp)
            if cursor is not None:
                self._upsert_cursor(item_id.connector_id, cursor, sync_timestamp)
        return entry

    def sync_permissions(
        self, item_id: KnowledgeItemId, permissions: PermissionSet
    ) -> bool:
        if not isinstance(item_id, KnowledgeItemId):
            raise TypeError("item_id must be a KnowledgeItemId")
        if not isinstance(permissions, PermissionSet):
            raise TypeError("permissions must be a PermissionSet")
        current = self._connection.execute(
            """
            SELECT i.tombstone, p.owner, p.visibility,
                   p.allowed_principals_json, p.allowed_groups_json,
                   p.classification
            FROM knowledge_items AS i
            JOIN permissions AS p USING (connector_id, source_object_id)
            WHERE i.connector_id = ? AND i.source_object_id = ?
            """,
            (item_id.connector_id, item_id.source_object_id),
        ).fetchone()
        if current is None or bool(current["tombstone"]):
            raise KeyError(f"cannot update permissions for missing live item {item_id}")
        desired = (
            permissions.owner,
            permissions.visibility.value,
            _dump_tuple(permissions.allowed_principals),
            _dump_tuple(permissions.allowed_groups),
            permissions.classification,
        )
        existing = (
            current["owner"],
            current["visibility"],
            current["allowed_principals_json"],
            current["allowed_groups_json"],
            current["classification"],
        )
        if existing == desired:
            return False
        with self._connection:
            self._upsert_permissions(item_id, permissions)
        return True

    def _sync_item_in_transaction(
        self, item: KnowledgeItem, chunks: tuple[Chunk, ...]
    ) -> JournalEntry | None:
        previous = self._connection.execute(
            """
            SELECT content_hash, tombstone
            FROM knowledge_items
            WHERE connector_id = ? AND source_object_id = ?
            """,
            (item.item_id.connector_id, item.item_id.source_object_id),
        ).fetchone()
        self._upsert_item(item)
        self._upsert_permissions(item.item_id, item.permissions)
        self._replace_chunks(item.item_id, chunks)

        entry: JournalEntry | None = None
        if previous is None or bool(previous["tombstone"]):
            entry = JournalEntry(
                connector_id=item.item_id.connector_id,
                source_object_id=item.item_id.source_object_id,
                project=item.project,
                change_type=ChangeType.CREATED,
                sync_timestamp=item.sync_timestamp,
                content_hash=item.content_hash,
            )
        elif previous["content_hash"] != item.content_hash:
            entry = JournalEntry(
                connector_id=item.item_id.connector_id,
                source_object_id=item.item_id.source_object_id,
                project=item.project,
                change_type=ChangeType.UPDATED,
                sync_timestamp=item.sync_timestamp,
                content_hash=item.content_hash,
                previous_content_hash=previous["content_hash"],
            )
        return self._append_journal(entry) if entry is not None else None

    def _tombstone_in_transaction(
        self, item_id: KnowledgeItemId, sync_timestamp: datetime
    ) -> JournalEntry | None:
        current = self._connection.execute(
            """
            SELECT project, content_hash, tombstone
            FROM knowledge_items
            WHERE connector_id = ? AND source_object_id = ?
            """,
            (item_id.connector_id, item_id.source_object_id),
        ).fetchone()
        if current is None or bool(current["tombstone"]):
            return None
        self._connection.execute(
            """
            UPDATE knowledge_items
            SET tombstone = 1, tombstoned_at = ?, sync_timestamp = ?
            WHERE connector_id = ? AND source_object_id = ?
            """,
            (
                sync_timestamp.isoformat(),
                sync_timestamp.isoformat(),
                item_id.connector_id,
                item_id.source_object_id,
            ),
        )
        return self._append_journal(
            JournalEntry(
                connector_id=item_id.connector_id,
                source_object_id=item_id.source_object_id,
                project=current["project"],
                change_type=ChangeType.DELETED,
                sync_timestamp=sync_timestamp,
                previous_content_hash=current["content_hash"],
            )
        )

    def apply_external_round(
        self,
        operations: Sequence[
            tuple[KnowledgeItemId, KnowledgeItem | None, Sequence[Chunk]]
        ],
        *,
        cursor: str,
        updated_at: datetime,
    ) -> tuple[JournalEntry | None, ...]:
        """Atomically apply one prepared external delta round and its cursor."""
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("cursor must be a non-empty string")
        _require_aware(updated_at, "updated_at")
        normalized_operations = tuple(operations)
        connector_id: str | None = None
        entries: list[JournalEntry | None] = []
        with self._connection:
            for item_id, item, chunks in normalized_operations:
                if not isinstance(item_id, KnowledgeItemId):
                    raise TypeError(
                        "external round item IDs must be KnowledgeItemId values"
                    )
                if connector_id is None:
                    connector_id = item_id.connector_id
                elif connector_id != item_id.connector_id:
                    raise ValueError("an external round must use one connector")
                if item is None:
                    entries.append(self._tombstone_in_transaction(item_id, updated_at))
                    continue
                if item.item_id != item_id:
                    raise ValueError("external round item ID does not match its item")
                normalized_chunks = tuple(chunks)
                self._validate_chunks(item, normalized_chunks)
                entries.append(self._sync_item_in_transaction(item, normalized_chunks))
            if connector_id is None:
                raise ValueError("an external round must contain an operation")
            self._upsert_cursor(connector_id, cursor, updated_at)
        return tuple(entries)

    def advance_cursor(
        self,
        connector_id: str,
        cursor: str,
        *,
        updated_at: datetime,
        project: str | None = None,
    ) -> None:
        """Atomically persist a cursor for a completed empty delta round."""
        if not isinstance(connector_id, str) or not connector_id.strip():
            raise ValueError("connector_id must be a non-empty string")
        if project is not None and (
            not isinstance(project, str) or not project.strip()
        ):
            raise ValueError("project must be a non-empty string when present")
        _require_aware(updated_at, "updated_at")
        with self._connection:
            self._upsert_cursor(connector_id, cursor, updated_at)
            if project is not None:
                self._connection.execute(
                    """
                    INSERT INTO meta(key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (
                        f"synchronized_project:{project}",
                        updated_at.isoformat(),
                    ),
                )

    def _validate_chunks(self, item: KnowledgeItem, chunks: tuple[Chunk, ...]) -> None:
        ordinals: set[int] = set()
        for chunk in chunks:
            if chunk.item_id != item.item_id:
                raise ValueError("every chunk must belong to the synchronized item")
            if chunk.project != item.project:
                raise ValueError("a chunk project must match its owning item")
            if chunk.chunk_id.chunk_ordinal in ordinals:
                raise ValueError("chunk ordinals must be unique within an item")
            if compute_content_hash(chunk.text) != chunk.content_hash:
                raise ValueError("chunk content_hash must match its text")
            ordinals.add(chunk.chunk_id.chunk_ordinal)

    def _upsert_item(self, item: KnowledgeItem) -> None:
        self._connection.execute(
            """
            INSERT INTO knowledge_items(
                connector_id, source_object_id, project, source_uri,
                source_label, source_fragment, document_type, content_hash,
                source_timestamp, sync_timestamp, title, tags_json, authority,
                trust, tombstone, tombstoned_at, schema_version,
                memory_type, subject_principal, memory_confidence,
                importance, memory_formed_at, superseded_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(connector_id, source_object_id) DO UPDATE SET
                project = excluded.project,
                source_uri = excluded.source_uri,
                source_label = excluded.source_label,
                source_fragment = excluded.source_fragment,
                document_type = excluded.document_type,
                content_hash = excluded.content_hash,
                source_timestamp = excluded.source_timestamp,
                sync_timestamp = excluded.sync_timestamp,
                title = excluded.title,
                tags_json = excluded.tags_json,
                authority = excluded.authority,
                trust = excluded.trust,
                tombstone = excluded.tombstone,
                tombstoned_at = excluded.tombstoned_at,
                schema_version = excluded.schema_version,
                memory_type = excluded.memory_type,
                subject_principal = excluded.subject_principal,
                memory_confidence = excluded.memory_confidence,
                importance = excluded.importance,
                memory_formed_at = excluded.memory_formed_at,
                superseded_by = excluded.superseded_by
            """,
            (
                item.item_id.connector_id,
                item.item_id.source_object_id,
                item.project,
                item.source_locator.uri,
                item.source_locator.label,
                item.source_locator.fragment,
                item.document_type.value,
                item.content_hash,
                item.source_timestamp.isoformat(),
                item.sync_timestamp.isoformat(),
                item.title,
                _dump_tuple(item.tags),
                item.authority.value,
                item.trust.value,
                int(item.tombstone),
                _optional_datetime(item.tombstoned_at),
                item.schema_version,
                item.memory_type.value if item.memory_type is not None else None,
                item.subject_principal,
                item.memory_confidence.value if item.memory_confidence is not None else None,
                item.importance,
                _optional_datetime(item.memory_formed_at),
                item.superseded_by,
            ),
        )

    def _upsert_permissions(
        self, item_id: KnowledgeItemId, permissions: PermissionSet
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO permissions(
                connector_id, source_object_id, owner, visibility,
                allowed_principals_json, allowed_groups_json, classification
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(connector_id, source_object_id) DO UPDATE SET
                owner = excluded.owner,
                visibility = excluded.visibility,
                allowed_principals_json = excluded.allowed_principals_json,
                allowed_groups_json = excluded.allowed_groups_json,
                classification = excluded.classification
            """,
            (
                item_id.connector_id,
                item_id.source_object_id,
                permissions.owner,
                permissions.visibility.value,
                _dump_tuple(permissions.allowed_principals),
                _dump_tuple(permissions.allowed_groups),
                permissions.classification,
            ),
        )

    def _replace_chunks(
        self, item_id: KnowledgeItemId, chunks: tuple[Chunk, ...]
    ) -> None:
        ordinals = tuple(chunk.chunk_id.chunk_ordinal for chunk in chunks)
        if ordinals:
            placeholders = ", ".join("?" for _ in ordinals)
            self._connection.execute(
                f"""
                DELETE FROM chunks
                WHERE connector_id = ? AND source_object_id = ?
                  AND chunk_ordinal NOT IN ({placeholders})
                """,
                (item_id.connector_id, item_id.source_object_id, *ordinals),
            )
        else:
            self._connection.execute(
                "DELETE FROM chunks WHERE connector_id = ? AND source_object_id = ?",
                (item_id.connector_id, item_id.source_object_id),
            )

        for chunk in chunks:
            self._connection.execute(
                """
                INSERT INTO chunks(
                    connector_id, source_object_id, chunk_ordinal, content_hash,
                    project, text, chunker_id, kind, heading, occurrence,
                    start_offset, token_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector_id, source_object_id, chunk_ordinal)
                DO UPDATE SET
                    content_hash = excluded.content_hash,
                    project = excluded.project,
                    text = excluded.text,
                    chunker_id = excluded.chunker_id,
                    kind = excluded.kind,
                    heading = excluded.heading,
                    occurrence = excluded.occurrence,
                    start_offset = excluded.start_offset,
                    token_count = excluded.token_count
                """,
                (
                    chunk.item_id.connector_id,
                    chunk.item_id.source_object_id,
                    chunk.chunk_id.chunk_ordinal,
                    chunk.content_hash,
                    chunk.project,
                    chunk.text,
                    chunk.chunker_id,
                    chunk.kind.value,
                    chunk.heading,
                    chunk.occurrence,
                    chunk.start_offset,
                    chunk.token_count,
                ),
            )

    def _append_journal(self, entry: JournalEntry) -> JournalEntry:
        cursor = self._connection.execute(
            """
            INSERT INTO synchronization_journal(
                connector_id, source_object_id, project, change_type,
                sync_timestamp, content_hash, previous_content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.connector_id,
                entry.source_object_id,
                entry.project,
                entry.change_type.value,
                entry.sync_timestamp.isoformat(),
                entry.content_hash,
                entry.previous_content_hash,
            ),
        )
        return JournalEntry(
            connector_id=entry.connector_id,
            source_object_id=entry.source_object_id,
            project=entry.project,
            change_type=entry.change_type,
            sync_timestamp=entry.sync_timestamp,
            content_hash=entry.content_hash,
            previous_content_hash=entry.previous_content_hash,
            sequence=cursor.lastrowid,
        )

    def _upsert_cursor(
        self, connector_id: str, cursor: str, updated_at: datetime
    ) -> None:
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("cursor must be a non-empty string")
        self._connection.execute(
            """
            INSERT INTO connector_sync_state(connector_id, cursor, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(connector_id) DO UPDATE SET
                cursor = excluded.cursor,
                updated_at = excluded.updated_at
            """,
            (connector_id, cursor, updated_at.isoformat()),
        )

    def get_connector_cursor(self, connector_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT cursor FROM connector_sync_state WHERE connector_id = ?",
            (connector_id,),
        ).fetchone()
        return None if row is None else row["cursor"]

    def get_item(self, item_id: KnowledgeItemId) -> KnowledgeItem | None:
        row = self._connection.execute(
            """
            SELECT i.*, p.owner, p.visibility, p.allowed_principals_json,
                   p.allowed_groups_json, p.classification
            FROM knowledge_items AS i
            JOIN permissions AS p USING (connector_id, source_object_id)
            WHERE i.connector_id = ? AND i.source_object_id = ?
            """,
            (item_id.connector_id, item_id.source_object_id),
        ).fetchone()
        return None if row is None else _item_from_row(row)

    def has_live_items(self, project: str) -> bool:
        if not isinstance(project, str) or not project.strip():
            raise ValueError("project must be a non-empty string")
        row = self._connection.execute(
            """
            SELECT 1
            FROM knowledge_items
            WHERE project = ? AND tombstone = 0
            LIMIT 1
            """,
            (project,),
        ).fetchone()
        return row is not None

    def has_synchronized_project(self, project: str) -> bool:
        if not isinstance(project, str) or not project.strip():
            raise ValueError("project must be a non-empty string")
        row = self._connection.execute(
            """
            SELECT 1
            FROM knowledge_items
            WHERE project = ?
            LIMIT 1
            """,
            (project,),
        ).fetchone()
        if row is not None:
            return True
        marker = self._connection.execute(
            "SELECT 1 FROM meta WHERE key = ?",
            (f"synchronized_project:{project}",),
        ).fetchone()
        return marker is not None

    def get_chunks(self, item_id: KnowledgeItemId) -> tuple[Chunk, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM chunks
            WHERE connector_id = ? AND source_object_id = ?
            ORDER BY chunk_ordinal
            """,
            (item_id.connector_id, item_id.source_object_id),
        ).fetchall()
        return tuple(_chunk_from_row(row) for row in rows)

    def journal_entries(
        self, item_id: KnowledgeItemId | None = None
    ) -> tuple[JournalEntry, ...]:
        query = "SELECT * FROM synchronization_journal"
        parameters: tuple[str, ...] = ()
        if item_id is not None:
            query += " WHERE connector_id = ? AND source_object_id = ?"
            parameters = (item_id.connector_id, item_id.source_object_id)
        query += " ORDER BY sequence"
        rows = self._connection.execute(query, parameters).fetchall()
        return tuple(_journal_from_row(row) for row in rows)

    def search(
        self,
        query: str,
        *,
        project: str,
        limit: int = 10,
        include_tombstoned: bool = False,
        match: str = "any",
    ) -> tuple[SearchHit, ...]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        return self._search(
            query,
            project=project,
            include_tombstoned=include_tombstoned,
            match=match,
            limit=limit,
        )

    def search_all(
        self,
        query: str,
        *,
        project: str,
        include_tombstoned: bool = False,
        match: str = "any",
    ) -> tuple[SearchHit, ...]:
        """Return all ranked FTS hits with one row materialization pass."""
        return self._search(
            query,
            project=project,
            include_tombstoned=include_tombstoned,
            match=match,
            limit=None,
        )

    def _search(
        self,
        query: str,
        *,
        project: str,
        include_tombstoned: bool,
        match: str,
        limit: int | None,
    ) -> tuple[SearchHit, ...]:
        if not isinstance(project, str) or not project.strip():
            raise ValueError("project must be a non-empty string")
        fts_query = _fts_query(query, match=match)
        if fts_query is None:
            return ()
        sql = """
            SELECT c.*, bm25(chunks_fts) AS score,
                   i.source_uri, i.source_label, i.source_fragment,
                   i.document_type, i.content_hash AS item_content_hash,
                   i.source_timestamp, i.sync_timestamp,
                   i.title, i.tags_json, i.authority, i.trust, i.tombstone,
                   i.tombstoned_at, i.schema_version,
                   i.memory_type, i.subject_principal, i.memory_confidence,
                   i.importance, i.memory_formed_at, i.superseded_by,
                   p.owner, p.visibility, p.allowed_principals_json,
                   p.allowed_groups_json, p.classification
            FROM chunks_fts
            JOIN chunks AS c ON c.id = chunks_fts.rowid
            JOIN knowledge_items AS i
              ON i.connector_id = c.connector_id
             AND i.source_object_id = c.source_object_id
            JOIN permissions AS p
              ON p.connector_id = i.connector_id
             AND p.source_object_id = i.source_object_id
            WHERE chunks_fts MATCH ? AND i.project = ?
              AND (? OR i.tombstone = 0)
            ORDER BY score, c.connector_id, c.source_object_id, c.chunk_ordinal
        """
        parameters: tuple[object, ...] = (
            fts_query,
            project,
            int(include_tombstoned),
        )
        if limit is not None:
            sql += " LIMIT ?"
            parameters = (*parameters, limit)
        rows = self._connection.execute(sql, parameters).fetchall()
        return tuple(
            SearchHit(
                item=_item_from_row(row),
                chunk=_chunk_from_row(row),
                score=float(row["score"]),
            )
            for row in rows
        )

    def record_receipt(self, receipt: RetrievalReceipt) -> int:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO retrieval_receipts(
                    connector_id, source_object_id, chunk_ordinal, content_hash,
                    source_connector_id, source_uri, source_label,
                    source_fragment, retrieval_timestamp, principal_id,
                    principal_type, principal_display_name,
                    principal_groups_json, project, query,
                    client_id, session_id, grant_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.knowledge_item_id.connector_id,
                    receipt.knowledge_item_id.source_object_id,
                    receipt.chunk_id.chunk_ordinal,
                    receipt.content_hash,
                    receipt.source_locator.connector_id,
                    receipt.source_locator.uri,
                    receipt.source_locator.label,
                    receipt.source_locator.fragment,
                    receipt.retrieval_timestamp.isoformat(),
                    receipt.principal.principal_id,
                    receipt.principal.principal_type.value,
                    receipt.principal.display_name,
                    _dump_tuple(receipt.principal.groups),
                    receipt.project,
                    receipt.query,
                    (
                        None
                        if receipt.auth_context is None
                        else receipt.auth_context.client_id
                    ),
                    (
                        None
                        if receipt.auth_context is None
                        else receipt.auth_context.session_id
                    ),
                    _dump_tuple(
                        ()
                        if receipt.auth_context is None
                        else receipt.auth_context.grant_ids
                    ),
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not assign a receipt identifier")
        return cursor.lastrowid

    def record_retrieval_event(self, event: RetrievalAuditEvent) -> int:
        if not isinstance(event, RetrievalAuditEvent):
            raise TypeError("event must be a RetrievalAuditEvent")
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO retrieval_audit_events(
                    query, retrieval_timestamp, principal_id, principal_type,
                    principal_display_name, principal_groups_json, project,
                    candidate_count, denied_count, released_count, truncated,
                    status, client_id, session_id, grant_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.query,
                    event.retrieval_timestamp.isoformat(),
                    event.principal.principal_id,
                    event.principal.principal_type.value,
                    event.principal.display_name,
                    _dump_tuple(event.principal.groups),
                    event.project,
                    event.candidate_count,
                    event.denied_count,
                    event.released_count,
                    int(event.truncated),
                    event.status.value,
                    (
                        None
                        if event.auth_context is None
                        else event.auth_context.client_id
                    ),
                    (
                        None
                        if event.auth_context is None
                        else event.auth_context.session_id
                    ),
                    _dump_tuple(
                        ()
                        if event.auth_context is None
                        else event.auth_context.grant_ids
                    ),
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not assign an audit event identifier")
        return cursor.lastrowid

    def record_access_event(self, event: AccessAuditEvent) -> int:
        if not isinstance(event, AccessAuditEvent):
            raise TypeError("event must be an AccessAuditEvent")
        principal = event.principal
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO access_audit_events(
                    event_type, timestamp, client_id, session_id,
                    principal_id, principal_type, principal_display_name,
                    principal_groups_json, tenant, project, operation,
                    outcome, reason_code, grant_ids_json, query_digest,
                    freshness_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    event.timestamp.isoformat(),
                    event.client_id,
                    event.session_id,
                    None if principal is None else principal.principal_id,
                    None if principal is None else principal.principal_type.value,
                    None if principal is None else principal.display_name,
                    _dump_tuple(() if principal is None else principal.groups),
                    event.tenant,
                    event.project,
                    event.operation,
                    event.outcome.value,
                    event.reason_code,
                    _dump_tuple(event.grant_ids),
                    event.query_digest,
                    event.freshness_state,
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not assign an access audit identifier")
        return cursor.lastrowid

    def list_access_events(self) -> tuple[tuple[int, AccessAuditEvent], ...]:
        rows = self._connection.execute(
            "SELECT * FROM access_audit_events ORDER BY id"
        ).fetchall()
        return tuple((row["id"], _access_event_from_row(row)) for row in rows)

    def get_receipt(self, receipt_id: int) -> RetrievalReceipt | None:
        row = self._connection.execute(
            "SELECT * FROM retrieval_receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        return None if row is None else _receipt_from_row(row)

    def list_receipts(
        self, item_id: KnowledgeItemId | None = None
    ) -> tuple[tuple[int, RetrievalReceipt], ...]:
        query = "SELECT * FROM retrieval_receipts"
        parameters: tuple[object, ...] = ()
        if item_id is not None:
            query += " WHERE connector_id = ? AND source_object_id = ?"
            parameters = (item_id.connector_id, item_id.source_object_id)
        query += " ORDER BY id"
        rows = self._connection.execute(query, parameters).fetchall()
        return tuple((row["id"], _receipt_from_row(row)) for row in rows)

    def get_retrieval_event(self, event_id: int) -> RetrievalAuditEvent | None:
        row = self._connection.execute(
            "SELECT * FROM retrieval_audit_events WHERE id = ?", (event_id,)
        ).fetchone()
        return None if row is None else _audit_event_from_row(row)

    def list_retrieval_events(self) -> tuple[tuple[int, RetrievalAuditEvent], ...]:
        rows = self._connection.execute(
            "SELECT * FROM retrieval_audit_events ORDER BY id"
        ).fetchall()
        return tuple((row["id"], _audit_event_from_row(row)) for row in rows)


def _item_from_row(row: sqlite3.Row) -> KnowledgeItem:
    item_id = KnowledgeItemId(row["connector_id"], row["source_object_id"])
    permissions = PermissionSet(
        owner=row["owner"],
        visibility=Visibility(row["visibility"]),
        allowed_principals=_load_tuple(row["allowed_principals_json"]),
        allowed_groups=_load_tuple(row["allowed_groups_json"]),
        classification=row["classification"],
    )
    return KnowledgeItem(
        item_id=item_id,
        project=row["project"],
        source_locator=SourceLocator(
            connector_id=item_id.connector_id,
            uri=row["source_uri"],
            label=row["source_label"],
            fragment=row["source_fragment"],
        ),
        document_type=DocumentType(row["document_type"]),
        content_hash=(
            row["item_content_hash"]
            if "item_content_hash" in row.keys()
            else row["content_hash"]
        ),
        source_timestamp=datetime.fromisoformat(row["source_timestamp"]),
        sync_timestamp=datetime.fromisoformat(row["sync_timestamp"]),
        permissions=permissions,
        title=row["title"],
        tags=_load_tuple(row["tags_json"]),
        authority=Authority(row["authority"]),
        trust=Trust(row["trust"]),
        tombstone=bool(row["tombstone"]),
        tombstoned_at=_parse_optional_datetime(row["tombstoned_at"]),
        schema_version=row["schema_version"],
        memory_type=(
            MemoryType(row["memory_type"]) if row["memory_type"] is not None else None
        ),
        subject_principal=row["subject_principal"],
        memory_confidence=(
            MemoryConfidence(row["memory_confidence"])
            if row["memory_confidence"] is not None
            else None
        ),
        importance=row["importance"],
        memory_formed_at=_parse_optional_datetime(row["memory_formed_at"]),
        superseded_by=row["superseded_by"],
    )


def _chunk_from_row(row: sqlite3.Row) -> Chunk:
    item_id = KnowledgeItemId(row["connector_id"], row["source_object_id"])
    return Chunk(
        chunk_id=ChunkId(
            item_id=item_id,
            chunk_ordinal=row["chunk_ordinal"],
            content_hash=row["content_hash"],
        ),
        project=row["project"],
        text=row["text"],
        chunker_id=row["chunker_id"],
        kind=ChunkKind(row["kind"]),
        heading=row["heading"],
        occurrence=row["occurrence"],
        start_offset=row["start_offset"],
        token_count=row["token_count"],
    )


def _journal_from_row(row: sqlite3.Row) -> JournalEntry:
    return JournalEntry(
        connector_id=row["connector_id"],
        source_object_id=row["source_object_id"],
        project=row["project"],
        change_type=ChangeType(row["change_type"]),
        sync_timestamp=datetime.fromisoformat(row["sync_timestamp"]),
        content_hash=row["content_hash"],
        previous_content_hash=row["previous_content_hash"],
        sequence=row["sequence"],
    )


def _auth_context_from_row(row: sqlite3.Row) -> RetrievalAuthContext | None:
    client_id = row["client_id"]
    session_id = row["session_id"]
    if client_id is None and session_id is None:
        return None
    if client_id is None or session_id is None:
        raise RuntimeError("repository auth context is incomplete")
    return RetrievalAuthContext(
        client_id=client_id,
        session_id=session_id,
        grant_ids=_load_tuple(row["grant_ids_json"]),
    )


def _receipt_from_row(row: sqlite3.Row) -> RetrievalReceipt:
    item_id = KnowledgeItemId(row["connector_id"], row["source_object_id"])
    return RetrievalReceipt(
        knowledge_item_id=item_id,
        chunk_id=ChunkId(
            item_id=item_id,
            chunk_ordinal=row["chunk_ordinal"],
            content_hash=row["content_hash"],
        ),
        content_hash=row["content_hash"],
        source_locator=SourceLocator(
            connector_id=row["source_connector_id"],
            uri=row["source_uri"],
            label=row["source_label"],
            fragment=row["source_fragment"],
        ),
        retrieval_timestamp=datetime.fromisoformat(row["retrieval_timestamp"]),
        principal=Principal(
            principal_id=row["principal_id"],
            principal_type=PrincipalType(row["principal_type"]),
            display_name=row["principal_display_name"],
            groups=_load_tuple(row["principal_groups_json"]),
        ),
        project=row["project"],
        query=row["query"],
        auth_context=_auth_context_from_row(row),
    )


def _audit_event_from_row(row: sqlite3.Row) -> RetrievalAuditEvent:
    return RetrievalAuditEvent(
        query=row["query"],
        retrieval_timestamp=datetime.fromisoformat(row["retrieval_timestamp"]),
        principal=Principal(
            principal_id=row["principal_id"],
            principal_type=PrincipalType(row["principal_type"]),
            display_name=row["principal_display_name"],
            groups=_load_tuple(row["principal_groups_json"]),
        ),
        project=row["project"],
        candidate_count=row["candidate_count"],
        denied_count=row["denied_count"],
        released_count=row["released_count"],
        truncated=bool(row["truncated"]),
        status=RetrievalAuditStatus(row["status"]),
        auth_context=_auth_context_from_row(row),
    )


def _access_event_from_row(row: sqlite3.Row) -> AccessAuditEvent:
    principal_id = row["principal_id"]
    principal = None
    if principal_id is not None:
        principal_type = row["principal_type"]
        if principal_type is None:
            raise RuntimeError("access audit principal type is missing")
        principal = Principal(
            principal_id=principal_id,
            principal_type=PrincipalType(principal_type),
            display_name=row["principal_display_name"],
            groups=_load_tuple(row["principal_groups_json"]),
        )
    return AccessAuditEvent(
        event_type=row["event_type"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        client_id=row["client_id"],
        session_id=row["session_id"],
        principal=principal,
        tenant=row["tenant"],
        project=row["project"],
        operation=row["operation"],
        outcome=AccessAuditOutcome(row["outcome"]),
        reason_code=row["reason_code"],
        grant_ids=_load_tuple(row["grant_ids_json"]),
        query_digest=row["query_digest"],
        freshness_state=row["freshness_state"],
    )


_FTS_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "s",
        "should",
        "that",
        "the",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
    }
)


def _fts_query(query: str, *, match: str = "any") -> str | None:
    """Build an FTS5 MATCH expression from a natural-language query.

    ``match="any"`` ORs the content tokens so paraphrase questions rank by
    BM25 overlap instead of requiring every token to co-occur (S1-R-11).
    ``match="all"`` is the strict AND mode for exact-token lookups. A small
    stopword set is stripped first; a query of only stopwords falls back to
    its raw tokens rather than matching nothing.
    """
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if match not in ("any", "all"):
        raise ValueError("match must be 'any' or 'all'")
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    if not tokens:
        return None
    content = [token for token in tokens if token.lower() not in _FTS_STOPWORDS]
    if not content:
        content = tokens
    joiner = " AND " if match == "all" else " OR "
    return joiner.join('"' + token.replace('"', '""') + '"' for token in content)


def _dump_tuple(values: tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _load_tuple(value: str) -> tuple[str, ...]:
    loaded = json.loads(value)
    if not isinstance(loaded, list) or not all(
        isinstance(item, str) for item in loaded
    ):
        raise RuntimeError("repository tuple metadata is corrupt")
    return tuple(loaded)


def _optional_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_optional_datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
