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
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .answer import answer as compute_answer
from .answer_contracts import AbsenceKind
from .chunking import chunk_document
from .connectors.base import (
    Connector,
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
from .connectors.outlook import OutlookConnector, OutlookScope
from .connectors.outlook_graph import GraphOutlookTransport
from .contracts import (
    DEFAULT_PROJECT,
    Authority,
    ChangeType,
    KnowledgeItem,
    KnowledgeItemId,
    Principal,
    Trust,
)
from .governance import MissingPrincipalError
from .governance import retrieve as governed_retrieve
from .microsoft_graph import (
    CredentialError,
    GraphClient,
    GraphCredential,
    GraphError,
    MicrosoftAccount,
    OAuthTokenManager,
    UrllibHttpTransport,
)
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

# Optional Microsoft Graph delegated Outlook configuration.  Tokens are kept
# in the OS secret service, never in this file.
#
# [microsoft_graph]
# client_id = "public-native-app-client-id"
# tenant = "common"
# scopes = ["Mail.Read", "User.Read"]
#
# [microsoft_graph.accounts.personal]
# user_id = "lee@example.com"
#
# [outlook.inbox]
# account = "personal"
# folder_id = "inbox-folder-id"
# folder_name = "Inbox"
# project = "default"
"""


@dataclass
class SyncSummary:
    """Counts of what one sync pass did, for a concise CLI report.

    A document that a user expects to be searchable must never disappear
    without a count: every candidate the sync did not index shows up in
    exactly one of ``skipped``, ``skipped_token_content``, ``git_ignored``,
    ``git_unresolved``, ``unhandled_formats``, or the Office scope/exclusion
    buckets.
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
    #: Office files explicitly outside an affected root's include scope.
    out_of_scope_formats: dict[str, int] = field(default_factory=dict)
    #: Office files explicitly protected by a global or root exclusion.
    excluded_formats: dict[str, int] = field(default_factory=dict)
    #: Safe parser/read classifications, keyed by their public value.
    failure_counts: dict[str, int] = field(default_factory=dict)
    #: Candidates owned by a more specific overlapping root during a scoped
    #: discovery pass.
    claimed_by_other_root: dict[str, int] = field(default_factory=dict)


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
    protected_source_object_ids: frozenset[str] = frozenset(),
    protected_source_prefixes: tuple[str, ...] = (),
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
        if source_object_id in protected_source_object_ids or any(
            source_object_id.startswith(prefix) for prefix in protected_source_prefixes
        ):
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
        protected_source_object_ids=frozenset(
            failure.source_object_id for failure in report.failures
        ),
        protected_source_prefixes=report.blocked_source_prefixes,
    )

    summary = SyncSummary(
        out_of_scope_formats=dict(report.out_of_scope_formats),
        excluded_formats=dict(report.excluded_formats),
        claimed_by_other_root=dict(report.claimed_by_other_root),
    )
    for failure in report.failures:
        summary.skipped += 1
        summary.failure_counts[failure.kind.value] = (
            summary.failure_counts.get(failure.kind.value, 0) + 1
        )
        summary.skipped_objects += (
            f"{failure.source_object_id} [{failure.kind.value}]",
        )
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
            summary.failure_counts[error.kind.value] = (
                summary.failure_counts.get(error.kind.value, 0) + 1
            )
            summary.skipped_objects += (
                f"{change.source_object_id} [{error.kind.value}]",
            )
            continue

        if contains_token_shaped_secret(document.content) or (
            document.title is not None and contains_token_shaped_secret(document.title)
        ):
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


