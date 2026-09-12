Decision: FAIL

Ticket reviewed:
- `tickets/WAVE-134-fiscal-projection-ingestion-lifecycle.md`, bounded document-coordinate increment at base `86bf4b3`.
- Allowed files/ownership: `build-contract.json:document_coordinate_increment` and `stack.index.json`. Full WAVE-134 remains in progress independently of this decision.

Evidence reviewed:
- Runtime/parser/runner diffs and all five changed/new test files listed in the build contract; operator, handoff, metadata research, planning maps and implementation proof.
- Independent focused run: 82 passed, zero skipped, two existing warnings, 4.76 seconds. Root's 466-pass broader run was reviewed as root evidence, not independently repeated.
- Independent actual `_find_exact_duplicate` / `_find_version_target` SQL against the existing disposable PostgreSQL 16 server, using a separately created/dropped minimal `coordinate_qc` schema and network-disabled client.
- Read-only inspection of existing API preview, dedupe refresh helpers and retrieval metadata hydration.

Acceptance criteria:
- [pass] Explicit opt-in retains existing mode/provider/default behavior; page chunks preserve exact retained text and existing page/character columns. All seven retained books ran in the independent focused selection without skips.
- [pass] Preamble preservation, blank-page handling, bounded slice splitting, page/line convention and source hashes are meaningfully tested. No canonical action/reference is inferred from chunk membership.
- [pass] Actual PostgreSQL selectors preserve old-profile migration, incomplete same-profile retry and tenant/business/store/source separation in the tested minimal schema.
- [fail] Operator state must not claim server profile adoption merely because a generic ingest response reports success.
- [fail] Same-byte dedupe must not acknowledge newly supplied evidence provenance while returning stale revision/citation fields from existing chunks.
- [deferred] Canonical entity/lifecycle and graph integration, fully migrated PostgreSQL/API/backend testing, deployment and paid/live replay remain outside this increment.

Findings:

1. **Unsupported server can be recorded as coordinate-profile success.** `submit_upsert` sends the new attribute, then accepts any `completed` or `deduplicated` response carrying IDs. `apply_operations` records the requested profile from the operation. An older server accepts arbitrary attributes but ignores this one, so the next plan can become a no-op while its live chunks remain unlocated. The existing `test_coordinate_opt_in_sends_exact_text_and_provenance_without_mode_change` passes using precisely a generic success response without server-computed chunker evidence. Root raised this case; independent code review confirms it.

   Required fix: before an opted-in text ingest, call the existing `/api/v1/ingestion/preview` with the exact intended request and `persist=false`, and require its server-computed `chunker` to equal `statecivics_page_markdown_v1` (with compatible mode). Missing, legacy, mismatched or failed preview must abort before the ingest POST or applied-state advancement. Preserve non-opted-in and PDF paths. Add negative tests for old/missing/mismatched responses and proof that no submit/state mutation occurs; add positive preview-to-submit coverage. This can use the existing endpoint/model rather than inventing a new API.

2. **Metadata-only source revision change leaves stale chunk provenance.** In actual PostgreSQL, a completed same-profile/same-byte document with stored chunk `source_revision_id=old-revision` deduplicated a request for `new-revision`. `_find_exact_duplicate` compares profile/content/source identity but not the provenance newly copied into chunks. The dedupe branch updates document metadata and `vector_store_files` attributes; it does not update `document_versions` provenance or chunk metadata. Existing `RetrievalService._hydrate_and_acl` returns `c.metadata` directly, so the accepted request can expose old evidence pointers alongside refreshed file/document metadata.

   Required fix: for this opt-in path, include the source/extraction/citation provenance fields in dedupe equivalence, or perform a coherent, explicitly tested refresh/version operation. A changed provenance binding must not become a false no-op. Preserve immutable evidence history, unchanged-provenance dedupe and reuse of the same source document identity. Test a same-byte revision/citation change through the accepted ingestion path and verify returned/persisted metadata, not only SQL string fragments. This is distinct from the deferred full canonical-graph lifecycle implementation.

Required fixes before next ticket:
- Resolve both findings above in the authorized files, record focused proof, then obtain a second independent review. Do not commit this increment as accepted or proceed to dependent work on this FAIL.
- No parser rewrite, global mode switch, upstream schema edit, paid provider call or deployment is required by these findings.

## Independent commands and results

Focused command, exit 0:

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

Result: `82 passed, 2 warnings in 4.76s`, zero skipped. Those tests do not establish the two missing acceptance cases.

Actual PostgreSQL probe, exit 0 in 0.98 seconds:

