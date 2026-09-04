"""Command-line entry point for Lee Knowledge Base.

Version 1 synchronization is explicitly user-driven (``lee-kb sync``).
``lee-kb search`` calls the governed :func:`lee_kb.governance.retrieve`
surface directly and prints ranked evidence with citations, freshness, and
receipt identifiers -- no synthesis. ``lee-kb ask`` layers claim assembly and
deterministic, offline synthesis on top of the same governed surface via
:func:`lee_kb.answer.answer`; see :mod:`lee_kb.answer` and
``docs/answer-architecture.md`` for the pipeline. Neither command has an
LLM dependency in this release.

``lee-kb access`` provisions the server-owned access plane -- employee
principals, client credentials, bounded knowledge grants, and access audit
evidence -- for authenticated multi-principal transports.  It is operator
state only: no flag on any command can widen a principal's tenant, lane,
scope, or purpose.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sqlite3
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .access import (
    AccessError,
    AccessRegistry,
    AuthorizationError,
    EmployeeIdentity,
    KnowledgeGrant,
    KnowledgePolicy,
)
from .access_store import (
    clients_path_for,
    load_policy,
    policy_path_for,
    save_policy,
)
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
from .connectors.calendar import CalendarConnector, CalendarScope
from .connectors.calendar_graph import GraphCalendarTransport
from .connectors.local_files import (
    LocalFilesConnector,
    contains_token_shaped_secret,
    load_config,
)
from .connectors.outlook import OutlookConnector, OutlookScope
from .connectors.outlook_graph import GraphOutlookTransport
from .contracts import (
    DEFAULT_PROJECT,
    WHOLE_ROOT_PATH_PREFIX,
    Authority,
    ChangeType,
    KnowledgeItem,
    KnowledgeItemId,
    MemoryConfidence,
    MemoryType,
    Principal,
    PrincipalType,
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
            memory_type=document.memory_type,
            subject_principal=document.subject_principal,
            memory_confidence=document.memory_confidence,
            importance=document.importance,
            memory_formed_at=document.memory_formed_at,
            superseded_by=document.superseded_by,
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

    # A changed source-owner grant (e.g. a root's allowed_principals) must
    # reach content-unchanged records too, mirroring the external path.
    changed_source_ids = {change.source_object_id for change in changes}
    failed_source_ids = {failure.source_object_id for failure in report.failures}
    for source_object in report.objects:
        if (
            source_object.source_object_id in changed_source_ids
            or source_object.source_object_id in failed_source_ids
        ):
            continue
        repository.sync_permissions(
            KnowledgeItemId(connector.connector_id, source_object.source_object_id),
            connector.permissions(source_object.source_object_id),
        )
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
            # Exclude the changed document from the projection while allowing
            # the completed delta round to advance. A tombstone removes any
            # previously indexed safe version of the same source object.
            prepared.append((change, None, ()))
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
            memory_type=document.memory_type,
            subject_principal=document.subject_principal,
            memory_confidence=document.memory_confidence,
            importance=document.importance,
            memory_formed_at=document.memory_formed_at,
            superseded_by=document.superseded_by,
        )
        chunks = chunk_document(
            document.content,
            item_id=item_id,
            project=document.project,
            document_type=document.document_type,
        )
        prepared.append((change, item, chunks))

    if summary.skipped:
        # Ordinary fetch failures leave the source in the connector's pending
        # pass, so do not request a checkpoint or persist partial operations.
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
            operations.append((item_id, item, chunks))
        entries = repository.apply_external_round(
            operations,
            cursor=cursor,
            updated_at=sync_timestamp,
        )
        for (change, item, _chunks), entry in zip(prepared, entries, strict=True):
            if change.change_type is ChangeType.DELETED:
                summary.deleted += 1
            elif item is None:
                if entry is not None:
                    summary.deleted += 1
            elif change.change_type is ChangeType.CREATED:
                summary.created += 1
            else:
                summary.updated += 1
    changed_source_ids = {change.source_object_id for change in changes}
    for source_object in objects:
        if source_object.source_object_id in changed_source_ids:
            continue
        item_id = KnowledgeItemId(
            connector.connector_id,
            source_object.source_object_id,
        )
        permissions = connector.permissions(source_object.source_object_id)
        try:
            repository.sync_permissions(item_id, permissions)
        except KeyError:
            # The connector cursor deliberately retains metadata for content
            # excluded by the token gate; absent and tombstoned items have no
            # live projection whose permissions should be refreshed.
            continue
    summary.unchanged = max(
        0,
        len(objects)
        - summary.created
        - summary.updated
        - summary.skipped
        - summary.skipped_token_content,
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
    allowed_scope_sets = (
        {"mail.read", "user.read"},
        {"calendars.read", "user.read"},
    )
    if scope_names not in allowed_scope_sets:
        raise ConnectorConfigError(
            "the current Microsoft Graph CLI requires exactly User.Read plus "
            "one read-only resource scope: Mail.Read or Calendars.Read"
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
    allowed_principals = source.get("allowed_principals", [])
    if not isinstance(allowed_principals, list) or not all(
        isinstance(principal, str) and principal.strip()
        for principal in allowed_principals
    ):
        raise ConnectorConfigError(
            "outlook source allowed_principals must be a string array"
        )
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
            allowed_principals=tuple(allowed_principals),
        )
        transport = GraphOutlookTransport(client)
        connector = OutlookConnector(
            scope,
            transport,
        )
    except (TypeError, ValueError) as error:
        raise ConnectorConfigError("Outlook source configuration is invalid") from error
    return connector, client


def _calendar_connector_from_config(
    raw_config: dict,
    source_name: str,
) -> tuple[CalendarConnector, GraphClient]:
    section = raw_config.get("calendar")
    if not isinstance(section, dict):
        raise ConnectorConfigError(
            "configuration must declare [calendar.<source>] for calendar sync"
        )
    source = section.get(source_name)
    if not isinstance(source, dict):
        raise ConnectorConfigError(f"unknown calendar source {source_name!r}")
    account_id = source.get("account")
    if account_id is not None and not isinstance(account_id, str):
        raise ConnectorConfigError("calendar source account must be a string")
    credential, client = _graph_runtime(raw_config, account_id)
    scope_names = {scope.casefold() for scope in credential.scopes}
    if scope_names != {"calendars.read", "user.read"}:
        raise ConnectorConfigError(
            "calendar sync requires exactly Calendars.Read and User.Read"
        )
    calendar_id = source.get("calendar_id")
    if not isinstance(calendar_id, str) or not calendar_id.strip():
        raise ConnectorConfigError("calendar source calendar_id is required")
    allowed_principals = source.get("allowed_principals", [])
    if not isinstance(allowed_principals, list) or not all(
        isinstance(principal, str) and principal.strip()
        for principal in allowed_principals
    ):
        raise ConnectorConfigError(
            "calendar source allowed_principals must be a string array"
        )
    configured_owner = source.get("owner")
    if configured_owner is not None and (
        not isinstance(configured_owner, str)
        or configured_owner.casefold() != credential.account.user_id.casefold()
    ):
        raise ConnectorConfigError(
            "calendar owner must match the verified Graph account user_id"
        )
    start_value = source.get("start")
    end_value = source.get("end")
    if not isinstance(start_value, str) or not isinstance(end_value, str):
        raise ConnectorConfigError(
            "calendar source start and end must be fixed ISO-8601 timestamps"
        )
    try:
        start = datetime.fromisoformat(start_value)
        end = datetime.fromisoformat(end_value)
        scope = CalendarScope(
            owner=credential.account.user_id,
            calendar_id=calendar_id,
            calendar_name=source.get("calendar_name"),
            start=start,
            end=end,
            project=source.get("project", DEFAULT_PROJECT),
            authority=Authority(source.get("authority", Authority.CANONICAL.value)),
            trust=Trust(source.get("trust", Trust.HUMAN_AUTHORED.value)),
            account_id=credential.account.account_id,
            tenant=credential.account.tenant,
            credential_binding=credential.binding,
            allowed_principals=tuple(allowed_principals),
        )
        connector = CalendarConnector(scope, GraphCalendarTransport(client))
    except (TypeError, ValueError) as error:
        raise ConnectorConfigError(
            "calendar source configuration is invalid"
        ) from error
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
            f", {total_out_of_scope} Office file(s) outside include scope ({breakdown})"
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


def _cmd_sync_calendar(
    args: argparse.Namespace, config_path: Path, raw_config: dict
) -> int:
    if args.source is None:
        print(
            "lee-kb: calendar sync requires a configured source name",
            file=sys.stderr,
        )
        return 2
    try:
        connector, _client = _calendar_connector_from_config(raw_config, args.source)
        status = connector.health()
        if not status.healthy:
            print(f"lee-kb: calendar sync refused: {status.detail}", file=sys.stderr)
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
        print(f"lee-kb: calendar sync failed: {error}", file=sys.stderr)
        return 1
    _print_sync_summary("calendar", f" ({args.source})", summary)
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
    if connector_name == "calendar":
        return _cmd_sync_calendar(args, config_path, raw_config)
    try:
        roots = load_config(config_path, workspace_root=args.workspace_root)
    except ConnectorConfigError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2
    if connector_name != "local_files":
        print(
            f"lee-kb: unknown connector {connector_name!r}; "
            "available connectors: 'local_files', 'outlook', 'calendar'",
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


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "memory"


_MEMORY_TYPE_BY_VALUE = {member.value: member for member in MemoryType}
_MEMORY_CONFIDENCE_BY_VALUE = {member.value: member for member in MemoryConfidence}


def cmd_remember(args: argparse.Namespace) -> int:
    """Write one durable memory record into a configured local_files root.

    A memory is an ordinary markdown file with a small frontmatter block
    (parsed by ``connectors.local_files.parse_memory_frontmatter``), synced
    through the same crawl-diff pipeline as every other document -- this
    command only structures the write and drives an immediate, scoped
    resync so the memory is queryable right away rather than waiting for
    the next scheduled ``lee-kb sync``.
    """
    config_path = resolve_config_path(args.config)
    try:
        raw_config = _load_raw_config(config_path)
        roots = load_config(config_path, workspace_root=args.workspace_root)
    except ConnectorConfigError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2

    root = next((candidate for candidate in roots if candidate.name == args.root), None)
    if root is None:
        configured = ", ".join(sorted(candidate.name for candidate in roots)) or "(none)"
        print(
            f"lee-kb: unknown root {args.root!r}; configured roots: {configured}",
            file=sys.stderr,
        )
        return 2

    memory_type = _MEMORY_TYPE_BY_VALUE.get(args.memory_type)
    if memory_type is None:
        allowed = ", ".join(sorted(_MEMORY_TYPE_BY_VALUE))
        print(f"lee-kb: --memory-type must be one of: {allowed}", file=sys.stderr)
        return 2

    confidence = MemoryConfidence.OBSERVED
    if args.confidence is not None:
        resolved = _MEMORY_CONFIDENCE_BY_VALUE.get(args.confidence)
        if resolved is None:
            allowed = ", ".join(sorted(_MEMORY_CONFIDENCE_BY_VALUE))
            print(f"lee-kb: --confidence must be one of: {allowed}", file=sys.stderr)
            return 2
        confidence = resolved

    if not (0.0 <= args.importance <= 1.0):
        print("lee-kb: --importance must be between 0.0 and 1.0", file=sys.stderr)
        return 2

    if args.content_file:
        content = Path(args.content_file).expanduser().read_text(encoding="utf-8")
    elif args.content:
        content = args.content
    else:
        print("lee-kb: one of --content or --content-file is required", file=sys.stderr)
        return 2
    content = content.strip()
    if not content:
        print("lee-kb: memory content must not be empty", file=sys.stderr)
        return 2

    if contains_token_shaped_secret(content) or contains_token_shaped_secret(args.title):
        print(
            "lee-kb: refusing to remember content that looks like it contains a "
            "credential",
            file=sys.stderr,
        )
        return 2

    formed_at = args.formed_at or (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    lines = [
        "---",
        f"memory_type: {memory_type.value}",
        f"subject_principal: {args.subject_principal}",
        f"confidence: {confidence.value}",
        f"importance: {args.importance}",
        f"formed_at: {formed_at}",
    ]
    if args.superseded_by:
        lines.append(f"superseded_by: {args.superseded_by}")
    if args.visibility:
        lines.append(f"visibility: {args.visibility}")
    if args.allowed_principals:
        lines.append(f"allowed_principals: {args.allowed_principals}")
    lines.append("---")
    frontmatter = "\n".join(lines)
    body = f"\n# {args.title}\n\n{content}\n"

    slug = args.slug or _slugify(args.title)
    relative = f"{memory_type.value}/{slug}.md"
    file_path = root.path / relative
    if file_path.exists() and not args.overwrite:
        print(
            f"lee-kb: {file_path} already exists; pass --overwrite to replace it "
            "or --slug to choose a different name",
            file=sys.stderr,
        )
        return 1
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(frontmatter + "\n" + body, encoding="utf-8")

    connector = LocalFilesConnector(roots, connector_id="local_files")
    db_path = _resolve_database_path(config_path, raw_config, args.database)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with SQLiteRepository(db_path) as repository:
            summary = _sync_connector(
                connector,
                repository,
                root_filter=args.root,
                sync_timestamp=datetime.now(timezone.utc),
            )
    except (ConnectorReadError, RuntimeError) as error:
        print(
            f"lee-kb: wrote {file_path} but sync failed: {error}", file=sys.stderr
        )
        return 1

    item_id = f"local_files:{args.root}:{relative}"
    print(f"Remembered: {file_path}")
    print(f"  item_id: {item_id}")
    print(
        f"  memory_type={memory_type.value} subject_principal={args.subject_principal} "
        f"confidence={confidence.value} importance={args.importance}"
    )
    _print_sync_summary("local_files", f" ({args.root})", summary)
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    """Remove a memory's source file and drive the tombstone that follows.

    Deletes the file (git history and, once committed, the working tree
    diff remain the audit trail) and re-syncs just its root, so the
    connector's own create/update/delete diff -- the exact path an
    ordinary file removal already takes -- calls
    ``repository.tombstone_item()``. No new persistence path: forgetting
    reuses the same soft-delete lee-kb already has for every source.
    """
    config_path = resolve_config_path(args.config)
    try:
        raw_config = _load_raw_config(config_path)
        roots = load_config(config_path, workspace_root=args.workspace_root)
    except ConnectorConfigError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2

    if ":" not in args.item_id:
        print(
            "lee-kb: --item-id must be '<connector_id>:<root>:<relative path>'",
            file=sys.stderr,
        )
        return 2
    connector_id, source_object_id = args.item_id.split(":", 1)
    if connector_id != "local_files":
        print(
            f"lee-kb: forget only supports local_files memory items, got "
            f"{connector_id!r}",
            file=sys.stderr,
        )
        return 2
    if ":" not in source_object_id:
        print(
            "lee-kb: --item-id must be '<connector_id>:<root>:<relative path>'",
            file=sys.stderr,
        )
        return 2
    root_name, relative = source_object_id.split(":", 1)
    root = next((candidate for candidate in roots if candidate.name == root_name), None)
    if root is None:
        print(f"lee-kb: unknown root {root_name!r} in --item-id", file=sys.stderr)
        return 2

    root_base = root.path.resolve()
    file_path = (root_base / relative).resolve()
    if file_path != root_base and root_base not in file_path.parents:
        print(f"lee-kb: --item-id escapes its root: {args.item_id!r}", file=sys.stderr)
        return 2
    if file_path.is_file():
        file_path.unlink()
    else:
        print(
            f"lee-kb: {file_path} does not exist on disk; syncing anyway in case "
            "it was already removed",
            file=sys.stderr,
        )

    connector = LocalFilesConnector(roots, connector_id="local_files")
    db_path = _resolve_database_path(config_path, raw_config, args.database)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with SQLiteRepository(db_path) as repository:
            summary = _sync_connector(
                connector,
                repository,
                root_filter=root_name,
                sync_timestamp=datetime.now(timezone.utc),
            )
    except (ConnectorReadError, RuntimeError) as error:
        print(f"lee-kb: forget sync failed: {error}", file=sys.stderr)
        return 1

    if summary.deleted:
        print(
            f"Forgot: {args.item_id} (tombstoned, still audit-visible, excluded "
            "from ordinary recall)"
        )
        return 0
    print(
        f"lee-kb: {args.item_id} was not found live in the projection "
        "(already forgotten, or never synchronized)",
        file=sys.stderr,
    )
    return 1


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
        with SQLiteRepository(db_path, initialize_schema=False) as repository:
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
    except sqlite3.OperationalError as error:
        if "readonly" not in str(error).lower():
            raise
        print(
            "lee-kb: retrieval requires write access to persist durable "
            "receipts and the query audit event; the projection is read-only",
            file=sys.stderr,
        )
        return 1

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


def _format_freshness(result) -> str:
    if result.freshness is None:
        return "Freshness: unavailable (retrieval did not complete)"
    state = "stale" if result.freshness.is_stale else "fresh"
    requirement = (
        "satisfied" if result.freshness.requirement_satisfied else "not satisfied"
    )
    return f"Freshness: {state}; requirement {requirement}"


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
        print(_format_freshness(result))
        print(_format_receipt_reference(result))
        return

    if result.prose:
        print(result.prose)
    else:
        for index, claim in enumerate(result.claims, start=1):
            print(f"[{index}] {claim.text}")
    print()

    print(f"Confidence: {result.confidence.value}")
    print(_format_freshness(result))
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
        with SQLiteRepository(db_path, initialize_schema=False) as repository:
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
    except sqlite3.OperationalError as error:
        if "readonly" not in str(error).lower():
            raise
        print(
            "lee-kb: retrieval requires write access to persist durable "
            "receipts and the query audit event; the projection is read-only",
            file=sys.stderr,
        )
        return 1

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


class _AccessCommandError(RuntimeError):
    """Operator-facing access provisioning failure carrying a CLI exit code."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _access_operations(value: str) -> frozenset[str]:
    operations = frozenset(part.strip() for part in value.split(",") if part.strip())
    if not operations:
        raise _AccessCommandError("--operations must name at least one operation")
    return operations


