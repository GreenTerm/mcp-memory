# Module Guide

Version: 1.0.0.

Short navigation for the current `mcp-memory` codebase. The project is now a schema-driven local knowledge base: old reverse-engineering services still exist for legacy compatibility/import paths, but the public 1.0.0 surface is generic records, typed relations, evidence, search, HTTP, MCP, CLI, and server-rendered GUI.

## High-Level Layout

```text
src/mcp_memory/
  api/        HTTP JSON API and project UI binding
  cli/        command line entrypoint
  config/     app/project config and registry
  domain/     legacy dataclasses and shared data shapes
  gui/        Home UI, workspace UI, rendering, assets, i18n
  mcp/        Streamable HTTP MCP server, tools, prompts
  schemas/    bundled project schema templates
  services/   project, generic record/relation/evidence/workflow logic
  storage/    SQLite connection and migrations
```

## Entry Points

- `mcp_memory.cli.main`: CLI commands for app init, project creation, schema commands, API/MCP/Home servers, import/export, backup/restore, and pending changes.
- `mcp_memory.api.server`: project HTTP API, generic routes, legacy-compatible routes, and `/ui/...` workspace rendering.
- `mcp_memory.mcp.server`: MCP Streamable HTTP endpoint at `/mcp`, generic tools, schema-aware prompts, session handling, and empty resources compatibility.
- `mcp_memory.gui.home`: Home UI on port `8764`, project shelf, start/stop/restart, Base URL setting, and DNS/path gateway proxy.
- `mcp_memory.gui.workspace`: server-rendered project UI pages for dashboard, records, entities, search, graph, evidence, schema, pending, import/export, backups, audit, and settings.

## Core Data Flow

- Project creation copies a bundled or explicit schema into `<project-root>/schema.json` and stores `schema_path` in `ProjectConfig`.
- Generic writes go through services and workflow helpers so `confirm` mode queues pending changes and `auto` mode applies immediately.
- Search documents are derived from schema `title_field`, `summary_field`, `search_fields`, and `tag_fields`.
- Records use UUID `record_id`; schemas can define an optional unique `slug_field` for human/agent friendly lookup.
- Records are archived with `status=archived`; default list/search/read behavior hides archived records unless explicitly requested.

## Public Surfaces

- HTTP generic routes include `/schema`, `/entity-types`, `/records`, `/relations`, `/related`, `/evidence`, `/search`, `/pending-changes`, `/export/json`, `/import/json`, `/backup`, and `/restore`.
- MCP publishes generic tools only: schema discovery, record CRUD/archive, relation/evidence writes, pending review, import/export, and backup/restore.
- MCP prompts include schema-aware instructions and examples for every tool. `agent_workspace_guide` is the best first prompt for agents.
- Home UI gateway exposes projects at `/<project_id>/ui/...`, `/<project_id>/schema`, `/<project_id>/records/...`, and `/<project_id>/mcp`.
- Direct project HTTP/MCP ports remain available for local/manual use.

## Important Boundaries

- `services/` is the main behavior boundary. Keep HTTP/MCP/GUI handlers thin.
- `storage/` should not import API, MCP, GUI, or service-specific behavior.
- `mcp/` should not import HTTP API helpers.
- `gui/` should preserve server-rendered HTML and avoid frontend build steps.
- Use small shared helpers for duplicated request/form/tool conversion only when duplication is already costly.

## Tests

Main suites:

- `tests/test_services.py`
- `tests/test_generic_records.py`
- `tests/test_api_server.py`
- `tests/test_mcp_server.py`
- `tests/test_gui_home.py`
- `tests/test_runtime_manager.py`
- `tests/test_config_cli.py`
- `tests/test_coverage_targets.py`
- `tests/test_transfer_archive.py`
- `scripts/local_smoke_check.py`

Run full verification:

```powershell
python -X utf8 -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_checks.ps1
```
