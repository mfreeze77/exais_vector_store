# DNS, TLS, And Secrets Wiring Runbook

RM-017 is an operator proof gate for a chosen production domain and cell. The
repo can validate env references and local/customer cell access, but it cannot
claim DNS or TLS without live domain evidence.

## Proof Boundary

The repo cannot claim DNS or TLS without live domain evidence for the selected
cell.

Do not close RM-017 unless the packet names the chosen domain/cell and includes
live DNS, HTTPS/TLS, and secret-manager proof. Local Docker access, the HTTP-only
`infra/caddy/Caddyfile`, and scaffolded Terraform/Ansible files are supporting
materials only.

Current repo scaffolds:

- `infra/caddy/Caddyfile` is an HTTP reverse proxy on `:80`; it does not prove
  production TLS.
- `infra/terraform/hetzner-cloud/main.tf` can provision a host and output
  `server_ipv4`; it does not wire DNS records or certificates.
- `infra/ansible/playbook.yml` applies `base-hardening`, `docker-host`,
  `svs-cell`, and `backup-agent`; current host-hardening and cell roles are
  scaffolds.
- `scripts/release/prod-env-preflight.py` validates production env references
  and rejects wildcard/dev/plaintext hazards without printing values.
- `scripts/release/cell-access-proof.py` proves API/admin access for a compose
  cell through host loopback or Docker cell-network fallback.

## Required Operator Inputs

| Input | Required evidence |
|---|---|
| Domain | FQDNs for API and admin, DNS zone/provider, expected A/AAAA/CNAME target, and TTL |
| Cell | Cell id, host identifier, public IPv4/IPv6, compose project, and registry image version |
| TLS | Certificate issuer, SAN list, validity window, chain path, renewal mechanism, and OCSP/stapling status if available |
| Secrets | SOPS/age/Vault/envref references for all secret-bearing variables; no plaintext values |
| Rollback | Previous DNS target, previous env reference set, cert rollback path, and restart/deploy command |

## Environment And Secret Reference Preflight

Production env files must contain references such as `sops://...#KEY`,
`age://...#KEY`, `vault://...#KEY`, or `envref://KEY` for secret-bearing
values. Validate the generated cell env:

```bash
python scripts/release/prod-env-preflight.py --env-file <cell-env>
```

The preflight must pass without:

- `WILDCARD_CORS`
- `TLS_VERIFY_DISABLED`
- `LOCAL_REGISTRY_PREFIX`
- `DEV_MODE_ENABLED`
- `PLAINTEXT_SECRET`
- `EMBEDDED_SECRET`
- `PLACEHOLDER`

Record `SVS_PUBLIC_API_BASE`, `SVS_ALLOWED_CORS_ORIGINS`,
`OPENSEARCH_VERIFY_CERTS`, provider reference keys, and object-store strictness
by variable name only. Do not attach decrypted secret values, bearer tokens, API
keys, database passwords, or DSNs containing passwords.

## DNS Proof

Capture live resolution for each FQDN:

```bash
nslookup <api-fqdn>
nslookup <admin-fqdn>
```

or:

```bash
dig +short <api-fqdn> A
dig +short <api-fqdn> AAAA
dig +short <admin-fqdn> A
dig +short <admin-fqdn> AAAA
```

The output must match the selected host or load balancer target. If Terraform is
used, attach `terraform output server_ipv4` and show the DNS record points at
that value or at the approved load balancer in front of it.

## TLS Proof

Capture HTTPS health checks and certificate details:

```bash
curl -fsS -I https://<api-fqdn>/readyz
curl -fsS -I https://<admin-fqdn>/
openssl s_client -connect <api-fqdn>:443 -servername <api-fqdn> -showcerts </dev/null
openssl s_client -connect <admin-fqdn>:443 -servername <admin-fqdn> -showcerts </dev/null
```

The proof must show:

- HTTP 200 or approved health status for API/admin over HTTPS.
- Certificate SAN covers the exact FQDNs.
- The certificate is valid for the current date.
- No wildcard dev allowance is required for CORS.
- TLS verification is not disabled for OpenSearch or other HTTPS backends.

The repo HTTP-only Caddy scaffold is not TLS proof. If Caddy is used in
production, attach the production Caddyfile or generated config that names the
domains and certificate/issuer behavior.

## Access And Smoke

Run access proof for the chosen cell when compose metadata is available:

```bash
python scripts/release/cell-access-proof.py --cell <cell-id>
```

Then run the normal release smoke path against the launched cell or equivalent
external API/admin checks:

```bash
python scripts/release/cell-smoke.py --cell <cell-id>
```

If the cell is behind a load balancer and not reachable through compose-local
metadata, replace those commands with redacted `curl` output for API readiness,
admin UI, model gateway readiness, and a retrieval smoke request.

## Rotation And Rollback

Use `runbooks/encrypted-secrets.md` for secret rotation and rollback. A complete
RM-017 packet must include:

- the command that changed the DNS record or load balancer target;
- the command that renewed or installed the certificate;
- the command that updated SOPS/age/Vault/envref references;
- `prod-env-preflight.py` output after rotation or rollback;
- service restart/deploy command;
- post-change HTTPS and access proof.

Until live DNS resolution, HTTPS/TLS health checks, and external
secret-manager/reference evidence are attached for the chosen domain/cell,
record RM-017 as packaged but operator-dependent.
