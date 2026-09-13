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
   That is asserted on the collection name the adapter RETURNS, because
   ``QdrantAdapter.collection_name`` does not take ``vector_store_id`` and a new
   vector store therefore separates nothing.
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
from svs_common.qdrant_adapter import QdrantAdapter
from svs_common.statecivics_contract_pin import (
    BRANCH_ROOTS,
    ContractPinError,
    load_contract,
)
from svs_common.statecivics_record_adapter import (
    EXPECTED_DISPATCH_REQUIRED,
    DispatchRule,
    EntityCollectionCollision,
    RecordBranchError,
    UnsupportedContractKeyword,
    adapt_manifest,
    adapt_records,
    classify_record,
    dispatch_rule,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
CONTRACT = FIXTURES / "statecivics-retrieval-export-record.314beafe.json"
MIXED = FIXTURES / "statecivics-mixed-manifest.jsonl"
BAD_ENTITY = FIXTURES / "statecivics-invalid-entity-record.jsonl"
BAD_DOCUMENT = FIXTURES / "statecivics-invalid-document-record.jsonl"
ADAPTER_SOURCE = ROOT / "packages" / "svs_common" / "svs_common" / "statecivics_record_adapter.py"

#: The instance and profiles from WAVE-134's store-id note. The document/statute
#: points for this cell live in svs_biz_ks_state_civics_voyage_4_docs_1024.
INSTANCE = "biz-ks-state-civics"
DOCUMENT_PROFILE = "voyage-4-docs-1024"
ENTITY_PROFILE = "voyage-4-entities-1024"


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


def _qdrant() -> QdrantAdapter:
    """A QdrantAdapter with settings only -- no client, no network.

    ``__new__`` is how tests/test_index_versioning.py already builds one; the
    constructor would try to reach a Qdrant.
    """
    adapter = QdrantAdapter.__new__(QdrantAdapter)
    adapter.settings = SimpleNamespace(qdrant_collection_prefix="svs_", svs_index_version="")
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
    assert "missing required property 'entity_type'" in message
    # The fixture carries the DOCUMENT branch's identity field. The entity
    # branch forbids it, and that is reported rather than tolerated.
    assert "property 'logical_document_id' is not permitted here" in message
    assert "is not relaxed to admit a record from the other branch" in message


def test_an_invalid_document_record_is_refused_against_the_document_branch() -> None:
    with pytest.raises(RecordBranchError) as excinfo:
        adapt_manifest(BAD_DOCUMENT, contract_schema=CONTRACT)
    message = str(excinfo.value)
    assert "routed to the document branch ($defs.legacy_document_record)" in message
    assert "by the contract's dispatch on ['record_kind']" in message
    assert "missing required property 'logical_document_id'" in message
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


def test_an_unimplemented_keyword_is_refused_rather_than_ignored(schema) -> None:
    extended = copy.deepcopy(schema)
    extended["$defs"]["as_of_snapshot"]["dependentRequired"] = {"declared": ["snapshot_id"]}
    with pytest.raises(UnsupportedContractKeyword, match="dependentRequired"):
        validate(_jsonl(MIXED)[1], extended, "entity_projection_envelope")


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


def test_a_new_vector_store_alone_does_not_separate_the_collection() -> None:
    """The sharpest finding in WAVE-134, asserted on the adapter's own output.

    ``collection_name`` takes (business_instance_id, embedding_profile_id). Two
    different vector stores on the same instance and profile resolve to the SAME
    collection, so the store id cannot be the separator.
    """
    qdrant = _qdrant()
    assert (
        qdrant.collection_name(INSTANCE, DOCUMENT_PROFILE)
        == "svs_biz_ks_state_civics_voyage_4_docs_1024"
    )
    with pytest.raises(EntityCollectionCollision) as excinfo:
        from svs_common.statecivics_record_adapter import entity_collection_name

        entity_collection_name(
            qdrant,
            business_instance_id=INSTANCE,
            document_embedding_profile_id=DOCUMENT_PROFILE,
            entity_embedding_profile_id=DOCUMENT_PROFILE,
        )
    assert "svs_biz_ks_state_civics_voyage_4_docs_1024" in str(excinfo.value)
    assert "vector_store_id" in str(excinfo.value)


def test_entity_records_never_reach_the_shared_statute_collection(manifest) -> None:
    """Route the adapter's real output and assert on where each group lands.

    The collection names are what the adapter RETURNS, not strings built here.
    """
    from svs_common.statecivics_record_adapter import entity_collection_name

    qdrant = _qdrant()
    document_collection = qdrant.collection_name(INSTANCE, DOCUMENT_PROFILE)
    # The Kansas statutes ride the same instance and the same document profile,
    # which is exactly why they share one collection with the fiscal documents.
    statute_collection = qdrant.collection_name(INSTANCE, DOCUMENT_PROFILE)
    assert statute_collection == document_collection

    entity_collection = entity_collection_name(
        qdrant,
        business_instance_id=INSTANCE,
        document_embedding_profile_id=DOCUMENT_PROFILE,
        entity_embedding_profile_id=ENTITY_PROFILE,
    )

    routed: dict[str, list[dict]] = {}
    routed.setdefault(document_collection, []).extend(manifest.document_records)
    routed.setdefault(entity_collection, []).extend(manifest.entity_records)

    assert entity_collection != statute_collection
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
