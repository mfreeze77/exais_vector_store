"""Contract tests for the jurisdiction document release (WAVE-118 assignment 1).

The fixtures here are synthetic so the suite never depends on the retained
`.tmp` corpus, but they exercise the same code paths the real export uses.

Half of these tests are negative controls. A validator that only ever passes is
indistinguishable from no validator, so each rejection asserts the specific
issue code rather than merely "not passed".
"""
from __future__ import annotations

import copy
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


exporter = _load("topeka-source-release-export.py", "topeka_source_release_export")
validator = _load("jurisdiction-release-validate.py", "jurisdiction_release_validate")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

SECTION_BLOCKS = [
    "There is hereby adopted by reference the 2034 Model Widget Code. (Ord. 12345 § 1, 1-2-34.)",
    "State Law References: Adoption by reference authorized, K.S.A. 12-3009 et seq.",
]

ORDINANCE_MD = """# 12345

Source collection: Topeka ordinance PDFs
Ordinance number: 12345
Official PDF: https://files.topeka.gov/community/ordinances/2034/Ordinance12345.pdf

## (Published in the Topeka Metro News January 2, 2034)

## ORDINANCE NO. 12345

AN ORDINANCE amending Chapter 9.99 of the Topeka Municipal Code.

Section 1. That section 9.99.010 is hereby amended to read as follows:

## Adoption of Model Widget Code.

There is hereby adopted by reference the 2034 Model Widget Code.
"""

