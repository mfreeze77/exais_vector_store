"""End-to-end pipeline proof: new, changed, ambiguous, unchanged rerun.

Drives the real release scripts as subprocesses over a self-contained fixture,
because the defects this covers all lived in the seams between stages rather
than inside any one of them.

Every assertion here traces to a review finding:
  * an ambiguous document must never reach the clean release lane;
  * a changed document must supersede the stale one and keep both versions;
  * a rerun with nothing new must not re-release what is already published;
  * every receipt, at every stage, must still resolve to its recorded bytes.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

NEW = "ks:city:topeka:ordinances:ordinance:30001"
CHANGED = "ks:city:topeka:ordinances:ordinance:30002"
AMBIGUOUS = "ks:city:topeka:ordinances:ordinance:30003"
STEADY = "ks:city:topeka:ordinances:ordinance:30005"
URLS = {
    NEW: "https://files.topeka.gov/community/ordinances/2026/Ordinance30001.docx",
    CHANGED: "https://files.topeka.gov/community/ordinances/2026/Ordinance30002.docx",
    # The href names 30004 while the listing label says 30003: identity is ambiguous.
    AMBIGUOUS: "https://files.topeka.gov/community/ordinances/2026/Ordinance30004.docx",
    STEADY: "https://files.topeka.gov/community/ordinances/2026/Ordinance30005.docx",
}


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document {NS}><w:body>'
            f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


VERSION_1 = {
    NEW: docx_bytes("Ordinance 30001 original text for the new document."),
    CHANGED: docx_bytes("Ordinance 30002 ORIGINAL body text."),
    AMBIGUOUS: docx_bytes("Ordinance 30003 ambiguous identity body."),
    STEADY: docx_bytes("Ordinance 30005 steady body text."),
}
VERSION_2 = {**VERSION_1, CHANGED: docx_bytes("Ordinance 30002 REVISED body text, materially different.")}


class Pipeline:
    """One working tree the pipeline stages read and write, across cycles."""

    def __init__(self, work: Path) -> None:
        self.work = work
        self.acquisition = work / "acquisition"
        self.extraction = work / "extraction"
        self.destinations = work / "destinations"
        self.releases = work / "releases"
        self.ledger = work / "released-state.jsonl"

    def run(self, script: str, *args: object) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(RELEASE / script), *map(str, args)],
            cwd=ROOT, capture_output=True, text=True,
        )

    def _write_corpus(self, version: dict[str, bytes]) -> None:
        for doc_id, payload in version.items():
            folder = self.acquisition / "ordinances" / "raw" / doc_id.rsplit(":", 1)[-1]
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{sha(payload)[:16]}.docx").write_bytes(payload)

    def _write_state(self, version: dict[str, bytes], tag: str) -> tuple[Path, Path]:
        checkpoint, worklist = self.work / f"checkpoint-{tag}.jsonl", self.work / f"worklist-{tag}.jsonl"
        rows = []
        for doc_id, payload in version.items():
            flags = ["identity_ambiguous"] if doc_id == AMBIGUOUS else []
            rows.append({
                "source_document_id": doc_id,
                "collection_id": "ks:city:topeka:ordinances",
                "official_url": URLS[doc_id],
                "sha256": sha(payload),
                "outcome": "downloaded_new",
                "saved_path": str(
                    self.acquisition / "ordinances" / "raw" / doc_id.rsplit(":", 1)[-1]
                    / f"{sha(payload)[:16]}.docx"
                ),
                "observed_at": "2026-09-15T00:00:00Z",
                "run_id": tag,
                "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "review_flags": flags,
                "review_status": "review_needed" if flags else "clear",
                "identity_conflict": (
                    {"publisher_key_from_label": "30003", "key_in_filename": "30004",
                     "review_status": "identity_ambiguous_review_needed"} if flags else None
                ),
            })
        checkpoint.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        worklist.write_text(
            "".join(json.dumps({"source_document_id": doc_id}) + "\n" for doc_id in version),
            encoding="utf-8",
        )
        return checkpoint, worklist

    def cycle(self, version: dict[str, bytes], tag: str) -> dict:
        self._write_corpus(version)
        checkpoint, worklist = self._write_state(version, tag)

        assert self.run("topeka-docx-extract.py", "--acquisition-dir", self.acquisition,
                        "--output-dir", self.extraction).returncode == 0
        assert self.run("topeka-destination-manifests.py", "--assignments", self.work / "absent.jsonl",
                        "--checkpoint", checkpoint, "--worklist", worklist,
                        "--output-dir", self.destinations).returncode == 0

        selection = self.work / f"selection-{tag}.jsonl"
        report = self.work / f"selection-report-{tag}.json"
        assert self.run("topeka-release-selection.py", "--destinations-dir", self.destinations,
                        "--extraction-dir", self.extraction, "--checkpoint", checkpoint,
                        "--output", selection, "--report", report,
                        "--released-state", self.ledger).returncode == 0

        bundle = self.releases / f"bundle-{tag}"
        assert self.run("topeka-source-release-export.py", "--selection", selection,
                        "--output-dir", bundle, "--release-id", f"proof-{tag}",
                        "--bundle-kind", "fixture", "--released-state", self.ledger,
                        "--allow-empty").returncode == 0

        selection_report = json.loads(report.read_text(encoding="utf-8"))
        manifest_path = bundle / "release-manifest.json"
        if not manifest_path.exists():
            return {"bundle": bundle, "selection": selection_report, "manifest": None}

        assert self.run("jurisdiction-release-validate.py", "--bundle", bundle).returncode == 0
        assert self.run("topeka-release-ledger.py", "--manifest", manifest_path,
                        "--ledger", self.ledger).returncode == 0
        return {
            "bundle": bundle,
            "selection": selection_report,
            "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
        }


@pytest.fixture(scope="module")
def cycles(tmp_path_factory) -> dict:
    pipeline = Pipeline(tmp_path_factory.mktemp("pipeline"))
    first = pipeline.cycle(VERSION_1, "1")
    second = pipeline.cycle(VERSION_2, "2")
    third = pipeline.cycle(VERSION_2, "3")
    return {"pipeline": pipeline, "first": first, "second": second, "third": third}


# --------------------------------------------------------------------------
# new documents
# --------------------------------------------------------------------------

def test_new_documents_are_released_and_all_are_accounted_for(cycles):
    selection = cycles["first"]["selection"]
    assert selection["counts"]["eligible_new"] == 3
    assert selection["documents_accounted_for"] == 4, "every document lands in exactly one bucket"


def test_an_ambiguous_document_never_reaches_the_release(cycles):
    first = cycles["first"]
    assert first["selection"]["counts"]["held_for_review"] == 1
    assert first["selection"]["held_for_review_by_flag"]["identity_ambiguous"] == 1
    released = {entry["source_document_id"] for entry in first["manifest"]["documents"]}
    assert AMBIGUOUS not in released


# --------------------------------------------------------------------------
# changed documents
# --------------------------------------------------------------------------

def test_a_changed_document_is_re_released_with_its_prior_version(cycles):
    second = cycles["second"]
    assert second["selection"]["counts"]["eligible_changed"] == 1
    changed = second["manifest"]["update"]["outcomes"]["changed"]
    assert len(changed) == 1
    assert changed[0]["source_document_id"] == CHANGED
    assert changed[0]["prior_version_id"] != changed[0]["document_version_id"]


def test_the_changed_release_carries_the_new_bytes_not_the_stale_ones(cycles):
    versions = {entry["document_version_id"] for entry in cycles["second"]["manifest"]["documents"]}
    assert any(version.endswith(sha(VERSION_2[CHANGED])[:16]) for version in versions)
    assert not any(version.endswith(sha(VERSION_1[CHANGED])[:16]) for version in versions)


def test_unchanged_documents_are_not_re_released_alongside_a_change(cycles):
    assert cycles["second"]["selection"]["counts"]["unchanged"] == 2


# --------------------------------------------------------------------------
# unchanged rerun
# --------------------------------------------------------------------------

def test_a_quiet_rerun_releases_nothing_and_claims_nothing(cycles):
    third = cycles["third"]
    assert third["manifest"] is None, "no manifest means no release was claimed"
    assert (third["bundle"].parent / "proofs" / "proof-3-no-release.json").exists()
    assert third["selection"]["counts"]["eligible_new"] == 0
    assert third["selection"]["counts"]["eligible_changed"] == 0


def test_the_rerun_compares_against_cumulative_state_not_the_last_bundle(cycles):
    """Release 2 held one document; the other two are still published."""
    third = cycles["third"]["selection"]
    assert third["counts"]["unchanged"] == 3
    assert third["baseline"].startswith("released_state")


def test_the_ledger_tracks_what_is_published_and_only_that(cycles):
    rows = [
        json.loads(line)
        for line in cycles["pipeline"].ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["source_document_id"] for row in rows} == {NEW, CHANGED, STEADY}
    by_id = {row["source_document_id"]: row for row in rows}
    assert by_id[CHANGED]["document_version_id"].endswith(sha(VERSION_2[CHANGED])[:16])
    assert AMBIGUOUS not in by_id, "a held document must never be recorded as published"


# --------------------------------------------------------------------------
# version integrity at every boundary
# --------------------------------------------------------------------------

def test_every_released_file_still_resolves_to_its_recorded_hash(cycles):
    mismatched = []
    for key in ("first", "second", "third"):
        cycle = cycles[key]
        if cycle["manifest"] is None:
            continue
        for entry in cycle["manifest"]["documents"]:
            for file_entry in entry["files"]:
                if not file_entry["present"]:
                    continue
                path = cycle["bundle"] / file_entry["path"]
                if not path.exists() or sha(path.read_bytes()) != file_entry["sha256"]:
                    mismatched.append(f"{cycle['bundle'].name}:{file_entry['path']}")
    assert not mismatched


def test_every_extraction_receipt_still_resolves_to_its_bytes(cycles):
    report = json.loads(
        (cycles["pipeline"].extraction / "docx-extraction-report.json").read_text(encoding="utf-8")
    )
    broken = []
    for row in report["results"]:
        path = Path(row["normalized_path"])
        if not path.exists():
            broken.append(row["document_key"])
            continue
        digest = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if digest != row["normalized_sha256"]:
            broken.append(row["document_key"])
    assert not broken


def test_both_versions_survive_acquisition_and_extraction(cycles):
    pipeline = cycles["pipeline"]
    key = CHANGED.rsplit(":", 1)[-1]
    originals = list((pipeline.acquisition / "ordinances" / "raw" / key).iterdir())
    extractions = list((pipeline.extraction / "ordinances" / key).iterdir())
    assert len(originals) == 2, "the superseded original must not be overwritten"
    assert len(extractions) == 2, "the superseded extraction must not be overwritten"


# --------------------------------------------------------------------------
# the actual refresh command
# --------------------------------------------------------------------------

@pytest.fixture
def refresh_tree(tmp_path: Path) -> Path:
    """A disposable instance tree the real refresh command can run against."""
    instance = tmp_path / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    for name in ("acquisition", "extraction", "destinations", "releases", "discovery"):
        (instance / name).mkdir(parents=True, exist_ok=True)

    folder = instance / "acquisition" / "ordinances" / "raw" / "30001"
    folder.mkdir(parents=True)
    payload = VERSION_1[NEW]
    (folder / f"{sha(payload)[:16]}.docx").write_bytes(payload)

    (instance / "acquisition" / "acquisition-checkpoint.jsonl").write_text(
        json.dumps({
            "source_document_id": NEW,
            "collection_id": "ks:city:topeka:ordinances",
            "official_url": URLS[NEW],
            "sha256": sha(payload),
            "outcome": "downloaded_new",
            "saved_path": str(folder / f"{sha(payload)[:16]}.docx"),
            "observed_at": "2026-09-16T00:00:00Z",
            "run_id": "refresh-test",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "review_flags": [],
            "review_status": "clear",
        }) + "\n", encoding="utf-8"
    )
    (instance / "discovery" / "worklist.jsonl").write_text(
        json.dumps({"source_document_id": NEW}) + "\n", encoding="utf-8"
    )
    return tmp_path


def run_refresh(tree: Path, release_id: str) -> subprocess.CompletedProcess:
    """Invoke the real command, with its own ROOT, offline."""
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": str(ROOT / "scripts" / "release"),
        "EXAIS_ROOT_OVERRIDE": str(tree),
    }
    return subprocess.run(
        [sys.executable, str(RELEASE / "topeka-collection-refresh.py"),
         "--execute", "--offline", "--release-id", release_id],
        cwd=tree, capture_output=True, text=True, env=env,
    )


def test_the_refresh_command_publishes_what_is_eligible_then_nothing(refresh_tree):
    """The reviewer's case: a second run with nothing eligible must publish nothing."""
    instance = refresh_tree / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"

    first = run_refresh(refresh_tree, "refresh-1")
    assert first.returncode == 0, first.stdout + first.stderr
    first_manifest = instance / "releases" / "refresh-1" / "release-manifest.json"
    assert first_manifest.exists(), "the eligible document should have been released"
    released = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert [entry["source_document_id"] for entry in released["documents"]] == [NEW]

    second = run_refresh(refresh_tree, "refresh-2")
    assert second.returncode == 0, second.stdout + second.stderr
    second_bundle = instance / "releases" / "refresh-2"
    assert not (second_bundle / "release-manifest.json").exists(), (
        "a run with nothing eligible must not publish a release"
    )
    assert not second_bundle.exists() or not any(second_bundle.iterdir()), (
        "a quiet run must not create or add to a release directory"
    )
    assert (instance / "releases" / "proofs" / "refresh-2-no-release.json").exists()

    report = json.loads((instance / "releases" / "proofs" / "release-selection.json").read_text())
    assert report["counts"]["eligible_new"] == 0
    assert report["counts"]["eligible_changed"] == 0
    assert report["counts"]["unchanged"] == 1