def _access_expiry(expires_days: int | None) -> datetime | None:
    if expires_days is None:
        return None
    if expires_days < 1:
        raise _AccessCommandError("--expires-days must be at least 1")
    return datetime.now(timezone.utc) + timedelta(days=expires_days)


def _existing_policy_records(
    policy_path: Path,
) -> tuple[tuple[EmployeeIdentity, ...], tuple[KnowledgeGrant, ...]]:
    """Return the persisted records, or empty ones when no policy exists yet."""
    if not policy_path.exists():
        return (), ()
    policy = load_policy(policy_path)
    return policy.employees, policy.grants


def _require_policy(policy_path: Path) -> KnowledgePolicy:
    if not policy_path.exists():
        raise _AccessCommandError(
            f"no access policy found at {policy_path}; "
            "run `lee-kb access employee add` first",
            exit_code=1,
        )
    return load_policy(policy_path)


def _access_employee(policy: KnowledgePolicy, principal_id: str) -> EmployeeIdentity:
    try:
        return policy.employee_for_principal(principal_id)
    except AuthorizationError as error:
        raise _AccessCommandError(
            f"principal {principal_id} is not a configured employee"
        ) from error


def _access_employee_add(args: argparse.Namespace, config_path: Path) -> int:
    policy_path = policy_path_for(config_path)
    employees, grants = _existing_policy_records(policy_path)
    if any(employee.employee_id == args.employee_id for employee in employees):
        raise _AccessCommandError(f"employee {args.employee_id} is already registered")
    if any(employee.principal_id == args.principal for employee in employees):
        raise _AccessCommandError(f"principal {args.principal} is already registered")
    employee = EmployeeIdentity(
        employee_id=args.employee_id,
        principal=Principal(args.principal, PrincipalType.AI_EMPLOYEE),
        tenant=args.tenant,
        lane=args.lane,
        scope_id=args.scope_id,
        purpose=args.purpose,
    )
    policy = KnowledgePolicy(employees=(*employees, employee), grants=grants)
    save_policy(policy_path, policy)
    print(f"Registered employee {employee.employee_id} as {employee.principal_id}.")
    print(f"Policy {policy_path} now hashes to {policy.policy_hash}.")
    return 0


