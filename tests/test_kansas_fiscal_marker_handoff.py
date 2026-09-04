from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from svs_common.fiscal_marker_handoff import (
    MarkerHandoffError,
    build_marker_handoff,
)

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
SCRIPT = RELEASE / "kansas-fiscal-marker-handoff.py"
sys.path.insert(0, str(RELEASE))


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "kansas_fiscal_marker_handoff_command", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


command = _load_script()
MARKDOWN = (
    "{0}"
    + "-" * 48
    + "\n# Kansas FY2025\n\n| Fund | Amount |\n|---|---:|\n| SGF | $41.0 |\n"
)
MARKDOWN_BYTES = MARKDOWN.encode("utf-8")
MARKDOWN_SHA256 = hashlib.sha256(MARKDOWN_BYTES).hexdigest()
SOURCE_SHA256 = "c" * 64
LOGICAL_ID = "b" * 64
PRODUCER_COMMIT = "e" * 40


def _source_record() -> dict:
    return {
        "logical_document_id": LOGICAL_ID,
        "source_revision_id": "revision-1",
        "content_hash_sha256": SOURCE_SHA256,
        "custody_uri": (f"civic-custody://kansas_fiscal_documents/cc/{SOURCE_SHA256}"),
        "citation_url": "https://budget.kansas.gov/fy2025-report.pdf",
        "mime_type": "application/pdf",
        "redistribution": "full",
        "record_digest_sha256": "a" * 64,
        "ingestion": {"action": "upsert"},
    }


def _state_entry() -> dict:
    return {
        "action": "upsert",
        "record_digest_sha256": "a" * 64,
        "document_id": "doc-1",
        "vector_store_file_id": "vsf-1",
    }


def _file_metadata() -> dict:
    return {
        "document_id": "doc-1",
        "vector_store_file_id": "vsf-1",
        "vector_store_id": "vs-fiscal",
        "status": "completed",
        "attributes": {
            "source_revision_id": "revision-1",
            "logical_document_id": LOGICAL_ID,
            "source_content_hash_sha256": SOURCE_SHA256,
            "custody_uri": (
                f"civic-custody://kansas_fiscal_documents/cc/{SOURCE_SHA256}"
            ),
            "citation_url": "https://budget.kansas.gov/fy2025-report.pdf",
            "pdf_parser": "runpod_marker",
            "marker_profile": "fiscal_tables_page_aware_v1",
            "marker_options": {
                "output_format": "markdown",
                "paginate_output": True,
                "html_tables_in_markdown": True,
                "disable_image_extraction": False,
            },
            "source_pdf_id": f"pdf_sha256_{SOURCE_SHA256[:16]}",
            "marker_job_id": "marker-job-1",
            "marker_output_format": "markdown",
            "marker_pages": 31,
            "marker_markdown_sha256": MARKDOWN_SHA256,
            "marker_markdown_chars": len(MARKDOWN),
            "marker_page_marker_count": 1,
            "marker_page_marker_first": 0,
            "marker_page_marker_last": 0,
            "marker_page_marker_sequence_complete": True,
            "marker_image_count": 2,
            "marker_table_count": 1,
            "marker_table_row_count": 2,
            "marker_table_cell_count": 4,
        },
    }


def _artifact():
    return build_marker_handoff(
        source_record=_source_record(),
        state_entry=_state_entry(),
        file_metadata=_file_metadata(),
        markdown_bytes=MARKDOWN_BYTES,
        vector_store_id="vs-fiscal",
        producer_commit=PRODUCER_COMMIT,
    )


def test_builder_binds_persisted_markdown_to_statecivics_revision() -> None:
    artifact = _artifact()
    record = artifact.record

    assert artifact.markdown_bytes == MARKDOWN_BYTES
    assert record["source_revision_id"] == "revision-1"
    assert record["source_content_hash_sha256"] == SOURCE_SHA256
    assert record["extracted_artifact"] == {
        "mime_type": "text/markdown",
        "relative_path": f"extracted/{MARKDOWN_SHA256}.md",
        "content_hash_sha256": MARKDOWN_SHA256,
        "byte_count": len(MARKDOWN_BYTES),
        "character_count": len(MARKDOWN),
        "page_marker_count": 1,
        "table_count": 1,
        "table_row_count": 2,
        "table_cell_count": 4,
    }
    assert record["exais"]["content_api_path"] == "/v1/files/doc-1/content"
    assert record["marker"]["profile"] == "fiscal_tables_page_aware_v1"
    assert record["marker"]["options"]["paginate_output"] is True
    assert record["marker"]["image_count"] == 2
    shadow = dict(record)
    digest = shadow.pop("record_digest_sha256")
    assert (
        digest
        == hashlib.sha256(
            json.dumps(
                shadow, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda metadata: metadata["attributes"].update(
                marker_markdown_sha256="0" * 64
            ),
            "marker_markdown_sha256",
        ),
        (
            lambda metadata: metadata["attributes"].update(
                source_revision_id="wrong-revision"
            ),
            "source_revision_id",
        ),
        (
            lambda metadata: metadata.update(status="in_progress"),
            "not completed",
        ),
    ],
)
def test_builder_fails_closed_on_persisted_metadata_mismatch(
    mutation, message: str
) -> None:
    metadata = _file_metadata()
    mutation(metadata)
    with pytest.raises(MarkerHandoffError, match=message):
        build_marker_handoff(
            source_record=_source_record(),
            state_entry=_state_entry(),
            file_metadata=metadata,
            markdown_bytes=MARKDOWN_BYTES,
            vector_store_id="vs-fiscal",
            producer_commit=PRODUCER_COMMIT,
        )


