from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from svs_common.fiscal_marker_handoff import build_marker_handoff

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "scripts" / "release" / "kansas-fiscal-document-ingest.py"
CONTRACT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "statecivics-retrieval-export-record.314beafe.json"
)
STATECIVICS_REPO = Path(os.getenv("STATECIVICS_REPO", "")).resolve()
pytestmark = pytest.mark.skipif(
    not os.getenv("STATECIVICS_REPO") or not (STATECIVICS_REPO / "src").is_dir(),
    reason="STATECIVICS_REPO must name the compatible StateCivics checkout",
)


def test_real_statecivics_export_is_accepted_by_fiscal_adapter_cli(
    tmp_path: Path,
) -> None:
    sys.path.insert(0, str(STATECIVICS_REPO / "src"))
    from kansas_accountability.services.civic_impact.custody_store import (
        LocalCustodyStore,
    )
    from kansas_accountability.services.civic_impact.retrieval_exporter import (
        ExporterIdentity,
        build_record,
        render_manifest,
    )

    pdf = b"%PDF-1.7\n% StateCivics to ExAIS contract proof\n"
    digest = hashlib.sha256(pdf).hexdigest()
    custody_root = tmp_path / "custody"
    custody_uri = LocalCustodyStore(custody_root).put("budget", pdf)
    artifact = SimpleNamespace(
        id="artifact-contract-proof",
        logical_key="budget:652:narrative:FY2027",
        source_family="division_of_budget",
        artifact_type="agency_budget_narrative",
        jurisdiction="ocd-jurisdiction/country:us/state:ks/government",
        publisher="Kansas Division of the Budget",
        canonical_url="https://budget.kansas.gov/fy2027/agency-652.pdf",
        license_profile="ks_public_records_review_required",
        redistribution="full",
    )
    revision = SimpleNamespace(
        id="revision-contract-proof",
        source_artifact_id=artifact.id,
        revision_number=1,
        content_hash_sha256=digest,
        object_path=custody_uri,
        custody_status="retained",
        retrieval_url=artifact.canonical_url,
        mime_type="application/pdf",
        byte_size=len(pdf),
        published_at=None,
        effective_from=None,
        effective_to=None,
        as_of_date=None,
        prior_revision_id=None,
        metadata_json={"fiscal_year": "2027", "title": "KSDE Budget Narrative FY2027"},
    )
    record = build_record(
        artifact=artifact,
        revision=revision,
        exporter=ExporterIdentity(
            code_commit="b3f5c09170c66453097bcd4fb44c6eb2b9031f39"
        ),
        target_instance_slug="ks-state-civics",
        target_vector_store_slug="kansas-fiscal-documents",
    )
    manifest = tmp_path / "kansas-fiscal-documents.jsonl"
    manifest.write_text(render_manifest([record]), encoding="utf-8")
    state = tmp_path / "state.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(ADAPTER),
            "--manifest",
            str(manifest),
            "--custody-root",
            str(custody_root),
            "--state",
            str(state),
            "--vector-store-id",
            "vs_contract_proof",
            # WAVE-133 made the contract pin mandatory on every entrypoint.
            "--contract-schema",
            str(CONTRACT_FIXTURE),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    proof, _end = json.JSONDecoder().raw_decode(completed.stdout.lstrip())
    assert proof["record_count"] == 1
    assert proof["planned"] == {"remove": 0, "upsert": 1, "noop": 0}
    assert proof["applied"] is False
    assert not state.exists(), "dry-run must not create adapter state"


def test_marker_handoff_matches_real_statecivics_contract() -> None:
    schema_path = (
        STATECIVICS_REPO
        / "contracts"
        / "civic-impact"
        / "marker-extraction-record.schema.json"
    )
    assert hashlib.sha256(schema_path.read_bytes()).hexdigest() == (
        "a0ff93a4cca17d78f243007861a14f5c6249fb865180c255ca35dd995f617839"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    markdown = (
        b"{0}------------------------------------------------\n"
        b"# Fiscal report\n\n| Fund | Amount |\n|---|---:|\n| SGF | 41.0 |\n"
    )
    markdown_hash = hashlib.sha256(markdown).hexdigest()
    source_hash = "c" * 64
    logical_id = "b" * 64
    custody_uri = f"civic-custody://kansas_fiscal_documents/cc/{source_hash}"
    source_record = {
        "source_revision_id": "revision-contract-proof",
        "logical_document_id": logical_id,
        "content_hash_sha256": source_hash,
        "custody_uri": custody_uri,
        "citation_url": "https://budget.kansas.gov/fy2025-report.pdf",
        "redistribution": "full",
        "mime_type": "application/pdf",
        "record_digest_sha256": "a" * 64,
        "ingestion": {"action": "upsert"},
    }
    state = {
        "action": "upsert",
        "record_digest_sha256": "a" * 64,
        "document_id": "doc-contract-proof",
        "vector_store_file_id": "vsf-contract-proof",
    }
    metadata = {
        "document_id": "doc-contract-proof",
        "vector_store_file_id": "vsf-contract-proof",
        "vector_store_id": "vs-contract-proof",
        "status": "completed",
        "created_at": 1788532800,
        "completed_at": 1788532860,
        "attributes": {
            "source_revision_id": "revision-contract-proof",
            "logical_document_id": logical_id,
            "source_content_hash_sha256": source_hash,
            "custody_uri": custody_uri,
            "citation_url": source_record["citation_url"],
            "pdf_parser": "runpod_marker",
            "marker_profile": "fiscal_tables_page_aware_v1",
            "marker_options": {
                "output_format": "markdown",
                "paginate_output": True,
                "html_tables_in_markdown": True,
                "disable_image_extraction": False,
            },
            "source_pdf_id": f"pdf_sha256_{source_hash[:16]}",
            "marker_job_id": "marker-job-contract-proof",
            "marker_output_format": "markdown",
            "marker_pages": 1,
            "marker_markdown_sha256": markdown_hash,
            "marker_markdown_chars": len(markdown.decode()),
            "marker_page_marker_count": 1,
            "marker_page_marker_first": 0,
            "marker_page_marker_last": 0,
            "marker_page_marker_sequence_complete": True,
            "marker_image_count": 0,
            "marker_table_count": 1,
            "marker_table_row_count": 2,
            "marker_table_cell_count": 4,
        },
    }
    record = build_marker_handoff(
        source_record=source_record,
        state_entry=state,
        file_metadata=metadata,
        markdown_bytes=markdown,
        vector_store_id="vs-contract-proof",
        producer_commit="e" * 40,
    ).record

    assert set(record) == set(schema["required"])
    for field in ("extracted_artifact", "marker", "exais", "producer"):
        contract = schema["properties"][field]
        assert set(contract["required"]) <= set(record[field])
        assert set(record[field]) <= set(contract["properties"])