# --------------------------------------------------------------------------
# release identity is immutable
# --------------------------------------------------------------------------

def _one_document_selection(tmp_path: Path, pipeline: "Pipeline", text: str, tag: str) -> Path:
    """Acquire, extract and select a single document with the given body text."""
    payload = docx_bytes(text)
    folder = pipeline.acquisition / "ordinances" / "raw" / "30001"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sha(payload)[:16]}.docx").write_bytes(payload)
    assert pipeline.run("topeka-docx-extract.py", "--acquisition-dir", pipeline.acquisition,
                        "--output-dir", pipeline.extraction).returncode == 0

    report = json.loads(
        (pipeline.extraction / "docx-extraction-report.json").read_text(encoding="utf-8")
    )
    extraction = next(row for row in report["results"] if row["source_sha256"] == sha(payload))
    selection = tmp_path / f"selection-{tag}.jsonl"
    selection.write_text(json.dumps({
        "source_document_id": NEW,
        "collection_id": "ks:city:topeka:ordinances",
        "source_uri": URLS[NEW],
        "sha256": sha(payload),
        "retained_artifact": str(folder / f"{sha(payload)[:16]}.docx"),
        "publisher_key": "30001",
        "builder": "acquired_document",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "observed_at": "2026-09-16T00:00:00Z",
        "run_id": tag,
        "normalized_path": extraction["normalized_path"],
        "structured_path": str(Path(extraction["normalized_path"]).with_name("structured.json")),
        "extractor": extraction["extractor"],
        "limitations": [],
        "limitation_descriptions": {},
    }) + "\n", encoding="utf-8")
    return selection


