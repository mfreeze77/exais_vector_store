# WAVE-134 retained document coordinates — implementation proof

Date: 2026-09-10. Base: `86bf4b3`.
Worktree: `/Users/mfrieson/Developer/exais-vector-store-law-money`.
Scope: the explicitly opted-in StateCivics retained-Markdown coordinate path,
including preview, ingestion and profile-aware replay. Canonical entity/graph
integration, live reindexing and paid bulk ingestion remain separate.

## Ownership and identity

The owner prioritized Tier 2 using existing chunk columns. The exact allowed
runtime/test files are listed in `build-contract.json:document_coordinate_increment`
and `stack.index.json`, owned by T-005 / WAVE-134. KS-600/650 are not inputs to this
bounded document-parser path; their requirements still gate the canonical
projection work. No upstream schema or canonical legal reference is invented.

A chunk remains retrieval context. Reviewed exact span-to-action bindings
identify which legal operation a passage supports. Section 96(i) and 96(j)
can coexist in a chunk; no action IDs or edges are inferred by this parser.

## Executed PostgreSQL selection proof

Root ran the actual `IngestionService._find_exact_duplicate` and
`_find_version_target` SQL against a newly created PostgreSQL 16 container
using a minimal isolated schema. This is selection/replay proof, not a fully
migrated service, RLS certification, provider/index test or production mutation.
Both containers had network disabled, with only a shared named Unix-socket
volume; the PostgreSQL data directory was tmpfs and no host port was published.

Server setup used the existing `postgres:16-alpine` image:

```sh
docker run --detach --rm --name exais-w134-pg-mtwa4o19 \
  --network none --memory 512m --cpus 1 \
  --mount type=volume,source=exais-w134-socket-mtwa4o19,target=/var/run/postgresql \
  --tmpfs /var/lib/postgresql/data:rw,size=256m \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16-alpine -c shared_buffers=32MB
docker exec exais-w134-pg-mtwa4o19 pg_isready -U postgres
```

Readiness returned accepting connections. Disposable local trust authentication
applied only inside this isolated test setup.

The first execution exposed an incomplete-ingest retry defect: a same-source,
same-byte document already on the new profile failed exact dedupe but also had
no version target. The worker corrected that opt-in branch before acceptance.
Complete requests still return through exact dedupe; incomplete repeats reuse
the existing exact source identity. Legacy changed-content selection remains.

Final executed command:

```sh
docker run --rm -i --platform linux/amd64 --network none --memory 2g --cpus 2 --mount type=volume,source=exais-w134-socket-mtwa4o19,target=/pgsocket -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python - <<'PY'
import hashlib,json
from sqlalchemy import create_engine,text
from svs_common.ingestion import IngestionService, _document_version_metadata
from svs_common.schemas import DocumentIngestRequest,Principal
profile='statecivics_page_markdown_v1'
content='<!-- page 1 -->\nquote\n'
digest=hashlib.sha256(content.encode()).hexdigest()
engine=create_engine('postgresql+psycopg://postgres@/postgres?host=/pgsocket')
service=object.__new__(IngestionService)
principal=Principal(tenant_id='tenant-proof',business_instance_id='biz-proof',max_security_level=5)
def request(identity='source-A',opt=True):
    attrs={'source_page_chunking_profile':profile,'source_collection':'statecivics-kansas-fiscal-documents','extraction_content_hash_sha256':digest,'source_revision_id':'revision-old','citation_url':'https://example.invalid/original.pdf'} if opt else {}
    return DocumentIngestRequest(vector_store_id='vs-proof',knowledge_base_id='kb-proof',title='isolated SQL proof',filename='proof.md',mime_type='text/markdown',content=content,mode='markdown_docs_v1',source_identity=identity,attributes=attrs)
with engine.begin() as db:
    db.execute(text('CREATE SCHEMA coordinate_probe'))
    db.execute(text('SET LOCAL search_path TO coordinate_probe'))
    db.execute(text("CREATE TABLE documents(id text,tenant_id text,business_instance_id text,knowledge_base_id text,vector_store_id text,content_hash text,status text,current_version_id text,source_uri text,filename text,created_at timestamptz DEFAULT now())"))
    db.execute(text("CREATE TABLE document_versions(id text,document_id text,tenant_id text,business_instance_id text,metadata jsonb,status text,chunking_profile_id text)"))
    db.execute(text("CREATE TABLE chunks(document_id text,document_version_id text,tenant_id text,business_instance_id text,active boolean,dense_index_status text,sparse_index_status text)"))
    for suffix,identity in [('a','source-A'),('b','source-B')]:
        values={'doc':'doc-'+suffix,'ver':'ver-'+suffix,'digest':digest,'meta':json.dumps({'source_identity':identity})}
        db.execute(text("INSERT INTO documents(id,tenant_id,business_instance_id,knowledge_base_id,vector_store_id,content_hash,status,current_version_id) VALUES(:doc,'tenant-proof','biz-proof','kb-proof','vs-proof',:digest,'active',:ver)"),values)
        db.execute(text("INSERT INTO document_versions VALUES(:ver,:doc,'tenant-proof','biz-proof',CAST(:meta AS jsonb),'indexed','markdown_heading_hierarchy_v2')"),values)
        db.execute(text("INSERT INTO chunks VALUES(:doc,:ver,'tenant-proof','biz-proof',true,'indexed','indexed')"),values)
    assert service._find_exact_duplicate(db,principal,request(opt=False),digest)['id']=='doc-a'
    assert service._find_exact_duplicate(db,principal,request(),digest) is None
    assert service._find_version_target(db,principal,request(),digest)['id']=='doc-a'
    assert service._find_version_target(db,principal,request('source-C'),digest) is None
    other=principal.model_copy(update={'tenant_id':'other-tenant'})
    assert service._find_version_target(db,other,request(),digest) is None
    db.execute(text("UPDATE document_versions SET chunking_profile_id=:profile, metadata=CAST(:metadata AS jsonb) WHERE id='ver-a'"),{'profile':profile,'metadata':json.dumps(_document_version_metadata(request(),'markdown_docs_v1'))})
    assert service._find_exact_duplicate(db,principal,request(),digest)['id']=='doc-a'
    assert service._find_version_target(db,principal,request(),'f'*64)['id']=='doc-a'
    for field,value in [('source_revision_id','revision-new'),('citation_url','https://example.invalid/revised.pdf'),('extraction_revision_id','extraction-new'),('source_page_count',1)]:
        changed=request()
        changed.attributes={**changed.attributes,field:value}
        assert service._find_exact_duplicate(db,principal,changed,digest) is None,field
        assert service._find_version_target(db,principal,changed,digest)['id']=='doc-a',field
    unrelated=request()
    unrelated.attributes={**unrelated.attributes,'operator_note':'not source evidence'}
    assert service._find_exact_duplicate(db,principal,unrelated,digest)['id']=='doc-a'
    db.execute(text("UPDATE chunks SET dense_index_status='failed' WHERE document_id='doc-a'"))
    assert service._find_exact_duplicate(db,principal,request(),digest) is None
    retry=service._find_version_target(db,principal,request(),digest)
    assert retry and retry['id']=='doc-a'
    print(json.dumps({'database':'disposable PostgreSQL16, minimal isolated schema','legacy_same_bytes_dedupe':True,'old_profile_not_silently_reused':True,'same_source_same_bytes_profile_migration':True,'other_source_and_tenant_excluded':True,'new_profile_repeat_dedupe':True,'changed_bytes_reuses_source_identity':True,'incomplete_new_profile_retry_target':dict(retry) if retry else None,'changed_revision_citation_extraction_and_count_rebuild_same_source':True,'unrelated_metadata_preserves_dedupe':True,'provider_requests':0},sort_keys=True))
    db.execute(text('DROP SCHEMA coordinate_probe CASCADE'))
engine.dispose()
PY
```

Final result after the review corrections: exit 0 in 0.99 seconds. Confirmed:

- Existing legacy same-byte requests still deduplicate.
- A requested coordinate profile cannot silently reuse the old chunk profile.
- Same-source/same-byte profile migration targets the existing document.
- Other source identities and another tenant cannot match that target.
- A completed new-profile request deduplicates without another version.
- Changed source revision, citation URL, extraction revision or declared page
  count refuses dedupe and creates a new version of the same source document.
- Unrelated operator metadata does not force a rebuild.
- Changed bytes retain the same source identity.
- An incomplete same-profile/same-byte retry targets `doc-a / ver-a`,
  rather than creating a second document identity.
- Zero provider requests and no operational database access.

After the final root and independent probes, root stopped
`exais-w134-pg-mtwa4o19` (created with `--rm`) and removed
`exais-w134-socket-mtwa4o19`. Both commands exited 0; filtered container and
volume listings then returned no matches. The disposable test resources remain
described above solely to reproduce the proof.

## Real corpus and regression

Worker's final focused container check returned **106 passed, zero skipped, two existing
warnings, 4.60 seconds**. It used the same image/environment below, mounting only
the worktree and Session Laws, and selected:

```text
tests/test_statecivics_page_chunking.py tests/test_ingestion_page_coordinates.py
tests/test_ingestion_metadata_refresh.py tests/test_kansas_fiscal_document_ingest.py
tests/test_vectorization_plan.py tests/test_chunking.py tests/test_router.py
tests/test_documents_ingest.py
```

