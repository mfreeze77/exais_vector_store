# HB 2513 candidate pilot

The local pilot persists A's nursing-fund action at revision 3, exports it with
provision revision 2, stores both in B, and retrieves the action by fund name.
The original source citation is retained: the account entry occupies characters
`[7763, 7813)` of source revision `01a09cda-2fa6-7143-9e7c-7b539adb86db`.

The result remains **candidate**, read from enrolled text as retained. This
pilot does not reconcile vetoes or later changes, resolve a fiscal account code,
ingest the whole bill, or publish results in the VPS UI. Its search demonstration
is over two candidate points, not a broad retrieval-accuracy evaluation.

## Query the running pilot

The candidate API listens on loopback port 28086. The existing local cell uses
header principals. These headers select the Kansas instance; they are not a
bearer-token authentication demonstration.

```sh
curl --fail-with-body http://127.0.0.1:28086/api/v1/statecivics/entities/candidate/search \
  -H 'Content-Type: application/json' \
  -H 'X-SVS-Tenant-Id: ten_ks_state_civics' \
  -H 'X-SVS-Business-Instance-Id: biz_ks_state_civics' \
  -H 'X-SVS-Roles: owner,admin' \
  -d '{"query":"Nurse fair treatment and recovery fund appropriation fiscal year 2027","limit":2}'
```

The first result should be action revision 3, `amount_kind: no_limit`, fiscal
period end `2027-06-30`, and source span
`01a0a168-d786-767d-a484-c31e6839ff2e`. Its source quote is
`Nurse fair treatment and recovery fund    No limit`.

The JSON receipt alongside this runbook records the actual query, image, point
ids, exact manifest hash, initial write and unchanged repeat. Full local logs,
the pre-write database dump and the readback are in
`/Users/mfrieson/Developer/exais-backups/pilot-delivery-20260914/`.

## Repeat ingestion

This uses the image that was tested and activated. The committed fixture is
byte-identical to the durable A export; it is not the earlier rehearsal fixture.

```sh
docker run --rm --network exais-vector-store-ks-fiscal-local_default \
  -v /Users/mfrieson/Developer/exais-backups/pilot-delivery-20260914:/evidence \
  -e SVS_TENANT_ID=ten_ks_state_civics \
  -e SVS_BUSINESS_INSTANCE_ID=biz_ks_state_civics \
  -e SVS_ROLES=owner,admin \
  sha256:5424d7bed8160eff34b922dd223dd84dfb973501487fc2edf6179f7a0fade7e1 \
  python scripts/release/kansas-fiscal-document-ingest.py \
  --record-kind entity --entity-path candidate --apply \
  --manifest /evidence/hb2513-pilot-candidates.jsonl \
  --contract-schema /app/configs/statecivics-contracts/retrieval-export-record.schema.json \
  --custody-root /evidence --state /evidence/b-state.json \
  --api http://candidate-api:8080 --cell ks-fiscal-local
```

An unchanged repeat reports `embedded: 0`, `written: 0`, `unchanged: 2`.
Changing `--entity-path` to `live` refuses the candidate before the API call.
The API also independently refuses candidates on its live path.

## Runtime and rollback

`start-kansas-candidate-api.py` starts a separate local API container using the
existing cell's runtime configuration, a distinct DNS alias and loopback port.
It copies secrets through a private temporary file, removes that file after
startup, and never replaces the host's PATH with the container's PATH.

```sh
python3 scripts/release/start-kansas-candidate-api.py \
  --image sha256:5424d7bed8160eff34b922dd223dd84dfb973501487fc2edf6179f7a0fade7e1 \
  --source-commit 5e24383abdad1e7e3168d7f1a0505ceb82f44412 --apply
```

The original API, worker and model gateway continue running. To disable this
pilot endpoint, stop `exais-ks-fiscal-candidate-api`; start that same container
to resume it. Its candidate collection remains separate from document retrieval.
A's append-only revisions and source spans remain in the ledger.

The unmerged bulk extraction work remains on A's `ks-659-operator-command`
branch at `80092998`. Its proviso and review-reachability findings remain open.
