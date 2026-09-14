"""The adapter wired to the REAL ingestion entrypoint.

Not the adapter in isolation: `scripts/release/kansas-fiscal-document-ingest.py`,
loaded the way the CLI loads it, driven through `main()` with real argv.

Two claims, and the second is the one that matters most:

1. A candidate revision is refused at the COMMAND, before any callback. Proved
   by driving `main()` with detonating stand-ins for every API seam, and
   separately by inversion -- moving the gate after dispatch and watching it
   fire. An empty spy list only proves it for the run that happened.

2. The document path is UNCHANGED. `kansas-fiscal-document-ingest.py` was
   byte-untouched through WAVE-133's seven rounds and all of WAVE-134, and
   28,812 documents were ingested through it. "Still passing" is not the claim;
   the claim is that it produces the same `LoadedManifest` it did before, and
   that is proved DIFFERENTIALLY against the pre-change file read out of git at
   a fixed sha, not against a expectation written here.

No provider, no API call, no store write, no embedding. Every manifest is a
committed fixture.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
CONSUMER = RELEASE / "kansas-fiscal-document-ingest.py"
FIXTURES = Path(__file__).parent / "fixtures"
CONTRACT = FIXTURES / "statecivics-retrieval-export-record.24c9d3de.json"
REAL_MANIFEST = FIXTURES / "statecivics-ks600-a2-1-entities-candidates.677d126d.jsonl"
MIXED = FIXTURES / "statecivics-mixed-manifest.jsonl"

#: The commit this branch forked from: the consumer as it stood before the
#: entity dispatch was wired in, and as 28,812 documents were ingested through.
PRE_CHANGE_COMMIT = "a7b2843"


def _load(path: Path, name: str):
    sys.path.insert(0, str(RELEASE))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ingest():
    return _load(CONSUMER, "kfdi_integration")


@pytest.fixture(scope="module")
def pre_change(tmp_path_factory):
    """The consumer as it was BEFORE this change, read from git at a fixed sha.

    Not a copy kept beside the test, which would drift, and not a description of
    the old behaviour, which would be a second implementation to get wrong.
    """
    blob = subprocess.run(
        ["git", "show", f"{PRE_CHANGE_COMMIT}:scripts/release/kansas-fiscal-document-ingest.py"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    path = tmp_path_factory.mktemp("pre-change") / "kansas-fiscal-document-ingest.py"
    path.write_bytes(blob)
    return _load(path, "kfdi_pre_change")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _document_manifest(ingest, tmp_path: Path) -> Path:
    """A document-only manifest, built the way the document suite builds one."""
    content = b"%PDF-1.7\nkansas fiscal integration fixture\n"
    digest = __import__("hashlib").sha256(content).hexdigest()
    record = {
        "export_record_id": "2" * 64,
        "logical_document_id": "1" * 64,
        "source_revision_id": "revision-1",
        "revision_number": 1,
        "content_hash_sha256": digest,
        "custody_uri": f"civic-custody://kanview/{digest[:2]}/{digest}",
        "custody_status": "retained",
        "citation_url": "https://budget.kansas.gov/reports/fy2027.pdf",
        "publisher": "Kansas Division of the Budget",
        "jurisdiction": "Kansas",
        "artifact_type": "budget_report",
        "record_digest_algorithm": "statecivics-canonical-json-v1",
        "record_digest_sha256": "0" * 64,
        "mime_type": "application/pdf",
        "byte_size": len(content),
        "title": "Kansas FY2027 Budget Report",
        "effective_period": {"fiscal_year": 2027},
        "exporter": {
            "name": "statecivics-retrieval-exporter",
            "version": "retrieval-export-1",
            "code_commit": "a" * 40,
            "exported_at": "2026-09-04T12:00:00Z",
        },
        "lifecycle": {"state": "current", "removal_required": False},
        "redistribution": "full",
        "ingestion": {
            "mode": "api_only",
            "action": "upsert",
            "target_instance_slug": "ks-state-civics",
            "target_vector_store_slug": "kansas-fiscal-documents",
            "recall_evaluation_required": True,
        },
    }
    record["record_digest_sha256"] = ingest.record_digest(record)
    path = tmp_path / "documents.jsonl"
    path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Claim 2: the document path is unchanged. DIFFERENTIALLY.
# --------------------------------------------------------------------------


def test_the_document_path_produces_the_identical_loaded_manifest(ingest, pre_change, tmp_path):
    """Byte-for-byte the same `LoadedManifest`, old implementation vs new.

    The strongest form available: the pre-change consumer is loaded alongside
    the new one and both are given the same manifest. If the dispatch guard
    changed ANY document-path behaviour -- ordering, digest, byte count, the
    records themselves -- these differ.
    """
    manifest_path = _document_manifest(ingest, tmp_path)
    kwargs = {"contract_schema": CONTRACT}
    new = ingest.load_manifest(manifest_path, **kwargs)
    old = pre_change.load_manifest(manifest_path, **kwargs)

    assert new.sha256 == old.sha256
    assert new.byte_count == old.byte_count
    assert new.path == old.path
    assert new.records == old.records
    assert len(new.records) == 1
    # Whole-object equality across two independently loaded module instances
    # cannot use `==` on the dataclass (different classes), so compare fields.
    assert [f.name for f in __import__("dataclasses").fields(new)] == [
        f.name for f in __import__("dataclasses").fields(old)
    ]


def test_the_document_path_refuses_identically(ingest, pre_change, tmp_path):
    """The refusals a document run already made are unchanged, message included."""
    cases = {
        "no trailing newline": b'{"a": 1}',
        "not utf-8": b"\xff\xfe\n",
        "invalid json": b"{not json}\n",
        "not an object": b"[1,2]\n",
        "empty": b"\n",
    }
    for label, payload in cases.items():
        path = tmp_path / f"{abs(hash(label))}.jsonl"
        path.write_bytes(payload)
        with pytest.raises(ingest.FiscalIngestError) as new_exc:
            ingest.load_manifest(path, contract_schema=CONTRACT)
        with pytest.raises(pre_change.FiscalIngestError) as old_exc:
            pre_change.load_manifest(path, contract_schema=CONTRACT)
        assert str(new_exc.value) == str(old_exc.value), label


def test_the_missing_schema_refusal_is_unchanged(ingest, pre_change, tmp_path):
    """WAVE-133's pin enforcement is untouched, word for word."""
    path = tmp_path / "m.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ingest.FiscalIngestError) as new_exc:
        ingest.load_manifest(path)
    with pytest.raises(pre_change.FiscalIngestError) as old_exc:
        pre_change.load_manifest(path)
    assert str(new_exc.value) == str(old_exc.value)
    assert "--contract-schema is required" in str(new_exc.value)


