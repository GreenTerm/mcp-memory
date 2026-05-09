# UI Redesign Implementation Plan

Version: 1.0.0.

This plan tracks the current UI polish pass for the server-rendered MCP Memory GUI. The goal is to keep the app simple and offline-friendly while making the workspace feel more like a dense professional knowledge tool than a collection of large cards.

## Goals

- Keep the current Python-rendered GUI, stdlib servers, packaged CSS/JS, and no frontend build step.
- Improve scanability of the dashboard, entity browser, schema overview, and entity constructor.
- Reduce visual noise: no letter badges in quick entries, fewer oversized blocks, more consistent compact controls.
- Make destructive actions visible but calm, especially entity delete actions.
- Make forms match expected input size: short text fields stay short; descriptions and JSON remain intentionally larger.
- Preserve routes, form names, query parameters, localization hooks, and tests.

## References

- Carbon Data Table: compact table structure, toolbar-first scanning, aligned actions. https://v10.carbondesignsystem.com/components/data-table/usage/
- Carbon Filtering: make filtering visible, reversible, and close to the result set. https://carbondesignsystem.com/patterns/filtering/
- Atlassian Forms: group related fields, use field lengths that match expected input. https://atlassian.design/patterns/forms
- Atlassian Empty State: empty states should explain the state and offer the next useful action. https://atlassian.design/foundations/content/designing-messages/empty-state
- SAP Fiori Empty States: differentiate neutral, error, and permission-empty cases. https://www.sap.com/design-system/fiori-design-web/v1-136/foundations/best-practices/global-patterns/designing-for-empty-states
- Material Navigation Drawer: stable workspace navigation with clear active state and compact icons. https://m1.material.io/patterns/navigation-drawer.html
- Microsoft UI/UX principles: reduce cognitive load and keep operational interfaces predictable. https://learn.microsoft.com/en-us/dynamics365/guidance/develop/ui-ux-design-principles
- Airtable field types: schema/field editing should look like property rows, not generic nested forms. https://support.airtable.com/docs/field-type-overview
- Notion database properties: property metadata is easier to scan as rows with type/role chips. https://www.notion.com/help/database-properties
- Cytoscape.js: future graph controls reference for fit, focus, legends, and graph interaction vocabulary. https://js.cytoscape.org/
- AntV G6 Behaviors: future reference for graph pan/zoom/focus behaviors. https://g6.antv.antgroup.com/en/manual/behavior/overview

## Phases

### Phase 1: Dashboard And Navigation Polish

- Replace quick-entry letter badges with quiet icon-style squares or remove markers entirely.
- Keep quick-entry cards compact with a stable title offset, consistent internal padding, and predictable grid density.
- Keep "Back to Projects" available from every workspace through the sidebar and topbar patterns.
- Improve local path display as one path per row, with readable wrapping and copy-friendly code style.

Verify:

- Dashboard contains the same links as before.
- No quick-entry card depends on first-letter badges.
- Russian and English dashboard text still localizes through existing markup localization.

### Phase 2: Entity Browser And Schema Overview

- Make `/ui/entities` feel like a compact management table: label, system name, required fields, actions.
- Keep New/Edit/Delete actions aligned and compact.
- Style delete as a muted danger action, not a bright warning block.
- Keep `/ui/schema` as an overview + JSON editor, with entity/relation summaries as readable cards/chips.
- Do not reintroduce duplicate Add Entity Type/Add Field/Add Relation forms on `/ui/schema`.

Verify:

- Entity create/edit/delete routes still work.
- Schema page still exposes `schema_json`.
- Tests continue to assert that duplicate add forms are absent from `/ui/schema`.

### Phase 3: Entity Constructor

- Redesign field rows as property-editor rows inspired by Airtable/Notion: field identity on the left, role toggles on the right.
- Avoid a visually empty right half by giving the role area a clear label and compact toggle chips.
- Use the same checkbox treatment for field rows and relation rows.
- Keep dynamic JavaScript row insertion simple and inline, with unchanged field names.

Verify:

- Existing constructor form names remain stable.
- Sparse dynamic rows continue to submit correctly.
- Relation rows keep `rel_name_*`, `rel_label_*`, `rel_from_*`, `rel_to_*`, `rel_directed_*`.

### Phase 4: Search, Records, Empty States, And Graph

- Make search feel like a focused retrieval surface: prominent search input, compact filters, results below.
- Keep record list tables dense and action-oriented.
- Use empty states with internal padding, concise text, and a clear next action where possible.
- Improve graph layout readability with better panel spacing and side-list density. Full interactive graph libraries remain future work.

Verify:

- Generic search and legacy search both pass.
- Graph filter invalid states still show useful warnings.
- Empty result states do not collapse against section borders.

### Phase 5: Verification And Documentation

- Update docs with completed status and design references.
- Add focused assertions only where they prevent regression of the reported issues.
- Run full unittest discovery and coverage.

Verify:

- `python -m unittest discover -s tests -v`
- `python -m coverage erase`
- `python -m coverage run --rcfile .coveragerc -m unittest discover -s tests`
- `python -m coverage report --rcfile .coveragerc`

## Parallel Work Plan

- Worker A owns CSS only: `src/mcp_memory/gui/assets/app.css`.
- Worker B owns dashboard/workspace markup only: `src/mcp_memory/gui/workspace.py`.
- Worker C owns generic entity/schema/constructor markup only: `src/mcp_memory/gui/generic.py`.
- Main thread owns docs, integration, conflict review, focused test updates, and final verification.

Workers must not edit tests at the same time. After their changes return, the main thread adds or adjusts tests once the final markup shape is known.

## Current Status

- Branch created: `codex/ui-redesign-references`.
- Plan documented: done.
- Worker implementation: done.
- Integration review: done.
- Regression tests: done.
- Full verification: done.

Latest verification:

- `python -m unittest discover -s tests -v`: 155 tests pass.
- `python -m coverage run --rcfile .coveragerc -m unittest discover -s tests`: 155 tests pass.
- `python -m coverage report --rcfile .coveragerc`: total coverage 95%.
