# Global Plan

This file records the current project picture after the generic schema-first refactor, DNS/path gateway work, GUI refactor, MCP prompt work, and verification updates.

## Architecture Direction

- Windows-first local application.
- Python 3.10+, SQLite, stdlib-first.
- Small offline-installable dependency footprint; Jinja2 is the only required runtime dependency.
- One app home with a project registry and one isolated workspace per project.
- One project HTTP/UI server and one MCP server per project when run directly.
- Home UI can proxy project UI/API/MCP by path for a single DNS/Base URL.
- Project data does not mix across workspaces.
- Backup/restore, import/export, audit, versions, pending changes, and archive are user-facing features.

## Runtime Layout

```text
app-home/
  app_config.json
  logs/

project-root/
  schema.json
  project.db
  attachments/
  exports/
  backups/
  logs/
```

```text
src/mcp_memory/
  api/
  cli/
  config/
  domain/
  gui/
  mcp/
  schemas/
  services/
  storage/
```

## Current Public Surface

The preferred public surface is generic and schema-driven:

- Project-local `schema.json`.
- Generic records, relations, evidence, search, archive, pending changes, audit, and versions.
- CLI commands for app/project/schema lifecycle, transfer, backup/restore, and pending review.
- HTTP API routes for schema, entity types, records, search, relations, related traversal, evidence, pending changes, JSON transfer, backup, and restore.
- MCP tools for schema discovery, record operations, relation/evidence writes, pending review, JSON transfer, backup, and restore.
- MCP prompts with schema-aware guidance and tool examples.
- Home UI for project management and DNS/path gateway.
- Workspace UI for dashboard, entities, records, search, graph, evidence, schema, pending changes, audit, import/export, backups, and settings.

Old fixed reverse-engineering routes, services, and GUI pages still exist as transitional implementation detail and regression coverage. New workflows should use generic records, or the `reverse_engineering` schema template plus `import-legacy-db` for old data.

## Implemented Phases

### 1. Config, Schema, Storage, Services

Done:

- `AppConfig`, `ProjectConfig`, and project registry.
- SQLite bootstrap/migrations.
- Project-local schema copy and validation.
- Bundled schema templates: `general_knowledge`, `reverse_engineering`, `infrastructure_deployment`, and `research_notes`.
- Generic record, relation, evidence, search, archive, workflow, transfer, backup, restore, and legacy import services.
- Pending changes with `confirm` and `auto` write modes.
- Audit rows and record version snapshots.
- SQLite FTS search documents.

### 2. HTTP API

Done:

- Health/config routes.
- Generic schema, entity type, record, search, relation, related traversal, evidence, archive, pending, import/export, backup, and restore routes.
- `PUT /schema` and `PUT /records/{entity_type}/{record_id_or_slug}`.
- UTF-8 JSON responses.
- Transitional old fixed routes remain available while cleanup continues.

### 3. MCP

Done:

- Stdlib MCP-over-HTTP implementation.
- Streamable HTTP compatible `POST /mcp`.
- `Mcp-Session-Id` lifecycle.
- JSON-RPC notifications with `202 Accepted`.
- Legacy no-session JSON-RPC compatibility.
- `tools/list`, `tools/call`, `prompts/list`, and `prompts/get`.
- List-only `resources/list` and `resources/templates/list`.
- Codex-style handshake compatibility.
- Generic-only published tool surface.

Current MCP tools:

- `get_project_config`
- `get_schema`
- `list_entity_types`
- `search_records`
- `get_record`
- `upsert_record`
- `archive_record`
- `get_related`
- `add_evidence`
- `create_relation`
- `list_pending_changes`
- `confirm_change`
- `reject_change`
- `export_json`
- `import_json`
- `backup_project`
- `restore_project`

Current MCP prompts:

- `agent_workspace_guide`
- `record_function_analysis`
- `record_structure_analysis`
- `record_hypothesis_evidence`
- `search_and_graph_workflow`

Resources:

- `resources/list` returns an empty list.
- `resources/templates/list` returns an empty list.

### 4. Import/Export And Backup/Restore

Done:

- Generic JSON bundle export/import with `bundle_version: 2`.
- Optional replace on import.
- Zip backup of project workspace.
- Restore to a new or existing project workspace.
- Schema included in JSON transfer and backups.
- CLI, HTTP API, MCP, and GUI entry points.

### 5. GUI

Done:

- Home project shelf and setup flow.
- Project card actions: start, stop, restart, open workspace, edit, delete.
- Base URL setting and DNS/path gateway.
- Workspace app shell with topbar, sidebar, theme switcher, language switcher, and global search.
- Generic dashboard.
- Entity browser, entity constructor, entity edit/delete, and schema builder actions.
- Generic record list/detail/create/edit/archive pages.
- Search, graph, evidence, pending, audit, import/export, backups, settings, and schema pages.
- Packaged CSS/JS, dark/light theme, English/Russian localization, and UTF-8 regression coverage.

## Write Policy

`write_mode=confirm`:

- Writes become pending changes.
- A caller must confirm or reject them.
- This is the safest default for agent usage.

`write_mode=auto`:

- Writes are applied immediately.
- This is useful for trusted local seeding and controlled workflows.

## Verification Target

Run:

```powershell
python -X utf8 -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_checks.ps1
```

Current direct unit verification:

- Command: `python -X utf8 -m unittest discover -s tests -v`
- Result: 155 tests, OK.

Project target:

- `scripts/run_local_checks.ps1` should finish with `process_exit_code=0`.
- Coverage should remain at or above the configured threshold.

## Known Remaining Work

- Retire or isolate old fixed reverse-engineering routes, pages, and services once legacy import coverage no longer needs them.
- Expand schema builder edit/delete/migration UX where needed.
- Improve larger-project browsing with pagination or incremental filtering.
- Add richer graph filtering and relation authoring.
- Consider MCP resources later if clients need resource-based reads instead of tools.
- Keep dependency footprint small; do not add an official MCP SDK unless it clearly reduces maintenance cost.
