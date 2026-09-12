Decision: PASS WITH NOTES

Ticket reviewed:
- `tickets/WAVE-134-fiscal-projection-ingestion-lifecycle.md`, base `86bf4b3`, bounded retained-document-coordinate increment only.
- Ownership: `build-contract.json:document_coordinate_increment` and `stack.index.json`, T-005 / WAVE-134. Independent inspection confirmed all nine changed runtime/test files are explicitly assigned there.
- The [first FAIL report](wave-134-document-coordinate-qc.md) is preserved. This second review closes its two findings for the corrected increment; full WAVE-133/134 graph integration remains open.

Evidence reviewed:
- All authorized runtime/test diffs: chunking, ingestion, vectorization preview, fiscal ingest runner and five test files.
- Updated operator/central handoff, semantic metadata research, ticket, ownership maps and [implementation proof](wave-134-document-coordinate-proof.md).
- Independent focused container test run and actual PostgreSQL selection/provenance probes below. Root's 490-pass combined run is reviewed root evidence, not a second independently executed full-suite count.
- Read-only review confirms the existing retrieval hydrator returns chunk metadata, and the corrected ingestion path versions changed evidence context rather than leaving stale fields behind.

Acceptance criteria:
- [pass] Exact source slices populate existing page/character columns and returned metadata. Both preview and ingestion use the same explicit source-specific parser without changing the mode or embedding/provider selection. Generic/PDF defaults remain intact.
- [pass] Real retained-source tests cover all seven books, fixed extraction hashes, every emitted slice/page/line/hash, meaningful source coverage, blank pages, unpaginated prefixes and the actual page-358 lapse. The complete specific legal quote remains distinct from its containing multi-provision chunk; no canonical action IDs or relationships are inferred.
- [pass] Resource and coordinate bounds fail closed; original Unicode/whitespace is retained and enclosing line ranges are labeled separately from authoritative exact character offsets.
- [pass] First FAIL finding 1 is fixed: opted-in text submission first requires the server's computed profile, compatible mode and bounded positive chunk count through `persist=false` ingestion preview. Missing, legacy, mismatched, malformed and failed preview cases cannot reach ingest or advance state. Positive tests verify preview and ingest use the same document request.
- [pass] First FAIL finding 2 is fixed: one evidence-context whitelist controls both version dedupe comparison and copied chunk metadata. Changed, removed or explicitly null provenance refuses false dedupe; version selection retains the same source document. Fresh-version tests verify matching version/chunk metadata. Unchanged evidence deduplicates without provider calls; unrelated operator metadata does not force a rebuild.
- [pass] Actual PostgreSQL checks establish profile migration, retry selection and tenant/business/store/source separation in an explicitly minimal disposable schema. They are not presented as fully migrated service/RLS/backend certification.
- [pass] No upstream schema, canonical provision identity, graph activation, live replay, paid provider call or deployment was added. All 44 reviewed local Markdown paths/anchors resolve; `git diff --check` passed.
- [deferred] Reviewed canonical graph records/contracts, bound verification provenance and source rights/QA, complete graph lifecycle, fully integrated API/backend and disposable fully migrated PostgreSQL acceptance, deployment and approved live re-ingestion.

Findings:
- No remaining blocker found for this bounded increment.
- The server preview proves support for the explicit parser on the responding implementation; the recorded tests do not constitute a live deployment or index-content check. The operator documentation preserves that boundary.
- Pipeline tests use no-network provider/index/storage doubles and inspect actual SQL insert parameters; actual PostgreSQL checks cover selectors separately. This combined proof is adequate for the assigned implementation, without claiming an end-to-end deployed law-to-money answer.

Required fixes before next ticket:
- None before accepting/committing this bounded increment.
- Keep full WAVE-133 and WAVE-134 in progress. Their remaining canonical integration and deployment/activation criteria are not waived by this review.

## Independent execution

Review date: 2026-09-10. The focused command used the existing image, read-only worktree and retained corpus mounts, no network, 2 GiB memory and two CPUs:

```sh
docker run --rm --platform linux/amd64 --network none --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-ks599-cpu-output/session-laws:/session-laws:ro \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent \
  -e SVS_FISCAL_SESSION_LAWS_ROOT=/session-laws \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 \
  python -m pytest -q -rs --tb=short -p no:cacheprovider \
  tests/test_statecivics_page_chunking.py tests/test_ingestion_page_coordinates.py \
  tests/test_ingestion_metadata_refresh.py tests/test_kansas_fiscal_document_ingest.py \
  tests/test_vectorization_plan.py tests/test_chunking.py tests/test_router.py \
  tests/test_documents_ingest.py
```

Observed: **106 passed, zero skipped, two existing deprecation warnings, 4.63 seconds**, exit 0. The explicit retained-corpus mount ensured the seven-book checks ran.

Independent actual PostgreSQL probe against the existing isolated server/socket, creating and dropping only a new `coordinate_qc2` test schema:

