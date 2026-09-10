"""CSV verifier mechanics and opt-in proof against retained Education extracts.

Mechanics examples are synthetic parser inputs, never graph acceptance fixtures.
Real-source proof requires both read-only corpus/custody mounts and reads only
the already identified FY2025/FY2026 ExpData_652 files and their manifests.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from svs_common.fiscal_graph_artifact import (
    MAX_STRUCTURED_SOURCE_BYTES,
    FiscalGraphArtifactError,
    sha256_json,
    validate_built_artifact,
    verify_structured_csv_evidence,
)
from svs_common.schemas import FiscalStructuredRecordEvidence, FiscalStructuredRecordLocator

ROOT = Path(__file__).resolve().parents[1]
CORPUS = os.environ.get("SVS_FISCAL_CORPUS_ROOT")
CUSTODY = os.environ.get("SVS_FISCAL_CUSTODY_ROOT")
REAL_SOURCES = {
    2025: ("6a96fc93c1721fe66479aadc988b53575648df7b24065d5b3674e86fe1234949", [987, 2568, 3742]),
    2026: ("ea386136d6135334aa71f84331ec8ab68b2d5c83d9b992efe72b41e1a569eaed", [384, 2671]),
}


def _load_script(filename: str):
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), ROOT / "scripts/release" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reference(number: int, headers: list[str], values: list[str]) -> dict:
    return {"data_record_1based": number, "raw_record_sha256": sha256_json({"headers": headers, "values": values})}


def _verify(source: bytes, records: list[dict], source_hash: str | None = None) -> dict:
    return verify_structured_csv_evidence(
        source_bytes=source, expected_source_sha256=source_hash or hashlib.sha256(source).hexdigest(), records=records,
    )


def test_exact_strings_bom_and_multiline_csv_records_have_distinct_line_locators():
    source = '\ufeffcode,description,total,\r\n"00840","quoted, value\r\nline 2 ""yes""", 001.20 ,\r\n840,plain,0,\r\n'.encode()
    headers = ["code", "description", "total", ""]
    references = [
        _reference(2, headers, ["840", "plain", "0", ""]),
        _reference(1, headers, ["00840", 'quoted, value\r\nline 2 "yes"', " 001.20 ", ""]),
    ]
    result = _verify(source, references)
    assert result["source_content_hash_sha256"] == hashlib.sha256(source).hexdigest()
    assert result["source_byte_size"] == len(source)
    assert result["source_records_read"] == result["verified_records"] == 2
    assert [row["locator"] for row in result["records"]] == [
        {"kind": "csv_record", "header_records": 1, "data_record_1based": 1, "physical_line_end_1based": 3},
        {"kind": "csv_record", "header_records": 1, "data_record_1based": 2, "physical_line_end_1based": 4},
    ]
    assert [row["raw_record_sha256"] for row in result["records"]] == [row["raw_record_sha256"] for row in reversed(references)]
    assert result["evidence_only"] is True and result["publication_allowed"] is False
    assert result["evidence_kind"] == "structured_record"
    with pytest.raises(FiscalGraphArtifactError, match="unsupported built artifact version"):
        validate_built_artifact(result)
    for forbidden in ("canonical_id", "source_revision_id", "chunk_id", "document_id", "load_request", "raw_record", "00840"):
        assert json.dumps(forbidden) not in json.dumps(result)
    assert _verify(source, list(reversed(references))) == result


def test_identical_rows_at_distinct_locators_are_not_deduplicated():
    result = _verify(b"code\n00840\n00840\n", [_reference(number, ["code"], ["00840"]) for number in (1, 2)])
    assert result["verified_records"] == 2
    assert result["records"][0]["raw_record_sha256"] == result["records"][1]["raw_record_sha256"]


