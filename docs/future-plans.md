# Future Plans

Список ближайших улучшений, которые еще не реализованы или требуют отдельного аккуратного прохода. Завершенные GUI/MCP hotfixes сюда больше не заносим как pending work.

## 1. FTS Escaping For Hyphenated Queries

Проблема: SQLite FTS может трактовать строку с дефисом как выражение. Например `gui-seed` может привести к ошибке парсинга вместо обычного поиска.

Цель:

- безопасно quote/escape пользовательский FTS input
- сохранить exact/tag filters
- добавить regression tests для `gui-seed`, адресов и строк с символами вроде `-`, `.`, `:`
- обновить MCP prompt warning после исправления

Текущий workaround: искать по словам без дефиса (`gui seed`) или по `tag`.

## 2. Richer Entity Browser

Сейчас есть отдельные pages для functions, structures и global hypotheses. Следующий шаг - общий entity browser для больших проектов.

Идеи:

- единая страница всех сущностей
- быстрые фильтры по binary, tag, entity type, status
- compact rows для больших списков
- bulk links на graph/search
- сохранение query params при переходах

## 3. Relation Authoring From GUI

Graph уже показывает существующие relations, но создавать связи удобнее через MCP/API.

Цель:

- добавить простую GUI-форму `create_relation`
- дать быстрый переход из detail page к созданию relation
- валидировать entity type/id на уровне формы
- после создания вести на focused graph

## 4. Graph Polish

Текущий graph - server-generated SVG без внешних graph dependencies.

Возможные улучшения:

- более понятная легенда
- richer focus controls
- сохранение выбранных filters
- улучшенная плотность labels
- links from side list to detail pages with better context

## 5. MCP Resources If Needed

Сейчас MCP resources объявлены как list-only compatibility surface и возвращают пустые списки. Данные проекта доступны через tools.

Добавлять resources стоит только если появится реальная потребность клиента:

- `project://config`
- `project://recent`
- `entity://function/...`
- `entity://structure/...`
- `entity://hypothesis/...`

До этого tools проще, явнее и лучше подходят текущему локальному workflow.

## 6. Optional Importers

Будущие importers должны оставаться опциональными и offline-friendly.

Кандидаты:

- IDA export JSON
- Ghidra export JSON
- Binary Ninja export JSON
- generic symbol list import

Правило: importer не должен требовать внешнего daemon или cloud service.

## 7. Larger Project UX

Для проектов с сотнями и тысячами записей нужно проверить:

- скорость list pages
- размер HTML responses
- pagination или incremental filters
- graph caps and warnings
- понятные empty/error states

## 8. Packaging And Offline Install

Проверить сценарий:

```powershell
pip download .
pip install --no-index --find-links <wheelhouse> mcp-memory
```

Цель - сохранить простую установку на машине без интернета.
