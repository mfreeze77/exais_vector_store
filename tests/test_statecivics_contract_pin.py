"""The per-branch contract pin, and the enforcement that reads it.

A whole-file `contractSha256` went stale the moment either branch moved and
nothing computed it, so it misled rather than protected.  These tests hold the
replacement to the property that makes it worth having: each branch is pinned
independently, and ingestion refuses a branch it was not pinned against.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from svs_common.statecivics_contract_pin import (
    DISPATCH_SHA256,
    DOCUMENT_BRANCH_SHA256,
    ENTITY_BRANCH_SHA256,
    ENFORCED_PINS,
    PINNED_BRANCH_COMMIT,
    PINNED_BRANCH_SHA256,
    PINNED_CONTRACT_COMMIT,
    PIN_NAMES,
    SUPERSEDED_BRANCH_SHA256,
    ContractPinError,
    branch_closure,
    branch_digest,
    branch_digests,
    dispatch_subtree,
    load_contract,
    verify_branch,
    verify_contract,
)

FIXTURE = Path(__file__).parent / "fixtures" / "statecivics-retrieval-export-record.314beafe.json"


@pytest.fixture(scope="module")
def contract() -> dict:
    return load_contract(FIXTURE)


def test_pinned_digests_are_reproducible_from_the_pinned_contract(contract) -> None:
    """The declared numbers are computed, not asserted."""
    assert branch_digests(contract) == {
        "document": DOCUMENT_BRANCH_SHA256,
        "entity": ENTITY_BRANCH_SHA256,
        "dispatch": DISPATCH_SHA256,
    }
    assert set(PIN_NAMES) == set(PINNED_BRANCH_SHA256)
    for name in PIN_NAMES:
        assert verify_branch(contract, name) == PINNED_BRANCH_SHA256[name]


def test_no_semantic_digest_exists(contract) -> None:
    """R-P2. An annotation-stripped digest cannot tell a constraint change from
    prose, because JSON Schema property names share a namespace with annotation
    keywords: legacy_document_record.properties.title is a real constraint on the
    ENFORCED branch. Calling that change 'annotation-only drift' is the defect
    class this module removes, so the mechanism is gone, not merely unused."""
    import svs_common.statecivics_contract_pin as pin

    for gone in ("strip_annotations", "ANNOTATION_KEYWORDS",
                 "DOCUMENT_BRANCH_SEMANTIC_SHA256", "ENTITY_BRANCH_SEMANTIC_SHA256",
                 "PINNED_BRANCH_SEMANTIC_SHA256"):
        assert not hasattr(pin, gone), f"{gone} must not come back"
    with pytest.raises(TypeError):
        branch_digest(contract, "document", semantic=True)
    # The phrase may appear in the module docstring, which explains why the
    # mechanism was removed. It must not survive anywhere an operator could see
    # it -- i.e. in any executable statement.
    import ast

    tree = ast.parse(Path(pin.__file__).read_text())
    literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    docstrings = {ast.get_docstring(n, clean=False) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
    for text in literals:
        if "annotation-only drift" in text:
            assert text in docstrings, "the phrase escaped into a runtime string"


def test_property_named_title_is_a_constraint_not_an_annotation(contract) -> None:
    """The exact collision QC proved by execution. Both mutations are real
    constraint changes to the enforced document branch and must refuse."""
    assert "title" in contract["$defs"]["legacy_document_record"]["properties"]
    assert contract["$defs"]["legacy_document_record"]["additionalProperties"] is False

    tightened = copy.deepcopy(contract)
    tightened["$defs"]["legacy_document_record"]["properties"]["title"] = {
        "type": "string", "minLength": 1,
    }
    with pytest.raises(ContractPinError, match="document digest mismatch"):
        verify_branch(tightened, "document")

    removed = copy.deepcopy(contract)
    del removed["$defs"]["legacy_document_record"]["properties"]["title"]
    with pytest.raises(ContractPinError, match="document digest mismatch"):
        verify_branch(removed, "document")


def test_routing_change_alone_is_refused(contract) -> None:
    """R-P3. Swapping the branches leaves both subtrees byte-identical and sends
    every untagged record to the entity branch."""
    assert list(dispatch_subtree(contract)) == ["if", "then", "else"]

    swapped = copy.deepcopy(contract)
    swapped["then"], swapped["else"] = swapped["else"], swapped["then"]
    assert branch_digest(swapped, "document") == DOCUMENT_BRANCH_SHA256
    assert branch_digest(swapped, "entity") == ENTITY_BRANCH_SHA256
    with pytest.raises(ContractPinError, match="dispatch digest mismatch"):
        verify_branch(swapped, "dispatch")
    with pytest.raises(ContractPinError, match="dispatch digest mismatch"):
        verify_contract(swapped, "document")

    widened = copy.deepcopy(contract)
    widened["if"]["required"] = ["record_kind", "record_version"]
    with pytest.raises(ContractPinError, match="dispatch digest mismatch"):
        verify_branch(widened, "dispatch")

    dropped = copy.deepcopy(contract)
    del dropped["else"]
    with pytest.raises(ContractPinError, match="missing top-level routing keys"):
        branch_digest(dropped, "dispatch")


def test_each_consumer_verifies_its_branch_and_the_routing(contract) -> None:
    assert ENFORCED_PINS == {
        "document": ("document", "dispatch"),
        "entity": ("entity", "dispatch"),
    }
    assert set(verify_contract(contract, "document")) == {"document", "dispatch"}
    assert set(verify_contract(contract, "entity")) == {"entity", "dispatch"}
    with pytest.raises(ContractPinError, match="unknown contract consumer"):
        verify_contract(contract, "dispatch")


def test_branches_are_disjoint_so_neither_pin_can_move_the_other(contract) -> None:
    """The property the split buys. If these overlap, per-branch pinning is a lie."""
    document = set(branch_closure(contract, "document"))
    entity = set(branch_closure(contract, "entity"))
    assert document == {"legacy_document_record"}
    assert "entity_projection_record" in entity and len(entity) == 13
    assert document & entity == set()


# --- one test per branch: a real change to that branch is refused --------------


def test_document_branch_change_is_refused(contract) -> None:
    mutated = copy.deepcopy(contract)
    mutated["$defs"]["legacy_document_record"]["required"].append("invented_field")
    with pytest.raises(ContractPinError) as excinfo:
        verify_branch(mutated, "document")
    message = str(excinfo.value)
    assert "document digest mismatch" in message
    assert PINNED_BRANCH_COMMIT["document"] in message
    # The other branch is untouched and still passes.
    assert verify_branch(mutated, "entity") == ENTITY_BRANCH_SHA256


def test_entity_branch_change_is_refused(contract) -> None:
    mutated = copy.deepcopy(contract)
    mutated["$defs"]["entity_relationship"]["properties"]["relationship_type"]["enum"].append(
        "action_similar_to_provision"
    )
    with pytest.raises(ContractPinError) as excinfo:
        verify_branch(mutated, "entity")
    message = str(excinfo.value)
    assert "entity digest mismatch" in message
    # A document-branch consumer is unaffected by entity-branch work.
    assert verify_branch(mutated, "document") == DOCUMENT_BRANCH_SHA256


def test_missing_branch_and_malformed_contract_are_refused(contract, tmp_path) -> None:
    stripped = copy.deepcopy(contract)
    del stripped["$defs"]["entity_projection_envelope"]
    with pytest.raises(ContractPinError, match="missing .defs.entity_projection_envelope"):
        branch_digest(stripped, "entity")
    with pytest.raises(ContractPinError, match="unknown contract branch"):
        branch_digest(contract, "relationship")
    with pytest.raises(ContractPinError, match="no .defs"):
        branch_digest({"title": "not a contract"}, "document")
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    with pytest.raises(ContractPinError, match="must be a JSON object"):
        load_contract(bad)
    worse = tmp_path / "worse.json"
    worse.write_text("{not json")
    with pytest.raises(ContractPinError, match="not valid JSON"):
        load_contract(worse)


def test_remote_refs_are_not_followed(contract) -> None:
    """The KS-600 payload contracts carry their own pins; this digest must not
    silently claim to cover them."""
    entity = branch_closure(contract, "entity")
    blob = json.dumps(entity)
    assert "https://statecivics.ai/contracts/civic-impact/provision-reference.schema.json" in blob
    assert "provision_reference_logical_id" in blob  # local target def is included
    assert set(entity) == set(branch_closure(contract, "entity"))


# --- the declaration must be the thing that is enforced -----------------------

REPO = Path(__file__).resolve().parents[1]
SOURCE_PACKAGES = (
    REPO / "instances/ks-state-civics/vector-stores/kansas-fiscal-documents/sources/statecivics-fiscal-ledger",
    REPO / "instances/ks-state-civics/vector-stores/kansas-statutes/sources/statecivics-statute-ledger",
)


@pytest.mark.parametrize("package", SOURCE_PACKAGES, ids=lambda p: p.parent.parent.parent.name)
def test_declared_pin_matches_the_enforced_constants(package: Path) -> None:
    """The previous pin drifted because the declaration and the code were
    unrelated. They are now the same numbers, and this fails if they diverge."""
    lock = json.loads((package / "source.lock.json").read_text())
    pin = lock["producer"]["contractPin"]
    assert "contractSha256" not in lock["producer"]
    assert "pinnedCommit" not in pin, "a single commit cannot cover three pins"
    assert pin["documentBranchCommit"] == PINNED_BRANCH_COMMIT["document"]
    assert pin["entityBranchCommit"] == PINNED_BRANCH_COMMIT["entity"]
    assert pin["documentBranchSha256"] == DOCUMENT_BRANCH_SHA256
    assert pin["entityBranchSha256"] == ENTITY_BRANCH_SHA256
    assert pin["dispatchCommit"] == PINNED_BRANCH_COMMIT["dispatch"]
    assert pin["dispatchSha256"] == DISPATCH_SHA256
    assert "documentBranchSemanticSha256" not in pin
    assert "entityBranchSemanticSha256" not in pin

    superseded = pin["supersededEntityBranch"]
    assert (("entity", superseded["commit"], superseded["sha256"])
            in SUPERSEDED_BRANCH_SHA256)

    text = (package / "source.yaml").read_text()
    assert "contractSha256:" not in text
    # R-P4. source.yaml is the human-authored file; a single pinnedCommit there
    # silently reasserts that one commit covers all three pins.
    assert "pinnedCommit" not in text
    for value in (
        PINNED_BRANCH_COMMIT["document"],
        PINNED_BRANCH_COMMIT["entity"],
        PINNED_BRANCH_COMMIT["dispatch"],
        DOCUMENT_BRANCH_SHA256,
        ENTITY_BRANCH_SHA256,
        DISPATCH_SHA256,
    ):
        assert value in text
    assert "semanticSha256" not in text

    # R-P1: BOTH real entrypoints must be declared as enforcing.
    for entrypoint in ("scripts/release/kansas-fiscal-document-ingest.py --contract-schema",
                       "scripts/release/kansas-statute-rollout.py --contract-schema"):
        assert entrypoint in text
        assert entrypoint in pin["enforcedAt"]


@pytest.mark.parametrize("package", SOURCE_PACKAGES, ids=lambda p: p.parent.parent.parent.name)
def test_superseded_whole_file_digest_is_kept_as_a_commit_digest_pair(package: Path) -> None:
    """The historical number stays recorded, but only with the commit that makes
    it checkable; a bare digest is what misled in the first place."""
    superseded = json.loads((package / "source.lock.json").read_text())["producer"]["contractPin"]["supersededWholeFile"]
    assert superseded["commit"] == "b3f5c09170c66453097bcd4fb44c6eb2b9031f39"
    assert superseded["sha256"] == "78a3de138cdb534831df034bc66f6a6a2bf7ec3f5d6d573efedf2b50d7a7f32b"
    assert "git show" in superseded["readWith"]


# --- the historical audits stay true -----------------------------------------

HISTORICAL_WHOLE_FILE = {
    "contracts/civic-impact/retrieval-export-record.schema.json":
        "78a3de138cdb534831df034bc66f6a6a2bf7ec3f5d6d573efedf2b50d7a7f32b",
    "contracts/civic-impact/source-artifact.schema.json":
        "f0fdefbe737a320076e848bf840596b290c052a7c6a7e961d6bd51c10d759f65",
}
HISTORICAL_COMMIT = "b3f5c09170c66453097bcd4fb44c6eb2b9031f39"
AUDIT = REPO / ".tranche/statecivics-semantic-graph/aligned/statute-real-export-audit.md"


def statecivics_repo() -> Path:
    """R-P5. The gate sets SVS_STATECIVICS_REPO. Unset is a FAILURE, never a
    skip: skipping is how the one check that the historical (commit, digest)
    pairs are still true would evaporate on CI while still reporting green."""
    raw = os.environ.get("SVS_STATECIVICS_REPO")
    if not raw:
        pytest.fail(
            "SVS_STATECIVICS_REPO is unset; the historical contract pairs cannot be "
            "verified. Set it to the StateCivics checkout -- do not skip this test."
        )
    repo = Path(raw)
    if not (repo / ".git").exists():
        pytest.fail(f"SVS_STATECIVICS_REPO={raw} is not a git checkout")
    return repo


def test_audit_records_its_digests_as_commit_digest_pairs() -> None:
    """A bare digest silently stopped being true. The pair cannot."""
    text = AUDIT.read_text()
    assert HISTORICAL_COMMIT in text
    for digest in HISTORICAL_WHOLE_FILE.values():
        assert digest in text
    assert "git" in text and "show" in text
    assert "WORKTREE-PATH-PROVENANCE" in text


def test_historical_digests_are_reproducible_at_their_recorded_commit() -> None:
    """Re-derive the audit's numbers from git, not from a mutable worktree."""
    import hashlib
    import subprocess

    UPSTREAM = statecivics_repo()

    for path, expected in HISTORICAL_WHOLE_FILE.items():
        blob = subprocess.run(
            ["git", "-C", str(UPSTREAM), "show", f"{HISTORICAL_COMMIT}:{path}"],
            capture_output=True, check=True,
        ).stdout
        assert hashlib.sha256(blob).hexdigest() == expected, path

    # The same read against the working tree is exactly what went stale.
    current = (UPSTREAM / "contracts/civic-impact/retrieval-export-record.schema.json").read_bytes()
    assert hashlib.sha256(current).hexdigest() != HISTORICAL_WHOLE_FILE[
        "contracts/civic-impact/retrieval-export-record.schema.json"
    ]


