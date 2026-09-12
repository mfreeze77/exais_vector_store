# Full statute chapter export: independent input audit

**PASS for the delivered input bytes, with one nonblocking producer validation finding.**
2026-09-11. This is a read-only handoff audit, not final implementation QC,
a live indexing result, an upstream database audit, or an upstream test-suite gate.

Reviewed ExAIS base: `872f7e2`. Upstream checkout was clean at
`ad6b38c0c0448b120ac4206a13aaf00d305b9d7b`; chapter records identify the actual
export producer as `63ae57b9221ed7a8eaf44ac57622b7025aea556e`.

## Verified over the complete delivery

| Check | Measured result |
|---|---:|
| Chapter tranche files, exact declared hashes and byte counts | 85 / 85 |
| JSONL bytes | 57,034,050 |
| Schema-valid records, valid record digests | 31,079 / 31,079 |
| Unique logical-document, source-revision, and export-record IDs | 31,079 each |
| Exact custody ↔ harvested Markdown byte comparisons | 31,079 / 31,079 |
| Statute custody namespace objects / bytes | 31,079 / 66,750,184 |
| Substantive documents | 28,812 |
| Empty-body documents | 2,264 |
| Inline-History-only documents | 3 |
| Computed chunks / exact character selections verified | 83,258 / 83,258 |
| Computed chunk characters, including overlap | 62,206,966 |
| Raw / deduplicated History references | 72,753 / 72,733 |
| Non-unresolved History references | 0 |

Each record validated with the retained Draft 2020-12 JSON Schema and format
checker, with schema references resolved locally and networking disabled.
Every record digest and both deterministic ID formulas were independently
recomputed. Records are current document upserts with full redistribution and
retained custody, all scoped to `ks-state-civics/kansas-statutes`.

For every record, the audit joined the logical chapter/article/section key to
the exact filename, full official Revisor URL, rendered Source line, pinned
harvest records, custody URI, content hash and byte size. The exported as-of
date is a recorded capture date; no effective date is inferred.
The union of all tranches exactly equals the harvest's 31,079 distinct filenames.
The statute namespace has no extra or missing content hashes. This does **not**
independently verify the reported global 34,429-row/hash/object ledger inventory;
no database was queried.

The existing ExAIS parser independently reproduced every chapter's indexable,
chunk and character counts. Every chunk's character range selected its exact
original text and its text hash recomputed. This verifies parser coordinates,
not a canonical provision binding or upstream locator-verification attestation.

## Six existing canaries stay the same sources

The original six-record export is unchanged: 10,954 bytes, SHA-256
`c9a06920795b47d92c8d336395ab94c459fa8404e029a92708444d06276ea3a7`.

All six documents are also present in their chapter tranches. For each, the
**only changed top-level fields are `exporter` and `record_digest_sha256`**.
The exporter commit advanced from `a54590b3...` to `63ae57b9...`.
Logical-document IDs, source-revision IDs, export-record IDs, content hashes,
custody URIs, rights/lifecycle metadata and all other fields remain identical.
A changed exporter pin is not a source-content change and does not itself warrant
new vectors. The rollout runner must preserve source-level idempotency while
retaining the new export provenance; root's separate consumer review owns that
operational check.

## Identity and the producer's label validation

Canonical document identity was **not changed to a content hash**. The registrar
still builds `ks-revisor-statutes:ch…:art…:sec…`, and the exported logical ID
still hashes jurisdiction, source family and logical key. The SHA-256 binds the
retained content/revision bytes. Neither the filename numbering nor a content
hash establishes a persistent provision identity through legal recodification.
The manager's statement that “identity is the sha256” should be corrected as
wording, not treated as a new contract.

There is a real, bounded validation weakness in the new label sanity check:
`_parse_rendered` accepts either label as an arbitrary substring of the other.
Executing the committed function against the real `ksa_001_002_0004.md`
accepted a deliberately wrong manifest label **1-20** for the rendered **1-204**.
That fails to reject a different section label that merely shares a prefix.
The file hash and URL checks do not repair this particular guard: a manifest can
retain the correct file hash/URL while carrying that wrong display label.

