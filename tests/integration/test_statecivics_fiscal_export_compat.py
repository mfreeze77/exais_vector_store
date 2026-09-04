from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "scripts" / "release" / "kansas-fiscal-document-ingest.py"
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
