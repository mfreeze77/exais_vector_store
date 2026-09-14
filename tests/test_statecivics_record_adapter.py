"""WAVE-134 lane B: the entity/document record adapter, proved on fixtures.

No provider, no upstream DB, no API call, no ingestion. Every record here is a
committed fixture, and the parts of it that carry upstream shape were fetched
from StateCivics' OWN committed fixtures rather than invented -- all three at
``314beafe4f7905f06a2edb7828b0ea8b2976266c``, read with ``git show``:

* ``tests/unit/civic_impact/fixtures/ks650/legacy_document_records.json``
  -- the legacy document record, verbatim.
* ``tests/unit/civic_impact/fixtures/ks650/provision_reference_payload.json``
* ``tests/unit/civic_impact/fixtures/ks650/appropriation_action_payload.json``
  -- the two ``entity`` payloads, verbatim.

The entity ENVELOPES around those payloads reproduce
``src/kansas_accountability/services/civic_impact/entity_projection.py``'s
``build_entity_record`` at the same commit: its constants, its assignment order
and its ``record_digest`` rule, over the row values in that module's own unit
test. The two invalid records are the only hand-written ones, and each is
hand-written to fail exactly one branch.

The claims under test, in order of how expensive they are to get wrong:

1. The branch a record is judged against is READ OUT OF the contract's root
   ``if``/``then``/``else``, not hardcoded here or in the adapter.
2. A record is refused by the branch the dispatch sent it to, with a message
   that names that branch -- and the document branch is never relaxed to let an
   entity record through.
3. An entity record cannot reach the shared statute/document Qdrant collection.
   The statute collection name is derived from the INSTANCE CONFIG
   (``instance.yaml`` plus the statute store's ``source.yaml``); the entity
   collection is what the adapter RETURNS. Neither is written out here to match
   the other -- round one computed both with the same call and the same
   arguments, so it asserted ``X == X`` and could not fail.
   ``QdrantAdapter.collection_name`` does not take ``vector_store_id``, so a new
   vector store separates nothing and the embedding profile is the only
   separator.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from svs_common.qdrant_adapter import QdrantAdapter
from svs_common.statecivics_contract_pin import (
    BRANCH_ROOTS,
    ContractPinError,
    load_contract,
)
from svs_common.statecivics_record_adapter import (
    ANNOTATION_KEYWORDS,
    ASSERTED_FORMATS,
    CANDIDATE_ELIGIBILITY_STATUS,
    CANDIDATE_PATH,
    EXPECTED_DISPATCH_REQUIRED,
    FORMAT_CHECKER,
    KNOWN_KEYWORDS,
    LIVE_ELIGIBILITY_STATUSES,
    LIVE_PATH,
    CallerSuppliedCollectionRefused,
    CandidateRecordRefused,
    DispatchRule,
    DocumentCollectionRosterIncomplete,
    EntityCollectionCollision,
    EnvelopePayloadMismatch,
    InstanceCollectionConfigError,
    RecordBranchError,
    RemovalRecordNotStageable,
    UnknownEligibilityStatus,
    UnsupportedContractKeyword,
    adapt_manifest,
    adapt_records,
    admit_entity_records,
    assert_envelope_payload_agreement,
    branch_subtree,
    candidate_collection_name,
    classify_record,
    deployment_index_settings,
    dispatch_rule,
    eligibility_status,
    entity_collection_name,
    entity_path_for,
    read_instance_collection_roster,
    resolve_staging_collection,
    stage_entity_descriptors,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
CONTRACT = FIXTURES / "statecivics-retrieval-export-record.24c9d3de.json"
MIXED = FIXTURES / "statecivics-mixed-manifest.jsonl"
BAD_ENTITY = FIXTURES / "statecivics-invalid-entity-record.jsonl"
BAD_DOCUMENT = FIXTURES / "statecivics-invalid-document-record.jsonl"
#: The REAL candidate manifest the exporter wrote for HB 2513 Sec. 15(b), both
#: records, byte-identical to repo A's committed
#: `tests/fixtures/civic_impact/ks600-a2-1-entities-candidates.jsonl` at
#: 677d126d (A's origin/main) -- read with `git show`, never from A's working tree.
#:
#: This REPLACES a copy earlier lifted out of A's unit-test source with `ast`.
#: That copy carried `record_digest_sha256 0a6fd522...` and
#: `exporter.code_commit cda8d793...`, which disagreed with the values the
#: exporter actually emits. Both are gone from A's tree: the hand-written
#: fixture was stale, the exporter was always right, and A has since derived
#: every fixture from this manifest so there is nothing left to keep in sync.
#: An artifact beats a reconstruction, which is the whole reason B refused to
#: assemble the missing record itself.
REAL_MANIFEST = FIXTURES / "statecivics-ks600-a2-1-entities-candidates.677d126d.jsonl"
REAL_MANIFEST_SHA256 = "dd795e63359238697d57eca693307a04cebc0ec1888bae91113496d1878b61a8"
#: The two logical identities in that manifest, so edge targets can be crossed
#: against them by name rather than by repeating a hex string in each assertion.
PROVISION_LOGICAL_ID = "f4cf16d51a9339c186343ece353dbd07fe2feef9e319770359fb9378ceb18998"
ACTION_LOGICAL_ID = (
    "ks-approp-action:ks-2025-2026-hb2513:v7:enrolled:section-15:subsection-b:appropriate"
)
ADAPTER_SOURCE = ROOT / "packages" / "svs_common" / "svs_common" / "statecivics_record_adapter.py"

#: The REAL instance tree. Every document collection name in these tests is
#: derived from it, never written out by hand to match something.
REAL_INSTANCE = ROOT / "instances" / "ks-state-civics"
STATUTE_SOURCE = (
    REAL_INSTANCE
    / "vector-stores/kansas-statutes/sources/statecivics-statute-ledger/source.yaml"
)
#: The prefix the TARGET DEPLOYMENT uses. Not instance.yaml's collectionPrefix.
#: ``config.Settings`` defaults to it, ``generate-cell-env.py`` writes it, and
#: the running fiscal cell's Qdrant collections carry it. See WAVE-146.
RUNTIME_PREFIX = "svs_"
#: The two document collections the running fiscal cell actually holds.
STATUTE_COLLECTION = "svs_biz_ks_state_civics_voyage_4_docs_1024"
OPENAI_COLLECTION = "svs_biz_ks_state_civics_openai_text_embedding_3_small_1536"
#: The candidate entity profile from WAVE-134's store-id note. Still an owner
#: decision; nothing here adopts it.
ENTITY_PROFILE = "voyage_4_entities_1024"


@pytest.fixture(scope="module")
def schema() -> dict:
    return load_contract(CONTRACT)


@pytest.fixture(scope="module")
def raw_contract() -> dict:
    """The contract read WITHOUT going through the adapter's own helpers."""
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def manifest():
    return adapt_manifest(MIXED, contract_schema=CONTRACT)


#: The two collections a correctly-configured cell resolves for entity work.
LIVE_ENTITY_COLLECTION = "svs_biz_ks_state_civics_voyage_4_entities_1024"
CANDIDATE_COLLECTION = "svs_biz_ks_state_civics_voyage_4_candidates_1024"
CANDIDATE_PROFILE = "voyage_4_candidates_1024"
ENTITY_STORES = ("kansas-fiscal-entities", "kansas-fiscal-entity-candidates")


def _staging(tmp_path: Path) -> dict:
    """Everything `stage_entity_descriptors` needs to RESOLVE its own collection.

    There is no `collection=` here on purpose: the destination is the guards'
    to decide. Round five found the guards existed and this function did not
    call them, so a caller naming the shared document collection was embedded
    and indexed straight into it.
    """
    return {
        "adapter": _qdrant(),
        "instance_root": _staging_instance(tmp_path),
        "entity_embedding_profile_id": ENTITY_PROFILE,
        "candidate_embedding_profile_id": CANDIDATE_PROFILE,
        "entity_store_slugs": ENTITY_STORES,
    }