def test_load_manifest_keeps_its_signature(ingest, pre_change):
    """Signature and return type unchanged -- callers cannot have been broken."""
    import inspect

    assert inspect.signature(ingest.load_manifest) == inspect.signature(pre_change.load_manifest)
    assert ingest.load_manifest.__annotations__["return"] == "LoadedManifest"


# --------------------------------------------------------------------------
# Claim 1: the candidate refusal happens at the COMMAND
# --------------------------------------------------------------------------


class _Detonator:
    """Fails if reached. An empty spy list only proves the run that happened."""

    def __init__(self, what: str) -> None:
        self.what = what
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError(f"{self.what} was called before the entity gate refused a candidate")


@pytest.fixture
def sealed(ingest, monkeypatch):
    """Every API seam in the consumer replaced by something that detonates."""
    seams = {}
    for name in ("ensure_vector_store", "apply_operations", "default_headers", "upload_document"):
        if hasattr(ingest, name):
            seams[name] = _Detonator(name)
            monkeypatch.setattr(ingest, name, seams[name])
    assert "ensure_vector_store" in seams and "apply_operations" in seams
    return seams


def _argv(manifest: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "kansas-fiscal-document-ingest.py",
        "--manifest", str(manifest),
        "--contract-schema", str(CONTRACT),
        "--custody-root", str(tmp_path),
        "--state", str(tmp_path / "state.json"),
        *extra,
    ]


def test_the_command_refuses_a_candidate_for_the_live_store(ingest, sealed, monkeypatch, tmp_path):
    """THE DELIVERABLE, at the real entrypoint, with --apply requested.

    `--apply` is passed deliberately: the refusal must come first even when the
    operator asked for the real thing.
    """
    from svs_common.statecivics_record_adapter import CandidateRecordRefused

    monkeypatch.setattr(
        sys, "argv", _argv(REAL_MANIFEST, tmp_path, "--record-kind", "entity", "--apply")
    )
    with pytest.raises(CandidateRecordRefused) as excinfo:
        ingest.main()
    message = str(excinfo.value)
    assert "for the live entity store" in message
    assert "eligibility.status is 'candidate'" in message
    assert "Nothing has been embedded or indexed." in message
    for name, seam in sealed.items():
        assert seam.calls == 0, f"{name} was reached before the refusal"