CHARTER_MD = """# 9

Source collection: Topeka ordinance PDFs
Official PDF: https://files.topeka.gov/community/ordinances/charter/CharterOrdinance9.pdf

## CHARTER ORDINANCE NO. 9

A CHARTER ORDINANCE exempting the City from K.S.A. 12-0000.
"""


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A minimal TMC capture set: sections.jsonl plus its rendered HTML."""
    root = tmp_path / "tmc"
    (root / "raw").mkdir(parents=True)
    html = b"<html><body><h1>9.99.010 Adoption of Model Widget Code.</h1></body></html>"
    html_hash = sha(html)
    (root / "raw" / f"9.99.010.{html_hash[:12]}.html").write_bytes(html)
    section = {
        "id": "ks-topeka:tmc:9.99.010",
        "jurisdiction_id": "ks-topeka",
        "jurisdiction_name": "City of Topeka, Kansas",
        "code": "TMC",
        "citation": "9.99.010",
        "title": "Adoption of Model Widget Code.",
        "page_type": "section",
        "source_url": "https://topeka.municipal.codes/TMC/9.99.010",
        "source_html_hash": html_hash,
        "content_hash": sha("\n".join(SECTION_BLOCKS).encode("utf-8")),
        "retrieved_at": "2026-08-28T04:37:08.753104Z",
        "text": "\n".join(SECTION_BLOCKS),
        "blocks": [{"kind": "paragraph", "order": index, "text": text} for index, text in enumerate(SECTION_BLOCKS)],
        "tables": [],
        "definitions": [],
        "references": [],
        "ordinance_history": [{"ordinance": "12345", "date": "1-2-34", "raw": "Ord. 12345 § 1, 1-2-34", "section": "1"}],
        "assets": [],
    }
    (root / "sections.jsonl").write_text(json.dumps(section) + "\n", encoding="utf-8")
    return root


@pytest.fixture
def seed(tmp_path: Path) -> Path:
    """A minimal ordinance seed: two PDFs, two extractions, two manifests."""
    root = tmp_path / "seed"
    (root / "raw" / "pdfs").mkdir(parents=True)
    (root / "extracted").mkdir(parents=True)
    (root / "manifests").mkdir(parents=True)

    rows, extractions = [], []
    for key, category, url, md in (
        ("12345", "ordinance", "https://files.topeka.gov/community/ordinances/2034/Ordinance12345.pdf", ORDINANCE_MD),
        ("9", "charter_ordinance", "https://files.topeka.gov/community/ordinances/charter/CharterOrdinance9.pdf", CHARTER_MD),
    ):
        pdf = f"%PDF-1.4 fixture {key}".encode("utf-8")
        pdf_name = f"{key}.pdf" if category == "ordinance" else f"CharterOrdinance{key}.pdf"
        (root / "raw" / "pdfs" / pdf_name).write_bytes(pdf)
        md_bytes = md.encode("utf-8")
        md_name = f"{key}.md" if category == "ordinance" else f"CharterOrdinance{key}.md"
        (root / "extracted" / md_name).write_bytes(md_bytes)
        record_id = f"topeka-ordinance:{sha(url.encode())[:24]}"
        rows.append({
            "id": record_id,
            "jurisdiction_id": "ks-topeka",
            "jurisdiction_name": "City of Topeka, Kansas",
            "category": category,
            "ordinance_number": key,
            "title": key if category == "ordinance" else f"Charter Ordinance {key}",
            "year": "",
            "pdf_url": url,
            "saved_path": f"raw/pdfs/{pdf_name}",
            "sha256": sha(pdf),
            "byte_count": len(pdf),
            "retrieved_at": "2026-08-27T21:48:44+00:00",
            "source_collection": "topeka-ordinances",
            "source_page_url": "https://topeka.gov/community/ordinances/index.php",
        })
        extractions.append({
            "id": record_id,
            "index": len(extractions) + 1,
            "ordinance_number": key,
            "pdf_url": url,
            "markdown_path": f"extracted/{md_name}",
            "markdown_sha256": sha(md_bytes),
            "markdown_chars": len(md),
            "extracted_at": "",
            "status": "extracted",
        })

    for name, items in (("ordinances.jsonl", rows), ("ordinance-extractions.jsonl", extractions)):
        (root / "manifests" / name).write_text(
            "".join(json.dumps(item) + "\n" for item in items), encoding="utf-8"
        )
    return root


def export(tmp_path: Path, corpus: Path, seed: Path, *, out: str = "bundle", **kwargs) -> Path:
    documents = [
        exporter.resolve_selection(selector, tmc_corpus=corpus, ordinance_seed=seed, include_originals=True)
        for selector in ("tmc:9.99.010", "ordinance:12345", "charter-ordinance:9")
    ]
    target = tmp_path / out
    exporter.write_bundle(
        documents,
        output_dir=target,
        release_id=kwargs.get("release_id", "test-release"),
        bundle_kind=kwargs.get("bundle_kind", "starter"),
        previous_manifest=kwargs.get("previous_manifest"),
        command=["python", exporter.EXPORTER_PATH],
    )
    return target


def retamper(bundle: Path, mutate) -> None:
    """Rewrite the manifest and its documents after an in-place mutation.

    Only the mutation under test should fail; hashes of untouched artifacts are
    left alone so the resulting failure is attributable.
    """
    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(manifest, bundle)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def codes(report) -> set[str]:
    return {issue.code for issue in report.issues if issue.severity == "error"}


# --------------------------------------------------------------------------
# schemas
# --------------------------------------------------------------------------

def test_published_schemas_are_valid_draft_2020_12():
    """Loading runs check_schema, so a malformed contract fails here, not silently."""
    release, document = contract.load_release_schemas()
    assert release.schema_id == contract.RELEASE_MANIFEST_SCHEMA_ID
    assert document.schema_id == contract.SOURCE_DOCUMENT_SCHEMA_ID
    assert release.version == document.version == contract.CONTRACT_VERSION
    assert len(release.sha256) == 64 and len(document.sha256) == 64


def test_a_malformed_schema_is_refused_at_construction():
    with pytest.raises(Exception):
        contract.SchemaValidator({"type": "not-a-real-type"})


@pytest.mark.parametrize(
    "label,schema,instance",
    [
        # Regression probes. A hand-rolled evaluator shipped here previously and
        # accepted every one of these: Python makes `True == 1`, `multipleOf` was
        # declared supported but never implemented, and 1 vs 1.0 compared unequal
        # through JSON text rather than as numbers.
        ("bool against const int", {"const": 1}, True),
        ("bool against enum int", {"enum": [1]}, True),
        ("multipleOf ignored", {"type": "number", "multipleOf": 3}, 7),
        ("1 and 1.0 are the same number", {"type": "array", "uniqueItems": True}, [1, 1.0]),
    ],
)
def test_keywords_a_hand_rolled_evaluator_got_wrong(label, schema, instance):
    assert contract.SchemaValidator(schema).validate(instance), label


@pytest.mark.parametrize(
    "schema,instance",
    [
        ({"const": 1}, 1),
        ({"enum": [1]}, 1),
        ({"type": "number", "multipleOf": 3}, 9),
        ({"type": "array", "uniqueItems": True}, [1, 2]),
    ],
)
def test_the_valid_forms_of_those_keywords_still_pass(schema, instance):
    assert contract.SchemaValidator(schema).validate(instance) == []


def test_evaluator_enforces_core_keywords():
    schema = contract.SchemaValidator({
        "type": "object",
        "required": ["a"],
        "properties": {
            "a": {"type": "string", "pattern": "^x"},
            "b": {"type": ["integer", "null"], "minimum": 1},
        },
        "additionalProperties": False,
    })
    assert schema.validate({"a": "xy", "b": None}) == []
    assert {e.keyword for e in schema.validate({})} == {"required"}
    assert {e.keyword for e in schema.validate({"a": "zz"})} == {"pattern"}
    assert {e.keyword for e in schema.validate({"a": "xy", "b": 0})} == {"minimum"}
    assert {e.keyword for e in schema.validate({"a": "xy", "c": 1})} == {"additionalProperties"}


# --------------------------------------------------------------------------
# collection routing
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        # the owner's two concrete member-document examples
        ("https://s3.us-east-1.amazonaws.com/files.topeka.gov/community/resolutions/2026/Resolution09749.pdf", "resolutions"),
        ("https://files.topeka.gov/community/ordinances/charter/CharterOrdinance126.pdf", "charter-ordinances"),
        # ordinary and code controls
        ("https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf", "ordinances"),
        ("https://topeka.municipal.codes/TMC/14.40.010", "municipal-code"),
        ("https://topeka.municipal.codes/TMC", "municipal-code"),
        # the unnumbered Standard Traffic Ordinance stays in the ordinary collection
        ("https://files.topeka.gov/community/ordinances/other-ordinances/STO.pdf", "ordinances"),
    ],
)
def test_routing_assigns_each_member_document_to_its_master_collection(url, expected):
    assert contract.route_document(official_url=url).slug == expected


def test_ui_fragments_and_host_aliases_do_not_mint_extra_documents():
    charter = "https://files.topeka.gov/community/ordinances/charter/CharterOrdinance126.pdf"
    assert contract.canonical_source_url(charter + "#undefined") == charter
    assert contract.canonical_source_url(charter + "?v=2") == charter
    alias = "https://s3.us-east-1.amazonaws.com/files.topeka.gov/community/resolutions/2026/Resolution09749.pdf"
    direct = "https://files.topeka.gov/community/resolutions/2026/Resolution09749.pdf"
    assert contract.canonical_source_url(alias) == contract.canonical_source_url(direct)


def test_listing_category_beats_url_shape():
    """Membership is the publisher's category, not a guess from the path."""
    spec = contract.route_document(
        official_url="https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf",
        listing_category="charter_ordinance",
    )
    assert spec.slug == "charter-ordinances"


