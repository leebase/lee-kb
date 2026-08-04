"""Persistence interfaces and the SQLite projection for lee-kb.

The source systems remain authoritative.  This module stores only the latest
searchable projection, plus the append-only synchronization journal and
retrieval receipts needed to audit how that projection has changed and been
used.
"""

from __future__ import annotations

import json
import re
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .contracts import (
    SCHEMA_VERSION,
    Authority,
    ChangeType,
    Chunk,
    ChunkId,
    ChunkKind,
    DocumentType,
    JournalEntry,
    KnowledgeItem,
    KnowledgeItemId,
    PermissionSet,
    Principal,
    PrincipalType,
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

    @abstractmethod
    def record_receipt(self, receipt: RetrievalReceipt) -> int:
        """Append a retrieval receipt and return its repository identifier."""

    @abstractmethod
    def get_receipt(self, receipt_id: int) -> RetrievalReceipt | None:
        """Resolve a previously stored retrieval receipt."""


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
    query TEXT NOT NULL
);
"""


class SQLiteRepository(Repository):
    """SQLite-backed latest-state projection using only the standard library."""

    def __init__(self, database: str | Path) -> None:
        self._connection = sqlite3.connect(str(database))
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

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
                row = self._connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is not None and int(row["value"]) != SCHEMA_VERSION:
                    raise RuntimeError(
                        "unsupported repository schema version "
                        f"{row['value']}; expected {SCHEMA_VERSION}"
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
            self._replace_chunks(item.item_id, normalized_chunks)

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
            if entry is not None:
                entry = self._append_journal(entry)
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
            current = self._connection.execute(
                """
                SELECT project, content_hash, tombstone
                FROM knowledge_items
                WHERE connector_id = ? AND source_object_id = ?
                """,
                (item_id.connector_id, item_id.source_object_id),
            ).fetchone()
            entry: JournalEntry | None = None
            if current is not None and not bool(current["tombstone"]):
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
                entry = self._append_journal(
                    JournalEntry(
                        connector_id=item_id.connector_id,
                        source_object_id=item_id.source_object_id,
                        project=current["project"],
                        change_type=ChangeType.DELETED,
                        sync_timestamp=sync_timestamp,
                        previous_content_hash=current["content_hash"],
                    )
                )
            if cursor is not None:
                self._upsert_cursor(item_id.connector_id, cursor, sync_timestamp)
        return entry

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
                trust, tombstone, tombstoned_at, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                schema_version = excluded.schema_version
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
        if not isinstance(project, str) or not project.strip():
            raise ValueError("project must be a non-empty string")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        fts_query = _fts_query(query, match=match)
        if fts_query is None:
            return ()
        rows = self._connection.execute(
            """
            SELECT c.*, bm25(chunks_fts) AS score,
                   i.source_uri, i.source_label, i.source_fragment,
                   i.document_type, i.content_hash AS item_content_hash,
                   i.source_timestamp, i.sync_timestamp,
                   i.title, i.tags_json, i.authority, i.trust, i.tombstone,
                   i.tombstoned_at, i.schema_version,
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
            LIMIT ?
            """,
            (fts_query, project, int(include_tombstoned), limit),
        ).fetchall()
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
                    principal_groups_json, project, query
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not assign a receipt identifier")
        return cursor.lastrowid

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
