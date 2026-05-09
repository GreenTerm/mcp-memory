# Generic Knowledge Base Refactor Plan

Working plan for the big-bang refactor from a fixed reverse-engineering knowledge base to a generic schema-first knowledge base for people and agents.

## Current Status

Status: v1.0.0 generic implementation is complete for schema, core, adapters, GUI, DNS/path gateway, MCP instructions, transfer, backup, legacy import, smoke checks, release checks, and unit tests. Old fixed-code surfaces are isolated as compatibility paths.

## Status Snapshot

### Completed Or Mostly Completed

- Schema DSL, bundled schemas, project-local `schema.json`, and schema validation helpers are implemented.
- Project creation supports bundled schema templates and explicit schema files.
- CLI supports schema-aware project creation plus `show-schema`, `validate-schema`, and `update-schema`.
- Generic storage foundation exists for records, relations, evidence, attachments, versions, audit, pending changes, and search documents.
- Generic core services exist for records, relations, evidence, search indexing, audit/version snapshots, archive, and confirm/auto workflow.
- Typed protocol dispatcher exists and is used by generic HTTP/MCP/workflow paths.
- Generic HTTP routes exist for schema, entity types, records, search, relations, related traversal, evidence, archive, and pending confirmation.
- MCP publishes generic tools and no longer imports HTTP API helpers.
- MCP prompts are schema-aware and include examples for every tool plus required/optional fields for generic record payloads.
- Generic GUI routes exist for entity browser, record list/detail/create/edit, search, graph, relation creation, evidence, pending confirmation, and raw schema JSON editing.
- Workspace dashboard uses generic schema/record statistics and recent generic records.
- Generic JSON transfer exists as `bundle_version: 2` and includes schema, records, relations, evidence, and attachment metadata.
- Backup/restore includes `schema.json`, rewrites project IDs on restore, and tolerates older backup shapes.
- Home GUI and setup wizard can create projects from bundled schema templates.
- Home GUI can act as a DNS/path gateway: `/<project_id>/ui/...`, `/<project_id>/schema`, project API routes, and `/<project_id>/mcp`.
- Basic GUI schema builder actions exist for entity types, fields, and relation types, with raw JSON editing still available.
- Selected `mcp-memory-main-0.2.0` GUI work has been integrated into the main implementation: `/ui/entities/new` entity type constructor, optional relation type creation from that form, constructor hints/translations/styles, generic-only workspace sidebar, and next-available port defaults in Home GUI project forms.
- Legacy DB importer is implemented as `import-legacy-db` and maps current old RE state into `reverse_engineering.schema.json`.
- Local smoke checks use bundled schemas and generic HTTP/MCP/GUI surfaces.
- README/user docs describe version 1.0.0, generic schemas, DNS/path gateway, API, MCP, legacy import, and offline dependency workflow.
- Full test suite passes: `python -X utf8 -m unittest discover -s tests -v` ran 155 tests successfully.
- `scripts/run_local_checks.ps1` no longer repeats the full test suite once per phase file; it now runs unit tests once, then smoke, then coverage.

### Not Done Yet

- Old fixed RE HTTP routes and GUI pages still exist during the transition.
- Old fixed RE service code still exists and has not been removed.
- Schema builder can add entity types, fields, and relation types, but does not yet provide full edit/delete/migration UX.
- Generated schema-specific MCP convenience tools are not implemented.
- Larger-project UX still needs validation for pagination, graph caps, and dense browsing.

### Latest Verification

The latest direct unit verification passed:

- Command: `python -X utf8 -m unittest discover -s tests -v`
- Result: 155 tests, OK.

The work has been split into phase files:

- [Phase 01 - Schema And Storage Foundation](refactor-phase-01-schema-storage.md)
- [Phase 02 - Generic Core Services And Protocol](refactor-phase-02-generic-core.md)
- [Phase 03 - Project Lifecycle, CLI, Transfer, And Legacy Import](refactor-phase-03-project-cli-transfer.md)
- [Phase 04 - Generic HTTP And MCP Surfaces](refactor-phase-04-http-mcp.md)
- [Phase 05 - Generic Jinja2 GUI](refactor-phase-05-gui.md)
- [Phase 06 - Tests, Smoke Checks, And Documentation](refactor-phase-06-tests-verification.md)
- [Release 0.3.0](release-0.3.0.md)

