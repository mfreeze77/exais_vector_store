"""Discovery and acquisition tests for the Topeka master listings (WAVE-118 assignment 2).

The fixture mirrors the shape of the real Revize document centre, including the
awkward parts the live pages actually contain: a category whose members sit in
year sub-groups, a category with no sub-groups, a document linked from the page
intro rather than the centre, a `.docx` instrument, a repeated listing entry and
a stale link to a retired bucket.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
sys.path.insert(0, str(RELEASE))

import jurisdiction_release_contract as contract  # noqa: E402


def _load(filename: str, module_name: str):
    path = RELEASE / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


discover = _load("topeka-collection-discover.py", "topeka_collection_discover")
acquire = _load("topeka-collection-acquire.py", "topeka_collection_acquire")

ORDINANCE_LISTING = "https://topeka.gov/community/ordinances/index.php"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file(url: str, label: str) -> str:
    return f'<li><a href="{url}" target="_blank"><span class="fa fa-file-text-o"></span>{label}</a></li>'


def _counter(n: int) -> str:
    return f'<span class="fa fa-caret-down"></span><small class="doc-center-counter">{n} documents</small>'


ORDINANCE_HTML = f"""<html><body>
<h1>Ordinances</h1>
Only ordinances within the last four years are located on this website.
<a href="https://cot-wp-uploads.s3.amazonaws.com/wp-content/uploads/legal/STO.pdf"></a>
<ul>
{_file("https://files.topeka.gov/community/ordinances/other-ordinances/STO.pdf", "Standard Traffic Ordinance")}
</ul>

<a class="rz-doc-center-hash" name="outer-538"></a>
<h3 class="docs-toggle clearfix">Charter Ordinances{_counter(2)}</h3>
<ul class="file-group">
{_file("https://files.topeka.gov/community/ordinances/charter/CharterOrdinance125.pdf", "125")}
{_file("https://files.topeka.gov/community/ordinances/charter/CharterOrdinance126.pdf", "126")}
</ul>

<a class="rz-doc-center-hash" name="outer-539"></a>
<h3 class="docs-toggle clearfix">Ordinances{_counter(5)}</h3>
<ul class="file-group">
{_file("https://files.topeka.gov/community/ordinances/2026/Ordinance20684.pdf", "20684")}
</ul>
  <a class="rz-doc-center-sub-hash" name="sub-2377"></a>
  <h4 class="docs-toggle clearfix">2026{_counter(3)}</h4>
  <ul class="file-group">
{_file("https://files.topeka.gov/community/ordinances/2026/Ordinance20661.docx", "20661")}
{_file("https://files.topeka.gov/community/ordinances/2026/Ordinance20661.docx", "20661")}
{_file("https://s3.us-east-1.amazonaws.com/files.topeka.gov/community/ordinances/2026/Ordinance20662.pdf", "20662")}
  </ul>
  <a class="rz-doc-center-sub-hash" name="sub-549"></a>
  <h4 class="docs-toggle clearfix">2023{_counter(1)}</h4>
  <ul class="file-group">
{_file("https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf", "20407")}
  </ul>
</body></html>"""


@pytest.fixture
def result():
    return discover.discover_listing(
        "ordinances", html_bytes=ORDINANCE_HTML.encode("utf-8"), source_url=ORDINANCE_LISTING
    )


def by_id(result) -> dict:
    return {row["source_document_id"]: row for row in result["documents"]}


def groups(result) -> dict:
    return {row["label"]: row for row in result["groups"]}


def codes(findings) -> set[str]:
    return {finding["code"] for finding in findings}


def errors(findings) -> set[str]:
    return {f["code"] for f in findings if f["severity"] == "error"}


# --------------------------------------------------------------------------
# parsing the document centre
# --------------------------------------------------------------------------

def test_categories_and_year_groups_are_read_from_the_publisher(result):
    found = groups(result)
    assert found["Charter Ordinances"]["level"] == "category"
    assert found["Charter Ordinances"]["declared_count"] == 2
    assert found["2026"]["level"] == "group"
    assert found["2026"]["parent"] == "Ordinances"
    assert found["2023"]["declared_count"] == 1


def test_year_navigation_does_not_split_a_collection(result):
    """2026 and 2023 are groups inside one store, not two stores."""
    assert {row["collection_id"] for row in result["documents"] if row["listing_group"] in {"2026", "2023"}} == {
        "ks:city:topeka:ordinances"
    }


def test_two_categories_on_one_page_stay_separate_collections(result):
    # 2 charter; 5 ordinances: 20684, 20661, 20662, 20407 and the STO.
    assert result["by_collection"] == {
        "ks:city:topeka:charter-ordinances": 2,
        "ks:city:topeka:ordinances": 5,
    }


def test_non_pdf_instruments_are_inventoried_not_dropped(result):
    docx = by_id(result)["ks:city:topeka:ordinances:ordinance:20661"]
    assert docx["media_type"].endswith("wordprocessingml.document")
    assert docx["extraction_supported"] is False
    assert codes(discover.reconcile(result)) >= {"EXTRACTION_UNSUPPORTED_MEDIA"}


def test_repeated_listing_entry_counts_once_as_a_document(result):
    """The publisher's count includes the repeat; our document set must not."""
    found = groups(result)["2026"]
    assert found["declared_count"] == found["listed_entries"] == 3
    assert found["duplicate_entries"] == 1
    assert found["distinct_documents"] == 2
    assert len([row for row in result["documents"] if row["listing_group"] == "2026"]) == 2