def test_a_release_id_cannot_be_rewritten_with_different_content(tmp_path):
    """The default id is daily, so this is an ordinary Tuesday, not an exotic case."""
    pipeline = Pipeline(tmp_path)
    bundle = pipeline.releases / "daily"

    first = pipeline.run("topeka-source-release-export.py",
                         "--selection", _one_document_selection(tmp_path, pipeline, "version one", "a"),
                         "--output-dir", bundle, "--release-id", "daily", "--bundle-kind", "fixture")
    assert first.returncode == 0, first.stdout + first.stderr
    manifest = json.loads((bundle / "release-manifest.json").read_text(encoding="utf-8"))
    receipt = {
        entry["path"]: entry["sha256"]
        for document in manifest["documents"] for entry in document["files"] if entry["present"]
    }

    second = pipeline.run(
        "topeka-source-release-export.py",
        "--selection", _one_document_selection(tmp_path, pipeline, "version two, different", "b"),
        "--output-dir", bundle, "--release-id", "daily", "--bundle-kind", "fixture",
    )
    assert second.returncode != 0, "a published id must not accept different content"
    assert "immutable" in (second.stdout + second.stderr)

    for path, digest in receipt.items():
        assert (bundle / path).exists(), f"{path} was removed by the refused run"
        assert sha((bundle / path).read_bytes()) == digest, f"{path} no longer matches its receipt"


