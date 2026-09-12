# Completed K.S.A. harvest: ExAIS handoff

Recorded from the completed manifest generated at 2026-09-11T03:06:53.360190+00:00
(September 10 in America/Chicago). Read-only corpus review; no acquisition,
custody registration, source activation, vectorization or canonical graph loading.

## Verified inventory and denominators

Corpus: `/Users/mfrieson/Developer/statecivics-statute-corpus/`, outside checkouts.
Manifest: `manifests/statute_scrape_20260911_030653.json`, SHA-256
`17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2`.
The [machine-readable audit](../../../.tranche/statecivics-semantic-graph/aligned/statute-harvest-inventory.json)
records final measurements and duplicate groups.

| Measurement | Raw manifest | Distinct retained documents |
|---|---:|---:|
| Records / Markdown files | 31,085 | 31,079 |
| Documents with parsed history events | 28,618 | 28,612 |
| Parsed history event occurrences | 72,753 | 72,733 |
| Recorded non-null response hashes | 31,079 | One fetched capture per duplicate group |
| Files with official Source URL | — | 31,079 |
| Files with History heading | — | 29,062 |

All 31,079 Markdown files match their manifest rendered SHA-256 and byte length;
their embedded Source URLs agree with the corresponding manifest records.
All 72,733 events after document-group deduplication remain `unresolved`.
These are citation occurrences, not 72,733 resolved or globally unique graph edges.

The manifest reports 91 chapters, 15,907 repealed entries skipped, zero section
failures and 24,562.8 seconds (6.82 hours). This review verifies retained files
against that manifest; it does not independently prove completeness against a
fresh live Revisor enumeration. Markdown logical bytes total 66,750,184; the
manifest is 36,806,911 bytes. The manager's 144 MB directory-size report is a
different measure and is not treated as Markdown content bytes here.

The six repeated groups are 73-201, 73-205, 73-209, 73-213, 73-220 and 73-1221.
Each pair has identical official URL, rendered hash and history content. The
first record has a response hash; the duplicate resume record has null. Those
nulls are not conflicting captures. The malformed TOC labels prepend article
headings; retain the original manifest as evidence and deduplicate the export
with an explicit audit mapping. Preserve the fetched record's non-null response
hash while selecting the clean section label; blindly keeping the last resume
record would discard that capture metadata. They repeat 20 event occurrences. This supports
a bounded upstream TOC normalization/replay fix, not a harvest restart. StateCivics
owns that follow-up; no new KS ticket ID is invented in this consumer handoff.

## Do not use 400 bytes as an ingestion exclusion

The measured 2,863 files at or below 400 bytes are 9.2% of the files. That is a
size bucket, not a count of header-only or unusable statutes.

Two independent full scans, using the actual `statute_to_markdown` renderer
boundaries, agree:

| File size | Nonempty body region | Empty body region |
|---|---:|---:|
| At or below 400 bytes | 667 | 2,196 |
| Above 400 bytes | 28,148 | 68 |
| Total | 28,815 | 2,264 |

A body region is the text after the unique `**Source:**` line and before the
first renderer-owned History, Source or Prior Law, Revisor's Note, Case
Annotations, Attorney General Opinions, or Law Review References heading.
The renderer is upstream
`src/kansas_accountability/etl/existinglaw/statute_parsers.py:statute_to_markdown`.
All files matched the expected source/heading structure in the independent scan.

Concrete counterexamples from retained files:

- `ksa_002_003_0003.md`, 397 bytes: K.S.A. 2-303 contains an actual restriction
  on spending the specified funds for speed premiums.
- `ksa_002_009_0016.md`, 395 bytes: a misdemeanor provision and a $100–$500 penalty.
- `ksa_002_009_0008.md`, 337 bytes: the statutory short title of an act.
- `ksa_060_034_0001.md`, 1,793 bytes: empty body, with history and annotations.
- `ksa_079_015_0064.md`, 1,196 bytes: empty body, with a transfer note and annotations.

