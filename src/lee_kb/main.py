"""Command-line entry point for Lee Knowledge Base.

Version 1 synchronization is explicitly user-driven (``lee-kb sync``) and
retrieval is evidence-only: ``lee-kb search`` calls the governed
:func:`lee_kb.governance.retrieve` surface and prints ranked evidence with
citations, freshness, and receipt identifiers. No LLM answer synthesis
happens in this release -- see :mod:`lee_kb.governance` for the pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tomllib

from . import __version__
from .chunking import chunk_document
from .connectors.base import ConnectorConfigError, ConnectorReadError
from .connectors.local_files import LocalFilesConnector, load_config
from .contracts import (
    DEFAULT_PROJECT,
    ChangeType,
    KnowledgeItem,
    KnowledgeItemId,
    Principal,
    Trust,
)
from .governance import MissingPrincipalError
from .governance import retrieve as governed_retrieve
from .repository import SQLiteRepository

#: Environment variable used to override the configuration file location.
CONFIG_ENV_VAR = "LEE_KB_CONFIG"

#: Fallback principal for a personal deployment when neither --principal nor
#: a configured owner is available. Architecture: "the personal CLI defaults
#: to Lee."
DEFAULT_PRINCIPAL_ID = "lee@leebase.com"

STARTER_CONFIG = """\
# lee-kb configuration
# See architecture.md ("Configuration") for the full contract.

schema = 1

# The default principal for `lee-kb search` when --principal is omitted.
owner = "lee@leebase.com"

