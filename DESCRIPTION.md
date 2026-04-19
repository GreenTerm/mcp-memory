# Product Description

`mcp-memory` - локальная offline-first knowledge base для reverse engineering. Она помогает человеку и агенту сохранять, искать и связывать знания о функциях, структурах, гипотезах, evidence и отношениях между сущностями.

## Основная цель

Сделать Windows-local инструмент, который работает без интернета и внешних сервисов, хранит проектные знания в SQLite и предоставляет несколько удобных интерфейсов:

- CLI для setup, lifecycle, import/export, backup/restore и pending changes
- JSON HTTP API для локальной автоматизации
- MCP Streamable HTTP endpoint для агентских клиентов
- web UI для ежедневного просмотра, поиска, редактирования и graph-навигации

## Текущее состояние

В проекте уже реализованы:

- project registry и per-project workspace isolation
- SQLite schema, migrations и service layer
- CRUD для functions, structures, global hypotheses, evidence и relations
- facts/hypotheses separation
- tags, FTS5 search и graph traversal
- pending changes с режимами `confirm` и `auto`
- audit trail и version history
- JSON import/export
- zip backup/restore
- local JSON HTTP API
- MCP tools, resources list stubs и полноценные MCP prompts
- Codex-compatible MCP Streamable HTTP handshake
- server-rendered web UI с home project shelf и workspace shell
- темная/светлая тема, русский/английский UI, sidebar icons и компактный dashboard

## Ограничения продукта

- Python и SQLite остаются базовым стеком.
- Runtime-зависимости не добавляются без явной необходимости.
- Проект не требует cloud, Docker, внешней БД или daemon-процессов.
- UI остается server-rendered и dependency-light.
- Semantic search и embeddings пока не реализованы.
- MCP resources пока возвращают пустые списки; данные доступны через MCP tools.

## Основные сущности

- `function`
- `structure`
- `global_hypothesis`
- `evidence`
- `relation`
- `pending_change`
- `audit_log`
- `entity_version`

Facts и hypotheses должны храниться раздельно. Псевдокод и крупные артефакты лучше сохранять как короткие evidence excerpts или отдельные attachments, а не как бесконечный raw text внутри основной записи.

## Агентский workflow

Агент подключается к MCP endpoint проекта, вызывает `initialize`, затем использует:

- `get_project_config`, чтобы понять проект и режим записи
- `search_records`, `get_record`, `get_related`, чтобы собрать контекст
- `create_*`, `update_*`, `add_evidence`, `create_relation`, чтобы записывать знания
- `list_pending_changes`, `confirm_change`, `reject_change` в `confirm` режиме
- `prompts/list` и `prompts/get`, чтобы получить точные инструкции по безопасной работе

В `confirm` режиме write tools создают proposal. В `auto` режиме запись применяется сразу.
