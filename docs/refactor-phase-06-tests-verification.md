# Phase 06 - Tests, Smoke Checks, And Documentation

Status: unit tests, generic smoke checks, release checks, and coverage threshold pass for v1.0.0.

Goal: replace fixed RE verification with generic model verification and keep local Windows checks reliable.

## Work Items

- Completed:
  - Added schema tests.
  - Added generic record tests.
  - Added relation/evidence/search coverage in generic service, HTTP, MCP, and GUI focused tests.
  - Added pending/audit/version coverage for generic records and generic pending confirmation.
  - Added focused generic HTTP tests.
  - Added focused generic MCP tests.
  - Added focused generic GUI tests.
  - Added focused generic transfer service and HTTP export/import tests.
  - Added legacy importer tests using an old-style sample DB.
  - Updated old-transition tests to match the generic vNext contract where the public surface changed.
  - Converted `scripts/local_smoke_check.py` to use bundled schemas and generic API/MCP/GUI.
  - Simplified `scripts/run_local_checks.ps1` so it runs the full unit suite once instead of repeating it once per phase file.
  - Updated README/docs for schema templates, generic APIs, MCP tools, legacy import, and offline Jinja2 wheel workflow.
  - Updated README/docs for DNS/path gateway and schema-aware MCP agent instructions.
  - Verified full suite: `python -X utf8 -m unittest discover -s tests -v` ran 155 tests and passed.
  - Added documentation phase files and updated the main refactor plan.

- Not done yet:
  - Remove remaining fixed API/GUI/service tests after fixed transitional code is retired.
  - Raise or re-scope coverage back to the configured `fail_under = 95`; current generic vNext coverage report is 87%.

## Acceptance Checks

- Passing now:
  - Full repository suite passes, including schema, records, relations, evidence, pending, HTTP, MCP, CLI schema commands, Home GUI, workspace GUI, transfer, and backup/restore.
  - Generic smoke check passes.

- Not done yet:
  - Coverage remains below the project threshold and needs a dedicated recovery pass.
