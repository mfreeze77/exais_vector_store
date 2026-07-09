# Customer Cell Launch Proof

This runbook packages RM-013 evidence for one selected VPS or customer host. It
must be run on that host, against pinned images from a completed external
registry proof. Do not use local Docker proof or registry proof alone as a
customer-cell readiness claim.

## Operator Inputs

- `CELL`: selected customer cell name, for example `customer-001`.
- `REGISTRY_PREFIX`: the same external registry namespace proven by RM-012.
- Target host: hostname, IP, DNS names, TLS termination path, firewall rules,
  and Docker/Compose installation.
- Production secret references only. Use `sops://`, `age://`, `vault://`, or
  `envref://` references as described in `runbooks/encrypted-secrets.md`; do not
  commit plaintext secret values.
- `.release/cells/$CELL/release-manifest.json` from the matching external
  registry proof. `cell-up.py` validates this manifest before pulling images.

## Prepare The Host

```bash
export CELL=customer-001
export REGISTRY_PREFIX=docker.io/expertaiservices
export APP_DIR=/opt/exais/vector-store
export CELL_ENV_FILE="$APP_DIR/.env.cell"
export PROOF_DIR="$APP_DIR/.release/cells/$CELL/customer-cell-launch"

git clone <repo-url> "$APP_DIR"
cd "$APP_DIR"
git checkout <approved-release-commit>
mkdir -p "$PROOF_DIR"
```

Generate the production env scaffold. The generator uses the repo `VERSION`
value; the checked-out commit must match the release manifest.

```bash
python scripts/release/generate-cell-env.py \
  --cell "$CELL" \
  --production \
  --registry-prefix "$REGISTRY_PREFIX" \
  --reference-source-env .env.production.example

cp ".release/cells/$CELL/.env.cell" "$CELL_ENV_FILE"
```

Operator-owned step: edit `$CELL_ENV_FILE` so public URLs, ports, provider
settings, and customer-specific references match the selected host. Keep secret
values as references, not plaintext.

## Capture Host And Topology Evidence

Run these on the selected host and keep the raw output.

```bash
{
  date -u
  hostname -f || hostname
  uname -a
  git rev-parse HEAD
  cat VERSION
  docker version
  docker compose version || docker-compose version
  ip addr
  ip route
  ss -ltnp || netstat -ltnp
} | tee "$PROOF_DIR/host-topology.txt"
```

## Launch Proof

```bash
python scripts/release/prod-env-preflight.py \
  --env-file "$CELL_ENV_FILE" \
  | tee "$PROOF_DIR/prod-env-preflight.txt"

python scripts/release/cell-up.py \
  --cell "$CELL" \
  --worker-scale 4 \
  | tee "$PROOF_DIR/cell-up.txt"

python scripts/release/cell-smoke.py \
  --cell "$CELL" \
  --worker-scale 4 \
  | tee "$PROOF_DIR/cell-smoke.txt"

python scripts/release/cell-access-proof.py \
  --cell "$CELL" \
  | tee "$PROOF_DIR/cell-access-proof.txt"
```

Capture final compose and image state after the smoke/access proofs pass.

```bash
docker ps --filter "name=exais-vector-store" --no-trunc \
  | tee "$PROOF_DIR/docker-ps.txt"

docker network ls \
  | tee "$PROOF_DIR/docker-network-ls.txt"

docker image ls "$REGISTRY_PREFIX/*" --digests --no-trunc \
  | tee "$PROOF_DIR/docker-image-digests.txt"
```

## Summary Record

Create the summary only after the raw files above exist on the selected host.

```bash
cat > "$PROOF_DIR/customer-cell-launch-summary.json" <<EOF
{
  "schema_version": 1,
  "proof_type": "customer_cell_launch",
  "cell": "$CELL",
  "registry_prefix": "$REGISTRY_PREFIX",
  "product_version": "$(cat VERSION)",
  "release_commit": "$(git rev-parse HEAD)",
  "claim_boundary": "Customer-cell launch proof for this selected host only; it does not prove other VPS or customer hosts.",
  "raw_evidence": [
    "host-topology.txt",
    "prod-env-preflight.txt",
    "cell-up.txt",
    "cell-smoke.txt",
    "cell-access-proof.txt",
    "docker-ps.txt",
    "docker-network-ls.txt",
    "docker-image-digests.txt"
  ]
}
EOF
```

## Acceptance Checklist

- Production preflight passes without printing secret values.
- `cell-up.py` validates the pinned release manifest, pulls registry images, and
  waits for API, worker, model-gateway, admin UI, and stateful services.
- `cell-smoke.py` and `cell-access-proof.py` pass on the selected host.
- Raw host/topology outputs are stored under
  `.release/cells/$CELL/customer-cell-launch/`.
- The summary identifies exactly one host/cell proof and does not extrapolate to
  any other VPS, customer, DNS, TLS, or registry state.
