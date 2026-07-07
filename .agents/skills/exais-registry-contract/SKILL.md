---
name: exais-registry-contract
description: Use for typed registries, descriptor arrays, route tables, provider/model metadata, mode-router descriptors, and small shared contracts in ExAIS Vector Store tickets.
---

# ExAIS Registry and Contract Skill

Move hardcoded options into typed descriptors or small registries while preserving behavior.

## Use This For

- Provider and model capability metadata.
- Mode-router descriptors.
- API route or operation metadata.
- Admin UI action descriptors.
- Small shared composition contracts.

## Rules

- Preserve current ordering and labels.
- Keep descriptor types narrow.
- Do not introduce a framework when a small typed collection is enough.
- Keep callbacks and persistence near stateful owners unless the ticket says otherwise.
- Add pure tests for filtering, ordering, defaults, and compatibility when practical.
- Never include secrets or provider credentials in descriptors.

## Project Anchors

- `packages/svs_common`
- `apps/api/svs_api`
- `apps/worker/svs_worker`
- `apps/model_gateway/svs_model_gateway`
- `apps/admin_ui/src`
- `configs`

## Proof

Report registry files changed, hardcoded block reduced, tests added, and behavior preserved.

## Reference Brief

See `tickets/codex-agents/REGISTRY_CONTRACT_AGENT.md` for the long-form instructions.