def _access_employee_list(args: argparse.Namespace, config_path: Path) -> int:
    policy = _require_policy(policy_path_for(config_path))
    for employee in policy.employees:
        print(
            f"{employee.employee_id}  principal={employee.principal_id}  "
            f"type={employee.principal.principal_type.value}  "
            f"tenant={employee.tenant}  lane={employee.lane}  "
            f"scope={employee.scope_id}  purpose={employee.purpose}"
        )
    return 0


def _access_client_register(args: argparse.Namespace, config_path: Path) -> int:
    policy = _require_policy(policy_path_for(config_path))
    employee = _access_employee(policy, args.principal)
    expires_at = _access_expiry(args.expires_days)
    registry = AccessRegistry(policy, state_path=clients_path_for(config_path))
    credential = registry.register_client(
        employee.principal_id, client_id=args.client_id, expires_at=expires_at
    )
    print(f"client_id: {credential.client_id}")
    print(f"principal: {credential.principal_id}")
    print(f"expires_at: {credential.expires_at.isoformat()}")
    print("Save this secret now: it is shown once and is never stored.")
    print(f"client_secret: {credential.client_secret}")
    return 0


def _access_client_list(args: argparse.Namespace, config_path: Path) -> int:
    policy = _require_policy(policy_path_for(config_path))
    registry = AccessRegistry(policy, state_path=clients_path_for(config_path))
    for info in registry.list_clients():
        state = (
            "active"
            if info.revoked_at is None
            else f"revoked={info.revoked_at.isoformat()}"
        )
        print(
            f"{info.client_id}  principal={info.principal_id}  "
            f"issued={info.issued_at.isoformat()}  "
            f"expires={info.expires_at.isoformat()}  {state}"
        )
    return 0


