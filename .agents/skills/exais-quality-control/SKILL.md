---
name: exais-quality-control
description: Use after every ExAIS Vector Store ticket implementation to independently review changed files, acceptance criteria, scope, verification proof, and whether the orchestrator can continue.
---

# ExAIS Quality Control Skill

Independently review ticket work before anything is marked complete.

## Required Inputs

- Tracker or wave path if available.
- Ticket path.
- Changed files.
- Verification commands and results.
- Proof notes.

Return BLOCKED if any required input is missing.

## Review Checklist

- Scope matches the assigned ticket.
- Acceptance criteria are met.
- No follow-up ticket was started.
- Code anchors were respected.
- Verification is real and adequate.
- No unrelated tenant isolation, API key, database, indexing, provider, deployment, or admin UI behavior changes.
- Production-safety claims are backed by actual proof.
- No fake command results.

## Decisions

Return exactly one:

- PASS
- PASS WITH NOTES
- FAIL
- BLOCKED

## Output Format

```text
Decision: PASS | PASS WITH NOTES | FAIL | BLOCKED

Ticket reviewed:
- {ticket path}

Evidence reviewed:
- {changed files}
- {commands}

Acceptance criteria:
- [pass/fail] criterion summary

Findings:
- {issues or none}

Required fixes before next ticket:
- {fixes or none}
```

## Reference Brief

See `tickets/codex-agents/QUALITY_CONTROL_AGENT.md` for the long-form instructions.