Completed in the current implementation pass:

- Updated `pyproject.toml` to allow `Jinja2>=3.1,<4`.
- Added package data entries for GUI templates and bundled schemas.
- Extended `ProjectConfig` with `schema_path`, with backward-compatible loading for existing project registry entries.
- Added a new project schema DSL module at `src/mcp_memory/schema.py`.
- Added bundled schema package `src/mcp_memory/schemas/`.
- Added bundled schema templates:
  - `general_knowledge.schema.json`
  - `reverse_engineering.schema.json`
  - `infrastructure_deployment.schema.json`
  - `research_notes.schema.json`
- Started the SQLite migration toward generic storage by adding the new `records` table and indexes to `sql/migrations/001_initial.sql`.
- Added bundled schema template listing and schema source selection helpers.
- Updated project creation to copy the selected schema into `<project-root>/schema.json`.
- Added initial CLI support for schema-aware project creation plus schema show/validate commands.
- Added initial CLI `update-schema` support.
- Added initial generic HTTP routes backed by the protocol/workflow layer.
- Replaced MCP's published tools with the initial generic tool surface.
- Completed focused generic HTTP/MCP coverage for records, relations, evidence, and pending confirm flow.
- Added initial generic GUI routes for entity types, record list/detail/create/edit, and schema JSON editing.
- Added generic GUI search, relation graph, relation creation, evidence viewing/creation, structured schema builder actions, and generic pending confirmation coverage.
- Added Home GUI schema template selection for project creation and setup wizard.
- Added focused generic GUI tests for record flow and schema-template project creation.
- Added legacy DB importer and CLI `import-legacy-db`.
- Converted local smoke check to bundled-schema generic API/MCP/GUI coverage.
- Updated README/user docs for generic schemas, generic API/MCP, legacy import, and offline dependencies.
- Added initial schema tests.
- Converted full test suite expectations to the generic schema-first contract and verified all tests pass.
- Integrated selected `mcp-memory-main-0.2.0` changes without copying the snapshot wholesale; data migration/import is intentionally left for a later fully-ready version.
- Added Home UI DNS/path gateway and `AppConfig.base_url`.
- Added schema-aware MCP agent instructions with tool examples and required/optional field references.
- Updated project version to 1.0.0.

Important note: the generic schema-first surface is implemented and verified, but old fixed RE services/API/GUI still exist as transitional code. The legacy importer uses the old data shape as an input format, so fixed-code retirement should be handled separately.

## Target Direction

Convert the project from fixed RE entities (`functions`, `structures`, `global_hypotheses`) to a generic schema-first knowledge base.

Each project should have a local `schema.json` that defines:

- entity types
- fields and widgets
- required fields
- title/summary/slug/search/tag fields
- typed relation types

The system should support:

- generic records
- typed graph relations
- evidence and attachments for any entity
- schema-configured search
- audit trail and version history
- confirm/auto write modes
- soft archive instead of hard delete
- generic HTTP API
- generic MCP tools
- schema-generated GUI forms
- basic GUI schema form builder
- legacy importer from the old RE database format

## Core Decisions

- Target model: schema-first with a custom simple DSL.
- Internal protocol: typed commands/queries/events through a central dispatcher.
- Migration strategy: breaking schema-first refactor, with a separate legacy importer for old databases.
- Old public surfaces: replace with generic HTTP/MCP/GUI surfaces; no permanent compatibility wrappers.
- GUI: use Jinja2 and schema-generated forms.
- Record identity: generated UUID `record_id`.
- Human/agent-friendly identity: optional unique `slug_field` per entity type.
- Delete behavior: soft archive.
- Schema editing: live editable through GUI form builder.
- Legacy import: map old RE data into `reverse_engineering.schema.json`; import current state only.

## Implementation Plan

### 1. Generic Schema Layer

- Finish `schema.py` and tests for:
  - loading bundled schemas
  - loading project-local `schema.json`
  - validating entity types, fields, required fields, slug fields, search fields, tag fields, and relation types
- Add helper functions for:
  - listing bundled schema templates
  - copying a bundled schema into a project workspace
  - updating project schema safely

### 2. Generic Storage

- Complete the generic SQLite schema:
  - `records`
  - generic `relations`
  - generic `evidence`
  - `attachments`
  - `record_versions`
  - generic `audit_log`
  - generic `pending_changes`
  - `search_documents` and FTS table