def _staging_instance(tmp_path: Path) -> Path:
    return _instance_tree(
        tmp_path,
        stores={
            "kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-documents": {"fiscal-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-entities": {"entity-ledger": ENTITY_PROFILE},
            "kansas-fiscal-entity-candidates": {"candidate-ledger": CANDIDATE_PROFILE},
        },
        preferred={"pdf_markdown_external_v1": "openai_text_embedding_3_small_1536"},
    )


def _qdrant(prefix: str = RUNTIME_PREFIX) -> QdrantAdapter:
    """A QdrantAdapter with settings only -- no client, no network.

    ``__new__`` is how tests/test_index_versioning.py already builds one; the
    constructor would try to reach a Qdrant.
    """
    adapter = QdrantAdapter.__new__(QdrantAdapter)
    adapter.settings = SimpleNamespace(qdrant_collection_prefix=prefix, svs_index_version="")
    return adapter


# --------------------------------------------------------------------------
# 1. The dispatch comes from the contract
# --------------------------------------------------------------------------


def test_the_rule_is_read_out_of_the_contracts_own_root_dispatch(raw_contract) -> None:
    """Nothing below names ``record_kind``; the contract does."""
    rule = dispatch_rule(raw_contract)
    assert rule.tag_keys == tuple(raw_contract["if"]["required"])
    assert rule.present_ref == raw_contract["then"]["$ref"].removeprefix("#/$defs/")
    assert rule.absent_ref == raw_contract["else"]["$ref"].removeprefix("#/$defs/")
    # And each arm resolves to a PINNED branch, through the pin module's own map.
    assert BRANCH_ROOTS[rule.present_pin] == rule.present_ref
    assert BRANCH_ROOTS[rule.absent_pin] == rule.absent_ref
    assert {rule.present_pin, rule.absent_pin} == {"entity", "document"}


def test_the_hardcoded_cross_check_matches_the_contract(raw_contract) -> None:
    """The module constant is a tripwire, and it must agree with the contract.

    If StateCivics re-roots the dispatch, this fails HERE -- naming the key --
    rather than only as an opaque DISPATCH_SHA256 mismatch.
    """
    assert EXPECTED_DISPATCH_REQUIRED == tuple(raw_contract["if"]["required"])


def test_a_contract_that_routes_on_another_key_is_refused(schema) -> None:
    widened = copy.deepcopy(schema)
    widened["if"]["required"] = ["record_kind", "record_version"]
    with pytest.raises(ContractPinError, match="dispatches on"):
        dispatch_rule(widened)


def test_a_contract_whose_arm_is_not_a_pinned_branch_is_refused(schema) -> None:
    moved = copy.deepcopy(schema)
    moved["$defs"]["some_other_record"] = {"type": "object"}
    moved["then"] = {"$ref": "#/$defs/some_other_record"}
    with pytest.raises(ContractPinError, match="not a pinned branch root"):
        dispatch_rule(moved)


def test_a_contract_that_lost_its_else_is_refused(schema) -> None:
    stripped = copy.deepcopy(schema)
    del stripped["else"]
    with pytest.raises(ContractPinError, match="missing top-level routing keys"):
        dispatch_rule(stripped)


class _RecordingMapping(Mapping):
    """Remembers every key anyone read. Mirrors StateCivics' own gate proof."""

    def __init__(self, data: dict) -> None:
        self._data = data
        self.accessed: set[str] = set()

    def __getitem__(self, key):
        self.accessed.add(key)
        return self._data[key]

    def get(self, key, default=None):
        self.accessed.add(key)
        return self._data.get(key, default)

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def test_classification_reads_only_the_tag_keys(schema) -> None:
    rule = dispatch_rule(schema)
    entity, document = _jsonl(MIXED)[1], _jsonl(MIXED)[0]
    for record, expected in ((entity, rule.present_pin), (document, rule.absent_pin)):
        watched = _RecordingMapping(record)
        assert classify_record(watched, rule) == expected
        assert watched.accessed <= set(rule.tag_keys), (
            f"dispatch read {sorted(watched.accessed - set(rule.tag_keys))} before deciding"
        )


# --------------------------------------------------------------------------
# 2. Branch-correct validation, and refusal by name
# --------------------------------------------------------------------------


def test_the_mixed_manifest_separates_into_two_branches(manifest) -> None:
    assert len(manifest.document_records) == 1
    assert len(manifest.entity_records) == 2
    assert [r["entity_type"] for r in manifest.entity_records] == [
        "provision_reference",
        "appropriation_action",
    ]
    # The edges WAVE-134 names are present on the action record.
    edges = {e["relationship_type"] for e in manifest.entity_records[1]["relationships"]}
    assert edges == {"action_relies_on_provision", "action_enacted_by_bill_version"}
    assert all(e["basis"] == "exact_shared_identifier"
               for e in manifest.entity_records[1]["relationships"])


def test_only_the_pins_for_branches_actually_read_are_verified(manifest, schema) -> None:
    assert set(manifest.verified_pins) == {"dispatch", "document", "entity"}
    # A document-only manifest must not be blocked by entity-branch drift.
    only_document = adapt_records([(1, _jsonl(MIXED)[0])], schema)
    assert set(only_document.verified_pins) == {"dispatch", "document"}
    assert only_document.entity_records == ()
    only_entity = adapt_records([(1, _jsonl(MIXED)[1])], schema)
    assert set(only_entity.verified_pins) == {"dispatch", "entity"}
    assert only_entity.document_records == ()


def test_entity_branch_drift_blocks_an_entity_record_but_not_a_document_one(schema) -> None:
    drifted = copy.deepcopy(schema)
    drifted["$defs"]["compact_description"]["properties"]["text"]["maxLength"] = 601
    assert adapt_records([(1, _jsonl(MIXED)[0])], drifted).document_records
    with pytest.raises(ContractPinError, match="contract entity digest mismatch"):
        adapt_records([(1, _jsonl(MIXED)[1])], drifted)


def test_an_invalid_entity_record_is_refused_against_the_entity_branch() -> None:
    with pytest.raises(RecordBranchError) as excinfo:
        adapt_manifest(BAD_ENTITY, contract_schema=CONTRACT)
    message = str(excinfo.value)
    assert "routed to the entity branch ($defs.entity_projection_envelope)" in message
    assert "by the contract's dispatch on ['record_kind']" in message
    assert "'entity_type' is a required property" in message
    # The fixture carries the DOCUMENT branch's identity field. The entity
    # branch forbids it, and that is reported rather than tolerated.
    assert "Additional properties are not allowed ('logical_document_id' was unexpected)" in message
    assert "is not relaxed to admit a record from the other branch" in message


def test_an_invalid_document_record_is_refused_against_the_document_branch() -> None:
    with pytest.raises(RecordBranchError) as excinfo:
        adapt_manifest(BAD_DOCUMENT, contract_schema=CONTRACT)
    message = str(excinfo.value)
    assert "routed to the document branch ($defs.legacy_document_record)" in message
    assert "by the contract's dispatch on ['record_kind']" in message
    assert "'logical_document_id' is a required property" in message
    assert "is not relaxed to admit a record from the other branch" in message


def test_the_document_branch_is_not_widened_to_accept_an_entity_record(schema) -> None:
    """The relaxation this adapter exists to avoid, asserted directly."""
    rule = dispatch_rule(schema)
    provision, action = _jsonl(MIXED)[1], _jsonl(MIXED)[2]
    for record in (provision, action):
        against_document = validate(record, schema, rule.absent_ref)
        assert not against_document.ok
        assert any("logical_document_id" in error for error in against_document.errors)
        assert any("record_kind" in error for error in against_document.errors)
        # ...while it is valid against the branch the dispatch actually chose.
        assert validate(record, schema, rule.present_ref).ok


def test_a_document_record_is_not_valid_on_the_entity_branch_either(schema) -> None:
    rule = dispatch_rule(schema)
    document = _jsonl(MIXED)[0]
    assert validate(document, schema, rule.absent_ref).ok
    assert not validate(document, schema, rule.present_ref).ok


def test_a_half_tagged_record_matches_neither_arm(schema) -> None:
    """Presence routing over more than one key has a third, unroutable state.

    Today's contract routes on one key, so this state is unreachable from it.
    The rule is built here with two keys deliberately: if StateCivics ever adds
    a second required tag, the code that must already handle the half-tagged
    record is proved to, rather than assigning it to a branch by accident.
    """
    live = dispatch_rule(schema)
    assert len(live.tag_keys) == 1, "the live contract's tag-key count changed; re-read this test"
    two_key = DispatchRule(
        tag_keys=("record_kind", "record_version"),
        present_pin=live.present_pin,
        absent_pin=live.absent_pin,
        present_ref=live.present_ref,
        absent_ref=live.absent_ref,
    )
    assert classify_record({"record_kind": "entity_projection", "record_version": 1}, two_key) == (
        live.present_pin
    )
    assert classify_record({"logical_document_id": "a" * 64}, two_key) == live.absent_pin
    with pytest.raises(RecordBranchError, match="matches neither"):
        classify_record({"record_kind": "entity_projection"}, two_key)


# --------------------------------------------------------------------------
# The evaluator refuses what it cannot check
# --------------------------------------------------------------------------


def test_a_draft_keyword_is_now_checked_rather_than_refused(schema) -> None:
    """``dependentRequired`` was refused by the old evaluator. It is now CHECKED.

    That is the migration's point: the library implements the vocabulary, so a
    keyword the hand-written evaluator had to refuse is simply enforced.
    """
    extended = copy.deepcopy(schema)
    extended["$defs"]["as_of_snapshot"]["dependentRequired"] = {"declared": ["nonexistent_key"]}
    result = validate(_jsonl(MIXED)[1], extended, "entity_projection_envelope")
    assert not result.ok
    assert any("nonexistent_key" in error for error in result.errors)


def test_a_keyword_outside_the_draft_vocabulary_is_refused(schema) -> None:
    """jsonschema IGNORES an unrecognised keyword. A consumer must not.

    A typo, or a keyword from a later draft, becomes a constraint nobody checks
    and nobody is told about. The vocabulary is guarded against the library's
    OWN validator table, not a hand-written list.
    """
    typo = copy.deepcopy(schema)
    typo["$defs"]["as_of_snapshot"]["dependentRequried"] = {"declared": ["snapshot_id"]}
    with pytest.raises(UnsupportedContractKeyword, match="dependentRequried"):
        validate(_jsonl(MIXED)[1], typo, "entity_projection_envelope")
    # ...and the library really would have ignored it, which is why this exists.
    import jsonschema

    assert "dependentRequried" not in jsonschema.Draft202012Validator.VALIDATORS


def test_a_boolean_never_satisfies_a_numeric_const(schema) -> None:
    """The round-one fail-open, at the gate the contract calls sufficient.

    ``True == 1`` in Python, so ``record_version: true`` satisfied ``const: 1``
    and was ADMITTED as a valid entity projection. Driven through the real
    ``adapt_records``, not through ``validate`` alone, because the claim is that
    the dispatch path admits it -- and that is what QC reproduced.
    """
    record = copy.deepcopy(_jsonl(MIXED)[1])
    record["record_version"] = True
    with pytest.raises(RecordBranchError, match="record_version: 1 was expected"):
        adapt_records([(1, record)], schema)


def test_enum_equality_is_typed_like_const() -> None:
    """``enum`` shares ``const``'s equality, so it shares the same trap.

    Every enum in the pinned contract sits on a ``type``-constrained string, so
    a boolean is caught by ``type`` before ``enum`` is reached. That makes the
    real contract safe TODAY and says nothing about the keyword, so the keyword
    is exercised directly -- which is the distinction round one missed.
    """
    schema = {"$defs": {"probe": {"enum": [1, "yes"]}}}
    assert validate(1, schema, "probe").ok
    assert validate(1.0, schema, "probe").ok, "1.0 and 1 are the same number"
    assert not validate(True, schema, "probe").ok, "true is not the number 1"
    assert not validate(0, schema, "probe").ok

    const = {"$defs": {"probe": {"const": 0}}}
    assert not validate(False, const, "probe").ok, "false is not the number 0"
    assert validate(0.0, const, "probe").ok


@pytest.mark.parametrize(
    "bad_date",
    ["2026-02-31", "2026-13-99", "0000-99-99", "2026-04-31", "20260701", "2026-W27-1"],
)
def test_a_calendar_invalid_date_is_refused(schema, bad_date) -> None:
    """A shape regex accepted every one of these on both branches."""
    record = copy.deepcopy(_jsonl(MIXED)[1])
    record["as_of"]["as_of_date"] = bad_date
    with pytest.raises(RecordBranchError, match="is not a 'date'"):
        adapt_records([(1, record)], schema)


@pytest.mark.parametrize(
    "bad_date_time",
    [
        "2026-02-31T00:00:00Z",  # calendar-invalid day
        "2026-09-04T25:00:00Z",  # impossible hour
        "2026-09-04T12:00:00",  # no offset: a local time is not an instant
        "2026-09-04 12:00:00Z",  # no date/time separator
        "yesterday",
    ],
)
def test_a_calendar_invalid_or_offsetless_date_time_is_refused(schema, bad_date_time) -> None:
    record = copy.deepcopy(_jsonl(MIXED)[1])
    record["exporter"]["exported_at"] = bad_date_time
    with pytest.raises(RecordBranchError, match="is not a 'date-time'"):
        adapt_records([(1, record)], schema)


@pytest.mark.parametrize("good_date_time", ["2026-09-04T12:00:00Z", "2026-09-04t12:00:00.5+02:00"])
def test_a_real_rfc3339_date_time_is_accepted(schema, good_date_time) -> None:
    """The refusals above must not be a validator that rejects everything."""
    record = copy.deepcopy(_jsonl(MIXED)[1])
    record["exporter"]["exported_at"] = good_date_time
    assert adapt_records([(1, record)], schema).entity_records


def test_unique_items_distinguishes_true_from_one_and_conflates_one_with_one_point_zero() -> None:
    """``uniqueItems`` uses the same typed equality as ``const``."""
    schema = {
        "$defs": {"probe": {"type": "object", "properties": {"xs": {"type": "array", "uniqueItems": True}}}}
    }
    assert validate({"xs": [True, 1]}, schema, "probe").ok, "true and 1 are different types"
    assert not validate({"xs": [1, 1.0]}, schema, "probe").ok, "1 and 1.0 are the same number"
    assert not validate({"xs": [True, True]}, schema, "probe").ok


def test_an_integer_valued_float_is_an_integer() -> None:
    """Draft 2020-12: ``integer`` matches any number with no fractional part."""
    schema = {"$defs": {"probe": {"type": "integer"}}}
    assert validate(48211.0, schema, "probe").ok
    assert not validate(48211.5, schema, "probe").ok
    assert not validate(True, schema, "probe").ok


def test_the_vocabulary_guard_comes_from_the_library_not_a_hand_list() -> None:
    """Round one and two both hand-maintained this. It is now derived."""
    import jsonschema

    asserting = set(jsonschema.Draft202012Validator.VALIDATORS)
    # Everything the library asserts is known, with no exceptions written here.
    assert asserting <= KNOWN_KEYWORDS
    # `if` applies `then`/`else`, so they have no validator entry of their own.
    assert {"then", "else"} <= KNOWN_KEYWORDS
    assert {"then", "else"}.isdisjoint(asserting)
    assert asserting.isdisjoint(ANNOTATION_KEYWORDS)
    # The keywords round one claimed while approximating are now the library's.
    assert {"const", "enum", "uniqueItems", "format", "pattern", "type"} <= asserting


def test_format_actually_asserts_because_a_checker_is_passed() -> None:
    """Draft 2020-12 makes ``format`` an ANNOTATION unless a checker is given.

    Without ``FormatChecker``, ``2026-02-31`` is a valid ``date``. This asserts
    the checker is wired AND that the two formats this contract depends on are
    among the ones it actually asserts -- read from the registry, not assumed.
    """
    import jsonschema

    assert isinstance(FORMAT_CHECKER, jsonschema.FormatChecker)
    assert {"date", "date-time", "uri"} <= ASSERTED_FORMATS
    # rfc3339-validator makes date-time assert; the format-nongpl extra's
    # rfc3986-validator/rfc3987-syntax make uri assert. Neither is GPL.
    assert "date-time" in FORMAT_CHECKER.checkers
    assert "uri" in FORMAT_CHECKER.checkers


def test_every_keyword_the_contract_uses_is_classified(schema, raw_contract) -> None:
    """Nothing either branch of the pinned contract uses is unclassified.

    The walk is the module's OWN ``branch_subtree``, so this proves the thing
    the validator actually inspects -- not a second traversal written here that
    could disagree with it.
    """
    rule = dispatch_rule(schema)
    seen: set[str] = set()
    for root in (rule.present_ref, rule.absent_ref):
        for node in branch_subtree(schema, root):
            seen.update(node)
    seen.update(raw_contract)  # the document root itself
    assert seen, "the walk found no keywords, so this test proves nothing"
    assert seen <= KNOWN_KEYWORDS, f"unclassified: {sorted(seen - KNOWN_KEYWORDS)}"


#: The round-two cross-check battery, RETAINED in the repository rather than
#: left in a scratch venv. Its job then was to compare two implementations;
#: its job now is to keep the semantic boundaries covered by something that
#: runs in CI, so a future change to how records are validated cannot quietly
#: move one. Organised by BOUNDARY, never by keyword name -- covering a keyword
#: by name is exactly what let round one ship five fail-open divergences.
_SEMANTIC_BOUNDARIES = [
    # (boundary, subschema, value, valid)
    ("bool-vs-number", {"const": 1}, True, False),
    ("bool-vs-number", {"const": 1}, 1, True),
    ("bool-vs-number", {"const": 1}, 1.0, True),
    ("bool-vs-number", {"const": 0}, False, False),
    ("bool-vs-number", {"const": True}, 1, False),
    ("bool-vs-number", {"enum": [1, "yes"]}, True, False),
    ("bool-vs-number", {"enum": [True]}, 1, False),
    ("bool-vs-number", {"type": "integer"}, True, False),
    ("bool-vs-number", {"type": "number"}, True, False),
    ("bool-vs-number", {"type": "boolean"}, 1, False),
    ("bool-vs-number", {"type": "array", "uniqueItems": True}, [True, 1], True),
    ("bool-vs-number", {"type": "array", "uniqueItems": True}, [False, 0], True),
    ("bool-vs-number", {"type": "array", "uniqueItems": True}, [True, True], False),
    ("int-vs-float", {"type": "integer"}, 48211.0, True),
    ("int-vs-float", {"type": "integer"}, 48211.5, False),
    ("int-vs-float", {"type": "integer"}, 48211, True),
    ("int-vs-float", {"const": 1.0}, 1, True),
    ("int-vs-float", {"enum": [1]}, 1.0, True),
    ("int-vs-float", {"type": "number", "minimum": 1}, 0.5, False),
    ("int-vs-float", {"type": "array", "uniqueItems": True}, [1, 1.0], False),
    ("int-vs-float", {"type": "array", "uniqueItems": True}, [[1], [1.0]], False),
    ("int-vs-float", {"type": "array", "uniqueItems": True}, [{"a": 1}, {"a": True}], True),
    ("date-calendar", {"type": "string", "format": "date"}, "2026-02-31", False),
    ("date-calendar", {"type": "string", "format": "date"}, "2026-13-99", False),
    ("date-calendar", {"type": "string", "format": "date"}, "0000-99-99", False),
    ("date-calendar", {"type": "string", "format": "date"}, "2026-04-31", False),
    ("date-calendar", {"type": "string", "format": "date"}, "2025-02-29", False),
    ("date-calendar", {"type": "string", "format": "date"}, "20260701", False),
    ("date-calendar", {"type": "string", "format": "date"}, "2024-02-29", True),
    ("date-calendar", {"type": "string", "format": "date"}, "2026-07-01", True),
    ("datetime-calendar", {"type": "string", "format": "date-time"}, "2026-02-31T00:00:00Z", False),
    ("datetime-calendar", {"type": "string", "format": "date-time"}, "2026-09-04T25:00:00Z", False),
    ("datetime-calendar", {"type": "string", "format": "date-time"}, "2026-09-04T12:00:00", False),
    ("datetime-calendar", {"type": "string", "format": "date-time"}, "2026-09-04 12:00:00Z", False),
    ("datetime-calendar", {"type": "string", "format": "date-time"}, "yesterday", False),
    ("datetime-calendar", {"type": "string", "format": "date-time"}, "2026-09-04T12:00:00Z", True),
    ("datetime-calendar", {"type": "string", "format": "date-time"}, "2026-09-04T12:00:00-06:00", True),
    ("uniqueitems-nested", {"type": "array", "uniqueItems": True},
     [{"a": 1, "b": 2}, {"b": 2, "a": 1}], False),
    ("uniqueitems-nested", {"type": "array", "uniqueItems": True}, [None, None], False),
    ("uniqueitems-nested", {"type": "array", "uniqueItems": True}, ["1", 1], True),
    ("uniqueitems-nested", {"type": "array", "uniqueItems": True}, [[], {}], True),
]


@pytest.mark.parametrize(
    ("boundary", "subschema", "value", "valid"),
    _SEMANTIC_BOUNDARIES,
    ids=[f"{b}-{i}" for i, (b, *_rest) in enumerate(_SEMANTIC_BOUNDARIES)],
)
def test_semantic_boundaries(boundary, subschema, value, valid) -> None:
    result = validate(value, {"$defs": {"probe": subschema}}, "probe")
    assert result.ok is valid, f"[{boundary}] {value!r} against {subschema}: {result.errors}"


def test_every_semantic_boundary_carries_near_misses_and_controls() -> None:
    """A battery of only-refusals proves nothing; so does one of only-passes."""
    from collections import Counter

    per_boundary = Counter(b for b, *_ in _SEMANTIC_BOUNDARIES)
    valid = Counter(b for b, _s, _v, ok in _SEMANTIC_BOUNDARIES if ok)
    for boundary, total in per_boundary.items():
        assert total >= 3, f"{boundary} has only {total} cases"
        assert 0 < valid[boundary] < total, f"{boundary} is all-pass or all-refuse"


def test_the_gate_boundary_is_reachable_through_the_real_dispatch(schema) -> None:
    """The bool-vs-number boundary, on the contract, through adapt_records.

    A probe schema proves the keyword. This proves the PATH: the same defect
    that QC found, driven the way a manifest is actually read.
    """
    record = copy.deepcopy(_jsonl(MIXED)[1])
    record["record_version"] = True
    with pytest.raises(RecordBranchError, match="record_version: 1 was expected"):
        adapt_records([(1, record)], schema)


def test_the_disclosure_channel_survived_the_migration(manifest, schema) -> None:
    """WAVE-145 predicted this tuple would SURVIVE. It did -- but SMALLER.

    ``pattern`` survives: ``jsonschema`` uses Python ``re``, not ECMA-262, so
    the divergence is a property of the library and cannot be cross-checked
    against it.

    ``format:uri`` does NOT survive, and the round-three note claiming it needed
    the GPLv3 ``rfc3987`` was WRONG. The ``format-nongpl`` extra pulls
    ``rfc3986-validator`` and ``rfc3987-syntax``, both non-GPL; only the plain
    ``format`` extra pulls ``rfc3987``. With the extra pinned, ``uri`` asserts
    and drops out of the disclosure set on its own -- the set is derived from
    the checker registry, so no code changed, only this expectation.
    """
    rule = dispatch_rule(schema)
    document, provision = _jsonl(MIXED)[0], _jsonl(MIXED)[1]
    # The entity branch declares no uri-formatted field; the document one does.
    assert validate(provision, schema, rule.present_ref).unsupported_keyword_semantics == (
        "pattern",
    )
    assert validate(document, schema, rule.absent_ref).unsupported_keyword_semantics == (
        "pattern",
    )
    assert manifest.unsupported_keyword_semantics == ("pattern",)
    # Derived, not listed: every disclosed format is one the checker lacks.
    for token in manifest.unsupported_keyword_semantics:
        if token.startswith("format:"):
            assert token.removeprefix("format:") not in ASSERTED_FORMATS


def test_unfollowed_remote_refs_are_reported_not_hidden(manifest) -> None:
    """A remote $ref names a separate contract with its own pin.

    ``branch_closure`` does not follow one either. What matters is that the
    adapter SAYS what it did not check, so "the KS-600 entity payload was not
    validated here" is a value, not an omission.
    """
    assert manifest.unvalidated_remote_refs == (
        "https://statecivics.ai/contracts/civic-impact/appropriation-action.schema.json",
        "https://statecivics.ai/contracts/civic-impact/provision-reference.schema.json",
        "https://statecivics.ai/contracts/civic-impact/source-artifact.schema.json#/properties/artifact_type",
    )


# --------------------------------------------------------------------------
# 3. Entity records cannot reach the shared statute collection
# --------------------------------------------------------------------------


def test_the_statute_collection_is_resolved_for_the_target_deployment() -> None:
    """The name under protection is the one the RUNNING cell uses.

    Round two derived it from ``instance.yaml``'s ``collectionPrefix``
    (``ks_civics_``) and produced ``ks_civics_biz_ks_state_civics_...``, which
    the deployment does not have. Nothing in this repository reads that YAML
    key; the prefix a cell uses is ``QDRANT_COLLECTION_PREFIX``, defaulted to
    ``svs_`` by ``config.Settings`` and by ``generate-cell-env.py``, and the
    running fiscal cell's Qdrant holds ``svs_``-prefixed collections. WAVE-146
    owns the disagreement.
    """
    instance = yaml.safe_load((REAL_INSTANCE / "instance.yaml").read_text(encoding="utf-8"))
    package = yaml.safe_load(STATUTE_SOURCE.read_text(encoding="utf-8"))
    assert instance["metadata"]["businessInstanceId"] == "biz_ks_state_civics"
    assert package["ingestion"]["embeddingProfile"] == "voyage_4_docs_1024"
    # The YAML's prefix is NOT what the deployment uses, and is not consulted.
    assert instance["storage"]["qdrant"]["collectionPrefix"] == "ks_civics_"

    settings = deployment_index_settings(REAL_INSTANCE, _qdrant(RUNTIME_PREFIX))
    assert settings.collection_prefix == RUNTIME_PREFIX == "svs_"
    assert settings.business_instance_id == "biz_ks_state_civics"
    qdrant = _qdrant(RUNTIME_PREFIX)
    assert (
        qdrant.collection_name(settings.business_instance_id, "voyage_4_docs_1024")
        == STATUTE_COLLECTION
    )


def test_the_settings_default_prefix_is_the_runtime_prefix() -> None:
    """Corroboration from a second, independent place in the tree."""
    from svs_common.config import Settings

    assert Settings.model_fields["qdrant_collection_prefix"].default == RUNTIME_PREFIX


def test_the_roster_covers_both_document_collections_the_cell_holds() -> None:
    """A source-package-only roster finds ONE of the two runtime collections.

    The running fiscal cell's Qdrant holds two document collections. Only the
    Voyage one is named by a source package; the OpenAI one is declared in
    ``instance.yaml`` under ``models.preferredEmbeddingProfiles``. A roster that
    reads only source packages would never enumerate it, let alone guard against
    it, so both places are read.
    """
    roster = read_instance_collection_roster(REAL_INSTANCE, _qdrant(RUNTIME_PREFIX))
    assert roster.preferred_profiles == ("openai_text_embedding_3_small_1536",)
    assert set(roster.document_collections.values()) == {
        STATUTE_COLLECTION,
        OPENAI_COLLECTION,
    }
    assert roster.document_collections["kansas-statutes:voyage_4_docs_1024"] == STATUTE_COLLECTION
    # Per SOURCE, never per store: four source packages declare no profile.
    assert roster.undeclared_profile_sources == (
        "kansas-court-decisions/kscourts-decisions",
        "kansas-fiscal-documents/statecivics-fiscal-ledger",
        "topeka-municipal-code/topeka-codified-code",
        "topeka-municipal-code/topeka-ordinances",
    )
    assert roster.undeclared_profile_stores == (
        "kansas-court-decisions",
        "kansas-fiscal-documents",
        "topeka-municipal-code",
    )


def _instance_tree(
    tmp_path: Path,
    *,
    stores: dict[str, dict[str, str | None]],
    preferred: dict[str, str] | None = None,
) -> Path:
    """Build an instance tree. ``stores`` maps slug -> {source slug: profile|None}.

    Same keys and nesting as the real one, so the reader under test meets the
    layout it will actually meet.
    """
    root = tmp_path / "ks-state-civics"
    root.mkdir()
    instance: dict = {
        "metadata": {"businessInstanceId": "biz_ks_state_civics"},
        "storage": {"qdrant": {"collectionPrefix": "ks_civics_"}},  # deliberately stale
    }
    if preferred:
        instance["models"] = {"preferredEmbeddingProfiles": preferred}
    (root / "instance.yaml").write_text(yaml.safe_dump(instance), encoding="utf-8")
    for slug, sources in stores.items():
        for source_slug, profile in sources.items():
            source = root / "vector-stores" / slug / "sources" / source_slug
            source.mkdir(parents=True)
            body: dict = {} if profile is None else {"ingestion": {"embeddingProfile": profile}}
            (source / "source.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    return root


def _complete_instance(tmp_path: Path) -> Path:
    return _instance_tree(
        tmp_path,
        stores={
            "kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-documents": {"fiscal-ledger": "voyage_4_docs_1024"},
        },
    )


def test_an_undeclared_source_is_not_masked_by_a_declaring_sibling(tmp_path) -> None:
    """Missing-source detection is per SOURCE, never per store.

    Round two collected profiles across a store's sources and treated the store
    as declared if ANY source named one, so a second source with no profile
    vanished. ``topeka-municipal-code`` really does carry two source packages,
    which is the arrangement that makes this reachable.
    """
    root = _instance_tree(
        tmp_path,
        stores={
            "kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"},
            "topeka-municipal-code": {
                "topeka-codified-code": "voyage_4_docs_1024",
                "topeka-ordinances": None,
            },
        },
    )
    roster = read_instance_collection_roster(root, _qdrant())
    assert roster.undeclared_profile_sources == ("topeka-municipal-code/topeka-ordinances",)
    with pytest.raises(DocumentCollectionRosterIncomplete, match="topeka-ordinances"):
        entity_collection_name(
            _qdrant(), instance_root=root, entity_embedding_profile_id=ENTITY_PROFILE
        )


def test_a_store_with_no_source_package_at_all_is_reported(tmp_path) -> None:
    root = _instance_tree(
        tmp_path,
        stores={"kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"}},
    )
    (root / "vector-stores" / "mystery-store").mkdir(parents=True)
    roster = read_instance_collection_roster(root, _qdrant())
    assert roster.undeclared_profile_sources == ("mystery-store/<no source package>",)


