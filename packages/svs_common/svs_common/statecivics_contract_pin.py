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

#: Digests computed from StateCivics at commit e94a894e (KS-650 slice B1).
#: Recompute with :func:`branch_digests`; never hand-edit.
PINNED_CONTRACT_COMMIT = "e94a894e6f66fdd7eb6b798e35b3ebe7a2ae266a"
DOCUMENT_BRANCH_SHA256 = "d3a7212a4873a2f375d451e74ab4d5f11a56ff50bbbeb5a162dae1f8640807e2"
ENTITY_BRANCH_SHA256 = "da242fd879b3c124449b6c1ddead558db64d8f0427ade638bf596c8fd1d9f17e"

PINNED_BRANCH_SHA256: dict[str, str] = {
    "document": DOCUMENT_BRANCH_SHA256,
    "entity": ENTITY_BRANCH_SHA256,
}

#: The same subtrees with annotation-only keywords removed.  A rewritten
#: ``description`` moves the digest above but not this one, so the pair tells an
#: operator whether a refusal is prose churn or a real contract change.  This is
#: not hypothetical: StateCivics 1de6312e rewrote two entity-branch descriptions
#: hours after B1 landed, moving ENTITY_BRANCH_SHA256 and nothing else.
DOCUMENT_BRANCH_SEMANTIC_SHA256 = "e75f616af11b97b28e59cb059cdaa55e1763f52f5b0353e6e8d7fa8cfaacbf45"
ENTITY_BRANCH_SEMANTIC_SHA256 = "3ad8f594bae3426944725c2946325c23f32bd8d4a81d201913b080c37ce29bae"

PINNED_BRANCH_SEMANTIC_SHA256: dict[str, str] = {
    "document": DOCUMENT_BRANCH_SEMANTIC_SHA256,
    "entity": ENTITY_BRANCH_SEMANTIC_SHA256,
}

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
        f"computed {got}. This is {kind}. Pinned contract commit "
        f"{PINNED_CONTRACT_COMMIT}; semantic digest expected {semantic_want}, "
        f"computed {semantic_got}. Re-pin deliberately or hand over the pinned revision."
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
