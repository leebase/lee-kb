# S1C — owner contract map and owner-acceptance artifact

Status: evidence produced 2026-08-13. Artifact status is **`accepted`**:
`evidence/s1c/S1C-lee-kb.json` carries an empty `failure_reasons` array and
every frozen row in sections 2–3 below computes as satisfied.

This document maps the frozen LeeOS S1C consumer contract
(`leeos/.sol-max-chief-of-staff/SPRINT-PLAN.md` lines 295–322) onto the exact
lee-kb symbols and tests that satisfy it. It also specifies the owner-gateway
deployment configuration and the content-free owner-acceptance artifact
produced by `tools/produce_s1c_owner_evidence.py`.

Nothing here is materialized under `.sol-max-chief-of-staff/`, and no LeeOS file
is modified: the controller copies the artifact when it decides to.

```
python3 tools/produce_s1c_owner_evidence.py --output evidence/s1c/S1C-lee-kb.json
```

Line numbers below were captured against the commit and working tree recorded
in the artifact's `owner_repository` section. The authoritative anchor is always
the symbol name; the artifact's `symbol_locations` section carries machine-read
current file/line pairs for every symbol cited here, so regenerating it detects
drift. `src/lee_kb/mcp.py` is under concurrent change, so its line numbers drift
fastest.

## 1. Consumer surface that must be satisfied

The consumer's own gateway is `leeos/src/leeos/core/adapters.py` lines
4643–5965 (read-only for this repository). Three facts of that surface
constrain lee-kb directly:

- **Minimal environment.** `_S1CStdioTransport._minimal_env`
  (adapters.py:5122–5129) spawns `lee-kb-mcp` with only `PATH`, `LANG`,
  `LC_ALL` and `LEE_KB_CONFIG`. Owner-gateway mode is therefore activated by
  the **configuration file**, never by an environment variable
  (section 5).
- **Wire handshake.** `_S1CStdioTransport.handshake()` (adapters.py:5212–5241)
  sends `initialize` with `protocolVersion "2025-06-18"`, then `tools/list`,
  and requires `kb_search` **and** `kb_history_get` to be present. It then
  *synthesizes* its handshake dict from its own constants
  (`KNOWLEDGE_OWNER_*`, adapters.py:4672–4680). lee-kb now publishes exactly
  those names and values in `initialize` → `serverInfo.owner`
  (`src/lee_kb/owner.py:82` `owner_handshake`), so an owner-side version or
  mapping change is visible on the wire instead of being assumed.
- **Forbidden client arguments and the receipt allowlist.** `_S1C_FORBIDDEN`
  (adapters.py:4700–4719) enumerates identity/scope names a client must never
  send; lee-kb's tool schemas are closed (`additionalProperties: false`) and
  expose only `query`, `limit` and the four exact-history locator fields.
  `KnowledgeNormalizer._receipt_values` (adapters.py:5490–5536) keeps exactly
  24 receipt names; every additive key lee-kb emits in owner-gateway mode is
  inside that set, and the artifact recomputes that from the live wire
  (`checks.wire_receipt_keys_within_consumer_allowlist`).

The consumer's `KnowledgeIdentityMapping.mapping_hash` (adapters.py:4827–4852)
hashes the same body shape as lee-kb's `OwnerIdentityMapping`
(`src/lee_kb/contracts.py:1051`), and its `canonical_sha256`
(`leeos/src/leeos/core/contracts.py:1439–1453`) uses the same parameters
(`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`). Identical
grant tuples therefore produce identical `mapping_hash` values; the artifact
records that agreement as `identity_mapping.mapping_hash_matches_consumer_algorithm`.
lee-kb accepts an empty grant tuple while the consumer requires at least one
grant, so the artifact's `identity_mapping.mapping_hash` is scoped to the
identity fields with an empty grant tuple. The deployment's real grants live in
the configuration file, and the wire probe compares the published handshake
against the mapping that configuration builds.

## 2. Deliver 1–4 mapping

`Satisfied` means the artifact computes the row as satisfied: the behaviour
probe observed exactly the required outcome **and** the row's evidence
requirement holds (a passing owner-native test, plus mutation detection where a
rule can regress silently).