def test_multiline_verifier_records_compose_unchanged_with_typed_source_evidence():
    # Explicit mechanics revision only; the byte verifier supplies no canonical
    # source identity, publication decision, or parsed-output parent relationship.
    source = b'code,description\n00840,"line one\nline two"\n840,plain\n'
    headers = ['code', 'description']
    result = _verify(source, [_reference(1, headers, ['00840', 'line one\nline two']),
                              _reference(2, headers, ['840', 'plain'])])
    for record in result['records']:
        original = json.loads(json.dumps(record))
        evidence = FiscalStructuredRecordEvidence(
            source_revision_id='explicit-mechanics-fixture-source-revision',
            source_content_hash_sha256=result['source_content_hash_sha256'],
            **record,
        )
        assert record == original
        assert evidence.locator.model_dump(exclude={'selected_columns'}) == record['locator']
        assert evidence.raw_record_sha256 == record['raw_record_sha256']
        assert evidence.extraction_revision_id is None
        assert evidence.locator.physical_line_end_1based > evidence.locator.data_record_1based + 1


@pytest.mark.parametrize("source,reference,match", [
    (b"code\n00840\n", _reference(1, ["code"], ["840"]), "record 1 hash mismatch"),
    (b"code\n00840\n", _reference(2, ["code"], ["00840"]), "missing requested"),
    (b"code,code\n00840,00840\n", _reference(1, ["code", "code"], ["00840", "00840"]), "duplicate headers"),
    (b"code\n00840\nextra,column\n", _reference(1, ["code"], ["00840"]), "unexpected column count"),
    (b"code\n00840\n\n", _reference(1, ["code"], ["00840"]), "unexpected column count"),
    (b'code\n00840\n"unterminated', _reference(1, ["code"], ["00840"]), "well-formed"),
    (b"code\n\xff\n", _reference(1, ["code"], ["00840"]), "valid UTF-8"),
    (b"", _reference(1, ["code"], ["00840"]), "header record"),
    (b"\n", _reference(1, ["code"], ["00840"]), "header record"),
])
def test_bad_csv_or_record_evidence_is_rejected_even_after_a_matching_row(source, reference, match):
    with pytest.raises(FiscalGraphArtifactError, match=match):
        _verify(source, [reference])


@pytest.mark.parametrize("number", [True, False, 0, -1, "1", 1.0, 100001, None])
def test_record_locator_requires_a_bounded_strict_positive_integer(number):
    with pytest.raises(FiscalGraphArtifactError, match="integer in"):
        _verify(b"code\n00840\n", [{"data_record_1based": number, "raw_record_sha256": "a" * 64}])


@pytest.mark.parametrize("records,match", [
    ([], "1..1000"),
    ({}, "1..1000"),
    ([None], "requires only"),
    ([{"data_record_1based": 1}], "requires only"),
    ([{"data_record_1based": 1, "raw_record_sha256": "a" * 64, "publication_allowed": True}], "requires only"),
    ([{"data_record_1based": 1, "raw_record_sha256": "A" * 64}], "lowercase SHA-256"),
    ([{"data_record_1based": 1, "raw_record_sha256": "a" * 63}], "lowercase SHA-256"),
    ([{"data_record_1based": 1, "raw_record_sha256": "a" * 64}] * 2, "duplicate CSV"),
    ([{"data_record_1based": 1, "raw_record_sha256": value * 64} for value in ("a", "b")], "duplicate CSV"),
    ([{"data_record_1based": 1, "raw_record_sha256": "a" * 64}] * 1001, "1..1000"),
])
def test_missing_duplicate_malformed_or_excessive_references_are_rejected(records, match):
    with pytest.raises(FiscalGraphArtifactError, match=match):
        _verify(b"code\n00840\n", records)


@pytest.mark.parametrize("source_hash", ["a" * 64, "A" * 64, "bad"])
def test_expected_source_digest_is_required_and_checked(source_hash):
    with pytest.raises(FiscalGraphArtifactError, match="source hash mismatch|lowercase SHA-256"):
        _verify(b"code\n00840\n", [_reference(1, ["code"], ["00840"])], source_hash)


