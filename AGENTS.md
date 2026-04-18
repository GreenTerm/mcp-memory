# AGENTS.md

Instructions for Codex in this repository. These notes should be treated as persistent project guidance and merged with task-specific user instructions.

## Project Context

- This repository is for a local offline-first RE knowledge base on Python.
- Prioritize simple local deployment on Windows over architectural purity.
- Favor SQLite, stdlib, and a minimal dependency footprint.
- Build backend and MCP before GUI.
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

## Dependency Rules

- Prefer stdlib first.
- Add third-party packages only when they materially reduce complexity or improve correctness.
- Any added dependency should be easy to pre-download and install offline with `pip download`.
- Avoid dependencies that imply cloud coupling, background services, or external daemons.

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