def test_host_alias_does_not_create_a_second_document(result):
    row = by_id(result)["ks:city:topeka:ordinances:ordinance:20662"]
    assert row["official_url"] == "https://files.topeka.gov/community/ordinances/2026/Ordinance20662.pdf"


def test_a_retired_bucket_never_becomes_the_official_url(result):
    sto = by_id(result)["ks:city:topeka:ordinances:ordinance:sto"]
    assert sto["official_url"] == "https://files.topeka.gov/community/ordinances/other-ordinances/STO.pdf"
    assert sto["legacy_urls"] == ["https://cot-wp-uploads.s3.amazonaws.com/wp-content/uploads/legal/STO.pdf"]
    assert sto["official_url"] not in sto["alias_urls"]


def test_unnumbered_document_survives_discovery(result):
    """The Standard Traffic Ordinance is not dropped for lacking a number."""
    assert "ks:city:topeka:ordinances:ordinance:sto" in by_id(result)


def test_link_outside_the_document_centre_is_flagged_not_silently_admitted(result):
    sto = by_id(result)["ks:city:topeka:ordinances:ordinance:sto"]
    assert sto["membership"] == "outside_document_centre_review_needed"
    assert "MEMBERSHIP_REVIEW_NEEDED" in codes(discover.reconcile(result))


def test_document_listed_at_category_level_is_still_found(result):
    """20684 sits under the category, in no year group."""
    row = by_id(result)["ks:city:topeka:ordinances:ordinance:20684"]
    assert row["listing_category"] == "Ordinances"
    assert row["listing_group"] is None


def test_clean_listing_reconciles_without_errors(result):
    assert errors(discover.reconcile(result)) == set()


# --------------------------------------------------------------------------
# reconciliation against the publisher's own counts
# --------------------------------------------------------------------------

def test_a_group_we_under_parse_is_an_error(result):
    result["groups"] = [
        {**group, "declared_count": group["declared_count"] + 5} if group["label"] == "2023" else group
        for group in result["groups"]
    ]
    assert "GROUP_COUNT_MISMATCH" in errors(discover.reconcile(result))


def test_a_declared_group_we_parse_as_empty_is_a_failure_not_a_clean_run():
    """A parser failure must never look like an empty successful listing."""
    html = ORDINANCE_HTML.replace(
        _file("https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf", "20407"), ""
    )
    result = discover.discover_listing("ordinances", html_bytes=html.encode(), source_url=ORDINANCE_LISTING)
    assert "EMPTY_DECLARED_GROUP" in errors(discover.reconcile(result))


def test_an_unregistered_source_is_reported_rather_than_given_a_collection():
    html = ORDINANCE_HTML.replace(
        "https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf",
        "https://example.invalid/some/other/Document.pdf",
    )
    result = discover.discover_listing("ordinances", html_bytes=html.encode(), source_url=ORDINANCE_LISTING)
    assert "UNROUTED_DOCUMENT" in errors(discover.reconcile(result))


# --------------------------------------------------------------------------
# worklist
# --------------------------------------------------------------------------