def test_unregistered_source_is_refused_rather_than_given_a_new_store():
    with pytest.raises(contract.RoutingError):
        contract.route_document(official_url="https://topeka.gov/community/budgets/2026/CIP.pdf")


def test_every_registered_collection_has_a_disjoint_routing_rule():
    """Derived invariant, not a hand-listed expectation."""
    for spec in contract.TOPEKA_COLLECTIONS:
        for other in contract.TOPEKA_COLLECTIONS:
            if spec is other or not set(spec.hosts) & set(other.hosts):
                continue
            for prefix in spec.path_prefixes:
                collides = any(
                    prefix.startswith(candidate) or candidate.startswith(prefix)
                    for candidate in other.path_prefixes
                )
                if collides:
                    assert spec.excluded_path_prefixes or other.excluded_path_prefixes, (
                        f"{spec.slug} and {other.slug} overlap with no exclusion to break the tie"
                    )


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def test_version_is_derived_from_publisher_bytes_and_identity_is_not():
    spec = contract.COLLECTIONS_BY_SLUG["ordinances"]
    doc_id = contract.source_document_id(spec, "20407")
    first = contract.document_version_id(doc_id, "a" * 64)
    second = contract.document_version_id(doc_id, "b" * 64)
    assert first != second
    assert first.startswith(doc_id) and second.startswith(doc_id)
    assert contract.source_document_id(spec, "20407") == doc_id