This is structural triage, not a new embedding-eligible or legally-current count.
Three nonempty regions contain only misplaced `History:` expiration text; an
empty body can still carry useful historical metadata. Check content and temporal
status, retain short substantive provisions, and keep metadata-only records for
identity/history handling. Do not discard them from custody or erase their
history merely because they are excluded from statute-body embeddings.

## Provenance and retrieval boundary

The retained Markdown hash is independently reproducible. The response hash is
recorded, but no HTML/raw-response artifact is present in this corpus directory.
Upstream `statute_scraper._fetch` returns `resp.text`; its caller hashes
`section_html.encode("utf-8")`. Thus that digest identifies UTF-8 re-encoded
response text, not demonstrably the original HTTP response bytes. Preserve that
distinction in custody/export metadata. This inspection does not establish that
raw captures are absent from every other store.

The complete corpus removes the acquisition wait. It does not supply custody
revisions, approved source/export records, semantic indexes, canonical provisions,
a ledger or reviewed account crosswalks by itself.

For the ExAIS implementation:

1. Consume StateCivics' custody-backed, versioned export; reuse the existing
   exporter/contract owners. Keep this a separate K.S.A. source policy rather
   than relabeling statute Markdown as fiscal PDF extraction.
2. Preserve official section/URL, rendered hash, observation time, exact text
   ranges and ordered history references. Section numbering is a citation label,
   not a substitute for the agreed provision identity.
3. Use section/subsection-aware exact slices with original coordinate mappings.
   These web-derived Markdown files have no physical PDF page markers; the
   fiscal-only `statecivics_page_markdown_v1` profile is not their parser.
4. Retain the agreed Voyage-4/1024 statute embedding choice in the future source
   configuration and verify the actual ingestion plan. No source package or
   embedding-model change is activated by this document.
5. Keep parsed History references unresolved until the cited session-law
   provision and its bill mapping are evidenced. A History reference does not
   itself provide a verified statute → session-law → bill path.
6. Keep the fiscal backbone unchanged: enacted provision → appropriation action
   → fiscal-year account → agency/fund, supported by exact source evidence.
   Migration 111's append-only verification attestations and KS-600/650's
   canonical contracts/export remain independent producer work.

No bulk deletion, 400-byte filter, paid embedding call or source-store activation
was performed. WAVE-132/133/134 remain open for their existing implementation and
real-answer acceptance requirements.

## Reproducible read-only inventory command

Implementation follow-up: [WAVE-137](../../../tickets/WAVE-137-kansas-statute-document-ingestion.md)
now owns the bounded preparation and API consumer, with a separate
[Kansas Statutes source package](../vector-stores/kansas-statutes/README.md).
Its [execution proof](../../../.tranche/statecivics-semantic-graph/aligned/wave-137-implementation-proof.md)
separates local corpus preparation from live custody/export and retrieval proof.
The inventory below remains the earlier read-only audit; it is not the ingestion
command or an activation record.

This uses host Python's standard library only, without project dependencies or
network access. A first draft assumed response hashes were non-null and refused
on the six resume records; the final audit below handles them explicitly. A
History-only body split was also superseded by the complete renderer boundary
definition before these body counts were accepted.

