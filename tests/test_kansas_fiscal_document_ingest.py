from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
SCRIPT = RELEASE / "kansas-fiscal-document-ingest.py"
sys.path.insert(0, str(RELEASE))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "kansas_fiscal_document_ingest", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["kansas_fiscal_document_ingest"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ingest():
    return _load_module()


def _record(
    ingest,
    content: bytes,
    *,
    logical_document_id: str = "1" * 64,
    mime_type: str = "application/pdf",
    action: str = "upsert",
) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    is_upsert = action == "upsert"
    record = {
        "export_record_id": "2" * 64,
        "logical_document_id": logical_document_id,
        "source_revision_id": "revision-1",
        "revision_number": 1,
        "content_hash_sha256": digest,
        "custody_uri": (
            f"civic-custody://kanview/{digest[:2]}/{digest}" if is_upsert else None
        ),
        "custody_status": "retained" if is_upsert else "retained_restricted",
        "citation_url": "https://budget.kansas.gov/reports/fy2027.pdf",
        "publisher": "Kansas Division of the Budget",
        "jurisdiction": "Kansas",
        "artifact_type": "budget_report",
        "record_digest_algorithm": "statecivics-canonical-json-v1",
        "record_digest_sha256": "0" * 64,
        "mime_type": mime_type,
        "byte_size": len(content),
        "title": "Kansas FY2027 Budget Report",
        "effective_period": {"fiscal_year": 2027},
        "exporter": {
            "name": "statecivics-retrieval-exporter",
            "version": "retrieval-export-1",
            "code_commit": "a" * 40,
            "exported_at": "2026-09-04T12:00:00Z",
        },
        "lifecycle": {
            "state": "current",
            "removal_required": not is_upsert,
        },
        "redistribution": "full" if is_upsert else "restricted",
        "ingestion": {
            "mode": "api_only",
            "action": action,
            "target_instance_slug": "ks-state-civics",
            "target_vector_store_slug": "kansas-fiscal-documents",
            "recall_evaluation_required": is_upsert,
        },
    }
    record["record_digest_sha256"] = ingest.record_digest(record)
    return record


def _write_manifest(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def _write_custody(root: Path, record: dict, content: bytes) -> Path:
    digest = hashlib.sha256(content).hexdigest()
    path = root / "kanview" / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_manifest_verifies_record_digest_and_target(ingest, tmp_path):
    content = b"%PDF-1.7\nFiscal report"
    record = _record(ingest, content)
    manifest_path = tmp_path / "manifest.jsonl"
    _write_manifest(manifest_path, [record])

    manifest = ingest.load_manifest(manifest_path)

    assert manifest.records == (record,)
    assert manifest.sha256 == hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    record["citation_url"] = "https://attacker.invalid/substitution.pdf"
    _write_manifest(manifest_path, [record])
    with pytest.raises(ingest.FiscalIngestError, match="record digest"):
        ingest.load_manifest(manifest_path)


def test_manifest_refuses_stale_upsert_after_rights_change(ingest, tmp_path):
    content = b"%PDF-1.7\nFiscal report"
    record = _record(ingest, content)
    record["redistribution"] = "restricted"
    record["record_digest_sha256"] = ingest.record_digest(record)
    path = tmp_path / "manifest.jsonl"
    _write_manifest(path, [record])

    with pytest.raises(ingest.FiscalIngestError, match="action must be remove"):
        ingest.load_manifest(path)


def test_manifest_refuses_raw_canonical_table_extracts(ingest, tmp_path):
    content = b"account,amount\n100,5\n"
    record = _record(ingest, content, mime_type="text/plain")
    record["artifact_type"] = "chart_of_accounts"
    record["record_digest_sha256"] = ingest.record_digest(record)
    path = tmp_path / "manifest.jsonl"
    _write_manifest(path, [record])

    with pytest.raises(ingest.FiscalIngestError, match="not retrieval-exportable"):
        ingest.load_manifest(path)


def test_custody_read_verifies_pdf_header_hash_and_size(ingest, tmp_path):
    content = b"%PDF-1.7\nFiscal report"
    record = _record(ingest, content)
    custody = tmp_path / "custody"
    object_path = _write_custody(custody, record, content)

    assert ingest.read_custody_object(custody, record) == content

    object_path.write_bytes(b"not a pdf")
    with pytest.raises(ingest.FiscalIngestError, match="PDF header"):
        ingest.read_custody_object(custody, record)


def test_plan_is_removal_first_and_repeat_upsert_is_a_noop(ingest, tmp_path):
    pdf = b"%PDF-1.7\nFiscal report"
    upsert = _record(ingest, pdf, logical_document_id="1" * 64)
    remove = _record(
        ingest,
        b"prior",
        logical_document_id="3" * 64,
        action="remove",
    )
    manifest = ingest.LoadedManifest(
        path=tmp_path / "manifest.jsonl",
        sha256="4" * 64,
        byte_count=1,
        records=(upsert, remove),
    )
    custody = tmp_path / "custody"
    _write_custody(custody, upsert, pdf)
    state = {
        "schema_version": 1,
        "vector_store_id": "vs_fiscal",
        "records": {
            upsert["logical_document_id"]: {
                "action": "upsert",
                "record_digest_sha256": upsert["record_digest_sha256"],
                "document_id": "doc-current",
                "vector_store_file_id": "vsf-current",
            },
            remove["logical_document_id"]: {
                "action": "upsert",
                "record_digest_sha256": "5" * 64,
                "document_id": "doc-prior",
                "vector_store_file_id": "vsf-prior",
            },
        },
    }

    operations = ingest.plan_operations(manifest, custody_root=custody, state=state)

    assert [(item.action, item.logical_document_id) for item in operations] == [
        ("remove", remove["logical_document_id"]),
        ("noop", upsert["logical_document_id"]),
    ]


def test_coordinate_profile_change_replays_same_digest_once_and_then_noops(ingest, tmp_path, monkeypatch):
    content = b'<!-- page 1 -->\nExact retained text.\n'
    record = _record(ingest, content, mime_type='text/markdown')
    custody = tmp_path / 'custody'
    _write_custody(custody, record, content)
    manifest = ingest.LoadedManifest(tmp_path / 'manifest.jsonl', '4' * 64, 1, (record,))
    state = {'schema_version': 1, 'vector_store_id': 'vs_fiscal', 'records': {
        record['logical_document_id']: {'action': 'upsert', 'record_digest_sha256': record['record_digest_sha256'],
                                         'document_id': 'doc-existing', 'vector_store_file_id': 'vsf-existing'}}}
    profile = ingest.STATECIVICS_PAGE_MARKDOWN_PROFILE
    assert ingest.plan_operations(manifest, custody_root=custody, state=state)[0].action == 'noop'
    operations = ingest.plan_operations(manifest, custody_root=custody, state=state, source_page_chunking_profile=profile)
    assert operations[0].action == 'upsert' and operations[0].source_page_chunking_profile == profile
    original_digest = record['record_digest_sha256']
    assert ingest.ingest_idempotency_key('vs_fiscal', record) != ingest.ingest_idempotency_key(
        'vs_fiscal', record, source_page_chunking_profile=profile)
    monkeypatch.setattr(ingest, 'submit_upsert', lambda *args, **kwargs: {
        'document_id': 'doc-existing', 'vector_store_file_id': 'vsf-coordinate'})
    ingest.apply_operations(operations, state=state, state_path=tmp_path / 'state.json', api_base='https://unused.invalid',
                            headers={}, vector_store_id='vs_fiscal', knowledge_base_id='kb', timeout=1, cell='test', transport='auto')
    assert state['records'][record['logical_document_id']]['source_page_chunking_profile'] == profile
    assert ingest.plan_operations(manifest, custody_root=custody, state=state,
                                  source_page_chunking_profile=profile)[0].action == 'noop'
    assert record['record_digest_sha256'] == original_digest


def test_coordinate_opt_in_sends_exact_text_and_provenance_without_mode_change(ingest, monkeypatch):
    content = '# File-Name\n\n<!-- page 1 -->\n  café\n'.encode()
    record = _record(ingest, content, mime_type='text/markdown')
    record['page_count'] = 1
    record['record_digest_sha256'] = ingest.record_digest(record)
    operation = ingest.PlannedOperation('upsert', record['logical_document_id'], 'profile change', record, content,
                                       ingest.STATECIVICS_PAGE_MARKDOWN_PROFILE)
    captured = {}

    def fake_json(method, base, path, payload, **kwargs):
        if path == '/api/v1/ingestion/preview':
            captured['preview'] = payload
            return {'chunker': ingest.STATECIVICS_PAGE_MARKDOWN_PROFILE, 'mode': 'markdown_docs_v1', 'estimated_chunks': 2}
        captured.update(payload=payload, request_kwargs=kwargs)
        return {'status': 'completed', 'document_id': 'doc', 'vector_store_file_id': 'vsf'}

    monkeypatch.setattr(ingest, 'api_json', fake_json)
    ingest.submit_upsert(operation, api_base='https://unused.invalid', headers={}, vector_store_id='vs_fiscal',
                         knowledge_base_id='kb', timeout=1, cell='test', transport='auto')
    payload = captured['payload']
    assert captured['preview'] == {**payload, 'persist': False}
    assert payload['mode'] == 'markdown_docs_v1' and payload['content'].encode() == content
    attrs = payload['attributes']
    assert attrs['source_page_chunking_profile'] == ingest.STATECIVICS_PAGE_MARKDOWN_PROFILE
    assert attrs['extraction_content_hash_sha256'] == record['content_hash_sha256']
    assert attrs['source_content_hash_sha256'] == record['content_hash_sha256']
    assert attrs['source_revision_id'] == record['source_revision_id'] and attrs['source_page_count'] == 1
    assert 'embedding_profile_id' not in attrs and 'provision_id' not in attrs


@pytest.mark.parametrize('preview', [None, {}, {'status': 'completed'},
    {'chunker': 'markdown_heading_hierarchy_v2', 'mode': 'markdown_docs_v1', 'estimated_chunks': 1},
    {'chunker': 'statecivics_page_markdown_v1', 'mode': 'pdf_markdown_external_v1', 'estimated_chunks': 1},
    {'chunker': 'statecivics_page_markdown_v1', 'mode': 'markdown_docs_v1', 'estimated_chunks': True},
    {'chunker': 'statecivics_page_markdown_v1', 'mode': 'markdown_docs_v1', 'estimated_chunks': 0},
    {'chunker': 'statecivics_page_markdown_v1', 'mode': 'markdown_docs_v1', 'estimated_chunks': 20001},
    RuntimeError('preview HTTP 404')])
def test_profile_preview_failure_prevents_ingest_and_state_advance(ingest, tmp_path, monkeypatch, preview):
    content = b'<!-- page 1 -->\ntext\n'
    record = _record(ingest, content, mime_type='text/markdown')
    operation = ingest.PlannedOperation('upsert', record['logical_document_id'], 'profile change', record, content,
                                       ingest.STATECIVICS_PAGE_MARKDOWN_PROFILE)
    calls = []

    def fake_json(method, base, path, payload, **kwargs):
        calls.append(path)
        assert path == '/api/v1/ingestion/preview', 'failed preview must prevent ingest POST'
        assert payload['persist'] is False
        if isinstance(preview, Exception):
            raise preview
        return preview

    monkeypatch.setattr(ingest, 'api_json', fake_json)
    state = {'schema_version': 1, 'vector_store_id': 'vs', 'records': {}}
    state_file = tmp_path / 'state.json'
    with pytest.raises((ingest.FiscalIngestError, RuntimeError)):
        ingest.apply_operations([operation], state=state, state_path=state_file, api_base='https://unused.invalid',
                                headers={}, vector_store_id='vs', knowledge_base_id='kb', timeout=1, cell='test', transport='auto')
    assert calls == ['/api/v1/ingestion/preview']
    assert state['records'] == {} and not state_file.exists()


@pytest.mark.parametrize('counts', [{'page_count': 2}, {'page_count': True}, {'pages': -1},
                                  {'source_page_count': 1, 'page_count': 2}])
def test_coordinate_opt_in_rejects_declared_count_mismatches(ingest, counts):
    content = b'<!-- page 1 -->\ntext\n'
    record = {**_record(ingest, content, mime_type='text/markdown'), **counts}
    with pytest.raises(ingest.FiscalIngestError):
        ingest._page_chunking_attributes(record, content)


def test_coordinate_profile_leaves_pdf_operations_on_existing_marker_path(ingest, tmp_path):
    content = b'%PDF-1.7\nFiscal report'
    record = _record(ingest, content)
    custody = tmp_path / 'custody'
    _write_custody(custody, record, content)
    manifest = ingest.LoadedManifest(tmp_path / 'manifest.jsonl', '4' * 64, 1, (record,))
    operation = ingest.plan_operations(manifest, custody_root=custody, state={'records': {}},
                                       source_page_chunking_profile=ingest.STATECIVICS_PAGE_MARKDOWN_PROFILE)[0]
    assert operation.action == 'upsert' and operation.source_page_chunking_profile is None


def test_pdf_upsert_uses_marker_upload_and_stable_identity(ingest, monkeypatch):
    content = b"%PDF-1.7\nFiscal report"
    record = _record(ingest, content)
    operation = ingest.PlannedOperation(
        "upsert", record["logical_document_id"], "test", record, content
    )
    captured: dict = {}

    def fake_multipart(api_base, path, **kwargs):
        captured.update({"api_base": api_base, "path": path, **kwargs})
        return {
            "id": "job-1",
            "status": "completed",
            "document_id": "doc-1",
            "vector_store_file_id": "vsf-1",
        }

    def forbidden_json(*args, **kwargs):
        raise AssertionError("PDFs must not bypass Marker through JSON ingestion")

    monkeypatch.setattr(ingest, "api_multipart", fake_multipart)
    monkeypatch.setattr(ingest, "api_json", forbidden_json)

    response = ingest.submit_upsert(
        operation,
        api_base="https://exais.invalid",
        headers={"Authorization": "Bearer redacted"},
        vector_store_id="vs_fiscal",
        knowledge_base_id="kb_civics",
        timeout=30,
        cell="ks-state-civics",
        transport="docker-network",
    )

    assert response["vector_store_file_id"] == "vsf-1"
    assert captured["path"] == "/api/v1/documents/upload"
    assert captured["mime_type"] == "application/pdf"
    assert captured["content"] == content
    assert captured["fields"]["mode"] == "auto_detect_v1"
    assert captured["fields"]["source_uri"] == record["citation_url"]
    assert captured["fields"]["source_identity"] == record["logical_document_id"]
    attrs = json.loads(captured["fields"]["attributes_json"])
    assert attrs["marker_profile"] == "fiscal_tables_page_aware_v1"
    assert attrs["source_revision_id"] == "revision-1"
    assert attrs["source_content_hash_sha256"] == record["content_hash_sha256"]


def test_text_upsert_bypasses_marker_without_losing_provenance(ingest, monkeypatch):
    content = b"# Fiscal narrative\n\nText already extracted.\n"
    record = _record(ingest, content, mime_type="text/markdown")
    operation = ingest.PlannedOperation(
        "upsert", record["logical_document_id"], "test", record, content
    )
    captured: dict = {}

    def forbidden_multipart(*args, **kwargs):
        raise AssertionError("structured text must not consume a Marker job")

    def fake_json(method, api_base, path, payload, **kwargs):
        captured.update(
            {
                "method": method,
                "api_base": api_base,
                "path": path,
                "payload": payload,
                **kwargs,
            }
        )
        return {
            "id": "job-1",
            "status": "deduplicated",
            "document_id": "doc-1",
            "vector_store_file_id": "vsf-1",
        }

    monkeypatch.setattr(ingest, "api_multipart", forbidden_multipart)
    monkeypatch.setattr(ingest, "api_json", fake_json)

    ingest.submit_upsert(
        operation,
        api_base="https://exais.invalid",
        headers={},
        vector_store_id="vs_fiscal",
        knowledge_base_id="kb_civics",
        timeout=30,
        cell="ks-state-civics",
        transport="docker-network",
    )

    assert captured["path"] == "/api/v1/documents/ingest"
    assert captured["payload"]["content"] == content.decode("utf-8")
    assert captured["payload"]["source_identity"] == record["logical_document_id"]


def test_already_absent_removal_advances_local_desired_state(ingest, tmp_path):
    record = _record(ingest, b"prior", action="remove")
    operation = ingest.PlannedOperation(
        "noop", record["logical_document_id"], "already absent", record
    )
    state_path = tmp_path / "state.json"
    state = {"schema_version": 1, "vector_store_id": "vs_fiscal", "records": {}}

    counts = ingest.apply_operations(
        [operation],
        state=state,
        state_path=state_path,
        api_base="https://exais.invalid",
        headers={},
        vector_store_id="vs_fiscal",
        knowledge_base_id="kb_civics",
        timeout=30,
        cell="ks-state-civics",
        transport="docker-network",
    )

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert counts == {"upserted": 0, "removed": 0, "unchanged": 1}
    assert saved["records"][record["logical_document_id"]] == {
        "action": "remove",
        "record_digest_sha256": record["record_digest_sha256"],
        "document_id": None,
        "vector_store_file_id": None,
    }


def test_idempotency_key_changes_with_desired_record_not_export_clock(ingest):
    record = _record(ingest, b"%PDF-1.7\nFiscal report")
    first = ingest.ingest_idempotency_key("vs_fiscal", record)
    record["exporter"]["exported_at"] = "2026-09-05T12:00:00Z"
    assert ingest.ingest_idempotency_key("vs_fiscal", record) == first

    record["citation_url"] = "https://budget.kansas.gov/reports/fy2027-revised.pdf"
    record["record_digest_sha256"] = ingest.record_digest(record)
    assert ingest.ingest_idempotency_key("vs_fiscal", record) != first

    other_identity = _record(
        ingest,
        b"%PDF-1.7\nFiscal report",
        logical_document_id="9" * 64,
    )
    assert ingest.ingest_idempotency_key("vs_fiscal", other_identity) != first


# --- WAVE-133 contract pin enforcement ---------------------------------------

CONTRACT_FIXTURE = Path(__file__).parent / "fixtures" / "statecivics-retrieval-export-record.314beafe.json"


def test_ingest_accepts_the_pinned_document_branch(ingest, tmp_path):
    """Enforcement reads the schema it is handed, not one it fetches."""
    content = b"%PDF-1.7\nFiscal report"
    manifest_path = tmp_path / "manifest.jsonl"
    _write_manifest(manifest_path, [_record(ingest, content)])

    manifest = ingest.load_manifest(manifest_path, contract_schema=CONTRACT_FIXTURE)
    assert len(manifest.records) == 1
    assert ingest.verify_contract_pin(CONTRACT_FIXTURE) == ingest.DOCUMENT_BRANCH_SHA256


def test_ingest_refuses_a_changed_document_branch(ingest, tmp_path):
    content = b"%PDF-1.7\nFiscal report"
    manifest_path = tmp_path / "manifest.jsonl"
    _write_manifest(manifest_path, [_record(ingest, content)])

    schema = json.loads(CONTRACT_FIXTURE.read_text())
    schema["$defs"]["legacy_document_record"]["properties"]["custody_uri"] = {"type": "integer"}
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(schema))

    with pytest.raises(ingest.ContractPinError, match="document branch digest mismatch"):
        ingest.load_manifest(manifest_path, contract_schema=changed)


def test_document_ingest_survives_entity_branch_changes(ingest, tmp_path):
    """The whole point of splitting the pin: B1's byte-stability stays bought."""
    content = b"%PDF-1.7\nFiscal report"
    manifest_path = tmp_path / "manifest.jsonl"
    _write_manifest(manifest_path, [_record(ingest, content)])

    schema = json.loads(CONTRACT_FIXTURE.read_text())
    schema["$defs"]["entity_relationship"]["properties"]["relationship_type"]["enum"].append(
        "action_supersedes_provision"
    )
    schema["$defs"]["entity_kind_version_gate"]["description"] = "reworded"
    moved = tmp_path / "entity-moved.json"
    moved.write_text(json.dumps(schema))

    manifest = ingest.load_manifest(manifest_path, contract_schema=moved)
    assert len(manifest.records) == 1