def test_every_pinned_digest_travels_with_its_commit(contract) -> None:
    """A digest without its commit is how 78a3de13... misled two people."""
    assert set(PINNED_BRANCH_COMMIT) == {"document", "entity", "dispatch"}
    for branch, commit in PINNED_BRANCH_COMMIT.items():
        assert len(commit) == 40 and int(commit, 16) >= 0
    assert PINNED_CONTRACT_COMMIT == PINNED_BRANCH_COMMIT["document"]
    # The pinned commit must be the one the fixture actually came from.
    assert branch_digests(contract) == {
        "document": DOCUMENT_BRANCH_SHA256,
        "entity": ENTITY_BRANCH_SHA256,
        "dispatch": DISPATCH_SHA256,
    }


def test_superseded_entity_pin_is_kept_as_a_commit_digest_pair() -> None:
    assert SUPERSEDED_BRANCH_SHA256 == (
        ("entity", "e94a894e6f66fdd7eb6b798e35b3ebe7a2ae266a",
         "da242fd879b3c124449b6c1ddead558db64d8f0427ade638bf596c8fd1d9f17e"),
    )
    live = {DOCUMENT_BRANCH_SHA256, ENTITY_BRANCH_SHA256, DISPATCH_SHA256}
    for _branch, _commit, digest in SUPERSEDED_BRANCH_SHA256:
        assert digest not in live, "a superseded digest is still pinned live"