| Row | Frozen requirement | lee-kb symbols | Tests | Outcome |
|---|---|---|---|---|
| `D1.owner_native_tests` | Deliver 1 — owner-native tests complete before the Core adapter | `src/lee_kb/owner.py:603` `OwnerGateway`, `src/lee_kb/governance.py:307` `ExactHistoricalReader` | `tests/test_owner.py` (23 tests), `tests/test_mcp.py` (27 tests), `python3 -m compileall -q src/lee_kb/owner.py` | satisfied |
| `D1.handshake_complete` | Deliver 1 — version/schema/corpus/identity/permission handshake complete | `src/lee_kb/owner.py:82` `owner_handshake`, `src/lee_kb/contracts.py:94–104` (`OWNER_*` versions), `src/lee_kb/mcp.py:968` `_handle_initialize` | `tests/test_owner.py` `test_owner_handshake_names_every_version`, `tests/test_mcp.py` `test_initialize_publishes_the_owner_handshake_in_owner_gateway_mode` | satisfied |
| `D1.field_receipt_freshness_parity` | Deliver 1 — field/receipt/freshness/recovery parity | `src/lee_kb/contracts.py:1357` `HistoricalReceipt`, `src/lee_kb/contracts.py:1519` `OwnerCurrentReceipt`, `:1634` `OwnerCurrentResult` | `tests/test_owner.py` `test_retrieve_current_binds_the_owner_receipt_to_mapping_and_policy`, `tests/test_mcp.py` `test_owner_gateway_releases_one_exact_history_object_with_its_receipt` | satisfied |
| `D2.immutable_server_mapping` | Deliver 2 — authenticated `lee` maps to `lee@leebase.com`, server-owned | `src/lee_kb/contracts.py:1051` `OwnerIdentityMapping`, `:1116` `resolve`, `:1009` `MappedIdentity`, `src/lee_kb/owner.py:639` `OwnerGateway.map_identity` | `tests/test_owner.py` `test_mapping_is_server_owned_and_client_identity_cannot_widen` | satisfied |
| `D2.clients_cannot_send_identity` | Deliver 2 — clients/delegates cannot send principal or groups | `src/lee_kb/mcp.py` `TOOL_DEFS` (closed schemas), `_tool_kb_history_get` exact-argument check, `src/lee_kb/contracts.py:1116` `resolve` (derives `Principal` with no groups) | `tests/test_mcp.py` `test_tool_surface_matches_kb_index_contract`, `test_forged_identity_arguments_are_rejected_at_the_wire`; live probe rejects an extra `principal` argument with `-32602` | satisfied |
| `D2.clients_cannot_widen_scope` | Deliver 2 — cannot widen project, source, root, path, or item or broaden filters | `src/lee_kb/contracts.py:1116` `resolve`, `:1148` `OwnerIdentityMapping.permits`, `:987` `SourceGrant.permits`, `src/lee_kb/owner.py:113` `_MappedPermissionEvaluator` | `tests/test_owner.py` `test_ungranted_project_is_rejected_before_retrieval`, `test_grants_narrow_namespace_root_path_and_item` (mutations `mapping_admits_ungranted_project` and `grant_ignores_path_prefix` both detected) | satisfied |
| `D2.multi_project_requires_grant` | Deliver 2 — multi-project requires an explicit grant and separate receipts | `src/lee_kb/contracts.py:1116` `resolve`, `src/lee_kb/owner.py:650` `retrieve_current` (one call, one granted project), `:1519` `OwnerCurrentReceipt.project` | `tests/test_owner.py` `test_multi_project_requires_one_explicit_granted_project` | satisfied |
| `D2.wire_identity_is_server_derived` | Deliver 2 — the frozen route derives identity from the server mapping only | `src/lee_kb/mcp.py:941` `_owner_bundle` (identity from `OwnerGatewayConfig.mapping`, configured `owner` ignored), `src/lee_kb/owner.py:650` `retrieve_current` | `tests/test_mcp.py` `test_owner_gateway_search_identity_comes_from_the_server_mapping`; live probe observed `mapped_principal=True|mapped_type=True|binds_mapping=True|configured_owner=False` | satisfied |
| `D3.current_requires_mapped_permission` | Deliver 3 — current release requires the mapped principal, project, source, root, path, item permission | `src/lee_kb/owner.py:650` `OwnerGateway.retrieve_current`, `:113` `_MappedPermissionEvaluator.is_permitted`, `src/lee_kb/governance.py` `retrieve(permission_evaluator=…)` | `tests/test_owner.py` `test_current_release_requires_the_mapped_permission` (mutation `mapped_current_evaluator_always_permits` detected) | satisfied |
| `D3.history_single_governed_locator` | Deliver 3 — exact history accepts only one governed `(repository, commit, path)` locator | `src/lee_kb/contracts.py:924` `HistoricalLocator`, `src/lee_kb/governance.py:341` `lookup(locator=…)`, `src/lee_kb/mcp.py` `kb_history_get` schema | `tests/test_owner.py` `test_exact_locator_rejects_patterns_traversal_and_refs` | satisfied |
| `D3.history_requires_versioned_manifest` | Deliver 3 — additionally requires a versioned source-owner historical-release manifest covering principal/project, exact locator and classification | `src/lee_kb/contracts.py:1250` `HistoricalReleaseManifest`, `:1308` `evaluate`, `:1200` `HistoricalReleaseRule.covers`, `src/lee_kb/owner.py:421` `load_owner_gateway` (manifest built and hashed from configuration) | `tests/test_owner.py` `test_missing_manifest_and_mismatched_classification_release_no_body`, `test_locator_outside_the_manifest_releases_no_body`, `test_ambiguous_manifest_rules_release_no_body`, `test_expired_manifest_releases_no_body` (both manifest mutations detected) | satisfied |
| `D3.no_substitution_for_manifest` | Deliver 3 — current visibility, repository reachability, a current receipt or semantic match cannot substitute | `src/lee_kb/governance.py:411–414` (current basis gate), `:558–571` `_resolve`, `src/lee_kb/owner.py:485` `GitExactObjectResolver` (one named object only), `src/lee_kb/mcp.py` `TOOL_DEFS` (no history search/cache tool) | `tests/test_owner.py` `test_history_requires_current_and_historical_policy_bases`, `test_absent_resolver_releases_no_body`, `test_git_exact_object_resolver_reads_exactly_one_named_object` | satisfied |
| `D4.receipt_binds_everything` | Deliver 4 — receipts bind bases/versions/hashes and decisions, mapped identity/scope, exact locator, classification, blob hash/time, evaluation time and audit id | `src/lee_kb/contracts.py:1357` `HistoricalReceipt` (32 fields; `audit_id` re-derived and verified in `__post_init__`), `src/lee_kb/governance.py:598–671` `_receipt`, `src/lee_kb/mcp.py` `_history_receipt_payload` | `tests/test_owner.py` `test_exact_success_has_complete_receipt_and_immutable_hash` | satisfied |
| `D4.non_enumerating_failure_states` | Deliver 4 — missing, ambiguous, drifted, stale, denied or mismatched bases return non-enumerating `UNKNOWN`/unauthorized before body release | `src/lee_kb/governance.py:367–537`, `src/lee_kb/contracts.py:1491` `HistoricalLookupResult.__post_init__`, `src/lee_kb/mcp.py` `UNKNOWN_HISTORY` (one shape for every withheld basis) | `tests/test_owner.py` (classification, locator, ambiguity, expiry, staleness, denial, unmapped principal), `tests/test_mcp.py` `test_owner_gateway_history_denials_are_identical_and_release_no_body` | satisfied |

