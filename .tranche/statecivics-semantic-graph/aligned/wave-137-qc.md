Decision: PASS WITH NOTES

Ticket reviewed:
- `tickets/WAVE-137-kansas-statute-document-ingestion.md`, bounded statute document preparation/ingestion implementation only.
- Worktree `/Users/mfrieson/Developer/exais-vector-store-law-money`, branch `feat/statecivics-law-money-projection`, base `16a92d8b777574a855cd297bb9e3763c9859710b`.

Evidence reviewed:
- All working-tree changes against the base, including new untracked implementation/tests, source package and proof files. The twelve runtime/test files match the ticket's serial ownership list. Root-owned declarations, ticket/parent links, handoff and build-contract/index addendum match this separately authorized increment.
- `wave-137-implementation-proof.md`, `wave-137-statute-preflight.json`, `wave-137-regression-summary.json`, and the actual retained JUnit report.
- Independent commands and results below. No implementation or upstream files were modified, no live service or paid provider was called, and corpus mounts were read-only. Only this QC report is written persistently by this review.

Acceptance criteria:
- [pass] All 31,079 retained files are exercised. Manifest/file hashes, byte counts, official URLs, paths and duplicate reconciliation pass; six exact duplicate groups preserve the non-null response capture. Counts remain 72,753 raw and 72,733 document-deduplicated unresolved history occurrences.
- [pass] Structural nonempty bodies remain 28,815; semantic classification distinguishes 28,812 substantive bodies, 2,264 empty bodies and three inline History-only records. Short substantive statutes survive without a byte-size eligibility filter.
- [pass] Independent coverage checks all 83,258 emitted chunks and 77,300 body/metadata regions. Every chunk selects its exact original substring, its text hash and LF/Unicode coordinates agree, and no non-whitespace is omitted within included regions. The two retained files containing CR preserve it. No PDF page or canonical legal identity is fabricated.
- [pass] Explicit statute family, collection and text-profile dispatch preserves the fiscal default and rejects ambiguous page/text profiles. Strict Voyage-4/1024 selection refuses unavailable, incompatible or privacy-disallowed configuration rather than falling back.
- [pass] The existing approved export and custody path remains authoritative for eligibility. The consumer joins by exact official URL/rendered hash and carries unresolved harvest metadata without changing upstream record digests. Invalid custody/join data fails before API effects.
- [pass] Nonpersistent server preview confirms the requested chunker and embedding profile before ingest or applied-state advancement. Tests reject unsupported responses. Excluded content uses the existing removal path for an earlier searchable version.
- [pass] Actual PostgreSQL selector execution confirms model/profile migration, changed evidence/history, unchanged dedupe, incomplete-index retry and scope isolation. Changed evidence retains document identity while requiring a new version. HTTP, provider, persistence-parameter and index doubles are accurately identified as such in the proof.
- [pass] The new source package validates but remains `productionReady: false`, with pending live store/export proof and graph disabled. No subsequent canonical GraphRAG implementation or activation was started.

Findings:
- No blocking defects found in this increment.
- Passing preparation/selector/wiring checks establishes an implementable document consumer, not a deployed statute index or successful real answer. Live custody-backed export delivery, deployment, provider/index execution and retrieval recall remain pending.
- The captured response hash describes decoded response text re-encoded as UTF-8. It does not prove retained raw HTTP bytes or a local HTML-to-Markdown derivation; declarations preserve this distinction.
- Source region labels and ordered unresolved History references remain retrieval metadata. They do not establish provision identity, resolved legal edges, current-law status or verified canonical support.

Required fixes before next ticket:
- None for accepting this bounded implementation. Preserve the existing live export/deployment and canonical integration gates; WAVE-132 and the full WAVE-133–136 GraphRAG work are not completed by this verdict.

## Independent verification commands

All Docker commands used the existing local API image
`sha256:181a0c365c2c056014c1366d772d69e815b36b8bbd486ee24bad1318b8d27f19`
with network disabled and bounded CPU/memory.

### Focused tests

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro -v /Users/mfrieson/Developer/statecivics-statute-corpus:/statutes:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent -e SVS_STATUTE_CORPUS_ROOT=/statutes localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python -m pytest -q -rs --tb=short -p no:cacheprovider tests/test_statecivics_statutes.py tests/test_kansas_statute_ingest.py tests/test_ingestion_page_coordinates.py tests/test_ingestion_metadata_refresh.py tests/test_vectorization_plan.py tests/test_instance_source_packages.py
```

Result: **113 passed, zero skipped, exit 0, 17.48 seconds**. This includes the full retained-harvest preflight, real short/long/CR-containing statutes, negative controls, strict routing, API-call wiring and metadata refresh. It does not invoke real HTTP/provider/index services.

### Actual PostgreSQL selectors

Executed the proof's retained Python code against the supplied disposable PostgreSQL 16 server `exais-w137-pg-mtweu993`, using a separately named temporary schema. The code creates and drops that schema in its transaction. Only the isolated database test fixtures are written.

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro -v /Users/mfrieson/Developer/statecivics-statute-corpus:/statutes:ro -v exais-w137-socket-mtweu993:/pgsocket -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python -c 'from pathlib import Path; p=Path(".tranche/statecivics-semantic-graph/aligned/wave-137-implementation-proof.md").read_text(); s=p.split("```python\n",1)[1].split("```",1)[0]; exec(compile(s.replace("statute_probe", "statute_independent_qc"),"retained-proof-selector-qc","exec"))'
```

