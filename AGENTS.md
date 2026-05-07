# AGENTS.md

Instructions for Codex in this repository. These notes should be treated as persistent project guidance and merged with task-specific user instructions.

## Project Context

- This repository is for a local offline-first RE knowledge base on Python.
- Prioritize simple local deployment on Windows over architectural purity.
- Favor SQLite, stdlib, and a minimal offline-deployable dependency footprint.
- Backend, MCP, and the server-rendered GUI are now implemented; preserve the simple local architecture, but allow small offline-deployable dependencies when they clearly reduce maintenance cost.
- Avoid cloud dependencies, external databases, and heavy frontend stacks unless explicitly requested.

## Working Style

- Read the current repository state before proposing or making changes.
- State assumptions explicitly when they materially affect implementation.
- If there are multiple reasonable interpretations, surface them instead of choosing silently.
- Prefer the simplest implementation that satisfies the request and current plan.
- Keep diffs tightly scoped to the task.
- Match the existing style and structure of the repository unless the user asks for a broader redesign.
- Do not add speculative abstractions, premature configuration, or future-proofing layers that are not needed yet.

## Behavioral Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them; don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
- Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it; don't delete it.

When your changes create orphans:

- Remove imports, variables, and functions that your changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

- "Add validation" -> "Write tests for invalid inputs, then make them pass"
- "Fix the bug" -> "Write a test that reproduces it, then make it pass"
- "Refactor X" -> "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Repo-Specific Preferences

- Prefer a single-process or few-process local architecture that is easy to run manually on Windows.
- Keep project data isolated per project/workspace.
- Treat audit history and version history as user-facing features, but do not let them pollute default agent responses.
- Keep facts and hypotheses separate in both storage and API design.
- Store large artifacts as files with references in SQLite rather than embedding raw blobs in records unless explicitly needed.
- Design search so exact/FTS-based retrieval works without embeddings.
- Make optional features degradable: if a subsystem is not configured, core CRUD and search should still work cleanly.

## Refactoring Preparation

This project is entering a refactoring-friendly phase. Prefer changes that make module boundaries clearer without changing behavior.

### Refactoring Goals

- Reduce coupling between transport/UI layers and core business logic.
- Keep `services/` as the primary behavior boundary.
- Move duplicated request/form/tool payload conversion toward small shared helpers only when duplication is already causing real maintenance cost.
- Preserve current user-visible behavior unless the task explicitly asks for behavior changes.
- Prefer incremental extraction over broad rewrites.

### Refactoring Rules

Before refactoring a module:

- Identify the current behavior surface: CLI, HTTP API, MCP, GUI, storage, tests, docs.
- Write down what must remain unchanged.
- Add or adjust focused tests before moving behavior when the existing tests do not pin it down.
- Make one boundary clearer at a time.
- Avoid mixing behavior changes, renames, formatting churn, and extraction in the same diff.

### Desired Boundaries

- `domain/`: dataclasses, enums, simple data shapes. No SQLite, HTTP, MCP, or HTML concerns.
- `storage/`: database connection, migrations, schema bootstrap. No transport/UI behavior.
- `services/`: validation, business rules, audit/version history, search indexing, pending-change application, import/export, backup/restore.
- `api/`: HTTP routing, JSON parsing, status codes, serialization, service calls.
- `mcp/`: JSON-RPC/MCP protocol handling, tool schemas, MCP result formatting, service calls.
- `gui/`: server-rendered HTML, form parsing, redirects, localization, service calls.
- `cli/`: argument parsing, command output, process startup, service calls.

If a lower layer starts importing from a higher layer, pause and reconsider the design.

### Refactoring Safety

- Keep public behavior stable across:
  - CLI commands
  - HTTP routes and response shapes
  - MCP tools, prompts, and session behavior
  - GUI routes, forms, and redirects
  - SQLite migration/bootstrap behavior
- When changing entity write behavior, check all adapters: HTTP payload builders, MCP tool handlers, GUI form builders, pending-change confirmation, import/export, tests.
- Do not introduce dependency injection frameworks, plugin systems, service containers, or broad interface layers unless explicitly requested.
- Prefer plain Python functions/classes and small adapter helpers.

