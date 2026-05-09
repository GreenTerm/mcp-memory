# Phase 02 - Generic Core Services And Protocol

Status: complete for v0.8.0 generic model; fixed services remain isolated compatibility code.

Goal: replace fixed RE services with generic records, relations, evidence, pending workflow, and a typed in-process protocol.

## Work Items

- Add generic record service:
  - create/update/list/get records
  - UUID `record_id` generation
  - optional unique slug handling
  - required-field validation from schema
  - title/summary/search/tag derivation from schema
  - soft archive
  - version snapshots and audit rows
- Add generic relation service:
  - validate relation type against schema
  - enforce allowed `from` and `to` entity types
  - list/traverse graph links
- Add generic evidence service for any entity.
- Replace fixed pending operation dispatch with generic operation dispatch.
- Add typed command/query/result models and a central dispatcher.
- Remove adapter-to-adapter imports from core workflow.

## Already Done

- Added `RecordService`, `RecordWrite`, `Record`, and `RecordValidationError`.
- Implemented generic record create/update/list/get/archive.
- Implemented required field validation, UUID generation, slug handling, tags, FTS search document updates, audit rows, and version snapshots for records.
- Added `GenericRelationService`, typed relation writes, schema relation validation, relation listing, and 1-2 hop traversal.
- Added `GenericEvidenceService` for attaching evidence and attachment refs to any generic record.
- Added `mcp_memory.protocol.ProjectDispatcher` and typed query/command messages for schema, entity types, search, records, relations, related traversal, and evidence.
- Added `GenericWorkflowService` for generic pending changes, confirm/reject flow, and protocol-backed operation application.
- Added `tests/test_generic_records.py` for generic record CRUD/search/archive validation.

## Acceptance Checks

- Generic records can be created, updated, listed, searched, and archived.
- Required fields and slug uniqueness are enforced.
- Relations reject invalid entity-type pairs.
- Confirm mode queues generic writes; auto mode applies them.
- Audit and version rows are written for generic record changes.
- Full suite verification passes with generic core tests included.

## Remaining Work

- Remove or retire fixed RE services once adapters no longer depend on them.
- Broaden tests around edge cases for schema edits against existing records.
- Decide whether generated schema-specific convenience services/tools are needed or should stay as adapter wrappers only.