def _sync_external_connector(
    connector: Connector,
    repository: SQLiteRepository,
    *,
    sync_timestamp: datetime,
) -> SyncSummary:
    """Synchronize a native-delta connector through the common repository.

    The connector computes the complete pending pass; this function prepares
    every fetch before writing anything, checkpoints only after all reads have
    succeeded, and uses the final item/tombstone transaction for non-empty
    rounds.  Empty rounds use the repository's atomic cursor-only capability.
    """
    previous_cursor = repository.get_connector_cursor(connector.connector_id)
    changes = connector.list_changes(previous_cursor)
    objects = connector.discover()
    summary = SyncSummary()
    prepared: list[tuple[ObjectChange, KnowledgeItem | None, tuple]] = []
    blocked = False

    for change in changes:
        if change.change_type is ChangeType.DELETED:
            prepared.append((change, None, ()))
            continue
        try:
            document = connector.fetch(change.source_object_id)
            permissions = connector.permissions(change.source_object_id)
        except ConnectorReadError as error:
            summary.skipped += 1
            summary.failure_counts[error.kind.value] = (
                summary.failure_counts.get(error.kind.value, 0) + 1
            )
            summary.skipped_objects += (
                f"{change.source_object_id} [{error.kind.value}]",
            )
            continue
        if contains_token_shaped_secret(document.content) or (
            document.title is not None and contains_token_shaped_secret(document.title)
        ):
            summary.skipped_token_content += 1
            blocked = True
            continue
        item_id = KnowledgeItemId(connector.connector_id, document.source_object_id)
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
        prepared.append((change, item, chunks))

    if summary.skipped or blocked:
        # Do not ask the connector for a checkpoint: a hardened connector keeps
        # the failed source in its pending pass and rejects advancement.
        summary.unchanged = max(
            0,
            len(objects)
            - summary.created
            - summary.updated
            - summary.skipped
            - summary.skipped_token_content,
        )
        return summary

    cursor = connector.checkpoint(objects)
    if not prepared:
        repository.advance_cursor(
            connector.connector_id,
            cursor,
            updated_at=sync_timestamp,
            project=getattr(connector, "project", DEFAULT_PROJECT),
        )
    else:
        operations = []
        for change, item, chunks in prepared:
            item_id = KnowledgeItemId(connector.connector_id, change.source_object_id)
            if change.change_type is not ChangeType.DELETED and item is None:
                raise RuntimeError("prepared external change lost its item")
            operations.append((item_id, item, chunks))
        repository.apply_external_round(
            operations,
            cursor=cursor,
            updated_at=sync_timestamp,
        )
        for change, _item, _chunks in prepared:
            if change.change_type is ChangeType.DELETED:
                summary.deleted += 1
            elif change.change_type is ChangeType.CREATED:
                summary.created += 1
            else:
                summary.updated += 1
    summary.unchanged = max(
        0,
        len(objects) - summary.created - summary.updated - summary.skipped,
    )
    return summary


def _graph_credential(
    raw_config: dict, account_id: str | None = None
) -> GraphCredential:
    section = raw_config.get("microsoft_graph")
    if not isinstance(section, dict):
        raise ConnectorConfigError(
            "configuration must declare [microsoft_graph] for Outlook sync"
        )
    selected_id = account_id or section.get("account_id") or "default"
    if not isinstance(selected_id, str) or not selected_id.strip():
        raise ConnectorConfigError("Microsoft Graph account_id must be non-empty")
    accounts = section.get("accounts", {})
    if not isinstance(accounts, dict):
        raise ConnectorConfigError("microsoft_graph.accounts must be a table")
    account_section = accounts.get(selected_id, {})
    if not isinstance(account_section, dict):
        raise ConnectorConfigError("Microsoft Graph account configuration is invalid")
    client_id = account_section.get("client_id", section.get("client_id"))
    user_id = account_section.get(
        "user_id", section.get("user_id", raw_config.get("owner"))
    )
    tenant = account_section.get("tenant", section.get("tenant", "common"))
    scopes = account_section.get(
        "scopes", section.get("scopes", ["Mail.Read", "User.Read"])
    )
    if not isinstance(client_id, str) or not client_id.strip():
        raise ConnectorConfigError("microsoft_graph.client_id is required")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ConnectorConfigError(
            "Microsoft Graph account user_id is required to bind the token"
        )
    if not isinstance(tenant, str) or not tenant.strip():
        raise ConnectorConfigError("Microsoft Graph tenant is required")
    if not isinstance(scopes, list) or not all(
        isinstance(scope, str) and scope.strip() for scope in scopes
    ):
        raise ConnectorConfigError("Microsoft Graph scopes must be a string array")
    try:
        return GraphCredential(
            MicrosoftAccount(
                account_id=selected_id,
                user_id=user_id,
                tenant=tenant,
            ),
            client_id=client_id,
            scopes=tuple(scopes),
        )
    except (TypeError, ValueError) as error:
        raise ConnectorConfigError(
            "Microsoft Graph account configuration is invalid"
        ) from error


