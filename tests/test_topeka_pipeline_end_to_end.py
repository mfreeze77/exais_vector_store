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
    assert (third["bundle"] / "no-release.json").exists()
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
    assert (second_bundle / "no-release.json").exists()

    report = json.loads((instance / "releases" / "proofs" / "release-selection.json").read_text())
    assert report["counts"]["eligible_new"] == 0
    assert report["counts"]["eligible_changed"] == 0
    assert report["counts"]["unchanged"] == 1