def test_re_exporting_identical_content_under_the_same_id_is_allowed(tmp_path):
    pipeline = Pipeline(tmp_path)
    bundle = pipeline.releases / "daily"
    selection = _one_document_selection(tmp_path, pipeline, "stable text", "a")
    for _ in range(2):
        result = pipeline.run("topeka-source-release-export.py", "--selection", selection,
                              "--output-dir", bundle, "--release-id", "daily", "--bundle-kind", "fixture")
        assert result.returncode == 0, result.stdout + result.stderr


def test_allocate_gives_changed_content_its_own_release(tmp_path):
    pipeline = Pipeline(tmp_path)
    bundle = pipeline.releases / "daily"
    first = pipeline.run("topeka-source-release-export.py",
                         "--selection", _one_document_selection(tmp_path, pipeline, "version one", "a"),
                         "--output-dir", bundle, "--release-id", "daily", "--bundle-kind", "fixture")
    assert first.returncode == 0

    second = pipeline.run(
        "topeka-source-release-export.py",
        "--selection", _one_document_selection(tmp_path, pipeline, "version two, different", "b"),
        "--output-dir", bundle, "--release-id", "daily", "--bundle-kind", "fixture",
        "--on-conflict", "allocate",
    )
    assert second.returncode == 0, second.stdout + second.stderr
    allocated = pipeline.releases / "daily-002"
    assert (allocated / "release-manifest.json").exists(), "changed content gets its own id"
    original = json.loads((bundle / "release-manifest.json").read_text(encoding="utf-8"))
    new = json.loads((allocated / "release-manifest.json").read_text(encoding="utf-8"))
    assert original["inventory"]["inventory_sha256"] != new["inventory"]["inventory_sha256"]