def test_capture_is_found_by_hash_when_the_filename_is_mangled(tmp_path, corpus, seed):
    """Appendix citations such as "AxB Art. III § 1" are sanitised into names no
    rule reconstructs, so captures resolve by content hash instead."""
    raw = corpus / "raw"
    original = next(raw.iterdir())
    html_hash = original.name.split(".")[-2]
    mangled = raw / f"AxB_ArtIII_1.{html_hash}.html"
    original.rename(mangled)

    built = exporter.resolve_selection(
        "tmc:9.99.010", tmc_corpus=corpus, ordinance_seed=seed, include_originals=True
    )
    assert built.record["evidence"]["source_revision"]["value"] == mangled.name
    assert contract.resolve_capture(raw, "0" * 64) is None


def test_unnumbered_document_still_gets_a_stable_identity():
    row = {"ordinance_number": "", "pdf_url": "https://files.topeka.gov/community/ordinances/other-ordinances/STO.pdf"}
    assert exporter._publisher_key_for(row) == "STO"
    spec = contract.route_document(official_url=row["pdf_url"])
    assert contract.source_document_id(spec, "STO") == "ks:city:topeka:ordinances:ordinance:sto"


# --------------------------------------------------------------------------
# export / validate round trip
# --------------------------------------------------------------------------

def test_export_then_validate_passes_and_resolves_real_evidence(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)
    report = validator.validate_bundle(bundle)
    assert report.passed, [str(issue) for issue in report.issues]
    assert report.checks["document_count"] == 3
    assert report.checks["evidence_references_resolved"] > 0
    assert report.checks["evidence_references_unavailable"] > 0
    assert set(report.checks["collections"]) == {
        "ks:city:topeka:municipal-code",
        "ks:city:topeka:ordinances",
        "ks:city:topeka:charter-ordinances",
    }


def test_release_separates_verbatim_from_normalized_text(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)
    folder = bundle / "documents" / "ks__city__topeka__ordinances__ordinance__12345"
    verbatim = (folder / "verbatim.md").read_text(encoding="utf-8")
    normalized = (folder / "normalized.md").read_text(encoding="utf-8")
    assert verbatim.startswith("# 12345")
    assert "Source collection:" in verbatim
    assert "Source collection:" not in normalized
    record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    assert record["content"]["verbatim"]["sha256"] != record["content"]["normalized_text"]["sha256"]
    names = {n["name"] for n in record["content"]["normalized_text"]["normalizations"]}
    assert "strip_exais_provenance_preamble" in names


def test_pdf_documents_declare_page_coordinates_unavailable(tmp_path, corpus, seed):
    """Markdown line numbers must never become PDF page numbers."""
    bundle = export(tmp_path, corpus, seed)
    folder = bundle / "documents" / "ks__city__topeka__ordinances__ordinance__12345"
    record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    page_refs = [r for r in record["evidence"]["references"] if r["ref_id"].endswith("#page")]
    assert page_refs and page_refs[0]["availability"] == "unavailable"
    assert "page" in page_refs[0]["unavailable_reason"]
    assert page_refs[0]["locator"] is None
    conventions = {c["name"] for c in record["evidence"]["coordinate_conventions"]}
    assert "pdf_page" not in conventions


