# Six-document statute export: independent input audit

**PASS for this bounded input handoff**, 2026-09-11. This is evidence inspection,
not implementation QC, upstream gate acceptance, or proof of live indexing.
ExAIS base: `f0114e0`; upstream reviewed:
`f445519009fb40b846af6a47cd7224992dd45a60`.

## Independently verified

- Approved export:
  `/Users/mfrieson/Developer/statecivics-statute-exports/kansas-statutes.jsonl`,
  **10,954 bytes**, SHA-256
  `c9a06920795b47d92c8d336395ab94c459fa8404e029a92708444d06276ea3a7`.
- All **six** JSONL records validate against the retained upstream
  `retrieval-export-record.schema.json`, with its `source-artifact.schema.json`
  reference registered locally. Draft 2020-12 validation included format checks
  and used no network.
- All six record digests independently recompute using sorted compact UTF-8 JSON,
  `ensure_ascii=False`, omitting only the digest and exporter clock. All six
  logical-document and export-record IDs recompute from the exporter formulas;
  revision, logical-document and export-record IDs are distinct within this batch.
- Selection exactly matches the six table rows in
  [registrar-handoff.md](../../../instances/ks-state-civics/vector-stores/kansas-statutes/registrar-handoff.md).
  Every record targets `ks-state-civics/kansas-statutes`, with current lifecycle,
  full redistribution, retained custody and document `upsert`.
- Each exact official URL is consistent with its complete expected Revisor path,
  corpus filename, rendered `**Source:**` line, rendered K.S.A. heading,
  source logical key and all matching pinned harvest records. The two manifest
  entries for 73-201 join to one output document.
- All six actual custody objects under
  `/Users/mfrieson/Developer/statecivics-custody/kansas_statutes/` are byte-for-byte
  equal to the harvested Markdown and match their URI digest, export hash and
  byte size. The inspected namespace contains exactly **six objects / 154,148 bytes**.
- Each exported `as_of_date` matches the UTC date of its fetched harvest record.
  Effective dates, publication dates and fiscal years remain null; no legal
  effectiveness is inferred from capture dates.

| Corpus filename | Bytes | Custody/export/corpus SHA-256 |
|---|---:|---|
| `ksa_001_002_0004.md` | 1,269 | `7f8cf97c69746dc7358a227f75b695f3d04a360fa986d72311c76b0e4646fba8` |
| `ksa_002_003_0003.md` | 397 | `5501388fc2e8da55cef32d49d15e7f5f14c0b20341d43e9f46d8c4cb381c7d02` |
| `ksa_041_002_0014.md` | 317 | `61ec4a306e8f38dbd32e8d2753de09762ab67cee8eae81f8483d7d4bb13426d8` |
| `ksa_060_034_0001.md` | 1,793 | `91730f6aac49e93c65c79454df9ec4178ae690fa6672f5c664117baba8e79bb9` |
| `ksa_073_002_0001.md` | 11,194 | `0fdec938ba323916318c69b107d963e153cbe6e2965d70db4b5f58fe9651ce15` |
| `ksa_079_036_0006.md` | 139,178 | `bfb19a7c558c635450563964c1571fa3dcd99756494aea82c6fa2b54b7e4c4f7` |

Harvest manifest SHA-256 independently rechecked:
`17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2`.

## Registrar review and limits

No handoff-breaking identity/provenance defect was found for these six inputs.
The registrar requires explicit selection, verifies selected rendered hashes and
sizes, checks header/URL identity, resolves the known duplicate with consistent
rendered/history fields, and passes unchanged bytes to custody and revision
registration. It places capture/History metadata on the revision, keeps History
events unresolved, and labels response hashes as decoded text re-encoded in UTF-8.

The publisher chapter/article/section key is a **document identity** in this
handoff. It does not prove persistent legal-provision identity across
recodification. Likewise, document lifecycle `current` is not a determination
that every retained section body remains legally operative.

The delivered document export does not carry raw HTML, source-artifact UUIDs,
text-hash/extractor fields, or the complete revision metadata. Its consistent
revision IDs and hashes do not independently prove live ledger rows, registration
replay, recorded extraction metadata, rights review, or collection-history
persistence. Those remain producer-reported in
`docs/STATUTE_REGISTRAR_FIRST_HANDOFF_PROOF.md`. No HTML-to-Markdown replay,
canonical graph linkage or locator-verification attestation was established.

The producer explicitly reports unchanged re-observation loss and currently
broad exporter selection. This batch is correctly bounded; a later broader batch
must not rely on the target store slug as an input-selection filter. The producer's
33-test result and full-suite baseline failures were read as reported evidence;
this audit ran neither those tests nor any upstream gate.

