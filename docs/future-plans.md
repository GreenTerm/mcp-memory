# Future Plans

Version: 1.0.4.

This list tracks work that is still useful after the generic schema-first refactor, DNS/path gateway, and schema-aware MCP instructions.

Release planning and the post-1.0 backlog live in [Release Roadmap And Backlog](temporary-release-roadmap.md).

## 1. Search Query Polish

Status: basic FTS escaping for hyphenated text shipped before 1.0.0. Queries such as `gui-seed` are now quoted before reaching SQLite FTS.

Goal:

- broaden regression tests for addresses and text with `.`, `:`, paths, and mixed punctuation
- decide whether quoted phrases, AND semantics, or prefix search should be exposed explicitly
- improve search result ranking/snippets once the schema-first model settles

## 2. Retire Fixed RE Transitional Code

The 1.0.0 public docs describe the generic schema-first surface, but some old function/structure/hypothesis routes, services, and GUI paths still exist to keep tests and import workflows stable during the transition.

Goal:

- keep `import-legacy-db` as the supported old-data entrypoint
- remove or isolate old fixed HTTP routes and GUI pages
- reduce old service code once the importer no longer needs direct legacy service behavior
- keep `reverse_engineering.schema.json` as a bundled schema template

## 3. Full Schema Builder Editing

The GUI can create and edit entity types, fields, and relation types. It still needs richer record-impact warnings.

Goal:

- clear warnings when schema edits make existing records incomplete

## 4. Larger Project UX

For projects with hundreds or thousands of records, validate:

- list page performance
- HTML response size
- pagination or incremental filtering
- graph caps and warnings
- compact rows and better empty/error states

## 5. Graph Polish

The current graph is server-generated SVG without external graph dependencies.

Possible improvements:

- clearer legend
- richer focus controls
- preserved filters
- denser labels
- links from side lists to detail pages

## 6. MCP Resources If Needed

MCP resources currently remain a list-only compatibility surface and return empty lists. Project data is available through tools and schema-aware prompts.

Add resources only if a real client need appears. Candidate resource URIs:

- `project://config`
- `project://recent`
- `entity://<entity_type>/<record_id_or_slug>`

## 7. Optional Importers

Future importers should stay optional and offline-friendly.

Candidates:

- IDA export JSON
- Ghidra export JSON
- Binary Ninja export JSON
- generic symbol list import

Rule: importers must not require external daemons, cloud services, or network access at runtime.

## 8. Packaging And Offline Install

Keep checking the offline install workflow:

```powershell
pip download .
pip install --no-index --find-links <wheelhouse> mcp-memory
```

Goal: preserve simple installation on a Windows machine without internet access.
