# mcp-memory

`mcp-memory` 1.0.2 is a local light-weigth schema-driven knowledge base for people and agents.

Projects are stored as isolated Windows-local workspaces with SQLite, files on disk, a JSON HTTP API, an MCP Streamable HTTP endpoint, and a server-rendered web UI. The current model is generic: each project has a portable `schema.json` that defines its entity types, fields, search metadata, and relation types.

## Features

- Project-local `schema.json`
- Bundled schema templates:
  - `general_knowledge`
  - `reverse_engineering`
  - `infrastructure_deployment`
  - `research_notes`
- Generic records with UUID `record_id` and optional unique slugs
- Typed relations between records
- Evidence and attachment references for any record
- SQLite FTS search driven by schema metadata
- Confirm/auto write modes with pending changes
- Audit rows and version snapshots for generic changes
- Soft archive for records
- Generic JSON export/import with schema included
- Workspace zip backup/restore with schema included
- Legacy importer from the old fixed RE database shape
- DNS/path gateway from Home UI to project UI/API/MCP endpoints
- Schema-aware MCP prompts with tool examples and required/optional fields
- Generic HTTP API, MCP tools, CLI, and server-rendered GUI

The project is designed for simple local deployment. It avoids cloud services, external databases, background daemons, and heavy frontend stacks.

## Requirements

- Windows
- Python 3.10+

Install from the repository root:

```powershell
python -m pip install -e .
```

For tests and coverage:

```powershell
python -m pip install -e .[dev]
```

Without editable install, use `PYTHONPATH`:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
python -m mcp_memory.cli --help
```

## Offline Dependency Workflow

Dependencies are intentionally small and can be prepared for an offline machine with `pip download`.

Example from an online Windows machine:

```powershell
python -m pip download `
  --dest .\wheelhouse `
  --only-binary=:all: `
  --platform win_amd64 `
  --python-version 310 `
  .
```

Then copy `wheelhouse` and install offline:

```powershell
python -m pip install --no-index --find-links .\wheelhouse mcp-memory
```

The GUI uses Jinja2. It is a normal pip-installable wheel and does not require a service or network access at runtime.

## Quick Start

Initialize the global app registry:

```powershell
mcp-memory init-app
```

App home resolution order:

1. `MCP_MEMORY_HOME`
2. `%LOCALAPPDATA%\mcp-memory`
3. `.\.mcp-memory`

Create a generic project from a bundled schema:

```powershell
mcp-memory create-project sample `
  --name "Sample Project" `
  --schema-template general_knowledge `
  --write-mode confirm
```

Create a project from an explicit schema file:

```powershell
mcp-memory create-project sample `
  --name "Sample Project" `
  --schema F:\schemas\my-project.schema.json
```

Run the home UI:

```powershell
mcp-memory run-ui-home
```

Default endpoints:

- Home UI: `http://127.0.0.1:8764/`
- Project workspace UI through Home gateway: `http://127.0.0.1:8764/sample/ui/`
- Project HTTP API through Home gateway: `http://127.0.0.1:8764/sample/schema`
- Project MCP through Home gateway: `http://127.0.0.1:8764/sample/mcp`
- Direct project workspace UI: `http://127.0.0.1:8765/ui/`
- Direct HTTP API health: `http://127.0.0.1:8765/health`
- Direct MCP health: `http://127.0.0.1:9876/health`
- Direct MCP endpoint: `http://127.0.0.1:9876/mcp`

DNS/path gateway:

- Point DNS such as `mcp-memory.local` to the machine running Home UI.
- In Home UI, set Base URL to `http://mcp-memory.local:8764`.
- Open projects at `http://mcp-memory.local:8764/<project_id>/ui/`.
- Use MCP endpoints at `http://mcp-memory.local:8764/<project_id>/mcp`.
- Old direct project ports stay available for local/manual use.
- Detailed setup and troubleshooting: [docs/dns-path-gateway.md](docs/dns-path-gateway.md).

Manual project servers:

```powershell
mcp-memory run-http-api sample
mcp-memory run-mcp sample
```

## Schema Commands

```powershell
mcp-memory show-schema sample
mcp-memory validate-schema --project-id sample
mcp-memory validate-schema --schema F:\schemas\schema.json
mcp-memory update-schema sample --schema F:\schemas\schema.json
```

Schema v1 supports:

- `entity_types`
- fields with widgets: `text`, `textarea`, `number`, `bool`, `enum`, `tags`, `json`, `datetime`, `url`, `path`
- `required`
- `title_field`
- `summary_field`
- `slug_field`
- `search_fields`
- `tag_fields`
- `relation_types` with allowed `from` and `to` entity types

## CLI

Main commands:

```powershell
mcp-memory init-app
mcp-memory create-project <project_id> --name "<display_name>"
mcp-memory list-projects

mcp-memory show-schema <project_id>
mcp-memory validate-schema --project-id <project_id>
mcp-memory update-schema <project_id> --schema schema.json

mcp-memory run-http-api <project_id> [--host 127.0.0.1] [--port 8765]
mcp-memory run-mcp <project_id> [--host 127.0.0.1] [--port 9876]
mcp-memory run-ui-home [--host 127.0.0.1] [--port 8764]

mcp-memory export-json <project_id> [--output bundle.json]
mcp-memory import-json <project_id> --input bundle.json [--replace-existing]
mcp-memory import-legacy-db <project_id> --input old-project.db [--source-project-id old] [--replace-existing]
mcp-memory backup-project <project_id> [--output backup.zip]
mcp-memory restore-project --input backup.zip --project-root F:\restored

mcp-memory list-pending <project_id> [--status pending|all]
mcp-memory confirm-change <project_id> <pending_change_id>
mcp-memory reject-change <project_id> <pending_change_id>
```

## HTTP API

Generic routes:

- `GET /schema`
- `PUT /schema`
- `GET /entity-types`
- `GET /records?entity_type=note`
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
- `GET /pending-changes`
- `POST /pending-changes/{id}/confirm`
- `POST /pending-changes/{id}/reject`
- `POST /export/json`
- `POST /import/json`
- `POST /backup`
- `POST /restore`

Create a record:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/records/note `
  -ContentType "application/json; charset=utf-8" `
  -Body '{"payload":{"slug":"first-note","title":"First Note","body":"hello agents"},"created_by":"user"}'
```

Search:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/search `
  -ContentType "application/json; charset=utf-8" `
  -Body '{"q":"agents","entity_types":["note"],"limit":10}'
```

## MCP Tools

Generic tools:

- `get_project_config`
- `get_schema`
- `list_entity_types`
- `search_records`
- `get_record`
- `upsert_record`
- `archive_record`
- `create_relation`
- `get_related`
- `add_evidence`
- `list_pending_changes`
- `confirm_change`
- `reject_change`
- `export_json`
- `import_json`
- `backup_project`
- `restore_project`

In `confirm` mode, write tools return a pending change. Call `list_pending_changes`, review the payload, then call `confirm_change`.

Agent instructions are available through MCP prompts:

- `agent_workspace_guide`
- `record_function_analysis`
- `record_structure_analysis`
- `record_hypothesis_evidence`
- `search_and_graph_workflow`

`agent_workspace_guide` includes example arguments for every tool. It also reads the active project `schema.json` and lists every entity type with required and optional payload fields for `upsert_record`.

## Web UI

Home UI:

- lists registered projects
- starts, stops, and restarts project HTTP/MCP processes
- creates projects from schema templates
- shows gateway and local endpoints plus MCP config
- stores optional Base URL for DNS/path links such as `http://mcp-memory.local:8764/<project_id>/ui/`

Workspace UI:

- generic dashboard
- entity type browser
- generic record list/detail/create/edit
- schema-generated forms
- search
- relation graph
- evidence forms
- schema editor and basic schema builder actions
- pending changes
- import/export
- backups
- settings

Important routes:

```text
/ui/
/ui/entities
/ui/records
/ui/records/{entity_type}/new
/ui/records/{entity_type}/{record_id_or_slug}
/ui/search
/ui/graph
/ui/schema
/ui/import-export
/ui/backups
/ui/settings
/ui/pending
/ui/audit
```

## Legacy Import

Old fixed reverse-engineering databases can be imported into a generic project:

```powershell
mcp-memory create-project imported-re `
  --name "Imported RE" `
  --schema-template reverse_engineering

mcp-memory import-legacy-db imported-re `
  --input F:\old-project\project.db `
  --source-project-id old-project `
  --replace-existing
```

Mappings:

- old `functions` -> generic `function` records
- old `structures` -> generic `structure` records
- old global hypotheses -> generic `hypothesis` records
- old evidence -> generic evidence attached to imported records
- old relations -> generic typed relations when both endpoints are imported

The importer migrates current state only. It does not preserve old audit, version, pending, duplicate, or conflict history.

## Verification

Run the full test suite:

```powershell
$env:TEMP=(Resolve-Path .\artifacts).Path
$env:TMP=$env:TEMP
python -X utf8 -m unittest discover -s tests -v
```

Run the local smoke check:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_checks.ps1
```

Smoke output is written under `artifacts/`.

Run the full release check before tagging a release:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_release_check.ps1
```

The release check validates version metadata, docs links, bundled schemas, unit tests, local smoke, and coverage. Output is written to `artifacts/release_check.txt`.

## Additional Docs

- [Module guide](docs/modules.md)
- [Generic refactor status](docs/generic-knowledge-refactor-plan.md)
- [Release 0.3.0 notes](docs/release-0.3.0.md)
- [Release 0.8.0 notes](docs/release-0.8.0.md)
- [Release 1.0.0 notes](docs/release-1.0.0.md)
- [Release roadmap and backlog](docs/temporary-release-roadmap.md)
- [Future plans](docs/future-plans.md)
