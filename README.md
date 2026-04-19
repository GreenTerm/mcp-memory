# mcp-memory

`mcp-memory` - локальная offline-first база знаний для reverse engineering. Проект хранит функции, структуры, гипотезы, evidence, связи, историю изменений и pending changes в SQLite и дает к ним доступ через CLI, JSON HTTP API, MCP HTTP endpoint и server-rendered web UI.

Система ориентирована на простой Windows-local запуск без облаков, внешних баз данных, фоновых сервисов и runtime-зависимостей. Для тестового покрытия используется только optional dependency `coverage`.

## Возможности

- изолированные workspaces для нескольких проектов
- SQLite-хранилище на проект с `project.db`, `attachments/`, `exports/`, `backups/`, `logs/`
- CLI для создания проектов, импорта, экспорта, backup/restore и pending changes
- JSON HTTP API для локальной автоматизации
- MCP Streamable HTTP endpoint для агентов
- MCP tools для чтения, поиска, записи, evidence, relations, import/export и backup/restore
- MCP prompts для агентского workflow
- server-rendered web UI: project shelf, workspace dashboard, search, graph, entity lists, detail pages, settings, import/export, backups
- режимы записи `confirm` и `auto`
- audit trail и version history
- русская и английская локализация UI

## Требования

- Windows
- Python `3.10+`

Установить проект из корня репозитория:

```powershell
python -m pip install -e .
```

Для локальных checks и coverage:

```powershell
python -m pip install -e .[dev]
```

Без editable install можно запускать через `PYTHONPATH`:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
python -m mcp_memory.cli --help
```

## Быстрый старт

1. Создать app home и registry:

```powershell
mcp-memory init-app
```

По умолчанию app home выбирается так:

1. `MCP_MEMORY_HOME`
2. `%LOCALAPPDATA%\mcp-memory`
3. `.\.mcp-memory`

2. Создать проект:

```powershell
mcp-memory create-project sample --name "Sample Project"
```

С явными путями и портами:

```powershell
mcp-memory create-project sample `
  --name "Sample Project" `
  --project-root F:\work\sample-project `
  --http-port 8765 `
  --mcp-port 9876 `
  --write-mode confirm
```

3. Посмотреть проекты:

```powershell
mcp-memory list-projects
```

4. Запустить web UI для полки проектов:

```powershell
mcp-memory run-ui-home
```

После этого доступны:

- home UI: `http://127.0.0.1:8764/`
- project workspace UI: `http://127.0.0.1:8765/ui/`
- HTTP API health: `http://127.0.0.1:8765/health`
- MCP health: `http://127.0.0.1:9876/health`
- MCP endpoint: `http://127.0.0.1:9876/mcp`

Home UI умеет запускать, останавливать и перезапускать project HTTP/MCP процессы. Если нужен ручной запуск:

```powershell
mcp-memory run-http-api sample
mcp-memory run-mcp sample
```

## CLI

Основные команды:

```powershell
mcp-memory init-app
mcp-memory create-project <project_id> --name "<display_name>"
mcp-memory list-projects

mcp-memory run-http-api <project_id> [--host 127.0.0.1] [--port 8765]
mcp-memory run-mcp <project_id> [--host 127.0.0.1] [--port 9876]
mcp-memory run-ui-home [--host 127.0.0.1] [--port 8764]

mcp-memory export-json <project_id> [--output bundle.json]
mcp-memory import-json <project_id> --input bundle.json [--replace-existing]
mcp-memory backup-project <project_id> [--output backup.zip]
mcp-memory restore-project --input backup.zip --project-root F:\restored

mcp-memory list-pending <project_id> [--status pending|all]
mcp-memory confirm-change <project_id> <pending_change_id>
mcp-memory reject-change <project_id> <pending_change_id>
```

Long-running entrypoints поддерживают `--log-level`:

```powershell
mcp-memory --log-level DEBUG run-http-api sample
mcp-memory --log-level INFO run-mcp sample
mcp-memory --log-level INFO run-ui-home
```

## Web UI

Home UI:

- показывает зарегистрированные проекты
- показывает статус `running` / `offline`
- запускает `Start`, `Stop`, `Restart`
- дает `Open Workspace`
- показывает HTTP/MCP endpoints
- копирует MCP config
- поддерживает меню карточки проекта с `Edit` и `Delete`

Workspace UI:

- компактный dashboard проекта
- sidebar с иконками и collapse-анимацией
- topbar с поиском, темой, режимом записи и языком
- pages: functions, structures, hypotheses, search, graph, import/export, backups, settings
- detail pages с facts, hypotheses, relations, history и audit links
- формы создания и редактирования сущностей
- empty states внутри единых card/section wrappers

Основные routes:

```text
/ui/
/ui/search
/ui/functions
/ui/functions/new
/ui/functions/{binary_id}/{function_id}
/ui/structures
/ui/structures/new
/ui/structures/{structure_id}
/ui/global-hypotheses
/ui/global-hypotheses/new
/ui/global-hypotheses/{hypothesis_id}
/ui/graph
/ui/import-export
/ui/backups
/ui/settings
/ui/pending
/ui/audit
```

## JSON HTTP API

HTTP API предназначен для локальной автоматизации и простых клиентов.

Основные routes:

- `GET /health`
- `GET /project/config`
- `GET /functions?binary_id=...`
- `GET /functions/{binary_id}/{function_id}`
- `POST /functions`
- `GET /structures`
- `GET /structures/{structure_id}`
- `POST /structures`
- `GET /global-hypotheses`
- `GET /global-hypotheses/{hypothesis_id}`
- `POST /global-hypotheses`
- `GET /evidence?entity_type=...&entity_id=...`
- `POST /evidence`
- `GET /relations?entity_type=...&entity_id=...`
- `POST /relations`
- `GET /related?entity_type=...&entity_id=...&hops=1`
- `POST /search`
- `GET /pending-changes`
- `POST /pending-changes/{id}/confirm`
- `POST /pending-changes/{id}/reject`
- `POST /export/json`
- `POST /import/json`
- `POST /backup`
- `POST /restore`

Пример поиска:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/search `
  -ContentType "application/json; charset=utf-8" `
  -Body '{"q":"main handler","entity_types":["function"],"limit":10}'
```

## MCP

MCP endpoint проекта:

```text
http://127.0.0.1:<mcp-port>/mcp
```

По умолчанию:

```text
http://127.0.0.1:9876/mcp
```

Endpoint реализован как MCP Streamable HTTP совместимый transport без новых runtime-зависимостей:

- `POST /mcp` принимает JSON-RPC requests
- `initialize` возвращает `Mcp-Session-Id`
- `notifications/initialized` и другие notifications без `id` возвращают `202 Accepted`
- `Mcp-Session-Id` проверяется, неизвестная session возвращает `404`
- legacy requests без session header принимаются для совместимости
- `Accept: application/json, text/event-stream` поддерживается
- ответы отдаются как UTF-8 JSON
- `GET /mcp` и `DELETE /mcp` возвращают `405 Method Not Allowed`
- `GET /health` остается обычной health-проверкой

Пример config для MCP-клиента:

```json
{
  "servers": {
    "mcp-memory-sample": {
      "transport": "http",
      "url": "http://127.0.0.1:9876/mcp"
    }
  }
}
```

Для Codex Desktop достаточно указать HTTP URL проекта. Если серверный код или настройки портов менялись, перезапусти project MCP server и сам MCP-клиент, чтобы handshake прошел заново.

### MCP tools

Текущий MCP server публикует:

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

### MCP resources

Resources capability включена для совместимости с MCP-клиентами:

- `resources/list` возвращает `{"resources": []}`
- `resources/templates/list` возвращает `{"resourceTemplates": []}`

Сейчас данные проекта экспортируются через tools, а не через resources.

### MCP prompts

Prompts capability включена и статична:

- `agent_workspace_guide` - общий workflow агента по проекту
- `record_function_analysis` - как создавать и обновлять function records
- `record_structure_analysis` - как записывать structures и fields
- `record_hypothesis_evidence` - как разделять факты, гипотезы, evidence и relations
- `search_and_graph_workflow` - как искать записи и строить контекст через graph/relations

`prompts/get` возвращает `messages` в MCP-формате `role/content` и динамически добавляет `project_id`, `display_name`, `write_mode`, HTTP endpoint и MCP endpoint.

## Режимы записи

`write_mode` задается в project config:

- `confirm`: write-операции создают pending change, затем пользователь или агент вызывает `confirm_change` или `reject_change`
- `auto`: write-операции сразу применяются к SQLite

Режим влияет на HTTP API, MCP tools и HTML forms.

## Поиск и graph

Поиск использует exact matching, tags и SQLite FTS5. Relations используются для graph и `get_related`.

Важная оговорка: FTS-запросы со строками через дефис могут интерпретироваться SQLite как выражение. Для значений вроде `gui-seed` лучше искать по словам без дефиса (`gui seed`) или по `tag`, пока escaping FTS-запросов не вынесен в отдельный bugfix.

Graph показывает только реальные relations. Если записи есть, но graph пустой, нужно создать связи через `create_relation`, HTTP API или UI.

## Структура проекта на диске

Project workspace:

```text
<project-root>/
  project.db
  attachments/
  exports/
  backups/
  logs/
```

App home:

```text
<app-home>/
  app_config.json
  logs/
```

Runtime logs пишутся plain text:

```text
timestamp level component event key=value ...
```

Основные log files:

- project-local: `logs/cli.log`, `logs/http-api.log`, `logs/mcp.log`
- app-home: `logs/ui-home.log`

## Локальная проверка

Основной script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_checks.ps1
```

Он запускает smoke-check, HTTP/MCP/UI проверки, runtime log проверки и coverage. Результаты сохраняются в `artifacts/`.

Ключевые файлы:

- `artifacts/local_checks.txt`
- `artifacts/local_checks.stdout.txt`
- `artifacts/coverage.txt`
- `artifacts/coverage.json`

Текущий порог coverage: не ниже `95%`.

## Developer docs

- [docs/modules.md](docs/modules.md)
- [docs/redesign-plan.md](docs/redesign-plan.md)
- [docs/future-plans.md](docs/future-plans.md)
- [docs/design-prompt.md](docs/design-prompt.md)

## Ограничения

- проект локальный, без multi-user auth
- storage только SQLite
- нет облачной синхронизации
- нет external services
- UI не SPA и не heavy frontend app
- semantic embeddings не реализованы
- resources/prompts MCP не заменяют tools: данные проекта сейчас доступны через tools
