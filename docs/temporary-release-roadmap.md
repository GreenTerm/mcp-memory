# Release Roadmap And Backlog

Version: 1.0.3.

Status: post-1.0 roadmap and backlog. This file remains separate from stable release notes so planning can be edited freely without changing historical release notes.

## Product Goal

Bring `mcp-memory` from a working schema-first local knowledge base to a release-quality offline product for humans and agents:

- predictable local installation on Windows
- stable Home UI DNS/path gateway
- polished server-rendered workbench UI
- schema-first records, relations, evidence, search, import/export, backup/restore
- clear MCP instructions for agents
- safe schema editing and data operations
- documentation that lets a new user create and operate a project without guessing

## Progress Through 1.0.0

Status markers:

- [x] `0.3.1` Dashboard and UI consistency patch
- [x] `0.4.0` Schema Builder beta
- [x] `0.5.0` Operations and offline install hardening
- [x] `0.6.0` Agent workflow hardening
- [x] `0.7.0` Search and graph usability baseline
- [x] `0.8.0` Legacy code retirement/isolation baseline
- [x] `0.9.0` Release candidate
- [x] `1.0.0` Stable local knowledge base

Completed notes:

- The workbench UI direction is now the default server-rendered GUI direction, with compact dashboard panels, grouped navigation, table-like schema editors, styled destructive actions, and RU/EN localization passes on touched pages.
- Entity create/edit/delete flows are GUI-first. Field editing and relation type editing are structured; raw JSON remains behind an advanced disclosure.
- DNS/path gateway, backup/restore, import/export, offline wheel workflow, and local operation docs are covered in README and release docs.
- MCP prompts and tool metadata are schema-aware and include usage examples plus required/optional payload guidance for the active schema.
- Search has regression coverage for technical text and graph pages expose focused relation browsing with caps handled in tests.
- Fixed reverse-engineering surfaces remain compatibility code for existing tests and users, but the documented product path is generic schema-first. `reverse_engineering.schema.json` and `import-legacy-db` remain supported.
- Release checks are repeatable through `scripts/run_release_check.ps1`; the local smoke check now verifies direct HTTP/MCP and Home gateway UI/API/MCP paths.

## Current State

The project is now at the `1.0.0` stable local baseline:

- the generic data model and adapters exist
- the DNS/path gateway exists
- MCP prompts and tool metadata are schema-aware
- GUI has the workbench direction as the normal product path, with future polish tracked as backlog
- tests, local smoke, gateway smoke, and coverage are repeatable through release scripts
- old reverse-engineering transitional code is isolated as compatibility surface rather than the documented main path
- offline installation and clean-machine release checks are documented; clean-machine execution remains an external release ritual

## Post-1.0 Backlog Themes

### UX And Visual Polish

- finish one consistent workbench visual system across all pages
- remove mixed old/new page structures
- fix all remaining RU/EN mixed strings
- make error, empty, loading, stopped-project, and unavailable-project states predictable
- keep forms compact and aligned with expected data size
- make destructive actions calm, clear, and confirmable

### Schema Builder Maturity

- make entity create/edit/delete flows equally polished
- support structured field editing without forcing raw JSON first
- support structured relation editing
- warn when schema edits can make existing records incomplete
- keep raw JSON editor as advanced fallback only

### Agent Experience

- keep `agent_workspace_guide` concise but complete
- make required and optional fields obvious for every active schema
- include examples for every MCP tool
- validate MCP error messages from the perspective of an agent recovering from mistakes
- document recommended agent workflows for search, evidence, relations, and pending changes

### Local Operations

- formalize backup/restore and import/export expectations
- make stopped project and port conflict states easy to understand
- keep old direct project ports compatible while promoting gateway URLs
- make logs discoverable from GUI/docs
- document how to move a project between machines

### Release Engineering

- run tests on a clean Windows environment
- verify offline wheel download/install workflow
- define release checklist and smoke scripts
- avoid generated artifacts in git status
- keep coverage at or above the configured threshold

## Version Plan

### 0.3.1: Dashboard And UI Consistency Patch

Status: done in `0.8.0` baseline.

Goal: stabilize the current workbench redesign and remove obvious visual regressions.

Scope:

- dashboard project overview/stat/quick-entry spacing
- record form sizing and hints
- entity list table alignment
- entity create/edit visual parity
- dropdown, checkbox, scrollbar, and transition polish
- eliminate newly found RU/EN mixed strings on touched pages

Exit criteria:

- key pages visually match the current workbench direction at desktop widths
- no overlapping dropdowns or broken z-index layers in entity constructor
- creating a record through GUI works
- deleting an entity shows a styled page, not browser-default HTML
- `python -m unittest discover -s tests -v` passes
- Playwright smoke script or equivalent manual checklist covers dashboard, entities, record create, search, graph, settings

### 0.4.0: Schema Builder Beta

Status: done in `0.8.0` baseline.

Goal: make schema editing feel intentional rather than transitional.

Scope:

- structured edit form for entity metadata
- structured edit form for fields
- structured edit form for relation types
- delete/confirm flows for fields and relation types
- raw JSON editor moved behind an advanced disclosure
- clearer validation messages for invalid schema edits
- warnings for schema changes that affect existing records