@pytest.mark.parametrize("source,match", [
    (b"a" * (MAX_STRUCTURED_SOURCE_BYTES + 1), "bounded bytes"),
    ((",".join(f"h{i}" for i in range(257)) + "\n").encode(), "256 columns"),
    (b"header\n" + b"a" * 65537, "65536 characters"),
    (b"a" * 65537 + b"\nx\n", "65536 characters"),
    (b"header\n" + b"a" * 131073, "bounded, well-formed"),
    (b"code\n" + b"00840\n" * 100001, "100000 data records"),
])
def test_source_parser_and_record_budgets_are_enforced(source, match):
    with pytest.raises(FiscalGraphArtifactError, match=match):
        _verify(source, [_reference(1, ["code"], ["00840"])])


def test_offline_cli_never_calls_runtime_or_requires_artifact_or_credentials(tmp_path, monkeypatch, capsys):
    cli = _load_script("kansas-fiscal-graphrag.py")
    source = tmp_path / "source.csv"
    source.write_bytes(b"code\n00840\n")
    references = tmp_path / "records.json"
    references.write_text(json.dumps([_reference(1, ["code"], ["00840"])]))

    def forbidden(*args, **kwargs):
        pytest.fail("offline evidence verification entered a runtime artifact/API path")

    monkeypatch.setattr(cli, "_call", forbidden)
    monkeypatch.setattr(cli, "validate_built_artifact", forbidden)
    monkeypatch.setattr(cli, "_safe_api", forbidden)
    monkeypatch.setattr("sys.argv", ["kansas-fiscal-graphrag.py", "verify-structured-evidence", "--source-csv", str(source),
                                    "--source-sha256", hashlib.sha256(source.read_bytes()).hexdigest(), "--records", str(references)])
    assert cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["verified_records"] == 1 and result["publication_allowed"] is False
    assert "00840" not in json.dumps(result)


def test_cli_rejects_non_regular_or_oversized_source_without_reading(tmp_path):
    cli = _load_script("kansas-fiscal-graphrag.py")
    with pytest.raises(ValueError, match="regular file"):
        cli._read_csv_bytes(tmp_path)
    oversized = tmp_path / "oversized.csv"
    with oversized.open("wb") as handle:
        handle.truncate(MAX_STRUCTURED_SOURCE_BYTES + 1)
    with pytest.raises(ValueError, match="16 MiB"):
        cli._read_csv_bytes(oversized)


@pytest.fixture(scope="module")
def retained_education_sources():
    if not (CORPUS and CUSTODY):
        pytest.skip("requires retained real KanView corpus and custody read-only mounts")
    audit = _load_script("kansas-fiscal-corpus-audit.py")
    return {year: audit.inspect_year(Path(CORPUS), Path(CUSTODY), "652-00-1000-0840", year) for year in REAL_SOURCES}


@pytest.mark.parametrize("year", [2025, 2026])
def test_real_selected_records_match_official_manifest_custody_and_independent_audit(retained_education_sources, year):
    evidence = retained_education_sources[year]
    pinned_hash, locators = REAL_SOURCES[year]
    assert evidence["source"]["content_hash_sha256"] == pinned_hash
    assert evidence["source"]["manifest_verified"] and evidence["source"]["custody_bytes_verified"]
    assert [row["locator"]["data_record_1based"] for row in evidence["records"]] == locators
    references = [{"data_record_1based": row["locator"]["data_record_1based"], "raw_record_sha256": row["raw_record_sha256"]}
                  for row in evidence["records"]]
    result = _verify((Path(CORPUS) / evidence["source"]["relative_path"]).read_bytes(), references, pinned_hash)
    assert result["source_records_read"] == evidence["source_records_read"]
    assert result["records"] == [{"locator": row["locator"], "raw_record_sha256": row["raw_record_sha256"]}
                                  for row in evidence["records"]]
    assert result["verified_records"] == len(locators)
    assert result["publication_allowed"] is False
    assert evidence["candidate_components"]["subunit"] is None
    assert evidence["legal_account_match"] == "candidate_missing_subunit"
    assert "canonical_id" not in result and "total" not in result