# Uncomment and edit to declare a source root for the local-files connector.
# `lee-kb sync` synchronizes every root; `lee-kb sync local_files <name>`
# synchronizes just one.
#
# [roots.notes]
# path = "/absolute/path/to/your/notes"
# owner = "lee@leebase.com"
# include = ["*.md", "*.txt"]
# exclude = [".git/**"]
# authority = "derived"
# trust = "curated"
# visibility = "private"
# project = "default"
"""


@dataclass
class SyncSummary:
    """Counts of what one sync pass did, for a concise CLI report."""

    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    skipped: int = 0
    skipped_objects: tuple[str, ...] = ()


def resolve_config_path(explicit: str | None) -> Path:
    """Resolve the configuration file path.

    Precedence: an explicit ``--config`` flag, then the ``LEE_KB_CONFIG``
    environment variable, then the XDG default documented in
    architecture.md (``~/.config/lee-kb/config.toml``, honoring
    ``XDG_CONFIG_HOME`` when set).
    """
    if explicit:
        return Path(explicit).expanduser()
    env_value = os.environ.get(CONFIG_ENV_VAR)
    if env_value:
        return Path(env_value).expanduser()
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = (
        Path(xdg_config_home).expanduser()
        if xdg_config_home
        else Path.home() / ".config"
    )
    return base / "lee-kb" / "config.toml"


def _load_raw_config(config_path: Path) -> dict:
    try:
        with config_path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConnectorConfigError(f"config file not found: {config_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConnectorConfigError(f"invalid TOML in {config_path}: {error}") from error


def _resolve_database_path(config_path: Path, raw_config: dict) -> Path:
    database = raw_config.get("database")
    if isinstance(database, str) and database.strip():
        candidate = Path(database).expanduser()
        if not candidate.is_absolute():
            candidate = config_path.parent / candidate
        return candidate
    return config_path.parent / "knowledge.sqlite"


def _root_name(source_object_id: str) -> str:
    return source_object_id.split(":", 1)[0]


def _decode_cursor(cursor: str | None) -> dict:
    return {} if cursor is None else json.loads(cursor)


def _encode_cursor(snapshot: dict) -> str:
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))


def cmd_init(args: argparse.Namespace) -> int:
    config_path = resolve_config_path(args.config)
    if config_path.exists() and not args.force:
        print(
            f"lee-kb: config already exists at {config_path}; use --force to overwrite",
            file=sys.stderr,
        )
        return 1
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(STARTER_CONFIG)
    print(f"Wrote starter configuration to {config_path}")
    print(
        "Edit the [roots] table to declare source directories, then run `lee-kb sync`."
    )
    return 0


def _sync_connector(
    connector: LocalFilesConnector,
    repository: SQLiteRepository,
    *,
    root_filter: str | None,
    sync_timestamp: datetime,
) -> SyncSummary:
    previous_cursor = repository.get_connector_cursor(connector.connector_id)
    snapshot = _decode_cursor(previous_cursor)
    changes = connector.list_changes(previous_cursor)
    if root_filter is not None:
        changes = tuple(
            change
            for change in changes
            if _root_name(change.source_object_id) == root_filter
        )

    summary = SyncSummary()
    for change in changes:
        item_id = KnowledgeItemId(connector.connector_id, change.source_object_id)
        if change.change_type is ChangeType.DELETED:
            snapshot.pop(change.source_object_id, None)
            repository.tombstone_item(
                item_id, sync_timestamp=sync_timestamp, cursor=_encode_cursor(snapshot)
            )
            summary.deleted += 1
            continue

        try:
            document = connector.fetch(change.source_object_id)
            permissions = connector.permissions(change.source_object_id)
        except ConnectorReadError as error:
            # One unfetchable object degrades the pass instead of ending it
            # (S1-R-10): count and report it, keep its cursor entry untouched
            # so the next pass retries, and continue with the rest.
            summary.skipped += 1
            summary.skipped_objects += (f"{change.source_object_id}: {error}",)
            continue
        item = KnowledgeItem(
            item_id=item_id,
            project=document.project,
            source_locator=document.source_locator,
            document_type=document.document_type,
            content_hash=document.content_hash,
            source_timestamp=document.source_timestamp,
            sync_timestamp=sync_timestamp,
            permissions=permissions,
            title=document.title,
            authority=document.authority,
            trust=document.trust,
        )
        chunks = chunk_document(
            document.content,
            item_id=item_id,
            project=document.project,
            document_type=document.document_type,
        )
        snapshot[change.source_object_id] = document.content_hash
        repository.sync_item(item, chunks, cursor=_encode_cursor(snapshot))
        if change.change_type is ChangeType.CREATED:
            summary.created += 1
        else:
            summary.updated += 1

    discovered = connector.discover()
    if root_filter is not None:
        discovered = tuple(
            obj for obj in discovered if _root_name(obj.source_object_id) == root_filter
        )
    summary.unchanged = max(
        0, len(discovered) - summary.created - summary.updated - summary.skipped
    )
    return summary


def cmd_sync(args: argparse.Namespace) -> int:
    config_path = resolve_config_path(args.config)
    try:
        roots = load_config(config_path)
        raw_config = _load_raw_config(config_path)
    except ConnectorConfigError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2

    connector_name = args.connector or "local_files"
    if connector_name != "local_files":
        print(
            f"lee-kb: unknown connector {connector_name!r}; "
            "only 'local_files' is available in this release",
            file=sys.stderr,
        )
        return 2

    if args.source is not None:
        known = {root.name for root in roots}
        if args.source not in known:
            configured = ", ".join(sorted(known)) or "(none)"
            print(
                f"lee-kb: unknown source {args.source!r} for connector "
                f"{connector_name!r}; configured roots: {configured}",
                file=sys.stderr,
            )
            return 2

    connector = LocalFilesConnector(roots, connector_id=connector_name)
    db_path = _resolve_database_path(config_path, raw_config)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with SQLiteRepository(db_path) as repository:
            summary = _sync_connector(
                connector,
                repository,
                root_filter=args.source,
                sync_timestamp=datetime.now(timezone.utc),
            )
    except (ConnectorReadError, RuntimeError) as error:
        print(f"lee-kb: sync failed: {error}", file=sys.stderr)
        return 1

    scope = f" ({args.source})" if args.source else ""
    line = (
        f"Synced {connector_name}{scope}: {summary.created} created, "
        f"{summary.updated} updated, {summary.deleted} deleted, "
        f"{summary.unchanged} unchanged"
    )
    if summary.skipped:
        line += f", {summary.skipped} skipped"
    print(line)
    for note in summary.skipped_objects:
        print(f"lee-kb: skipped {note}", file=sys.stderr)
    return 0


def _format_age(delta: timedelta) -> str:
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "moments"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def _lookup_receipt_ids(repository: SQLiteRepository, bundle) -> dict:
    if not bundle.evidence:
        return {}
    # retrieve() persists one receipt per evidence item, in evidence order,
    # immediately before returning the bundle -- they are the last rows
    # inserted, in the same order.
    tail = repository.list_receipts()[-len(bundle.evidence) :]
    return {
        evidence.chunk_id: receipt_id
        for evidence, (receipt_id, _receipt) in zip(bundle.evidence, tail)
    }


def _print_bundle(bundle, receipt_ids: dict) -> None:
    if not bundle.evidence:
        print("No evidence found.")
        if bundle.denied_count:
            print(f"({bundle.denied_count} result(s) denied by permissions.)")
        return

    for evidence in bundle.evidence:
        citation = evidence.citation
        title = (
            citation.title
            or citation.source_locator.label
            or citation.source_locator.uri
        )
        heading = f" — {citation.heading}" if citation.heading else ""
        age = _format_age(bundle.retrieval_timestamp - evidence.sync_timestamp)
        receipt_id = receipt_ids.get(evidence.chunk_id)
        receipt_label = (
            f"receipt #{receipt_id}"
            if receipt_id is not None
            else "receipt (unavailable)"
        )

        print(f"[{evidence.fused_rank}] {title}{heading}")
        print(f"    {citation.source_locator.uri}")
        print(f"    synced {age} ago  ·  {receipt_label}")
        if citation.trust is Trust.MODEL_PRODUCED:
            print("    (model-produced)")
        snippet = " ".join(evidence.text.strip().split())
        if len(snippet) > 240:
            snippet = snippet[:240].rstrip() + "..."
        print(f"    {snippet}")
        print()

    if bundle.denied_count:
        print(f"{bundle.denied_count} additional result(s) denied by permissions.")
    if bundle.truncated:
        print("More evidence was available than --top-k allowed.")


def cmd_search(args: argparse.Namespace) -> int:
    if args.top_k < 1:
        print("lee-kb: --top-k must be at least 1", file=sys.stderr)
        return 2

    config_path = resolve_config_path(args.config)
    raw_config: dict = {}
    if config_path.exists():
        try:
            raw_config = _load_raw_config(config_path)
        except ConnectorConfigError as error:
            print(f"lee-kb: {error}", file=sys.stderr)
            return 2

    db_path = _resolve_database_path(config_path, raw_config)
    if not db_path.exists():
        print(
            f"lee-kb: no synchronized knowledge found at {db_path}; "
            "run `lee-kb sync` first",
            file=sys.stderr,
        )
        return 1

    principal_id = args.principal or raw_config.get("owner") or DEFAULT_PRINCIPAL_ID
    principal = Principal(principal_id=principal_id)

    try:
        with SQLiteRepository(db_path) as repository:
            bundle = governed_retrieve(
                repository,
                args.query,
                principal=principal,
                project=args.project,
                top_k=args.top_k,
            )
            receipt_ids = _lookup_receipt_ids(repository, bundle)
    except MissingPrincipalError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2

    _print_bundle(bundle, receipt_ids)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lee-kb",
        description=(
            "Lee Knowledge Base — a governed knowledge fabric for "
            "permission-aware federated retrieval."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.epilog = (
        "The ingestion and retrieval pipeline is under active development. "
        "See README.md and sprint-plan.md for the current scope."
    )

    subparsers = parser.add_subparsers(dest="command")

    config_help = (
        "Path to the configuration file "
        f"(default: ${CONFIG_ENV_VAR} or the XDG default "
        "~/.config/lee-kb/config.toml)."
    )

    init_parser = subparsers.add_parser(
        "init", help="Write a starter configuration file."
    )
    init_parser.add_argument("--config", help=config_help)
    init_parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing configuration file."
    )
    init_parser.set_defaults(func=cmd_init)

    sync_parser = subparsers.add_parser(
        "sync", help="User-driven synchronization of a connector's sources."
    )
    sync_parser.add_argument(
        "connector",
        nargs="?",
        default=None,
        help="Connector to synchronize (default: local_files).",
    )
    sync_parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Single configured source (root) to synchronize.",
    )
    sync_parser.add_argument("--config", help=config_help)
    sync_parser.set_defaults(func=cmd_sync)

    search_parser = subparsers.add_parser(
        "search", help="Search governed evidence for a query (no LLM synthesis)."
    )
    search_parser.add_argument("query", help="Query text.")
    search_parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=f"Project to search (default: {DEFAULT_PROJECT}).",
    )
    search_parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        dest="top_k",
        help="Maximum evidence items to return.",
    )
    search_parser.add_argument(
        "--principal",
        default=None,
        help=(
            "Principal to search as (default: the configured owner, "
            "then lee@leebase.com)."
        ),
    )
    search_parser.add_argument("--config", help=config_help)
    search_parser.set_defaults(func=cmd_search)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "command", None) is None:
        parser.print_help()
        return

    exit_code = args.func(args)
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
