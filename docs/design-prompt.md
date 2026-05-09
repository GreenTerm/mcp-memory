# GUI Design Prompt

Design a calm, practical web UI for a local offline-first schema-driven knowledge base. The UI is used daily by people and agents as a working tool, not as a marketing site.

## Product Context

The app stores and displays schema-defined knowledge records. Depending on the project schema, this can include reverse-engineering data, infrastructure deployment notes, research notes, or any custom entity types.

- entity types
- records
- evidence
- typed relations between records
- change history
- audit trail
- pending changes

The product is local-first and Windows-friendly. It uses Python stdlib HTTP, server-rendered HTML, packaged CSS and small progressive-enhancement JavaScript. Do not assume a SPA or heavy frontend stack.

## Visual Direction

The target feeling is:

- 70% Obsidian
- 30% Notion
- dark-first
- calm
- dense enough for real work
- readable for long reverse engineering sessions
- modern, but not decorative

Avoid:

- generic admin dashboard visuals
- marketing hero sections
- spreadsheet-like tables as the primary UI
- bright cyberpunk styling
- heavy gradients
- decorative blobs
- large unused empty space

## Layout

Workspace layout:

- left sidebar for workspace navigation
- topbar for global controls
- compact page header for breadcrumbs, page title and back-to-project-shelf link
- main content as consistent cards/sections
- optional right detail panel where useful

The topbar owns:

- global workspace search
- theme toggle
- write-mode status
- language switcher

The sidebar owns generic workspace navigation:

- Entities
- Records
- Search
- Graph
- Evidence
- Import/Export
- Backups
- Schema
- Settings

Do not put `Projects` in the workspace sidebar. The return to project shelf lives in the workspace header.

## Components

Use consistent styling for:

- project cards
- section cards
- metric cards
- quick entry cards
- entity rows/cards
- empty states
- forms
- buttons
- badges
- MCP config blocks
- pending/audit cards

Empty states need real internal padding and should sit inside the same card/section system as normal content.

## Motion

Animations should be simple and unobtrusive:

- sidebar open/close
- page content entrance
- menu open/close
- hover/focus transitions

Respect reduced-motion preferences.

## Language And Encoding

The UI supports English and Russian. Russian text must be real UTF-8, not mojibake. Long Russian labels must wrap cleanly without breaking cards.

## MCP And Agent Context

The UI should make MCP endpoint information easy to copy, but the full agent workflow is exposed through MCP tools and prompts. The UI should not duplicate protocol documentation inline.

## Implementation Constraints

- no new runtime dependencies unless explicitly approved
- no cloud services
- no external fonts
- no frontend build step
- no hidden route changes
- preserve existing forms and POST behavior
- preserve `lang` across navigation
