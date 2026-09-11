Decision: PASS WITH NOTES

Ticket reviewed:
- WAVE-132/133 alignment follow-up at ExAIS base `a8ab082`; documentation and inventory only. Existing WAVE-132/133/134 acceptance remains open.

Evidence reviewed:
- Seven changed Markdown files, new [statute handoff](../../../instances/ks-state-civics/research/statute-harvest-handoff.md) and [inventory JSON](statute-harvest-inventory.json).
- Root's retained-file audit and the separate extraction-quality review's body-size scan; this reviewer independently checked manifest counts, duplicates, all retained filenames, 43 file samples and five counterexamples below, not a third full content scan.
- Read-only renderer, scraper, fiscal context/caller, immutable span model and JUnit evidence-gate code. No gate, database reset, runtime suite or network harvest was executed.

Acceptance criteria:
- [pass] Distinguish 31,085 raw manifest rows from exactly 31,079 retained Markdown filenames and six duplicate groups. Deduplicated document history retains 72,733 unresolved occurrences versus 72,753 raw occurrences; these are not asserted resolved or globally unique graph edges.
- [pass] Duplicate groups have identical URL/rendered hash/history, with a non-null first response hash and a null resumed record. Handoff preserves capture metadata rather than blindly keeping the last record.
- [pass] The 400-byte bucket is not an eligibility/header-only classifier. The 667 short nonempty and 68 larger empty-body cases invalidate that shortcut; the stated body matrix is internally consistent and uses actual renderer boundaries. Counts are explicitly structural triage, not legal validity or embedding eligibility.
- [pass] Retained Markdown hashes are distinguished from response text re-encoded as UTF-8. No claim is made that the latter proves original HTTP bytes or that raw captures are absent from every store.
- [pass] Caller finding is closed in code: `context.text` is passed to span registration and the existing context/source/derivation checks bind its hash. The manager's 67-test gate result is attributed and not claimed independently rerun here.
- [pass] Append-only attestations remain an upstream-owned agreed handoff with snapshot applicability; no ExAIS schema/implementation is invented. Database constraints are not misrepresented as proof that verification actually ran.
- [pass] No runtime, schema, source activation, indexing, paid embedding or corpus mutation accompanies the update. Existing historical proofs remain intact. All 93 local link targets/anchors checked resolved; `git diff --check` passed.

Findings:
- No blocking issue. Root corrected one wording detail during review to “67 executed tests through the PostgreSQL evidence gate,” preserving attribution and avoiding an exaggerated execution claim.
- Acquisition completion does not establish freshness/completeness against a new live enumeration, custody/publication eligibility, resolved lineage or functioning GraphRAG. The docs state those limits.

Required fixes before next ticket:
- None for this documentation/inventory increment. Preserve the existing upstream custody/export/attestation and ExAIS implementation/acceptance gates.

## Independent read-only verification

Host standard-library command, exit 0 in 0.29 seconds; no project imports, dependencies or network:

```sh
python3 - <<'PY'
from pathlib import Path
from collections import defaultdict,Counter
import hashlib,json,re
root=Path('/Users/mfrieson/Developer/statecivics-statute-corpus');mp=root/'manifests/statute_scrape_20260911_030653.json';raw=mp.read_bytes();m=json.loads(raw)
assert hashlib.sha256(raw).hexdigest()=='17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2'
groups=defaultdict(list)
for row in m['documents']:groups[row['filename']].append(row)
files={p.name for p in (root/'data/ksa').glob('*.md')};assert files==set(groups)
dups=[v for v in groups.values() if len(v)>1]
assert len(dups)==6 and all(len(v)==2 for v in dups)
for rows in dups:
 assert len({r['source_url'] for r in rows})==len({r['rendered_sha256'] for r in rows})==1
 assert rows[0]['history_events']==rows[1]['history_events']
 assert rows[0]['response_sha256'] and rows[1]['response_sha256'] is None
raw_events=sum(len(r.get('history_events',[])) for r in m['documents']);dedup_events=sum(len(v[-1].get('history_events',[])) for v in groups.values())
assert raw_events==72753 and dedup_events==72733
assert all(e['resolution_status']=='unresolved' for v in groups.values() for e in v[-1].get('history_events',[]))
selected=set(sorted(files)[::997])|{v[0]['filename'] for v in dups}|{'ksa_002_003_0003.md','ksa_002_009_0016.md','ksa_002_009_0008.md','ksa_060_034_0001.md','ksa_079_015_0064.md'}
for name in selected:
 b=(root/'data/ksa'/name).read_bytes();t=b.decode();r=groups[name][0]
 assert hashlib.sha256(b).hexdigest()==r['rendered_sha256'] and len(b)==r['rendered_bytes']
 source=re.search(r'^\*\*Source:\*\* (https://ksrevisor\.gov/[^\r\n]+)\n',t,re.M);assert source and source.group(1)==r['source_url']
for name,expected in [('ksa_002_003_0003.md',True),('ksa_002_009_0016.md',True),('ksa_002_009_0008.md',True),('ksa_060_034_0001.md',False),('ksa_079_015_0064.md',False)]:
 t=(root/'data/ksa'/name).read_text();body=t.split('**Source:** ',1)[1].split('\n',1)[1]
 body=re.split(r"^## (?:History|Source or Prior Law|Revisor's Note|Case Annotations|Attorney General Opinions|Law Review References)[ \t]*$",body,maxsplit=1,flags=re.M)[0].strip()
 assert bool(body)==expected
print(json.dumps({'manifest_hash_verified':True,'retained_filenames_match_manifest':len(files),'raw_manifest_rows':len(m['documents']),'duplicate_groups':len(dups),'raw_events':raw_events,'document_deduplicated_events':dedup_events,'all_deduplicated_events_unresolved':True,'independent_hash_size_url_samples':len(selected),'size_filter_counterexamples_verified':5}))
PY
```

Observed:

```json
{"manifest_hash_verified": true, "retained_filenames_match_manifest": 31079, "raw_manifest_rows": 31085, "duplicate_groups": 6, "raw_events": 72753, "document_deduplicated_events": 72733, "all_deduplicated_events_unresolved": true, "independent_hash_size_url_samples": 43, "size_filter_counterexamples_verified": 5}
```

Audit JSON arithmetic independently reconciles 28,815 nonempty bodies plus 2,264 empty bodies to 31,079 files, including both size buckets. Full-scan body counts remain attributed to the root and separate extraction-quality audits.

Only this QC artifact was written by this reviewer. No code, corpus, upstream, database, historical proof or commit was changed.