def test_an_entity_store_is_not_a_document_store(tmp_path) -> None:
    """The guard must never fire against the entity store itself.

    An entity store declared in the tree with its own profile is excluded from
    the document side entirely -- neither a collection to avoid, nor an
    undeclared document source when it declares nothing.
    """
    root = _instance_tree(
        tmp_path,
        stores={
            "kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-documents": {"fiscal-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-entities": {"entity-ledger": ENTITY_PROFILE},
        },
    )
    qdrant = _qdrant()
    # Without the classification, the entity store is a document store and the
    # guard refuses the ONLY arrangement that is actually correct.
    with pytest.raises(EntityCollectionCollision, match="kansas-fiscal-entities"):
        entity_collection_name(
            qdrant, instance_root=root, entity_embedding_profile_id=ENTITY_PROFILE
        )
    # With it, the entity store is excluded and the collection resolves.
    roster = read_instance_collection_roster(
        root, qdrant, entity_store_slugs=("kansas-fiscal-entities",)
    )
    assert roster.entity_store_slugs == ("kansas-fiscal-entities",)
    assert not any("kansas-fiscal-entities" in key for key in roster.document_collections)
    assert roster.undeclared_profile_sources == ()
    resolved = entity_collection_name(
        qdrant,
        instance_root=root,
        entity_embedding_profile_id=ENTITY_PROFILE,
        entity_store_slugs=("kansas-fiscal-entities",),
    )
    assert resolved == f"{RUNTIME_PREFIX}biz_ks_state_civics_voyage_4_entities_1024"
    assert resolved not in set(roster.document_collections.values())


def test_an_undeclared_entity_store_is_not_counted_as_a_document_gap(tmp_path) -> None:
    """Classification excludes the store from BOTH sides, not just one."""
    root = _instance_tree(
        tmp_path,
        stores={
            "kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-entities": {"entity-ledger": None},
        },
    )
    roster = read_instance_collection_roster(
        root, _qdrant(), entity_store_slugs=("kansas-fiscal-entities",)
    )
    assert roster.undeclared_profile_sources == ()


def test_the_collision_fires_against_any_resolved_document_collection(tmp_path) -> None:
    """The guard no longer depends on which profile the caller names.

    Quality control's round-two probe: passing a document profile that is not
    the statute profile returned the real shared statute collection with no
    collision raised. There is no document profile argument to pass any more,
    so the probe is unexpressible; what remains is that the RESOLVED collections
    collide.
    """
    root = _complete_instance(tmp_path)
    qdrant = _qdrant()
    roster = read_instance_collection_roster(root, qdrant)
    assert roster.undeclared_profile_sources == ()
    assert set(roster.document_collections.values()) == {STATUTE_COLLECTION}

    with pytest.raises(EntityCollectionCollision) as excinfo:
        entity_collection_name(
            qdrant, instance_root=root, entity_embedding_profile_id="voyage_4_docs_1024"
        )
    message = str(excinfo.value)
    assert STATUTE_COLLECTION in message
    assert "kansas-statutes:voyage_4_docs_1024" in message
    assert "kansas-fiscal-documents:voyage_4_docs_1024" in message
    assert "vector_store_id" in message


def test_the_collision_fires_against_the_preferred_profile_collection(tmp_path) -> None:
    """The second runtime collection is guarded too, not just the Voyage one."""
    root = _instance_tree(
        tmp_path,
        stores={"kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"}},
        preferred={"pdf_markdown_external_v1": "openai_text_embedding_3_small_1536"},
    )
    with pytest.raises(EntityCollectionCollision) as excinfo:
        entity_collection_name(
            _qdrant(),
            instance_root=root,
            entity_embedding_profile_id="openai_text_embedding_3_small_1536",
        )
    assert OPENAI_COLLECTION in str(excinfo.value)
    assert "models.preferredEmbeddingProfiles" in str(excinfo.value)


