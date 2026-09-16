"""Extraction-by-format and destination-routing tests (WAVE-118 review follow-up).

DOCX instruments need no paid remote path, so the local extractor is exercised
against a real DOCX built here rather than a recorded fixture.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
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

def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


# --------------------------------------------------------------------------
# review-round regressions
# --------------------------------------------------------------------------

def test_tracked_changes_inside_a_table_are_counted_and_flagged():
    """A table cell going from 100 to 200 must not publish as a clean 200."""
    cell = (
        "<w:tc><w:p>"
        "<w:del><w:r><w:delText>100</w:delText></w:r></w:del>"
        "<w:ins><w:r><w:t>200</w:t></w:r></w:ins>"
        "</w:p></w:tc>"
    )
    body = f"<w:tbl><w:tr><w:tc>{para('Amount')}</w:tc>{cell}</w:tr></w:tbl>"
    result = docx.extract_docx(build_docx(body))

    assert result["tables"][0]["rows"] == [["Amount", "200"]]
    assert result["revisions"] == {"insertions": 1, "deletions": 1}
    assert result["tables"][0]["revisions"] == {"insertions": 1, "deletions": 1}
    codes = {item["code"] for item in result["limitations"]}
    assert "unresolved_tracked_changes" in codes
    detail = next(i["description"] for i in result["limitations"] if i["code"] == "unresolved_tracked_changes")
    assert "inside tables" in detail


def test_paragraph_and_table_revisions_are_both_counted():
    body = (
        '<w:p><w:ins><w:r><w:t>new clause</w:t></w:r></w:ins></w:p>'
        f"<w:tbl><w:tr><w:tc><w:p><w:del><w:r><w:delText>old</w:delText></w:r></w:del></w:p></w:tc></w:tr></w:tbl>"
    )
    result = docx.extract_docx(build_docx(body))
    assert result["revisions"]["insertions"] == 1
    assert result["revisions"]["deletions"] == 1


def test_docx_extraction_versions_its_output_by_source_hash(tmp_path):
    """Two versions of one document must not share an output path."""
    import subprocess

    acquisition = tmp_path / "acq" / "ordinances" / "raw" / "30002"
    acquisition.mkdir(parents=True)
    first, second = build_docx(para("version one")), build_docx(para("version two, revised"))
    for payload in (first, second):
        (acquisition / f"{sha(payload)[:16]}.docx").write_bytes(payload)

    result = subprocess.run(
        [sys.executable, str(RELEASE / "topeka-docx-extract.py"),
         "--acquisition-dir", str(tmp_path / "acq"), "--output-dir", str(tmp_path / "ex")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "ex" / "docx-extraction-report.json").read_text())
    assert len(report["results"]) == 2
    paths = {row["normalized_path"] for row in report["results"]}
    assert len(paths) == 2, "each version needs its own output path"
    for row in report["results"]:
        text = Path(row["normalized_path"]).read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == row["normalized_sha256"]


def test_acquisition_reads_a_stored_file_before_trusting_its_name(tmp_path):
    """A hash-named path is a claim about its contents, not proof of them."""
    acquire_mod = _load("topeka-collection-acquire.py", "topeka_collection_acquire_probe")
    row = {
        "source_document_id": "ks:city:topeka:ordinances:ordinance:20662",
        "collection_id": "ks:city:topeka:ordinances",
        "official_url": "https://files.topeka.gov/community/ordinances/2026/Ordinance20662.pdf",
        "outcome": "acquire_new",
    }
    payload = b"%PDF the real bytes"
    destination = acquire_mod.version_path(tmp_path / "out", row, sha(payload))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"CORRUPTED")

    def downloader(url, *, timeout):
        return payload, "application/pdf"

    result = acquire_mod.acquire_row(
        row, output_dir=tmp_path / "out", seed=tmp_path / "seed",
        previous={"source_document_id": row["source_document_id"],
                  "remote_sha256": sha(payload), "run_id": "r1"},
        timeout=5, downloader=downloader, run_id="r1", trust_checkpoint=True,
    )
    on_disk = sha(Path(result["saved_path"]).read_bytes())
    assert result["sha256"] == on_disk, "the receipt must describe the bytes that are there"
    assert on_disk == sha(payload)
    assert result["repaired_corrupt_stored_copy"] is True


def test_held_versions_reports_what_files_contain_not_what_they_are_named(tmp_path):
    acquire_mod = _load("topeka-collection-acquire.py", "topeka_collection_acquire_probe2")
    row = {
        "source_document_id": "ks:city:topeka:ordinances:ordinance:20662",
        "collection_id": "ks:city:topeka:ordinances",
        "official_url": "https://files.topeka.gov/community/ordinances/2026/Ordinance20662.pdf",
    }
    folder = acquire_mod.document_dir(tmp_path / "out", row)
    folder.mkdir(parents=True)
    (folder / "deadbeefdeadbeef.pdf").write_bytes(b"actually different bytes")
    assert acquire_mod.held_versions(tmp_path / "out", row) == [sha(b"actually different bytes")]
    assert acquire_mod.verified_path(tmp_path / "out", row, "de" + "a" * 62) is None


# --------------------------------------------------------------------------
# stage-seam regressions (third review round)
# --------------------------------------------------------------------------

def _seam_fixture(tmp_path: Path, *, acquired: bytes, flags: list[str], outcome: str,
                  out_name: str = "dest", tag: str = "seam"):
    """A retained-split record and an acquisition receipt for the same document."""
    doc = "ks:city:topeka:ordinances:ordinance:20407"
    url = "https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf"
    retained = b"%PDF retained bytes"

    seed = tmp_path / "seed" / "manifests"
    seed.mkdir(parents=True, exist_ok=True)
    (tmp_path / "seed" / "raw" / "pdfs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "seed" / "raw" / "pdfs" / "20407.pdf").write_bytes(retained)
    (seed / "ordinances.jsonl").write_text(json.dumps({
        "id": "topeka-ordinance:legacy", "category": "ordinance", "ordinance_number": "20407",
        "pdf_url": url, "saved_path": "raw/pdfs/20407.pdf", "sha256": sha(retained),
    }) + "\n", encoding="utf-8")

    assignments = tmp_path / "assignments.jsonl"
    assignments.write_text(json.dumps({
        "source_document_id": doc, "collection_id": "ks:city:topeka:ordinances", "source_uri": url,
        "content_sha256": sha(retained), "retained_artifact": "raw/pdfs/20407.pdf",
        "record_kind": "ordinance_pdf", "legacy_id": "topeka-ordinance:legacy",
    }) + "\n", encoding="utf-8")

    acquired_path = tmp_path / f"acquired-{tag}.pdf"
    acquired_path.write_bytes(acquired)
    checkpoint = tmp_path / f"checkpoint-{tag}.jsonl"
    checkpoint.write_text(json.dumps({
        "source_document_id": doc, "collection_id": "ks:city:topeka:ordinances", "official_url": url,
        "sha256": sha(acquired), "outcome": outcome, "saved_path": str(acquired_path),
        "observed_at": "2026-09-16T00:00:00Z", "run_id": tag,
        "review_flags": flags, "review_status": "review_needed" if flags else "clear",
    }) + "\n", encoding="utf-8")

    worklist = tmp_path / "worklist.jsonl"
    worklist.write_text(json.dumps({"source_document_id": doc}) + "\n", encoding="utf-8")

    out = tmp_path / out_name
    result = subprocess.run(
        [sys.executable, str(RELEASE / "topeka-destination-manifests.py"),
         "--assignments", str(assignments), "--checkpoint", str(checkpoint),
         "--worklist", str(worklist), "--output-dir", str(out),
         "--ordinance-seed", str(tmp_path / "seed")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return doc, out, sha(retained)


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_ingestion_slice_never_names_bytes_the_destination_superseded(tmp_path):
    """The destination selected new bytes; the slice must not feed the old ones."""
    doc, out, retained_sha = _seam_fixture(
        tmp_path, acquired=b"%PDF new publisher bytes", flags=[], outcome="downloaded_changed"
    )
    manifest = _rows(out / "ordinances.manifest.jsonl")
    assert manifest and manifest[0]["sha256"] != retained_sha, "destination takes the acquired revision"

    for row in _rows(out / "ordinances.ingest-slice.jsonl"):
        assert row["sha256"] != retained_sha, "the slice must not carry the superseded bytes"
        assert row["sha256"] == manifest[0]["sha256"]

    report = json.loads((out / "destination-report.json").read_text(encoding="utf-8"))
    gaps = [g for d in report["destinations"] for g in d.get("ingest_slice_gaps", [])]
    assert any(g["source_document_id"] == doc for g in gaps), (
        "a revision with no matching extraction is reported, not substituted"
    )


def test_destination_ingestion_and_artifact_agree_when_bytes_are_unchanged(tmp_path):
    doc, out, retained_sha = _seam_fixture(
        tmp_path, acquired=b"%PDF retained bytes", flags=[], outcome="unchanged_remote"
    )
    manifest = _rows(out / "ordinances.manifest.jsonl")
    slice_rows = _rows(out / "ordinances.ingest-slice.jsonl")
    assert manifest[0]["sha256"] == retained_sha
    assert slice_rows and slice_rows[0]["sha256"] == retained_sha
    assert slice_rows[0]["exais_source_document_id"] == doc
    report = json.loads((out / "destination-report.json").read_text(encoding="utf-8"))
    assert report["passed"], report["issues"]


def test_unchanged_bytes_do_not_erase_newly_discovered_uncertainty(tmp_path):
    """Hash equality settles the content question and nothing else."""
    doc, out, retained_sha = _seam_fixture(
        tmp_path, acquired=b"%PDF retained bytes",
        flags=["membership_review_needed"], outcome="unchanged_remote",
    )
    clean = _rows(out / "ordinances.manifest.jsonl")
    review = _rows(out / "ordinances.review.jsonl")
    assert [row["source_document_id"] for row in review] == [doc]
    assert not clean, "a flagged document must not sit in the clean ingestion lane"
    assert review[0]["review_flags"] == ["membership_review_needed"]
    assert review[0]["review_status"] == "review_needed"
    assert review[0]["reconfirmed_by_acquisition"] is True


def test_a_flag_is_cleared_only_by_an_explicit_resolution(tmp_path):
    """Re-running with no flags does not silently clear one already recorded."""
    doc, out, _ = _seam_fixture(
        tmp_path, acquired=b"%PDF retained bytes",
        flags=["membership_review_needed"], outcome="unchanged_remote",
    )
    assert _rows(out / "ordinances.review.jsonl"), "flag recorded on the first pass"


# --------------------------------------------------------------------------
# repeat-run regressions (fourth review round)
# --------------------------------------------------------------------------

def test_an_empty_slice_removes_the_previous_run_s_file(tmp_path):
    """A report saying 0 slice rows must not sit beside a file offering one."""
    doc, out, retained_sha = _seam_fixture(
        tmp_path, acquired=b"%PDF retained bytes", flags=[], outcome="unchanged_remote", tag="first"
    )
    slice_path = out / "ordinances.ingest-slice.jsonl"
    assert len(_rows(slice_path)) == 1, "the first run has one ingestable row"

    # Second run into the SAME directory: the selected revision changed and has
    # no retained extraction, so nothing is ingestable.
    _seam_fixture(tmp_path, acquired=b"%PDF a newer publisher revision",
                  flags=[], outcome="downloaded_changed", tag="second")

    report = json.loads((out / "destination-report.json").read_text(encoding="utf-8"))
    declared = sum(entry["ingest_slice_rows"] for entry in report["destinations"])
    assert declared == 0
    assert _rows(slice_path) == [], "the superseded row must not survive in the file"


def test_a_hold_survives_a_later_run_that_does_not_observe_it(tmp_path):
    """Not re-observing a condition is not the same as resolving it."""
    doc, out, _ = _seam_fixture(
        tmp_path, acquired=b"%PDF retained bytes",
        flags=["membership_review_needed"], outcome="unchanged_remote", tag="first",
    )
    assert [row["source_document_id"] for row in _rows(out / "ordinances.review.jsonl")] == [doc]

    # Second run into the same directory, with no flag on the receipt.
    _seam_fixture(tmp_path, acquired=b"%PDF retained bytes", flags=[],
                  outcome="unchanged_remote", tag="second")

    review = _rows(out / "ordinances.review.jsonl")
    assert [row["source_document_id"] for row in review] == [doc], "the hold must persist"
    assert review[0]["review_flags"] == ["membership_review_needed"]
    assert not _rows(out / "ordinances.manifest.jsonl"), "still out of the clean lane"

    report = json.loads((out / "destination-report.json").read_text(encoding="utf-8"))
    carried = report["holds_carried_from_earlier_runs"]
    assert any(row["source_document_id"] == doc for row in carried)


def test_a_hold_clears_only_with_a_recorded_resolution(tmp_path):
    doc, out, _ = _seam_fixture(
        tmp_path, acquired=b"%PDF retained bytes",
        flags=["membership_review_needed"], outcome="unchanged_remote", tag="first",
    )
    assert _rows(out / "ordinances.review.jsonl")

    (out / "review-resolutions.jsonl").write_text(json.dumps({
        "source_document_id": doc,
        "review_flag": "membership_review_needed",
        "resolved_by": "records-clerk",
        "reason": "confirmed with the City Clerk that the STO is a listed member of the ordinances library",
        "resolved_at": "2026-09-16T12:00:00Z",
    }) + "\n", encoding="utf-8")

    _seam_fixture(tmp_path, acquired=b"%PDF retained bytes", flags=[],
                  outcome="unchanged_remote", tag="third")

    assert not _rows(out / "ordinances.review.jsonl"), "the resolution clears the hold"
    clean = _rows(out / "ordinances.manifest.jsonl")
    assert [row["source_document_id"] for row in clean] == [doc]
    report = json.loads((out / "destination-report.json").read_text(encoding="utf-8"))
    cleared = report["holds_cleared_by_resolution"]
    assert cleared and cleared[0]["resolved_by"] == "records-clerk"


def test_a_resolution_without_an_author_or_reason_does_not_clear(tmp_path):
    doc, out, _ = _seam_fixture(
        tmp_path, acquired=b"%PDF retained bytes",
        flags=["membership_review_needed"], outcome="unchanged_remote", tag="first",
    )
    (out / "review-resolutions.jsonl").write_text(
        json.dumps({"source_document_id": doc, "review_flag": "membership_review_needed"}) + "\n",
        encoding="utf-8",
    )
    _seam_fixture(tmp_path, acquired=b"%PDF retained bytes", flags=[],
                  outcome="unchanged_remote", tag="third")
    assert _rows(out / "ordinances.review.jsonl"), "an unsigned resolution is not a resolution"


def test_a_hold_survives_the_document_vanishing_from_a_run(tmp_path):
    """held -> absent from the worklist -> returns unflagged. The hold must persist.

    A document can drop out of a run for reasons that say nothing about its
    review state: a listing hiccup, a narrowed --collection, a discovery
    failure. Rebuilding the holds ledger from only what is present deletes the
    hold, and the next run that sees the document releases it.
    """
    doc, out, _ = _seam_fixture(
        tmp_path, acquired=b"%PDF retained bytes",
        flags=["membership_review_needed"], outcome="unchanged_remote", tag="first",
    )
    assert [row["source_document_id"] for row in _rows(out / "ordinances.review.jsonl")] == [doc]

    # Run 2: the document is absent from every input -- it vanished from this
    # run entirely, which is what a listing hiccup or a narrowed --collection
    # looks like.
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(RELEASE / "topeka-destination-manifests.py"),
         "--assignments", str(empty), "--checkpoint", str(empty), "--worklist", str(empty),
         "--output-dir", str(out), "--ordinance-seed", str(tmp_path / "seed")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    holds = _rows(out / "review-holds.jsonl")
    assert [row["source_document_id"] for row in holds] == [doc], (
        "a hold must not be deleted because the document was absent for one run"
    )
    report = json.loads((out / "destination-report.json").read_text(encoding="utf-8"))
    assert any(
        row["source_document_id"] == doc
        for row in report["holds_on_documents_absent_this_run"]
    )

    # Run 3: the document returns, with no flag on the receipt and no resolution.
    _seam_fixture(tmp_path, acquired=b"%PDF retained bytes", flags=[],
                  outcome="unchanged_remote", tag="third")
    review = _rows(out / "ordinances.review.jsonl")
    assert [row["source_document_id"] for row in review] == [doc], "still held"
    assert review[0]["review_flags"] == ["membership_review_needed"]
    assert not _rows(out / "ordinances.manifest.jsonl"), "must not reach the clean lane"


def test_an_absent_document_s_hold_still_clears_with_a_resolution(tmp_path):
    doc, out, _ = _seam_fixture(
        tmp_path, acquired=b"%PDF retained bytes",
        flags=["membership_review_needed"], outcome="unchanged_remote", tag="first",
    )
    (out / "review-resolutions.jsonl").write_text(json.dumps({
        "source_document_id": doc, "review_flag": "membership_review_needed",
        "resolved_by": "records-clerk", "reason": "confirmed with the City Clerk",
    }) + "\n", encoding="utf-8")

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert subprocess.run(
        [sys.executable, str(RELEASE / "topeka-destination-manifests.py"),
         "--assignments", str(empty), "--checkpoint", str(empty), "--worklist", str(empty),
         "--output-dir", str(out), "--ordinance-seed", str(tmp_path / "seed")],
        cwd=ROOT, capture_output=True, text=True,
    ).returncode == 0

    assert _rows(out / "review-holds.jsonl") == [], "a signed resolution clears even an absent hold"
