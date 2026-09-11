# WAVE-137 implementation proof

Status: bounded implementation verified; independent QC PASS WITH NOTES. This file records executed proof; it does not establish a live statute index.

## Source package

Executed the existing source-package validator for `ks-state-civics/kansas-statutes` with `--production --json`: one package, zero issues, exit 0. The flag checks declaration rules. The source itself remains `productionReady: false`, with pending store/export IDs and graph disabled.

## Actual PostgreSQL selectors

Executed the actual `IngestionService` duplicate/version-target queries in a disposable PostgreSQL 16 database with a minimal isolated schema. This is selector proof, not full migrated-schema or provider/index proof. The input bytes were retained K.S.A. 2-303 (`5501388fc2e8da55cef32d49d15e7f5f14c0b20341d43e9f46d8c4cb381c7d02`); the database rows and history-change cases are isolated test fixtures, not published civic facts.

Result: **39 assertions passed**, exit 0. Covered legacy behavior, source identity during profile/model migration, unchanged replay, changes to six evidence fields, nested ordered history, absent versus null/empty evidence, unrelated metadata, tenant/business/knowledge-base/store/source isolation, changed bytes, and incomplete index retry. No operational database, model provider, or retrieval index was accessed.

The server had no network and no exposed port, used tmpfs data and a task-specific Unix socket volume. A read-only API image client mounted that socket and the worktree/corpus. PostgreSQL image: `postgres:16-alpine`, local image `sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685`. Client image: `localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575`, local image `sha256:181a0c365c2c056014c1366d772d69e815b36b8bbd486ee24bad1318b8d27f19`.

Reproduce by creating a disposable PostgreSQL 16 with a Unix socket mounted as `/pgsocket` in that client, read-only source tree as `/work`, retained corpus as `/statutes`, and `PYTHONPATH=/work/packages/svs_common`, then execute:

```python
import hashlib,json
from pathlib import Path
from sqlalchemy import create_engine,text
from svs_common.ingestion import IngestionService, _document_version_metadata
from svs_common.schemas import DocumentIngestRequest,Principal
from svs_common.statecivics_statutes import STATECIVICS_STATUTE_MARKDOWN_PROFILE as PROFILE, STATUTE_EMBEDDING_PROFILE as EMBEDDING

content=Path('/statutes/data/ksa/ksa_002_003_0003.md').read_bytes().decode('utf-8')
digest=hashlib.sha256(content.encode()).hexdigest()
engine=create_engine('postgresql+psycopg://postgres@/postgres?host=/pgsocket')
service=object.__new__(IngestionService)
principal=Principal(tenant_id='tenant-proof',business_instance_id='biz-proof',max_security_level=5)
def request(identity='source-A',opt=True):
    attrs={'source_text_chunking_profile':PROFILE,'source_collection':'statecivics-kansas-statutes',
           'extraction_content_hash_sha256':digest,'source_revision_id':'revision-old',
           'citation_url':'https://ksrevisor.gov/statutes/chapters/ch02/002_003_0003.html',
           'statute_harvest_evidence':{'section_number':'2-303','history_events':[{'ordinal':1,'year':1927,'chapter':'7','section':'1','citation_text':'proof history','resolution_status':'unresolved'}]}} if opt else {}
    return DocumentIngestRequest(vector_store_id='vs-proof',knowledge_base_id='kb-proof',title='isolated SQL proof',filename='ksa_002_003_0003.md',mime_type='text/markdown',content=content,mode='markdown_docs_v1',source_identity=identity,attributes=attrs)
checks=[]
def expect(value,name):
    assert value,name
    checks.append(name)
with engine.begin() as db:
    db.execute(text('CREATE SCHEMA statute_probe'))
    db.execute(text('SET LOCAL search_path TO statute_probe'))
    db.execute(text("CREATE TABLE documents(id text,tenant_id text,business_instance_id text,knowledge_base_id text,vector_store_id text,content_hash text,status text,current_version_id text,source_uri text,filename text,created_at timestamptz DEFAULT now())"))
    db.execute(text("CREATE TABLE document_versions(id text,document_id text,tenant_id text,business_instance_id text,metadata jsonb,status text,chunking_profile_id text,embedding_profile_id text)"))
    db.execute(text("CREATE TABLE chunks(document_id text,document_version_id text,tenant_id text,business_instance_id text,active boolean,dense_index_status text,sparse_index_status text)"))
    for suffix,identity in [('a','source-A'),('b','source-B')]:
        values={'doc':'doc-'+suffix,'ver':'ver-'+suffix,'digest':digest,'meta':json.dumps({'source_identity':identity})}
        db.execute(text("INSERT INTO documents(id,tenant_id,business_instance_id,knowledge_base_id,vector_store_id,content_hash,status,current_version_id) VALUES(:doc,'tenant-proof','biz-proof','kb-proof','vs-proof',:digest,'active',:ver)"),values)
        db.execute(text("INSERT INTO document_versions VALUES(:ver,:doc,'tenant-proof','biz-proof',CAST(:meta AS jsonb),'indexed','markdown_heading_hierarchy_v2','embedding_local_dev')"),values)
        db.execute(text("INSERT INTO chunks VALUES(:doc,:ver,'tenant-proof','biz-proof',true,'indexed','indexed')"),values)
    expect(service._find_exact_duplicate(db,principal,request(opt=False),digest)['id']=='doc-a','legacy same-byte replay retained')
    expect(service._find_exact_duplicate(db,principal,request(),digest) is None,'legacy profile cannot satisfy statute replay')
    expect(service._find_version_target(db,principal,request(),digest)['id']=='doc-a','profile migration retains source identity')
    def set_metadata(req):
        db.execute(text("UPDATE document_versions SET metadata=CAST(:metadata AS jsonb) WHERE id='ver-a'"),{'metadata':json.dumps(_document_version_metadata(req,'markdown_docs_v1'))})
    db.execute(text("UPDATE document_versions SET chunking_profile_id=:profile, embedding_profile_id=:embedding WHERE id='ver-a'"),{'profile':PROFILE,'embedding':EMBEDDING})
    set_metadata(request())
    expect(service._find_exact_duplicate(db,principal,request(),digest)['id']=='doc-a','statute unchanged replay deduplicates')
    for field,value in [('source_revision_id','revision-new'),('citation_url','https://ksrevisor.gov/statutes/chapters/ch02/002_003_0004.html'),('extraction_revision_id','extraction-new'),('extraction_content_hash_sha256','e'*64),('source_content_hash_sha256','f'*64),('logical_document_id','logical-new')]:
        changed=request()
        changed.attributes={**changed.attributes,field:value}
        expect(service._find_exact_duplicate(db,principal,changed,digest) is None,'changed '+field+' rebuilds')
        expect(service._find_version_target(db,principal,changed,digest)['id']=='doc-a','changed '+field+' retains source identity')
    changed=request()
    changed.attributes['statute_harvest_evidence']['history_events'][0]['year']=1928
    expect(service._find_exact_duplicate(db,principal,changed,digest) is None,'changed ordered history rebuilds')
    expect(service._find_version_target(db,principal,changed,digest)['id']=='doc-a','changed ordered history retains source identity')
    for value in [None,{},[]]:
        changed=request()
        changed.attributes['extraction_revision_id']=value
        expect(service._find_exact_duplicate(db,principal,changed,digest) is None,'absent evidence distinct from '+repr(value))
    with_null=request()
    with_null.attributes['extraction_revision_id']=None
    set_metadata(with_null)
    expect(service._find_exact_duplicate(db,principal,with_null,digest)['id']=='doc-a','matching explicit null deduplicates')
    expect(service._find_exact_duplicate(db,principal,request(),digest) is None,'stored null distinct from request absence')
    set_metadata(request())
    unrelated=request()
    unrelated.attributes['operator_note']='not source evidence'
    expect(service._find_exact_duplicate(db,principal,unrelated,digest)['id']=='doc-a','unrelated metadata preserves dedupe')
    db.execute(text("UPDATE document_versions SET embedding_profile_id='openai_3_small_1536' WHERE id='ver-a'"))
    expect(service._find_exact_duplicate(db,principal,request(),digest) is None,'wrong model cannot satisfy statute replay')
    expect(service._find_version_target(db,principal,request(),digest)['id']=='doc-a','model migration retains source identity')
    db.execute(text("UPDATE document_versions SET embedding_profile_id=:embedding WHERE id='ver-a'"),{'embedding':EMBEDDING})
    for key,value in [('tenant_id','other-tenant'),('business_instance_id','other-business')]:
        other=principal.model_copy(update={key:value})
        expect(service._find_exact_duplicate(db,other,request(),digest) is None,key+' duplicate isolation')
        expect(service._find_version_target(db,other,request(),digest) is None,key+' version isolation')
    for key,value in [('knowledge_base_id','other-kb'),('vector_store_id','other-store'),('source_identity','source-C')]:
        other=request().model_copy(update={key:value})
        expect(service._find_exact_duplicate(db,principal,other,digest) is None,key+' duplicate isolation')
        expect(service._find_version_target(db,principal,other,digest) is None,key+' version isolation')
    expect(service._find_version_target(db,principal,request(),'f'*64)['id']=='doc-a','changed bytes reuse source identity')
    db.execute(text("UPDATE chunks SET dense_index_status='failed' WHERE document_id='doc-a'"))
    expect(service._find_exact_duplicate(db,principal,request(),digest) is None,'incomplete index does not deduplicate')
    expect(service._find_version_target(db,principal,request(),digest)['id']=='doc-a','incomplete retry retains source identity')
    db.execute(text('DROP SCHEMA statute_probe CASCADE'))
engine.dispose()
print(json.dumps({'kind':'wave-137-disposable-postgresql-selector-proof','database':'PostgreSQL 16; minimal isolated schema, not full migration proof','checks_passed':len(checks),'checks':checks,'real_document_sha256':digest,'provider_requests':0,'operational_database_touched':False},sort_keys=True,indent=2))

```

