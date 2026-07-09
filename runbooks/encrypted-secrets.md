# Encrypted Secrets Workflow

RM-005 is repo-buildable validation only. It proves production cell env files
carry secret references and fail on plaintext secrets. It does not prove live
Vault, SOPS, age, DNS, TLS, or customer-host access.

## Accepted Reference Grammar

Production secret-bearing variables must use one of these forms:

```text
sops://<path>#<KEY>
age://<path>#<KEY>
vault://<path>#<KEY>
envref://<ENV_VAR>
```

Examples:

```text
POSTGRES_PASSWORD=sops://configs/cell-secrets.example.sops.yaml#POSTGRES_PASSWORD
DATABASE_URL=vault://kv/exais/customer-001#DATABASE_URL
OPENAI_API_KEY=envref://OPENAI_API_KEY
SVS_API_KEY_PEPPER=age://configs/cell-secrets.example.sops.yaml#SVS_API_KEY_PEPPER
```

`envref://` means the operator injects the secret from an external runtime
source. The env file records the injection contract, not the secret.

## Buildable Validation

Validate a production-reference env file without printing values:

```bash
python scripts/release/prod-env-preflight.py --env-file .env.production.example
```

The report prints variable names and issue codes only. It rejects:

- plaintext secret-bearing variables such as passwords, API keys, access keys,
  tokens, peppers, and production DSNs;
- URLs or DSNs containing embedded passwords;
- malformed `sops://`, `age://`, `vault://`, or `envref://` references;
- placeholder strings such as `replace-with` or `change-me`.

Generate a production-reference cell env from an operator reference file:

```bash
python scripts/release/generate-cell-env.py \
  --cell customer-001 \
  --production \
  --registry-prefix docker.io/expertaiservices \
  --reference-source-env .env.production.example
```

The generator imports only secret references. If a source file contains raw
secret material for a secret-bearing key, it fails and prints only the affected
variable names.

## SOPS/Age Setup

Create a real encrypted file outside this example:

```bash
sops --encrypt --age <age-recipient> configs/cell-secrets.customer-001.yaml > configs/cell-secrets.customer-001.sops.yaml
```

Keep only encrypted files or references in Git. Keep age identities, decrypted
material, and one-time provider tokens outside the repo.

## Vault Setup

Use Vault-style references when the deployment host resolves secrets at runtime:

```text
DATABASE_URL=vault://kv/exais/customer-001#DATABASE_URL
OPENAI_API_KEY=vault://kv/exais/customer-001#OPENAI_API_KEY
```

The preflight validates the reference shape only. Live Vault authentication,
policy, and read proof belong to the external secret-manager proof gate.

## Rotation

1. Write the new value in SOPS/age, Vault, or the external injector.
2. Update the referenced key or path in the production env only if the locator
   changed.
3. Run `prod-env-preflight.py` and keep the name-only output as proof.
4. Redeploy or restart the affected services through the cell release flow.
5. Revoke the old provider key or database credential after smoke proof passes.

## Rollback

1. Restore the previous encrypted file revision or Vault secret version.
2. Restore the previous production env references if the locator changed.
3. Run `prod-env-preflight.py` again.
4. Restart the affected services and record smoke proof.
5. Do not print, paste, or attach decrypted values to rollback notes.