# --------------------------------------------------------------------------
# transitions through the real runner, under one requested id
# --------------------------------------------------------------------------

def _stage_docx(tree: Path, text: str) -> str:
    """Put one version of the document in place and return its hash."""
    instance = tree / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    payload = docx_bytes(text)
    folder = instance / "acquisition" / "ordinances" / "raw" / "30001"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sha(payload)[:16]}.docx").write_bytes(payload)
    (instance / "acquisition" / "acquisition-checkpoint.jsonl").write_text(
        json.dumps({
            "source_document_id": NEW,
            "collection_id": "ks:city:topeka:ordinances",
            "official_url": URLS[NEW],
            "sha256": sha(payload),
            "outcome": "downloaded_new",
            "saved_path": str(folder / f"{sha(payload)[:16]}.docx"),
            "observed_at": "2026-09-16T00:00:00Z",
            "run_id": "t",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "review_flags": [],
            "review_status": "clear",
        }) + "\n", encoding="utf-8"
    )
    (instance / "discovery").mkdir(parents=True, exist_ok=True)
    (instance / "discovery" / "worklist.jsonl").write_text(
        json.dumps({"source_document_id": NEW}) + "\n", encoding="utf-8"
    )
    return sha(payload)


def test_new_then_changed_then_unchanged_through_the_real_runner(tmp_path):
    """One requested id across three transitions. Nothing may be rewritten."""
    instance = tmp_path / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    releases = instance / "releases"
    ledger_path = releases / "released-state.jsonl"

    def ledger_versions() -> dict[str, str]:
        if not ledger_path.exists():
            return {}
        return {
            json.loads(line)["source_document_id"]: json.loads(line)["document_version_id"]
            for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()
        }

    def bundle_hashes(bundle: Path) -> dict[str, str]:
        manifest = json.loads((bundle / "release-manifest.json").read_text(encoding="utf-8"))
        files = {
            entry["path"]: entry["sha256"]
            for document in manifest["documents"] for entry in document["files"] if entry["present"]
        }
        files["release-manifest.json"] = sha((bundle / "release-manifest.json").read_bytes())
        return files

    # 1. new
    first_sha = _stage_docx(tmp_path, "the original body text")
    assert run_refresh(tmp_path, "daily").returncode == 0
    first = releases / "daily"
    assert (first / "release-manifest.json").exists()
    first_hashes = bundle_hashes(first)
    assert ledger_versions()[NEW].endswith(first_sha[:16])

    # 2. changed, same requested id
    second_sha = _stage_docx(tmp_path, "a materially different revised body")
    assert run_refresh(tmp_path, "daily").returncode == 0
    allocated = releases / "daily-002"
    assert (allocated / "release-manifest.json").exists(), "changed content needs its own release"

    for path, digest in first_hashes.items():
        assert sha((first / path).read_bytes()) == digest, f"{path} in the first release was rewritten"

    assert ledger_versions()[NEW].endswith(second_sha[:16]), (
        "the ledger must record the release that was actually written, not the requested id"
    )
    proof = releases / "proofs" / "daily-002-validation.json"
    assert proof.exists(), "validation must target the allocated release"
    assert json.loads(proof.read_text(encoding="utf-8"))["passed"]

    # 3. unchanged rerun
    assert run_refresh(tmp_path, "daily").returncode == 0
    assert not (releases / "daily-003").exists(), "an unchanged rerun must not allocate a release"
    assert ledger_versions()[NEW].endswith(second_sha[:16])
    for path, digest in bundle_hashes(allocated).items():
        assert sha((allocated / path).read_bytes()) == digest