Deliver 5 (adapter evaluation/freeze), 6 (Core normalization) and 7 (artifact)
are consumer-owned, but two of them bind this repository:

| Row | Frozen requirement | lee-kb symbols | Outcome |
|---|---|---|---|
| `D5.frozen_candidate_full_contract` | Deliver 5 — the frozen persistent-MCP candidate must pass the full identity/mapping, receipt and exact-history contract | `src/lee_kb/mcp.py:291` `_runtime`, `:941` `_owner_bundle`, `:968` `_handle_initialize`, `:1214` `_tool_kb_history_get`; `pyproject.toml` `lee-kb-mcp` console script | satisfied |
| `D7.artifact_fields` | Deliver 7 — content-free artifact names owner repository/version, commands, schema/corpus/identity, matrices, receipt fields, no-write result, adapter candidates and final handshake | `tools/produce_s1c_owner_evidence.py`, `evidence/s1c/S1C-lee-kb.json` | satisfied |

## 3. Acceptance mapping

| Row | Frozen acceptance bullet | lee-kb evidence | Outcome |
|---|---|---|---|
| `A1.owner_artifact_validates` | Owner artifact validates independently; owner-native and Core contract tests pass | artifact self-validation (`checks.artifact_sections_present`, `checks.artifact_is_content_free`), `tests/test_owner.py`, `tests/test_mcp.py`. Core contract tests are consumer-side and out of this slice | satisfied (owner side) |
| `A2.denial_before_body` | Denial occurs before evidence/body/model work and produces the safe non-enumerating receipt state | `src/lee_kb/governance.py:380–409` (grant check precedes `_resolve`), `:411–436` (current basis precedes `_resolve`), `:476` (resolver called last). Owner-native tests count exact-object seam calls and assert `0` on the widened-path, unmapped-principal, ambiguity, expiry, staleness and current-denial paths | satisfied |
| `A3.receipts_map_losslessly_or_fail_closed` | Current/history, source/effective/retrieval time, freshness row/state, role/basis, supersession/conflict/absence and exact-reference receipts map losslessly or fail closed | `src/lee_kb/contracts.py:1357` `HistoricalReceipt` and `:1519` `OwnerCurrentReceipt` are complete against the frozen field lists; every additive wire key is inside the consumer's receipt allowlist | satisfied |
| `A4.deterministic_recovery_cases` | REC-08 crash/version/schema/corpus/timeout/cancel cases behave deterministically | `src/lee_kb/governance.py:307` `ExactHistoricalReader` takes only `mapping`, `manifest`, `current_permission`, `resolver`, `clock`: no timeout/cancel surface, and every resolver exception degrades to `UNKNOWN` (`:558–571`). The exact-object seam is itself time- and size-bounded (`src/lee_kb/owner.py:485`). Process timeout, cancel and restart are consumer-side by construction | satisfied (owner side, scope-limited) |
| `A5.repeated_queries_reread` | Repeated current queries re-read lee-kb; an older observation cannot satisfy them | two identical `kb_search` calls over live stdio produced distinct receipt ids and persisted rows (`no_write.persisted_current_receipts`), `tests/test_mcp.py` `test_kb_search_preserves_result_shape_and_attaches_receipts` | satisfied |
| `A6.one_route_no_fallback` | One production route is live; loser, direct-store fallback, dual-route code/config and historical search/cache absent | `src/lee_kb/mcp.py` `TOOL_DEFS` exposes exactly `kb_search`, `kb_status`, `kb_compile_preview`, `kb_history_get`; no history search or cache tool; the no-write proof holds | satisfied (owner side; route selection/removal is consumer-side) |