Exit criteria:

- user can create and edit a useful schema without opening raw JSON
- raw JSON still works as fallback
- entity create/edit pages share one layout and component set
- invalid schema edits do not corrupt existing `schema.json`
- tests cover create/edit/delete for entities, fields, relation types, and invalid forms

### 0.5.0: Operations And Offline Install Hardening

Status: done in `0.8.0` baseline.

Goal: make the local product reliable to install, move, backup, restore, and run offline.

Scope:

- clean Windows install instructions
- offline wheelhouse workflow
- backup/restore UX and docs
- import/export UX and docs
- stopped project and port conflict pages
- clear log locations and troubleshooting steps
- project move/copy checklist

Exit criteria:

- clean Windows machine can install from pre-downloaded wheels
- user can create project, stop/start it, backup, restore, export, and import using documented steps
- gateway URLs remain correct after restart
- failure states are clear in GUI and CLI
- local smoke checklist is documented and repeatable

### 0.6.0: Agent Workflow Hardening

Status: done in `0.8.0` baseline.

Goal: make MCP usage robust for real agent workflows.

Scope:

- refine `agent_workspace_guide`
- add task-oriented prompts for common generic workflows
- improve examples for relation and evidence tools
- document agent-side read/write workflow
- add tests for prompt content against multiple schemas
- consider MCP resources only if clients need them

Exit criteria:

- connected agent can infer required fields and safe write flow from prompts
- every write tool has clear examples and validation errors
- schema changes are reflected in agent instructions without manual docs edits
- MCP tests cover generic and non-RE schemas

### 0.7.0: Search And Graph Usability

Status: done as baseline in `0.8.0`; richer graph interactions stay post-0.8 backlog.

Goal: make retrieval and relation browsing good enough for larger projects.

Scope:

- search ranking/snippets
- punctuation/path/address query regression tests
- pagination or incremental filtering for large lists
- graph focus controls and warnings
- graph legend and denser labels
- related-record navigation polish

Exit criteria:

- search handles common technical text reliably
- list pages remain usable with hundreds or thousands of records
- graph view explains when data is capped or filtered
- exact retrieval and FTS behavior are documented

### 0.8.0: Legacy Code Retirement

Status: done as isolation baseline. Compatibility surfaces remain documented instead of fully removed.

Goal: reduce internal confusion before 1.0 by removing or isolating old fixed RE surfaces.

Scope:

- keep `reverse_engineering.schema.json`
- keep `import-legacy-db`
- remove or isolate fixed function/structure/hypothesis HTTP/GUI/MCP paths if no longer needed
- update tests to generic-first expectations
- document any remaining compatibility surface explicitly

Exit criteria:

- public docs describe generic schema-first behavior only
- legacy import remains tested
- lower layers do not depend on old adapter behavior
- codebase boundaries match `AGENTS.md` desired boundaries more closely

### 0.9.0: Release Candidate

Status: done in `1.0.0` baseline.

Goal: freeze behavior and focus on bugs, docs, and repeatability.

Scope:

- no major feature work
- full docs pass
- clean install pass
- local UX smoke pass
- API/MCP compatibility review
- database migration/bootstrap review
- release checklist dry run

Exit criteria:

- no known critical data-loss, install, startup, or GUI-blocking bugs
- all documented commands work on a clean machine
- all tests pass
- coverage stays at or above threshold
- release checklist can be executed from scratch

### 1.0.0: Stable Local Knowledge Base

Status: done.

Goal: mark the first stable release for local offline schema-first knowledge bases.

Scope:

- only fixes found during `0.9.0`
- final version bump
- final release notes
- final README/onboarding pass

Exit criteria:

- a new user can install, create a project, define schema, add records, search, add evidence, create relations, backup/restore, and connect an MCP agent using docs alone
- project data remains local and portable
- GUI and MCP behavior are stable enough to avoid breaking without a migration note
- no transitional UI pages remain in normal workflows

## Suggested Temporary Backlog

High priority:

- finish dashboard spacing and copy consistency
- complete entity edit page parity with entity create page
- style entity delete/error pages consistently
- audit all RU pages for mixed English text
- keep a Playwright smoke script for workbench navigation

Medium priority:

- improve schema overview readability
- improve search result snippets
- add graph legend and cap warnings
- add copy buttons for paths and endpoints
- document clean-machine setup and offline install

Low priority:

- optional generated per-entity MCP convenience tools
- optional importers for external RE tools
- optional richer graph interactions
- optional MCP resources if clients need them

## Release Checklist Draft

- Update version in package metadata and docs.
- Run `python -m unittest discover -s tests -v`.
- Run coverage with `.coveragerc`.
- Run local GUI smoke through Home gateway.
- Verify direct project HTTP and MCP ports still work.
- Verify DNS/path gateway URLs in Home UI.
- Verify offline wheel download/install workflow.
- Create a fresh project from each bundled schema template.
- Export, import, backup, and restore one sample project.
- Connect an MCP client and call read/write tools.
- Review `git status` for generated artifacts before commit.