This does **not** invalidate the inspected delivery. All 31,079 delivered label
groups had an exact rendered-label member except the already documented
`ksa_074_032_0315.md`: manifest `74-32,315`, rendered
`74-32,315 through 74-32,400`. The six chapter-73 duplicate groups contain an
exact canonical label alongside the glued-heading variant. No incorrect
delivered identity/URL/bytes join was found.

Suggested producer follow-up: retain explicit accepted transformations for
TOC heading prefixes and range/list labels, but compare complete citation tokens
rather than arbitrary numeric substrings. Add the real 1-20/1-204 collision as a
negative case. This is a producer-owned hardening item; no upstream file changed.

The reported “1,270 ranges” also needs precise language. There are **1,270
manifest labels failing the old single-section regex**, including 366 labels
containing ` through `, 898 other multi-hyphen labels (including citation lists),
and six glued-heading labels. The issue is broader than ranges. No ingestion
decision in this audit used label length, byte length or that old shape filter.

## Delivery and proof limits

- These 85 files are bounded tranches, not omission-based desired-state snapshots.
  No absence in chapter 2 authorizes deleting a chapter-1 document. That semantic
  is present in INDEX and producer documentation; consumer behavior is reviewed
  separately by root.
- All 72,733 document-deduplicated History occurrences remain unresolved. No
  statute → session-law → bill relationship was promoted to a canonical edge.
- This audit verifies the retained Markdown and export provenance chain.
  Original HTML is absent; response hashes represent decoded text re-encoded
  as UTF-8. There was no original-HTML replay or independent legal correctness
  review of all statute text.
- Registration replay, source-ledger contents, repeat-observation persistence,
  rights-review decisions and upstream suite results were not rerun here.
- No provider, API, live database, Docker service configuration or index was
  touched. Only this report and its compact JSON summary were written.

## Reproduction

Inputs:

| Input | SHA-256 |
|---|---|
| `chapters/INDEX.json` | `65d2424709bb1e54ab7fad9142ceffb6c00f961d463ca78b5dc7c277194f63e0` |
| Pinned harvest manifest | `17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2` |
| Retrieval export schema | `78a3de138cdb534831df034bc66f6a6a2bf7ec3f5d6d573efedf2b50d7a7f32b` |
| Source artifact schema | `f0fdefbe737a320076e848bf840596b290c052a7c6a7e961d6bd51c10d759f65` |
| Registrar source | `5d175238dd1a31c317280a2c33d6ae73c9d7e79a5e25ada873d641ab82c4dafd` |
| Operator exporter source | `1668587ca7c4446ec71d87114781be303f5c165c104cc62b5c046ffd6ec0285f` |
| Export service source | `a568a722340619951f98c4728cb2f7102317e60557f1267b3bd9f77629a8b14d` |
| ExAIS statute parser source | `fb46e638978e81e64bda701c9571396848ab448f93861a2859e97915d72643dc` |
| ExAIS shared chunking source | `520b9537644014353393b1c2a913d428e0fdfd383cbbc8d9c8c0588f5a4b5ebe` |

Existing `ks-test-runner:latest` image ID:
`sha256:64cd3013228b70b33338c9b4ab46fad3e251ed31fcc5542536cd0f3002516b77`.
Read-only inputs, no network, 2 GiB / 2 CPUs, no credentials or .env.
**Full audit exit 0, measured Python audit time 28.92 seconds.**
A second read-only 0.37-second container command counted the label categories and
recorded source-file hashes in the compact summary.

[Machine-readable summary](statute-chapter-export-audit-summary.json).

<details>
<summary>Exact full audit command</summary>