## 4. Topic-by-topic detail

### Modes and their precedence

`mcp._runtime` (`src/lee_kb/mcp.py:291`) resolves exactly one mode per process:

1. **Employee mode** — `LEE_KB_CLIENT_ID` is present in this server's own
   environment. Unchanged by this slice.
2. **Owner-gateway mode** — the configuration file carries `[owner_gateway]`.
   Identity, project and grants come from the versioned mapping; the top-level
   `owner` key is ignored for identity.
3. **Legacy owner mode** — neither of the above. Byte-identical to before:
   `Principal(owner)` from configuration, no `serverInfo.owner`, and
   `kb_history_get` answers the non-enumerating `UNKNOWN`.

Employee credentials **and** `[owner_gateway]` together are a configuration
error (`employee credentials and owner-gateway configuration cannot both be
set`): two identity authorities would make the released scope ambiguous, so the
process fails closed instead of choosing one.

### Immutable server-side mapping `lee` → `lee@leebase.com`

`OwnerIdentityMapping` (`src/lee_kb/contracts.py:1051`) is a frozen slotted
dataclass whose `authenticated_principal`/`principal_id` default to `lee` and
`lee@leebase.com` with `tenant=leebase`, `lane=default`, `scope_id=leeos`,
`purpose=knowledge`, `version=lee-kb.owner.mapping/v1`, and a `mapping_hash`
derived from the canonical body (`:1084–1107`). `resolve` (`:1116`) refuses any
other authenticated principal with `PermissionError("owner identity is not
authorized")`, and returns a `MappedIdentity` whose `Principal` has **no**
groups. `OwnerGateway.map_identity` (`src/lee_kb/owner.py:639`) is the only
entry point and takes no identity data beyond the authenticated principal name
and an optional already-granted project. A configured `mapping_hash` that does
not match the configured body is a configuration error, so mapping drift cannot
be deployed silently.

### Clients cannot send principal/groups or widen scope

