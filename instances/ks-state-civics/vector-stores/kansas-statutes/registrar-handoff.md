# First statute registrar and retrieval-export handoff

Reviewed upstream `a4091f62` against ExAIS `8804f79`. The registry corrections
are present. This is an operator handoff for the existing StateCivics owner;
it does not implement a registrar or register custody. The requirements below
are retained as the original handoff; the subsequent delivery is recorded here.

## Delivered handoff — 2026-09-11

StateCivics delivered the sibling registrar at `a54590b3b3ec8de064ae2b59ed620290750d2d4f`
and its proof at main `f445519009fb40b846af6a47cd7224992dd45a60`.
The approved `kansas-statutes.jsonl` is 10,954 bytes, six records, SHA-256
`c9a06920795b47d92c8d336395ab94c459fa8404e029a92708444d06276ea3a7`.
Its actual custody namespace is `civic-custody://kansas_statutes/`.

The [independent ExAIS input audit](../../../../.tranche/statecivics-semantic-graph/aligned/statute-real-export-audit.md)
validated all six records against the retained upstream schema, recomputed
record and identity digests, and verified the exact intended files, official
URLs, harvest bindings and six byte-identical custody objects (154,148 bytes).
The existing consumer's [dry run](../../../../.tranche/statecivics-semantic-graph/aligned/statute-real-export-plan.json)
planned four semantic upserts and two exclusions. Upstream reports unchanged
registration/export replay; ExAIS has not independently queried that ledger or
replayed registration. Live local indexing and retrieval belong to
[WAVE-138](../../../../tickets/WAVE-138-kansas-statute-local-canary.md).

Unchanged bytes currently have no separate repeat-observation row upstream.
That requires a producer-owned collection-observation decision; do not mint a
new document/revision or imply the observation was persisted. It does not block
indexing this export. Bounded source selection is still required before a wider
or second statute family enters the same export query.

The manager reports a pre-existing red full suite and 33 added passing tests.
The input audit is a bounded handoff result, not certification of that full
suite. Custody reconciliation compares distinct revision hashes to objects;
multiple revision rows may correctly share the same object.

## Full chapter delivery — 2026-09-11

Upstream main `ad6b38c0c0448b120ac4206a13aaf00d305b9d7b` delivered 85 chapter
exports produced at `63ae57b9221ed7a8eaf44ac57622b7025aea556e`, with
INDEX SHA-256 `65d2424709bb1e54ab7fad9142ceffb6c00f961d463ca78b5dc7c277194f63e0`.
The original six-record manifest remains byte-identical.

The [complete input audit](../../../../.tranche/statecivics-semantic-graph/aligned/statute-chapter-export-audit.md)
checked every tranche/record, every custody-to-corpus byte pair and every parsed
chunk: 31,079 records, 28,812 substantive documents, 2,264 empty bodies,
three inline-History-only documents and 83,258 exact-source chunks. These are
available inputs, not live index counts. No upstream database or full-suite
health claim follows from this audit.

These files are partial batches. Omission is not withdrawal. The existing
consumer plans only incoming rows and preserves omitted state; explicit
lifecycle removals and content exclusions still apply to their named documents.
[WAVE-139](../../../../tickets/WAVE-139-kansas-statute-chapter-handoff.md)
owns the shared-state regression and two-chapter live proof before further rollout.

Canonical document identity remains jurisdiction/source-family/logical-key;
SHA-256 binds content. The manager's hash-as-identity wording does not describe
a contract change. The actual label guard does have a producer-owned defect:
substring matching accepts `1-20` for `1-204`. All delivered joins passed the
independent audit, so tightening that guard is a future-input correction, not a
reason to discard this pinned delivery. The audit records the executable case.

## Reuse the existing storage and ledger services

A small sibling such as `scripts/operator/register_statute_document_corpus.py`
can supply the statute-specific planning and registration fields. Reuse
`services/civic_impact/custody_store.py:default_store`,
`SourceArtifactService.register_artifact`, and
`SourceArtifactService.register_revision`. The service accepts bytes and MIME
metadata already. The fiscal operator script hard-codes PDF checks and fiscal
identity/MIME fields, so merely bypassing its filename filter is insufficient.
Reuse `export_retrieval_manifest.py` and its existing contract for projection.

Validate all selected retained files before applying; pass the exact bytes to
both custody and `register_revision(content_bytes=...)`. Preserve the original
Markdown, including embedded CR characters. Register `artifact_type: statute`,
`source_family: ks_revisor_statutes`, `collection_method: official_html`, and
`mime_type: text/markdown`. The revision content and text hashes should describe
those exact retained UTF-8 Markdown bytes. Observation times, manifest binding,
response-text capture details and changing History metadata belong with revision
or observation evidence, not immutable artifact metadata.

