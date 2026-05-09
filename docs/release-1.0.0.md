# Release 1.0.0 Notes

`mcp-memory` 1.0.0 is the first stable baseline for the local offline schema-first knowledge base.

## What Is Stable

- Project-local `schema.json` controls entity types, fields, display metadata, search metadata, and allowed relation types.
- Generic records use UUID `record_id` values and optional unique slugs.
- Typed relations, evidence, attachment references, search, pending changes, audit rows, and record versions are generic features.
- Home UI exposes the DNS/path gateway as the preferred public access pattern:
  - `/<project_id>/ui/`
  - `/<project_id>/schema`
  - `/<project_id>/records/...`
  - `/<project_id>/mcp`
- Direct per-project HTTP and MCP ports remain available for local/manual use.
- MCP prompts are schema-aware and include tool examples plus required/optional fields for the active schema.
- Import/export and backup/restore are local and portable.
- `import-legacy-db` remains the supported path for old fixed reverse-engineering databases.

## Included Release Checks

Run the release check before tagging:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_release_check.ps1
```

The release check validates:

- version metadata and key docs mention `1.0.0`
- README doc links resolve
- bundled schemas load and validate
- release scripts exist
- roadmap marks `0.9.0` and `1.0.0` complete
- full unittest discovery
- local smoke test
- coverage threshold

The local smoke test covers:

- CLI project creation from bundled schema
- generic record/relation/evidence services
- export/import
- backup/restore
- direct HTTP API
- direct MCP endpoint
- Home UI root
- Home gateway project UI/API/MCP paths

## Compatibility Notes

- The documented product surface is generic schema-first behavior.
- Old function/structure/hypothesis services and GUI/API routes still exist as compatibility surfaces and for legacy workflows.
- New projects should prefer schema templates and generic records instead of fixed reverse-engineering routes.

## Known Post-1.0 Backlog

- More visual regression automation for GUI screenshots.
- Richer graph interactions.
- Search snippets/ranking improvements.
- Optional generated per-entity MCP convenience tools.
- Final cleanup or removal decision for fixed reverse-engineering compatibility paths.