def test_an_identical_re_export_does_not_touch_a_single_byte(tmp_path):
    """released_at must not move, or every lock citing the release is invalidated."""
    pipeline = Pipeline(tmp_path)
    bundle = pipeline.releases / "daily"
    selection = _one_document_selection(tmp_path, pipeline, "stable text", "a")

    assert pipeline.run("topeka-source-release-export.py", "--selection", selection,
                        "--output-dir", bundle, "--release-id", "daily",
                        "--bundle-kind", "fixture").returncode == 0
    before = {
        path.relative_to(bundle).as_posix(): sha(path.read_bytes())
        for path in sorted(bundle.rglob("*")) if path.is_file()
    }
    manifest_mtime = (bundle / "release-manifest.json").stat().st_mtime_ns

    result = pipeline.run("topeka-source-release-export.py", "--selection", selection,
                          "--output-dir", bundle, "--release-id", "daily", "--bundle-kind", "fixture")
    assert result.returncode == 0
    after = {
        path.relative_to(bundle).as_posix(): sha(path.read_bytes())
        for path in sorted(bundle.rglob("*")) if path.is_file()
    }
    assert after == before, "an identical retry must be a no-op on disk"
    assert (bundle / "release-manifest.json").stat().st_mtime_ns == manifest_mtime
    assert "unchanged" in result.stdout