def _access_client_revoke(args: argparse.Namespace, config_path: Path) -> int:
    policy = _require_policy(policy_path_for(config_path))
    registry = AccessRegistry(policy, state_path=clients_path_for(config_path))
    if not registry.revoke_client(args.client_id):
        raise _AccessCommandError(f"client {args.client_id} is not registered")
    print(f"Revoked client {args.client_id}.")
    return 0


def _access_grant_add(args: argparse.Namespace, config_path: Path) -> int:
    policy_path = policy_path_for(config_path)
    policy = _require_policy(policy_path)
    employee = _access_employee(policy, args.principal)
    grant_id = args.grant_id or (
        f"grant:{employee.employee_id}:{args.project}:{secrets.token_urlsafe(6)}"
    )
    grant = KnowledgeGrant(
        grant_id=grant_id,
        principal_id=employee.principal_id,
        # Tenant, lane, scope, and purpose are copied from the server-owned
        # employee record. No flag can widen a grant beyond that context.
        tenant=employee.tenant,
        lane=employee.lane,
        scope_id=employee.scope_id,
        purpose=employee.purpose,
        project=args.project,
        source_namespace=args.source_namespace,
        root=args.root,
        path_prefix=args.path_prefix,
        operations=_access_operations(args.operations),
        classification=args.classification,
        expires_at=_access_expiry(args.expires_days),
    )
    updated = KnowledgePolicy(
        employees=policy.employees, grants=(*policy.grants, grant)
    )
    save_policy(policy_path, updated)
    print(f"Granted {grant.grant_id} to {grant.principal_id}.")
    print(
        f"Scope: project={grant.project}  source={grant.source_namespace}  "
        f"root={grant.root}  path_prefix={grant.path_prefix}  "
        f"operations={','.join(sorted(grant.operations))}"
    )
    print(
        f"Context: tenant={grant.tenant}  lane={grant.lane}  "
        f"scope={grant.scope_id}  purpose={grant.purpose}"
    )
    return 0