Result: **39 assertions passed, exit 0**. The actual selector SQL verifies old profile/model migration, complete replay, six evidence-field changes, ordered history changes, absent/null/empty distinction, unrelated metadata, tenant/business/knowledge-base/store/source isolation, changed bytes and failed-index retry. The input document hash is `5501388fc2e8da55cef32d49d15e7f5f14c0b20341d43e9f46d8c4cb381c7d02`. This is minimal-schema selector proof, not full migration or deployed API proof.

### Independent corpus coverage and retained regression report

```sh
docker run --rm -i --platform linux/amd64 --network none --memory 2g --cpus 2 -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro -v /Users/mfrieson/Developer/statecivics-statute-corpus:/statutes:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python - <<'PY'
from pathlib import Path
from collections import Counter
import hashlib,json,xml.etree.ElementTree as ET
from svs_common.statecivics_statutes import parse_statute_markdown,statecivics_statute_markdown_chunks
counts=Counter()
for path in sorted(Path('/statutes/data/ksa').glob('*.md')):
    raw=path.read_bytes(); original=raw.decode('utf-8'); digest=hashlib.sha256(raw).hexdigest()
    parsed=parse_statute_markdown(original,expected_sha256=digest)
    chunks=statecivics_statute_markdown_chunks(original,expected_sha256=digest)
    counts['documents']+=1; counts[parsed.classification]+=1; counts['chunks']+=len(chunks)
    if '\r' in original: counts['documents_containing_cr']+=1
    if parsed.classification!='substantive_body':
        assert not chunks,path
        continue
    regions=[('statute_body',parsed.body_start,parsed.body_end),*parsed.metadata_regions]
    for role,start,end in regions:
        selected=[c for c in chunks if c.metadata['statute_region']==role]
        cursor=start
        for chunk in sorted(selected,key=lambda c:c.char_start):
            assert start <= chunk.char_start < chunk.char_end <= end,(path,role)
            assert not original[cursor:chunk.char_start].strip(),(path,'uncovered non-whitespace',cursor,chunk.char_start)
            cursor=max(cursor,chunk.char_end)
            assert original[chunk.char_start:chunk.char_end]==chunk.text,(path,'slice')
            assert hashlib.sha256(chunk.text.encode('utf-8')).hexdigest()==chunk.metadata['text_hash']
            assert original.count('\n',0,chunk.char_start)+1==chunk.metadata['line_start']
            assert original.count('\n',0,chunk.char_end-1)+1==chunk.metadata['line_end']
            assert chunk.page_start is None and chunk.page_end is None
            assert not {'provision_id','section_id','appropriation_action_id','effective_date','resolved_history_edges'} & chunk.metadata.keys()
        assert not original[cursor:end].strip(),(path,'uncovered tail',cursor,end)
        counts['regions_fully_covered']+=1
assert counts['documents']==31079 and counts['chunks']==83258,counts
report=Path('.release/cells/ks-state-civics/kansas-statutes/qc/wave-137-regression.xml')
assert hashlib.sha256(report.read_bytes()).hexdigest()=='66564e1eef5f8d64d421892ba90a6abc6c52453f48e8e0afab79cf348026fda8'
cases=ET.fromstring(report.read_bytes()).findall('.//testcase')
assert len(cases)==561 and all(not any(c.find(tag) is not None for tag in ('skipped','failure','error')) for c in cases)
print(json.dumps({'independent_exact_slice_coverage':dict(counts),'root_junit_verified_cases':len(cases),'network_requests':0,'persistent_writes':0},sort_keys=True))
PY
```

Result: **exit 0**:

```json
{"independent_exact_slice_coverage":{"chunks":83258,"documents":31079,"documents_containing_cr":2,"empty_body":2264,"inline_history_only":3,"regions_fully_covered":77300,"substantive_body":28812},"network_requests":0,"persistent_writes":0,"root_junit_verified_cases":561}
```

The root broad regression was not redundantly re-run. Its actual report hash
`66564e1eef5f8d64d421892ba90a6abc6c52453f48e8e0afab79cf348026fda8`
and all **561** cases were independently verified, with no skipped, failed or errored cases.

### Declaration validation and diff hygiene

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python scripts/release/validate-instance-source-packages.py --instance ks-state-civics --vector-store kansas-statutes --production --json
git diff --check
git rev-parse HEAD
```

Results: source declaration **one package, zero issues, exit 0**; diff check clean; HEAD matches the stated base. The validator's `--production` flag is a declaration check, not an activation or production-readiness assertion.
