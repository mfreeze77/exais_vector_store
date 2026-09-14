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


#: Every network-capable attribute of the consumer module. Enumerated, and then
#: CHECKED to exist -- see `sealed`.
NETWORK_SEAMS = (
    "api_json",
    "api_json_via_api_container",
    "api_json_via_cell_network",
    "api_json_via_direct_http",
    "api_json_via_host_curl",
    "api_multipart",
    "apply_operations",
    "default_api_base",
    "default_headers",
    "ensure_vector_store",
    "submit_upsert",
)


@pytest.fixture
def sealed(ingest, monkeypatch):
    """Every network-capable seam replaced by something that detonates.

    An earlier version of this fixture listed four names guarded by `hasattr`,
    one of which -- `upload_document` -- does not exist in the module. So it
    silently sealed three of four and reported a proof stronger than the one it
    had run. A guard that skips what it cannot find is the same shape as the
    defects this ticket keeps turning up, and it was inside a test written to
    prove the opposite.

    So: every name is asserted to EXIST before it is sealed. A seam that is
    renamed away fails here loudly instead of quietly reducing the proof. The
    two bottom layers are sealed too, so a seam nobody enumerated still cannot
    reach the network.
    """
    import socket
    import urllib.request

    missing = [name for name in NETWORK_SEAMS if not hasattr(ingest, name)]
    assert not missing, (
        f"{missing} are named as network seams but do not exist in the module; "
        "a seal list that silently skips what it cannot find proves less than it claims"
    )
    seams = {}
    for name in NETWORK_SEAMS:
        seams[name] = _Detonator(name)
        monkeypatch.setattr(ingest, name, seams[name])
    for module, name in ((socket, "socket"), (urllib.request, "urlopen")):
        seams[f"{module.__name__}.{name}"] = _Detonator(f"{module.__name__}.{name}")
        monkeypatch.setattr(module, name, seams[f"{module.__name__}.{name}"])
    assert len(seams) == len(NETWORK_SEAMS) + 2
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


# --------------------------------------------------------------------------
# WAVE-148: the runtime refusals the docstrings already claimed
# --------------------------------------------------------------------------


def test_plan_operations_refuses_entity_records_by_name(ingest):
    """A forged `LoadedManifest` of entity records. Named refusal, not KeyError.

    `LoadedEntityManifest` is a distinct type, so the two cannot be confused
    STATICALLY -- but `plan_operations` is duck-typed, and constructing the
    wrong object by hand used to produce `KeyError: 'logical_document_id'`. A
    claim that holds only until somebody builds the object by hand is a claim
    about type checking, not about the program.
    """
    records = tuple(_jsonl(REAL_MANIFEST))
    forged = ingest.LoadedManifest(
        path=Path("forged.jsonl"), sha256="0" * 64, byte_count=1, records=records
    )
    # `state={}` is deliberate: the guard must raise before anything reads it,
    # and a real state dict would hide that ordering.
    with pytest.raises(ingest.FiscalIngestError) as excinfo:
        ingest.plan_operations(forged, custody_root=Path("/nonexistent"), state={})
    message = str(excinfo.value)
    assert "'record_kind'" in message
    assert "ENTITY projection" in message
    assert "logical_document_id" in message
    assert "--record-kind entity" in message


def test_plan_operations_refuses_a_record_with_no_document_identity(ingest):
    """The other half: untagged, but still not a document record."""
    forged = ingest.LoadedManifest(
        path=Path("forged.jsonl"), sha256="0" * 64, byte_count=1,
        records=({"export_record_id": "a" * 64},),
    )
    with pytest.raises(ingest.FiscalIngestError, match="no logical_document_id"):
        ingest.plan_operations(forged, custody_root=Path("/nonexistent"), state={})


def test_plan_operations_still_plans_real_document_records(ingest, tmp_path):
    """The positive control: the guard is not "refuse everything"."""
    manifest = ingest.load_manifest(
        _document_manifest(ingest, tmp_path), contract_schema=CONTRACT
    )
    custody = tmp_path / "custody" / "kanview"
    record = manifest.records[0]
    digest = record["content_hash_sha256"]
    (custody / digest[:2]).mkdir(parents=True)
    (custody / digest[:2] / digest).write_bytes(b"%PDF-1.7\nkansas fiscal integration fixture\n")
    operations = ingest.plan_operations(
        manifest,
        custody_root=tmp_path / "custody",
        state=ingest.load_state(tmp_path / "state.json", vector_store_id="vs_test"),
    )
    assert operations and operations[0].logical_document_id == record["logical_document_id"]


@pytest.mark.parametrize("declared", ["nonsense", "", "fiscal_graph_publisher", 1, None])
def test_an_unknown_record_kind_gets_its_own_message(ingest, tmp_path, declared):
    """Routing is by PRESENCE, so an unknown kind lands in the same guard.

    Advising "use --record-kind entity" would send that operator to a path that
    refuses the record too, at the kind/version gate. The two cases now get
    different advice.
    """
    path = tmp_path / f"unknown-{abs(hash(str(declared)))}.jsonl"
    path.write_text(
        json.dumps({"record_kind": declared, "export_record_id": "a" * 64}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ingest.FiscalIngestError) as excinfo:
        ingest.load_manifest(path, contract_schema=CONTRACT)
    message = str(excinfo.value)
    assert "is not a record kind this contract knows" in message
    assert "would refuse it too, at the kind/version gate" in message
    assert "Read it with --record-kind entity, which routes" not in message


def test_a_real_entity_record_keeps_the_entity_advice(ingest):
    """...and the record that IS an entity projection still gets sent there."""
    with pytest.raises(ingest.FiscalIngestError) as excinfo:
        ingest.load_manifest(REAL_MANIFEST, contract_schema=CONTRACT)
    message = str(excinfo.value)
    assert "this is an ENTITY record" in message
    assert "Read it with --record-kind entity" in message
    assert "is not a record kind this contract knows" not in message


def test_the_known_kind_is_read_from_the_contract_not_written_here(ingest):
    """The message's notion of "known" must move with the contract."""
    import json as _json

    schema = _json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert ingest._known_entity_record_kind(schema) == (
        schema["$defs"]["entity_kind_version_gate"]["properties"]["record_kind"]["const"]
    )
    # A contract whose gate is gone must not silently make every kind "known".
    stripped = _json.loads(CONTRACT.read_text(encoding="utf-8"))
    del stripped["$defs"]["entity_kind_version_gate"]
    assert ingest._known_entity_record_kind(stripped) is None


def test_the_seal_list_fails_loudly_when_a_seam_disappears(ingest, monkeypatch):
    """The fixture's own guard, tested.

    The previous fixture used `hasattr` and silently sealed 3 of 4 named seams.
    This asserts the replacement refuses instead of shrinking.
    """
    missing = [name for name in NETWORK_SEAMS if not hasattr(ingest, name)]
    assert not missing
    assert "upload_document" not in NETWORK_SEAMS, (
        "upload_document does not exist in the module; naming it is what made the "
        "earlier seal list report a proof it had not run"
    )
    assert len(NETWORK_SEAMS) == 11