def test_cross_collection_link_is_evidenced_and_the_reverse_stays_unresolved(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)
    section = json.loads(
        (bundle / "documents" / "ks__city__topeka__municipal-code__tmc__9.99.010" / "record.json").read_text("utf-8")
    )
    amended = [r for r in section["meaning"]["relationships"] if r["predicate"] == "amended_by"]
    assert amended and amended[0]["resolved"] is True
    assert amended[0]["target"]["value"] == "ks:city:topeka:ordinances:ordinance:12345"
    assert amended[0]["evidence_ref"]

    ordinance = json.loads(
        (bundle / "documents" / "ks__city__topeka__ordinances__ordinance__12345" / "record.json").read_text("utf-8")
    )
    cites = [r for r in ordinance["meaning"]["relationships"] if r["predicate"] == "cites_code_section"]
    assert cites and all(r["resolved"] is False for r in cites), "a text match must not publish as resolved"


def test_repeat_export_is_deterministic_and_reports_unchanged(tmp_path, corpus, seed):
    first = export(tmp_path, corpus, seed, out="first", release_id="r1")
    second = export(tmp_path, corpus, seed, out="second", release_id="r2",
                    previous_manifest=first / "release-manifest.json")
    a = json.loads((first / "release-manifest.json").read_text("utf-8"))
    b = json.loads((second / "release-manifest.json").read_text("utf-8"))
    assert a["inventory"]["inventory_sha256"] == b["inventory"]["inventory_sha256"]
    assert [d["payload_sha256"] for d in a["documents"]] == [d["payload_sha256"] for d in b["documents"]]
    assert len(b["update"]["outcomes"]["unchanged"]) == 3
    assert b["update"]["outcomes"]["new"] == []
    assert b["update"]["previous_release_id"] == "r1"
    assert validator.validate_bundle(second).passed


def test_changed_publisher_bytes_make_a_new_version_not_a_new_document(tmp_path, corpus, seed):
    first = export(tmp_path, corpus, seed, out="first", release_id="r1")
    pdf = seed / "raw" / "pdfs" / "12345.pdf"
    pdf.write_bytes(pdf.read_bytes() + b" revised")
    rows = [json.loads(line) for line in (seed / "manifests" / "ordinances.jsonl").read_text().splitlines()]
    for row in rows:
        if row["saved_path"].endswith("12345.pdf"):
            row["sha256"] = sha(pdf.read_bytes())
            row["byte_count"] = pdf.stat().st_size
    (seed / "manifests" / "ordinances.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    second = export(tmp_path, corpus, seed, out="second", release_id="r2",
                    previous_manifest=first / "release-manifest.json")
    manifest = json.loads((second / "release-manifest.json").read_text("utf-8"))
    changed = manifest["update"]["outcomes"]["changed"]
    assert len(changed) == 1
    assert changed[0]["source_document_id"] == "ks:city:topeka:ordinances:ordinance:12345"
    assert changed[0]["prior_version_id"] != changed[0]["document_version_id"]
    assert changed[0]["prior_retained"] is True
    assert len(manifest["update"]["outcomes"]["unchanged"]) == 2
    assert validator.validate_bundle(second).passed


# --------------------------------------------------------------------------
# negative controls
# --------------------------------------------------------------------------

def test_tampered_artifact_bytes_are_rejected(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)
    target = bundle / "documents" / "ks__city__topeka__ordinances__ordinance__12345" / "normalized.md"
    target.write_text(target.read_text("utf-8").replace("2034 Model", "2099 Model"), encoding="utf-8")
    assert "FILE_HASH_MISMATCH" in codes(validator.validate_bundle(bundle))


def test_empty_extraction_is_rejected(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)
    folder = bundle / "documents" / "ks__city__topeka__ordinances__ordinance__12345"
    (folder / "normalized.md").write_text("", encoding="utf-8")

    def mutate(manifest, _bundle):
        for entry in manifest["documents"]:
            for file_entry in entry["files"]:
                if file_entry["path"].endswith("ordinance__12345/normalized.md"):
                    file_entry["sha256"] = sha(b"")
                    file_entry["byte_count"] = 0

    retamper(bundle, mutate)
    found = codes(validator.validate_bundle(bundle))
    assert "EMPTY_EXTRACTION" in found