@pytest.fixture
def seed(tmp_path: Path) -> Path:
    root = tmp_path / "seed"
    (root / "raw" / "pdfs").mkdir(parents=True)
    (root / "manifests").mkdir(parents=True)
    rows = []
    for key, url, category in (
        ("20407", "https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf", "ordinance"),
        ("19000", "https://files.topeka.gov/community/ordinances/2015/Ordinance19000.pdf", "ordinance"),
    ):
        payload = f"%PDF fixture {key}".encode()
        (root / "raw" / "pdfs" / f"{key}.pdf").write_bytes(payload)
        rows.append({
            "id": f"topeka-ordinance:{key}", "category": category, "ordinance_number": key,
            "pdf_url": url, "saved_path": f"raw/pdfs/{key}.pdf", "sha256": sha(payload),
        })
    (root / "manifests" / "ordinances.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return root


def test_worklist_reuses_retained_bytes_and_marks_the_rest_for_acquisition(result, seed):
    worklist = discover.build_worklist([result], seed)
    reuse = {row["source_document_id"] for row in worklist["verify_then_reuse"]}
    assert "ks:city:topeka:ordinances:ordinance:20407" in reuse
    assert worklist["counts"]["verify_then_reuse"] == 1
    # 7 discovered, 1 of them retained.
    assert worklist["counts"]["acquire_new"] == 6


def test_a_document_that_left_the_listing_is_not_treated_as_repealed(result, seed):
    """The city publishes only the last four years; older retained items stay."""
    worklist = discover.build_worklist([result], seed)
    unlisted = worklist["retained_but_unlisted"]
    assert [row["source_document_id"] for row in unlisted] == ["ks:city:topeka:ordinances:ordinance:19000"]
    assert "not a repeal" in unlisted[0]["reason"]
    assert unlisted[0]["retained_sha256"]


def test_every_record_on_both_sides_lands_in_exactly_one_bucket(result, seed):
    worklist = discover.build_worklist([result], seed)
    buckets = (
        [row["source_document_id"] for row in worklist["verify_then_reuse"]]
        + [row["source_document_id"] for row in worklist["acquire_new"]]
        + [row["source_document_id"] for row in worklist["retained_but_unlisted"]]
    )
    assert len(buckets) == len(set(buckets))
    assert len(buckets) == worklist["counts"]["verify_then_reuse"] + worklist["counts"]["acquire_new"] \
        + worklist["counts"]["retained_but_unlisted"]


# --------------------------------------------------------------------------
# acquisition
# --------------------------------------------------------------------------

def make_row(doc_id: str, url: str, outcome: str, **extra) -> dict:
    return {
        "source_document_id": doc_id,
        "collection_id": "ks:city:topeka:ordinances",
        "official_url": url,
        "outcome": outcome,
        "reason": "fixture",
        **extra,
    }


def downloader_for(payload: bytes):
    calls: list[str] = []

    def download(url: str, *, timeout: int):
        calls.append(url)
        return payload, "application/pdf"

    download.calls = calls  # type: ignore[attr-defined]
    return download


def test_retained_bytes_are_verified_and_reused_without_a_rewrite(tmp_path, seed):
    payload = (seed / "raw" / "pdfs" / "20407.pdf").read_bytes()
    row = make_row(
        "ks:city:topeka:ordinances:ordinance:20407",
        "https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf",
        "verify_then_reuse",
        retained_path="raw/pdfs/20407.pdf",
        retained_sha256=sha(payload),
    )
    result = acquire.acquire_row(
        row, output_dir=tmp_path / "out", seed=seed, previous=None, timeout=5,
        downloader=downloader_for(payload),
    )
    assert result["outcome"] == "reused_verified"
    assert not (tmp_path / "out").exists(), "verified reuse must not write a second copy"


def test_retained_bytes_that_fail_their_own_hash_are_refused(tmp_path, seed):
    row = make_row(
        "ks:city:topeka:ordinances:ordinance:20407",
        "https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf",
        "verify_then_reuse",
        retained_path="raw/pdfs/20407.pdf",
        retained_sha256="0" * 64,
    )
    result = acquire.acquire_row(
        row, output_dir=tmp_path / "out", seed=seed, previous=None, timeout=5,
        downloader=downloader_for(b"anything"),
    )
    assert result["outcome"] == "failed"
    assert "refusing to reuse unverified bytes" in result["error"]


def test_interrupted_run_resumes_without_redoing_completed_items(tmp_path, seed):
    payload = b"%PDF new document"
    row = make_row(
        "ks:city:topeka:ordinances:ordinance:20662",
        "https://files.topeka.gov/community/ordinances/2026/Ordinance20662.pdf",
        "acquire_new",
    )
    first_downloader = downloader_for(payload)
    first = acquire.acquire_row(row, output_dir=tmp_path / "out", seed=seed, previous=None,
                                timeout=5, downloader=first_downloader, run_id="run-1")
    assert first["outcome"] == "downloaded_new"
    assert Path(first["saved_path"]).read_bytes() == payload
    assert len(first_downloader.calls) == 1

    # Same run resuming after an interruption: this item is already done.
    resumed = downloader_for(payload)
    second = acquire.acquire_row(row, output_dir=tmp_path / "out", seed=seed, previous=first,
                                 timeout=5, downloader=resumed, run_id="run-1")
    assert second["outcome"] == "unchanged_remote"
    assert resumed.calls == [], "an item completed in this run must not be refetched"


def test_a_later_run_asks_the_publisher_again_rather_than_trusting_the_checkpoint(tmp_path, seed):
    """Resume must not become a cache: a changed document has to be noticed."""
    row = make_row(
        "ks:city:topeka:ordinances:ordinance:20662",
        "https://files.topeka.gov/community/ordinances/2026/Ordinance20662.pdf",
        "acquire_new",
    )
    first = acquire.acquire_row(row, output_dir=tmp_path / "out", seed=seed, previous=None,
                                timeout=5, downloader=downloader_for(b"%PDF v1"), run_id="run-1")
    later = downloader_for(b"%PDF v1")
    second = acquire.acquire_row(row, output_dir=tmp_path / "out", seed=seed, previous=first,
                                 timeout=5, downloader=later, run_id="run-2")
    assert later.calls, "a new run must re-check the publisher"
    assert second["outcome"] == "unchanged_remote"

    # Opting out of that check is possible, but only explicitly.
    trusted = downloader_for(b"%PDF v1")
    third = acquire.acquire_row(row, output_dir=tmp_path / "out", seed=seed, previous=first,
                                timeout=5, downloader=trusted, run_id="run-3", trust_checkpoint=True)
    assert trusted.calls == []
    assert "--trust-checkpoint" in third["reason"]


def test_a_changed_document_does_not_destroy_the_version_we_already_held(tmp_path, seed):
    """Two-run reproduction: the first receipt's hash must still resolve after a change.

    Storage is content-addressed, so a revision lands beside its predecessor
    rather than on top of it. Overwriting would invalidate every acquisition
    receipt that cited the earlier bytes.
    """
    row = make_row(
        "ks:city:topeka:ordinances:ordinance:20662",
        "https://files.topeka.gov/community/ordinances/2026/Ordinance20662.pdf",
        "acquire_new",
    )
    out = tmp_path / "out"
    v1, v2 = b"%PDF original bytes", b"%PDF revised bytes, longer"

    first = acquire.acquire_row(row, output_dir=out, seed=seed, previous=None,
                                timeout=5, downloader=downloader_for(v1), run_id="run-1")
    second = acquire.acquire_row(row, output_dir=out, seed=seed, previous=first,
                                 timeout=5, downloader=downloader_for(v2), run_id="run-2")

    assert first["outcome"] == "downloaded_new"
    assert second["outcome"] == "downloaded_changed"
    assert second["prior_sha256"] == first["sha256"]

    # Both receipts still resolve, to the exact bytes each one recorded.
    for receipt, expected in ((first, v1), (second, v2)):
        stored = Path(receipt["saved_path"])
        assert stored.exists(), f"{receipt['sha256'][:12]} is no longer retrievable"
        assert stored.read_bytes() == expected
        assert sha(stored.read_bytes()) == receipt["sha256"]

    assert first["saved_path"] != second["saved_path"]
    assert set(second["versions"]) == {first["sha256"], second["sha256"]}
    assert len(list(acquire.document_dir(out, row).iterdir())) == 2


def test_reacquiring_identical_bytes_adds_no_second_copy(tmp_path, seed):
    row = make_row(
        "ks:city:topeka:ordinances:ordinance:20662",
        "https://files.topeka.gov/community/ordinances/2026/Ordinance20662.pdf",
        "acquire_new",
    )
    out = tmp_path / "out"
    payload = b"%PDF stable bytes"
    first = acquire.acquire_row(row, output_dir=out, seed=seed, previous=None,
                                timeout=5, downloader=downloader_for(payload), run_id="run-1")
    second = acquire.acquire_row(row, output_dir=out, seed=seed, previous=first,
                                 timeout=5, downloader=downloader_for(payload), run_id="run-2")
    assert second["outcome"] == "unchanged_remote"
    assert second["saved_path"] == first["saved_path"]
    assert len(list(acquire.document_dir(out, row).iterdir())) == 1


def test_observation_history_survives_a_checkpoint_rewrite(tmp_path):
    """The checkpoint is rewritten wholesale each flush, so history lives elsewhere."""
    log = acquire.ObservationLog(tmp_path / "observations.jsonl")
    log.append({"source_document_id": "a", "sha256": "1" * 64, "observed_at": "t1"})
    log.append({"source_document_id": "b", "sha256": "2" * 64, "observed_at": "t1"})
    log.append({"source_document_id": "a", "sha256": "3" * 64, "observed_at": "t2"})

    checkpoint = acquire.Checkpoint.load(tmp_path / "checkpoint.jsonl")
    checkpoint.record({"source_document_id": "a", "outcome": "downloaded_changed"})

    history = log.observations_for("a")
    assert [row["sha256"] for row in history] == ["1" * 64, "3" * 64]
    assert [row["observed_at"] for row in history] == ["t1", "t2"]


def test_changed_publisher_bytes_are_recorded_with_the_prior_hash(tmp_path, seed):
    row = make_row(
        "ks:city:topeka:ordinances:ordinance:20662",
        "https://files.topeka.gov/community/ordinances/2026/Ordinance20662.pdf",
        "acquire_new",
    )
    first = acquire.acquire_row(row, output_dir=tmp_path / "out", seed=seed, previous=None,
                                timeout=5, downloader=downloader_for(b"%PDF v1"), run_id="run-1")
    second = acquire.acquire_row(row, output_dir=tmp_path / "out", seed=seed, previous=first,
                                 timeout=5, downloader=downloader_for(b"%PDF v2 revised"), run_id="run-2")
    assert second["outcome"] == "downloaded_changed"
    assert second["prior_sha256"] == first["sha256"]
    assert Path(second["saved_path"]).read_bytes() == b"%PDF v2 revised"


def test_a_fetch_failure_leaves_the_item_pending_rather_than_done(tmp_path, seed):
    from urllib import error as urlerror

    def failing(url: str, *, timeout: int):
        raise urlerror.URLError("connection reset")

    row = make_row("ks:city:topeka:ordinances:ordinance:20663",
                   "https://files.topeka.gov/community/ordinances/2026/Ordinance20663.pdf", "acquire_new")
    result = acquire.acquire_row(row, output_dir=tmp_path / "out", seed=seed, previous=None,
                                 timeout=5, downloader=failing)
    assert result["outcome"] == "failed"
    assert "connection reset" in result["error"]
    assert result["saved_path"] is None


def test_unlisted_retained_document_is_skipped_not_fetched(tmp_path, seed):
    row = make_row("ks:city:topeka:ordinances:ordinance:19000",
                   "https://files.topeka.gov/community/ordinances/2015/Ordinance19000.pdf",
                   "retained_but_unlisted", retained_sha256="a" * 64)
    downloader = downloader_for(b"should not be called")
    result = acquire.acquire_row(row, output_dir=tmp_path / "out", seed=seed, previous=None,
                                 timeout=5, downloader=downloader)
    assert result["outcome"] == "skipped_unlisted"
    assert downloader.calls == []


def test_checkpoint_round_trips_so_a_run_can_resume(tmp_path):
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = acquire.Checkpoint.load(path)
    checkpoint.record({"source_document_id": "b", "outcome": "downloaded_new"})
    checkpoint.record({"source_document_id": "a", "outcome": "reused_verified"})
    reloaded = acquire.Checkpoint.load(path)
    assert set(reloaded.entries) == {"a", "b"}
    assert reloaded.entries["a"]["outcome"] == "reused_verified"
    assert path.read_text().index('"a"') < path.read_text().index('"b"'), "checkpoint is written sorted"


def test_urls_with_spaces_are_encoded_before_fetching():
    assert acquire.encoded_url("https://topeka.gov/community/ordinances/2026 Program Overview.docx") == (
        "https://topeka.gov/community/ordinances/2026%20Program%20Overview.docx"
    )


def test_every_acquisition_outcome_is_one_the_reporter_counts():
    """The outcome set is closed: a new outcome must be added to OUTCOMES."""
    assert set(acquire.OUTCOMES) >= {
        "reused_verified", "downloaded_new", "downloaded_changed",
        "unchanged_remote", "failed", "skipped_unlisted",
    }


def test_a_path_plus_is_retried_as_a_space_only_after_the_literal_form_fails(monkeypatch):
    """Topeka writes `Ordinance20670+.docx` for a file stored with a trailing space."""
    from urllib import error as urlerror

    tried: list[str] = []

    class _Response:
        headers = {"Content-Type": "application/vnd.openxmlformats"}

        def read(self):
            return b"PK\x03\x04 docx"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(req, timeout=None):
        tried.append(req.full_url)
        if req.full_url.endswith("%2B.docx"):
            raise urlerror.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return _Response()

    monkeypatch.setattr(acquire.request, "urlopen", urlopen)
    payload, content_type = acquire.fetch(
        "https://files.topeka.gov/community/ordinances/2026/Ordinance20670+.docx", timeout=5
    )
    assert payload.startswith(b"PK")
    assert "url_resolution=plus_decoded_as_space" in content_type
    assert tried[0].endswith("%2B.docx"), "the publisher's literal href must be tried first"
    assert tried[1].endswith("%20.docx")


def test_a_non_404_error_is_not_retried_as_a_different_url(monkeypatch):
    from urllib import error as urlerror

    tried: list[str] = []

    def urlopen(req, timeout=None):
        tried.append(req.full_url)
        raise urlerror.HTTPError(req.full_url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(acquire.request, "urlopen", urlopen)
    with pytest.raises(urlerror.HTTPError):
        acquire.fetch("https://files.topeka.gov/community/ordinances/2026/Ordinance20670+.docx", timeout=5)
    assert len(tried) == 1


# --------------------------------------------------------------------------
# evidenced URL correction
# --------------------------------------------------------------------------

CORRECTION_ROW = {
    "source_document_id": "ks:city:topeka:ordinances:ordinance:20632",
    "collection_id": "ks:city:topeka:ordinances",
    "official_url": "https://files.topeka.gov/community/ordinances/2026/Ordinancec.pdf",
    "outcome": "acquire_new",
    "reason": "fixture",
    "convention_candidate_url": "https://files.topeka.gov/community/ordinances/2026/Ordinance20632.pdf",
    "convention_evidence": {
        "dominant_pattern": "Ordinance{key}.pdf",
        "group": "2026",
        "listing_label": "20632",
        "members_following_pattern": 44,
        "publisher_key": "20632",
    },
}


def correcting_downloader(payload: bytes, *, serves: str):
    from urllib import error as urlerror

    calls: list[str] = []

    def download(url: str, *, timeout: int):
        calls.append(url)
        if url != serves:
            raise urlerror.HTTPError(url, 404, "Not Found", {}, None)
        return payload, "application/pdf"

    download.calls = calls  # type: ignore[attr-defined]
    return download


def test_an_evidenced_correction_retains_both_urls_and_the_evidence(tmp_path, seed):
    payload = b"%PDF ordinance 20632"
    result = acquire.acquire_row(
        CORRECTION_ROW, output_dir=tmp_path / "out", seed=seed, previous=None, timeout=5,
        downloader=correcting_downloader(payload, serves=CORRECTION_ROW["convention_candidate_url"]),
        run_id="run-1",
    )
    assert result["outcome"] == "downloaded_corrected_url"
    assert result["listing_url"] == CORRECTION_ROW["official_url"], "the broken listing URL must be kept"
    assert result["listing_url_status"] == 404
    assert result["fetched_url"] == CORRECTION_ROW["convention_candidate_url"]
    assert result["sha256"] == sha(payload)
    assert Path(result["saved_path"]).read_bytes() == payload

    evidence = result["correction_evidence"]
    assert evidence["broken_listing_url"] == CORRECTION_ROW["official_url"]
    assert evidence["http_status"] == 200
    assert evidence["same_host_and_directory"] is True
    assert evidence["publisher_key_in_candidate_filename"] is True
    assert evidence["members_following_pattern"] == 44
    assert evidence["review_status"] == "evidenced_correction_pending_review"


def test_a_correction_off_the_official_host_is_refused(tmp_path, seed):
    row = {**CORRECTION_ROW, "convention_candidate_url": "https://example.invalid/2026/Ordinance20632.pdf"}
    result = acquire.acquire_row(
        row, output_dir=tmp_path / "out", seed=seed, previous=None, timeout=5,
        downloader=correcting_downloader(b"x", serves=row["convention_candidate_url"]),
        run_id="run-1",
    )
    assert result["outcome"] == "unavailable_at_source"


def test_a_correction_into_another_directory_is_refused(tmp_path, seed):
    row = {**CORRECTION_ROW,
           "convention_candidate_url": "https://files.topeka.gov/community/ordinances/2022/Ordinance20632.pdf"}
    result = acquire.acquire_row(
        row, output_dir=tmp_path / "out", seed=seed, previous=None, timeout=5,
        downloader=correcting_downloader(b"x", serves=row["convention_candidate_url"]),
        run_id="run-1",
    )
    assert result["outcome"] == "unavailable_at_source"


def test_a_200_alone_is_not_enough_without_the_publisher_key_in_the_name(tmp_path, seed):
    row = {**CORRECTION_ROW,
           "convention_candidate_url": "https://files.topeka.gov/community/ordinances/2026/Something.pdf"}
    result = acquire.acquire_row(
        row, output_dir=tmp_path / "out", seed=seed, previous=None, timeout=5,
        downloader=correcting_downloader(b"x", serves=row["convention_candidate_url"]),
        run_id="run-1",
    )
    assert result["outcome"] == "unavailable_at_source"


def test_with_no_candidate_a_broken_link_stays_unavailable(tmp_path, seed):
    row = {k: v for k, v in CORRECTION_ROW.items() if not k.startswith("convention_")}
    result = acquire.acquire_row(
        row, output_dir=tmp_path / "out", seed=seed, previous=None, timeout=5,
        downloader=correcting_downloader(b"x", serves="https://nowhere.invalid/x.pdf"),
        run_id="run-1",
    )
    assert result["outcome"] == "unavailable_at_source"
    assert "would invent provenance" in result["reason"]


def test_a_different_file_format_is_never_proposed_as_a_url_correction():
    """The .docx instruments are served correctly; a .pdf is a different document."""
    docs = [
        {"official_url": f"https://files.topeka.gov/community/ordinances/2026/Ordinance{n}.pdf",
         "publisher_key": str(n), "listing_category": "Ordinances", "listing_group": "2026",
         "label": str(n)}
        for n in range(20600, 20610)
    ]
    docs.append({
        "official_url": "https://files.topeka.gov/community/ordinances/2026/Ordinance20666.docx",
        "publisher_key": "20666", "listing_category": "Ordinances", "listing_group": "2026",
        "label": "20666",
    })
    discover.convention_candidate(docs)
    assert "convention_candidate_url" not in docs[-1]


def test_a_label_that_contradicts_its_href_is_reported_not_corrected():
    docs = [
        {"official_url": f"https://files.topeka.gov/community/ordinances/2024/Ordinance{n}.pdf",
         "publisher_key": str(n), "listing_category": "Ordinances", "listing_group": "2024",
         "label": str(n)}
        for n in range(20500, 20510)
    ]
    docs.append({
        "official_url": "https://files.topeka.gov/community/ordinances/2024/Ordinance20521.pdf",
        "publisher_key": "20520", "listing_category": "Ordinances", "listing_group": "2024",
        "label": "20520",
    })
    discover.convention_candidate(docs)
    conflicted = docs[-1]
    assert "convention_candidate_url" not in conflicted, "identity is ambiguous; do not guess"
    assert conflicted["identity_conflict"]["key_in_filename"] == "20521"
    assert conflicted["identity_conflict"]["review_status"] == "identity_ambiguous_review_needed"


def test_zero_padding_is_not_an_identity_conflict():
    """The listing writes 09380 where the file is named 9380 -- same document."""
    docs = [
        {"official_url": f"https://files.topeka.gov/community/resolutions/2025/Resolution{n}.pdf",
         "publisher_key": str(n), "listing_category": "2025", "listing_group": "2025", "label": str(n)}
        for n in range(9370, 9380)
    ]
    docs.append({
        "official_url": "https://files.topeka.gov/community/resolutions/2025/Resolution9380.pdf",
        "publisher_key": "09380", "listing_category": "2025", "listing_group": "2025", "label": "09380",
    })
    discover.convention_candidate(docs)
    assert "identity_conflict" not in docs[-1]
