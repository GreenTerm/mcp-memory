# Phase 04 - Generic HTTP And MCP Surfaces

Status: generic surfaces implemented and verified for v1.0.0; old fixed-code paths remain compatibility cleanup.

Goal: replace fixed RE routes and MCP tools with generic schema-aware interfaces.

## HTTP Work Items

- Replace fixed routes with:
  - `GET /schema`
  - `PUT /schema`
  - `GET /entity-types`
  - `GET /records?entity_type=...`
  - `GET /records/{entity_type}/{record_id_or_slug}`
  - `POST /records/{entity_type}`
  - `PUT /records/{entity_type}/{record_id_or_slug}`
  - `POST /records/{entity_type}/{record_id_or_slug}/archive`
  - `POST /relations`
  - `GET /relations`
  - `GET /related`
  - `POST /evidence`
  - `GET /evidence`
  - `POST /search`
- Keep generic pending/import/export/backup routes.

## MCP Work Items

- Replace fixed RE tools with:
  - `get_schema`
  - `list_entity_types`
  - `search_records`
  - `get_record`
  - `upsert_record`
  - `archive_record`
  - `create_relation`
  - `get_related`
  - `add_evidence`
  - pending/import/export/backup tools
- Add generated schema-based tools as convenience wrappers over `upsert_record`.
- Preserve MCP session and Streamable HTTP compatibility behavior.
- Publish schema-aware agent instructions with examples for every tool and required/optional fields for record payloads.

## Acceptance Checks

- Passing:
  - HTTP generic CRUD/search/relation/evidence routes work.
  - HTTP generic writes work in confirm and auto modes.
  - MCP generic tools work in confirm and auto modes.
  - MCP no longer imports HTTP API helpers.
  - MCP publishes generic tools plus `get_project_config`; old fixed create tools are absent.
  - MCP prompts describe every tool with example payloads and schema-derived `upsert_record` fields.
  - Full suite passes with HTTP/MCP generic route and tool coverage.

- Not done yet:
  - Old fixed RE HTTP routes are still present during the transition.
  - Old fixed RE MCP tools have been removed from the published generic tool list, but broader cleanup of fixed code remains.
  - Generated schema-based MCP tools are not implemented yet.

## Already Done

- Added initial generic HTTP routes for schema, entity types, records, search, relations, related traversal, evidence, archive, and schema update.
- Generic HTTP writes now use `GenericWorkflowService`, so confirm mode queues and auto mode applies.
- Added API regression tests for generic record create/list/read/search/archive, relation creation/traversal, evidence, and pending confirm flow.
- Replaced MCP tool publishing with generic tools and removed MCP's import dependency on HTTP API helpers.
- Switched MCP pending tools to `GenericWorkflowService`.
- Added MCP regression tests for generic record create/search/read/archive, relation creation/traversal, evidence, and pending confirm flow.
- Added schema-aware MCP prompt reference blocks and write-tool metadata descriptions.
