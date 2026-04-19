# GUI Redesign Plan And Status

Этот документ фиксирует план редизайна workspace UI и его текущий статус. Изначальная цель была перейти от старого Warm Lab вида к спокойному Obsidian/Notion-like интерфейсу без тяжелого frontend stack.

## Summary

Реализованный подход:

- stdlib HTTP server
- server-rendered Python HTML helpers
- packaged CSS/JS
- no SPA
- no external frontend dependencies
- dark-first UI with light theme
- compact workspace shell
- consistent cards, sections and empty states

## Public Interface

Routes сохранены и расширены:

- `/`
- `/projects/new`
- `/ui/`
- `/ui/search`
- `/ui/functions`
- `/ui/functions/new`
- `/ui/functions/{binary_id}/{function_id}`
- `/ui/structures`
- `/ui/structures/new`
- `/ui/structures/{structure_id}`
- `/ui/global-hypotheses`
- `/ui/global-hypotheses/new`
- `/ui/global-hypotheses/{hypothesis_id}`
- `/ui/graph`
- `/ui/import-export`
- `/ui/backups`
- `/ui/settings`
- `/ui/pending`
- `/ui/audit`

Packaged assets:

- `/assets/app.css`
- `/assets/ui.js`
- `/ui/assets/app.css`
- `/ui/assets/ui.js`

## Completed Work

### Home GUI / Project Shelf

Done:

- project cards
- project status
- Start / Stop / Restart
- Open Workspace
- Copy MCP config
- Edit / Delete menu on project cards
- better action-row spacing
- consistent project card padding

### Workspace Shell

Done:

- app shell with sidebar and topbar
- sidebar icons
- collapsed sidebar state
- simple open/close animations
- page transition polish
- global search in topbar
- theme switcher
- language switcher
- single write-mode status indicator
- duplicate workspace controls removed
- `Projects` removed from sidebar
- explicit back-to-project-shelf link in workspace header

### Header And Dashboard Cleanup

Done:

- `Warm Lab` removed from workspace UI
- oversized hero spacing removed
- compact breadcrumb/title header
- dashboard starts with project summary card
- main blocks use consistent card layout
- empty states have proper padding
- quick entries have stable card structure

### Entity Pages

Done:

- functions list page
- structures list page
- global hypotheses list page
- create/edit forms
- detail pages
- history views
- audit links
- focused graph links

### Search And Graph

Done:

- `/ui/search` with filters and cards
- search empty state inside section/card wrapper
- `/ui/graph` route
- server-generated SVG graph
- graph filters
- focused graph from entity pages
- graph empty state with links back to Search/Functions

### Settings, Import/Export, Backups

Done:

- `/ui/settings`
- editable display name, write mode and endpoints
- readable Russian strings
- `/ui/import-export`
- `/ui/backups`
- POST flows for export/import/backup/restore

### I18n And Encoding

Done:

- Russian mojibake fixed in UI translations
- regression tests for Russian settings page
- language preservation across shell controls
- single language switcher in topbar

## Current Visual Rules

- Main workspace content should be in cards/sections with consistent padding.
- The app shell topbar owns global controls.
- `workspace_header(...)` owns local identity only: breadcrumb, title, project subtitle and back link.
- Sidebar contains workspace navigation only, not project shelf navigation.
- Empty states must not touch borders.
- Buttons in action rows should keep stable gaps and vertical alignment.
- Motion must remain subtle and respect reduced-motion preferences.

## Verification

Use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_checks.ps1
```

Expected:

- `process_exit_code=0`
- `coverage_process_exit_code=0`
- coverage `>=95%`

Relevant UI coverage includes:

- shell controls are not duplicated
- sidebar no longer contains `Projects`
- header contains back-to-shelf link
- `Warm Lab` is absent
- Russian UI strings are readable
- graph/search empty states render inside card/section wrappers
- dashboard still renders summary, quick entries, storage paths and recent updates

## Remaining Polish

- relation creation from GUI
- richer graph controls
- entity browser for all record types
- FTS escaping for hyphenated search terms
