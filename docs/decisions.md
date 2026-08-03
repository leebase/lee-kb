1. Identity: what makes a knowledge item and chunk ID stable?
Receipts and citations reference evidence by ID. If re-syncing a changed document re-chunks it and mints new chunk IDs, every old receipt dangles. You need a deliberate scheme — something like item ID = (connector, source_id), chunk ID = (item_id, position, content_hash) — and a decision about what a receipt points at when the underlying chunk has since changed. Recommendation: receipts store both the chunk ID and the content hash at retrieval time, so a receipt is verifiable forever even if the projection has moved on.

2. History: latest-only projection, or versioned?
Your use cases include "When did this bug first appear?" and "executive briefing on what changed this week" — both are questions about change over time, and a latest-only projection can't answer them. Versioning everything doubles schema complexity. Recommendation: latest-only chunks for v1, but keep an append-only sync journal (item, content hash, timestamp, change type) from day one. It's cheap, it makes "what changed this week" answerable, and it defers full versioning without foreclosing it.

3. Deletion semantics.
A source file gets deleted — hard-delete the projection, or tombstone it? Tombstones keep receipts resolvable and support "this used to exist"; hard deletes are what a client's compliance team will demand ("when it's gone from SharePoint, it's gone from you"). Recommendation: tombstone by default, with a purge operation. This becomes a sales-relevant governance feature later, so make it explicit now.

4. Schema migration strategy.
You will change the schema — semantic search, projects, permissions are all coming. Decide now: schema version number in the database and a migration mechanism from the first release, or "wipe and re-sync" as the official upgrade path while personal-only? Recommendation: a stored schema version plus wipe-and-resync as the documented v1 upgrade path is honest and cheap — the projection is disposable by design; the sources are authoritative. Real migrations start when someone other than you deploys it.

5. The retrieve() request contract.
Everything downstream depends on this signature: query string, top_k, metadata filters (which fields are filterable — source, date range, project?), freshness requirement, principal. Recommendation: define it as a frozen dataclass in S1-01 with exactly those six things, and let the filter grammar be simple equality/range on a fixed field list — no query language.

Shaping — decide before sprint execution, they direct what gets built

