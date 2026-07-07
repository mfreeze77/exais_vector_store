---
name: exais-ui-refactor-extraction
description: Use for behavior-preserving React admin UI extraction tickets in ExAIS Vector Store, especially panes, forms, tables, toolbars, route-local markup, and admin UI component splits.
---

# ExAIS UI Refactor Extraction Skill

Extract admin UI composition without changing behavior.

## Use This For

- Admin UI pane extraction.
- Toolbar or action-row extraction.
- Route-local layout extraction.
- Presentation-heavy React markup refactors.
- Behavior-preserving component splits.

## Rules

- Preserve current behavior first.
- Move presentation before moving state.
- Keep API calls and mutations near the current owner unless the ticket explicitly says otherwise.
- Use explicit typed props.
- Do not pass one large untyped state bag.
- Preserve copy, ordering, test ids, accessibility labels, disabled states, and keyboard behavior.
- Do not introduce broad context or global state for a one-ticket extraction.

## Project Anchors

- `apps/admin_ui/src/main.tsx`
- `apps/admin_ui/src/styles.css`
- `apps/admin_ui/package.json`

## Proof

Report original block, new component path, props introduced, behavior preserved,
and verification run.

## Reference Brief

See `tickets/codex-agents/UI_REFACTOR_EXTRACTION_AGENT.md` for the long-form instructions.
