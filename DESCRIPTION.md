# Product Description

`mcp-memory` is a local light-weigth, schema-driven knowledge base for people and agents.

It stores project knowledge in isolated Windows-local workspaces backed by SQLite and plain files. Each project owns a portable `schema.json` that defines entity types, fields, search metadata, and relation types. The same project data is available through CLI commands, a JSON HTTP API, an MCP Streamable HTTP endpoint, and a server-rendered web UI.

## Goal

The project is meant to be easy to run manually on a local Windows machine without cloud services, external databases, Docker, background daemons, or a frontend build pipeline.

Primary interfaces:

- CLI for app setup, project lifecycle, schema management, import/export, backup/restore, and pending changes.
- JSON HTTP API for local automation.
- MCP Streamable HTTP endpoint for agent clients.
- Home UI and workspace UI for browsing, search, editing, graph navigation, schema work, imports, backups, and settings.

## Current State

Implemented in version 1.0.0:

- Global app registry and isolated per-project workspaces.
- Project-local `schema.json` plus bundled schema templates.
- Generic records with UUID `record_id` and optional unique slugs.
- Schema-generated fields and forms.
- Typed relations between generic records.
- Evidence and attachment references for any record.
- SQLite FTS search based on schema metadata.
- Confirm/auto write modes with pending change review.
- Audit rows and version snapshots for generic writes.
- Soft archive for records.
- Generic JSON export/import that includes the schema.
- Zip backup/restore that includes the schema and workspace files.
- Legacy importer from the old fixed reverse-engineering database shape.
- JSON HTTP API with generic schema, record, relation, evidence, search, pending, transfer, and archive routes.
- MCP Streamable HTTP server with generic tools, session handling, empty resource-list compatibility, and schema-aware prompts.
- Home UI with project shelf, process start/stop/restart, project creation, Base URL setting, and DNS/path gateway to project UI/API/MCP endpoints.
- Server-rendered workspace UI with generic dashboard, entity browser, record pages, search, graph, evidence, schema editor/builder actions, pending changes, audit, import/export, backups, and settings.
- English/Russian UI localization, dark/light theme, packaged CSS/JS, and Jinja2-backed template rendering where useful.

## Product Constraints

- Python 3.10+ and SQLite are the base stack.
- Runtime dependencies stay small and offline-installable; Jinja2 is currently the only required third-party runtime dependency.
- The project must not require cloud services, external databases, native system packages, or network access at runtime.
- The web UI remains server-rendered; no SPA or frontend build pipeline.
- Exact and FTS-based search are the default retrieval mechanisms; semantic search and embeddings are not implemented.
- MCP resources currently return empty lists for compatibility. Project data is exposed through MCP tools and prompts.

## Data Model

The public 1.0.0 model is generic:

- `schema.json` defines entity types, fields, required fields, title/summary/slug/search/tag fields, and relation types.
- `records` stores schema-specific payloads by entity type.
- `relations` stores typed links between records.
- `evidence` stores excerpts and attachment references tied to records.
- `pending_changes` stores confirm-mode proposals.
- `audit_log` and `record_versions` preserve user-visible history.
- `search_documents` and SQLite FTS indexes power search.

The old fixed reverse-engineering concepts (`functions`, `structures`, `global_hypotheses`) still exist as transitional code and as a legacy import source. New public workflows should prefer generic records and the bundled `reverse_engineering` schema template when reverse-engineering data is needed.

## Agent Workflow

An agent connects to the project MCP endpoint, calls `initialize`, then uses:

- `get_project_config`, `get_schema`, and `list_entity_types` to understand the active workspace.
- `search_records`, `get_record`, and `get_related` to gather context.
- `upsert_record`, `archive_record`, `add_evidence`, and `create_relation` to propose or apply changes.
- `list_pending_changes`, `confirm_change`, and `reject_change` in `confirm` mode.
- `prompts/list` and `prompts/get` for schema-aware writing guidance and tool examples.

In `confirm` mode, write tools create pending proposals. In `auto` mode, writes are applied immediately.