Root's combined regression command:

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro -v /Users/mfrieson/Developer/statecivics-kanview-corpus:/corpus:ro -v /Users/mfrieson/Developer/statecivics-custody:/custody:ro -v /Users/mfrieson/Developer/statecivics-ks599-cpu-output/session-laws:/session-laws:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent -e SVS_FISCAL_CORPUS_ROOT=/corpus -e SVS_FISCAL_CUSTODY_ROOT=/custody -e SVS_FISCAL_SESSION_LAWS_ROOT=/session-laws localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python -m pytest -q -rs --tb=short -p no:cacheprovider tests/test_statecivics_page_chunking.py tests/test_ingestion_page_coordinates.py tests/test_ingestion_metadata_refresh.py tests/test_kansas_fiscal_document_ingest.py tests/test_vectorization_plan.py tests/test_chunking.py tests/test_code_chunker.py tests/test_structured_and_logs_chunkers.py tests/test_router.py tests/test_fiscal_document_evidence.py tests/test_fiscal_projection_contract.py tests/test_fiscal_structured_evidence.py tests/test_fiscal_graph.py tests/test_fiscal_graph_artifact.py tests/test_fiscal_graph_routes.py tests/test_fiscal_real_corpus.py tests/test_openapi_contract.py tests/test_grant_cell_graph.py
```

Observed **490 passed, zero skipped, three existing deprecation warnings,
15.35 seconds**, exit 0. This includes the prior 379-test graph/evidence selection
and the relevant ingestion, parser, router and compatibility checks. The focused
and combined runs overlap; their counts are not additive.

The retained-source tests verify extraction hashes from the independent manifest,
every emitted chunk's exact source slice/hash, page and enclosing-line mapping,
complete non-whitespace coverage of text-bearing pages, and no fabricated chunks
for blank pages. No filename heading or canonical action reference is inferred.

| Book | Chunks | Nonempty pages |
|---|---:|---:|
| 2023 B1 | 895 | 890 |
| 2023 B2 | 963 | 936 |
| 2024 B1 | 897 | 892 |
| 2024 B2 | 901 | 893 |
| 2024 B3 | 863 | 826 |
| 2025 B1 | 1,071 | 1,066 |
| 2025 B2 | 1,095 | 1,071 |

Total: **6,685 chunks**, 6,574 text-bearing pages, 13 blank marked pages and
seven explicitly unpaginated prefixes. Book 2's $4M clause appears in one
page-358 chunk (ordinal 359), absolute code points `[984508,987254)`, enclosing
page-local lines 2–49. Its exact supporting span remains `[986097,986411)` and
lines 31–35, quote hash
`3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6`.
The neighboring $156,085,651 clause also appears in that chunk: the broader
chunk's hash is deliberately not substituted for the specific citation hash.

The pipeline tests execute ingestion with no-network provider/index/storage
doubles and inspect the actual SQL insert parameters for existing page/character
columns, metadata and selected profile. This establishes parameter propagation;
it is not a live API/Qdrant/object-store integration or a deployed query result.

Bounds: 16 MiB UTF-8 per extraction, 10,000 pages, one million LF characters,
100,000 words per region, 20,000 chunks, 4,096 characters per chunk and bounded
approximate token/overlap settings. Original whitespace and Unicode are retained.

## Independent review and limits

The first independent [QC](wave-134-document-coordinate-qc.md) returned **FAIL**
despite the passing focused tests. It identified two missing cases: an older
server could ignore the new attribute while the CLI recorded the profile as
applied, and same-byte dedupe could retain old chunk revision/citation metadata
after the request's evidence context changed.

Both defects were corrected before the final test runs above. Opted-in upserts
now submit the identical document request with `persist=false` to the existing
ingestion preview endpoint and require its computed profile, mode and bounded
positive chunk count before ingestion. Legacy, missing, mismatched or failed
preview results cannot advance ingestion or operator state. Profile-aware dedupe
now compares the exact evidence context stored on the document version, including
absent fields; a shared whitelist also governs copying those fields to chunks.
Changed evidence context requires a new version, while unchanged context still
deduplicates without a provider call.

The [second independent QC](wave-134-document-coordinate-qc-2.md) returned
**PASS WITH NOTES** for this bounded increment: 106 tests passed, zero skipped,
4.63 seconds. Its separate PostgreSQL checks exercised changed, missing and null
evidence fields, unchanged/unrelated metadata, legacy behavior, retry and scope
separation. No further runtime fix is required for this increment. The first FAIL
is retained as an audit record; full canonical graph integration remains open.

The manager-reported 13,181 existing live chunks have
not been queried or backfilled by this implementation proof. A reviewed manifest,
deployment and explicit replay/apply remain necessary to change that live index.
Current upstream custody/QA/publication prerequisites still apply.
