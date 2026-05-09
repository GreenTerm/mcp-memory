# Phase 01 - Schema And Storage Foundation

Status: complete for v1.0.0 generic model; fixed-table cleanup remains compatibility cleanup.

Goal: introduce the project-local schema DSL and generic SQLite foundation while keeping the repository understandable during the big-bang transition.

## Already Done

- Added `Jinja2>=3.1,<4` to `pyproject.toml`.
- Project package version is now `1.0.0`.
- Added package-data entries for GUI templates and bundled schemas.
- Added `ProjectConfig.schema_path` with backward-compatible loading.
- Added `src/mcp_memory/schema.py` with schema dataclasses, validation, bundled schema loading, and project schema save/load helpers.
- Added bundled schema package `src/mcp_memory/schemas/`.
- Added bundled schemas:
  - `general_knowledge.schema.json`
  - `reverse_engineering.schema.json`
  - `infrastructure_deployment.schema.json`
  - `research_notes.schema.json`
- Added generic SQLite storage foundation to `sql/migrations/001_initial.sql`:
  - `records`
  - `relations`
  - `evidence`
  - `attachments`
  - `entity_versions`
  - `audit_log`
  - `pending_changes`
  - `search_documents`
  - `search_documents_fts`
- Added bundled schema template listing and schema source selection helpers.
- Updated `ProjectService.create_project` to copy a bundled or explicit schema into `<project-root>/schema.json`.
- Added CLI support for `create-project --schema`, `create-project --schema-template`, `show-schema`, `validate-schema`, and `update-schema`.
- Added `tests/test_schema.py` for bundled schemas and project schema copy behavior.

## Remaining Work

- Decide what old fixed RE tables remain temporarily for transition/legacy import and what is removed in vNext cleanup.
- Rename or document `entity_versions` as the generic version table, since the original plan called it `record_versions`.
- Extend schema-layer tests only as the DSL grows.

## Acceptance Checks

- Bundled schemas load and validate.
- A new project gets a valid `schema.json`.
- Existing registry entries without `schema_path` still load.
- Fresh DB bootstrap includes generic tables.