## Reproduction and pinned review inputs

Read-only Git comparison established these bytes match the reviewed upstream
commit:

| Upstream file | SHA-256 |
|---|---|
| `scripts/operator/register_statute_document_corpus.py` | `f1d1d516685c870ae3440367af5b4d12c589cf0146ec69e9f03b30e58c5408ab` |
| `services/civic_impact/retrieval_exporter.py` under `src/kansas_accountability/` | `a568a722340619951f98c4728cb2f7102317e60557f1267b3bd9f77629a8b14d` |
| `contracts/civic-impact/retrieval-export-record.schema.json` | `78a3de138cdb534831df034bc66f6a6a2bf7ec3f5d6d573efedf2b50d7a7f32b` |
| `contracts/civic-impact/source-artifact.schema.json` | `f0fdefbe737a320076e848bf840596b290c052a7c6a7e961d6bd51c10d759f65` |

The standalone audit ran with `--network none --memory 1g --cpus 1`, read-only
export/corpus/custody/contracts/handoff mounts, and
`PYTHONDONTWRITEBYTECODE=1`. Existing ARM64 image `ks-test-runner:latest`,
image ID `sha256:64cd3013228b70b33338c9b4ab46fad3e251ed31fcc5542536cd0f3002516b77`.
**Exit 0, approximately 0.34 seconds.** Its normal entrypoint was preserved;
no .env, DB DSN or credentials were supplied.

One initial attempt with the existing ExAIS API image exited before performing
the audit because `jsonschema` is absent there. No dependency was installed;
the already-present test image provided the validator.

<details>
<summary>Exact successful audit command</summary>

