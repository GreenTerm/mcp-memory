# Module Guide

Краткая навигация по коду `mcp-memory`: где искать поведение, какие модули являются точками входа и какие границы важно сохранять.

## High-Level Layout

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

## Entry Points

### `mcp_memory.cli`

Главный файл:

- [src/mcp_memory/cli/main.py](../src/mcp_memory/cli/main.py)

Отвечает за:

- parsing CLI arguments
- `init-app`, `create-project`, `list-projects`
- `run-http-api`, `run-mcp`, `run-ui-home`
- import/export/backup/restore commands
- pending change commands
- logging bootstrap

### `mcp_memory.api`

Главный файл:

- [src/mcp_memory/api/server.py](../src/mcp_memory/api/server.py)

Локальный JSON HTTP API и project workspace UI живут в одном project HTTP server. Модуль отвечает за:

- `GET` / `POST` routing
- JSON serialization
- UTF-8 responses
- health/config endpoints
- binding GUI handlers to `/ui/...`
- request logging
- conversion of JSON payloads into service calls

### `mcp_memory.mcp`

Главный файл:

- [src/mcp_memory/mcp/server.py](../src/mcp_memory/mcp/server.py)

Stdlib MCP HTTP server. Отвечает за:

- MCP Streamable HTTP compatible `POST /mcp`
- JSON-RPC request/response handling
- session lifecycle through `Mcp-Session-Id`
- `initialize`, `ping`
- `tools/list`, `tools/call`
- `resources/list`, `resources/templates/list`
- `prompts/list`, `prompts/get`
- prompt registry
- mapping MCP tools to service operations

Важно: `GET /mcp` и `DELETE /mcp` возвращают `405`. Отдельный SSE stream сейчас не предоставляется.

### `mcp_memory.gui`

Главные файлы:

- [src/mcp_memory/gui/home.py](../src/mcp_memory/gui/home.py)
- [src/mcp_memory/gui/workspace.py](../src/mcp_memory/gui/workspace.py)
- [src/mcp_memory/gui/render.py](../src/mcp_memory/gui/render.py)
- [src/mcp_memory/gui/i18n.py](../src/mcp_memory/gui/i18n.py)
- [src/mcp_memory/gui/assets/app.css](../src/mcp_memory/gui/assets/app.css)
- [src/mcp_memory/gui/assets/ui.js](../src/mcp_memory/gui/assets/ui.js)

Роли:

- `home.py`: home server, project shelf, start/stop/restart, edit/delete project actions
- `workspace.py`: workspace routes, entity pages, graph, settings, import/export, backups, pending, audit
- `render.py`: shared HTML helpers, shell, cards, forms, empty states
- `i18n.py`: English/Russian phrase translations
- `app.css`: shared visual system
- `ui.js`: theme toggle, sidebar collapse, copy interactions, light page transitions

## Config Layer

### `mcp_memory.config.models`

Файл:

- [src/mcp_memory/config/models.py](../src/mcp_memory/config/models.py)

Содержит:

- `ProjectConfig`
- `AppConfig`

`ProjectConfig` хранит identity проекта, paths, HTTP/MCP host/port и `write_mode`.

### `mcp_memory.config.registry`

Отвечает за:

- чтение и запись `app_config.json`
- регистрацию проектов
- поиск проекта по `project_id`
- обновление project config из GUI/CLI

### `mcp_memory.config.paths`

Отвечает за выбор `app_home`:

1. `MCP_MEMORY_HOME`
2. `%LOCALAPPDATA%\mcp-memory`
3. local fallback

## Domain Layer

### `mcp_memory.domain.models`

Файл:

- [src/mcp_memory/domain/models.py](../src/mcp_memory/domain/models.py)

Содержит dataclasses и enums для:

- function writes/records
- structure writes/records
- global hypothesis writes/records
- evidence records
- observed facts
- hypothesis items
- statuses and timestamps

Если нужно понять форму данных, начинать стоит здесь.

## Storage Layer

### `mcp_memory.storage.database`

Отвечает за:

- opening SQLite database
- connection wrapper
- transaction access

### `mcp_memory.storage.migrations`

Отвечает за:

- schema bootstrap
- applying SQL migrations

SQL migrations:

- [sql/migrations](../sql/migrations)

## Service Layer

Service layer - основной слой бизнес-логики. HTTP API, MCP и GUI должны оставаться тонкими адаптерами поверх него.

### `services.projects`

Отвечает за:

- app bootstrap
- project workspace creation
- directory creation
- registry updates

### `services.functions`

Отвечает за:

- upsert function records
- facts/hypotheses/tags
- version snapshots
- audit rows
- address conflict handling
- search document updates

### `services.structures`

Отвечает за:

- upsert structure records
- fields serialization
- facts/hypotheses/tags
- versions/audit/search updates

### `services.hypotheses`

Отвечает за:

- global hypothesis writes
- facts/tags
- versions/audit/search updates

### `services.evidence`

Отвечает за:

- evidence rows
- attachment references
- audit rows

### `services.relations`

Отвечает за:

- create relation
- list relations
- related traversal
- graph source data

### `services.search`

Отвечает за:

- exact search
- FTS5 search
- tag filtering
- entity type filtering

Known caveat: FTS strings with hyphens can be parsed as expressions. Search by separate words or tags until escaping is fixed.

### `services.transfer`

Отвечает за:

- JSON export
- JSON import
- replace-existing behavior

### `services.archive`

Отвечает за:

- zip backup
- restore project workspace

### `services.pending`

Отвечает за:

- pending change proposals
- confirm/reject flow
- write-mode integration for agent and GUI writes

## Tests

Основные группы тестов:

- `tests/test_services.py`
- `tests/test_api_server.py`
- `tests/test_mcp_server.py`
- `tests/test_gui_home.py`
- `scripts/local_smoke_check.py`

Полный локальный check:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_checks.ps1
```

Порог coverage: `>=95%`.