```sh
docker run --rm -i --platform linux/amd64 --network none --memory 2g --cpus 2 \
  --mount type=volume,source=exais-w134-socket-mtwa4o19,target=/pgsocket \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python - <<'PY'
import hashlib,json
from sqlalchemy import create_engine,text
from svs_common.ingestion import IngestionService
from svs_common.schemas import DocumentIngestRequest,Principal
profile='statecivics_page_markdown_v1';content='<!-- page 1 -->\nquote\n';digest=hashlib.sha256(content.encode()).hexdigest()
engine=create_engine('postgresql+psycopg://postgres@/postgres?host=/pgsocket')
service=object.__new__(IngestionService);principal=Principal(tenant_id='qc-tenant',business_instance_id='qc-biz')
def req(identity='source-A',revision='new-revision',opt=True,vs='vs-qc'):
 attrs={'source_page_chunking_profile':profile,'source_collection':'statecivics-kansas-fiscal-documents','extraction_content_hash_sha256':digest,'source_revision_id':revision} if opt else {}
 return DocumentIngestRequest(vector_store_id=vs,knowledge_base_id='kb-qc',title='QC selector probe',filename='qc.md',mime_type='text/markdown',content=content,mode='markdown_docs_v1',source_identity=identity,attributes=attrs)
with engine.begin() as db:
 db.execute(text('CREATE SCHEMA coordinate_qc'));db.execute(text('SET LOCAL search_path TO coordinate_qc'))
 db.execute(text('CREATE TABLE documents(id text,tenant_id text,business_instance_id text,knowledge_base_id text,vector_store_id text,content_hash text,status text,current_version_id text,source_uri text,filename text,created_at timestamptz DEFAULT now())'))
 db.execute(text('CREATE TABLE document_versions(id text,document_id text,tenant_id text,business_instance_id text,metadata jsonb,status text,chunking_profile_id text)'))
 db.execute(text('CREATE TABLE chunks(document_id text,document_version_id text,tenant_id text,business_instance_id text,active boolean,dense_index_status text,sparse_index_status text,metadata jsonb)'))
 values={'digest':digest,'meta':json.dumps({'source_identity':'source-A','attributes':{'source_revision_id':'old-revision'}}),'chunkmeta':json.dumps({'source_revision_id':'old-revision'})}
 db.execute(text("INSERT INTO documents VALUES('doc-qc','qc-tenant','qc-biz','kb-qc','vs-qc',:digest,'active','ver-qc',NULL,'qc.md',now())"),values)
 db.execute(text("INSERT INTO document_versions VALUES('ver-qc','doc-qc','qc-tenant','qc-biz',CAST(:meta AS jsonb),'indexed','markdown_heading_hierarchy_v2')"),values)
 db.execute(text("INSERT INTO chunks VALUES('doc-qc','ver-qc','qc-tenant','qc-biz',true,'indexed','indexed',CAST(:chunkmeta AS jsonb))"),values)
 assert service._find_exact_duplicate(db,principal,req(opt=False),digest)['id']=='doc-qc'
 assert service._find_exact_duplicate(db,principal,req(),digest) is None
 assert service._find_version_target(db,principal,req(),digest)['id']=='doc-qc'
 assert service._find_version_target(db,principal,req('source-B'),digest) is None
 assert service._find_version_target(db,principal,req(vs='vs-other'),digest) is None
 for other in [principal.model_copy(update={'tenant_id':'other'}),principal.model_copy(update={'business_instance_id':'other'})]:
  assert service._find_version_target(db,other,req(),digest) is None
 db.execute(text('UPDATE document_versions SET chunking_profile_id=:p'),{'p':profile})
 duplicate=service._find_exact_duplicate(db,principal,req(),digest)
 assert duplicate and duplicate['id']=='doc-qc'
 stored=db.execute(text("SELECT metadata->>'source_revision_id' FROM chunks")).scalar()
 db.execute(text("UPDATE chunks SET sparse_index_status='failed'"))
 assert service._find_exact_duplicate(db,principal,req(),digest) is None
 assert service._find_version_target(db,principal,req(),digest)['id']=='doc-qc'
 print(json.dumps({'profile_migration_and_incomplete_retry_pass':True,'source_tenant_business_store_scope_pass':True,'changed_source_revision_request_deduplicates_existing_version':bool(duplicate),'stored_chunk_revision':stored,'requested_revision':req().attributes['source_revision_id'],'minimal_disposable_schema_only':True}))
 db.execute(text('DROP SCHEMA coordinate_qc CASCADE'))
engine.dispose()
PY
```

Observed output confirms the defect as well as the successful scope/retry cases:

```json
{"profile_migration_and_incomplete_retry_pass": true, "source_tenant_business_store_scope_pass": true, "changed_source_revision_request_deduplicates_existing_version": true, "stored_chunk_revision": "old-revision", "requested_revision": "new-revision", "minimal_disposable_schema_only": true}
```

`git diff --check` also passed. No code/corpus/provider/live state was changed by this reviewer; only the isolated test schema and this QC artifact were written. No commit was made. The PostgreSQL server/socket volume remain with root for correction checks and cleanup.
