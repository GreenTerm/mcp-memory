# Module Guide

Этот документ нужен для быстрой навигации по коду `mcp-memory`: кто за что отвечает, где искать поведение и какие модули являются основными точками входа.

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

Логика проекта разделена так:

- `config`: где и как живут app/project конфиги
- `domain`: dataclass-модели и доменные типы
- `storage`: SQLite bootstrap и low-level DB access
- `services`: core business logic
- `api`: JSON HTTP API
- `mcp`: MCP-over-HTTP server
- `gui`: server-rendered web UI
- `cli`: основной пользовательский entrypoint

## Entry Points

### `mcp_memory.cli`

Основной CLI интерфейс проекта.

Главный файл:

- [src/mcp_memory/cli/main.py](../src/mcp_memory/cli/main.py)

Отвечает за:

- парсинг аргументов
- выбор команды
- bootstrap logging
- запуск HTTP/MCP/UI servers
- вызов import/export/backup/pending операций

Когда нужен обзор всех доступных команд, начинать надо отсюда.

### `mcp_memory.api`

Локальный JSON HTTP API.

Главный файл:

- [src/mcp_memory/api/server.py](../src/mcp_memory/api/server.py)

Отвечает за:

- маршруты `GET`/`POST`
- JSON serialization
- связку UI + API в одном project HTTP server
- request logging
- payload conversion в domain write-модели

Если нужен ответ на вопрос “какой HTTP route что делает”, смотреть сюда.

### `mcp_memory.mcp`

MCP-over-HTTP transport.

Главный файл:

- [src/mcp_memory/mcp/server.py](../src/mcp_memory/mcp/server.py)

Отвечает за:

- `initialize`
- `ping`
- `tools/list`
- `tools/call`
- map MCP tools -> service operations

Если нужно понять, какие MCP tools доступны и как они вызывают core logic, смотреть сюда.

### `mcp_memory.gui`

Server-rendered web UI.

Главные файлы:

- [src/mcp_memory/gui/home.py](../src/mcp_memory/gui/home.py)
- [src/mcp_memory/gui/workspace.py](../src/mcp_memory/gui/workspace.py)
- [src/mcp_memory/gui/render.py](../src/mcp_memory/gui/render.py)

Роли:

- `home.py`
  - home server
  - список проектов
  - probe project status
- `workspace.py`
  - project UI pages
  - search/cards/history/audit/pending
  - HTML form handlers
- `render.py`
  - повторно используемые HTML helpers
  - layout fragments
  - asset loading

Если сломалась страница, form flow или navigation, почти всегда нужный код здесь.

## Config Layer

### `mcp_memory.config.models`

Файл:

- [src/mcp_memory/config/models.py](../src/mcp_memory/config/models.py)

Содержит:

- `ProjectConfig`
- `AppConfig`

Это основная форма конфигурации проекта и registry.

### `mcp_memory.config.registry`

Отвечает за:

- чтение `app_config.json`
- запись `app_config.json`
- поиск и список проектов

Если нужно понять, как проект регистрируется или находится по `project_id`, смотреть сюда.

### `mcp_memory.config.paths`

Отвечает за:

- вычисление `app_home`
- fallback logic для `MCP_MEMORY_HOME`, `LOCALAPPDATA`, local fallback

## Domain Layer

### `mcp_memory.domain.models`

Файл:

- [src/mcp_memory/domain/models.py](../src/mcp_memory/domain/models.py)

Содержит dataclass-модели и enum-ы для:

- `FunctionWrite` / `FunctionRecord`
- `StructureWrite` / `StructureRecord`
- `GlobalHypothesisWrite` / `GlobalHypothesisRecord`
- `EvidenceWrite` / `EvidenceRecord`
- `ObservedFact`
- `HypothesisItem`
- статусы гипотез и timestamp helper

Если нужна “истинная форма данных”, начинать надо здесь.

## Storage Layer

### `mcp_memory.storage.database`

Отвечает за:

- открытие SQLite database
- connection wrapper
- transaction access

### `mcp_memory.storage.migrations`

Отвечает за:

- bootstrap schema
- применение SQL migrations

SQL миграции лежат в:

- [sql/migrations](../sql/migrations)

Если нужно понять таблицы и индексы, смотреть сюда и в SQL.

## Service Layer

Service layer — это core логика проекта. Все внешние интерфейсы поверх него тонкие.

### `services.projects`

Создание app и project workspaces.

Отвечает за:

- `init-app`
- `create-project`
- directory bootstrap
- project registration

### `services.functions`

CRUD и валидация для `functions`.

Отвечает за:

- upsert функции
- facts/hypotheses/tags
- version snapshots
- audit rows
- address conflict handling
- search document updates

### `services.structures`

CRUD и валидация для `structures`.

Отвечает за:

- upsert структуры
- fields serialization
- facts/hypotheses/tags
- versions/audit/search updates

### `services.hypotheses`

CRUD и валидация для `global hypotheses`.

Отвечает за:

- upsert глобальной гипотезы
- facts/tags
- versions/audit/search updates

### `services.evidence`

Создание и listing `evidence`.

Отвечает за:

- evidence rows
- attachment references
- audit rows

### `services.relations`

Связи между сущностями.

Отвечает за:

- create relation
- list relations
- traverse related entities

### `services.search`

Локальный поиск без embeddings.

Отвечает за:

- exact/FTS search
- entity type filtering
- binary/tag/address filtering

### `services.pending`

Confirm-mode queue.

Отвечает за:

- create pending change
- list pending changes
- confirm pending
- reject pending
- apply deferred operations

Это критичный модуль для agent-safe write flow.

### `services.transfer`

JSON import/export.

Отвечает за:

- export bundle
- import bundle
- clear and replace project data

### `services.archive`

Zip backup/restore.

Отвечает за:

- backup workspace
- restore workspace
- re-register restored project

## Logging

### `mcp_memory.logging_utils`

Файл:

- [src/mcp_memory/logging_utils.py](../src/mcp_memory/logging_utils.py)

Отвечает за:

- logger bootstrap
- plain-text runtime formatting
- shared log event helper
- request timing helper
- logger shutdown for tests

Это runtime logging слой. Не путать с `audit_log` в SQLite.

## Как искать код по задаче

### Нужно изменить CLI-команду

Смотреть:

- `cli/main.py`
- при необходимости соответствующий service

### Нужно изменить HTTP route

Смотреть:

- `api/server.py`
- потом domain/service слой

### Нужно изменить MCP tool

Смотреть:

- `mcp/server.py`
- потом service слой

### Нужно изменить UI страницу или HTML form

Смотреть:

- `gui/workspace.py`
- иногда `gui/render.py`
- home screen: `gui/home.py`

### Нужно изменить хранение сущности

Смотреть:

- `domain/models.py`
- соответствующий `services/*.py`
- при необходимости `sql/migrations`

### Нужно понять, почему запись попала в pending вместо прямого save

Смотреть:

- `services/pending.py`
- `api/server.py`
- `mcp/server.py`
- `gui/workspace.py`

### Нужно понять runtime log behavior

Смотреть:

- `logging_utils.py`
- `cli/main.py`
- `api/server.py`
- `mcp/server.py`
- `gui/home.py`
- `gui/workspace.py`

## Test Layout

Тесты лежат в:

- [tests](../tests)

Основные группы:

- `test_config_cli.py`
- `test_api_server.py`
- `test_mcp_server.py`
- `test_gui_home.py`
- `test_services.py`
- `test_transfer_archive.py`
- `test_logging_runtime.py`

Общий smoke/coverage workflow:

- [scripts/run_local_checks.ps1](../scripts/run_local_checks.ps1)
- [scripts/local_smoke_check.py](../scripts/local_smoke_check.py)

## Practical Rule Of Thumb

Если нужно быстро ориентироваться:

1. Найди внешний интерфейс: CLI / HTTP / MCP / UI
2. Перейди в соответствующий entrypoint
3. Найди вызов нужного service
4. Уже потом смотри domain/storage

Это почти всегда самый быстрый маршрут по проекту.