Every wire schema is closed and identity-free (`src/lee_kb/mcp.py` `TOOL_DEFS`),
`kb_history_get` additionally requires the argument set to equal
`{repository, commit, path, classification}` exactly, and the live probe
confirms an extra `principal` argument is answered with JSON-RPC `-32602`.
Scope narrowing is enforced by `SourceGrant.permits`
(`src/lee_kb/contracts.py:987`) over project, source namespace, root, path
prefix and item id, aggregated by `OwnerIdentityMapping.permits` (`:1148`) and
applied to current release by `_MappedPermissionEvaluator`
(`src/lee_kb/owner.py:113`), which reads the item's **own** `(namespace, root,
path)` through the injected source mapping rather than inferring the root from
the grants.

`retrieve_current` binds one call to exactly one granted project. An unmapped
principal, an ungranted project and an ambiguous multi-project selection all
raise the same `OwnerAccessError("owner request is not permitted")` before any
retrieval runs, so the refusal names no basis.

### Exact-history locator, versioned release manifest and the object seam

`HistoricalLocator` (`src/lee_kb/contracts.py:924`) accepts exactly one
`(repository, commit, path)` triple: full lowercase 40/64-hex commit, relative
path, no empty/`.`/`..` component, no `*?[]{}`. `ExactHistoricalReader.lookup`
(`src/lee_kb/governance.py:341`) takes one `locator`, never a list, and requires
`HistoricalReleaseManifest.evaluate` (`src/lee_kb/contracts.py:1308`) to return
exactly one covering rule for `(principal_id, project, locator, classification,
at)`; zero or multiple matches, or an expired manifest, degrade to
`PolicyBasis.unknown`. A missing manifest is treated as unknown.

The body itself comes from `GitExactObjectResolver`
(`src/lee_kb/owner.py:485`), the supported exact-object seam. It is not a
walker, a searcher, a cache or a network client:

- the repository **name** must be in the `[owner_gateway.repositories]`
  allowlist, and its configured worktree path must be absolute and present;
- `git -C <worktree> rev-parse --verify --quiet <commit>^{commit}` must return
  the requested commit verbatim, so an abbreviation or a branch name cannot
  resolve;
- `git show -s --format=%cI <commit>` supplies the immutable blob timestamp;
- `git cat-file -s <commit>:<path>` bounds the size before
  `git cat-file blob <commit>:<path>` reads it — anything above 1 MiB, any tree,
  and any non-UTF-8 object is refused;
- every invocation is `subprocess.run` with a fixed argv, no shell, a minimal
  environment and a 5 s timeout;
- the object's classification is the one the source owner declared for that
  exact locator; an undeclared locator resolves to nothing.

Any refusal returns `None`, which the reader turns into the safe
non-enumerating `UNKNOWN`.

### Receipts

`HistoricalReceipt` (`src/lee_kb/contracts.py:1357`) binds all 32 required
fields, re-derives `audit_id` from the canonical body in `__post_init__`, and
refuses a `KNOWN` receipt without both `allow` decisions, a manifest hash, a
blob hash and a blob timestamp. `OwnerCurrentReceipt` (`:1519`) is the additive
current-release parity carrier: mapped identity and mapping hash, project,
item/chunk/content hash, source locator, the mapped `(namespace, root, path,
item)` scope, the item's classification, the current permission basis
(`lee-kb.owner.permission/v1` plus the mapping hash and decision), the freshness
state, the retrieval timestamp and a re-derived `audit_id`. The **persisted**
`RetrievalReceipt` (`:638`) is deliberately unchanged, so the projection and its
stored rows keep their schema.

On the wire, owner-gateway mode adds those names to each `kb_search` receipt and
returns a full `receipt` object plus an allowlist-clean `receipts` array from
`kb_history_get`. Every additive name is inside the consumer's receipt
allowlist; the artifact recomputes the difference from the live payloads rather
than trusting this paragraph.

### Non-enumerating UNKNOWN and current-permission requirement

Every failure path in `lookup` returns `OwnerKnowledgeState.UNKNOWN` or
`UNAUTHORIZED` with `body=None`, `error=None`, and a receipt that names no
reason (`src/lee_kb/governance.py:367–537`); the unmapped-principal path returns
no receipt at all. `HistoricalLookupResult.__post_init__`
(`src/lee_kb/contracts.py:1491`) makes a body on a non-`KNOWN` result
structurally impossible. Over the wire, `mcp._history_payload` emits the single
`UNKNOWN_HISTORY` shape for every withheld basis — missing scope, classification
mismatch, locator mismatch, rule ambiguity, expiry, staleness, unmapped
principal, resolver failure and current-permission denial are byte-identical,
and the artifact proves that by hashing the four probed denials.

### Version/schema/corpus/identity/permission handshake

`initialize` returns `serverInfo.owner` in owner-gateway mode only:

```json
{"owner": "lee-kb", "api_version": "lee-kb.owner.api/v1",
 "contract_version": "lee-kb.owner.contract/v1",
 "schema_version": "lee-kb.owner.schema/v1",
 "corpus_version": "lee-kb.owner.corpus/v1",
 "mapping_version": "lee-kb.owner.mapping/v1", "mapping_hash": "<sha256>",
 "permission_version": "lee-kb.owner.permission/v1",
 "receipt_version": "lee-kb.owner.receipt/v1",
 "historical_version": "lee-kb.owner.historical-release/v1"}