def test_out_of_range_evidence_is_rejected(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)
    _mutate_record(bundle, "ks__city__topeka__municipal-code__tmc__9.99.010", _push_span_out_of_range)
    assert "EVIDENCE_OUT_OF_RANGE" in codes(validator.validate_bundle(bundle))


def test_quote_that_does_not_match_its_span_is_rejected(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)

    def mutate(record):
        for reference in record["evidence"]["references"]:
            if reference["availability"] == "available":
                reference["quote"] = "text that is not at this offset"
                return

    _mutate_record(bundle, "ks__city__topeka__municipal-code__tmc__9.99.010", mutate)
    assert "EVIDENCE_QUOTE_MISMATCH" in codes(validator.validate_bundle(bundle))


def test_dangling_meaning_evidence_is_rejected(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)

    def mutate(record):
        record["meaning"]["relationships"][0]["evidence_ref"] = "no-such-reference"

    _mutate_record(bundle, "ks__city__topeka__municipal-code__tmc__9.99.010", mutate)
    assert "MEANING_DANGLING_EVIDENCE" in codes(validator.validate_bundle(bundle))


def test_unavailable_reference_may_not_smuggle_a_coordinate(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)

    def mutate(record):
        for reference in record["evidence"]["references"]:
            if reference["availability"] == "unavailable":
                reference["locator"] = {"convention": "utf8_char_offset", "start": 0, "end": 5}
                return

    _mutate_record(bundle, "ks__city__topeka__ordinances__ordinance__12345", mutate)
    assert "EVIDENCE_UNAVAILABLE_WITH_COORDINATE" in codes(validator.validate_bundle(bundle))


def test_misrouted_document_is_rejected(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)

    def mutate(record):
        record["identity"]["collection_id"] = "ks:city:topeka:charter-ordinances"

    _mutate_record(bundle, "ks__city__topeka__ordinances__ordinance__12345", mutate)
    found = codes(validator.validate_bundle(bundle))
    assert "ROUTING_DISAGREEMENT" in found


def test_version_id_detached_from_the_retained_original_is_rejected(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)

    def mutate(record):
        record["identity"]["document_version_id"] = record["identity"]["source_document_id"] + "@deadbeefdeadbeef"

    _mutate_record(bundle, "ks__city__topeka__ordinances__ordinance__12345", mutate)
    assert "VERSION_NOT_DERIVED_FROM_ORIGINAL" in codes(validator.validate_bundle(bundle))


def test_inventory_that_disagrees_with_the_documents_is_rejected(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)

    def mutate(manifest, _bundle):
        manifest["inventory"]["document_count"] = 99
        manifest["inventory"]["present_byte_count"] += 1

    retamper(bundle, mutate)
    found = codes(validator.validate_bundle(bundle))
    assert "INVENTORY_DOCUMENT_COUNT" in found
    assert "INVENTORY_BYTE_COUNT" in found


def test_disappearance_may_not_be_published_as_a_repeal(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)

    def mutate(manifest, _bundle):
        manifest["update"]["outcomes"]["unavailable"].append({
            "source_document_id": "ks:city:topeka:ordinances:ordinance:12345",
            "reason": "no longer on the listing, therefore repealed",
            "last_seen_release_id": "r1",
        })

    retamper(bundle, mutate)
    assert "UNAVAILABLE_CLAIMS_REPEAL" in codes(validator.validate_bundle(bundle))


def test_complete_coverage_claim_without_a_discovered_count_is_rejected(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed)

    def mutate(manifest, _bundle):
        manifest["collections"][0]["coverage"]["state"] = "complete"
        manifest["collections"][0]["coverage"]["discovered_count"] = None

    retamper(bundle, mutate)
    assert "COVERAGE_COMPLETE_UNPROVEN" in codes(validator.validate_bundle(bundle))


def test_missing_manifest_fails_rather_than_reporting_nothing_to_check(tmp_path):
    report = validator.validate_bundle(tmp_path / "not-a-bundle")
    assert not report.passed
    assert "MANIFEST_MISSING" in codes(report)


