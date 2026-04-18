# Future Plans

Список ближайших продуктовых улучшений, которые пока не реализованы, но уже согласованы как желаемые направления развития проекта.

## 1. Entity Browser From Project Home

- Добавить возможность открыть список всех сущностей проекта с главного экрана workspace.
- Поддержать быстрые переходы:
  - все `functions`
  - все `structures`
  - все `global hypotheses`
  - все сущности сразу в одном общем представлении
- Цель: упростить навигацию по проекту без обязательного поискового запроса.

## 2. Project Launch From GUI [Done]

Status: done

Implemented in home UI: Start / Stop / Restart, Open Workspace, MCP endpoint visibility, and managed project HTTP/MCP lifecycle from a single `mcp-memory run-ui-home` entrypoint.

- Пользователь должен запускать только:
  - `mcp-memory run-ui-home`
- После этого home UI должен показывать список всех проектов и уметь запускать выбранный проект прямо из GUI.
- При запуске из GUI должны стартовать:
  - project HTTP server
  - project MCP server
- Цель: убрать необходимость отдельно запускать каждый проект вручную через CLI.

## 3. Replace Project Address On Dashboard With MCP Link

- На project dashboard заменить текущее поле с адресом проекта.
- Вместо него показывать поле со ссылкой или connection block для MCP endpoint проекта.
- Цель: сделать главное подключаемое значение более полезным для агентского workflow.

## 4. Project Settings In GUI

- Добавить возможность изменять настройки проекта из GUI.
- Обязательно поддержать изменение:
  - `write_mode`
- Желательно также дать редактировать:
  - `display_name`
  - `http_host/http_port`
  - `mcp_host/mcp_port`
- Цель: убрать необходимость править настройки проекта только через CLI или вручную.

## 5. Dark Theme In GUI

- Добавить полноценную тёмную тему в UI.
- Сохранить текущий дружелюбный визуальный стиль, а не делать generic dark dashboard.
- Желательно поддержать:
  - ручное переключение темы
  - сохранение выбора пользователя
- Цель: сделать интерфейс комфортным для долгих RE-сессий.

## 6. Agent Instructions In MCP Server

- Добавить инструкции для агентов на стороне MCP server.
- Нужен понятный способ передавать агенту:
  - правила работы с проектом
  - ограничения по записи
  - рекомендации по стилю и workflow
- Возможные варианты реализации:
  - отдельный MCP tool
  - системный resource / prompt surface
  - проектный instruction document, отдаваемый через MCP
- Цель: улучшить качество и предсказуемость агентской работы с knowledge base.