def _access_grant_list(args: argparse.Namespace, config_path: Path) -> int:
    policy = _require_policy(policy_path_for(config_path))
    for grant in policy.grants:
        if args.principal and grant.principal_id != args.principal:
            continue
        state = (
            "active"
            if grant.revoked_at is None
            else f"revoked={grant.revoked_at.isoformat()}"
        )
        expires = "never" if grant.expires_at is None else grant.expires_at.isoformat()
        print(
            f"{grant.grant_id}  principal={grant.principal_id}  "
            f"project={grant.project}  "
            f"source={grant.source_namespace}:{grant.root}/{grant.path_prefix}  "
            f"operations={','.join(sorted(grant.operations))}  "
            f"classification={grant.classification or '-'}  "
            f"expires={expires}  {state}"
        )
    return 0


def _access_grant_revoke(args: argparse.Namespace, config_path: Path) -> int:
    policy_path = policy_path_for(config_path)
    policy = _require_policy(policy_path)
    revoked_at = datetime.now(timezone.utc)
    grants: list[KnowledgeGrant] = []
    found = False
    for grant in policy.grants:
        if grant.grant_id == args.grant_id and grant.revoked_at is None:
            found = True
            grant = replace(grant, revoked_at=revoked_at)
        grants.append(grant)
    if not found:
        known = any(grant.grant_id == args.grant_id for grant in policy.grants)
        raise _AccessCommandError(
            f"grant {args.grant_id} is already revoked"
            if known
            else f"grant {args.grant_id} is not registered"
        )
    updated = KnowledgePolicy(employees=policy.employees, grants=tuple(grants))
    save_policy(policy_path, updated)
    print(f"Revoked grant {args.grant_id} at {revoked_at.isoformat()}.")
    return 0


