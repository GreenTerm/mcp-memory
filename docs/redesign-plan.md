# GUI Redesign Plan And Status

Version: 1.0.2.

This document records the current GUI direction. The original goal was to move away from the old Warm Lab look toward a calm Obsidian/Notion-like working interface without a heavy frontend stack.

## Summary

Implemented approach:

- stdlib HTTP server
- server-rendered HTML with Python helpers and Jinja2 where useful
- packaged CSS/JS
- no SPA
- no frontend build step
- dark-first UI with light theme
- compact workspace shell
- generic schema-driven pages
- DNS/path gateway from Home UI to project UI/API/MCP

## Public Interface

Home UI routes:

- `/`
- `/setup`
- `/projects/new`
- `/projects/{project_id}/edit`
- `/settings/base-url`
- `/<project_id>/ui/...`
- `/<project_id>/schema`
- `/<project_id>/records/...`
- `/<project_id>/mcp`

Workspace UI routes:

- `/ui/`
- `/ui/entities`
- `/ui/entities/new`
- `/ui/entities/{entity_type}/edit`
- `/ui/records`
- `/ui/records/{entity_type}/new`
- `/ui/records/{entity_type}/{record_id_or_slug}`
- `/ui/search`
- `/ui/graph`
- `/ui/evidence`
- `/ui/schema`
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

- Home project shelf with project cards, status, start/stop/restart, edit/delete, Base URL, gateway/local endpoints, and copyable MCP config.
- Workspace shell with sidebar, topbar, global search, theme switcher, language switcher, write-mode badge, and back-to-projects link.
- Generic dashboard with schema/record stats, quick entries, local paths, recent records, and MCP config.
- Generic entity browser and entity constructor.
- Generic record list, create/edit forms, detail pages, search, graph, evidence, pending, audit, import/export, backups, settings, and schema pages.
- Russian/English localization for the active UI, with UTF-8 text and layout fixes for long labels.
- Visual fixes for quick-entry cards, schema/entity pages, checkbox rows, language buttons, local path rows, and project creation forms.

## Current Visual Rules

- Main workspace content should use full-width sections and consistent padding.
- Repeated items may use cards; avoid cards nested inside cards.
- Sidebar contains generic workspace navigation only.
- The topbar owns global controls.
- Empty states must have internal padding and should not touch borders.
- Forms should keep short text fields compact and multiline fields intentionally taller.
- Motion must remain subtle and respect reduced-motion preferences.

## Verification

Use:

```powershell
python -X utf8 -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_checks.ps1
```

Current full suite verification: 155 tests pass, total coverage 95%.

## Remaining Polish

- current implementation plan and references: `docs/ui-redesign-implementation-plan.md`
- full schema builder edit/delete UX
- old fixed RE page retirement
- larger-project list pagination/filtering
- richer graph controls
