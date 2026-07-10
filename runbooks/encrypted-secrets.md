# Encrypted Secrets Workflow

RM-005 implements production secret resolution for the host-side cell release
flow. Production `.env.cell` files keep references only; `cell-up.py` validates
and resolves those references before image-pin activation or any Docker call.
The repository proves the resolver and launch ordering without claiming access
to a customer's SOPS keys, age identity, Vault account, or production host.

## Reference Contract

Production secret-bearing variables must use one of these forms:

```text
sops://<path>#<KEY>
age://<path>#<KEY>
vault://<path>#<KEY>
envref://<ENV_VAR>
```

Examples:

```text
POSTGRES_PASSWORD=sops://configs/cell-secrets.customer-001.sops.yaml#POSTGRES_PASSWORD
DATABASE_URL=vault://kv/exais/customer-001#DATABASE_URL
OPENAI_API_KEY=envref://OPENAI_API_KEY
SVS_API_KEY_PEPPER=age://configs/cell-secrets.customer-001.sops.yaml#SVS_API_KEY_PEPPER
```

`sops://` and `age://` both address a SOPS document. The `age://` form records
that the SOPS document is encrypted to age recipients; it is not a raw age
ciphertext format. Relative paths are resolved from the repository root.

`vault://` reads one field from a Vault KV path. `envref://` reads the named
variable from the release process environment, allowing an external injector
to supply a secret without putting it in the cell env file.

## Host Prerequisites

- Docker and Docker Compose are installed for the release operator.
- `sops` is installed for `sops://` and `age://` references. Set
  `SVS_SOPS_BIN` to an absolute executable path when it is not on `PATH`.
- `vault` is installed and authenticated for `vault://` references. Set
  `SVS_VAULT_BIN` to an absolute executable path when needed.
- The release account can decrypt only the selected cell's SOPS file or read
  only the selected Vault path.
- The production cell env and encrypted source are readable only by the release
  account. Never commit decrypted material.

The resolver invokes the equivalent of these argument-safe commands without
printing their output:

```text
sops --decrypt --extract ["KEY"] <path>
vault kv get -field=KEY <path>
```

## Validate And Launch

Generate a cell env from reference values:

```bash
python scripts/release/generate-cell-env.py \
  --cell customer-001 \
  --production \
  --registry-prefix docker.io/expertaiservices \
  --reference-source-env .env.production.example
```

Run the name-only preflight independently when collecting approval evidence:

```bash
python scripts/release/prod-env-preflight.py \
  --env-file .release/cells/customer-001/.env.cell
```

Then launch through the supported entrypoint:

```bash
python scripts/release/cell-up.py \
  --cell customer-001 \
  --release-manifest /opt/exais/proof/operator-approved-release-manifest.json
```

`cell-up.py` repeats production preflight, resolves every supported reference,
and writes a process-scoped dotenv file under the operating-system temporary
directory. On POSIX hosts the directory is mode `0700` and the file is mode `0600`.
The generated file points `SVS_CELL_ENV_FILE` to itself so Compose uses
resolved values for interpolation and service `env_file` injection. It is
removed in `finally` and at normal process exit. A resolution failure occurs
before candidate image pins are activated and before Docker runs.

`cell-smoke.py` resolves the same references into its own temporary env before
the smoke gate stops and recreates workers, then removes that file after worker
restoration. Read-only or destructive shutdown commands such as `cell-down.py`
do not require secret-manager access because they do not create containers.

An ungraceful host or process termination can leave an `exais-secrets-*`
temporary directory. Remove it as the same release account before retrying.
On Windows production hosts, the operator must also verify that the account's
temporary-directory ACL does not grant other users access.

Docker stores container environment values in container configuration. Treat
Docker daemon and host administrator access as privileged secret access; this
workflow prevents plaintext source files and command output, not access by a
root-equivalent Docker operator.

## Failure Rules

Production preflight rejects:

- plaintext passwords, API keys, access keys, tokens, peppers, and DSNs;
- URLs or DSNs containing embedded passwords;
- malformed `sops://`, `age://`, `vault://`, or `envref://` references;
- placeholder strings such as `replace-with` or `change-me`.

Resolution also rejects missing tools or environment variables, failed secret
manager reads, empty or multiline values, chained references, and conflicting
process-level secret overrides. Errors contain issue codes, schemes, and
variable names only. Resolver stdout and stderr are never included.

## SOPS With Age

Create a customer-specific SOPS file from an operator-only plaintext staging
file, then securely remove that staging file:

```bash
sops --encrypt --age <age-recipient> \
  secrets.customer-001.yaml \
  > configs/cell-secrets.customer-001.sops.yaml
```

Keep the age identity outside the repository. Confirm the release account can
extract required fields before the maintenance window, but do not attach the
decrypted output to proof records.

## Vault

Authenticate the release account using the host's approved Vault auth method.
Grant field reads only for the selected path, for example
`kv/exais/customer-001`. The cell env records the path and field name; Vault
authentication material remains outside the repo.

## Rotation

1. Write the new value to the referenced SOPS document, Vault version, or
   external injector.
2. Change the cell env reference only when its path or field name changed.
3. Run `prod-env-preflight.py` and retain its name-only output.
4. Run `cell-up.py` with the approved immutable release manifest.
5. Run cell smoke and access proof, recording no decrypted values.
6. Revoke the old provider key or database credential after the new cell state
   passes proof.

## Rollback

1. Restore the previous encrypted file revision, Vault secret version, or
   injector value.
2. Restore the previous cell env reference when its locator changed.
3. Run production preflight again.
4. Run `cell-up.py` and the cell smoke/access proofs.
5. Record reference names and secret-manager versions only; never paste a
   decrypted value into rollback notes.

## Proof Boundary

Repository tests prove supported resolver command construction, name-only
errors, plaintext rejection, launch ordering, temporary-file cleanup, and
Compose-safe encoding for special characters. Closing a customer-host proof
still requires an operator-authenticated SOPS/age or Vault read on that host
plus a successful cell launch using the selected references.
