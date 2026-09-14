"""Per-branch digests of the StateCivics retrieval-export contract.

The contract dispatches on tag presence: an untagged record is a legacy
document record, a tagged one is an entity projection.  The two branches are
independently versioned in practice, so a whole-file digest is the wrong pin --
it goes stale the moment the other branch changes, and a stale pin that nothing
reads is indistinguishable from no pin at all.

Three subtrees are pinned and all three are enforced:

``document``
    ``$defs.legacy_document_record`` and everything it reaches.
``entity``
    ``$defs.entity_projection_envelope`` and everything it reaches.
``dispatch``
    the top-level ``if``/``then``/``else`` routing predicate.  A consumer of one
    branch depends on the routing that sends a record *to* that branch, so a
    change to routing alone must refuse even when both branch subtrees are
    untouched.

Each digest covers exactly its own subtree, so a document-branch consumer is
unaffected by entity-branch work and vice versa.  Nothing here fetches, parses
or trusts a remote contract: the caller hands over the bytes it is about to
rely on.

There is deliberately no "semantic" or annotation-stripped digest.  An earlier
revision of this module had one, and it was wrong: JSON Schema property names
live in the same namespace as annotation keywords, so stripping keys named
``description`` or ``title`` also strips the real properties
``legacy_document_record.properties.title`` and
``entity_projection_record.properties.description``.  Tightening or deleting
either -- a genuine constraint change on an enforced branch -- was reported as
"annotation-only drift" with an unchanged digest.  Telling an operator that a
constraint change is only prose is the same defect class this module exists to
remove, so the literal digest is the whole ruling.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: ``$defs``-rooted subtrees, keyed by pin name.  ``$defs`` entry -> pin.
BRANCH_ROOTS: dict[str, str] = {
    "document": "legacy_document_record",
    "entity": "entity_projection_envelope",
}

#: The top-level keys that decide which branch a record is validated against.
DISPATCH_KEYS: tuple[str, ...] = ("if", "then", "else")

#: Every pin name, in report order.
PIN_NAMES: tuple[str, ...] = ("document", "entity", "dispatch")

#: A digest is meaningless without the commit it was computed from -- that is
#: precisely how the superseded whole-file ``78a3de13...`` misled two people in
#: one day.  Every pinned digest below travels with its commit, and the pins
#: carry their commits separately because they move separately.
#:
#: Each entry is the commit at which THAT BRANCH last changed, which is not the
#: same thing as the commit the fixture came from.  Recompute with
#: :func:`branch_digests`; never hand-edit.
#:
#: ``document`` and ``dispatch`` are still at 314beafe (KS-650 B1 + B1.1,
#: landed_by 121083e9) because KS-650 B1.3 touched neither: its whole diff is
#: inside ``$defs.entity_eligibility``.  ``entity`` moved to 24c9d3de, where the
#: status enum gained ``candidate``.  This is the arrangement the module was
#: built for and the first time it has actually occurred, so the three commits
#: no longer agree -- which is why nothing below collapses them into one.
PINNED_BRANCH_COMMIT: dict[str, str] = {
    "document": "314beafe4f7905f06a2edb7828b0ea8b2976266c",
    "entity": "24c9d3ded35405054094a1280c7ea1f074fad5d5",
    "dispatch": "314beafe4f7905f06a2edb7828b0ea8b2976266c",
}

#: The commit the COMMITTED FIXTURE's bytes came from.  A separate fact from
#: any branch pin: the fixture is one whole file, and a file carries every
#: branch at whatever revision that file has.  It is the commit a byte-identity
#: check must read, and the only one.
#:
#: There was a ``PINNED_CONTRACT_COMMIT`` here, defined as the document branch's
#: commit and documented as "valid only while the three agree".  They stopped
#: agreeing at 24c9d3de, so it is GONE rather than left to answer with the
#: document branch's commit while the fixture is a later file.  A constant whose
#: stated precondition has failed is precisely the superseded whole-file
#: ``78a3de13...`` defect, which is what this module exists to not repeat.
FIXTURE_CONTRACT_COMMIT = "24c9d3ded35405054094a1280c7ea1f074fad5d5"

#: Pins that point at upstream work which has NOT yet merged to ``main``.
#:
#: EMPTY, and that is the outcome the mechanism was built for. ``24c9d3de`` was
#: recorded here while it lived only on ``ks-600-a2-1-hb2513-slice``; the
#: provenance check still required it to be an ancestor of THAT branch, so it
#: could never have been a dangling object, and a test failed the moment the
#: branch merged. It did fail, with "HAS merged to StateCivics main, so the
#: provisional entry ... is stale. Delete it", and this is that deletion.
#:
#: Keep it empty. An entry that outlives its branch is indistinguishable from a
#: pin that was never checked.
PROVISIONAL_BRANCH_COMMIT: dict[str, str] = {}

DOCUMENT_BRANCH_SHA256 = "d3a7212a4873a2f375d451e74ab4d5f11a56ff50bbbeb5a162dae1f8640807e2"
ENTITY_BRANCH_SHA256 = "52fd9ee50585c805664a39f5548ba04d00c0ac1a16c4095e2149d06451817058"
DISPATCH_SHA256 = "03dc178429d04275f7b49a6d4ab9e05ee56bc970a31de78268942eb3de3b7940"

PINNED_BRANCH_SHA256: dict[str, str] = {
    "document": DOCUMENT_BRANCH_SHA256,
    "entity": ENTITY_BRANCH_SHA256,
    "dispatch": DISPATCH_SHA256,
}

#: Which pins each real ingestion entrypoint must verify.  A consumer verifies
#: the branch it reads plus the routing that delivers records to it; it must not
#: verify the other branch, or unrelated upstream work would block it.
ENFORCED_PINS: dict[str, tuple[str, ...]] = {
    "document": ("document", "dispatch"),
    "entity": ("entity", "dispatch"),
}

#: Superseded pins, kept as (name, commit, digest) triples so they stay true
#: rather than quietly ceasing to be.  Each is re-derivable with
#: ``git show <commit>:<path>``.
#:
#: The entity branch has now moved twice, and the document branch not at all.
#:
#: e94a894e -> 1de6312e was PROSE ONLY: StateCivics rewrote two entity-branch
#: descriptions.  A whole-file hash could not have told that apart from a
#: constraint change, and that distinction is why this module pins per branch.
#: The contract file was byte-identical from 1de6312e through 314beafe.
#:
#: 314beafe -> 24c9d3de is a real CONSTRAINT change, and the first one this
#: mechanism has had to carry: KS-650 B1.3 widened
#: ``entity_eligibility.properties.status.enum`` from ``[reviewed, published]``
#: to ``[candidate, reviewed, published]`` and rewrote the two descriptions
#: around it.  The whole diff is inside ``$defs.entity_eligibility``, so the
#: document and dispatch digests are byte-for-byte what they were -- which is
#: the property per-branch pinning was built to deliver, demonstrated rather
#: than argued.  Re-derived here from ``git show 24c9d3de:<contract>`` with
#: :func:`branch_digests`, not copied from upstream's published value.
SUPERSEDED_BRANCH_SHA256: tuple[tuple[str, str, str], ...] = (
    ("entity", "e94a894e6f66fdd7eb6b798e35b3ebe7a2ae266a",
     "da242fd879b3c124449b6c1ddead558db64d8f0427ade638bf596c8fd1d9f17e"),
    ("entity", "314beafe4f7905f06a2edb7828b0ea8b2976266c",
     "d5248a5452389c40a55c844f2e455343b2e24ce3dedff9a9ecac0752eeb28734"),
)

_LOCAL_REF = "#/$defs/"


class ContractPinError(ValueError):
    """The handed contract is not the pinned contract for this pin."""


def canonical_json(value: Any) -> str:
    """Sorted keys, no whitespace -- the repository's canonical JSON form."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _local_refs(node: Any, found: set[str]) -> set[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith(_LOCAL_REF):
                found.add(value[len(_LOCAL_REF):])
            else:
                _local_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _local_refs(value, found)
    return found


