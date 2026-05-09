# Phase 03 - Project Lifecycle, CLI, Transfer, And Legacy Import

Status: complete for v1.0.0 generic project lifecycle, transfer, backup portability, and legacy DB import.

Goal: make generic schemas part of project lifecycle and provide import/export paths for generic and legacy data.

Current decision: legacy data migration is explicit and opt-in through `import-legacy-db`; there is no automatic in-place migration.

## Work Items

- Update `ProjectService.create_project`:
  - accept bundled schema template name
  - accept explicit schema file path
  - default to `general_knowledge`
  - copy selected schema into project root
- Update CLI:
  - `create-project --schema <path>`
  - `create-project --schema-template <name>`
  - `show-schema`
  - `validate-schema`
  - `update-schema`
  - `import-legacy-db`
- Replace fixed JSON transfer format with generic portable bundle:
  - schema
  - records
  - relations
  - evidence
  - attachment refs
- Add legacy importer:
  - old `functions` -> generic `function`
  - old `structures` -> generic `structure`
  - old `hypotheses` -> generic `hypothesis`
  - old evidence/relations/tags -> generic core tables
  - import current state only

## Already Done

- Project creation accepts explicit schema paths and bundled schema templates.
- Project IDs are validated for DNS/path gateway use; reserved root paths such as `assets`, `projects`, `setup`, `health`, `mcp`, and `ui` are rejected.
- Project creation copies selected schema into `<project-root>/schema.json`.
- CLI supports:
  - `create-project --schema <path>`
  - `create-project --schema-template <name>`
  - `show-schema`
  - `validate-schema`
  - `update-schema`
- Home GUI and setup wizard can select bundled schema templates during project creation.
- Generic JSON export/import bundle is implemented as `bundle_version: 2`.
- Generic bundle includes:
  - project metadata
  - schema payload
  - generic records
  - generic relations
  - generic evidence
  - attachment metadata
- Import supports replacing existing generic project data.
- Export filters relations/evidence/attachments to generic records included in the bundle.
- Backup/restore includes `schema.json`, restores it into the project root, rewrites project IDs across known project-scoped tables, and tolerates older backup databases without generic tables.
- Legacy fixed `bundle_version: 1` import remains as a compatibility path for old fixed bundles.
- CLI `import-legacy-db` imports old fixed RE databases into a generic project using `reverse_engineering.schema.json`.
- Legacy import maps old functions, structures, global hypotheses, relations, evidence, and attachment references into generic records/relations/evidence.
- Legacy import is current-state only; old audit/version/pending/duplicate history is intentionally not migrated.
- Added service, HTTP, and MCP tests for generic export/import and backup/restore round trips.
- Added legacy importer regression coverage using an old-style sample database.

## Not Done Yet

- Existing fixed export behavior has been replaced by generic `bundle_version: 2`, but old fixed import compatibility remains in code.
- No automatic in-place migration is provided; users run `import-legacy-db` when ready.

## Acceptance Checks

- CLI can create a project from each bundled schema.
- CLI can validate and show a project schema.
- Generic export/import round-trips current project data.
- Backup/restore preserves generic schema and data.
- Legacy old-style DB imports into `reverse_engineering.schema.json`.