```sh
docker run --rm -i --platform linux/arm64 --network none --memory 2g --cpus 2 -v /Users/mfrieson/Developer/exais-vector-store-law-money/packages/svs_common:/consumer:ro -v /Users/mfrieson/Developer/statecivics-statute-exports:/exports:ro -v /Users/mfrieson/Developer/statecivics-statute-corpus:/corpus:ro -v /Users/mfrieson/Developer/statecivics-custody/kansas_statutes:/custody/kansas_statutes:ro -v /Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai:/upstream:ro -v /Users/mfrieson/Developer/exais-vector-store-law-money/.tranche/statecivics-semantic-graph/aligned:/proof -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/consumer ks-test-runner:latest python - <<'PY'
import ast, hashlib, json, re, time
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime, timezone
from collections import Counter, defaultdict
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from svs_common.statecivics_statutes import parse_statute_markdown, statecivics_statute_markdown_chunks
start=time.monotonic()
sha=lambda b:hashlib.sha256(b).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
def require(value,label):
 if not value:raise AssertionError(label)
schemas={}
for name,expected in [('retrieval-export-record.schema.json','78a3de138cdb534831df034bc66f6a6a2bf7ec3f5d6d573efedf2b50d7a7f32b'),('source-artifact.schema.json','f0fdefbe737a320076e848bf840596b290c052a7c6a7e961d6bd51c10d759f65')]:
 raw=(Path('/upstream/contracts/civic-impact')/name).read_bytes();require(sha(raw)==expected,name)
 schemas[name]=json.loads(raw)
registry=Registry().with_resources((s['$id'],Resource.from_contents(s)) for s in schemas.values())
schema=schemas['retrieval-export-record.schema.json'];Draft202012Validator.check_schema(schema)
validator=Draft202012Validator(schema,registry=registry,format_checker=FormatChecker())
indexraw=Path('/exports/chapters/INDEX.json').read_bytes()
require(sha(indexraw)=='65d2424709bb1e54ab7fad9142ceffb6c00f961d463ca78b5dc7c277194f63e0','index sha')
idx=json.loads(indexraw)
require(idx['totals']=={'tranches':85,'records':31079,'bytes':57034050,'indexable_documents':28812,'chunks':83258,'chunk_chars':62206966},'declared totals')
manifest_raw=Path('/corpus/manifests/statute_scrape_20260911_030653.json').read_bytes()
require(sha(manifest_raw)=='17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2','harvest sha')
manifest=json.loads(manifest_raw)
by_filename=defaultdict(list)
for d in manifest['documents']:by_filename[d['filename']].append(d)
canary_raw=Path('/exports/kansas-statutes.jsonl').read_bytes()
require(len(canary_raw)==10954 and sha(canary_raw)=='c9a06920795b47d92c8d336395ab94c459fa8404e029a92708444d06276ea3a7','canary pin')
canaries={r['logical_document_id']:r for r in map(json.loads,canary_raw.splitlines())}
seen_ids={k:set() for k in ('export_record_id','logical_document_id','source_revision_id')}
seen_files=set();seen_chapters=set();seen_digests=set()
totals=Counter();classifications=Counter();canary_changes=[];label_diffs=[];range_count=0;manifest_range_labels=0
for rows in by_filename.values():
 manifest_range_labels+=sum(' through ' in str(r.get('section_number','')) for r in rows)
history_count=0;raw_history_count=0
for rows in by_filename.values():
 for r in rows:raw_history_count+=len(r.get('history_events') or [])
 events=rows[0].get('history_events') or []
 require(all(canonical(r.get('history_events') or [])==canonical(events) for r in rows),'history duplicate agreement')
 require(all(e['resolution_status']=='unresolved' for e in events),'unresolved history')
 history_count+=len(events)
chapter_results=[]
for chapter in idx['chapters']:
 require(chapter['chapter'] not in seen_chapters,'duplicate chapter')
 seen_chapters.add(chapter['chapter'])
 name=chapter['file'];require(name==f"ksa-ch{chapter['chapter']}.jsonl",'tranche filename')
 raw=(Path('/exports/chapters')/name).read_bytes()
 require(sha(raw)==chapter['sha256'] and len(raw)==chapter['bytes'],f'tranche bytes/hash {name}')
 rows=[json.loads(line) for line in raw.splitlines()]
 require(len(rows)==chapter['records'],f'tranche record count {name}')
 local=Counter(records=len(rows),bytes=len(raw),indexable_documents=0,chunks=0,chunk_chars=0)
 for r in rows:
  validator.validate(r)
  shadow=json.loads(json.dumps(r));shadow.pop('record_digest_sha256');shadow['exporter'].pop('exported_at',None)
  require(sha(canonical(shadow))==r['record_digest_sha256'],'record digest')
  require(r['record_digest_algorithm']=='statecivics-canonical-json-v1','digest algorithm')
  require(r['exporter']['code_commit']=='63ae57b9221ed7a8eaf44ac57622b7025aea556e','export commit')
  require(sha(canonical({'source_revision_id':r['source_revision_id'],'exporter_name':r['exporter']['name'],'exporter_version':r['exporter']['version']}))==r['export_record_id'],'export identity')
  for key,seen in seen_ids.items():
   require(r[key] not in seen,f'duplicate {key}');seen.add(r[key])
  meta=r['metadata'];require(meta['source_family']=='ks_revisor_statutes','source family')
  logical_key=meta['source_logical_key']
  match=re.fullmatch(r'ks-revisor-statutes:ch(\d{3}[a-z]?):art(\d{3}[a-z]?):sec(\d{4}[a-z]?)',logical_key);require(match,'logical key')
  ch,article,section=match.groups();filename=f'ksa_{ch}_{article}_{section}.md'
  require(ch==chapter['chapter'] and filename not in seen_files,'chapter key or duplicate filename')
  seen_files.add(filename)
  require(sha(canonical({'jurisdiction':r['jurisdiction'],'source_family':meta['source_family'],'logical_key':logical_key}))==r['logical_document_id'],'logical identity')
  chapterdigits=re.fullmatch(r'(\d+)([a-z]?)',ch)
  url=f"https://ksrevisor.gov/statutes/chapters/ch{int(chapterdigits[1]):02d}{chapterdigits[2]}/{ch}_{article}_{section}.html"
  require(r['citation_url']==r['retrieval_url']==url,'complete official URL')
  require(r['ingestion']['action']=='upsert' and r['ingestion']['mode']=='api_only','action and mode')
  require(r['ingestion']['target_instance_slug']=='ks-state-civics' and r['ingestion']['target_vector_store_slug']=='kansas-statutes','target')
  require(r['artifact_type']=='statute' and r['mime_type']=='text/markdown','artifact type')
  require(r['jurisdiction']=='ocd-jurisdiction/country:us/state:ks/government','jurisdiction')
  require(r['publisher']=='Kansas Office of Revisor of Statutes','publisher')
  require(r['custody_status']=='retained' and r['redistribution']=='full','custody publication')
  require(r['license_profile']=='ks_public_records_review_required','license profile')
  require(r['lifecycle']['state']=='current' and r['lifecycle']['removal_required'] is False,'lifecycle')
  require(r['revision_number']==1,'revision number')
  u=urlsplit(r['custody_uri']);digest=r['content_hash_sha256'];seen_digests.add(digest)
  require(u.scheme=='civic-custody' and u.netloc=='kansas_statutes' and u.path==f'/{digest[:2]}/{digest}' and not u.query and not u.fragment,'custody URI')
  b=(Path('/custody/kansas_statutes')/digest[:2]/digest).read_bytes()
  body=(Path('/corpus/data/ksa')/filename).read_bytes()
  require(b==body and sha(b)==digest and len(b)==r['byte_size'],'exact custody/corpus/hash/size')
  totals['custody_bytes']+=len(b)
  text=b.decode('utf-8',errors='strict')
  require(re.findall(r'^\*\*Source:\*\* (\S+)[\r]?$',text,re.M)==[url],'rendered URL')
  selected=by_filename[filename]
  require(all(d['source_url']==url and d['rendered_sha256']==digest and d['rendered_bytes']==len(b) for d in selected),'manifest URL/hash/size')
  captures={datetime.fromisoformat(d['scraped_at_utc']).astimezone(timezone.utc).date().isoformat() for d in selected}
  require(r['effective_period']['as_of_date'] in captures,'capture date')
  require(all(r['effective_period'][key] is None for key in ('effective_from','effective_to','published_at','fiscal_year')),'no inferred effective date')
  parsed=parse_statute_markdown(text,expected_sha256=digest,expected_source_url=url)
  classifications[parsed.classification]+=1
  labels={d['section_number'] for d in selected}
  require(any(parsed.section_label in label or label in parsed.section_label for label in labels),'related labels')
  if parsed.section_label not in labels:label_diffs.append({'filename':filename,'rendered':parsed.section_label,'manifest':sorted(labels)})
  range_count+=int(' through ' in parsed.section_label)
  chunks=statecivics_statute_markdown_chunks(text,expected_sha256=digest,expected_source_url=url)
  local['indexable_documents']+=bool(chunks)
  local['chunks']+=len(chunks)
  local['chunk_chars']+=sum(len(c.text) for c in chunks)
  for c in chunks:
   require(text[c.char_start:c.char_end]==c.text,'chunk exact character selection')
   require(sha(c.text.encode('utf-8'))==c.metadata['text_hash'],'chunk hash')
  if r['logical_document_id'] in canaries:
   old=canaries[r['logical_document_id']]
   changed=sorted(key for key in old.keys()|r.keys() if old.get(key)!=r.get(key))
   require(changed==['exporter','record_digest_sha256'],f'canary changed unexpected fields {changed}')
   canary_changes.append({'logical_key':logical_key,'changed_fields':changed,'source_revision_id':r['source_revision_id'],'content_hash_sha256':digest})
 for key in ('records','bytes','indexable_documents','chunks','chunk_chars'):
  require(local[key]==chapter[key],f'{name} computed {key} differs {local[key]} {chapter[key]}')
  totals[key]+=local[key]
 chapter_results.append({'chapter':ch,'records':local['records'],'chunks':local['chunks']})
 if len(chapter_results)%10==0:print(f"verified chapters {len(chapter_results)}/85; records {totals['records']}",flush=True)
require(seen_files==set(by_filename),'full manifest file set')
objects=[p for p in Path('/custody/kansas_statutes').rglob('*') if p.is_file()]
require(len(objects)==31079 and {p.name for p in objects}==seen_digests,'namespace object inventory')
require(len(canary_changes)==6,'all canaries compared')
require(history_count==72733 and raw_history_count==72753,'history counts')
for key,value in idx['totals'].items():
 require((len(chapter_results) if key=='tranches' else totals[key])==value,f'computed total {key}')
require(totals['custody_bytes']==66750184,'custody bytes')
# Execute the committed label parser only, with its original regex constants,
# to show whether substring matching rejects a different statute label.
source=Path('/upstream/scripts/operator/register_statute_document_corpus.py').read_text()
tree=ast.parse(source)
selected_nodes=[]
for node in tree.body:
 if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'_H1_RE','_CHAPTER_RE','_ARTICLE_RE','_SOURCE_RE'} for t in node.targets):selected_nodes.append(node)
 if isinstance(node,ast.FunctionDef) and node.name=='_parse_rendered':selected_nodes.append(node)
scope={'re':re,'PlanError':ValueError}
exec(compile(ast.Module(body=selected_nodes,type_ignores=[]),'<committed _parse_rendered>','exec'),scope)
test_text=Path('/corpus/data/ksa/ksa_001_002_0004.md').read_text()
bad_label=scope['_parse_rendered'](test_text,filename='ksa_001_002_0004.md',section_numbers=['1-20'],source_url='https://ksrevisor.gov/statutes/chapters/ch01/001_002_0004.html')
require(bad_label['section_number']=='1-204','substring false-match reproduced')
summary={'result':'PASS_INPUT_BYTES_WITH_NONBLOCKING_LABEL_GUARD_FINDING','input_scope':'all 85 delivered chapter tranches; no live DB/provider/index calls','index_sha256':sha(indexraw),'harvest_manifest_sha256':sha(manifest_raw),'canary_export_sha256':sha(canary_raw),'totals':dict(totals),'tranches':len(chapter_results),'custody_objects':len(objects),'unique_ids':{k:len(v) for k,v in seen_ids.items()},'classifications':dict(classifications),'raw_history_references':raw_history_count,'deduplicated_history_references':history_count,'all_history_unresolved':True,'manifest_range_labels':manifest_range_labels,'rendered_range_labels':range_count,'nonidentical_label_documents':len(label_diffs),'nonidentical_label_examples':label_diffs[:10],'canary_records_compared':canary_changes,'schema_errors':0,'record_digest_mismatches':0,'tranche_hash_or_size_mismatches':0,'exact_custody_corpus_pairs':totals['records'],'exact_chunk_character_selections':totals['chunks'],'substring_guard_accepts_wrong_label':{'actual':'1-204','manifest':'1-20','accepted':True},'elapsed_seconds':round(time.monotonic()-start,2)}
Path('/proof/statute-chapter-export-audit-summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(json.dumps(summary,indent=2,sort_keys=True))

PY
```

</details>

