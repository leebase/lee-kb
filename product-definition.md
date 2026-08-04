# Lee Knowledge Base (lee-kb)

## Product Vision

Lee Knowledge Base (lee-kb) is a Governed Knowledge Fabric that provides a unified, searchable, permission-aware view of organizational knowledge without requiring organizations to migrate their data into a single repository.

Rather than replacing existing systems, lee-kb connects to them, periodically synchronizes their contents into a normalized knowledge projection, and provides governed retrieval for both humans and AI employees.

The authoritative copy of every artifact remains in its original system.

lee-kb provides the experience of "knowing everything at once" while preserving ownership, governance, provenance, and freshness.

---

# Problem Statement

Organizations accumulate knowledge across dozens of disconnected systems.

Examples include:

- local documents
- OneDrive
- SharePoint
- Outlook
- Gmail
- Teams
- Telegram
- GitHub
- source code
- CI/CD systems
- project documentation
- Agent-Orch
- Agent Board
- Snowflake
- SQL databases
- customer systems

Humans waste significant effort remembering where information lives.

AI systems typically solve this by copying documents into another repository.

Large "move everything into one place" initiatives almost always become expensive, difficult to maintain, and eventually stale.

lee-kb takes the opposite approach.

Leave knowledge where it naturally belongs.

Synchronize only enough information to make it searchable.

---

# Vision

Provide one governed interface through which humans and AI employees can answer questions using knowledge distributed across many systems.

The user should never have to remember where information lives.

---

# Product Principles

## Federated ownership

Original systems remain authoritative.

lee-kb stores a searchable projection.

---

## Connector-first architecture

Everything enters through connectors.

There are no privileged knowledge sources.

Agent-Orch is simply another connector.

GitHub is simply another connector.

Outlook is simply another connector.

---

## Unified knowledge

Application development state is not a special category of knowledge.

It is knowledge obtained through one or more connectors.

Emails are knowledge.

Mission receipts are knowledge.

Documents are knowledge.

Database rows are knowledge.

Everything becomes normalized knowledge.

---

## Governance first

Retrieval never bypasses authorization.

Permission filtering occurs before evidence reaches an AI model.

Retrieving evidence never authorizes an action.

Execution authority remains outside the knowledge system.

---

## Evidence before answers

Every answer should be backed by evidence.

Users should always be able to inspect original sources.

---

## Auditable retrieval

Every retrieval produces a Retrieval Receipt: what evidence was retrieved, why, and under what permissions.

This is a headline capability, not an implementation detail. It is the answer to "how do we let an AI employee near our data?" — and it is always on, even in single-user deployments.

---

## Freshness matters

Every answer should know:

- when the source changed
- when it was synchronized
- whether it satisfies the requested freshness requirement

If necessary, connectors may refresh before answering.

---

## Configurable persistence

Persistence is configurable.

Supported persistence targets include:

- SQLite
- PostgreSQL
- Snowflake

No architectural decisions should assume one specific database.

---

## Provider abstraction

Search, embeddings, reranking, and persistence are configurable providers.

The product should never assume a particular vector database or embedding provider.

---

# Users

Primary users:

- Lee
- Chief of Staff
- AI Employees
- Employee Zero

Future users:

- customer AI employees
- customer executives
- customer engineers
- customer support agents

---

# Primary Use Cases

## Personal knowledge

"What proposal did I send TVIQ?"

---

## Organizational memory

"Why was this architectural decision made?"

---

## Application health

"What is the current state of Agent-Orch?"

---

## Customer knowledge

"What commitments have we made to Acme?"

---

## Development history

"When did this bug first appear?"

---

## Executive briefing

"What happened across all projects this week?"

---

## AI employee context

Provide governed evidence for autonomous AI employees.

---

# Non-Goals

lee-kb is not:

- a replacement for SharePoint
- a replacement for GitHub
- a replacement for Outlook
- a replacement for document management systems
- an execution engine
- an authorization engine
- a workflow engine

---

# Core Concepts

## Connector

Synchronizes knowledge from a source.

Examples:

- Outlook
- GitHub
- Local Files
- OneDrive
- Agent-Orch

---

## Knowledge Item

Normalized representation of a source artifact.

---

## Chunk

Retrievable portion of a Knowledge Item.

A chunk is either a direct slice of source content or a derived artifact.

---

## Derived Artifact

An LLM-normalized distillation of conversational content: question, summary, resolution, systems, references.

Email threads, Teams conversations, and chat channels retrieve poorly as raw transcripts and well as derived artifacts.

---

## Project

A named bundle of knowledge sources relevant to a team, client, or initiative.

Lightweight references, not copies — the same source can belong to many projects.

Every knowledge item belongs to exactly one project. The field is required from the first release; personal deployments use a single `default` project.

Queries are scoped to a project by default. Projects are also the tenancy boundary for customer deployments.

---

## Retrieval

Finding evidence relevant to a question.

Exposed as two surfaces: retrieve() returns raw evidence for AI employees and agents; answer() adds planning and synthesis for humans who want an answer with citations.

---

## Evidence Bundle

The collection of evidence used to answer a question.

---

## Retrieval Receipt

An auditable record of what evidence was retrieved, why, and under what permissions.

---

# Success Criteria

A successful system should allow users to ask questions without needing to know where the information lives.

Every answer should:

- cite original sources
- respect permissions
- report freshness
- explain uncertainty
- distinguish authoritative information from historical context

---

# First Release

Personal deployment.

SQLite.

Local documents — v1 is a reimplementation of the existing Employee Zero knowledge system with improved architecture, not a greenfield product. The deployed reference corpus is ~1,200 documents across 15 source roots. The existing source-root configuration (`knowledge/sources.toml`) is preserved; the knowledge projection is rebuilt from sources. The old compiled index is not authoritative.

Supported formats: Markdown, plain text, Word (.docx), Excel (.xlsx), PowerPoint (.pptx) — the formats the deployed Chief of Staff workflow actually uses.

Acceptance criterion: the Chief of Staff can stop using the old `kb` commands and use lee-kb instead without losing capability.

One additional connector: email (decided). It is the highest-value personal corpus, it exercises conversational knowledge, threading, metadata extraction, and future distillation — and every customer has email. Not every customer has GitHub. GitHub remains an important connector but no longer defines the early product.

Lexical retrieval, with the Evidence Bundle carrying per-retriever ranks so fusion and semantic search can be added without schema changes.

Chunking.

Source citations.

Freshness reporting.

Retrieval receipts.

No enterprise infrastructure required.

---

# Long-Term Vision

Become the shared knowledge substrate for:

- Chief of Staff
- Agentflow
- Agent-Orch
- Employee Zero
- AI Employee Factory
- customer AI employees

Every consumer should depend on the same governed knowledge platform rather than implementing its own retrieval system.