```sh
docker run --rm -i --platform linux/arm64 --network none --memory 1g --cpus 1 \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money/instances/ks-state-civics/vector-stores/kansas-statutes/registrar-handoff.md:/handoff.md:ro \
  -v /Users/mfrieson/Developer/statecivics-statute-exports/kansas-statutes.jsonl:/export.jsonl:ro \
  -v /Users/mfrieson/Developer/statecivics-statute-corpus:/corpus:ro \
  -v /Users/mfrieson/Developer/statecivics-custody/kansas_statutes:/custody/kansas_statutes:ro \
  -v /Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai/contracts/civic-impact:/contracts:ro \
  -e PYTHONDONTWRITEBYTECODE=1 \
  ks-test-runner:latest python - <<'PY'
import hashlib,json,re
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime,timezone
from jsonschema import Draft202012Validator,FormatChecker
from referencing import Registry,Resource
sha=lambda b:hashlib.sha256(b).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
schemas={}
for name,expected in [('retrieval-export-record.schema.json','78a3de138cdb534831df034bc66f6a6a2bf7ec3f5d6d573efedf2b50d7a7f32b'),('source-artifact.schema.json','f0fdefbe737a320076e848bf840596b290c052a7c6a7e961d6bd51c10d759f65')]:
 raw=(Path('/contracts')/name).read_bytes();assert sha(raw)==expected
 schemas[name]=json.loads(raw)
registry=Registry().with_resources((s['$id'],Resource.from_contents(s)) for s in schemas.values())
schema=schemas['retrieval-export-record.schema.json'];Draft202012Validator.check_schema(schema)
validator=Draft202012Validator(schema,registry=registry,format_checker=FormatChecker())
raw=Path('/export.jsonl').read_bytes()
assert len(raw)==10954 and sha(raw)=='c9a06920795b47d92c8d336395ab94c459fa8404e029a92708444d06276ea3a7'
records=[json.loads(line) for line in raw.splitlines()]
assert len(records)==6
for key in ('export_record_id','logical_document_id','source_revision_id'):
 assert len({r[key] for r in records})==6,key
manifest_raw=Path('/corpus/manifests/statute_scrape_20260911_030653.json').read_bytes()
assert sha(manifest_raw)=='17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2'
man=json.loads(manifest_raw)
expected=set(re.findall(r'^\| `(ksa_[^`]+\.md)` \|',Path('/handoff.md').read_text(),re.M));assert len(expected)==6
by_filename={}
for d in man['documents']:by_filename.setdefault(d['filename'],[]).append(d)
seen=set();result=[]
for r in records:
 validator.validate(r)
 shadow=json.loads(json.dumps(r));shadow.pop('record_digest_sha256');shadow['exporter'].pop('exported_at',None)
 assert sha(canonical(shadow))==r['record_digest_sha256']
 assert r['record_digest_algorithm']=='statecivics-canonical-json-v1'
 assert r['exporter']['code_commit']=='a54590b3b3ec8de064ae2b59ed620290750d2d4f'
 assert sha(canonical({'source_revision_id':r['source_revision_id'],'exporter_name':r['exporter']['name'],'exporter_version':r['exporter']['version']}))==r['export_record_id']
 meta=r['metadata'];assert meta['source_family']=='ks_revisor_statutes'
 logical_key=meta['source_logical_key']
 match=re.fullmatch(r'ks-revisor-statutes:ch(\d{3}[a-z]?):art(\d{3}[a-z]?):sec(\d{4}[a-z]?)',logical_key);assert match
 chapter,article,section=match.groups();filename=f'ksa_{chapter}_{article}_{section}.md'
 assert filename in expected and filename not in seen;seen.add(filename)
 assert sha(canonical({'jurisdiction':r['jurisdiction'],'source_family':meta['source_family'],'logical_key':logical_key}))==r['logical_document_id']
 url=f'https://ksrevisor.gov/statutes/chapters/ch{int(chapter):02d}/{chapter}_{article}_{section}.html'
 assert r['citation_url']==r['retrieval_url']==url
 assert r['ingestion']['action']=='upsert' and r['ingestion']['mode']=='api_only'
 assert r['ingestion']['target_instance_slug']=='ks-state-civics' and r['ingestion']['target_vector_store_slug']=='kansas-statutes'
 assert r['artifact_type']=='statute' and r['mime_type']=='text/markdown'
 assert r['jurisdiction']=='ocd-jurisdiction/country:us/state:ks/government'
 assert r['publisher']=='Kansas Office of Revisor of Statutes'
 assert r['custody_status']=='retained' and r['redistribution']=='full'
 assert r['license_profile']=='ks_public_records_review_required'
 assert r['lifecycle']['state']=='current' and r['lifecycle']['removal_required'] is False
 assert r['revision_number']==1
 u=urlsplit(r['custody_uri']);digest=r['content_hash_sha256']
 assert u.scheme=='civic-custody' and u.netloc=='kansas_statutes' and u.path==f'/{digest[:2]}/{digest}' and not u.query and not u.fragment
 custody=Path('/custody/kansas_statutes')/digest[:2]/digest
 b=custody.read_bytes();body=(Path('/corpus/data/ksa')/filename).read_bytes()
 assert b==body and sha(b)==digest and len(b)==r['byte_size']
 text=b.decode('utf-8',errors='strict')
 assert re.findall(r'^\*\*Source:\*\* (\S+)[\r]?$',text,re.M)==[url]
 heading=re.match(r'# K\.S\.A\. (.+?) —',text).group(1)
 selected=by_filename[filename]
 assert all(d['source_url']==url and d['rendered_sha256']==digest and d['rendered_bytes']==len(b) for d in selected)
 valid_numbers={d['section_number'] for d in selected if re.fullmatch(r'[0-9]{1,3}[a-z]?-[0-9][0-9a-z,]*',d['section_number'])}
 assert valid_numbers=={heading}
 fetched=[d for d in selected if d['response_sha256']]
 assert len(fetched)==1
 capture=datetime.fromisoformat(fetched[0]['scraped_at_utc']).astimezone(timezone.utc)
 assert r['effective_period']['as_of_date']==capture.date().isoformat()
 assert all(r['effective_period'][key] is None for key in ('effective_from','effective_to','published_at','fiscal_year'))
 result.append({'filename':filename,'ksa':heading,'bytes':len(b),'sha256':digest,'manifest_rows':len(selected),'custody_equal':True,'as_of_date':r['effective_period']['as_of_date']})
assert seen==expected
objects=[p for p in Path('/custody/kansas_statutes').rglob('*') if p.is_file()]
assert len(objects)==6
assert {p.name for p in objects}=={r['content_hash_sha256'] for r in records}
print(json.dumps({'export_sha256':sha(raw),'export_bytes':len(raw),'records_validated':len(records),'record_digests_valid':6,'logical_and_export_ids_recomputed':6,'exact_expected_files':True,'custody_objects':len(objects),'custody_bytes':sum(r['bytes'] for r in result),'records':sorted(result,key=lambda r:r['filename']),'live_database_or_raw_html_verified':False},indent=2,sort_keys=True))
PY
```

</details>

Only this report was written. No registrar apply, live DB query, upstream gate,
corpus mutation, provider call, index write or operational deployment occurred.