### Refactoring Anti-Patterns

Avoid these unless explicitly requested:

- Replacing stdlib HTTP servers with web frameworks.
- Introducing a frontend framework or build pipeline.
- Moving business rules into HTTP/MCP/GUI handlers.
- Adding abstract base classes for single implementations.
- Adding global service registries or dependency containers.
- Rewriting large files only to improve organization.
- Changing database schema and transport behavior in the same refactor.
- Renaming public commands, routes, tools, fields, or tables as part of cleanup.

### Test Expectations For Refactors

For narrow internal refactors:

- Run focused unit tests for the touched area.

For changes that cross adapter boundaries:

- Run full unittest discovery.
- Run `scripts/run_local_checks.ps1` when HTTP/MCP/GUI/runtime behavior may be affected.

Coverage should stay at or above the current project threshold.

## GUI Refactoring Direction

The current GUI is server-rendered and should remain server-rendered.

If HTML string composition becomes difficult to maintain:

- Prefer introducing a small template layer over adding a frontend framework.
- `Jinja2` is the preferred candidate for templates.
- Keep route handling in Python stdlib HTTP servers unless explicitly asked otherwise.
- Move page markup into templates incrementally, one page or shared component at a time.
- Keep existing routes, forms, query parameters, redirects, language switching, and write-mode behavior stable.
- Do not convert the GUI into an SPA.

## Dependency Rules

- Prefer stdlib first, but allow small, mature dependencies when they materially reduce code complexity, improve correctness, or make refactoring safer.

A dependency is acceptable only if:

- It can be installed offline from wheels downloaded ahead of time.
- It supports Windows and Python 3.10+.
- It can be fetched with a workflow like `python -m pip download --platform win_amd64 --python-version 310 --only-binary=:all: --dest vendor/wheels <package>`.
- It can later be installed with `python -m pip install --no-index --find-links vendor/wheels <package>`.
- It does not require external services, background daemons, cloud accounts, native system packages, or network access at runtime.
- It has a stable API and a modest transitive dependency tree.
- It is added for a concrete simplification, not speculative future flexibility.

Avoid dependencies that:

- Require compilation during install.
- Lack Windows wheels.
- Pull in large frontend stacks, databases, task queues, telemetry, or cloud SDKs.
- Add hidden runtime networking.
- Make local manual deployment harder.

When adding a dependency:

- Explain why stdlib is no longer the simplest maintainable choice.
- Check wheel availability for Windows/Python 3.10+.
- Pin or constrain the dependency in `pyproject.toml`.
- Update README/offline install docs if needed.
- Add or update tests around behavior that now depends on the package.

## Preferred Dependency Candidates

These are acceptable directions when they simplify existing code:

- Template rendering: prefer `Jinja2` if GUI HTML construction becomes hard to maintain.
- Data validation/parsing: consider stdlib dataclasses first; add a dependency only if validation duplication becomes a real maintenance problem.
- Testing helpers: keep `unittest` unless a dependency clearly improves maintainability without making offline setup heavier.
- Packaging/offline install helpers: keep simple pip wheel workflows; do not add package managers or environment managers as project requirements.

For server-rendered GUI refactoring, `Jinja2` is the preferred template dependency candidate. It is mature, commonly available as wheels, works offline, and can replace brittle string-built HTML while preserving the current no-frontend-build architecture.

## Change Discipline

- Before larger edits, identify the minimum file set needed.
- Preserve unrelated user changes.
- If you notice a conflict between the current repo state and the agreed plan, pause and call it out before proceeding.
- When possible, verify behavior with focused tests or checks rather than broad unscoped changes.

## Verification Fallback

- If a command, test run, or local verification step cannot be executed in the Codex environment, do not stop at "I couldn't run it".
- By the end of the task, create a script that runs the required verification commands on the user's machine and writes the results to a file in the repository.
- Prefer simple repository-local scripts such as `scripts/run_local_checks.ps1` and repository-local output files such as `artifacts/local_checks.txt`.
- The script should be narrowly scoped to the checks needed for the current task.
- After creating the script, tell the user exactly what to run and which output file to point you to.
- Once the user says they ran it, read the saved output file and use that result as the verification source of truth.