- Decide whether old fixed tables should remain in `001_initial.sql` temporarily for legacy-import tests or be removed completely after the importer is implemented.

### 3. Generic Core Services

- Add generic record service:
  - create/update records
  - validate payload against project schema
  - generate UUID record IDs
  - enforce slug uniqueness
  - derive title/summary/search/tags from schema
  - create version snapshots and audit rows
  - upsert search documents
  - soft archive records
- Add generic relation service:
  - enforce typed relation definitions from schema
  - list and traverse relations
  - audit relation changes
- Add generic evidence service:
  - attach evidence to any entity type/record ID
  - preserve attachment references
  - audit evidence changes
- Replace fixed pending operation dispatch with generic command dispatch.

### 4. Protocol Dispatcher

- Add typed command/query/result objects.
- Route all adapter writes and reads through a central dispatcher.
- Remove adapter-to-adapter imports:
  - MCP must not import HTTP helpers.
  - pending workflow must not import API payload builders.
  - GUI/API/MCP/CLI should build protocol commands and queries.

### 5. Project Creation And Schema Templates

- Update `ProjectService.create_project` to:
  - accept either a schema file path or bundled schema template name
  - copy schema into `<project-root>/schema.json`
  - store `schema_path` in `ProjectConfig`
  - default to `general_knowledge`
- Update CLI:
  - `create-project --schema <path>`
  - `create-project --schema-template <name>`
  - `show-schema`
  - `validate-schema`
  - `update-schema`
  - `import-legacy-db`
- Update Home GUI project creation to allow selecting a schema template.

### 6. Generic HTTP API

Replace fixed routes with:

- `GET /schema`
- `PUT /schema`
- `GET /entity-types`
- `GET /records?entity_type=...`
- `GET /records/{entity_type}/{record_id_or_slug}`
- `POST /records/{entity_type}`
- `PUT /records/{entity_type}/{record_id_or_slug}`
- `POST /records/{entity_type}/{record_id_or_slug}/archive`
- `POST /relations`
- `GET /relations`
- `GET /related`
- `POST /evidence`
- `GET /evidence`
- `POST /search`
- generic pending/import/export/backup routes

### 7. Generic MCP API

Replace fixed RE tools with generic tools:

- `get_schema`
- `list_entity_types`
- `search_records`
- `get_record`
- `upsert_record`
- `archive_record`
- `create_relation`
- `get_related`
- `add_evidence`
- `list_pending_changes`
- `confirm_change`
- `reject_change`
- `export_json`
- `import_json`
- `backup_project`
- `restore_project`

Then add generated schema-based tools as convenience wrappers over `upsert_record`.

### 8. Generic GUI

- Add Jinja2-backed template rendering, with a small fallback if needed for local checks before dependencies are installed.
- Replace fixed pages with:
  - workspace dashboard
  - entity type browser
  - record list
  - record detail
  - schema-generated create/edit forms
  - search
  - graph
  - evidence views
  - pending changes
  - import/export
  - backups
  - settings
- Add basic schema form builder in Settings:
  - create/edit entity types
  - create/edit fields
  - set required fields
  - set title/summary/slug/search/tag fields
  - create/edit relation types
- Do not build full record migration UI for schema edits in v1.

### 9. Transfer And Legacy Import

- Replace fixed export/import bundle with generic portable bundle:
  - schema
  - records
  - relations
  - evidence
  - attachment refs
  - optionally audit/version data if simple
- Legacy importer:
  - read old database with `functions`, `structures`, `hypotheses`, `evidence`, `relations`, `tags`
  - map into `reverse_engineering.schema.json`
  - import current state only
  - create import audit event or per-record audit events

### 10. Tests And Verification

- Add schema tests.
- Add generic record tests.
- Add relation/evidence/search tests.
- Add pending/audit/version tests.
- Replace old HTTP/MCP/GUI tests with generic surface tests.
- Added legacy importer test using an old-style sample DB.
- Updated local smoke check to create a project from a bundled schema and exercise generic API/MCP/GUI.
- Keep coverage at or above the current threshold.

## Remaining Cleanup Risk

Before treating the codebase as fully cleaned up, finish:

- old fixed route/page/service cleanup
- generated schema-specific MCP wrappers if they are still desired
- larger-project UX verification and graph/search polish
