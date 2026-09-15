"""Extraction-by-format and destination-routing tests (WAVE-118 review follow-up).

DOCX instruments need no paid remote path, so the local extractor is exercised
against a real DOCX built here rather than a recorded fixture.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
sys.path.insert(0, str(RELEASE))


def _load(filename: str, module_name: str):
    path = RELEASE / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


docx = _load("topeka-docx-extract.py", "topeka_docx_extract")
destinations = _load("topeka-destination-manifests.py", "topeka_destination_manifests")

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def build_docx(body: str, *, media: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {NS}><w:body>{body}</w:body></w:document>')
        archive.writestr("[Content_Types].xml", "<Types/>")
        if media:
            archive.writestr("word/media/image1.png", b"\x89PNG fake")
    return buffer.getvalue()


def para(text: str, style: str | None = None) -> str:
    prefix = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{prefix}<w:r><w:t>{text}</w:t></w:r></w:p>"


def test_a_docx_ordinance_extracts_readable_text_without_a_remote_service():
    payload = build_docx(
        para("ORDINANCE NO. 20658", style="Heading1")
        + para("AN ORDINANCE approving City expenditures.")
    )
    result = docx.extract_docx(payload)
    assert result["usable_text"] is True
    assert "ORDINANCE NO. 20658" in result["normalized_text"]
    assert "approving City expenditures" in result["normalized_text"]
    assert [block["kind"] for block in result["blocks"]] == ["heading", "paragraph"]


def test_docx_tables_are_preserved_as_structure():
    table = (
        "<w:tbl>"
        f"<w:tr><w:tc>{para('Vendor checks')}</w:tc><w:tc>{para('1,181,258.52')}</w:tc></w:tr>"
        f"<w:tr><w:tc>{para('ACH transfers')}</w:tc><w:tc>{para('14,430,631.99')}</w:tc></w:tr>"
        "</w:tbl>"
    )
    result = docx.extract_docx(build_docx(para("Section 3.") + table))
    assert len(result["tables"]) == 1
    assert result["tables"][0]["rows"] == [
        ["Vendor checks", "1,181,258.52"],
        ["ACH transfers", "14,430,631.99"],
    ]
    assert any(block["kind"] == "table" for block in result["blocks"])


def test_a_docx_never_claims_page_coordinates():
    """A DOCX has no fixed pagination; inventing pages would repeat the PDF defect."""
    result = docx.extract_docx(build_docx(para("Text.")))
    codes = {item["code"] for item in result["limitations"]}
    assert "no_page_coordinates" in codes


def test_tracked_changes_are_reported_rather_than_silently_flattened():
    body = (
        para("Clean paragraph.")
        + f'<w:p><w:ins><w:r><w:t>inserted text</w:t></w:r></w:ins>'
          f'<w:del><w:r><w:delText>removed text</w:delText></w:r></w:del></w:p>'
    )
    result = docx.extract_docx(build_docx(body))
    assert result["revisions"]["insertions"] == 1
    assert result["revisions"]["deletions"] == 1
    assert "unresolved_tracked_changes" in {item["code"] for item in result["limitations"]}
    # Deleted runs must not appear in the reading text.
    assert "removed text" not in result["normalized_text"]
    assert "inserted text" in result["normalized_text"]


def test_embedded_media_is_declared_as_not_extracted():
    result = docx.extract_docx(build_docx(para("Exhibit A follows."), media=True))
    assert "embedded_media_not_extracted" in {item["code"] for item in result["limitations"]}


def test_a_file_that_is_not_a_word_document_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("something/else.xml", "<x/>")
    with pytest.raises(ValueError, match="word/document.xml"):
        docx.extract_docx(buffer.getvalue())


def test_an_empty_document_produces_no_usable_text():
    result = docx.extract_docx(build_docx(para("   ")))
    assert result["usable_text"] is False


# --------------------------------------------------------------------------
# destination routing
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://topeka.municipal.codes/TMC/14.40.010", "ks:city:topeka:municipal-code"),
        ("https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf", "ks:city:topeka:ordinances"),
        ("https://files.topeka.gov/community/ordinances/charter/CharterOrdinance126.pdf", "ks:city:topeka:charter-ordinances"),
        ("https://files.topeka.gov/community/resolutions/2026/Resolution09749.pdf", "ks:city:topeka:resolutions"),
    ],
)
def test_each_destination_claims_its_own_documents_and_only_those(url, expected):
    derived, claimants = destinations.prove_routing({"source_uri": url})
    assert derived == expected
    assert claimants == [expected], f"{url} is claimed by {claimants}"


def test_routing_proof_flags_a_record_assigned_to_the_wrong_destination(tmp_path):
    assignments = tmp_path / "assignments.jsonl"
    assignments.write_text(json.dumps({
        "source_document_id": "ks:city:topeka:charter-ordinances:charter-ordinance:126",
        "collection_id": "ks:city:topeka:charter-ordinances",
        "source_uri": "https://files.topeka.gov/community/resolutions/2026/Resolution09749.pdf",
        "content_sha256": "a" * 64,
        "retained_artifact": "raw/x.pdf",
        "record_kind": "ordinance_pdf",
    }) + "\n", encoding="utf-8")
    result = destinations.build(assignments, tmp_path / "missing.jsonl", tmp_path / "missing-worklist.jsonl")
    assert "ROUTING_DISAGREEMENT" in {issue["code"] for issue in result["issues"]}


def test_a_superseded_identity_is_excluded_from_every_destination(tmp_path):
    worklist = tmp_path / "worklist.jsonl"
    worklist.write_text(json.dumps({"source_document_id": "ks:city:topeka:resolutions:resolution:09749"}) + "\n",
                        encoding="utf-8")
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text("".join(json.dumps(row) + "\n" for row in [
        {"source_document_id": "ks:city:topeka:resolutions:resolution:09749",
         "collection_id": "ks:city:topeka:resolutions", "outcome": "downloaded_new",
         "official_url": "https://files.topeka.gov/community/resolutions/2026/Resolution09749.pdf",
         "sha256": "b" * 64, "saved_path": "x/09749/bb.pdf"},
        {"source_document_id": "ks:city:topeka:resolutions:resolution:resolution09749",
         "collection_id": "ks:city:topeka:resolutions", "outcome": "downloaded_new",
         "official_url": "https://files.topeka.gov/community/resolutions/2026/Resolution09749.pdf",
         "sha256": "b" * 64, "saved_path": "x/old/bb.pdf"},
    ]), encoding="utf-8")

    result = destinations.build(tmp_path / "missing.jsonl", checkpoint, worklist)
    assert [row["source_document_id"] for row in result["records"]] == [
        "ks:city:topeka:resolutions:resolution:09749"
    ]
    assert [row["code"] for row in result["superseded"]] == ["SUPERSEDED_IDENTITY"]


def test_a_corrected_url_is_carried_into_the_destination_manifest(tmp_path):
    worklist = tmp_path / "worklist.jsonl"
    worklist.write_text(json.dumps({"source_document_id": "ks:city:topeka:ordinances:ordinance:20632"}) + "\n",
                        encoding="utf-8")
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(json.dumps({
        "source_document_id": "ks:city:topeka:ordinances:ordinance:20632",
        "collection_id": "ks:city:topeka:ordinances",
        "outcome": "downloaded_corrected_url",
        "official_url": "https://files.topeka.gov/community/ordinances/2026/Ordinancec.pdf",
        "listing_url": "https://files.topeka.gov/community/ordinances/2026/Ordinancec.pdf",
        "fetched_url": "https://files.topeka.gov/community/ordinances/2026/Ordinance20632.pdf",
        "url_resolution": "evidenced_correction",
        "sha256": "c" * 64, "saved_path": "x/20632/cc.pdf",
    }) + "\n", encoding="utf-8")

    result = destinations.build(tmp_path / "missing.jsonl", checkpoint, worklist)
    record = result["records"][0]
    assert record["source_uri"].endswith("Ordinance20632.pdf"), "the bytes came from the corrected URL"
    assert record["listing_url"].endswith("Ordinancec.pdf"), "the broken listing URL must survive"
    assert record["url_resolution"] == "evidenced_correction"
    assert not result["issues"]