```

The first nine names and values are exactly what `_s1c_handshake_ok`
(adapters.py:5274–5286) compares its own constants against;
`historical_version` is additive. The artifact's wire probe compares the
published object against `owner.owner_handshake(configured_mapping)` field by
field.

### No-write

The artifact's `no_write` section snapshots every file in a purpose-built
temporary corpus, runs `lee-kb sync`, `lee-kb search`, a live stdio
`kb_search` ×2, a live stdio `kb_history_get` release plus four denials, and an
in-process `OwnerGateway.retrieve_history`, then re-snapshots. Digests and file
count are unchanged; the sqlite projection and receipts are written outside the
corpus, as designed. The history repository is created by the generator inside
the same temporary directory and is only ever read through git plumbing.

## 5. Owner-gateway configuration

Owner-gateway mode is a single TOML table in the lee-kb configuration file
(`LEE_KB_CONFIG`). It is parsed by `owner.load_owner_gateway`
(`src/lee_kb/owner.py:421`) into `OwnerGatewayConfig` (`:167`); any problem
raises `OwnerConfigurationError`, which `mcp._runtime` reports as a
deployment error rather than degrading to another mode.

```toml
[owner_gateway]
# Optional. Required when the mapping grants more than one project: it binds
# every kb_search call to exactly one granted project.
project = "default"

[owner_gateway.mapping]
authenticated_principal = "lee"          # default "lee"
principal_id = "lee@leebase.com"         # default "lee@leebase.com"
tenant = "leebase"                       # default "leebase"
lane = "default"                         # default "default"
scope_id = "leeos"                       # default "leeos"
purpose = "knowledge"                    # default "knowledge"
version = "lee-kb.owner.mapping/v1"      # default OWNER_MAPPING_VERSION
# Optional. When present it must equal the hash of the configured body.
mapping_hash = "<sha256>"

# One or more. At least one grant is required.
[[owner_gateway.mapping.grants]]
project = "default"
source_namespace = "local_files"
root = "notes"
path_prefix = "*"                        # "*" = whole root; otherwise a literal
item_ids = []                            # optional; empty = every item

[owner_gateway.historical_release]
version = "lee-kb.owner.historical-release/v1"
expires_at = "2027-01-01T00:00:00+00:00" # optional, must carry a UTC offset
manifest_hash = "<sha256>"               # optional; verified when present

# One or more. Each rule releases exactly one immutable object.
[[owner_gateway.historical_release.rules]]
repository = "history"                   # must be in [owner_gateway.repositories]
commit = "<40 or 64 lowercase hex>"
path = "docs/fact.md"                    # exact relative path, never a pattern
classification = "public"
principals = ["lee@leebase.com"]
projects = ["default"]
source_namespace = "local_files"         # the grant scope the object belongs to
root = "notes"
item_id = "local_files:docs/fact.md"     # optional
decision = "allow"                       # optional, "allow" (default) or "deny"
not_before = "2026-01-01T00:00:00+00:00" # optional
not_after = "2027-01-01T00:00:00+00:00"  # optional

