# План миграции GUI на новый Obsidian/Notion design

## Summary

- Переезжаем с текущего Warm Lab UI на новый дизайн из `docs/design-prompt.md`: 70% Obsidian, 30% Notion, dark-first, calm, плотный, без admin-dashboard ощущения.
- Стек остается текущим: stdlib HTTP + server-rendered Python render helpers + packaged CSS/маленький JS. FastAPI/Jinja из prompt трактуем как template-архитектуру, но без новой runtime-зависимости.
- Миграция идет фазами: сначала дизайн-система и shell, затем текущие страницы, затем недостающие страницы из prompt.
- Темы `dark/light` хранятся в браузере через `localStorage`; backend registry не меняем.
- Coverage держим не ниже `95%`, текущий smoke workflow расширяем, но не ломаем.

## Public Interfaces

- Новые workspace routes:
  - `GET /ui/functions`
  - `GET /ui/structures`
  - `GET /ui/global-hypotheses`
  - `GET /ui/graph`
  - `GET /ui/import-export`
  - `POST /ui/import-export/export`
  - `POST /ui/import-export/import`
  - `GET /ui/backups`
  - `POST /ui/backups/create`
  - `POST /ui/backups/restore`
- Новые home/setup routes:
  - `GET /setup`
  - `POST /setup/project`
- Новые packaged assets:
  - `/assets/ui.js`
  - `/ui/assets/ui.js`
- Existing routes remain compatible:
  - Home GUI `/`, `/projects/new`, start/stop/restart
  - Workspace `/ui/`, `/ui/search`, `/ui/settings`, `/ui/pending`, `/ui/audit`
  - Existing detail/edit/history routes for functions, structures, global hypotheses

## Implementation Plan

### Phase 0. Safety Baseline

1. Проверить текущую ветку и diff, чтобы не смешать редизайн с generated artifacts вроде `.coverage`, `artifacts/`, `__pycache__`.
2. Запустить текущий локальный baseline через `scripts/run_local_checks.ps1` или использовать последний успешный результат как стартовую точку.
3. Зафиксировать визуальный contract: dark-first, light supported, no external fonts, no frontend deps, no SPA.
4. Добавить краткий internal checklist в тесты/комментарии только если нужен для smoke, без новых пользовательских документов на этом шаге.

### Phase 1. Design System Foundation

1. Переписать `app.css` на token-based систему: `--bg`, `--panel`, `--ink`, `--muted`, `--accent`, `--border`, `--confidence-*`, `--status-*`.
2. Сделать default `data-theme="dark"` и light override через `[data-theme="light"]`.
3. Добавить typography stack без web fonts: спокойный sans для UI, выразительный local serif/display только для крупных заголовков.
4. Добавить базовые компоненты CSS: sidebar, topbar, breadcrumbs, cards, list rows, detail panel, tabs, badges, empty states, action cards, forms.
5. Добавить `ui.js`: theme toggle, sidebar collapse persistence, copy-to-clipboard для MCP config; все функции progressive enhancement.
6. Расширить `html_page(...)`, чтобы он умел подключать shared CSS/JS, задавать body/layout classes и не ломал старые страницы.

### Phase 2. Shared Layout Components

1. Вынести reusable GUI helpers в текущий render layer, например `gui/render.py` или новый маленький `gui/components.py`.
2. Добавить `app_shell(...)`: sidebar + topbar + breadcrumbs + main content + optional right panel.
3. Добавить `sidebar_nav(...)` с пунктами: Projects, Binaries, Functions, Structures, Hypotheses, Search, Graph, Import/Export, Backups, Settings.
4. Добавить `top_search(...)`, который ведет на `/ui/search?q=...` и сохраняет `lang`.
5. Добавить `breadcrumbs(...)` и использовать на каждой workspace странице.
6. Добавить badge helpers для entity type, confidence, hypothesis status и write mode.
7. Добавить `mcp_config_block(...)` с endpoint и copy button.

### Phase 3. Home GUI / Projects List Redesign

1. Перестроить `/` как Projects List из prompt: карточки проектов вместо dashboard-like блоков.
2. В каждой карточке показывать display name, project id, DB path, HTTP/MCP endpoints, status, Start/Stop/Restart/Open Workspace.
3. Добавить Copy MCP config на карточку проекта.
4. Сохранить существующий flow создания проекта `/projects/new`, но привести форму к новой дизайн-системе.
5. Если проектов нет, показывать calm first-run empty state с CTA на `/setup` и `/projects/new`.
6. Проверить, что language switcher, flash messages и runtime status не регрессируют.

### Phase 4. Workspace Overview Redesign

1. Перестроить `/ui/` как Project Overview, а не generic dashboard.
2. Верхняя зона: project name, project summary, write mode, MCP endpoint, Copy MCP config.
3. Stats cards: binaries count, functions, structures, hypotheses, pending, recent updates.
4. Quick entries: Functions, Structures, Hypotheses, Graph, Search, Settings, Import/Export, Backups.
5. Secondary details: DB path, exports dir, backups dir, HTTP endpoint.
6. Recent updates брать из `search_documents` или существующих list services, без новой схемы БД.

### Phase 5. Entity List Pages

