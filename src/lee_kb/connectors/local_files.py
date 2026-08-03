"""Local-file connector: the first-release connector for lee-kb.

Reads a ``sources.toml`` configuration compatible with the Employee Zero
``knowledge/sources.toml`` shape (see
``research/employee-zero-kb-reference.md``): a table of named roots, each
with a filesystem ``path``, an include glob list, an optional exclude glob
list, and declared ``authority``/``trust``/``owner`` metadata. Matching is
default-deny: a file is only discovered if it matches at least one
``include`` pattern and no ``exclude`` pattern.

Configuration shape::

    schema = 1

    [roots.notes]
    path = "/home/lee/notes"
    owner = "lee@leebase.com"
    include = ["*.md", "*.txt"]
    exclude = [".git/**", "tmp/**"]
    authority = "canonical"   # "canonical" | "derived", default "derived"
    trust = "human_authored"  # "human_authored" | "curated" | "model_produced",
                               # default "curated"
    visibility = "private"    # "private" | "project" | "public", default "private"
    project = "default"       # default DEFAULT_PROJECT
    required = true           # default true; missing path fails health()

Format handlers
----------------

Discovery and fetch only recognize file extensions registered in
``FORMAT_HANDLERS``. The v1 registry covers Markdown and plain text only;
office formats (``docx``, ``xlsx``, ``pptx``) are deliberately not
registered here even though :class:`lee_kb.contracts.DocumentType`
enumerates them — the parsing libraries they need are new runtime
dependencies and are deferred pending explicit approval (see Open Question 4
in ``docs/sprint-1-contracts.md``). Extend the registry by adding a
``FormatHandler`` to ``FORMAT_HANDLERS`` keyed by lowercase file suffix
(including the leading dot); a handler needs only a ``document_type`` and a
``decode`` callable from raw bytes to text.

Change detection
----------------

There is no native change feed for a filesystem, so
:meth:`LocalFilesConnector.list_changes` takes a snapshot cursor: a JSON
object mapping ``source_object_id`` to its last-known ``content_hash``,
produced by :meth:`LocalFilesConnector.checkpoint`. Diffing the current
:meth:`LocalFilesConnector.discover` result against that snapshot yields
created, updated, and deleted objects without depending on mtimes, which are
unreliable across copies, clones, and restores.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path

import tomllib

from ..contracts import (
    DEFAULT_PROJECT,
    Authority,
    ChangeType,
    DocumentType,
    PermissionSet,
    SourceLocator,
    Trust,
    Visibility,
    compute_content_hash,
)
from .base import (
    Connector,
    ConnectorConfigError,
    ConnectorReadError,
    FetchedDocument,
    HealthStatus,
    ObjectChange,
    SourceObject,
)

__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "FormatHandler",
    "FORMAT_HANDLERS",
    "RootConfig",
    "load_config",
    "LocalFilesConnector",
]

#: Version of the sources.toml shape this loader accepts.
CONFIG_SCHEMA_VERSION = 1

_AUTHORITY_BY_VALUE = {member.value: member for member in Authority}
_TRUST_BY_VALUE = {member.value: member for member in Trust}
_VISIBILITY_BY_VALUE = {member.value: member for member in Visibility}


@dataclass(frozen=True, slots=True)
class FormatHandler:
    """Decodes one file format into normalized text for a document type."""

    document_type: DocumentType
    decode: Callable[[bytes], str]


def _decode_text(raw: bytes) -> str:
    return raw.decode("utf-8")


#: Registered file-format handlers, keyed by lowercase suffix (with dot).
#: Add entries here to support new text-like formats; do not add office
#: formats without approval (see the module docstring).
FORMAT_HANDLERS: dict[str, FormatHandler] = {
    ".md": FormatHandler(DocumentType.MARKDOWN, _decode_text),
    ".markdown": FormatHandler(DocumentType.MARKDOWN, _decode_text),
    ".txt": FormatHandler(DocumentType.PLAIN_TEXT, _decode_text),
    ".text": FormatHandler(DocumentType.PLAIN_TEXT, _decode_text),
}


@dataclass(frozen=True, slots=True)
class RootConfig:
    """One configured source root."""

    name: str
    path: Path
    owner: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    authority: Authority = Authority.DERIVED
    trust: Trust = Trust.CURATED
    visibility: Visibility = Visibility.PRIVATE
    project: str = DEFAULT_PROJECT
    required: bool = True


def load_config(config_path: str | Path) -> tuple[RootConfig, ...]:
    """Parse a sources.toml file into root configurations.

    Raises :class:`ConnectorConfigError` on a missing schema declaration, an
    unsupported schema version, or a root missing a required field.
    """
    config_path = Path(config_path)
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConnectorConfigError(f"config file not found: {config_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConnectorConfigError(f"invalid TOML in {config_path}: {error}") from error

    schema = data.get("schema")
    if schema != CONFIG_SCHEMA_VERSION:
        raise ConnectorConfigError(
            f"unsupported sources.toml schema {schema!r}; "
            f"expected {CONFIG_SCHEMA_VERSION}"
        )

    raw_roots = data.get("roots")
    if not isinstance(raw_roots, dict) or not raw_roots:
        raise ConnectorConfigError("sources.toml must declare at least one root")

    roots = []
    for name, raw_root in raw_roots.items():
        roots.append(_parse_root(name, raw_root, config_path.parent))
    return tuple(roots)


def _parse_root(name: str, raw: object, config_dir: Path) -> RootConfig:
    if not isinstance(raw, dict):
        raise ConnectorConfigError(f"root {name!r} must be a table")

    raw_path = raw.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ConnectorConfigError(f"root {name!r} is missing a non-empty path")
    path = Path(raw_path)
    if not path.is_absolute():
        path = config_dir / path
    path = path.resolve()

    owner = raw.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        raise ConnectorConfigError(f"root {name!r} is missing a non-empty owner")

    include = raw.get("include")
    if (
        not isinstance(include, list)
        or not include
        or not all(isinstance(pattern, str) and pattern for pattern in include)
    ):
        raise ConnectorConfigError(
            f"root {name!r} must declare a non-empty include pattern list"
        )

    exclude = raw.get("exclude", [])
    if not isinstance(exclude, list) or not all(
        isinstance(pattern, str) and pattern for pattern in exclude
    ):
        raise ConnectorConfigError(f"root {name!r} has an invalid exclude list")

    authority = _lookup(raw, name, "authority", _AUTHORITY_BY_VALUE, Authority.DERIVED)
    trust = _lookup(raw, name, "trust", _TRUST_BY_VALUE, Trust.CURATED)
    visibility = _lookup(
        raw, name, "visibility", _VISIBILITY_BY_VALUE, Visibility.PRIVATE
    )

    project = raw.get("project", DEFAULT_PROJECT)
    if not isinstance(project, str) or not project.strip():
        raise ConnectorConfigError(f"root {name!r} has an invalid project")

    required = raw.get("required", True)
    if not isinstance(required, bool):
        raise ConnectorConfigError(f"root {name!r} has a non-boolean required flag")

    return RootConfig(
        name=name,
        path=path,
        owner=owner,
        include=tuple(include),
        exclude=tuple(exclude),
        authority=authority,
        trust=trust,
        visibility=visibility,
        project=project,
        required=required,
    )


def _lookup(raw: dict, root_name: str, field: str, table: dict, default):
    value = raw.get(field)
    if value is None:
        return default
    if value not in table:
        raise ConnectorConfigError(
            f"root {root_name!r} has an unrecognized {field} {value!r}"
        )
    return table[value]


def _matches(
    relative_posix: str, include: Sequence[str], exclude: Sequence[str]
) -> bool:
    if not any(fnmatchcase(relative_posix, pattern) for pattern in include):
        return False
    return not any(fnmatchcase(relative_posix, pattern) for pattern in exclude)


def _split_object_id(source_object_id: str) -> tuple[str, str]:
    if ":" not in source_object_id:
        raise ConnectorReadError(
            f"malformed source_object_id (expected 'root:path'): {source_object_id!r}"
        )
    root_name, _, relative = source_object_id.partition(":")
    return root_name, relative


class LocalFilesConnector(Connector):
    """Connector over one or more local filesystem roots."""

    def __init__(
        self,
        roots: Sequence[RootConfig],
        *,
        connector_id: str = "local_files",
    ) -> None:
        if not roots:
            raise ConnectorConfigError("at least one root is required")
        self._connector_id = connector_id
        self._roots_by_name = {root.name: root for root in roots}

    @classmethod
    def from_config(
        cls, config_path: str | Path, *, connector_id: str = "local_files"
    ) -> "LocalFilesConnector":
        """Build a connector from a sources.toml file."""
        return cls(load_config(config_path), connector_id=connector_id)

    @property
    def connector_id(self) -> str:
        return self._connector_id

    def discover(self) -> tuple[SourceObject, ...]:
        objects: list[SourceObject] = []
        for root in self._roots_by_name.values():
            if not root.path.is_dir():
                continue
            for file_path in sorted(root.path.rglob("*")):
                if not file_path.is_file():
                    continue
                relative = file_path.relative_to(root.path).as_posix()
                if not _matches(relative, root.include, root.exclude):
                    continue
                handler = FORMAT_HANDLERS.get(file_path.suffix.lower())
                if handler is None:
                    continue
                objects.append(self._describe(root, relative, file_path, handler))
        return tuple(objects)

    def _describe(
        self, root: RootConfig, relative: str, file_path: Path, handler: FormatHandler
    ) -> SourceObject:
        try:
            raw = file_path.read_bytes()
            stat = file_path.stat()
        except OSError as error:
            raise ConnectorReadError(f"cannot read {file_path}: {error}") from error
        return SourceObject(
            source_object_id=f"{root.name}:{relative}",
            source_locator=SourceLocator(
                connector_id=self._connector_id,
                uri=file_path.as_uri(),
                label=relative,
            ),
            document_type=handler.document_type,
            content_hash=compute_content_hash(raw),
            source_timestamp=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            project=root.project,
            authority=root.authority,
            trust=root.trust,
        )

    def list_changes(self, cursor: str | None = None) -> tuple[ObjectChange, ...]:
        previous = _decode_snapshot(cursor)
        current = {obj.source_object_id: obj.content_hash for obj in self.discover()}

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
            if source_object_id not in current:
                changes.append(
                    ObjectChange(
                        source_object_id,
                        ChangeType.DELETED,
                        previous_content_hash=previous_hash,
                    )
                )
        return tuple(sorted(changes, key=lambda change: change.source_object_id))

    def fetch(self, source_object_id: str) -> FetchedDocument:
        root, relative, file_path = self._resolve(source_object_id)
        handler = FORMAT_HANDLERS.get(file_path.suffix.lower())
        if handler is None:
            raise ConnectorReadError(
                f"no format handler registered for {file_path.suffix!r}: "
                f"{source_object_id}"
            )
        try:
            raw = file_path.read_bytes()
            stat = file_path.stat()
        except OSError as error:
            raise ConnectorReadError(f"cannot read {file_path}: {error}") from error
        try:
            content = handler.decode(raw)
        except UnicodeDecodeError as error:
            raise ConnectorReadError(f"cannot decode {file_path}: {error}") from error

        return FetchedDocument(
            source_object_id=source_object_id,
            source_locator=SourceLocator(
                connector_id=self._connector_id,
                uri=file_path.as_uri(),
                label=relative,
            ),
            document_type=handler.document_type,
            content=content,
            content_hash=compute_content_hash(raw),
            source_timestamp=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            project=root.project,
            title=Path(relative).name,
            authority=root.authority,
            trust=root.trust,
        )

    def refresh(self, source_object_id: str) -> FetchedDocument:
        # Local reads are already live: there is no separate refresh path
        # to distinguish from an ordinary fetch.
        return self.fetch(source_object_id)

    def permissions(self, source_object_id: str) -> PermissionSet:
        root, _relative, _file_path = self._resolve(source_object_id)
        return PermissionSet(owner=root.owner, visibility=root.visibility)

    def relationships(self, source_object_id: str) -> tuple[str, ...]:
        # The local filesystem has no relationship model in v1.
        self._resolve(source_object_id)
        return ()

    def health(self) -> HealthStatus:
        missing_required = tuple(
            root.name
            for root in self._roots_by_name.values()
            if root.required and not root.path.is_dir()
        )
        healthy = not missing_required
        detail = (
            "all roots reachable"
            if healthy
            else f"missing required roots: {', '.join(missing_required)}"
        )
        return HealthStatus(
            healthy=healthy,
            checked_at=datetime.now(timezone.utc),
            detail=detail,
            missing_required_roots=missing_required,
        )

    def checkpoint(self, objects: Sequence[SourceObject]) -> str:
        snapshot = {obj.source_object_id: obj.content_hash for obj in objects}
        return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))

    def _resolve(self, source_object_id: str) -> tuple[RootConfig, str, Path]:
        root_name, relative = _split_object_id(source_object_id)
        root = self._roots_by_name.get(root_name)
        if root is None:
            raise ConnectorReadError(f"unknown root in source_object_id: {root_name!r}")
        file_path = (root.path / relative).resolve()
        if root.path not in file_path.parents and file_path != root.path:
            raise ConnectorReadError(
                f"source_object_id escapes its root: {source_object_id!r}"
            )
        if not file_path.is_file():
            raise ConnectorReadError(
                f"source object no longer exists: {source_object_id}"
            )
        return root, relative, file_path


def _decode_snapshot(cursor: str | None) -> dict[str, str]:
    if cursor is None:
        return {}
    try:
        snapshot = json.loads(cursor)
    except json.JSONDecodeError as error:
        raise ConnectorConfigError(f"invalid cursor: {error}") from error
    if not isinstance(snapshot, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in snapshot.items()
    ):
        raise ConnectorConfigError("invalid cursor: expected a JSON object of strings")
    return snapshot