@pytest.mark.parametrize('year,record_number', [(2025, 987), (2025, 2568), (2025, 3742), (2026, 384), (2026, 2671)])
def test_real_verifier_locator_composes_unchanged_without_inventing_revision_ids(
    retained_education_sources, year, record_number,
):
    audited = retained_education_sources[year]
    retained_record = next(row for row in audited['records'] if row['locator']['data_record_1based'] == record_number)
    result = _verify((Path(CORPUS) / audited['source']['relative_path']).read_bytes(), [{
        'data_record_1based': record_number, 'raw_record_sha256': retained_record['raw_record_sha256'],
    }], REAL_SOURCES[year][0])
    raw_locator = result['records'][0]['locator']
    # Validate the real locator directly: the source-only verifier cannot supply
    # an upstream canonical revision, so this test must not manufacture one.
    typed_locator = FiscalStructuredRecordLocator.model_validate(raw_locator)
    assert typed_locator.model_dump(exclude={'selected_columns'}) == raw_locator == retained_record['locator']
    assert typed_locator.data_record_1based == record_number
    assert typed_locator.physical_line_end_1based >= record_number + typed_locator.header_records


@pytest.mark.parametrize("year", [2025, 2026])
def test_real_source_corruption_wrong_locator_and_changed_raw_value_fail(retained_education_sources, year):
    evidence = retained_education_sources[year]
    source = (Path(CORPUS) / evidence["source"]["relative_path"]).read_bytes()
    original = evidence["records"][0]
    reference = {"data_record_1based": original["locator"]["data_record_1based"], "raw_record_sha256": original["raw_record_sha256"]}
    with pytest.raises(FiscalGraphArtifactError, match="source hash mismatch"):
        _verify(source + b" ", [reference], REAL_SOURCES[year][0])
    with pytest.raises(FiscalGraphArtifactError, match="hash mismatch"):
        _verify(source, [{**reference, "data_record_1based": reference["data_record_1based"] + 1}])
    changed = {"headers": list(original["raw_record"]["headers"]), "values": list(original["raw_record"]["values"])}
    index = changed["headers"].index("Budget_Ref")
    changed["values"][index] = "840" if year == 2025 else "0840"
    with pytest.raises(FiscalGraphArtifactError, match="hash mismatch"):
        _verify(source, [{**reference, "raw_record_sha256": sha256_json(changed)}])


def test_real_cli_verifies_five_exact_rows_without_emitting_source_text(retained_education_sources, tmp_path, monkeypatch, capsys):
    cli = _load_script("kansas-fiscal-graphrag.py")
    verified = 0
    for year, evidence in retained_education_sources.items():
        references = tmp_path / f"FY{year}-references.json"
        references.write_text(json.dumps([
            {"data_record_1based": row["locator"]["data_record_1based"], "raw_record_sha256": row["raw_record_sha256"]}
            for row in evidence["records"]
        ]))
        monkeypatch.setattr("sys.argv", ["kansas-fiscal-graphrag.py", "verify-structured-evidence", "--source-csv",
                                        str(Path(CORPUS) / evidence["source"]["relative_path"]), "--source-sha256",
                                        REAL_SOURCES[year][0], "--records", str(references)])
        assert cli.main() == 0
        output = capsys.readouterr().out
        result = json.loads(output)
        assert result["publication_allowed"] is False and result["evidence_only"] is True
        assert "SUPPLEMENTAL GENERAL STATE AID" not in output and "raw_record\"" not in output
        verified += result["verified_records"]
    assert verified == 5
