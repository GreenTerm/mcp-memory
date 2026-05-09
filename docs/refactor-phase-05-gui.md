# Phase 05 - Generic Jinja2 GUI

Status: generic GUI and Home UI gateway implemented and verified for v1.0.0; old fixed pages still exist as compatibility code.

Goal: replace fixed function/structure/hypothesis UI with schema-generated generic pages.

## Work Items

- Completed:
  - Added a Jinja2-backed rendering layer with a small stdlib fallback for offline/local checks before dependencies are installed.
  - Added generic workspace routes:
    - `/ui/entities`
    - `/ui/records`
    - `/ui/records/{entity_type}/new`
    - `/ui/records/{entity_type}/{record_id_or_slug}`
    - `/ui/records/{entity_type}/{record_id_or_slug}/edit`
    - `/ui/schema`
  - Added schema-generated create/edit forms for generic records.
  - Added generic record list and detail pages.
  - Added generic search page backed by schema-configured search documents.
  - Added generic relation graph page and a schema-validated relation creation form.
  - Added generic evidence views and an add-evidence form for any record.
  - Routed generic pending confirm/reject actions through the generic workflow dispatcher.
  - Replaced workspace dashboard stats, quick entries, and recent updates with generic schema/record data.
  - Added generic sidebar entries for entity types, records, and schema.
  - Added Home GUI schema template selection for project creation and setup wizard.
  - Added basic structured schema builder actions for adding entity types, fields, and relation types.
  - Added GUI tests for generic record creation/detail/search/graph/evidence/pending/schema pages and schema-template project creation.
  - Integrated selected GUI improvements from `mcp-memory-main-0.2.0`:
    - Added `/ui/entities/new`, a schema-backed entity type constructor with dynamic fields, field metadata flags, enum options, optional relation types, validation, and schema save.
    - Added hints, styles, and Russian translations for the constructor UI.
    - Updated the workspace sidebar to generic-only navigation instead of fixed RE links.
  - Updated Home GUI project forms to propose the next available HTTP/MCP ports.
    - Added Home UI DNS/path gateway with `base_url`, gateway project links, and proxying for project UI/API/MCP.
    - Kept the existing responsive project grid instead of the snapshot's fixed two-column grid.

- Remaining:
  - Remove or retire old fixed function/structure/hypothesis pages.
  - Convert pending page styling/copy to generic-only terminology.
  - Expand schema builder beyond add-only CRUD:
  - edit/delete entity types
  - edit/delete fields
  - structured required/search/tag field selection edits
  - edit/delete relation types

## Acceptance Checks

- Passing:
  - GUI can create and read a generic `note` record from the default bundled schema.
  - GUI can search generic records.
  - GUI can create and render generic typed relations.
  - GUI can add and render generic evidence.
  - GUI can confirm generic pending record creation.
  - GUI dashboard uses generic records and schema stats.
  - GUI can display and save project `schema.json`.
  - GUI can add schema entity types, fields, and relation types through basic form actions.
  - GUI can create a new entity type and optional relation types from `/ui/entities/new`.
  - Home GUI project creation can select bundled schema templates.
  - Home GUI project creation defaults to the next unused local ports.
  - Home GUI can show and save Base URL and expose projects as `/<project_id>/ui/` and `/<project_id>/mcp`.

- Still required:
  - GUI can create and edit records for each bundled schema.
  - GUI can fully edit/delete schema metadata through the basic builder, not only add entries or raw JSON.
  - Existing records remain readable after live schema edits.
  - Backups, settings, and old fixed entity pages are fully retired or replaced.