Keep the official URL and capture metadata, explicitly identifying
`response_sha256` as decoded response text re-encoded as UTF-8. The original
HTML is not retained in this corpus; do not create a supposedly retained original
object or claim a verified HTML-to-Markdown replay. Do not append provenance
headers to the Markdown during registration: that would change the consumer's
pinned hash and coordinates.

## Exact first selection

All filenames are under `data/ksa/` in the existing retained corpus. Bind the
selection to manifest
`statute_scrape_20260911_030653.json`, SHA-256
`17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2`.

| Retained file | Case exercised | Local chunks |
|---|---|---:|
| `ksa_001_002_0004.md` | Fund/financial-rule text, K.S.A. 1-204 | 2 |
| `ksa_002_003_0003.md` | Short substantive body, 397 bytes | 2 |
| `ksa_073_002_0001.md` | Two manifest records, one retained document | 7 |
| `ksa_079_036_0006.md` | Long text with subsection and metadata boundaries | 51 |
| `ksa_060_034_0001.md` | Empty body despite a 1,793-byte file | 0 |
| `ksa_041_002_0014.md` | Inline History-only text | 0 |

The six retained files' hashes and sizes were checked against every corresponding
harvest record. A run of the current ExAIS parser produced **62 chunks**
from four files, with exact source slices; two files contributed no chunks.
This was local parsing in a network-disabled container, not embedding or indexing.
Retain all six in custody according to the producer's policy; semantic exclusion
does not erase their source or History records.

## Export selection and replay

Deliver the actual approved JSONL targeting
`ks-state-civics/kansas-statutes`, the matching custody objects/root, and the
registration/export proof. Use canonical ledger IDs and exporter digests.
The [existing consumer commands](README.md#plan-an-approved-custody-export)
join that export to the pinned harvest.

At `a4091f62`, `export_retrieval_manifest.py:_select_pinned_revisions`
filters by artifact type and jurisdiction. `--vector-store-slug` labels the
output; it does not filter the source family or the selected artifact IDs.
Verify that the first output contains exactly the intended six identities.
If other statute families/documents are present, add bounded selection to the
existing exporter rather than assuming its target flag selects them or creating
a second exporter.

The existing `register_revision` reuses an earlier revision for the same
artifact/content hash. An unchanged re-harvest therefore does not automatically
create a new revision just because the observation date changed. Preserve repeat
observations in the collection evidence; do not change `logical_key` to force
new rows. This does not block first registration.

Acceptance for the first handoff:

- Register and export the six real files; validate every exported custody object,
  URL, hash, byte size and canonical identity before API effects.
- Replay the same registration/export and retain the same artifact/revision/
  document identities without duplicate custody objects.
- With all six eligible as document upserts and an empty consumer state, expect
  four planned semantic upserts and two content exclusions, totalling 62 local
  chunks. Eligibility/lifecycle removals remain authoritative if the producer
  withholds a record.
- After deploying the consumer, verify server preview selects the statute
  chunker and Voyage-4/1024, then check real retrieval and citation coordinates.
  Lifecycle/correction integration must be exercised without publishing
  fabricated statute text.

Migration 111 and canonical provision/entity linking remain independent of this
document handoff.

## Local selection verification command

This command exited 0 and returned per-file chunk counts 2, 2, 7, 51, 0, 0.

```sh
docker run --rm -i --platform linux/amd64 --network none --memory 1g --cpus 1 -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro -v /Users/mfrieson/Developer/statecivics-statute-corpus:/statutes:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python - <<'PY'
from pathlib import Path
import hashlib,json
from svs_common.statecivics_statutes import parse_statute_markdown,statecivics_statute_markdown_chunks
root=Path('/statutes/data/ksa')
for name in ['ksa_001_002_0004.md','ksa_002_003_0003.md','ksa_073_002_0001.md','ksa_079_036_0006.md','ksa_060_034_0001.md','ksa_041_002_0014.md']:
    raw=(root/name).read_bytes();md=raw.decode('utf-8');sha=hashlib.sha256(raw).hexdigest()
    parsed=parse_statute_markdown(md,expected_sha256=sha)
    chunks=statecivics_statute_markdown_chunks(md,expected_sha256=sha)
    assert all(md[c.char_start:c.char_end]==c.text for c in chunks)
    print(json.dumps({'filename':name,'classification':parsed.classification,'chunks':len(chunks)}))
PY
```