## Full-corpus preparation and regression

The new CLI completed against the retained corpus with exit 0. Its generated
[JSON proof](wave-137-statute-preflight.json) records all 31,079 files and
66,750,184 rendered bytes verified, six duplicate groups reconciled while
retaining capture metadata, and 72,753 raw / 72,733 document-deduplicated
unresolved history occurrences. Body classifications are 28,812 substantive,
2,264 empty and three inline History-only; the structural nonempty count remains
28,815. The parser produced **83,258 exact-coordinate chunks**, including
separately labelled trailing history and annotations. These are local chunk
outputs, not paid embeddings or indexed records.

Executed command (corpus/worktree read-only; only proof directory writable):

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro -v /Users/mfrieson/Developer/statecivics-statute-corpus:/statutes:ro -v /Users/mfrieson/Developer/exais-vector-store-law-money/.tranche/statecivics-semantic-graph/aligned:/proof -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python scripts/release/kansas-statute-preflight.py --manifest /statutes/manifests/statute_scrape_20260911_030653.json --corpus-root /statutes --expected-manifest-sha256 17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2 --proof /proof/wave-137-statute-preflight.json
```

The coder's final focused Docker run passed **138 tests, zero skipped**. Root's
broader Docker regression passed **561 tests, zero skipped, zero failures/errors**
in 32.46 seconds. The [machine-readable summary](wave-137-regression-summary.json)
was produced from the JUnit test cases, requiring a nonempty run and refusing any
skipped/failure/error case. Three existing framework deprecation warnings were
reported. This includes the full retained statute preparation and prior fiscal,
graph, parser, metadata, source-package, routing and OpenAPI regressions.

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro -v /Users/mfrieson/Developer/statecivics-statute-corpus:/statutes:ro -v /Users/mfrieson/Developer/exais-vector-store-law-money/.release/cells/ks-state-civics/kansas-statutes/qc:/proof -v /Users/mfrieson/Developer/statecivics-kanview-corpus:/corpus:ro -v /Users/mfrieson/Developer/statecivics-custody:/custody:ro -v /Users/mfrieson/Developer/statecivics-ks599-cpu-output/session-laws:/session-laws:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent -e SVS_STATUTE_CORPUS_ROOT=/statutes -e SVS_FISCAL_CORPUS_ROOT=/corpus -e SVS_FISCAL_CUSTODY_ROOT=/custody -e SVS_FISCAL_SESSION_LAWS_ROOT=/session-laws localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python -m pytest -q -rs --tb=short --junit-xml=/proof/wave-137-regression.xml -p no:cacheprovider tests/test_statecivics_page_chunking.py tests/test_ingestion_page_coordinates.py tests/test_ingestion_metadata_refresh.py tests/test_kansas_fiscal_document_ingest.py tests/test_vectorization_plan.py tests/test_chunking.py tests/test_code_chunker.py tests/test_structured_and_logs_chunkers.py tests/test_router.py tests/test_fiscal_document_evidence.py tests/test_fiscal_projection_contract.py tests/test_fiscal_structured_evidence.py tests/test_fiscal_graph.py tests/test_fiscal_graph_artifact.py tests/test_fiscal_graph_routes.py tests/test_fiscal_real_corpus.py tests/test_openapi_contract.py tests/test_grant_cell_graph.py tests/test_statecivics_statutes.py tests/test_kansas_statute_ingest.py tests/test_instance_source_packages.py
```

The runner tests capture actual requests for `/api/v1/ingestion/preview` and
`/api/v1/documents/ingest`, verifying identical content/attributes and a
nonpersistent preview. They use an HTTP-call double. The service tests execute
the real plan/chunk/persistence path and inspect database parameters with
provider, index and storage doubles. Those proofs establish wiring and exact
coordinates; they do not establish deployed HTTP service or retrieval recall.
The separate PostgreSQL proof above executes the real selector SQL.

## Independent QC and limits

[Independent QC](wave-137-qc.md) returned **PASS WITH NOTES**: 113 tests executed,
zero skipped; all 39 actual PostgreSQL selector assertions rerun; every exact
slice and coverage of 77,300 included body/metadata regions checked across all
31,079 retained files. No uncovered non-whitespace within those regions or
blocking defect was found. Both
files containing carriage returns retained the correct original characters and
LF/Unicode coordinates. QC independently checked the root JUnit report and source
declaration validation.

The task's disposable PostgreSQL container and Unix-socket volume were removed
after review. Local Markdown links and changed JSON syntax passed final checks.
No live store was created or indexed. The custody-backed statute retrieval
export and deployment remain the next live handoff. The available upstream
checkout still reports `3f975e79`; no statute retrieval-export JSONL was found
in that checkout or the retained statute corpus during the final read-only check.
That is a statement about the available handoff, not every possible external
location. Canonical provision/attestation/entity integration and deployed recall
remain separate acceptance work.