def _graph_runtime(
    raw_config: dict, account_id: str | None = None
) -> tuple[GraphCredential, GraphClient]:
    credential = _graph_credential(raw_config, account_id)
    scope_names = {scope.casefold() for scope in credential.scopes}
    if scope_names != {"mail.read", "user.read"}:
        raise ConnectorConfigError(
            "the current Microsoft Graph CLI requires exactly Mail.Read and User.Read"
        )
    section = raw_config["microsoft_graph"]
    try:
        minimum_interval = float(section.get("minimum_request_interval", 0.0))
    except (TypeError, ValueError) as error:
        raise ConnectorConfigError(
            "microsoft_graph.minimum_request_interval must be numeric"
        ) from error
    from .microsoft_graph import SpacingRateLimiter

    http = UrllibHttpTransport()
    tokens = OAuthTokenManager(credential, transport=http)
    client = GraphClient(
        credential,
        token_manager=tokens,
        http=http,
        rate_limiter=SpacingRateLimiter(minimum_interval),
    )
    return credential, client


def _outlook_connector_from_config(
    raw_config: dict,
    source_name: str,
) -> tuple[OutlookConnector, GraphClient]:
    section = raw_config.get("outlook")
    if not isinstance(section, dict):
        raise ConnectorConfigError(
            "configuration must declare [outlook.<source>] for Outlook sync"
        )
    source = section.get(source_name)
    if not isinstance(source, dict):
        raise ConnectorConfigError(f"unknown Outlook source {source_name!r}")
    account_id = source.get("account")
    if account_id is not None and not isinstance(account_id, str):
        raise ConnectorConfigError("outlook source account must be a string")
    credential, client = _graph_runtime(raw_config, account_id)
    scope_names = {scope.casefold() for scope in credential.scopes}
    if "mail.read" not in scope_names:
        raise ConnectorConfigError("Outlook requires the delegated Mail.Read scope")
    if "user.read" not in scope_names:
        raise ConnectorConfigError(
            "Outlook requires User.Read to verify the delegated account identity"
        )
    if scope_names.difference({"mail.read", "user.read"}):
        raise ConnectorConfigError(
            "Outlook configuration requests a scope outside its read-only boundary"
        )
    folder_id = source.get("folder_id")
    if not isinstance(folder_id, str) or not folder_id.strip():
        raise ConnectorConfigError("outlook source folder_id is required")
    folder_name = source.get("folder_name")
    configured_owner = source.get("mailbox_owner")
    if configured_owner is not None and (
        not isinstance(configured_owner, str)
        or configured_owner.casefold() != credential.account.user_id.casefold()
    ):
        raise ConnectorConfigError(
            "outlook mailbox_owner must match the verified Graph account user_id"
        )
    mailbox_owner = credential.account.user_id
    project = source.get("project", DEFAULT_PROJECT)
    if source.get("connector_id") is not None:
        raise ConnectorConfigError(
            "outlook connector_id is derived from the account and folder scope"
        )
    try:
        scope = OutlookScope(
            mailbox_owner=mailbox_owner,
            folder_id=folder_id,
            folder_name=folder_name,
            project=project,
            authority=Authority(source.get("authority", Authority.CANONICAL.value)),
            trust=Trust(source.get("trust", Trust.HUMAN_AUTHORED.value)),
            account_id=credential.account.account_id,
            tenant=credential.account.tenant,
            credential_binding=credential.binding,
        )
        transport = GraphOutlookTransport(client)
        connector = OutlookConnector(
            scope,
            transport,
        )
    except (TypeError, ValueError) as error:
        raise ConnectorConfigError("Outlook source configuration is invalid") from error
    return connector, client


def _print_sync_summary(
    connector_name: str,
    scope: str,
    summary: SyncSummary,
) -> None:
    line = (
        f"Synced {connector_name}{scope}: {summary.created} created, "
        f"{summary.updated} updated, {summary.deleted} deleted, "
        f"{summary.unchanged} unchanged"
    )
    if summary.skipped:
        if summary.failure_counts:
            breakdown = ", ".join(
                f"{kind}: {count}"
                for kind, count in sorted(summary.failure_counts.items())
            )
            line += f", {summary.skipped} skipped ({breakdown})"
        else:
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
    if summary.out_of_scope_formats:
        total_out_of_scope = sum(summary.out_of_scope_formats.values())
        breakdown = ", ".join(
            f"{suffix}: {count}"
            for suffix, count in sorted(summary.out_of_scope_formats.items())
        )
        line += (
            f", {total_out_of_scope} Office file(s) outside include scope "
            f"({breakdown})"
        )
    if summary.excluded_formats:
        total_excluded = sum(summary.excluded_formats.values())
        breakdown = ", ".join(
            f"{suffix}: {count}"
            for suffix, count in sorted(summary.excluded_formats.items())
        )
        line += f", {total_excluded} excluded Office file(s) ({breakdown})"
    if summary.claimed_by_other_root:
        total_claimed = sum(summary.claimed_by_other_root.values())
        breakdown = ", ".join(
            f"{root}: {count}"
            for root, count in sorted(summary.claimed_by_other_root.items())
        )
        line += f", {total_claimed} claimed by other root(s) ({breakdown})"
    print(line)
    for note in summary.skipped_objects:
        print(f"lee-kb: skipped {note}", file=sys.stderr)