```sh
docker run --rm -i --platform linux/amd64 --network none --memory 2g --cpus 2 \
  --mount type=volume,source=exais-w134-socket-mtwa4o19,target=/pgsocket \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python - <<'PY'
import hashlib,json
from sqlalchemy import create_engine,text
from svs_common.ingestion import IngestionService,_document_version_metadata
from svs_common.schemas import DocumentIngestRequest,Principal
profile='statecivics_page_markdown_v1';content='<!-- page 1 -->\nquote\n';digest=hashlib.sha256(content.encode()).hexdigest()
engine=create_engine('postgresql+psycopg://postgres@/postgres?host=/pgsocket')
service=object.__new__(IngestionService);principal=Principal(tenant_id='qc2-tenant',business_instance_id='qc2-biz')
baseattrs={'source_page_chunking_profile':profile,'source_collection':'statecivics-kansas-fiscal-documents','extraction_content_hash_sha256':digest,'source_revision_id':'revision-old','source_content_hash_sha256':'a'*64,'logical_document_id':'logical-A','extraction_revision_id':'extraction-old','citation_url':'https://example.invalid/old.pdf'}
def req(attrs=None,identity='source-A',vs='vs-qc'):
 return DocumentIngestRequest(vector_store_id=vs,knowledge_base_id='kb-qc',title='QC2 selector probe',filename='qc.md',mime_type='text/markdown',content=content,mode='markdown_docs_v1',source_identity=identity,attributes=baseattrs if attrs is None else attrs)
with engine.begin() as db:
 db.execute(text('CREATE SCHEMA coordinate_qc2'));db.execute(text('SET LOCAL search_path TO coordinate_qc2'))
 db.execute(text('CREATE TABLE documents(id text,tenant_id text,business_instance_id text,knowledge_base_id text,vector_store_id text,content_hash text,status text,current_version_id text,source_uri text,filename text,created_at timestamptz DEFAULT now())'))
 db.execute(text('CREATE TABLE document_versions(id text,document_id text,tenant_id text,business_instance_id text,metadata jsonb,status text,chunking_profile_id text)'))
 db.execute(text('CREATE TABLE chunks(document_id text,document_version_id text,tenant_id text,business_instance_id text,active boolean,dense_index_status text,sparse_index_status text)'))
 db.execute(text("INSERT INTO documents VALUES('doc-qc','qc2-tenant','qc2-biz','kb-qc','vs-qc',:digest,'active','ver-qc',NULL,'qc.md',now())"),{'digest':digest})
 db.execute(text("INSERT INTO document_versions VALUES('ver-qc','doc-qc','qc2-tenant','qc2-biz',CAST(:meta AS jsonb),'indexed',:profile)"),{'meta':json.dumps(_document_version_metadata(req(),'markdown_docs_v1')),'profile':profile})
 db.execute(text("INSERT INTO chunks VALUES('doc-qc','ver-qc','qc2-tenant','qc2-biz',true,'indexed','indexed')"))
 assert service._find_exact_duplicate(db,principal,req(),digest)['id']=='doc-qc'
 changes=[('source_revision_id','revision-new'),('source_content_hash_sha256','b'*64),('logical_document_id','logical-B'),('extraction_revision_id','extraction-new'),('citation_url','https://example.invalid/new.pdf'),('source_page_count',1)]
 for key,value in changes:
  changed=req({**baseattrs,key:value})
  assert service._find_exact_duplicate(db,principal,changed,digest) is None,key
  assert service._find_version_target(db,principal,changed,digest)['id']=='doc-qc',key
 for key in ('source_revision_id','citation_url','extraction_revision_id'):
  absent=dict(baseattrs);absent.pop(key)
  for attrs in (absent,{**baseattrs,key:None}):
   assert service._find_exact_duplicate(db,principal,req(attrs),digest) is None
   assert service._find_version_target(db,principal,req(attrs),digest)['id']=='doc-qc'
 assert service._find_exact_duplicate(db,principal,req({**baseattrs,'operator_note':'irrelevant'}),digest)['id']=='doc-qc'
 assert service._find_exact_duplicate(db,principal,req({}),digest)['id']=='doc-qc'
 for other in (principal.model_copy(update={'tenant_id':'other'}),principal.model_copy(update={'business_instance_id':'other'})):
  assert service._find_exact_duplicate(db,other,req(),digest) is None
  assert service._find_version_target(db,other,req(),digest) is None
 for otherreq in (req(identity='source-B'),req(vs='vs-other')):
  assert service._find_exact_duplicate(db,principal,otherreq,digest) is None
  assert service._find_version_target(db,principal,otherreq,digest) is None
 db.execute(text("UPDATE chunks SET dense_index_status='failed'"))
 assert service._find_exact_duplicate(db,principal,req(),digest) is None
 assert service._find_version_target(db,principal,req(),digest)['id']=='doc-qc'
 db.execute(text("UPDATE document_versions SET chunking_profile_id='markdown_heading_hierarchy_v2'"))
 assert service._find_exact_duplicate(db,principal,req(),digest) is None
 assert service._find_version_target(db,principal,req(),digest)['id']=='doc-qc'
 print(json.dumps({'changed_evidence_fields_reject_dedupe':len(changes),'absent_or_null_provenance_rejects_dedupe':6,'unchanged_and_unrelated_metadata_dedupe':True,'source_identity_retained_for_rebuild':True,'legacy_retry_migration_and_scope_checks':True,'live_database_or_provider_access':False},sort_keys=True))
 db.execute(text('DROP SCHEMA coordinate_qc2 CASCADE'))
engine.dispose()
PY
```

Observed exit 0:

```json
{"absent_or_null_provenance_rejects_dedupe": 6, "changed_evidence_fields_reject_dedupe": 6, "legacy_retry_migration_and_scope_checks": true, "live_database_or_provider_access": false, "source_identity_retained_for_rebuild": true, "unchanged_and_unrelated_metadata_dedupe": true}
```

The unchanged extraction hash is independently required before ingest dedupe; the focused tests also verify missing/incorrect expected extraction hashes cannot reach dedupe or a provider. The SQL probe above tests selection mechanics, not fabricated source records or fully integrated persistence.

Only this second QC artifact and the temporary isolated test schema were written by this reviewer. The first FAIL artifact, runtime code, upstream, corpus and live indexes were untouched. No commit was made; the disposable PostgreSQL server/socket remain available for root's cleanup.
