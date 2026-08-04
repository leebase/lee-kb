"""Command-line entry point for Lee Knowledge Base.

Version 1 synchronization is explicitly user-driven (``lee-kb sync``).
``lee-kb search`` calls the governed :func:`lee_kb.governance.retrieve`
surface directly and prints ranked evidence with citations, freshness, and
receipt identifiers -- no synthesis. ``lee-kb ask`` layers claim assembly and
deterministic, offline synthesis on top of the same governed surface via
:func:`lee_kb.answer.answer`; see :mod:`lee_kb.answer` and
``docs/answer-architecture.md`` for the pipeline. Neither command has an
LLM dependency in this release.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tomllib

from . import __version__
from .answer import answer as compute_answer
from .answer_contracts import AbsenceKind
from .chunking import chunk_document
from .connectors.base import (
    ConnectorConfigError,
    ConnectorReadError,
    ObjectChange,
    SourceObject,
)
from .connectors.local_files import (
    LocalFilesConnector,
    contains_token_shaped_secret,
    load_config,
)
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
    """Counts of what one sync pass did, for a concise CLI report.

    A document that a user expects to be searchable must never disappear
    without a count: every candidate the sync did not index shows up in
    exactly one of ``skipped``, ``skipped_token_content``, ``git_ignored``,
    ``git_unresolved``, or ``unhandled_formats``.
    """

    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    skipped: int = 0
    skipped_objects: tuple[str, ...] = ()
    #: Fetched content matched a token-shaped secret pattern and was not
    #: indexed (see lee_kb.connectors.local_files.contains_token_shaped_secret).
    skipped_token_content: int = 0
    #: Candidates git reports as ignored, excluded from the projection.
    git_ignored: int = 0
    #: Candidates whose git-ignore status could not be resolved (non-git
    #: root, or git unavailable) -- not excluded, only unverified.
    git_unresolved: int = 0
    #: Lowercase file suffix to count of candidates with no registered
    #: format handler.
    unhandled_formats: dict[str, int] = field(default_factory=dict)


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


def _resolve_database_path(
    config_path: Path, raw_config: dict, explicit: str | None = None
) -> Path:
    if explicit:
        return Path(explicit).expanduser()
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


def _changes_from_objects(
    objects: tuple[SourceObject, ...],
    previous: dict[str, str],
    *,
    root_filter: str | None,
) -> tuple[ObjectChange, ...]:
    """Diff one discovery result against the stored snapshot cursor."""
    current = {
        obj.source_object_id: obj.content_hash
        for obj in objects
        if root_filter is None or _root_name(obj.source_object_id) == root_filter
    }
    changes: list[ObjectChange] = []
    for source_object_id, content_hash in current.items():
        previous_hash = previous.get(source_object_id)
        if previous_hash is None:
            changes.append(
                ObjectChange(
                    source_object_id,
                    ChangeType.CREATED,
                    content_hash=content_hash,
                )
            )
        elif previous_hash != content_hash:
            changes.append(
                ObjectChange(
                    source_object_id,
                    ChangeType.UPDATED,
                    content_hash=content_hash,
                    previous_content_hash=previous_hash,
                )
            )
    for source_object_id, previous_hash in previous.items():
        if root_filter is not None and _root_name(source_object_id) != root_filter:
            continue
        if source_object_id not in current:
            changes.append(
                ObjectChange(
                    source_object_id,
                    ChangeType.DELETED,
                    previous_content_hash=previous_hash,
                )
            )
    return tuple(sorted(changes, key=lambda change: change.source_object_id))


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
    report = connector.discover_report(root_name=root_filter)
    changes = _changes_from_objects(
        report.objects,
        snapshot,
        root_filter=root_filter,
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

        if contains_token_shaped_secret(document.content):
            # Credentials must not enter the projection: skip indexing and
            # leave the cursor untouched so the file is re-checked (and
            # re-reported) every sync until it is redacted or removed.
            summary.skipped_token_content += 1
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

    summary.unhandled_formats = report.unhandled_formats
    summary.git_ignored = report.git_ignored
    summary.git_unresolved = report.git_unresolved
    summary.unchanged = max(
        0,
        len(report.objects)
        - summary.created
        - summary.updated
        - summary.skipped
        - summary.skipped_token_content,
    )
    return summary


def cmd_sync(args: argparse.Namespace) -> int:
    config_path = resolve_config_path(args.config)
    try:
        raw_config = _load_raw_config(config_path)
        roots = load_config(config_path, workspace_root=args.workspace_root)
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

    # A required root that has become unreachable (unmounted drive, moved or
    # renamed repository) would otherwise be skipped silently and simply
    # produce a smaller corpus (S2-R-13). Check health before syncing so the
    # root is named, and refuse the pass rather than record a projection that
    # is quietly missing a source the operator declared required.
    status = connector.health()
    if not status.healthy:
        print(f"lee-kb: sync refused: {status.detail}", file=sys.stderr)
        print(
            "lee-kb: fix the path or set required = false for that root "
            "in the configuration.",
            file=sys.stderr,
        )
        return 1
    if status.detail and status.detail != "all roots reachable":
        print(f"lee-kb: {status.detail}", file=sys.stderr)

    db_path = _resolve_database_path(config_path, raw_config, args.database)
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
    if summary.skipped_token_content:
        line += f", {summary.skipped_token_content} skipped (token-shaped content)"
    if summary.git_ignored:
        line += f", {summary.git_ignored} git-ignored"
    if summary.git_unresolved:
        line += f", {summary.git_unresolved} git-ignore status unresolved"
    if summary.unhandled_formats:
        total_unhandled = sum(summary.unhandled_formats.values())
        breakdown = ", ".join(
            f"{suffix}: {count}"
            for suffix, count in sorted(summary.unhandled_formats.items())
        )
        line += f", {total_unhandled} unhandled format(s) ({breakdown})"
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


def _format_receipt_reference(result) -> str:
    if not result.receipt_ids:
        return "No evidence was receipted for this answer."
    timestamp = min(receipt_id.retrieval_timestamp for receipt_id in result.receipt_ids)
    return (
        f"{len(result.receipt_ids)} evidence item(s) receipted "
        f"at {timestamp.isoformat()}"
    )


def _print_answer(result) -> None:
    print(f"Q: {result.question}")
    print()

    if result.is_absent:
        absence = result.absence
        print(f"A: [{absence.kind.value}] {absence.detail or 'No answer available.'}")
        if absence.kind is AbsenceKind.NOT_FOUND:
            print(f"    searched projects: {', '.join(absence.searched_projects)}")
        elif absence.kind is AbsenceKind.INACCESSIBLE:
            print(
                f"    withheld: {absence.withheld_count} item(s) denied by permissions"
            )
        print()
        print(f"Confidence: {result.confidence.value}")
        print(_format_receipt_reference(result))
        return

    if result.prose:
        print(result.prose)
    else:
        for index, claim in enumerate(result.claims, start=1):
            print(f"[{index}] {claim.text}")
    print()

    print(f"Confidence: {result.confidence.value}")
    print()

    print("Citations:")
    for index, claim in enumerate(result.claims, start=1):
        for citation in claim.citations:
            label = (
                citation.title
                or citation.source_locator.label
                or citation.source_locator.uri
            )
            print(f"  [{index}] {label} — {citation.source_locator.uri}")

    if result.conflicts:
        print()
        print("Conflicts:")
        for conflict in result.conflicts:
            print(f"  - {conflict.left.claim.text!r}")
            print(f"    vs {conflict.right.claim.text!r}")
            print(
                f"    newer: {conflict.newer.value}; "
                f"more authoritative: {conflict.more_authoritative.value}"
            )

    if result.evidence_omitted:
        print()
        print(
            f"{len(result.evidence_omitted)} additional evidence item(s) "
            "considered, not used."
        )

    print()
    print(_format_receipt_reference(result))


def cmd_ask(args: argparse.Namespace) -> int:
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

    db_path = _resolve_database_path(config_path, raw_config, args.database)
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
            result = compute_answer(
                repository,
                args.question,
                principal=principal,
                project=args.project,
                top_k=args.top_k,
            )
    except MissingPrincipalError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2

    _print_answer(result)
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
    sync_parser.add_argument(
        "--workspace-root",
        help=(
            "Resolve relative source-root paths against this directory "
            "(overrides workspace_root in the config)."
        ),
    )
    sync_parser.add_argument(
        "--database",
        help="Write the synchronized SQLite projection to this path.",
    )
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

    ask_parser = subparsers.add_parser(
        "ask",
        help=(
            "Ask a question and receive a synthesized, cited answer over "
            "governed evidence (deterministic, offline synthesis)."
        ),
    )
    ask_parser.add_argument("question", help="Question text.")
    ask_parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=f"Project to search (default: {DEFAULT_PROJECT}).",
    )
    ask_parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        dest="top_k",
        help="Maximum evidence items to consider.",
    )
    ask_parser.add_argument(
        "--principal",
        default=None,
        help=(
            "Principal to ask as (default: the configured owner, "
            "then lee@leebase.com)."
        ),
    )
    ask_parser.add_argument("--config", help=config_help)
    ask_parser.add_argument(
        "--database",
        help="Read the synchronized SQLite projection from this path.",
    )
    ask_parser.set_defaults(func=cmd_ask)

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