def _format_access_event(event) -> str:
    principal_id = "-" if event.principal is None else event.principal.principal_id
    return "  ".join(
        (
            event.timestamp.isoformat(),
            event.event_type,
            event.outcome.value,
            f"reason={event.reason_code}",
            f"principal={principal_id}",
            f"client={event.client_id}",
            f"session={event.session_id or '-'}",
            f"project={event.project or '-'}",
            f"grants={','.join(event.grant_ids) or '-'}",
            f"query_digest={event.query_digest or '-'}",
            f"freshness={event.freshness_state or '-'}",
        )
    )


def _access_audit_list(args: argparse.Namespace, config_path: Path) -> int:
    if args.limit < 1:
        raise _AccessCommandError("--limit must be at least 1")
    raw_config: dict = {}
    if config_path.exists():
        raw_config = _load_raw_config(config_path)
    db_path = _resolve_database_path(config_path, raw_config)
    if not db_path.exists():
        raise _AccessCommandError(
            f"no synchronized knowledge found at {db_path}; run `lee-kb sync` first",
            exit_code=1,
        )
    with SQLiteRepository(db_path) as repository:
        events = repository.list_access_events()
    for _event_id, event in events[-args.limit :]:
        print(_format_access_event(event))
    return 0


#: Access provisioning handlers keyed by the resolved sub-subcommand.
_ACCESS_HANDLERS: dict[str, Callable[[argparse.Namespace, Path], int]] = {
    "employee-add": _access_employee_add,
    "employee-list": _access_employee_list,
    "client-register": _access_client_register,
    "client-list": _access_client_list,
    "client-revoke": _access_client_revoke,
    "grant-add": _access_grant_add,
    "grant-list": _access_grant_list,
    "grant-revoke": _access_grant_revoke,
    "audit-list": _access_audit_list,
}