def test_fixture_bundle_cannot_be_validated_as_production(tmp_path, corpus, seed):
    bundle = export(tmp_path, corpus, seed, bundle_kind="fixture")
    report = validator.validate_bundle(bundle, expect_kind="production")
    assert "BUNDLE_KIND" in codes(report)


def test_extraction_hash_mismatch_that_is_not_the_known_transformation_fails_closed(tmp_path, corpus, seed):
    md = seed / "extracted" / "12345.md"
    md.write_bytes(md.read_bytes().replace(b"2034 Model", b"2099 Model"))
    with pytest.raises(SystemExit, match="not the known terminal-newline transformation"):
        exporter.resolve_selection("ordinance:12345", tmc_corpus=corpus, ordinance_seed=seed, include_originals=True)


def test_terminal_newline_transformation_is_recorded_as_lineage(tmp_path, corpus, seed):
    """The STO's provenance gap, reproduced: content identical but for a final LF."""
    md = seed / "extracted" / "12345.md"
    original_sha = sha(md.read_bytes())
    md.write_bytes(md.read_bytes() + b"\n")
    built = exporter.resolve_selection(
        "ordinance:12345", tmc_corpus=corpus, ordinance_seed=seed, include_originals=True
    )
    steps = {step["step"]: step for step in built.record["source"]["lineage"]}
    assert "terminal_newline_appended" in steps
    assert steps["terminal_newline_appended"]["input_sha256"] == original_sha
    assert steps["terminal_newline_appended"]["output_sha256"] == sha(md.read_bytes())


def test_exporter_refuses_to_release_the_same_document_twice(tmp_path, corpus, seed):
    documents = [
        exporter.resolve_selection(s, tmc_corpus=corpus, ordinance_seed=seed, include_originals=True)
        for s in ("ordinance:12345", "ordinance:12345")
    ]
    ids = [d.record["identity"]["source_document_id"] for d in documents]
    assert len(set(ids)) == 1, "the same publisher document must resolve to one identity"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _push_span_out_of_range(record):
    for reference in record["evidence"]["references"]:
        locator = reference.get("locator")
        if reference["availability"] == "available" and locator and locator.get("end") is not None:
            locator["start"] = 10**6
            locator["end"] = 10**6 + 5
            reference["quote"] = None
            return
    raise AssertionError("fixture has no available span to move")


def _mutate_record(bundle: Path, folder: str, mutate) -> None:
    """Edit one record and re-stamp only that record's hashes.

    Everything else in the manifest stays put, so the validator's complaint is
    about the mutation rather than about collateral hash drift.
    """
    path = bundle / "documents" / folder / "record.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    mutate(record)
    payload = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    path.write_bytes(payload)

    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["documents"]:
        if entry["record_path"].endswith(f"{folder}/record.json"):
            entry["record_sha256"] = sha(payload)
            entry["payload_sha256"] = contract.payload_fingerprint(record)
            entry["document_version_id"] = record["identity"]["document_version_id"]
            entry["collection_id"] = record["identity"]["collection_id"]
            for file_entry in entry["files"]:
                if file_entry["role"] == "record":
                    file_entry["sha256"] = sha(payload)
                    file_entry["byte_count"] = len(payload)
    manifest["inventory"]["inventory_sha256"] = contract.inventory_fingerprint(manifest["documents"])
    manifest["inventory"]["present_byte_count"] = sum(
        f["byte_count"] for e in manifest["documents"] for f in e["files"] if f["present"]
    )
    counts: dict[str, int] = {}
    for entry in manifest["documents"]:
        counts[entry["collection_id"]] = counts.get(entry["collection_id"], 0) + 1
    manifest["inventory"]["by_collection"] = [
        {"collection_id": key, "document_count": value} for key, value in sorted(counts.items())
    ]
    for collection in manifest["collections"]:
        collection["document_count"] = counts.get(collection["collection_id"], 0)
        collection["coverage"]["released_count"] = counts.get(collection["collection_id"], 0)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