def test_a_retry_after_an_interrupted_ledger_update_reuses_the_same_release(tmp_path):
    """Crash between validate and ledger, then restart. The release must be reused.

    This is the recovery path that matters: the bundle is on disk and valid, but
    the ledger never learned about it. A restart that allocates a fresh id
    instead of recognising its own work leaves two identical releases and a
    ledger that still points at the older version.
    """
    instance = tmp_path / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    releases = instance / "releases"
    ledger_path = releases / "released-state.jsonl"

    def ledger_version() -> str | None:
        if not ledger_path.exists():
            return None
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line)["source_document_id"] == NEW:
                return json.loads(line)["document_version_id"]
        return None

    # 1. publish the original
    first_sha = _stage_docx(tmp_path, "the original body text")
    assert run_refresh(tmp_path, "daily").returncode == 0
    assert ledger_version().endswith(first_sha[:16])

    # Capture the ledger exactly as it stands before the revision is published.
    # Restoring these bytes verbatim is what a crash before the ledger write
    # actually leaves behind; reconstructing the rows by editing a field would
    # keep metadata the pre-crash ledger never had.
    pre_crash_ledger = ledger_path.read_bytes()

    # 2. publish a revision, then simulate the crash: the bundle and its
    #    validation exist, but the ledger update never happened.
    second_sha = _stage_docx(tmp_path, "a materially different revised body")
    assert run_refresh(tmp_path, "daily").returncode == 0
    allocated = releases / "daily-002"
    assert (allocated / "release-manifest.json").exists()

    ledger_path.write_bytes(pre_crash_ledger)
    assert ledger_version().endswith(first_sha[:16]), "the ledger is back to pre-crash state"
    before = {
        path.relative_to(allocated).as_posix(): sha(path.read_bytes())
        for path in sorted(allocated.rglob("*")) if path.is_file()
    }

    # 3. restart
    assert run_refresh(tmp_path, "daily").returncode == 0
    assert not (releases / "daily-003").exists(), "the retry must reuse daily-002, not duplicate it"
    after = {
        path.relative_to(allocated).as_posix(): sha(path.read_bytes())
        for path in sorted(allocated.rglob("*")) if path.is_file()
    }
    assert after == before, "the reused release must not be rewritten"
    assert ledger_version().endswith(second_sha[:16]), "the retry must finish the ledger update"

    # 4. and then go quiet
    assert run_refresh(tmp_path, "daily").returncode == 0
    assert not (releases / "daily-003").exists()
    assert ledger_version().endswith(second_sha[:16])


