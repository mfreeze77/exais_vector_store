---
name: exais-ticket-implementation
description: Use for implementing exactly one ExAIS Vector Store ticket when no more specific specialist skill applies. Reads ticket anchors, changes only assigned scope, runs verification, and records proof.
---

# ExAIS Ticket Implementation Skill

Implement exactly one assigned ticket and stop.

## Required Inputs

- Tracker or wave path if available.
- Ticket path.
- Any explicit code anchors from the orchestrator.

## Rules

- Implement only the assigned ticket.
- Do not start blockers or follow-up tickets.
- Read the ticket and every named code anchor before editing.
- Preserve behavior unless the ticket explicitly changes it.
- Keep changes typed, small, and reviewable.
- Do not touch tenant isolation, API key behavior, database migrations, indexing semantics, provider routing, deployment, or admin UI behavior unless the ticket explicitly targets them.

## Finish Requirements

Report:

- changed files,
- verification commands,
- results,
- acceptance criteria checklist,
- blockers or follow-ups.

If verification cannot run, state why and provide exact commands for the operator.

## Reference Brief

See `tickets/codex-agents/TICKET_IMPLEMENTATION_AGENT.md` for the long-form instructions.
