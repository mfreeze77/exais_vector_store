# HB 2513 bulk candidate retrieval

The source handoff contains 2,391 candidate appropriation actions and 197
supporting provisions from enrolled HB 2513 as retained. Fifty entries using
other spending language and eight claimant/leading passages remain cited review
items in A. The data is not human-reviewed, reconciled final authority, or a
resolved fiscal-account crosswalk. The source begins mid-section.

The exact compressed manifest is
`tests/fixtures/statecivics-hb2513-bulk-durable.c49d7105.jsonl.gz`, byte-identical to
A's committed artifact. Its uncompressed SHA-256 is
`5155056a4b2d411896787ff6e681d90a8cd58655cf3ddf6805849ca9dccc791b`.

## Query

The candidate API is available locally at `http://127.0.0.1:28086`.

```sh
curl --fail-with-body http://127.0.0.1:28086/api/v1/statecivics/entities/candidate/search \
  -H 'Content-Type: application/json' \
  -H 'X-SVS-Tenant-Id: ten_ks_state_civics' \
  -H 'X-SVS-Business-Instance-Id: biz_ks_state_civics' \
  -H 'X-SVS-Roles: owner,admin' \
  -d '{"query":"PKU treatment appropriation fiscal year 2027","limit":5}'
```

Responses include the full source-bound record and its eligibility status. The
existing local cell uses header principals; this is not a bearer-token security
demonstration or a public-UI deployment.

## Repeat the complete handoff

Use the refreshed B plain operator clone. The command checks the entire
manifest before the first request, preserves its bytes across bounded batches,
and records partial completion honestly if a later request fails. The API's
record-digest check makes a repeat idempotent. The candidate API image already supports
this operation; the updated batching command runs from the operator clone.

```sh
docker run --rm --network exais-vector-store-ks-fiscal-local_default --memory 2g \
  -v /Users/mfrieson/Developer/exais-vector-store-operator-repo:/app:ro \
  -v /Users/mfrieson/Developer/exais-backups/bulk-candidates-20260914:/evidence \
  -w /app -e PYTHONPATH=/app/packages/svs_common:/app/apps/api:/app/scripts/release \
  -e SVS_TENANT_ID=ten_ks_state_civics \
  -e SVS_BUSINESS_INSTANCE_ID=biz_ks_state_civics -e SVS_ROLES=owner,admin \
  ks-test-runner:formatnongpl python scripts/release/kansas-fiscal-document-ingest.py \
  --record-kind entity --entity-path candidate --apply \
  --manifest /evidence/hb2513-bulk-candidates.jsonl \
  --contract-schema /app/configs/statecivics-contracts/retrieval-export-record.schema.json \
  --custody-root /evidence --state /evidence/b-state.json \
  --proof /evidence/b-cli-repeat.json --api http://candidate-api:8080 --cell ks-fiscal-local
```

The current source file is also preserved compressed in both repositories. The
local evidence directory holds the complete manifest, partition hashes, per-batch
API receipts, database pre/post backups and verification output.

## Runtime boundary

The candidate service remains `exais-ks-fiscal-candidate-api`, image
`sha256:5424d7bed8160eff34b922dd223dd84dfb973501487fc2edf6179f7a0fade7e1`.
It embeds through the existing model gateway with OpenAI text-embedding-3-small
and stores candidate points separately from document retrieval. Stopping this
container disables the local candidate endpoint without changing the ledger or
other cell services. The VPS UI is unchanged.


## Reproduce the readback proof

The snapshot-specific verification command reads all candidate points and compares
every complete record with the hash-pinned fixture in this repository. It checks
three fund queries, a real vector's dimensions, live-path refusal, and unchanged
document counts from the saved pre-operation inventory. It writes
`b-verification.json` under the evidence directory. This is a fixed-snapshot
acceptance check, not a general search-recall benchmark.

```sh
docker run --rm --network exais-vector-store-ks-fiscal-local_default --memory 1g \
  -v /Users/mfrieson/Developer/exais-vector-store-operator-repo:/app:ro \
  -v /Users/mfrieson/Developer/exais-backups/bulk-candidates-20260914:/evidence \
  -w /app ks-test-runner:formatnongpl \
  python scripts/release/verify-hb2513-candidate-handoff.py \
  --evidence-root /evidence --api http://candidate-api:8080 \
  --qdrant http://qdrant:6333
```


## Measured delivery

All 2,588 records were stored and read back exactly. The command above then
reported `embedded=0`, `written=0`, `unchanged=2588`, all 26 batches complete.
PKU treatment, sexually violent predator expense fund and nursing-fund queries
each returned the expected FY2027 action first. The first is $199,274; the other
two carry the source's "No limit" designation. Every returned record includes
its durable citation. Three queries are examples, not a recall benchmark.

The [delivery receipt](statecivics-bulk-delivery-20260914.json) preserves complete
query responses, record counts, backups and repeat results. Initial indexing
resumed after two provider connection/read failures; successful-batch embedding
counts exclude those failed attempts. Both document collections retained their
original counts, 83,858 and 12,579. A checksum-verified Qdrant snapshot and the
operator ledger's pre/post dumps are outside Dropbox in the evidence directory.
Their existence and hashes are verified; snapshot restoration was not exercised.

Validation: 298 focused B tests at `4e8ae97`, followed by the actual complete
command repeat and the repository's snapshot-specific readback check at `4adb5fe`.