def test_the_command_accepts_the_same_records_on_the_candidate_path(
    ingest, sealed, monkeypatch, tmp_path, capsys
):
    """...and the refusal is candidacy, not a blanket no at the entrypoint."""
    monkeypatch.setattr(
        sys, "argv",
        _argv(REAL_MANIFEST, tmp_path, "--record-kind", "entity", "--entity-path", "candidate"),
    )
    assert ingest.main() == 0
    printed = capsys.readouterr().out
    report = json.loads(printed[: printed.rindex("}") + 1])
    assert report["record_kind"] == "entity"
    assert report["entity_path"] == "candidate"
    assert report["record_count"] == 2
    assert report["applied"] is False
    assert sorted(report["verified_pins"]) == ["dispatch", "entity"]
    assert {row["entity_revision"] for row in report["admitted"]} == {2}
    assert {row["eligibility_status"] for row in report["admitted"]} == {"candidate"}
    for seam in sealed.values():
        assert seam.calls == 0
    assert "no API call, embedding or index write was made" in printed


def test_the_entity_entrypoint_verifies_the_entity_pin_not_the_document_pin(ingest, tmp_path):
    """A consumer must not verify a branch it does not read."""
    loaded = ingest.load_entity_manifest(
        REAL_MANIFEST, contract_schema=CONTRACT, entity_path="candidate"
    )
    assert sorted(loaded.verified_pins) == ["dispatch", "entity"]
    assert "document" not in loaded.verified_pins
    assert loaded.entity_path == "candidate"
    assert len(loaded.records) == 2


def test_the_entity_entrypoint_requires_a_contract_schema(ingest):
    """An optional pin is not a pin, on this entrypoint either."""
    with pytest.raises(ingest.FiscalIngestError, match="--contract-schema is required"):
        ingest.load_entity_manifest(REAL_MANIFEST)


def test_the_entity_entrypoint_refuses_a_document_manifest(ingest, tmp_path):
    path = _document_manifest(ingest, tmp_path)
    with pytest.raises(ingest.FiscalIngestError, match="DOCUMENT record"):
        ingest.load_entity_manifest(path, contract_schema=CONTRACT, entity_path="candidate")


def test_the_document_entrypoint_refuses_an_entity_manifest(ingest):
    """The mirror. Each branch names the other rather than mis-reading it."""
    with pytest.raises(ingest.FiscalIngestError) as excinfo:
        ingest.load_manifest(REAL_MANIFEST, contract_schema=CONTRACT)
    assert "this is an ENTITY record" in str(excinfo.value)
    assert "--record-kind entity" in str(excinfo.value)


def test_a_mixed_manifest_is_refused_at_the_entity_line(ingest, tmp_path):
    """A VALID document record first, then a real entity record.

    Built rather than reused: the committed mixed fixture's document record
    targets no store, so it is refused on line 1 for a different and correct
    reason -- which would have made this test pass without ever reaching the
    dispatch it is about.
    """
    document = _jsonl(_document_manifest(ingest, tmp_path))[0]
    entity = _jsonl(REAL_MANIFEST)[0]
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        "".join(
            json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in (document, entity)
        ),
        encoding="utf-8",
    )
    with pytest.raises(ingest.FiscalIngestError) as excinfo:
        ingest.load_manifest(path, contract_schema=CONTRACT)
    message = str(excinfo.value)
    assert "this is an ENTITY record" in message
    assert ":2:" in message, "the refusal must name the entity line, not the document one"


def test_entity_path_without_record_kind_entity_is_refused(ingest, monkeypatch, tmp_path):
    """A flag that silently does nothing is worse than one that refuses."""
    manifest = _document_manifest(ingest, tmp_path)
    monkeypatch.setattr(sys, "argv", _argv(manifest, tmp_path, "--entity-path", "candidate"))
    with pytest.raises(ingest.FiscalIngestError, match="requires --record-kind entity"):
        ingest.main()


def test_the_default_record_kind_is_document(ingest):
    """The document path is what an unchanged command line still gets."""
    import inspect

    source = inspect.getsource(ingest.parse_args)
    assert '"--record-kind", choices=["document", "entity"], default="document"' in source