@pytest.mark.parametrize("profile", [None, "", "   ", 0])
def test_an_empty_entity_profile_is_refused_not_resolved(tmp_path, profile) -> None:
    """``None`` used to resolve to the degenerate ``svs_biz_ks_state_civics_``."""
    with pytest.raises(InstanceCollectionConfigError, match="non-empty profile id"):
        entity_collection_name(
            _qdrant(),
            instance_root=_complete_instance(tmp_path),
            entity_embedding_profile_id=profile,
        )


def test_a_deployment_with_no_prefix_setting_is_refused(tmp_path) -> None:
    """Fail toward blocking when the deployment cannot be named at all."""
    adapter = QdrantAdapter.__new__(QdrantAdapter)
    adapter.settings = SimpleNamespace(qdrant_collection_prefix="", svs_index_version="")
    with pytest.raises(InstanceCollectionConfigError, match="qdrant_collection_prefix"):
        deployment_index_settings(_complete_instance(tmp_path), adapter)


def test_entity_records_never_reach_the_shared_statute_collection(manifest, tmp_path) -> None:
    """Route the adapter's real output and assert on where each group lands.

    The document collections are the ones the TARGET DEPLOYMENT resolves; the
    entity collection is what the adapter RETURNS. Neither is a string built
    here to match the other.
    """
    root = _instance_tree(
        tmp_path,
        stores={
            "kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-documents": {"fiscal-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-entities": {"entity-ledger": ENTITY_PROFILE},
        },
        preferred={"pdf_markdown_external_v1": "openai_text_embedding_3_small_1536"},
    )
    qdrant = _qdrant()
    entity_stores = ("kansas-fiscal-entities",)
    roster = read_instance_collection_roster(root, qdrant, entity_store_slugs=entity_stores)
    statute_collection = roster.document_collections["kansas-statutes:voyage_4_docs_1024"]
    assert statute_collection == STATUTE_COLLECTION
    assert OPENAI_COLLECTION in set(roster.document_collections.values())

    entity_collection = entity_collection_name(
        qdrant,
        instance_root=root,
        entity_embedding_profile_id=ENTITY_PROFILE,
        entity_store_slugs=entity_stores,
    )

    routed: dict[str, list[dict]] = {}
    routed.setdefault(statute_collection, []).extend(manifest.document_records)
    routed.setdefault(entity_collection, []).extend(manifest.entity_records)

    assert entity_collection != statute_collection
    assert entity_collection not in set(roster.document_collections.values())
    assert len(routed) == 2
    assert manifest.entity_records  # the assertion below is not vacuous
    for record in routed[statute_collection]:
        assert "record_kind" not in record, (
            f"an entity projection reached the shared statute collection {statute_collection}"
        )
        assert "logical_document_id" in record
    for record in routed[entity_collection]:
        assert record["record_kind"] == "entity_projection"
        assert "logical_document_id" not in record


def test_the_adapted_manifest_has_no_combined_accessor(manifest) -> None:
    """Separation must be structural, not a convention a caller can forget."""
    assert not hasattr(manifest, "records")
    assert not hasattr(manifest, "all_records")
    document_ids = {id(r) for r in manifest.document_records}
    assert document_ids.isdisjoint({id(r) for r in manifest.entity_records})


# --------------------------------------------------------------------------
# The document consumer, unchanged, still cannot read an entity record
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def document_consumer():
    release = ROOT / "scripts" / "release"
    sys.path.insert(0, str(release))
    spec = importlib.util.spec_from_file_location(
        "kansas_fiscal_document_ingest_adapter_probe", release / "kansas-fiscal-document-ingest.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_document_consumer_still_refuses_an_entity_manifest(document_consumer, tmp_path) -> None:
    """The problem this adapter exists for -- now refused for the RIGHT reason.

    Before the integration, ``load_manifest`` routed every line down the
    document path and an entity record failed as a missing
    ``logical_document_id``: a shape error wearing a data error's clothes. It
    now dispatches on the contract's own routing predicate and says what the
    record actually is, and where to read it.
    """
    entity_only = tmp_path / "entities.jsonl"
    entity_only.write_text(
        json.dumps(_jsonl(MIXED)[1], sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(document_consumer.FiscalIngestError) as excinfo:
        document_consumer.load_manifest(entity_only, contract_schema=CONTRACT)
    message = str(excinfo.value)
    assert "this is an ENTITY record" in message
    assert "--record-kind entity" in message
    # The old message named a field the record was never supposed to have.
    assert "missing logical_document_id" not in message


def test_the_adapter_adds_no_load_manifest_call_site() -> None:
    """``enforcedAt`` is DISCOVERED from load_manifest call sites.

    tests/test_statecivics_contract_pin.py::test_every_load_manifest_caller_enforces_the_pin
    walks the tracked source and requires the declared set to equal the
    discovered set exactly, both directions. This adapter reads the manifest
    itself and verifies the pins for the branches it actually read, so it adds
    no call site and that declaration is untouched. Asserted structurally, so
    adding one later fails here first, with a reason.
    """
    tree = ast.parse(ADAPTER_SOURCE.read_text(encoding="utf-8"))
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "load_manifest" not in called
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "load_manifest" not in imported


# --------------------------------------------------------------------------
# Fixture provenance
# --------------------------------------------------------------------------


def test_the_fixtures_cover_every_entity_kind_upstream_emits(manifest) -> None:
    """StateCivics' entity branch enumerates exactly two entity_type values."""
    enumerated = set(
        load_contract(CONTRACT)["$defs"]["entity_projection_record"]["properties"]["entity_type"]["enum"]
    )
    assert enumerated == {"provision_reference", "appropriation_action"}
    assert {r["entity_type"] for r in manifest.entity_records} == enumerated


# --------------------------------------------------------------------------
# Item 6: the live path refuses a candidate BEFORE any embed or index call
# --------------------------------------------------------------------------


def _candidate(record: dict, status: str = CANDIDATE_ELIGIBILITY_STATUS) -> dict:
    """A copy of an entity record with its own review status rewritten.

    At the pinned contract (24c9d3de) ``entity_eligibility.status`` admits
    ``candidate``, so such a record is contract-VALID and reaches the gate
    through ``adapt_records``. Before the re-pin it did not: the enum was
    ``["reviewed","published"]`` and the record was refused by the schema first.
    """
    out = copy.deepcopy(record)
    out["eligibility"]["status"] = status
    # BOTH halves. Rewriting only the envelope produces the self-contradictory
    # record round five is about, and the cross-field rule now refuses it -- so
    # a helper that did that would be testing the wrong thing everywhere.
    out["entity"]["status"] = status
    return out


class _Detonator:
    """A callable that fails if it is ever called.

    The ordering claim is that nothing is embedded or written before the
    eligibility gate decides. Asserting "the spy list is empty afterwards" only
    proves it for the run that happened; a callable that raises proves it for
    the call itself, and names which one fired.
    """

    def __init__(self, what: str) -> None:
        self.what = what
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError(
            f"{self.what} was called before the eligibility gate refused a candidate"
        )


def test_a_candidate_is_refused_for_the_live_path_by_name(manifest) -> None:
    record = _candidate(manifest.entity_records[0])
    with pytest.raises(CandidateRecordRefused) as excinfo:
        admit_entity_records([record], path=LIVE_PATH)
    message = str(excinfo.value)
    assert "for the live entity store" in message
    assert "eligibility.status is 'candidate'" in message
    assert record["entity_logical_id"] in message
    assert "Nothing has been embedded or indexed." in message


def test_the_candidate_path_accepts_it(manifest) -> None:
    record = _candidate(manifest.entity_records[0])
    admitted = admit_entity_records([record], path=CANDIDATE_PATH)
    assert len(admitted) == 1
    assert admitted[0]["eligibility"]["status"] == CANDIDATE_ELIGIBILITY_STATUS
    assert entity_path_for(record) == CANDIDATE_PATH


def test_the_live_path_accepts_reviewed_and_published(manifest) -> None:
    for status in sorted(LIVE_ELIGIBILITY_STATUSES):
        record = _candidate(manifest.entity_records[0], status)
        assert entity_path_for(record) == LIVE_PATH
        assert len(admit_entity_records([record], path=LIVE_PATH)) == 1
    # ...and the real fixtures, unmodified, are live records.
    assert len(admit_entity_records(manifest.entity_records, path=LIVE_PATH)) == 2


def test_the_candidate_path_refuses_a_reviewed_record(manifest) -> None:
    """Symmetry: a reviewed revision parked on the candidate path is invisible."""
    with pytest.raises(CandidateRecordRefused, match="belongs on the 'live' path"):
        admit_entity_records(manifest.entity_records, path=CANDIDATE_PATH)


def test_nothing_is_embedded_or_indexed_before_the_refusal(manifest, tmp_path) -> None:
    """THE ordering proof. The callables detonate if reached."""
    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    records = [manifest.entity_records[0], _candidate(manifest.entity_records[1])]
    with pytest.raises(CandidateRecordRefused):
        stage_entity_descriptors(
            records,
            path=LIVE_PATH,
            **_staging(tmp_path),
            embed=embed,
            index_write=index_write,
        )
    assert embed.calls == 0, "an embedding call was made before the refusal"
    assert index_write.calls == 0, "an index write was made before the refusal"


def test_one_candidate_refuses_the_whole_batch_before_the_first_embed(manifest, tmp_path) -> None:
    """The clean record ahead of it must not be embedded either.

    Per-record refusal would embed the first record, then refuse -- and the
    money is spent and the point is written whatever the refusal then says.
    """
    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    records = [manifest.entity_records[0]] * 5 + [_candidate(manifest.entity_records[1])]
    with pytest.raises(CandidateRecordRefused):
        stage_entity_descriptors(
            records, path=LIVE_PATH, **_staging(tmp_path), embed=embed, index_write=index_write
        )
    assert embed.calls == 0


def test_staging_calls_embed_then_index_once_admitted(manifest, tmp_path) -> None:
    """The gate is not simply refusing everything."""
    embedded: list[str] = []
    written: list[tuple] = []
    result = stage_entity_descriptors(
        manifest.entity_records,
        path=LIVE_PATH,
        **_staging(tmp_path),
        embed=lambda text: embedded.append(text) or [0.0],
        index_write=lambda collection, rows: written.append((collection, rows)),
    )
    assert result.embedded == 2
    assert len(embedded) == 2
    assert embedded == [r["description"]["text"] for r in manifest.entity_records]
    assert len(written) == 1
    # The collection is the one the GUARDS resolved, not one named here.
    assert written[0][0] == result.collection == LIVE_ENTITY_COLLECTION


def test_staging_takes_no_default_io_callables() -> None:
    """``embed``/``index_write`` are keyword-only with no defaults.

    A default would make it possible to invoke this into doing I/O by accident.
    """
    import inspect

    sig = inspect.signature(stage_entity_descriptors)
    for name in ("path", "adapter", "instance_root", "embed", "index_write"):
        parameter = sig.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


def test_the_gate_itself_holds_no_io_seam() -> None:
    """``admit_entity_records`` cannot be arranged into spending anything."""
    import inspect

    sig = inspect.signature(admit_entity_records)
    assert set(sig.parameters) == {"records", "path"}


@pytest.mark.parametrize(
    "eligibility",
    [None, {}, {"status": "draft"}, {"status": None}, {"status": 1}, {"human_reviewed": True}],
)
def test_an_unrecognised_or_missing_status_is_refused(manifest, eligibility) -> None:
    record = copy.deepcopy(manifest.entity_records[0])
    # MIRROR the mutation into the payload, so the cross-field rule passes and
    # this test is about the status rule alone. Dropping the payload instead
    # would now be refused as a payload-less upsert -- correct, but a different
    # rule, and a test that cannot say which rule fired proves neither.
    if eligibility is None:
        record.pop("eligibility")
        record["entity"]["status"] = None
    else:
        record["eligibility"] = eligibility
        record["entity"]["status"] = eligibility.get("status")
    with pytest.raises(UnknownEligibilityStatus):
        eligibility_status(record)
    with pytest.raises(UnknownEligibilityStatus):
        admit_entity_records([record], path=LIVE_PATH)


def test_the_candidate_collection_is_not_the_live_entity_collection(tmp_path) -> None:
    root = _instance_tree(
        tmp_path,
        stores={
            "kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-entities": {"entity-ledger": ENTITY_PROFILE},
            "kansas-fiscal-entity-candidates": {"candidate-ledger": "voyage_4_candidates_1024"},
        },
    )
    entity_stores = ("kansas-fiscal-entities", "kansas-fiscal-entity-candidates")
    qdrant = _qdrant()
    candidate = candidate_collection_name(
        qdrant,
        instance_root=root,
        candidate_embedding_profile_id="voyage_4_candidates_1024",
        entity_embedding_profile_id=ENTITY_PROFILE,
        entity_store_slugs=entity_stores,
    )
    live = entity_collection_name(
        qdrant,
        instance_root=root,
        entity_embedding_profile_id=ENTITY_PROFILE,
        entity_store_slugs=entity_stores,
    )
    assert candidate == "svs_biz_ks_state_civics_voyage_4_candidates_1024"
    assert candidate != live
    assert candidate != STATUTE_COLLECTION
    with pytest.raises(EntityCollectionCollision, match="LIVE entity collection"):
        candidate_collection_name(
            qdrant,
            instance_root=root,
            candidate_embedding_profile_id=ENTITY_PROFILE,
            entity_embedding_profile_id=ENTITY_PROFILE,
            entity_store_slugs=entity_stores,
        )


def test_the_pinned_contract_now_permits_candidate_and_the_gate_still_refuses(schema) -> None:
    """This test was a TRIPWIRE and it fired. Here is what it caught.

    Before KS-650 B1.3 it asserted the enum was ``["reviewed","published"]`` and
    that a candidate record was refused by ``adapt_records`` -- so the gate could
    not silently go live against a contract that did not permit the value. The
    re-pin to 24c9d3de widened the enum, this test failed, and it now asserts the
    other half of the invariant: the CONTRACT admits ``candidate``, and the LIVE
    GATE still refuses it. Those are different mechanisms and both must hold --
    a schema that permits a value is not a store that should receive it, which
    is what the contract's own new description says in terms.
    """
    status = schema["$defs"]["entity_eligibility"]["properties"]["status"]
    assert status["enum"] == ["candidate", "reviewed", "published"]
    # The prose must not be left contradicting the enum it describes.
    assert "never enter a live entity store" in status["description"].lower()
    assert (
        "only those two values can appear"
        not in schema["$defs"]["entity_eligibility"]["description"]
    )

    record = _candidate(_jsonl(MIXED)[1])
    # The contract now accepts it...
    adapted = adapt_records([(1, record)], schema)
    assert len(adapted.entity_records) == 1
    # ...and the live path still does not.
    with pytest.raises(CandidateRecordRefused):
        admit_entity_records(adapted.entity_records, path=LIVE_PATH)
    assert len(admit_entity_records(adapted.entity_records, path=CANDIDATE_PATH)) == 1


# --------------------------------------------------------------------------
# Item 7: the composition milestone, on BOTH real HB 2513 revision-2 records
# --------------------------------------------------------------------------
#
# Not a fixture written here: the manifest repo A's exporter actually wrote for
# HB 2513 Sec. 15(b), committed at 5e9b88cc and byte-identical to it. Two
# records, both revision 2, both `candidate`: the provision_reference and the
# appropriation_action with its three stored edges.


@pytest.fixture(scope="module")
def real_records() -> dict[str, dict]:
    records = _jsonl(REAL_MANIFEST)
    assert len(records) == 2
    return {record["entity_type"]: record for record in records}


@pytest.fixture(scope="module")
def real_action(real_records) -> dict:
    return real_records["appropriation_action"]


@pytest.fixture(scope="module")
def real_provision(real_records) -> dict:
    return real_records["provision_reference"]


def _payload_revision(record: dict) -> int:
    """The revision the KS-600 payload itself carries, by entity type."""
    entity = record["entity"]
    return entity["revision" if record["entity_type"] == "appropriation_action" else
                  "provision_reference_revision"]


def test_the_manifest_is_the_artifact_upstream_committed() -> None:
    """Provenance before proof. These are the exporter's bytes, unaltered."""
    import hashlib

    assert hashlib.sha256(REAL_MANIFEST.read_bytes()).hexdigest() == REAL_MANIFEST_SHA256


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_7_1_the_real_record_is_valid_under_the_widened_contract(
    real_records, schema, kind
) -> None:
    """Proof 1. Valid -- which neither record was before the enum widened."""
    record = real_records[kind]
    rule = dispatch_rule(schema)
    assert classify_record(record, rule) == rule.present_pin
    result = validate(record, schema, rule.present_ref)
    assert result.ok, result.errors
    assert record["eligibility"]["status"] == "candidate"


def test_7_1b_the_whole_manifest_goes_through_the_reader(real_records, schema) -> None:
    """Both records at once, through adapt_records, as a manifest is read."""
    adapted = adapt_manifest(REAL_MANIFEST, contract_schema=CONTRACT)
    assert len(adapted.entity_records) == 2
    assert adapted.document_records == ()
    assert {r["entity_type"] for r in adapted.entity_records} == set(real_records)
    assert set(adapted.verified_pins) == {"dispatch", "entity"}


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_7_1c_the_same_record_was_invalid_under_the_superseded_entity_branch(
    real_records, schema, kind
) -> None:
    """The widening is load-bearing, not cosmetic."""
    narrowed = copy.deepcopy(schema)
    narrowed["$defs"]["entity_eligibility"]["properties"]["status"]["enum"] = [
        "reviewed",
        "published",
    ]
    result = validate(real_records[kind], narrowed, "entity_projection_envelope")
    assert not result.ok
    assert any("candidate" in error for error in result.errors)


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_7_2_the_live_path_refuses_it_with_the_named_refusal(real_records, kind) -> None:
    """Proof 2. THE DELIVERABLE, now for both records."""
    record = real_records[kind]
    with pytest.raises(CandidateRecordRefused) as excinfo:
        admit_entity_records([record], path=LIVE_PATH)
    message = str(excinfo.value)
    assert "for the live entity store" in message
    assert "eligibility.status is 'candidate'" in message
    assert record["entity_logical_id"] in message
    assert record["export_record_id"] in message
    assert "revision 2" in message
    assert "Nothing has been embedded or indexed." in message


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_7_2b_the_refusal_is_for_candidacy_and_for_nothing_else(
    real_records, schema, kind
) -> None:
    """Proof 2, sharpened. A refusal for the WRONG reason is not the milestone.

    The record must be otherwise flawless: valid against the branch, and the
    same record with ONLY `status` changed must sail through the live path.
    """
    record = real_records[kind]
    rule = dispatch_rule(schema)
    assert validate(record, schema, rule.present_ref).ok
    for status in sorted(LIVE_ELIGIBILITY_STATUSES):
        twin = _candidate(record, status)  # BOTH halves; see round five
        assert entity_path_for(twin) == LIVE_PATH
        assert len(admit_entity_records([twin], path=LIVE_PATH)) == 1
        # ...and still valid, so nothing else in the record is marginal.
        assert validate(twin, schema, rule.present_ref).ok
    # No URI reason can be hiding either: `uri` asserts here, and A is strict on
    # it too, so neither side can refuse the other for that.
    assert "uri" in ASSERTED_FORMATS


def test_7_2c_the_whole_manifest_is_refused_with_nothing_spent(real_records, tmp_path) -> None:
    """Proof 2, ordered, on the real manifest: two records, zero calls."""
    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    with pytest.raises(CandidateRecordRefused):
        stage_entity_descriptors(
            list(real_records.values()),
            path=LIVE_PATH,
            **_staging(tmp_path),
            embed=embed,
            index_write=index_write,
        )
    assert (embed.calls, index_write.calls) == (0, 0)


def test_7_3_the_candidate_path_accepts_both(real_records, tmp_path) -> None:
    """Proof 3."""
    records = list(real_records.values())
    for record in records:
        assert entity_path_for(record) == CANDIDATE_PATH
    assert len(admit_entity_records(records, path=CANDIDATE_PATH)) == 2

    embedded: list[str] = []
    written: list[tuple] = []
    staged = stage_entity_descriptors(
        records,
        path=CANDIDATE_PATH,
        **_staging(tmp_path),
        embed=lambda text: embedded.append(text) or [0.0],
        index_write=lambda collection, rows: written.append((collection, rows)),
    )
    assert staged.embedded == 2
    assert embedded == [r["description"]["text"] for r in records]
    assert written[0][0] == staged.collection == CANDIDATE_COLLECTION


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_7_4_no_fallback_envelope_and_payload_both_say_revision_two(
    real_records, kind
) -> None:
    """Proof 4. The one that would have failed silently.

    An as-of query that quietly picked revision 1 -- which is the superseded,
    non-candidate row -- would make the live path appear to ACCEPT a record it
    must never see, and it would look like success.

    Two assertions, because A made envelope/payload agreement the fallback
    signature: a revision-2 envelope wrapping a revision-1 payload is exactly
    what a half-applied selection leaves behind. (That mismatch was real, in a
    stale hand-written fixture, and is what refusing to reconstruct surfaced.)
    """
    record = real_records[kind]
    assert record["entity_revision"] == 2
    assert _payload_revision(record) == 2


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_7_4b_the_superseded_twin_would_be_admitted_which_is_the_point(
    real_records, kind
) -> None:
    """What makes assertion 4 load-bearing rather than decorative.

    On arrival a silent fallback is INDISTINGUISHABLE from a legitimate live
    record: revision 1 is `reviewed`, so the gate admits it and everything
    downstream looks like success. B cannot watch A's selection. So the guard
    has to be the assertion on the revision as emitted, and this is the thing
    it guards against.
    """
    fallback = _candidate(real_records[kind], "reviewed")
    fallback["entity_revision"] = 1
    fallback["entity"]["revision" if kind == "appropriation_action"
                       else "provision_reference_revision"] = 1
    assert len(admit_entity_records([fallback], path=LIVE_PATH)) == 1
    assert fallback["entity_revision"] != real_records[kind]["entity_revision"]


def test_7_5_the_action_carries_its_three_stored_edges(real_action) -> None:
    """Every v1 edge an appropriation action's own columns support.

    The `action_relies_on_provision` target is revision **2** -- the candidate
    provision in this same manifest, not the superseded one. An edge pointing at
    revision 1 would be the fallback wearing a different hat.
    """
    edges = {e["relationship_type"]: e for e in real_action["relationships"]}
    assert set(edges) == {
        "action_relies_on_provision",
        "action_enacted_by_bill_version",
        "action_supersedes_action",
    }
    assert all(e["basis"] == "exact_shared_identifier" for e in edges.values())

    relies = edges["action_relies_on_provision"]["target"]
    assert relies["provision_reference_logical_id"] == PROVISION_LOGICAL_ID
    assert relies["provision_reference_revision"] == 2, (
        "the action must rely on the revision-2 provision in this manifest, not the "
        "superseded revision 1"
    )
    assert edges["action_enacted_by_bill_version"]["target"] == {"bill_version_id": 4782}
    assert edges["action_supersedes_action"]["target"] == {
        "appropriation_action_id": ACTION_LOGICAL_ID,
        "appropriation_action_revision": 1,
    }


def test_7_5b_the_provision_carries_only_its_own_supersession_edge(real_provision) -> None:
    """A provision has exactly one kind of edge; the action side owns the FK."""
    edges = real_provision["relationships"]
    assert [e["relationship_type"] for e in edges] == ["provision_supersedes_provision"]
    assert edges[0]["basis"] == "exact_shared_identifier"
    assert edges[0]["target"] == {
        "provision_reference_logical_id": PROVISION_LOGICAL_ID,
        "provision_reference_revision": 1,
    }


def test_7_5c_the_edge_targets_are_consistent_with_the_manifest(real_action, real_provision) -> None:
    """Cross the two records against each other, not against constants here."""
    relies = next(
        e for e in real_action["relationships"]
        if e["relationship_type"] == "action_relies_on_provision"
    )["target"]
    assert relies["provision_reference_logical_id"] == real_provision["entity_logical_id"]
    assert relies["provision_reference_revision"] == real_provision["entity_revision"]
    supersedes = next(
        e for e in real_action["relationships"]
        if e["relationship_type"] == "action_supersedes_action"
    )["target"]
    assert supersedes["appropriation_action_id"] == real_action["entity_logical_id"]
    assert supersedes["appropriation_action_revision"] == real_action["entity_revision"] - 1


def test_the_real_records_match_the_authoritative_identifiers(real_action, real_provision) -> None:
    """The identifiers, now read from a committed artifact rather than relayed.

    The values previously carried here -- `0a6fd522...` and `cda8d793...` --
    came from a hand-written fixture that had gone stale. They are gone from
    upstream's tree and gone from here.

    Refreshed to A's `origin/main` at 677d126d. The two manifests differ in
    EXACTLY two fields -- `exporter.code_commit` and `record_digest_sha256` --
    which was verified here by diffing them rather than taken on report. Every
    substantive field is identical, so item 7's semantic conclusions carry over
    and only these digest assertions needed re-running.
    """
    assert real_action["export_record_id"] == (
        "f3f720043071536735e626895a345c510ae9be097b8414c98b0b57399f742941"
    )
    assert real_action["record_digest_sha256"] == (
        "3479ae3bbc5b7df554230c8434510e2b6803ea281e9f38261791d1a2b68d9334"
    )
    assert real_provision["export_record_id"] == (
        "f4c674039b228388692962afbbeaf05cc981262d97a733e15828c40165343684"
    )
    assert real_provision["record_digest_sha256"] == (
        "14c01e5a8f9a6bf11902f741a52bd76dc3c5c86725525c6a30256e67eb2322b0"
    )
    for record in (real_action, real_provision):
        assert record["exporter"]["code_commit"] == (
            "d3000e989afb85a7a9efd24d529672b50359ffcd"
        )
        assert record["record_digest_algorithm"] == "statecivics-canonical-json-v1"
        assert record["as_of"]["declared"] is True
        assert record["eligibility"]["status"] == "candidate"
        assert record["eligibility"]["human_reviewed"] is False
        assert record["eligibility"]["review_level"] == "none"
    # `publication_allowed` differs BY ENTITY TYPE, and the contract says why:
    # civic_appropriation_actions has no such column, so null says "no column"
    # rather than inventing a permissive default. Asserted per type, because
    # asserting one value for both would have hidden that distinction.
    assert real_action["eligibility"]["publication_allowed"] is None
    assert real_provision["eligibility"]["publication_allowed"] is False
    # The KS-600 payloads are NOT validated here -- they are remote $refs with
    # their own pins -- so their shape is recorded, not judged. `source_url` is
    # the declared key and the stray `url` that KS-650 B1.3 fixed is absent.
    assert sorted(real_action["entity"]["source"]) == [
        "locator",
        "source_revision_id",
        "source_span_id",
        "source_url",
    ]
    assert "url" not in real_action["entity"]["source"]
    assert "url" not in real_provision["entity"]["evidence"][0]


# --------------------------------------------------------------------------
# Round five, item 1: envelope and payload must agree
# --------------------------------------------------------------------------
#
# The gap this closes was reported as a STRENGTH. "The same record with only
# `status` changed passes the live path" was offered as proof the refusal was
# single-reason. It is the opposite: changing only the ENVELOPE's status leaves
# the PAYLOAD saying `candidate`, and that self-contradictory record satisfied
# both schemas -- and reached the embedding and index callbacks.
#
# JSON Schema cannot express this. The envelope is validated against the
# retrieval-export contract and the payload against its own KS-600 contract,
# and nothing relates them. So it is a cross-field rule, applied after schema
# validation, and it moves no digest.


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_r5_1_the_contradictory_record_is_now_refused(real_records, schema, kind) -> None:
    """THE INVERSION. This record passed before round five; it must not now."""
    record = copy.deepcopy(real_records[kind])
    record["eligibility"]["status"] = "published"  # envelope only
    assert record["entity"]["status"] == "candidate"  # payload untouched

    # Both schemas still accept it -- which is the whole problem.
    rule = dispatch_rule(schema)
    assert validate(record, schema, rule.present_ref).ok

    with pytest.raises(EnvelopePayloadMismatch) as excinfo:
        adapt_records([(1, record)], schema)
    message = str(excinfo.value)
    assert "eligibility.status='published'" in message
    assert "status='candidate'" in message
    assert record["export_record_id"] in message
    # ...and the gate refuses it too, so no path to embedding is left open.
    with pytest.raises(EnvelopePayloadMismatch):
        admit_entity_records([record], path=LIVE_PATH)


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_r5_1b_the_revision_mismatch_twin_is_refused(real_records, schema, kind) -> None:
    """Envelope revision 2, payload revision 1.

    Exactly the shape upstream's stale fixture produced by accident, and exactly
    what a half-applied as-of selection would leave behind.
    """
    record = copy.deepcopy(real_records[kind])
    payload_key = "revision" if kind == "appropriation_action" else "provision_reference_revision"
    record["entity"][payload_key] = 1
    rule = dispatch_rule(schema)
    assert validate(record, schema, rule.present_ref).ok, "schemas still accept it"

    with pytest.raises(EnvelopePayloadMismatch) as excinfo:
        adapt_records([(1, record)], schema)
    message = str(excinfo.value)
    assert "entity_revision=2" in message
    assert f"{payload_key}=1" in message


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_r5_1c_an_identity_mismatch_is_refused(real_records, schema, kind) -> None:
    """The third field. A record pointing at somebody else's identity."""
    record = copy.deepcopy(real_records[kind])
    payload_key = (
        "appropriation_action_id" if kind == "appropriation_action"
        else "provision_reference_logical_id"
    )
    record["entity"][payload_key] = "0" * 64
    # PRECONDITION, as r5_1 and r5_1b have: both halves are individually
    # schema-valid, so what follows can only be the cross-field rule. Without
    # this the test cannot distinguish that rule from a schema incidentally
    # catching the mutation -- it would pass either way and prove neither.
    rule = dispatch_rule(schema)
    assert validate(record, schema, rule.present_ref).ok, (
        "the mutated record must still satisfy both schemas, or this test is "
        "measuring schema validation rather than the cross-field rule"
    )
    with pytest.raises(EnvelopePayloadMismatch, match="entity_logical_id"):
        adapt_records([(1, record)], schema)


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_r5_1d_the_real_records_are_positive_controls(real_records, kind) -> None:
    """The internally consistent revision-2 records still pass. Not a blanket no."""
    assert_envelope_payload_agreement(real_records[kind])
    assert len(admit_entity_records([real_records[kind]], path=CANDIDATE_PATH)) == 1


def test_r5_1e_nothing_is_embedded_when_a_contradictory_record_is_refused(
    real_records, tmp_path
) -> None:
    """Same batch-level, pre-embed ordering as the candidate gate, proved the same way."""
    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    contradictory = _candidate(real_records["provision_reference"], "published")
    contradictory["entity"]["status"] = "candidate"  # break the agreement again
    clean = _candidate(real_records["appropriation_action"], "published")
    with pytest.raises(EnvelopePayloadMismatch):
        stage_entity_descriptors(
            [clean, contradictory],
            path=LIVE_PATH,
            **_staging(tmp_path),
            embed=embed,
            index_write=index_write,
        )
    assert (embed.calls, index_write.calls) == (0, 0)


def _tombstone(record: dict, state: str = "superseded") -> dict:
    """A REAL removal record, as upstream's ``build_removal_record`` makes one.

    Identity-minimal: no entity, no description, no derivation; action
    ``remove``; lifecycle stating which kind of retraction and why.
    """
    out = copy.deepcopy(record)
    for key in ("entity", "description", "derivation"):
        out.pop(key, None)
    out["ingestion"] = dict(out["ingestion"], action="remove", recall_evaluation_required=False)
    out["relationships"] = []
    out["lifecycle"] = {
        "state": state,
        "reason": "superseded by a reviewed revision",
        "replaced_by": {"entity_logical_id": out["entity_logical_id"], "entity_revision": 3},
        "removal_required": True,
    }
    out["eligibility"] = {
        "status": "published",
        "human_reviewed": True,
        "review_level": "retracted",
        "publication_allowed": False,
    }
    return out


# --- F3: the payload requirement is decided by the ACTION, not by absence -----
#
# `assert_envelope_payload_agreement` used to return silently whenever `entity`
# was missing. So a record that was NOT a tombstone -- lifecycle `current`,
# action `upsert`, description intact -- but whose payload had been stripped
# skipped the check entirely and was embedded and indexed. Absence of the thing
# being checked was read as permission to skip the check.


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
@pytest.mark.parametrize("payload", [None, "missing"])
def test_f3_1_a_current_upsert_without_a_payload_is_refused(
    real_records, tmp_path, kind, payload
) -> None:
    """F3 check 1. Refused, and refused BEFORE any callback."""
    record = _candidate(real_records[kind], "published")
    if payload == "missing":
        record.pop("entity")
    else:
        record["entity"] = None
    assert record["lifecycle"]["state"] == "current"
    assert record["ingestion"]["action"] == "upsert"
    assert "description" in record, "not a tombstone by any reading"

    with pytest.raises(EnvelopePayloadMismatch) as excinfo:
        assert_envelope_payload_agreement(record)
    message = str(excinfo.value)
    assert "requires an entity payload" in message
    assert "A missing payload is not a tombstone" in message

    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    with pytest.raises(EnvelopePayloadMismatch):
        stage_entity_descriptors(
            [record], path=LIVE_PATH, **_staging(tmp_path), embed=embed, index_write=index_write
        )
    assert (embed.calls, index_write.calls) == (0, 0)


@pytest.mark.parametrize(
    ("action", "state", "removal_required"),
    [
        ("remove", "current", True),      # retraction claiming current state
        ("remove", "current", False),
        ("upsert", "superseded", False),  # the inverse
        ("upsert", "withdrawn", True),
        ("remove", "superseded", False),  # action and flag disagree
        ("upsert", "current", True),
    ],
)
def test_f3_2_contradictory_removal_flags_are_refused(
    real_records, action, state, removal_required
) -> None:
    """F3 check 2. An action and a lifecycle that disagree describe two records."""
    record = _candidate(real_records["provision_reference"], "published")
    record["ingestion"] = dict(record["ingestion"], action=action)
    record["lifecycle"] = dict(
        record["lifecycle"], state=state, removal_required=removal_required
    )
    with pytest.raises(EnvelopePayloadMismatch) as excinfo:
        assert_envelope_payload_agreement(record)
    assert "ingestion.action" in str(excinfo.value)


@pytest.mark.parametrize("state", ["superseded", "withdrawn"])
@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_f3_3_a_legitimate_tombstone_adapts_but_never_embeds(
    real_records, schema, tmp_path, kind, state
) -> None:
    """F3 check 3, BOTH halves.

    A tombstone is valid to ADAPT -- it is a real record the manifest carries --
    and is not valid to STAGE, because it directs a DELETE and has no
    description to embed.
    """
    tombstone = _tombstone(real_records[kind], state)

    # half one: valid, schema and cross-field alike, and it goes through the reader.
    rule = dispatch_rule(schema)
    assert validate(tombstone, schema, rule.present_ref).ok
    assert_envelope_payload_agreement(tombstone)
    assert len(adapt_records([(1, tombstone)], schema).entity_records) == 1

    # half two: refused at the staging gate, before any callback.
    with pytest.raises(RemovalRecordNotStageable, match="directs a DELETE"):
        admit_entity_records([tombstone], path=LIVE_PATH)
    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    with pytest.raises(RemovalRecordNotStageable):
        stage_entity_descriptors(
            [tombstone], path=LIVE_PATH, **_staging(tmp_path), embed=embed, index_write=index_write
        )
    assert (embed.calls, index_write.calls) == (0, 0)


def test_f3_3b_a_tombstone_carrying_a_payload_is_refused(real_records) -> None:
    """A tombstone names what to delete and nothing else."""
    tombstone = _tombstone(real_records["provision_reference"])
    tombstone["entity"] = copy.deepcopy(real_records["provision_reference"]["entity"])
    with pytest.raises(EnvelopePayloadMismatch, match="names what to delete and nothing else"):
        assert_envelope_payload_agreement(tombstone)


@pytest.mark.parametrize("kind", ["appropriation_action", "provision_reference"])
def test_f3_4_existing_valid_upserts_still_work(real_records, tmp_path, kind) -> None:
    """F3 check 4. The positive control: the fix is not "refuse everything"."""
    record = _candidate(real_records[kind], "published")
    assert_envelope_payload_agreement(record)
    assert len(admit_entity_records([record], path=LIVE_PATH)) == 1
    written: list[tuple] = []
    staged = stage_entity_descriptors(
        [record],
        path=LIVE_PATH,
        **_staging(tmp_path),
        embed=lambda text: [0.0],
        index_write=lambda collection, rows: written.append((collection, rows)),
    )
    assert staged.embedded == 1
    assert written[0][0] == LIVE_ENTITY_COLLECTION
    # ...and the real candidate records still route to the candidate path.
    assert len(admit_entity_records([real_records[kind]], path=CANDIDATE_PATH)) == 1


def test_f3_5_the_discriminator_is_the_action_not_record_kind(real_records) -> None:
    """`record_kind` says "entity projection" and nothing about upsert vs remove.

    Both records below carry `record_kind: entity_projection`; they differ only
    in their action, and the payload requirement follows the action.
    """
    upsert = _candidate(real_records["provision_reference"], "published")
    tombstone = _tombstone(real_records["provision_reference"])
    assert upsert["record_kind"] == tombstone["record_kind"] == "entity_projection"
    assert_envelope_payload_agreement(tombstone)  # no payload: correct for remove
    with pytest.raises(EnvelopePayloadMismatch):
        stripped = copy.deepcopy(upsert)
        stripped.pop("entity")
        assert_envelope_payload_agreement(stripped)  # no payload: wrong for upsert


def test_r5_1g_the_rule_moves_no_digest(schema) -> None:
    """A cross-field rule relates two documents; it changes neither."""
    from svs_common.statecivics_contract_pin import (
        DISPATCH_SHA256,
        DOCUMENT_BRANCH_SHA256,
        ENTITY_BRANCH_SHA256,
        branch_digests,
    )

    assert branch_digests(schema) == {
        "document": DOCUMENT_BRANCH_SHA256,
        "entity": ENTITY_BRANCH_SHA256,
        "dispatch": DISPATCH_SHA256,
    }


# --------------------------------------------------------------------------
# Round five, item 2: staging resolves its own collection
# --------------------------------------------------------------------------


def test_r5_2_a_caller_supplied_document_collection_is_refused(real_records, tmp_path) -> None:
    """THE FINDING. This exact call embedded into the shared statute collection.

    The guards existed and `stage_entity_descriptors` did not call them, so a
    guard that describes an invariant is not a guard that holds one.
    """
    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    live = [_candidate(r, "published") for r in real_records.values()]
    with pytest.raises(CallerSuppliedCollectionRefused) as excinfo:
        stage_entity_descriptors(
            live,
            path=LIVE_PATH,
            **_staging(tmp_path),
            collection=STATUTE_COLLECTION,
            embed=embed,
            index_write=index_write,
        )
    message = str(excinfo.value)
    assert STATUTE_COLLECTION in message
    assert LIVE_ENTITY_COLLECTION in message
    assert "Nothing has been embedded or indexed." in message
    assert (embed.calls, index_write.calls) == (0, 0)


def test_r5_2b_the_live_path_resolves_its_own_collection(real_records, tmp_path) -> None:
    """No `collection=` given at all: the guards decide, and they decide right."""
    written: list[tuple] = []
    staged = stage_entity_descriptors(
        [_candidate(r, "published") for r in real_records.values()],
        path=LIVE_PATH,
        **_staging(tmp_path),
        embed=lambda text: [0.0],
        index_write=lambda collection, rows: written.append((collection, rows)),
    )
    assert staged.collection == LIVE_ENTITY_COLLECTION
    assert written[0][0] == LIVE_ENTITY_COLLECTION
    assert staged.collection != STATUTE_COLLECTION
    assert staged.collection != OPENAI_COLLECTION


def test_r5_2c_the_candidate_path_resolves_its_own_collection(real_records, tmp_path) -> None:
    staged = stage_entity_descriptors(
        list(real_records.values()),
        path=CANDIDATE_PATH,
        **_staging(tmp_path),
        embed=lambda text: [0.0],
        index_write=lambda collection, rows: None,
    )
    assert staged.collection == CANDIDATE_COLLECTION
    assert staged.collection not in {STATUTE_COLLECTION, OPENAI_COLLECTION, LIVE_ENTITY_COLLECTION}


def test_r5_2d_a_matching_caller_supplied_collection_is_permitted(real_records, tmp_path) -> None:
    """`collection=` is an ASSERTION, not a selection. Agreeing is allowed."""
    staged = stage_entity_descriptors(
        list(real_records.values()),
        path=CANDIDATE_PATH,
        **_staging(tmp_path),
        collection=CANDIDATE_COLLECTION,
        embed=lambda text: [0.0],
        index_write=lambda collection, rows: None,
    )
    assert staged.collection == CANDIDATE_COLLECTION


def test_r5_2e_staging_inherits_every_collection_guard(real_records, tmp_path) -> None:
    """The guards are reached THROUGH staging, not merely available beside it."""
    (tmp_path / "incomplete").mkdir()
    incomplete = _instance_tree(
        tmp_path / "incomplete",
        stores={
            "kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-documents": {"fiscal-ledger": None},
            "kansas-fiscal-entities": {"entity-ledger": ENTITY_PROFILE},
        },
    )
    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    with pytest.raises(DocumentCollectionRosterIncomplete):
        stage_entity_descriptors(
            [_candidate(real_records["provision_reference"], "published")],
            path=LIVE_PATH,
            adapter=_qdrant(),
            instance_root=incomplete,
            entity_embedding_profile_id=ENTITY_PROFILE,
            entity_store_slugs=("kansas-fiscal-entities",),
            embed=embed,
            index_write=index_write,
        )
    assert (embed.calls, index_write.calls) == (0, 0)

    # ...and the collision guard, through the same seam.
    (tmp_path / "colliding").mkdir()
    colliding = _instance_tree(
        tmp_path / "colliding",
        stores={
            "kansas-statutes": {"statute-ledger": "voyage_4_docs_1024"},
            "kansas-fiscal-entities": {"entity-ledger": "voyage_4_docs_1024"},
        },
    )
    with pytest.raises(EntityCollectionCollision):
        stage_entity_descriptors(
            [_candidate(real_records["provision_reference"], "published")],
            path=LIVE_PATH,
            adapter=_qdrant(),
            instance_root=colliding,
            entity_embedding_profile_id="voyage_4_docs_1024",
            entity_store_slugs=("kansas-fiscal-entities",),
            embed=embed,
            index_write=index_write,
        )
    assert (embed.calls, index_write.calls) == (0, 0)


def test_r5_2f_the_candidate_path_needs_its_own_profile(real_records, tmp_path) -> None:
    """Falling back to the live profile would serve candidates from the live store."""
    with pytest.raises(InstanceCollectionConfigError, match="candidate path needs its own"):
        resolve_staging_collection(
            _qdrant(),
            path=CANDIDATE_PATH,
            instance_root=_staging_instance(tmp_path),
            entity_embedding_profile_id=ENTITY_PROFILE,
            entity_store_slugs=ENTITY_STORES,
        )


def test_r5_2g_the_adapter_is_now_wired_to_the_real_entrypoint() -> None:
    """This assertion INVERTED, which is the tripwire doing its job.

    It used to assert that NO application caller of ``adapt_manifest`` existed,
    and to fail the moment one appeared -- because until one did, an image
    rebuild would have shipped a library nothing invokes. One now exists, so the
    test says the opposite: the adapter is reachable from the command, and names
    where. Deleting it instead would have thrown away the check that the wiring
    stays wired.
    """
    consumer = ROOT / "scripts" / "release" / "kansas-fiscal-document-ingest.py"
    tree = ast.parse(consumer.read_text(encoding="utf-8"))
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "adapt_manifest" in called, "the entity entrypoint no longer reads through the adapter"
    assert "admit_entity_records" in called, "the eligibility gate is no longer applied"
    assert "classify_record" in called, "the document path no longer dispatches on the contract"
