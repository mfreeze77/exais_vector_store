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
    CandidateRecordRefused,
    DispatchRule,
    DocumentCollectionRosterIncomplete,
    EntityCollectionCollision,
    InstanceCollectionConfigError,
    RecordBranchError,
    UnknownEligibilityStatus,
    UnsupportedContractKeyword,
    adapt_manifest,
    adapt_records,
    admit_entity_records,
    branch_subtree,
    candidate_collection_name,
    classify_record,
    deployment_index_settings,
    dispatch_rule,
    eligibility_status,
    entity_collection_name,
    entity_path_for,
    read_instance_collection_roster,
    stage_entity_descriptors,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
CONTRACT = FIXTURES / "statecivics-retrieval-export-record.314beafe.json"
MIXED = FIXTURES / "statecivics-mixed-manifest.jsonl"
BAD_ENTITY = FIXTURES / "statecivics-invalid-entity-record.jsonl"
BAD_DOCUMENT = FIXTURES / "statecivics-invalid-document-record.jsonl"
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
    """The problem this adapter exists for, demonstrated rather than asserted.

    ``load_manifest`` routes every line down the document path, so an entity
    record fails as a MISSING FIELD -- a shape error wearing a data error's
    clothes. Nothing about ``load_manifest`` is changed by this work.
    """
    entity_only = tmp_path / "entities.jsonl"
    entity_only.write_text(
        json.dumps(_jsonl(MIXED)[1], sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(document_consumer.FiscalIngestError) as excinfo:
        document_consumer.load_manifest(entity_only, contract_schema=CONTRACT)
    assert "logical_document_id" in str(excinfo.value)


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

    NOTE: at the pinned contract (314beafe) ``entity_eligibility.status`` is
    ``["reviewed","published"]``, so a record like this is contract-INVALID and
    ``adapt_records`` refuses it before the eligibility gate is ever reached.
    The gate is therefore exercised directly here. The end-to-end path opens
    when the enum is extended upstream and ``ENTITY_BRANCH_SHA256`` is
    deliberately re-pinned -- WAVE-134 item 5, which waits on repo A.
    """
    out = copy.deepcopy(record)
    out["eligibility"]["status"] = status
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


def test_nothing_is_embedded_or_indexed_before_the_refusal(manifest) -> None:
    """THE ordering proof. The callables detonate if reached."""
    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    records = [manifest.entity_records[0], _candidate(manifest.entity_records[1])]
    with pytest.raises(CandidateRecordRefused):
        stage_entity_descriptors(
            records,
            path=LIVE_PATH,
            collection="svs_biz_ks_state_civics_voyage_4_entities_1024",
            embed=embed,
            index_write=index_write,
        )
    assert embed.calls == 0, "an embedding call was made before the refusal"
    assert index_write.calls == 0, "an index write was made before the refusal"


def test_one_candidate_refuses_the_whole_batch_before_the_first_embed(manifest) -> None:
    """The clean record ahead of it must not be embedded either.

    Per-record refusal would embed the first record, then refuse -- and the
    money is spent and the point is written whatever the refusal then says.
    """
    embed, index_write = _Detonator("embed"), _Detonator("index_write")
    records = [manifest.entity_records[0]] * 5 + [_candidate(manifest.entity_records[1])]
    with pytest.raises(CandidateRecordRefused):
        stage_entity_descriptors(
            records, path=LIVE_PATH, collection="c", embed=embed, index_write=index_write
        )
    assert embed.calls == 0


def test_staging_calls_embed_then_index_once_admitted(manifest) -> None:
    """The gate is not simply refusing everything."""
    embedded: list[str] = []
    written: list[tuple] = []
    result = stage_entity_descriptors(
        manifest.entity_records,
        path=LIVE_PATH,
        collection="svs_biz_ks_state_civics_voyage_4_entities_1024",
        embed=lambda text: embedded.append(text) or [0.0],
        index_write=lambda collection, rows: written.append((collection, rows)),
    )
    assert result.embedded == 2
    assert len(embedded) == 2
    assert embedded == [r["description"]["text"] for r in manifest.entity_records]
    assert len(written) == 1
    assert written[0][0] == "svs_biz_ks_state_civics_voyage_4_entities_1024"


def test_staging_takes_no_default_io_callables() -> None:
    """``embed``/``index_write`` are keyword-only with no defaults.

    A default would make it possible to invoke this into doing I/O by accident.
    """
    import inspect

    sig = inspect.signature(stage_entity_descriptors)
    for name in ("path", "collection", "embed", "index_write"):
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
    if eligibility is None:
        record.pop("eligibility")
    else:
        record["eligibility"] = eligibility
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


def test_the_pinned_contract_still_forbids_the_candidate_status(schema) -> None:
    """Item 5 is not done, and this records exactly why the gate is not yet live.

    The gate above is ready. The contract is not: ``candidate`` is not in the
    enum at 314beafe, so a candidate record cannot reach the gate through
    ``adapt_records``. When repo A extends the enum, ENTITY_BRANCH_SHA256 moves
    and must be re-pinned deliberately; this test then flips to asserting the
    new enum, and the end-to-end path opens.
    """
    enum = schema["$defs"]["entity_eligibility"]["properties"]["status"]["enum"]
    assert enum == ["reviewed", "published"], (
        "the pinned contract's eligibility enum changed; re-pin ENTITY_BRANCH_SHA256 "
        "deliberately (WAVE-134 item 5) and update this test"
    )
    record = _candidate(_jsonl(MIXED)[1])
    with pytest.raises(RecordBranchError, match="is not one of"):
        adapt_records([(1, record)], schema)
