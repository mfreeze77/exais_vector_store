"""Per-branch digests of the StateCivics retrieval-export contract.

The contract dispatches on tag presence: an untagged record is a legacy
document record, a tagged one is an entity projection.  The two branches are
independently versioned in practice, so a whole-file digest is the wrong pin --
it goes stale the moment the other branch changes, and a stale pin that nothing
reads is indistinguishable from no pin at all.

Each branch digest therefore covers exactly the ``$defs`` subtree reachable
from that branch's dispatch target, so a document-branch consumer is unaffected
by entity-branch work and vice versa.  Nothing here fetches, parses or trusts a
remote contract: the caller hands over the bytes it is about to rely on.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Dispatch targets, keyed by branch name.  ``$defs`` entry -> branch.
BRANCH_ROOTS: dict[str, str] = {
    "document": "legacy_document_record",
    "entity": "entity_projection_envelope",
}

#: A digest is meaningless without the commit it was computed from -- that is
#: precisely how the superseded whole-file ``78a3de13...`` misled two people in
#: one day.  Every pinned digest below therefore travels with its commit, and
#: the branches carry their commits separately because they move separately.
#:
#: Computed from StateCivics main at 314beafe (KS-650 B1 + B1.1, landed_by
#: 121083e9).  Recompute with :func:`branch_digests`; never hand-edit.
PINNED_BRANCH_COMMIT: dict[str, str] = {
    "document": "314beafe4f7905f06a2edb7828b0ea8b2976266c",
    "entity": "314beafe4f7905f06a2edb7828b0ea8b2976266c",
}

#: Both branches happen to be pinned at the same commit today.  Prefer
#: ``PINNED_BRANCH_COMMIT[branch]``; this stays only for messages that name one
#: contract revision, and is valid only while the two agree.
PINNED_CONTRACT_COMMIT = PINNED_BRANCH_COMMIT["document"]

DOCUMENT_BRANCH_SHA256 = "d3a7212a4873a2f375d451e74ab4d5f11a56ff50bbbeb5a162dae1f8640807e2"
ENTITY_BRANCH_SHA256 = "d5248a5452389c40a55c844f2e455343b2e24ce3dedff9a9ecac0752eeb28734"

PINNED_BRANCH_SHA256: dict[str, str] = {
    "document": DOCUMENT_BRANCH_SHA256,
    "entity": ENTITY_BRANCH_SHA256,
}

#: The same subtrees with annotation-only keywords removed.  A rewritten
#: ``description`` moves the digest above but not this one, so the pair tells an
#: operator whether a refusal is prose churn or a real contract change.
DOCUMENT_BRANCH_SEMANTIC_SHA256 = "e75f616af11b97b28e59cb059cdaa55e1763f52f5b0353e6e8d7fa8cfaacbf45"
ENTITY_BRANCH_SEMANTIC_SHA256 = "3ad8f594bae3426944725c2946325c23f32bd8d4a81d201913b080c37ce29bae"

PINNED_BRANCH_SEMANTIC_SHA256: dict[str, str] = {
    "document": DOCUMENT_BRANCH_SEMANTIC_SHA256,
    "entity": ENTITY_BRANCH_SEMANTIC_SHA256,
}

#: Superseded pins, kept as (commit, digest) pairs so they stay true rather than
#: quietly ceasing to be.  Each is re-derivable with ``git show <commit>:<path>``.
#:
#: The entity branch moved once, and for prose only: between e94a894e and
#: 1de6312e StateCivics rewrote two entity-branch descriptions, which moved the
#: annotated entity digest and left the semantic entity digest and BOTH document
#: digests untouched.  A whole-file hash could not have told those apart; that
#: distinction is the whole reason this module exists.  The contract file has
#: been byte-identical from 1de6312e through 314beafe.
SUPERSEDED_BRANCH_SHA256: tuple[tuple[str, str, str], ...] = (
    ("entity", "e94a894e6f66fdd7eb6b798e35b3ebe7a2ae266a",
     "da242fd879b3c124449b6c1ddead558db64d8f0427ade638bf596c8fd1d9f17e"),
)

#: Keywords that annotate without constraining.  Draft 2020-12 treats these as
#: carrying no validation effect.
ANNOTATION_KEYWORDS = frozenset(
    {"description", "$comment", "title", "examples", "deprecated", "readOnly", "writeOnly"}
)

_LOCAL_REF = "#/$defs/"


class ContractPinError(ValueError):
    """The handed contract is not the pinned contract for this branch."""


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


def strip_annotations(node: Any) -> Any:
    """Drop keywords that annotate without constraining."""
    if isinstance(node, dict):
        return {k: strip_annotations(v) for k, v in node.items() if k not in ANNOTATION_KEYWORDS}
    if isinstance(node, list):
        return [strip_annotations(v) for v in node]
    return node


def branch_digest(schema: dict[str, Any], branch: str, *, semantic: bool = False) -> str:
    """SHA-256 over the canonical JSON of one branch's reachable subtree."""
    closure = branch_closure(schema, branch)
    if semantic:
        closure = strip_annotations(closure)
    return hashlib.sha256(canonical_json(closure).encode("utf-8")).hexdigest()


def branch_digests(schema: dict[str, Any], *, semantic: bool = False) -> dict[str, str]:
    """Both branch digests, for reporting and for refreshing the pin."""
    return {branch: branch_digest(schema, branch, semantic=semantic) for branch in BRANCH_ROOTS}


def verify_branch(schema: dict[str, Any], branch: str, *, expected: str | None = None) -> str:
    """Refuse unless ``branch`` of ``schema`` matches its pinned digest.

    Only the named branch is checked.  That is the point: document ingestion
    must keep working across entity-branch releases, and entity ingestion must
    keep working across document-branch releases, but neither may silently
    accept a changed contract for the branch it actually reads.
    """
    want = PINNED_BRANCH_SHA256[branch] if expected is None else expected
    got = branch_digest(schema, branch)
    if got == want:
        return got
    semantic_got = branch_digest(schema, branch, semantic=True)
    semantic_want = PINNED_BRANCH_SEMANTIC_SHA256[branch]
    kind = (
        "annotation-only drift (the validating keywords are unchanged)"
        if semantic_got == semantic_want
        else "a CONSTRAINT change (the validating keywords differ)"
    )
    raise ContractPinError(
        f"StateCivics contract {branch} branch digest mismatch: expected {want}, "
        f"computed {got}. This is {kind}. The {branch} branch is pinned at "
        f"StateCivics commit {PINNED_BRANCH_COMMIT[branch]}; semantic digest "
        f"expected {semantic_want}, computed {semantic_got}. Re-pin deliberately "
        f"or hand over the pinned revision."
    )


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