1. Добавить `/ui/functions` с hybrid list rows: name, summary, status/confidence, binary, address, tags, updated date.
2. Добавить `/ui/structures` с аналогичным list view: name, summary, binary, fields count, tags, updated date.
3. Добавить `/ui/global-hypotheses` как простой список: title/text, status, confidence, linked entities where available, updated date.
4. Фильтры делать server-rendered через GET params: `q`, `binary_id`, `tag`, `status`, `sort`.
5. Не делать heavy tables; строки должны быть карточками/list rows с clear hover/focus state.
6. В sidebar и overview добавить ссылки на эти pages.

### Phase 6. Entity Detail Redesign

1. Перестроить Function Detail в main column + right metadata panel.
2. Header function detail: current/raw name, address, binary, confidence, status badges, tags, updated date.
3. Tabs сделать server-side через `?tab=facts|hypotheses|relations|history`; default `facts`.
4. Facts и hypotheses держать визуально раздельно, даже если отображаются рядом.
5. Relations tab показывает callers/callees/structures/hypotheses как readable links, плюс link на focused graph.
6. History tab переиспользует текущий version/history flow, но в новом visual style.
7. Structure Detail и Global Hypothesis Detail привести к той же layout-схеме с собственными metadata panels.
8. Existing edit/create forms сохранить функционально, но визуально привести к новым form components.

### Phase 7. Search And Graph

1. Перестроить `/ui/search`: top search + filters + result cards с preview и direct open links.
2. Global top search на всех workspace pages ведет в `/ui/search`.
3. Добавить `/ui/graph` без внешних graph libraries.
4. Graph v1 рендерить как server-generated SVG + side list, links from nodes ведут на detail pages.
5. Graph filters: focus entity, binary, entity type, hypothesis status, min confidence, hops `1|2`.
6. Если focus entity не выбран, показывать recent relation clusters с cap, например 50 nodes и 80 edges.
7. Если связей нет, показывать friendly empty state и ссылку на Search/Functions.

### Phase 8. Settings, Import/Export, Backups

1. Перестроить `/ui/settings` по новому дизайну: action cards, MCP config, DB path, network settings, write mode.
2. Добавить `/ui/import-export` с local-path text fields, без multipart upload и без новых deps.
3. `POST /ui/import-export/export` вызывает `ProjectTransferService.export_project(...)`.
4. `POST /ui/import-export/import` вызывает `ProjectTransferService.import_project(...)`, с checkbox `replace_existing`.
5. Добавить `/ui/backups` с create backup и restore controls.
6. `POST /ui/backups/create` вызывает `ProjectArchiveService.create_backup(...)`.
7. `POST /ui/backups/restore` восстанавливает backup как новый project через registry, не перезаписывает текущий project silently.
8. Для destructive-ish операций показывать validation errors inline и success flash после redirect.

### Phase 9. First-Run Setup Wizard

1. Добавить `/setup` в home GUI как спокойный 4-step wizard.
2. Step 1 показывает app home, registry path и объясняет offline-local модель.
3. Step 2 создает project через тот же parser/service, что `/projects/new`.
4. Step 3 показывает MCP endpoint и Copy MCP config для созданного project.
5. Step 4 показывает DB path, exports dir, backups dir и links на Backup/Export pages.
6. `POST /setup/project` после успеха редиректит на `/setup?project_id=<id>&flash=created&lang=<lang>`.
7. Если project уже создан, wizard не создает второй автоматически, а показывает next steps.

### Phase 10. I18n, Accessibility, Responsive Polish

1. Все новые строки добавить в существующий `i18n.py`.
2. Все links/forms сохраняют `lang`.
3. Theme/sidebar controls получают aria-label и keyboard focus states.
4. Добавить `prefers-reduced-motion` handling для любых transitions.
5. Проверить mobile-safe поведение: sidebar складывается, detail panel уходит под main column, формы без horizontal scroll.
6. Убрать визуальную зависимость от цвета: statuses должны читаться по тексту и форме badge.

### Phase 11. Tests And Smoke

1. Unit tests для asset routing: CSS и `ui.js` доступны в home/workspace.
2. Tests для home redesign: projects list, MCP copy block, empty state, setup links.
3. Tests для workspace shell: sidebar links, top search, breadcrumbs, theme toggle markup.
4. Tests для entity list pages: functions, structures, hypotheses routes return `200`, filters preserve values, records link to details.
5. Tests для detail tabs: facts/hypotheses/relations/history render correct content and not-found still works.
6. Tests для graph: empty graph, focused graph, hops validation, cap behavior.
7. Tests для import/export/backups POST flows using temp paths.
8. Tests для setup wizard valid/invalid create flow.
9. Update `scripts/local_smoke_check.py`: home opens, setup/create works, start project, overview/list/detail/search/graph/settings/import-export/backups pages open.
10. Keep coverage total `>=95%`; if local Codex VM cannot run checks, use existing `scripts/run_local_checks.ps1` artifact workflow.

## Assumptions And Defaults

- No new runtime dependencies; no FastAPI/Jinja migration in this redesign phase.
- No database schema migration is required for visual redesign and list/graph/import pages.
- Default theme is dark; light theme is available via browser-persisted toggle.
- Import/Export/Backup forms use local filesystem path text inputs, not file uploads.
- Graph v1 is readable and useful, not a full interactive canvas.
- Restore from backup creates/restores into a project target explicitly provided by the user; it must not silently overwrite the currently open project.
- Current JSON API, MCP API, CLI commands and existing GUI routes remain backward-compatible.
