"""Owner-first LeeOS knowledge contract for lee-kb.

This module is an additive, dependency-free seam. It owns identity mapping,
current release under the versioned server mapping, and exact historical
release. It never searches history, walks a repository, or mirrors source
payloads: the only historical source is one exact named object read through
git plumbing, inside an explicit repository allowlist, with bounded size and
bounded time.

Owner-gateway mode is activated by the deployment configuration file, never by
an environment variable, because the frozen consumer launches this server with
a minimal environment that carries only ``PATH``, ``LANG``, ``LC_ALL`` and
``LEE_KB_CONFIG``.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .contracts import (
    OWNER_CONTRACT_VERSION,
    OWNER_CORPUS_VERSION,
    OWNER_HISTORICAL_VERSION,
    OWNER_MAPPING_VERSION,
    OWNER_PERMISSION_VERSION,
    OWNER_RECEIPT_VERSION,
    OWNER_SCHEMA_VERSION,
    WHOLE_ROOT_PATH_PREFIX,
    HistoricalLocator,
    HistoricalLookupResult,
    HistoricalReleaseManifest,
    HistoricalReleaseRule,
    ImmutableHistoricalObject,
    KnowledgeItem,
    MappedIdentity,
    OwnerCurrentReceipt,
    OwnerCurrentResult,
    OwnerFreshnessState,
    OwnerIdentityMapping,
    OwnerKnowledgeState,
    PolicyBasis,
    Principal,
    RetrievalReceipt,
    RetrieveRequest,
    SourceGrant,
    compute_content_hash,
)
from .governance import ExactHistoricalReader, PermissionEvaluator, retrieve
from .repository import Repository

OWNER_NAME = "lee-kb"
OWNER_API_VERSION = "lee-kb.owner.api/v1"

#: One denial message for every owner-mode refusal: the basis is never named.
OWNER_ACCESS_DENIED = "owner request is not permitted"

#: Largest exact historical object this owner will read into memory.
MAX_EXACT_OBJECT_BYTES = 1024 * 1024

#: Wall-clock bound on every git plumbing invocation.
GIT_TIMEOUT_SECONDS = 5.0

#: ``KnowledgeItem`` -> (source_namespace, root, path) inside the mapped scope.
SourceScope = Callable[[KnowledgeItem], tuple[str, str, str] | None]


class OwnerConfigurationError(ValueError):
    """Raised when ``[owner_gateway]`` cannot be turned into a usable gateway."""


class OwnerAccessError(PermissionError):
    """Non-enumerating owner refusal: which basis failed is never disclosed."""


def owner_handshake(mapping: OwnerIdentityMapping) -> dict[str, str]:
    """Return the additive owner handshake carried by ``initialize``.

    The frozen consumer synthesizes the same shape from its own constants and
    compares them, so publishing them here is what makes owner-side version
    drift visible on the wire.
    """
    if not isinstance(mapping, OwnerIdentityMapping):
        raise TypeError("mapping must be an OwnerIdentityMapping")
    return {
        "owner": OWNER_NAME,
        "api_version": OWNER_API_VERSION,
        "contract_version": OWNER_CONTRACT_VERSION,
        "schema_version": OWNER_SCHEMA_VERSION,
        "corpus_version": OWNER_CORPUS_VERSION,
        "mapping_version": mapping.version,
        "mapping_hash": mapping.mapping_hash,
        "permission_version": OWNER_PERMISSION_VERSION,
        "receipt_version": OWNER_RECEIPT_VERSION,
        "historical_version": OWNER_HISTORICAL_VERSION,
    }


class ExactObjectResolver(Protocol):
    """Supported owner-native exact object seam; no repository walking."""

    def resolve(
        self, locator: HistoricalLocator
    ) -> ImmutableHistoricalObject | None: ...


class _MappedPermissionEvaluator(PermissionEvaluator):
    """Apply server-owned source grants before the normal item permission."""

    def __init__(
        self,
        identity: MappedIdentity,
        source_mapping: SourceScope | None,
    ) -> None:
        self._identity = identity
        self._source_mapping = source_mapping

    def is_permitted(self, item: KnowledgeItem, principal: Principal) -> bool:
        if principal != self._identity.principal or self._source_mapping is None:
            return False
        scope = self._source_mapping(item)
        if scope is None:
            return False
        source_namespace, root, path = scope
        if not any(
            grant.permits(
                project=item.project,
                source_namespace=source_namespace,
                root=root,
                path=path,
                item_id=str(item.item_id),
            )
            for grant in self._identity.grants
        ):
            return False
        permissions = item.permissions
        return (
            principal.principal_id == permissions.owner
            or principal.principal_id in permissions.allowed_principals
            or bool(set(principal.groups) & set(permissions.allowed_groups))
            or permissions.visibility.value == "public"
        )


@dataclass(frozen=True, slots=True)
class HistoricalReleaseScope:
    """Server-declared source scope and classification of one exact object.

    The wire carries only ``(repository, commit, path, classification)``, so
    the source namespace, root and item that the release is governed under are
    resolved here, from configuration, never from a client argument.
    """

    locator: HistoricalLocator
    classification: str
    source_namespace: str
    root: str
    item_id: str | None = None


@dataclass(frozen=True, slots=True)
class OwnerGatewayConfig:
    """Deployment configuration that activates owner-gateway mode."""

    mapping: OwnerIdentityMapping
    manifest: HistoricalReleaseManifest | None
    scopes: tuple[HistoricalReleaseScope, ...]
    repositories: tuple[tuple[str, str], ...]
    project: str | None = None

    def scope_for(self, locator: HistoricalLocator) -> HistoricalReleaseScope | None:
        """Return the single declared scope for ``locator``; ambiguity is None."""
        matches = tuple(scope for scope in self.scopes if scope.locator == locator)
        return matches[0] if len(matches) == 1 else None

    def classification_for(self, locator: HistoricalLocator) -> str | None:
        scope = self.scope_for(locator)
        return scope.classification if scope is not None else None

    def repository_paths(self) -> dict[str, str]:
        return dict(self.repositories)

    def projects(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(grant.project for grant in self.mapping.grants))

    def current_permission(
        self,
    ) -> Callable[[MappedIdentity, HistoricalLocator, str], PolicyBasis]:
        """Bind the mapped current permission used as the history pre-condition."""

        def evaluate(
            identity: MappedIdentity,
            locator: HistoricalLocator,
            classification: str,
        ) -> PolicyBasis:
            scope = self.scope_for(locator)
            if scope is None or scope.classification != classification:
                return PolicyBasis.unknown(OWNER_PERMISSION_VERSION)
            permitted = self.mapping.permits(
                identity,
                source_namespace=scope.source_namespace,
                root=scope.root,
                path=locator.path,
                item_id=scope.item_id,
            )
            return PolicyBasis(
                OWNER_PERMISSION_VERSION,
                identity.mapping_hash,
                "allow" if permitted else "deny",
            )

        return evaluate


def _table(section: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    value = section.get(name)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise OwnerConfigurationError(f"[owner_gateway.{name}] must be a table")
    return value


def _text(section: Mapping[str, Any], name: str, default: str | None = None) -> str:
    value = section.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise OwnerConfigurationError(
            f"owner_gateway {name} must be a non-empty string"
        )
    return value


def _texts(section: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = section.get(name)
    if not isinstance(value, list) or not value:
        raise OwnerConfigurationError(f"owner_gateway {name} must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise OwnerConfigurationError(f"owner_gateway {name} must contain strings")
    return tuple(value)


def _moment(section: Mapping[str, Any], name: str) -> datetime | None:
    value = section.get(name)
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as error:
            raise OwnerConfigurationError(
                f"owner_gateway {name} must be an ISO-8601 timestamp"
            ) from error
    else:
        raise OwnerConfigurationError(
            f"owner_gateway {name} must be an ISO-8601 timestamp"
        )
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise OwnerConfigurationError(f"owner_gateway {name} must carry a UTC offset")
    return moment


def _grants(section: Mapping[str, Any]) -> tuple[SourceGrant, ...]:
    raw = section.get("grants")
    if not isinstance(raw, list) or not raw:
        raise OwnerConfigurationError(
            "[owner_gateway.mapping] requires at least one grant"
        )
    grants: list[SourceGrant] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise OwnerConfigurationError("owner_gateway grants must be tables")
        item_ids = entry.get("item_ids", [])
        if not isinstance(item_ids, list) or any(
            not isinstance(item, str) or not item.strip() for item in item_ids
        ):
            raise OwnerConfigurationError(
                "owner_gateway grant item_ids must be strings"
            )
        try:
            grants.append(
                SourceGrant(
                    _text(entry, "project"),
                    _text(entry, "source_namespace"),
                    _text(entry, "root"),
                    _text(entry, "path_prefix", WHOLE_ROOT_PATH_PREFIX),
                    tuple(item_ids),
                )
            )
        except (TypeError, ValueError) as error:
            raise OwnerConfigurationError(f"owner_gateway grant is invalid: {error}")
    return tuple(grants)


def _release(
    section: Mapping[str, Any],
) -> tuple[HistoricalReleaseManifest | None, tuple[HistoricalReleaseScope, ...]]:
    """Build the versioned release manifest and its declared source scopes."""
    version = _text(section, "version", OWNER_HISTORICAL_VERSION)
    expires_at = _moment(section, "expires_at")
    raw = section.get("rules")
    if not isinstance(raw, list) or not raw:
        raise OwnerConfigurationError(
            "[owner_gateway.historical_release] requires at least one rule"
        )
    rules: list[HistoricalReleaseRule] = []
    scopes: list[HistoricalReleaseScope] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise OwnerConfigurationError("owner_gateway release rules must be tables")
        decision = _text(entry, "decision", "allow")
        if decision not in {"allow", "deny"}:
            raise OwnerConfigurationError(
                "owner_gateway rule decision must be allow or deny"
            )
        not_before = _moment(entry, "not_before")
        not_after = _moment(entry, "not_after")
        item_id = entry.get("item_id")
        if item_id is not None and (
            not isinstance(item_id, str) or not item_id.strip()
        ):
            raise OwnerConfigurationError("owner_gateway rule item_id must be a string")
        try:
            locator = HistoricalLocator(
                _text(entry, "repository"), _text(entry, "commit"), _text(entry, "path")
            )
        except (TypeError, ValueError) as error:
            raise OwnerConfigurationError(
                f"owner_gateway rule locator is invalid: {error}"
            )
        classification = _text(entry, "classification")
        body = {
            "version": version,
            "locator": list(locator.as_tuple()),
            "classification": classification,
            "decision": decision,
            "not_before": not_before.isoformat() if not_before else None,
            "not_after": not_after.isoformat() if not_after else None,
        }
        basis = PolicyBasis(
            version,
            compute_content_hash(
                json.dumps(
                    body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
            ),
            decision,
            None,
            not_after,
        )
        for principal_id in _texts(entry, "principals"):
            for project in _texts(entry, "projects"):
                try:
                    rules.append(
                        HistoricalReleaseRule(
                            principal_id,
                            project,
                            locator,
                            classification,
                            basis,
                            not_before,
                            not_after,
                        )
                    )
                except (TypeError, ValueError) as error:
                    raise OwnerConfigurationError(
                        f"owner_gateway release rule is invalid: {error}"
                    )
        scopes.append(
            HistoricalReleaseScope(
                locator,
                classification,
                _text(entry, "source_namespace"),
                _text(entry, "root"),
                item_id,
            )
        )
    try:
        manifest = HistoricalReleaseManifest(
            version=version, rules=tuple(rules), expires_at=expires_at
        )
    except (TypeError, ValueError) as error:
        raise OwnerConfigurationError(
            f"owner_gateway release manifest is invalid: {error}"
        )
    declared = section.get("manifest_hash")
    if declared is not None and declared != manifest.manifest_hash:
        raise OwnerConfigurationError(
            "owner_gateway manifest_hash does not match rules"
        )
    return manifest, tuple(scopes)


def _repositories(section: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    allowlist: list[tuple[str, str]] = []
    for name, value in section.items():
        if not isinstance(name, str) or not name.strip():
            raise OwnerConfigurationError(
                "owner_gateway repository names must be strings"
            )
        if not isinstance(value, str) or not value.strip():
            raise OwnerConfigurationError(
                "owner_gateway repository paths must be absolute strings"
            )
        path = Path(value)
        if not path.is_absolute():
            raise OwnerConfigurationError(
                "owner_gateway repository paths must be absolute strings"
            )
        allowlist.append((name, str(path)))
    return tuple(sorted(allowlist))


def load_owner_gateway(raw_config: Mapping[str, Any]) -> OwnerGatewayConfig | None:
    """Return the owner-gateway configuration, or ``None`` when it is absent."""
    if not isinstance(raw_config, Mapping):
        raise OwnerConfigurationError("configuration must be a table")
    section = raw_config.get("owner_gateway")
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise OwnerConfigurationError("[owner_gateway] must be a table")

    mapping_section = _table(section, "mapping")
    if mapping_section is None:
        raise OwnerConfigurationError("[owner_gateway.mapping] is required")
    declared_hash = mapping_section.get("mapping_hash")
    if declared_hash is not None and not isinstance(declared_hash, str):
        raise OwnerConfigurationError("owner_gateway mapping_hash must be a string")
    try:
        mapping = OwnerIdentityMapping(
            authenticated_principal=_text(
                mapping_section, "authenticated_principal", "lee"
            ),
            principal_id=_text(mapping_section, "principal_id", "lee@leebase.com"),
            tenant=_text(mapping_section, "tenant", "leebase"),
            lane=_text(mapping_section, "lane", "default"),
            scope_id=_text(mapping_section, "scope_id", "leeos"),
            purpose=_text(mapping_section, "purpose", "knowledge"),
            grants=_grants(mapping_section),
            version=_text(mapping_section, "version", OWNER_MAPPING_VERSION),
            mapping_hash=declared_hash or "",
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, OwnerConfigurationError):
            raise
        raise OwnerConfigurationError(f"owner_gateway mapping is invalid: {error}")

    release_section = _table(section, "historical_release")
    manifest: HistoricalReleaseManifest | None = None
    scopes: tuple[HistoricalReleaseScope, ...] = ()
    if release_section is not None:
        manifest, scopes = _release(release_section)

    repositories_section = _table(section, "repositories")
    repositories = (
        () if repositories_section is None else _repositories(repositories_section)
    )

    project = section.get("project")
    if project is not None and (not isinstance(project, str) or not project.strip()):
        raise OwnerConfigurationError(
            "owner_gateway project must be a non-empty string"
        )
    projects = tuple(dict.fromkeys(grant.project for grant in mapping.grants))
    if project is not None and project not in projects:
        raise OwnerConfigurationError("owner_gateway project is not granted")

    return OwnerGatewayConfig(
        mapping=mapping,
        manifest=manifest,
        scopes=scopes,
        repositories=repositories,
        project=project,
    )


class GitExactObjectResolver:
    """Read exactly one named immutable object through git plumbing.

    This is not a repository walker, a history search, a cache or a network
    client: it verifies one commit, reads one blob at one exact path inside one
    allowlisted worktree, and refuses anything oversized, non-textual, slow or
    unnamed. Every refusal is ``None``, which the reader turns into the safe
    non-enumerating ``UNKNOWN`` state.
    """

    def __init__(
        self,
        repositories: Mapping[str, str | Path],
        classification: Callable[[HistoricalLocator], str | None],
        *,
        max_bytes: int = MAX_EXACT_OBJECT_BYTES,
        timeout: float = GIT_TIMEOUT_SECONDS,
        git: str = "git",
    ) -> None:
        if not isinstance(repositories, Mapping):
            raise TypeError("repositories must be a mapping of name to worktree path")
        if not callable(classification):
            raise TypeError("classification must be callable")
        self._repositories = {
            str(name): str(path) for name, path in repositories.items()
        }
        self._classification = classification
        self._max_bytes = int(max_bytes)
        self._timeout = float(timeout)
        self._git = git
        self._env = {
            "PATH": os.environ.get("PATH", ""),
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
        }

    @property
    def repositories(self) -> tuple[str, ...]:
        """The allowlisted repository names; nothing else is readable."""
        return tuple(sorted(self._repositories))

    def _run(self, worktree: str, *args: str) -> bytes | None:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [self._git, "-C", worktree, *args],
                capture_output=True,
                check=False,
                timeout=self._timeout,
                env=self._env,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout

    def resolve(self, locator: HistoricalLocator) -> ImmutableHistoricalObject | None:
        if not isinstance(locator, HistoricalLocator):
            return None
        worktree = self._repositories.get(locator.repository)
        if worktree is None or not Path(worktree).is_dir():
            return None
        classification = self._classification(locator)
        if not isinstance(classification, str) or not classification.strip():
            return None

        resolved = self._run(
            worktree, "rev-parse", "--verify", "--quiet", f"{locator.commit}^{{commit}}"
        )
        if (
            resolved is None
            or resolved.decode("utf-8", "replace").strip() != locator.commit
        ):
            return None

        stamp = self._run(worktree, "show", "-s", "--format=%cI", locator.commit)
        if stamp is None:
            return None
        try:
            blob_timestamp = datetime.fromisoformat(stamp.decode("utf-8").strip())
        except (UnicodeDecodeError, ValueError):
            return None
        if blob_timestamp.tzinfo is None or blob_timestamp.utcoffset() is None:
            return None

        reference = f"{locator.commit}:{locator.path}"
        size = self._run(worktree, "cat-file", "-s", reference)
        if size is None:
            return None
        try:
            if int(size.decode("utf-8").strip()) > self._max_bytes:
                return None
        except (UnicodeDecodeError, ValueError):
            return None

        blob = self._run(worktree, "cat-file", "blob", reference)
        if blob is None or len(blob) > self._max_bytes:
            return None
        try:
            body = blob.decode("utf-8")
        except UnicodeDecodeError:
            return None
        try:
            return ImmutableHistoricalObject(
                locator,
                body,
                compute_content_hash(body),
                blob_timestamp,
                classification,
            )
        except (TypeError, ValueError):
            return None


class OwnerGateway:
    """One owner-native current/history gateway with server-derived identity."""

    api_version = OWNER_API_VERSION
    schema_version = OWNER_SCHEMA_VERSION
    corpus_version = OWNER_CORPUS_VERSION

    def __init__(
        self,
        repository: Repository,
        *,
        mapping: OwnerIdentityMapping,
        manifest: HistoricalReleaseManifest | None = None,
        current_permission: (
            Callable[[MappedIdentity, HistoricalLocator, str], PolicyBasis] | None
        ) = None,
        resolver: (
            Callable[[HistoricalLocator], ImmutableHistoricalObject | None]
            | ExactObjectResolver
            | None
        ) = None,
        source_mapping: SourceScope | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._mapping = mapping
        self._source_mapping = source_mapping
        self._history = ExactHistoricalReader(
            mapping=mapping,
            manifest=manifest,
            current_permission=current_permission,
            resolver=resolver,
            clock=clock,
        )
        self._clock = clock

    def map_identity(
        self, authenticated_principal: str, *, project: str | None = None
    ) -> MappedIdentity:
        """Resolve identity and project solely from configured server grants."""
        if (
            not isinstance(authenticated_principal, str)
            or not authenticated_principal.strip()
        ):
            raise ValueError("authenticated_principal is required")
        return self._mapping.resolve(authenticated_principal, project=project)

    def retrieve_current(
        self,
        query: str,
        *,
        authenticated_principal: str,
        project: str | None = None,
        top_k: int = 10,
    ) -> OwnerCurrentResult:
        """Release current evidence under the mapped principal, project and grants.

        One call is bound to exactly one granted project. An unmapped
        principal, an ungranted project and an ambiguous project selection all
        raise the same :class:`OwnerAccessError`, before any retrieval runs.
        """
        if (
            not isinstance(authenticated_principal, str)
            or not authenticated_principal.strip()
        ):
            raise ValueError("authenticated_principal is required")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be non-empty")
        if len(query.encode("utf-8")) > 16 * 1024:
            raise ValueError("query exceeds maximum size")
        if (
            not isinstance(top_k, int)
            or isinstance(top_k, bool)
            or not 1 <= top_k <= 20
        ):
            raise ValueError("top_k must be between 1 and 20")
        if project is not None and (
            not isinstance(project, str) or not project.strip()
        ):
            raise OwnerAccessError(OWNER_ACCESS_DENIED)
        if self._source_mapping is None:
            raise ValueError("owner current release requires a source mapping")
        try:
            identity = self.map_identity(authenticated_principal, project=project)
        except PermissionError as error:
            raise OwnerAccessError(OWNER_ACCESS_DENIED) from error

        request = RetrieveRequest(
            query=query,
            principal=identity.principal,
            project=identity.project,
            top_k=top_k,
        )
        bundle = retrieve(
            self._repository,
            request.query,
            principal=request.principal,
            project=request.project,
            top_k=request.top_k,
            permission_evaluator=_MappedPermissionEvaluator(
                identity, self._source_mapping
            ),
            clock=self._clock,
        )
        policy = PolicyBasis(OWNER_PERMISSION_VERSION, identity.mapping_hash, "allow")
        freshness_state = (
            OwnerFreshnessState.STALE
            if bundle.freshness.is_stale
            else OwnerFreshnessState.FRESH
        )
        receipts = tuple(
            self._current_receipt(identity, receipt, policy, freshness_state)
            for receipt in bundle.receipts
        )
        return OwnerCurrentResult(
            knowledge_state=(
                OwnerKnowledgeState.KNOWN if receipts else OwnerKnowledgeState.UNKNOWN
            ),
            freshness_state=freshness_state,
            identity=identity,
            policy=policy,
            bundle=bundle,
            receipts=receipts,
        )

    def _current_receipt(
        self,
        identity: MappedIdentity,
        receipt: RetrievalReceipt,
        policy: PolicyBasis,
        freshness_state: OwnerFreshnessState,
    ) -> OwnerCurrentReceipt:
        item = self._repository.get_item(receipt.knowledge_item_id)
        if item is None or self._source_mapping is None:
            raise OwnerAccessError(OWNER_ACCESS_DENIED)
        scope = self._source_mapping(item)
        if scope is None:
            raise OwnerAccessError(OWNER_ACCESS_DENIED)
        source_namespace, root, path = scope
        permissions = item.permissions
        classification = permissions.classification or permissions.visibility.value
        fields: dict[str, Any] = {
            "mapping_version": identity.mapping_version,
            "mapping_hash": identity.mapping_hash,
            "principal": identity.principal,
            "project": identity.project,
            "knowledge_item_id": receipt.knowledge_item_id,
            "chunk_id": receipt.chunk_id,
            "content_hash": receipt.content_hash,
            "source_locator": receipt.source_locator,
            "source_namespace": source_namespace,
            "root": root,
            "path": path,
            "item_id": str(receipt.knowledge_item_id),
            "classification": classification,
            "policy_version": policy.version,
            "policy_hash": policy.sha256,
            "policy_decision": policy.decision,
            "freshness_state": freshness_state,
            "knowledge_state": OwnerKnowledgeState.KNOWN,
            "retrieval_timestamp": receipt.retrieval_timestamp,
        }
        audit_id = (
            "audit-"
            + compute_content_hash(
                json.dumps(
                    {
                        "contract_version": OWNER_CONTRACT_VERSION,
                        "receipt_version": OWNER_RECEIPT_VERSION,
                        "mapping_version": fields["mapping_version"],
                        "mapping_hash": fields["mapping_hash"],
                        "principal_id": identity.principal_id,
                        "project": fields["project"],
                        "item_id": fields["item_id"],
                        "chunk_id": str(receipt.chunk_id),
                        "content_hash": receipt.content_hash,
                        "source_namespace": source_namespace,
                        "root": root,
                        "path": path,
                        "classification": classification,
                        "current_policy": (
                            policy.version,
                            policy.sha256,
                            policy.decision,
                        ),
                        "freshness_state": freshness_state.value,
                        "retrieval_timestamp": receipt.retrieval_timestamp.isoformat(),
                        "state": OwnerKnowledgeState.KNOWN.value,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )[:32]
        )
        return OwnerCurrentReceipt(audit_id=audit_id, **fields)

    def retrieve_history(
        self,
        *,
        authenticated_principal: str,
        locator: HistoricalLocator,
        classification: str,
        source_namespace: str,
        root: str,
        item_id: str | None = None,
        project: str | None = None,
    ) -> HistoricalLookupResult:
        """Read exactly one locator; body release is fail-closed."""
        if (
            not isinstance(authenticated_principal, str)
            or not authenticated_principal.strip()
        ):
            raise ValueError("authenticated_principal is required")
        return self._history.lookup(
            authenticated_principal=authenticated_principal,
            locator=locator,
            classification=classification,
            source_namespace=source_namespace,
            root=root,
            item_id=item_id,
            project=project,
        )


__all__ = [
    "OWNER_NAME",
    "OWNER_API_VERSION",
    "OWNER_SCHEMA_VERSION",
    "OWNER_CORPUS_VERSION",
    "OWNER_CONTRACT_VERSION",
    "OWNER_PERMISSION_VERSION",
    "OWNER_RECEIPT_VERSION",
    "OWNER_HISTORICAL_VERSION",
    "OWNER_ACCESS_DENIED",
    "MAX_EXACT_OBJECT_BYTES",
    "GIT_TIMEOUT_SECONDS",
    "ExactObjectResolver",
    "GitExactObjectResolver",
    "HistoricalReleaseScope",
    "OwnerAccessError",
    "OwnerConfigurationError",
    "OwnerGateway",
    "OwnerGatewayConfig",
    "SourceGrant",
    "load_owner_gateway",
    "owner_handshake",
]
