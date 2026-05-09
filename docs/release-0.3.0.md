# Release 0.3.0

`mcp-memory` 0.3.0 is the first documented schema-first release line for the generic knowledge base.

## Highlights

- Generic project-local `schema.json` model with bundled templates.
- Generic records, typed relations, evidence, search, pending changes, audit, versions, export/import, backup/restore, and legacy DB import.
- Server-rendered Home UI and workspace UI with English/Russian localization.
- Home UI DNS/path gateway:
  - Home: `<base_url>/`
  - Project UI/API: `<base_url>/<project_id>/ui/...`, `<base_url>/<project_id>/schema`, `<base_url>/<project_id>/records/...`
  - Project MCP: `<base_url>/<project_id>/mcp`
- Schema-aware MCP prompts with examples for every tool and required/optional fields for `upsert_record`.
- Offline-friendly dependency footprint with Jinja2 as the only runtime dependency.

## Compatibility

- Direct per-project HTTP and MCP ports remain supported.
- Old fixed reverse-engineering databases are imported explicitly with `import-legacy-db`.
- Old fixed service and route code still exists as transitional implementation detail and should not be treated as the preferred public surface.

## Verification

Latest direct unit suite:

```powershell
python -X utf8 -m unittest discover -s tests -v
```

Result: 155 tests, OK.