def dispatch_subtree(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the top-level routing predicate.

    Every key must be present: a contract that has lost its ``else`` is not a
    contract this consumer can reason about, and silently digesting a smaller
    object would make the pin agree with it.
    """
    missing = [key for key in DISPATCH_KEYS if key not in schema]
    if missing:
        raise ContractPinError(f"contract is missing top-level routing keys: {', '.join(missing)}")
    return {key: schema[key] for key in DISPATCH_KEYS}


def branch_closure(schema: dict[str, Any], branch: str) -> dict[str, Any]:
    """Return every ``$defs`` entry reachable from ``branch``'s dispatch target.

    Reachability is by local ``$ref`` only.  A remote ``$ref`` is deliberately
    not followed: it names a separate contract with its own pin, and chasing it
    here would silently widen what this digest claims to cover.
    """
    if branch not in BRANCH_ROOTS:
        raise ContractPinError(f"unknown contract branch {branch!r}")
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        raise ContractPinError("contract has no $defs object")
    pending = [BRANCH_ROOTS[branch]]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        if name not in defs:
            raise ContractPinError(f"contract is missing $defs.{name}")
        seen.add(name)
        pending.extend(_local_refs(defs[name], set()))
    return {name: defs[name] for name in sorted(seen)}


def pin_subtree(schema: dict[str, Any], name: str) -> dict[str, Any]:
    """The exact object a pin digests."""
    if name == "dispatch":
        return dispatch_subtree(schema)
    return branch_closure(schema, name)


def branch_digest(schema: dict[str, Any], name: str) -> str:
    """SHA-256 over the canonical JSON of one pin's subtree."""
    return hashlib.sha256(canonical_json(pin_subtree(schema, name)).encode("utf-8")).hexdigest()


def branch_digests(schema: dict[str, Any]) -> dict[str, str]:
    """All three digests, for reporting and for refreshing the pin."""
    return {name: branch_digest(schema, name) for name in PIN_NAMES}


def verify_branch(schema: dict[str, Any], name: str, *, expected: str | None = None) -> str:
    """Refuse unless ``name``'s subtree of ``schema`` matches its pinned digest."""
    if name not in PINNED_BRANCH_SHA256:
        raise ContractPinError(f"unknown contract pin {name!r}")
    want = PINNED_BRANCH_SHA256[name] if expected is None else expected
    got = branch_digest(schema, name)
    if got != want:
        raise ContractPinError(
            f"StateCivics contract {name} digest mismatch: expected {want}, computed "
            f"{got}. The {name} pin is at StateCivics commit "
            f"{PINNED_BRANCH_COMMIT[name]}. Re-pin deliberately, naming the commit "
            f"you re-pinned from, or hand over the pinned revision."
        )
    return got


def verify_contract(schema: dict[str, Any], consumer: str) -> dict[str, str]:
    """Verify every pin a consumer depends on.

    ``consumer`` is ``"document"`` or ``"entity"`` -- the branch of records the
    caller is about to ingest.  Routing is always verified alongside it.
    """
    if consumer not in ENFORCED_PINS:
        raise ContractPinError(f"unknown contract consumer {consumer!r}")
    return {name: verify_branch(schema, name) for name in ENFORCED_PINS[consumer]}


def load_contract(path: Any) -> dict[str, Any]:
    """Read a contract file as JSON, refusing anything that is not an object."""
    from pathlib import Path

    raw = Path(path).read_bytes()
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractPinError(f"{path}: contract is not valid JSON") from exc
    if not isinstance(schema, dict):
        raise ContractPinError(f"{path}: contract must be a JSON object")
    return schema
