# Release 0.8.0 Notes

`mcp-memory` 0.8.0 is a schema-first pre-release focused on making the generic knowledge base path the default product direction.

## Completed Stages

- [x] `0.3.1` Dashboard and UI consistency patch
- [x] `0.4.0` Schema Builder beta
- [x] `0.5.0` Operations and offline install hardening
- [x] `0.6.0` Agent workflow hardening
- [x] `0.7.0` Search and graph usability baseline
- [x] `0.8.0` Legacy code retirement/isolation baseline

## Highlights

- The server-rendered GUI now follows one workbench direction across the main generic pages.
- Entity creation and editing are GUI-first: metadata, fields, and relation types can be changed without opening raw JSON.
- Raw entity JSON remains available as an advanced fallback.
- MCP prompts describe every tool, include examples, and list required and optional payload fields from the active `schema.json`.
- Home UI gateway URLs are the preferred public way to open project UI/API/MCP endpoints.
- Offline installation, import/export, backup/restore, and local operation flows are documented in README and the temporary roadmap.
- Legacy fixed reverse-engineering surfaces remain compatibility code. The documented primary behavior is generic schema-first projects plus `reverse_engineering.schema.json` and `import-legacy-db`.

## Compatibility Notes

- Existing direct project HTTP and MCP ports are still supported.
- Existing generic API, MCP tools, CLI commands, GUI routes, import/export, backup/restore, and pending-change behavior are preserved.
- Fixed function/structure/hypothesis compatibility code has not been fully deleted because tests and existing users still exercise it. Treat it as legacy adapter surface, not the product path for new work.

## Verification For This Stage

Run:

```powershell
python -m unittest tests.test_api_server tests.test_gui_home tests.test_generic_records tests.test_transfer_archive tests.test_mcp_server -v
python -m unittest discover -s tests -v
python -m coverage run --rcfile .coveragerc -m unittest discover -s tests
python -m coverage report --rcfile .coveragerc
```

Suggested GUI smoke pages through Home gateway:

- `http://127.0.0.1:8764/<project_id>/ui/?lang=ru`
- `http://127.0.0.1:8764/<project_id>/ui/entities?lang=ru`
- `http://127.0.0.1:8764/<project_id>/ui/entities/new?lang=ru`
- `http://127.0.0.1:8764/<project_id>/ui/records/<entity_type>/new?lang=en`
- `http://127.0.0.1:8764/<project_id>/ui/search?lang=ru`
- `http://127.0.0.1:8764/<project_id>/ui/graph?lang=ru`

## Remaining Before 1.0

- Formal clean Windows install dry run from pre-downloaded wheels.
- Playwright-backed visual smoke script committed as a repeatable release check.
- Final decision on deleting, hiding, or keeping the legacy fixed RE GUI/API compatibility surface.
- Release-candidate docs pass for `0.9.0`.