def _cmd_sync_outlook(
    args: argparse.Namespace, config_path: Path, raw_config: dict
) -> int:
    if args.source is None:
        print("lee-kb: Outlook sync requires a configured source name", file=sys.stderr)
        return 2
    try:
        connector, _client = _outlook_connector_from_config(raw_config, args.source)
        status = connector.health()
        if not status.healthy:
            print(f"lee-kb: Outlook sync refused: {status.detail}", file=sys.stderr)
            return 1
        db_path = _resolve_database_path(config_path, raw_config, args.database)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with SQLiteRepository(db_path) as repository:
            summary = _sync_external_connector(
                connector,
                repository,
                sync_timestamp=datetime.now(timezone.utc),
            )
    except (ConnectorConfigError, ConnectorReadError, RuntimeError) as error:
        print(f"lee-kb: Outlook sync failed: {error}", file=sys.stderr)
        return 1
    _print_sync_summary("outlook", f" ({args.source})", summary)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    config_path = resolve_config_path(args.config)
    try:
        raw_config = _load_raw_config(config_path)
    except ConnectorConfigError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2

    connector_name = args.connector or "local_files"
    if connector_name == "outlook":
        return _cmd_sync_outlook(args, config_path, raw_config)
    try:
        roots = load_config(config_path, workspace_root=args.workspace_root)
    except ConnectorConfigError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2
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
    _print_sync_summary(connector_name, scope, summary)
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
        if result.withheld_count:
            print(
                f"    withheld: {result.withheld_count} item(s) denied by permissions"
            )
        if result.truncated:
            print("    more evidence was available than --top-k allowed")
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
    if result.withheld_count:
        print()
        print(f"{result.withheld_count} additional result(s) withheld by permissions.")
    if result.truncated:
        print()
        print("More evidence was available than --top-k allowed.")

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
                project_has_synchronized_content=repository.has_synchronized_project(
                    args.project
                ),
                allow_provider_failure=True,
            )
    except MissingPrincipalError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2

    _print_answer(result)
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    config_path = resolve_config_path(args.config)
    try:
        raw_config = _load_raw_config(config_path)
        credential, client = _graph_runtime(raw_config, args.account)
        token_manager = client.token_manager
        if not isinstance(token_manager, OAuthTokenManager):
            raise ConnectorConfigError("Graph client token manager is invalid")
        if args.auth_action == "revoke":
            token_manager.revoke()
            print(
                "Revoked local Microsoft Graph token for "
                f"{credential.account.account_id}."
            )
            return 0

        def show_device_code(device) -> None:
            print(device.message)
            print(f"Open {device.verification_uri} and enter code {device.user_code}.")

        client.login(on_device_code=show_device_code)
        print(f"Authenticated Microsoft Graph account {credential.account.account_id}.")
        return 0
    except (ConnectorConfigError, CredentialError, GraphError, RuntimeError) as error:
        print(f"lee-kb: Microsoft authentication failed: {error}", file=sys.stderr)
        return 1


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

    auth_parser = subparsers.add_parser(
        "auth", help="Authenticate or revoke a local Microsoft Graph account."
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_action")
    auth_subparsers.required = True
    auth_login_parser = auth_subparsers.add_parser(
        "login", help="Sign in with the Microsoft device authorization flow."
    )
    auth_login_parser.add_argument("--account", default=None)
    auth_login_parser.add_argument("--config", help=config_help)
    auth_login_parser.set_defaults(func=cmd_auth)
    auth_revoke_parser = auth_subparsers.add_parser(
        "revoke", help="Delete the local Microsoft token for an account."
    )
    auth_revoke_parser.add_argument("--account", default=None)
    auth_revoke_parser.add_argument("--config", help=config_help)
    auth_revoke_parser.set_defaults(func=cmd_auth)

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