```sh
python3 - <<'PY'
from pathlib import Path
from collections import Counter,defaultdict
import json,hashlib,re
root=Path('/Users/mfrieson/Developer/statecivics-statute-corpus')
m=root/'manifests/statute_scrape_20260911_030653.json'
b=m.read_bytes();manifest=json.loads(b);groups=defaultdict(list)
for row in manifest['documents']: groups[row['filename']].append(row)
counts=Counter();examples={'small_with_body':[],'large_without_body':[]};bad=[]
for name,rows in groups.items():
    path=root/'data/ksa'/name;raw=path.read_bytes();text=raw.decode('utf-8')
    sha=hashlib.sha256(raw).hexdigest();matches=[r for r in rows if r['rendered_sha256']==sha and r['rendered_bytes']==len(raw)]
    if len(matches)!=len(rows): bad.append(name)
    source=re.search(r'^\*\*Source:\*\* (https://ksrevisor\.gov/[^\r\n]+)\n',text,re.M)
    if source is None or any(source.group(1)!=r['source_url'] for r in rows):bad.append('source:'+name)
    body=text[source.end():] if source else ''
    body=re.split(r"^## (?:History|Source or Prior Law|Revisor's Note|Case Annotations|Attorney General Opinions|Law Review References)[ \t]*$",body,maxsplit=1,flags=re.M)[0].strip()
    row=rows[-1]
    counts['files']+=1;counts['markdown_bytes']+=len(raw)
    counts['files_with_official_source_url']+=source is not None
    counts['files_with_history_heading']+=bool(re.search(r'^## History\s*$',text,re.M))
    counts['files_with_parsed_events']+=bool(row.get('history_events'))
    counts['parsed_events']+=len(row.get('history_events',[]))
    counts['unresolved_events']+=sum(e.get('resolution_status')=='unresolved' for e in row.get('history_events',[]))
    counts['files_le400_bytes']+=len(raw)<=400
    counts['files_gt400_bytes']+=len(raw)>400
    counts['files_with_body']+=bool(body);counts['files_without_body']+=not body
    counts['small_with_body']+=bool(body) and len(raw)<=400
    counts['small_without_body']+=not body and len(raw)<=400
    counts['large_with_body']+=bool(body) and len(raw)>400
    counts['large_without_body']+=not body and len(raw)>400
    if body and len(raw)<=400 and len(examples['small_with_body'])<3:examples['small_with_body'].append({'file':name,'bytes':len(raw),'body':body})
    if not body and len(raw)>400 and len(examples['large_without_body'])<3:examples['large_without_body'].append({'file':name,'bytes':len(raw)})
raw_counts={'records':len(manifest['documents']),'response_hashes':sum(bool(re.fullmatch('[0-9a-f]{64}',(r.get('response_sha256') or ''))) for r in manifest['documents']),'records_with_parsed_events':sum(bool(r.get('history_events')) for r in manifest['documents']),'parsed_events':sum(len(r.get('history_events',[])) for r in manifest['documents'])}
duplicates=[{'filename':k,'section_labels':[r['section_number'] for r in v],'same_url':len({r['source_url'] for r in v})==1,'same_rendered_hash':len({r['rendered_sha256'] for r in v})==1,'non_null_response_hashes_agree':len({r['response_sha256'] for r in v if r['response_sha256']})==1,'null_response_hashes':sum(r['response_sha256'] is None for r in v),'repeated_events':sum(len(r.get('history_events',[])) for r in v[1:])} for k,v in groups.items() if len(v)>1]
print(json.dumps({'manifest':str(m),'manifest_sha256':hashlib.sha256(b).hexdigest(),'manifest_bytes':len(b),'harvest_generated_at':manifest['generated_at'],'manifest_reported':{k:manifest[k] for k in ('chapters_scraped','sections_scraped','sections_skipped_repealed','sections_failed','files_written','duration_seconds')},'raw_manifest':raw_counts,'distinct_retained_documents':dict(counts),'mismatches':bad,'duplicate_groups':duplicates,'examples':examples,'body_definition':"Non-whitespace text after the official Source line and before the first renderer-owned History, Source or Prior Law, Revisor's Note, Case Annotations, Attorney General Opinions, or Law Review References heading; not legal validity, substantive eligibility, or extraction completeness QA."},indent=2,ensure_ascii=False))
PY
```

The final command exited 0. Its JSON is retained in the linked audit. Independent
review reproduced the body-size matrix, duplicate groups and event denominators.
This is corpus inventory and document-shape proof, not a rerun of upstream
PostgreSQL gates or an end-to-end GraphRAG result.

Independent [documentation/inventory QC](../../../.tranche/statecivics-semantic-graph/aligned/statute-harvest-handoff-qc.md)
returned PASS WITH NOTES. It verified the full filename set and duplicate/event
denominators, sampled 43 file hash/size/URL bindings, checked the five filter
counterexamples and reviewed the two independently measured body-region scans.
No runtime suite was rerun for this documentation-only update.
