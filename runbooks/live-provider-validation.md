# Live Provider Validation Runbook

RM-014 is an operator-dependent proof lane. The repo can package the proof command and redact output, but it must not claim OpenAI, RunPod, TEI, Infinity, or private endpoint readiness until real credentials/endpoints are supplied.

## Inputs

Supported provider inputs:

- OpenAI: `OPENAI_API_KEY`
- RunPod: `RUNPOD_EMBEDDING_ENDPOINT_URL`, `RUNPOD_API_KEY`
- TEI: `TEI_ENDPOINT_URL`
- Infinity: `INFINITY_ENDPOINT_URL`
- Self-hosted/OpenAI-compatible private: `SELF_HOSTED_MODEL_ENDPOINT_URL`, optional `SELF_HOSTED_MODEL_API_KEY`

Secret values must be supplied through the operator shell, secret manager, or the running gateway environment. The proof output prints env names and references only, never secret values.

## Dry Run

This command is safe without credentials. It should report skipped providers and `live_proof_claimed: false`.

```powershell
python scripts/release/live-provider-validation.py `
  --providers openai,runpod,tei,infinity,self_hosted
```

## Gateway Proof

Run this only after the model gateway is running with the same provider credentials/endpoints.

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
python scripts/release/live-provider-validation.py `
  --gateway-url $env:MODEL_GATEWAY_URL `
  --providers openai,runpod,tei,infinity,self_hosted `
  --approved-providers openai,runpod,tei,infinity,self_hosted `
  --rerank-providers runpod,infinity,self_hosted `
  --security-level 2 `
  --require-live `
  --output-file ".release/live-provider-validation/rm-014-$stamp.json"
```

For confidential routes, raise `--security-level`. External providers such as OpenAI are blocked above the registry policy threshold instead of being called.

## Evidence Rules

Accept the proof only when:

- `live_proof_claimed` is `true`.
- `gateway_live_proof_claimed` is `true` for gateway-route proof.
- Requested providers are not listed under `unavailable_or_unconfigured_providers`.
- Requested providers are not listed under `partial_providers`; a successful
  embedding plus failed requested rerank is partial proof, not a passed proof.
- Requested providers are not listed under `unapproved_providers` or `policy_denied_providers`, unless the purpose of the run is to prove denial behavior.
- Provider operations include latency and provider/model metadata.
- Cost metadata is present, or explicitly reports `cost_unavailable`.

Skipped providers mean the required operator inputs were absent or unresolved. They are not live proof.

## Remaining Operator Inputs

- Real provider API keys or endpoint credentials.
- Reachable RunPod, TEI, Infinity, or private endpoint URLs.
- An approved provider allowlist for the target customer/cell.
- Target security level for the content being validated.
- A running model gateway URL when gateway-route proof is required.