def test_builder_refuses_markdown_without_real_page_delimiters() -> None:
    markdown = b"# Page labels were not preserved\n"
    metadata = _file_metadata()
    metadata["attributes"].update(
        {
            "marker_markdown_sha256": hashlib.sha256(markdown).hexdigest(),
            "marker_markdown_chars": len(markdown.decode()),
            "marker_page_marker_count": 0,
            "marker_page_marker_first": None,
            "marker_page_marker_last": None,
            "marker_page_marker_sequence_complete": False,
            "marker_table_count": 0,
            "marker_table_row_count": 0,
            "marker_table_cell_count": 0,
        }
    )
    with pytest.raises(MarkerHandoffError, match="no page delimiters"):
        build_marker_handoff(
            source_record=_source_record(),
            state_entry=_state_entry(),
            file_metadata=metadata,
            markdown_bytes=markdown,
            vector_store_id="vs-fiscal",
            producer_commit=PRODUCER_COMMIT,
        )


def test_command_fetches_persisted_content_without_marker_call() -> None:
    calls: list[tuple[str, str]] = []

    def fetch_json(method, api_base, path, payload, **_kwargs):
        assert payload is None
        calls.append((method, path))
        return _file_metadata()

    def fetch_bytes(method, api_base, path, **_kwargs):
        calls.append((method, path))
        return MARKDOWN_BYTES

    artifacts = command.collect_handoff_artifacts(
        records=[_source_record()],
        state={"records": {LOGICAL_ID: _state_entry()}},
        vector_store_id="vs-fiscal",
        producer_commit=PRODUCER_COMMIT,
        api_base="https://exais.invalid",
        headers={},
        timeout=30,
        cell="ks-state-civics",
        transport="host-curl",
        fetch_json=fetch_json,
        fetch_bytes=fetch_bytes,
    )

    assert len(artifacts) == 1
    assert calls == [
        ("GET", "/v1/vector_stores/vs-fiscal/files/vsf-1"),
        ("GET", "/v1/files/doc-1/content"),
    ]


def test_handoff_package_is_byte_identical_on_repeat(tmp_path: Path) -> None:
    output = tmp_path / "handoff"
    first = command.write_handoff_package(
        output,
        [_artifact()],
        source_manifest_sha256="f" * 64,
        producer_commit=PRODUCER_COMMIT,
    )
    before = {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }

    second = command.write_handoff_package(
        output,
        [_artifact()],
        source_manifest_sha256="f" * 64,
        producer_commit=PRODUCER_COMMIT,
    )
    after = {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }

    assert second == first
    assert after == before
    assert set(after) == {
        Path("manifest.jsonl"),
        Path("handoff-proof.json"),
        Path("extracted") / f"{MARKDOWN_SHA256}.md",
    }


def test_plan_makes_no_api_call_or_write(tmp_path: Path, monkeypatch, capsys) -> None:
    source = _source_record()
    manifest_path = tmp_path / "manifest.jsonl"
    # The dry-run still uses the production manifest validator. Import its
    # digest helper so this fixture follows the exact desired-state contract.
    ingest = command._load_ingest_command()
    source.update(
        {
            "export_record_id": "1" * 64,
            "revision_number": 1,
            "custody_status": "retained",
            "publisher": "Kansas Division of the Budget",
            "jurisdiction": "Kansas",
            "artifact_type": "budget_report",
            "record_digest_algorithm": "statecivics-canonical-json-v1",
            "title": "Kansas FY2025 Budget Report",
            "effective_period": {"fiscal_year": 2025},
            "exporter": {
                "name": "statecivics-retrieval-exporter",
                "version": "1",
                "code_commit": "a" * 40,
            },
            "lifecycle": {"state": "current", "removal_required": False},
        }
    )
    source["ingestion"] = {
        "mode": "api_only",
        "action": "upsert",
        "target_instance_slug": "ks-state-civics",
        "target_vector_store_slug": "kansas-fiscal-documents",
        "recall_evaluation_required": True,
    }
    source["record_digest_sha256"] = ingest.record_digest(source)
    manifest_path.write_text(
        json.dumps(source, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "vector_store_id": "vs-fiscal",
                "records": {LOGICAL_ID: _state_entry()},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        command,
        "collect_handoff_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("API called")),
    )

    assert (
        command.main(
            [
                "--manifest",
                str(manifest_path),
                "--state",
                str(state_path),
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    assert not (tmp_path / "output").exists()
    assert '"marker_requests": 0' in capsys.readouterr().out