def cmd_access(args: argparse.Namespace) -> int:
    """Provision the server-owned access policy, credentials, and grants."""
    config_path = resolve_config_path(args.config)
    try:
        return _ACCESS_HANDLERS[args.access_action](args, config_path)
    except _AccessCommandError as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return error.exit_code
    except (AccessError, ConnectorConfigError, TypeError, ValueError) as error:
        print(f"lee-kb: {error}", file=sys.stderr)
        return 2


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

    remember_parser = subparsers.add_parser(
        "remember",
        help=(
            "Write one durable memory record into a configured local_files "
            "root and sync it immediately."
        ),
    )
    remember_parser.add_argument(
        "--root", required=True, help="Configured local_files root to write into."
    )
    remember_parser.add_argument(
        "--memory-type",
        required=True,
        dest="memory_type",
        help="One of: preference, relationship, episodic, lesson.",
    )
    remember_parser.add_argument(
        "--subject-principal",
        required=True,
        dest="subject_principal",
        help="Who or what this memory is about (e.g. 'lee').",
    )
    remember_parser.add_argument("--title", required=True, help="Short memory title.")
    remember_parser.add_argument(
        "--content", default=None, help="Memory prose (semantic, not a raw transcript)."
    )
    remember_parser.add_argument(
        "--content-file",
        default=None,
        dest="content_file",
        help="Read memory prose from this file instead of --content.",
    )
    remember_parser.add_argument(
        "--confidence",
        default=None,
        help="One of: stated, observed, inferred, reported, derived (default: observed).",
    )
    remember_parser.add_argument(
        "--importance", type=float, default=0.5, help="0.0-1.0 (default: 0.5)."
    )
    remember_parser.add_argument(
        "--formed-at",
        default=None,
        dest="formed_at",
        help="ISO-8601 formation timestamp (default: now).",
    )
    remember_parser.add_argument(
        "--superseded-by",
        default=None,
        dest="superseded_by",
        help="item_id of the memory this one replaces, if any.",
    )
    remember_parser.add_argument(
        "--visibility",
        default=None,
        help="Override this root's default visibility for this item only.",
    )
    remember_parser.add_argument(
        "--allowed-principals",
        default=None,
        dest="allowed_principals",
        help="Comma-separated principals this memory is explicitly shared with.",
    )
    remember_parser.add_argument(
        "--slug", default=None, help="Explicit filename stem (default: derived from title)."
    )
    remember_parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing file at the same slug."
    )
    remember_parser.add_argument("--config", help=config_help)
    remember_parser.add_argument("--workspace-root")
    remember_parser.add_argument("--database")
    remember_parser.set_defaults(func=cmd_remember)

    forget_parser = subparsers.add_parser(
        "forget",
        help=(
            "Remove a memory's source file and sync the tombstone it "
            "produces (audit-visible, excluded from ordinary recall)."
        ),
    )
    forget_parser.add_argument(
        "--item-id",
        required=True,
        dest="item_id",
        help="'local_files:<root>:<relative path>', as printed by 'remember'.",
    )
    forget_parser.add_argument("--config", help=config_help)
    forget_parser.add_argument("--workspace-root")
    forget_parser.add_argument("--database")
    forget_parser.set_defaults(func=cmd_forget)

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
            "Principal to ask as (default: the configured owner, then lee@leebase.com)."
        ),
    )
    ask_parser.add_argument("--config", help=config_help)
    ask_parser.add_argument(
        "--database",
        help="Read the synchronized SQLite projection from this path.",
    )
    ask_parser.set_defaults(func=cmd_ask)

    access_parser = subparsers.add_parser(
        "access",
        help=(
            "Provision employee principals, client credentials, and knowledge "
            "grants for authenticated multi-principal access."
        ),
    )
    access_groups = access_parser.add_subparsers(dest="access_group")
    access_groups.required = True

    employee_parser = access_groups.add_parser(
        "employee", help="Manage server-owned employee principals."
    )
    employee_actions = employee_parser.add_subparsers(dest="employee_action")
    employee_actions.required = True
    employee_add_parser = employee_actions.add_parser(
        "add",
        help=(
            "Register one AI-employee principal with its governed tenant, "
            "lane, scope, and purpose."
        ),
    )
    employee_add_parser.add_argument(
        "--employee-id", required=True, dest="employee_id", help="Employee record id."
    )
    employee_add_parser.add_argument(
        "--principal",
        required=True,
        help="Principal identifier, for example employee:chief-of-staff.",
    )
    employee_add_parser.add_argument("--tenant", required=True, help="Tenant boundary.")
    employee_add_parser.add_argument("--lane", required=True, help="Governed lane.")
    employee_add_parser.add_argument(
        "--scope", required=True, dest="scope_id", help="Scope identifier."
    )
    employee_add_parser.add_argument(
        "--purpose", required=True, help="Declared purpose of the access."
    )
    employee_add_parser.add_argument("--config", help=config_help)
    employee_add_parser.set_defaults(func=cmd_access, access_action="employee-add")

    employee_list_parser = employee_actions.add_parser(
        "list", help="List configured employee principals."
    )
    employee_list_parser.add_argument("--config", help=config_help)
    employee_list_parser.set_defaults(func=cmd_access, access_action="employee-list")

    client_parser = access_groups.add_parser(
        "client", help="Manage authenticated client credentials."
    )
    client_actions = client_parser.add_subparsers(dest="client_action")
    client_actions.required = True
    client_register_parser = client_actions.add_parser(
        "register",
        help="Register one client for an employee and print its one-time secret.",
    )
    client_register_parser.add_argument(
        "--principal", required=True, help="Employee principal to issue the client for."
    )
    client_register_parser.add_argument(
        "--client-id", default=None, dest="client_id", help="Explicit client id."
    )
    client_register_parser.add_argument(
        "--expires-days",
        type=int,
        default=None,
        dest="expires_days",
        help="Credential lifetime in days (default: 90).",
    )
    client_register_parser.add_argument("--config", help=config_help)
    client_register_parser.set_defaults(
        func=cmd_access, access_action="client-register"
    )

    client_list_parser = client_actions.add_parser(
        "list", help="List registered clients without secrets."
    )
    client_list_parser.add_argument("--config", help=config_help)
    client_list_parser.set_defaults(func=cmd_access, access_action="client-list")

    client_revoke_parser = client_actions.add_parser(
        "revoke", help="Revoke one client credential and its live sessions."
    )
    client_revoke_parser.add_argument(
        "--client-id", required=True, dest="client_id", help="Client id to revoke."
    )
    client_revoke_parser.add_argument("--config", help=config_help)
    client_revoke_parser.set_defaults(func=cmd_access, access_action="client-revoke")

    grant_parser = access_groups.add_parser(
        "grant", help="Manage bounded knowledge grants."
    )
    grant_actions = grant_parser.add_subparsers(dest="grant_action")
    grant_actions.required = True
    grant_add_parser = grant_actions.add_parser(
        "add",
        help=(
            "Grant one employee bounded access to a source root. Tenant, lane, "
            "scope, and purpose always come from the employee record."
        ),
    )
    grant_add_parser.add_argument(
        "--principal", required=True, help="Employee principal to grant."
    )
    grant_add_parser.add_argument(
        "--project", required=True, help="Project the grant applies to."
    )
    grant_add_parser.add_argument(
        "--source-namespace",
        required=True,
        dest="source_namespace",
        help="Connector namespace, for example local_files.",
    )
    grant_add_parser.add_argument(
        "--root", required=True, help="Configured source root name."
    )
    grant_add_parser.add_argument(
        "--path-prefix",
        default=WHOLE_ROOT_PATH_PREFIX,
        dest="path_prefix",
        help=(
            "Relative path prefix inside the root "
            f"(default: {WHOLE_ROOT_PATH_PREFIX}, the whole root)."
        ),
    )
    grant_add_parser.add_argument(
        "--operations",
        default="search,read,cite",
        help="Comma-separated operations (default: search,read,cite).",
    )
    grant_add_parser.add_argument(
        "--grant-id", default=None, dest="grant_id", help="Explicit grant id."
    )
    grant_add_parser.add_argument(
        "--expires-days",
        type=int,
        default=None,
        dest="expires_days",
        help="Grant lifetime in days (default: no expiry).",
    )
    grant_add_parser.add_argument(
        "--classification",
        default=None,
        help="Restrict the grant to items with this classification.",
    )
    grant_add_parser.add_argument("--config", help=config_help)
    grant_add_parser.set_defaults(func=cmd_access, access_action="grant-add")

    grant_list_parser = grant_actions.add_parser(
        "list", help="List configured grants, including revoked ones."
    )
    grant_list_parser.add_argument(
        "--principal", default=None, help="Only list grants for this principal."
    )
    grant_list_parser.add_argument("--config", help=config_help)
    grant_list_parser.set_defaults(func=cmd_access, access_action="grant-list")

    grant_revoke_parser = grant_actions.add_parser(
        "revoke", help="Revoke one grant, keeping the record for evidence."
    )
    grant_revoke_parser.add_argument(
        "--grant-id", required=True, dest="grant_id", help="Grant id to revoke."
    )
    grant_revoke_parser.add_argument("--config", help=config_help)
    grant_revoke_parser.set_defaults(func=cmd_access, access_action="grant-revoke")

    audit_parser = access_groups.add_parser(
        "audit", help="Inspect durable access evidence (never query text)."
    )
    audit_actions = audit_parser.add_subparsers(dest="audit_action")
    audit_actions.required = True
    audit_list_parser = audit_actions.add_parser(
        "list", help="Print the most recent access audit events, newest last."
    )
    audit_list_parser.add_argument(
        "--limit", type=int, default=50, help="Events to print (default: 50)."
    )
    audit_list_parser.add_argument("--config", help=config_help)
    audit_list_parser.set_defaults(func=cmd_access, access_action="audit-list")

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
