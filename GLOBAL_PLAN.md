# Global Plan

Этот файл фиксирует актуальную картину проекта после реализации backend, MCP и GUI. Исторический план был ориентирован на поэтапную сборку; сейчас большинство MVP-пунктов уже выполнено.

## Архитектурное направление

- Windows-first local application.
- Python `3.10+`, SQLite, stdlib-first.
- Никаких обязательных runtime-зависимостей.
- Один app home с registry и отдельный workspace на каждый проект.
- Один project HTTP/UI server и один MCP server на проект.
- Данные разных проектов не смешиваются.
- Backup/restore, import/export и audit считаются пользовательскими возможностями, а не внутренними деталями.

## Текущий runtime layout

```text
app-home/
  app_config.json
  logs/

project-root/
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
  services/
  storage/
```

## Реализованные фазы

### 1. Config, schema, services

Done:

- `AppConfig`, `ProjectConfig`, project registry
- SQLite bootstrap/migrations
- domain dataclasses
- service layer для functions, structures, hypotheses, evidence, relations
- pending changes
- audit log и version snapshots
- FTS search documents

### 2. HTTP API

Done:

- health/config endpoints
- CRUD/read routes для основных сущностей
- search, relations, related traversal
- pending confirm/reject
- import/export
- backup/restore
- UTF-8 JSON responses

### 3. MCP

Done:

- stdlib MCP-over-HTTP implementation
- Streamable HTTP compatible `POST /mcp`
- `Mcp-Session-Id` lifecycle
- JSON-RPC notifications with `202 Accepted`
- legacy no-session JSON-RPC compatibility
- `tools/list`, `tools/call`
- list-only `resources/list`, `resources/templates/list`
- `prompts/list`, `prompts/get`
- Codex-style handshake compatibility

### 4. Import/export and backup/restore

Done:

- JSON bundle export/import
- optional replace on import
- zip backup of project workspace
- restore to a project workspace
- CLI, HTTP API, MCP and GUI entry points

### 5. GUI

Done:

- home project shelf
- project card actions: Start, Stop, Restart, Open Workspace, Edit, Delete
- project settings UI
- workspace app shell with topbar and icon sidebar
- compact workspace header
- dashboard cards
- search page and empty states
- functions, structures and hypotheses list/detail/edit/create pages
- graph page based on relations
- import/export and backups pages
- pending changes and audit pages
- dark/light theme
- English/Russian language switcher
- Russian mojibake regression coverage

## Current MCP surface

Tools:

- `get_project_config`
- `search_records`
- `get_record`
- `get_related`
- `create_function`
- `update_function`
- `create_structure`
- `update_structure`
- `create_hypothesis`
- `add_evidence`
- `create_relation`
- `list_pending_changes`
- `confirm_change`
- `reject_change`
- `export_json`
- `import_json`
- `backup_project`
- `restore_project`

Prompts:

- `agent_workspace_guide`
- `record_function_analysis`
- `record_structure_analysis`
- `record_hypothesis_evidence`
- `search_and_graph_workflow`

Resources:

- `resources/list` returns an empty list
- `resources/templates/list` returns an empty list

## Write policy

`write_mode=confirm`:

- writes become pending changes
- caller must confirm or reject them
- safest default for agent usage

`write_mode=auto`:

- writes are applied immediately
- useful for controlled local seeding and trusted workflows

## Verification target

Use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_checks.ps1
```

Expected status:

- `process_exit_code=0`
- `coverage_process_exit_code=0`
- coverage `>=95%`

## Known remaining work

- Escape or quote FTS queries with hyphens so `gui-seed` does not break SQLite FTS parsing.
- Improve entity browsing and bulk navigation for large projects.
- Add richer graph filtering and relation authoring from the GUI.
- Consider MCP resources later if clients need resource-based reads instead of tools.
- Keep dependency footprint small; do not add an official MCP SDK unless it clearly reduces maintenance cost.
