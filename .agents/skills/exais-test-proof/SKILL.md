---
name: exais-test-proof
description: Use for ExAIS Vector Store tickets focused on characterization tests, regression proof, verification commands, final proof notes, or test-only baseline work.
---

# ExAIS Test and Proof Skill

Pin behavior and produce proof for ticket completion.

## Rules

- Prefer behavior tests over snapshots.
- Pin current behavior before refactor.
- Keep tests focused and cheap.
- Use existing repo test patterns.
- Do not change production behavior just to satisfy a test.

## Proof Checklist

- Acceptance criteria status.
- Changed files.
- Commands run.
- Command results.
- Known limitations.
- Follow-up tickets.

## Candidate Commands

Use ticket-specific commands first. If absent, consider:

```bash
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
  python -m compileall -f -q packages apps tests
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
  pytest -q -rs
npm --prefix apps/admin_ui run build
docker compose config
```

If a script does not exist, report that honestly and provide the closest known command.

## Reference Brief

See `tickets/codex-agents/TEST_PROOF_AGENT.md` for the long-form instructions.
