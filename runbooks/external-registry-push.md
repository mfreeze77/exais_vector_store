# External Registry Push Proof

This runbook packages RM-012 evidence only: versioned images were pushed to an
external registry and then pulled by immutable digest from a clean local tag
state. It does not prove VPS readiness or customer-cell readiness.

## Operator Inputs

- `REGISTRY_PREFIX`: external namespace such as `docker.io/expertaiservices` or
  `registry.example.com/exais`.
- `CELL`: proof folder name under `.release/cells/`, for example
  `external-registry` or the selected customer cell name.
- Docker credentials: complete `docker login` outside this repo before running
  the proof. Do not put credentials in command arguments, env files, or proof
  files.
- A clean local registry gate from `docs/DOCKER_LOCAL_CELL_RELEASE.md`.

## Dry Run

```bash
python scripts/release/external-registry-proof.py \
  --registry-prefix "$REGISTRY_PREFIX" \
  --cell "$CELL" \
  --dry-run
```

The dry run prints the build, push, local-tag removal, and pull-by-digest plan
without running Docker commands and without writing proof JSON.

## Proof Command

```bash
python scripts/release/external-registry-proof.py \
  --registry-prefix "$REGISTRY_PREFIX" \
  --cell "$CELL"
```

The wrapper uses the repo `VERSION` value and writes:

- `.release/cells/$CELL/release-manifest.json`
- `.release/cells/$CELL/external-registry-proof.json`

The proof JSON records the release manifest hash, pushed image digests, clean
pull-by-digest references, command output, and the explicit claim boundary that
this is external-registry proof only.

## What The Wrapper Runs

```bash
python scripts/release/build-images.py --registry-prefix "$REGISTRY_PREFIX"
python scripts/release/publish-images.py --registry-prefix "$REGISTRY_PREFIX" --cell "$CELL"
python scripts/release/remove-local-app-images.py --registry-prefix "$REGISTRY_PREFIX"
docker pull "$IMAGE_REPOSITORY@$SHA256_DIGEST"
docker image inspect "$IMAGE_REPOSITORY@$SHA256_DIGEST"
```

The final two Docker commands are generated for every app image in
`scripts/release/release_common.py:APP_IMAGES` from the verified release
manifest.

## Acceptance Checklist

- `release-manifest.json` verifies with fixed `VERSION`, non-local
  `REGISTRY_PREFIX`, full app image set, and `sha256` digests.
- `external-registry-proof.json` exists under `.release/cells/$CELL/`.
- Every app image has a `pull_by_digest` entry using `repository@sha256:...`.
- The proof command did not require or print secret values.
- No VPS, DNS, TLS, or customer-host readiness claim is made from this proof.