[owner_gateway.repositories]
history = "/absolute/path/to/worktree"
```

Notes on the deliberate shapes:

- **Rules are exact, not prefixes.** A release rule names one
  `(repository, commit, path)` triple, because a path prefix would authorize
  objects the source owner has never reviewed, including ones committed later.
  The rules cross-product `principals × projects` into
  `HistoricalReleaseRule` values, and the whole set is hashed into one
  versioned `HistoricalReleaseManifest`; two rules covering the same request
  are an ambiguity and fail closed.
- **The wire cannot name a scope.** `source_namespace`, `root` and `item_id`
  come from the matching rule, never from a tool argument, so a client cannot
  point an exact locator at a scope it was not granted.
- **The repository allowlist is names, not paths.** A locator names
  `repository = "history"`; only the configuration maps that to a worktree.
- **Grants are deployment configuration.** They change `mapping_hash`, which is
  published in the handshake, so a grant change is visible to the consumer.

## 6. Artifact schema — `lee-kb.owner.acceptance/v1`

`evidence/s1c/S1C-lee-kb.json`, top-level keys (JSON object, sorted keys, 2-space
indent, trailing newline):

| Field | Type | Meaning |
|---|---|---|
| `version` | string | `lee-kb.owner.acceptance/v1` |
| `artifact_id` | string | `S1C-lee-kb` |
| `status` | string | `accepted` only when `failure_reasons` is empty, otherwise `failed` |
| `failure_reasons` | string[] | one entry per failing command, per no-write failure, and per unsatisfied contract-row reason |
| `generated_at` | string | UTC RFC3339, second precision |
| `owner_repository` | object | `name`, `owner_repository_commit` (`git rev-parse HEAD`), `dirty`, `dirty_file_count`, `package_version` (from `pyproject.toml`), `contract_document`, `generator`, `console_scripts` |
| `versions` | object | `owner_api_version`, `owner_schema_version`, `owner_corpus_version`, `owner_contract_version`, `owner_mapping_version`, `owner_historical_release_version`, `access_policy_version`, `projection_schema_version`, `mcp_protocol_version`, `python_version` |
| `identity_mapping` | object | `authenticated_principal`, `principal_id`, `principal_type`, `tenant`, `lane`, `scope_id`, `purpose`, `mapping_version`, `mapping_hash`, `mapping_hash_scope`, `mapping_hash_body_keys`, `mapping_hash_algorithm`, `mapping_hash_matches_consumer_algorithm`, `grants_are_deployment_configuration`, `client_supplied_identity_fields` (always empty) |
| `commands` | object[] | `name`, `argv`, `returncode`, `output_sha256`, `output_bytes`, `output_normalization` |
| `handshake` | object | live stdio facts: `candidate`, `executable_token`, `probe_argv`, `probe_env_keys`, `console_script_declared`, `protocol_version`, `capabilities`, `server_name`, `server_version`, `tools`, `required_tools`, `required_tools_present`, `owner_handshake_fields_exposed`, `owner_handshake_fields_required`, `owner_handshake_matches_owner_versions`, `current` (payload/receipt **key names**, principal and mapping booleans, additive-key allowlist diff, repeat-receipt boolean), `history` (payload and receipt key names, state, `body_released`, `receipt_present`, `receipt_missing_required`, `listed_receipt_keys_outside_consumer_allowlist`, `release_capable`, `denied_states`, `denials_release_no_body`, `denials_are_indistinguishable`, `identity_argument_rejected`), `probe_ok`, `probe_error`, `exit_code` |
| `permission_matrices` | object | `current` and `history` arrays of `{case_id, expectation, outcome, observed, expected, evidence, test_id, test_returncode, mutation, mutation_detected, reasons}` |
| `receipt_fields` | object | field-name lists introspected from the dataclasses, the required-field diffs, the required wire receipt names and the consumer receipt allowlist |
| `no_write` | object | `proof` (`corpus_file_count`, `corpus_unchanged`, `corpus_digest`, `corpus_digest_stable`, `digest_algorithm`), `cycle_steps`, `persisted_current_receipts`, `owner_history` |
| `adapter_candidates` | object[] | the selected stdio candidate and the never-trialled python-api candidate with its `GATE-DEP-001` reason |
| `contract_rows` | object[] | `{row_id, source, requirement, cases, checks, satisfied, reasons}` for every frozen row in sections 2–3 |
| `checks` | object | named booleans with a human `detail` string; contract rows reference them |
| `symbol_locations` | object[] | `{symbol, file, line}` read with `inspect` at generation time |
| `mutation_probes` | object[] | `{mutation, file, applied, effective, suite, suite_returncode, detected}` |
| `determinism` | object | normalization description, `volatile_fields`, `stable_body_scope` |
| `provenance` | object | content-free statement, generator, contract document, evidence basis |
| `stable_body_sha256` | string | canonical sha256 of the artifact minus `determinism.volatile_fields` |
| `artifact_sha256` | string | canonical sha256 of the artifact minus `artifact_sha256` |

Canonical hashing for both digests is
`sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))`.

### How each field is computed

- **`commands`** — four real runs: `python3 -m pytest tests/test_owner.py -q`,
  `python3 -m pytest tests/test_mcp.py -q`,
  `python3 -m compileall -q src/lee_kb/owner.py`, and the live stdio probe.
  `argv[0]` is recorded as the token `python3`; the generator executes
  `sys.executable` so the artifact stays machine-independent.
- **`handshake`** — a real `lee_kb.mcp` subprocess with the consumer's minimal
  environment (`PATH`, `LANG`, `LC_ALL`, `LEE_KB_CONFIG`, plus `PYTHONPATH`
  because the probe runs from the source checkout instead of an installed
  console script). It performs the consumer's own `initialize` + `tools/list`
  handshake, compares `serverInfo.owner` against
  `owner.owner_handshake(configured_mapping)`, asserts `kb_search` and
  `kb_history_get`, then probes identity, repeat-read, one real exact-history
  release against a git repository the generator creates (`git init`, one
  commit), and four denial cases. Only tool names, key names, the protocol
  version and booleans are recorded.
- **`permission_matrices`** — each case runs an in-process behaviour probe, and
  where the rule can regress silently it also runs the named focused test
  (`pytest -q <test id>`, exit code recorded) and a mutation probe. A case is
  `satisfied` only if the observation equals the required token, the named test
  exits 0, and the mutation was detected. `evidence: "structural"` marks cases
  that assert an API/wire/route shape, where this generator's probe is the
  evidence and no test is demanded.
- **`mutation_probes`** — each mutation is appended to a private copy of
  `src/lee_kb` in a temporary directory (the working tree is never modified),
  `effective` is proven by a separate verifier program that must observe the
  broken rule, and `detected` is `tests/test_owner.py` failing afterwards.
- **`no_write`** — sha256 of every file in a purpose-built temporary corpus
  before and after the full cycle; only counts, digests and booleans are kept.
- **`receipt_fields`** — `dataclasses.fields` on `HistoricalReceipt`,
  `RetrievalReceipt`, `OwnerCurrentReceipt`, `Evidence`, `Citation`,
  `EvidenceBundle`, `FreshnessReport`, `RetrievalAuditEvent`,
  `AccessAuditEvent`, `HistoricalLookupResult`.

### Determinism

`stable_body_sha256` is byte-reproducible on the same toolchain. Excluded
volatile fields: `generated_at`, `artifact_sha256`, `stable_body_sha256`,
`owner_repository.owner_repository_commit`, `owner_repository.dirty`,
`owner_repository.dirty_file_count`. The temporary history repository's commit
hash never enters the artifact: only key names, states and booleans derived from
it are recorded.

Command digests hash **normalized** output, because pytest embeds wall-clock
durations and absolute temporary paths. Normalization (`pytest-normalized/v1`)
replaces, in order: absolute temporary, repository, home, and prefix paths with
`<tmp>`/`<repo>`/`<home>`/`<prefix>`, RFC3339-ish timestamps with
`<timestamp>`, `N.NNNs` and `N.NN seconds` durations with `<duration>`, and
32-or-more-hex-digit runs with `<digest>`; then it strips trailing whitespace
per line and normalizes the final newline. `output_bytes` is the length of that
normalized text. The stdio handshake command's digest
(`content-free-handshake/v1`) is the canonical hash of
`{protocol_version, tools}` only.

Remaining sources of legitimate difference between two runs: the interpreter
and pytest versions (recorded in `versions.python_version`), the repository
commit and dirty flag, and `generated_at`.

### Content-free rule

The artifact contains no source content, question text, corpus path lists or
evidence bodies. It contains only lee-kb's own root-relative file names, symbol
names, test ids, schema key names, digests, counts, enum values and booleans.
The generator enforces this before finalizing: `checks.artifact_is_content_free`
fails if any `body`/`text`/`query`/`question`/`snippet`/`paths` key holds a
string, or if any string echoes the probe corpus text, the probe query or the
released historical body.