6. Is MCP a surface in the plan at all?
Your docs define retrieve() and answer(), and the whole thesis is AI employees as consumers — but neither the project plan nor sprint plan mentions an MCP server. Given that you'd be your own first agent-consumer (Claude Code querying lee-kb), MCP may be the highest-value surface after the library itself, and it's a thin wrapper over retrieve(). Recommendation: library core + CLI in Sprint 1 (answers your open question #3: both, CLI as thin shell), MCP server as an explicit early Phase 2 item — it's also your best demo for the Factory pitch.

7. How is sync triggered?
Explicit lee-kb sync command, a scheduler/daemon, or filesystem watching? A daemon is a very different operational commitment. Recommendation: explicit CLI sync only for v1; freshness reporting makes staleness visible, which is your stated philosophy anyway. No daemon until it hurts.

8. Where does configuration live?
Sources, roots, include/exclude patterns, eventually projects — Cerebras made self-service config files a feature. Decide format and location (e.g., ~/.lee-kb/config.toml + per-project files). Recommendation: one TOML file, schema documented, treated as a public contract from day one since client deployments will live and die by it.

9. What does "good retrieval" mean, measurably?
Your success metric says "users can answer representative questions" — but nothing defines the question set. Without it, the Phase 2 gate ("lexical establishes a measurable baseline before semantic") can't actually be evaluated. Recommendation: a small golden set — 15–20 real questions against your real documents with expected source hits — built during Sprint 1 as a test fixture. This is the cheapest high-leverage item on this list.

10. Does Project appear in the v1 schema?
You just added Projects to the architecture; the sprint predates it. Retrofitting a scoping column into every query path later is annoying. Recommendation: a project column with a single default value in v1 — the concept exists in the schema, the feature waits.

Explicitly deferred — name them so nobody designs for them accidentally

Embedding/semantic provider choice (schema reserves nothing; the sync journal and content hashes are enough to rebuild), reranking, distillation implementation (the concept is in the model; the LLM ingest pipeline waits for the email connector), Postgres provider, multi-user auth internals, and targeted refresh.

The one existing open question I'd push back on: context.md still frames the second connector as "Outlook or GitHub" and project-plan Phase 2 says the same — yesterday's discussion landed on email as the leading candidate for product reasons (conversational corpus, forces distillation, every client has one). Worth updating Phase 2 to reflect that lean.

If you want, give me your calls on these (or just "take your recommendations") and I'll record the decisions in context.md's Decisions Locked table, refresh the open-questions list, and fold anything that changes scope into sprint-plan.md.


Decisions:

I agree with almost all of those recommendations. There are only a couple where I’d tweak the direction based on what we’ve discussed over the last day. Here’s the response.md I’d give Codex.

Response to Architecture Review

Thank you. This review raises exactly the kinds of decisions that should be locked before implementation begins.

Below are the project decisions.

⸻

1. Identity

Decision

Accepted with one refinement.

Knowledge item identity should be stable for the lifetime of the source object.

Proposed model:

Knowledge Item ID
    = (connector_id, source_object_id)
Chunk ID
    = (knowledge_item_id, chunk_ordinal, content_hash)

Chunk IDs intentionally change when chunk contents change.

Retrieval receipts must therefore never rely solely on a chunk identifier.

Each receipt will store:

* knowledge item ID
* chunk ID
* content hash
* source locator
* retrieval timestamp

This guarantees a receipt remains independently verifiable even after the current projection has evolved.

The repository stores the latest projection.

Receipts preserve the historical evidence that was actually retrieved.

⸻

2. History

Decision

Accepted.

The knowledge repository remains a latest-state projection.

Versioning every chunk and every document from day one adds significant complexity without immediate value.

However, an append-only synchronization journal will exist from the first release.

Minimum journal contents:

* connector
* source object
* content hash
* synchronization timestamp
* change type
* previous content hash

This supports questions such as:

* What changed this week?
* When did this document first change?
* When was this connector last updated?

without requiring full historical reconstruction.

Future releases may introduce full historical document versions if justified.

⸻

3. Deletion Semantics

Decision

Accepted.

Deletion should become an explicit governance policy.

Default behavior:

* knowledge item becomes tombstoned
* source metadata retained
* retrieval receipts remain resolvable
* knowledge no longer appears in ordinary search

Optional purge policies may permanently remove the projection.

Client deployments will eventually configure deletion policy according to governance requirements.

⸻

4. Schema Migration

Decision

Accepted.

Version 1 will include:

* stored schema version
* migration framework
* documented wipe-and-resync upgrade path

The knowledge projection is intentionally disposable.

Authoritative systems remain the source of truth.

Real schema migrations become mandatory once customer deployments begin.

⸻

5. retrieve() Contract

Decision

Accepted.

The retrieval contract becomes a first-class API.

Initial request fields:

* query
* principal
* top_k
* metadata filters
* freshness requirement
* project

Metadata filtering remains intentionally simple.

Supported filters initially:

* connector
* project
* date range
* document type
* tags

No query language in v1.

⸻

6. MCP Surface

Decision

Accepted with clarification.

The library remains the primary product.

The CLI becomes the first user interface.

The MCP server becomes an explicit Phase 2 deliverable.

Architecture should ensure:

CLI
    ↓
MCP Server
    ↓
Knowledge Library

Both consumers should exercise the exact same public retrieval API.

⸻

7. Synchronization

Decision

Accepted.

Version 1 synchronization is explicitly user-driven.

Supported mechanisms:

* lee-kb sync
* lee-kb sync 
* lee-kb sync 

Freshness reporting informs users when indexed knowledge may be stale.

Filesystem watchers and background services are intentionally deferred.

⸻

8. Configuration

Decision

Accepted.

Configuration becomes a documented public contract.

Initial location:

~/.config/lee-kb/config.toml

Project-specific configuration may later override global settings.

Configuration should include:

* connectors
* roots
* include patterns
* exclude patterns
* schedules (future)
* projects
* retrieval defaults

⸻

9. Retrieval Quality

Decision

Accepted.

A measurable retrieval benchmark becomes part of Sprint 1.

Create a golden evaluation corpus consisting of approximately twenty real questions against real personal data.

Each test records:

* expected evidence
* expected source
* expected citation

Lexical retrieval establishes the initial baseline.

Semantic retrieval must demonstrate measurable improvement before replacing lexical-only retrieval.

⸻

10. Project Support

Decision

Accepted.

Projects become part of the v1 schema.

Every knowledge item belongs to exactly one project.

Version 1 may simply use:

default

for every existing item.

The schema therefore supports future multi-project deployments without later structural changes.

⸻

Deferred Work

Explicitly defer:

* embedding provider
* semantic provider
* reranking
* document distillation
* PostgreSQL implementation
* Snowflake implementation
* multi-user authorization
* targeted refresh
* daemon synchronization
* filesystem watching

The architecture should reserve extension points but avoid premature implementation.

⸻

Email Connector

Agreed.

The second connector should be email rather than GitHub.

Rationale:

Email provides significantly broader product value.

It exercises:

* conversational knowledge
* threading
* metadata extraction
* document relationships
* summarization
* future distillation

Every customer has email.

Not every customer has GitHub.

GitHub remains an important connector but no longer defines the early product.

⸻

Additional Architectural Decision

One additional decision should be explicitly recorded.

lee-kb is a platform.

It is not an Agent-Orch subsystem.

Agent-Orch, Agentflow, Chief of Staff, Employee Zero, and future customer AI employees are all consumers of the same public knowledge platform.

The dependency direction is therefore:

Consumers
Chief of Staff
Agentflow
Agent-Orch
Employee Zero
Customer AI Employees
        ↓
lee-kb
        ↓
Connectors
Outlook
OneDrive
GitHub
Local Files
Agent-Orch
Snowflake
Teams
Telegram
...

This keeps lee-kb reusable, consumer-agnostic, and independently evolvable.

⸻

Overall Assessment

No architectural blockers were identified.

The review materially strengthened the architecture by locking several important contracts before implementation.

The project should now proceed with:

1. architecture documents
2. repository contracts
3. connector contracts
4. retrieval contracts
5. first SQLite vertical slice
6. lexical retrieval baseline
7. email connector
8. MCP surface

before introducing semantic retrieval or additional persistence providers.

The only substantive change I’d make is to #10 (Projects).

After thinking about it more, I would actually make project_id required, not optional. Even if every record initially belongs to "default", forcing every knowledge item through a project boundary from day one will make customer multi-tenancy, scoping, and selective synchronization much cleaner later. It costs almost nothing now and avoids retrofitting one of the most fundamental dimensions of the data model later.