def test_an_explicit_retry_against_the_allocated_id_is_recognised(tmp_path):
    """Re-exporting a revised document into the id that already holds it is a no-op."""
    pipeline = Pipeline(tmp_path)
    baseline = tmp_path / "ledger.jsonl"
    bundle = pipeline.releases / "rel"

    first_selection = _one_document_selection(tmp_path, pipeline, "original text", "a")
    assert pipeline.run("topeka-source-release-export.py", "--selection", first_selection,
                        "--output-dir", bundle, "--release-id", "rel",
                        "--bundle-kind", "fixture").returncode == 0
    assert pipeline.run("topeka-release-ledger.py", "--manifest", bundle / "release-manifest.json",
                        "--ledger", baseline).returncode == 0

    revised = _one_document_selection(tmp_path, pipeline, "revised text, different", "b")
    second = pipeline.releases / "rel2"
    assert pipeline.run("topeka-source-release-export.py", "--selection", revised,
                        "--output-dir", second, "--release-id", "rel2",
                        "--released-state", baseline, "--bundle-kind", "fixture").returncode == 0
    manifest = json.loads((second / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["update"]["outcomes"]["changed"], "this release carries a revised document"
    before = sha((second / "release-manifest.json").read_bytes())

    # The explicit retry: same selection, same baseline, same id.
    retry = pipeline.run("topeka-source-release-export.py", "--selection", revised,
                         "--output-dir", second, "--release-id", "rel2",
                         "--released-state", baseline, "--bundle-kind", "fixture")
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert "unchanged" in retry.stdout
    assert sha((second / "release-manifest.json").read_bytes()) == before


def test_a_quiet_run_does_not_add_a_file_to_a_published_bundle(tmp_path):
    """A no-op receipt inside an immutable bundle makes every lock count stale."""
    instance = tmp_path / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    releases = instance / "releases"

    _stage_docx(tmp_path, "the original body text")
    assert run_refresh(tmp_path, "daily").returncode == 0
    bundle = releases / "daily"

    lock = releases / "daily.lock.json"
    pipeline = Pipeline(tmp_path)
    assert pipeline.run("topeka-release-lock.py", "--bundle", bundle, "--output", lock).returncode == 0
    before = {
        path.relative_to(bundle).as_posix(): sha(path.read_bytes())
        for path in sorted(bundle.rglob("*")) if path.is_file()
    }

    # Nothing has changed, so the next run is quiet.
    assert run_refresh(tmp_path, "daily").returncode == 0
    after = {
        path.relative_to(bundle).as_posix(): sha(path.read_bytes())
        for path in sorted(bundle.rglob("*")) if path.is_file()
    }
    assert after == before, "a quiet run must not touch a published bundle"
    assert not (bundle / "no-release.json").exists()
    assert (releases / "proofs" / "daily-no-release.json").exists(), "the receipt goes beside, not inside"

    verify = pipeline.run("topeka-release-lock.py", "--bundle", bundle, "--output", lock, "--verify")
    assert verify.returncode == 0, verify.stdout + verify.stderr


def test_lock_verification_catches_a_bundle_that_gained_a_file(tmp_path):
    instance = tmp_path / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    _stage_docx(tmp_path, "the original body text")
    assert run_refresh(tmp_path, "daily").returncode == 0
    bundle = instance / "releases" / "daily"
    lock = instance / "releases" / "daily.lock.json"

    pipeline = Pipeline(tmp_path)
    assert pipeline.run("topeka-release-lock.py", "--bundle", bundle, "--output", lock).returncode == 0
    (bundle / "stray.json").write_text("{}", encoding="utf-8")

    verify = pipeline.run("topeka-release-lock.py", "--bundle", bundle, "--output", lock, "--verify")
    assert verify.returncode == 1
    assert "bundle_file_count" in verify.stdout


def test_lock_verification_catches_a_same_length_corruption(tmp_path):
    """The reviewer's case: aggregate counts cannot see a byte flipped in place.

    File count, byte total and the manifest hash are all unchanged by a
    same-length edit to a document artifact, so the lock comparison alone passes
    it. --verify must therefore always run the content validation too.
    """
    instance = tmp_path / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    _stage_docx(tmp_path, "the original body text")
    assert run_refresh(tmp_path, "daily").returncode == 0
    bundle = instance / "releases" / "daily"
    lock = instance / "releases" / "daily.lock.json"

    pipeline = Pipeline(tmp_path)
    assert pipeline.run("topeka-release-lock.py", "--bundle", bundle, "--output", lock).returncode == 0

    target = next(bundle.rglob("normalized.txt"))
    original = target.read_bytes()
    # Flip one byte in place. Same length, same file count, same byte total.
    index = original.index(b"original")
    corrupted = original[:index] + b"0riginal" + original[index + 8:]
    assert len(corrupted) == len(original), "the probe must not change the file's length"
    assert corrupted != original
    target.write_bytes(corrupted)

    # The aggregates are untouched, which is exactly why the lock alone is not enough.
    files = [path for path in bundle.rglob("*") if path.is_file()]
    recorded = json.loads(lock.read_text(encoding="utf-8"))
    assert recorded["bundle_file_count"] == len(files)
    assert recorded["bundle_byte_count"] == sum(path.stat().st_size for path in files)
    assert recorded["manifest_sha256"] == sha((bundle / "release-manifest.json").read_bytes())

    verify = pipeline.run("topeka-release-lock.py", "--bundle", bundle, "--output", lock, "--verify")
    assert verify.returncode == 1, "the publication gate must reject a same-length corruption"
    assert "lock identity and counts   PASS" in verify.stdout
    assert "bundle content             FAIL" in verify.stdout
