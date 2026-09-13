"""Route a StateCivics retrieval-export record to the branch the CONTRACT names.

WAVE-134, lane B. This is a *reader*, not an ingestion path: nothing here
embeds, uploads, calls an API or writes to a store. It turns a mixed JSONL
manifest into two separated, branch-validated groups so a caller physically
cannot hand an entity projection to the document ingest path.

Why a second reader rather than a change to ``load_manifest``
------------------------------------------------------------
``scripts/release/kansas-fiscal-document-ingest.py`` is the DOCUMENT consumer.
It verifies ``ENFORCED_PINS["document"]`` and routes every line down the
document path unconditionally -- ``record_kind`` appears nowhere in it. Making
it also read entity records would make it verify a pin it does not consume and
would put a second call site of ``load_manifest`` under
``test_every_load_manifest_caller_enforces_the_pin``'s discovery walk. Neither
is wanted here, so this module reads the manifest itself and verifies exactly
the pins the records it actually saw require.

Three properties this module exists to hold
-------------------------------------------
**The dispatch is read out of the contract, never guessed.** The contract
dispatches at its ROOT: ``if {"required": [...]} / then <entity> / else
<document>``. :func:`dispatch_rule` reads that object -- the tag key, and which
``$defs`` entry each arm targets -- from the schema the caller handed over, and
maps each arm back to its pin name through
:data:`statecivics_contract_pin.BRANCH_ROOTS`. The module-level constant
:data:`EXPECTED_DISPATCH_REQUIRED` is a cross-check, not the source: the rule is
derived, then asserted against it, so a contract that starts dispatching on a
different key fails loudly instead of being silently mis-routed. (The pin would
also catch it -- ``DISPATCH_SHA256`` covers exactly this object -- but a digest
mismatch says "something moved", and this says which thing.)

**A record is judged against ONE branch and refused by name.** There is no
"try the other branch" fallback and no relaxation of the document branch to let
entity records through. Relaxing it is the defect class the pin exists to stop:
the document branch's ``additionalProperties: false`` is what keeps a tagged
record from falling into it even if the dispatch were deleted, which the
upstream contract says in as many words.

**Entity output is separable at the call site.** :class:`AdaptedManifest`
carries ``document_records`` and ``entity_records`` as distinct tuples -- there
is no combined accessor to pass by accident -- and :func:`entity_collection_name`
refuses to name a collection for entity points when it would be the same
collection the document points land in. ``QdrantAdapter.collection_name`` takes
``business_instance_id`` and ``embedding_profile_id`` and NOT ``vector_store_id``,
so a new vector store on the same instance and profile resolves to the same
Qdrant collection. A distinct embedding profile is the only thing that separates
them, and choosing one is an owner decision, so this function takes both profile
ids from the caller and refuses the collision rather than inventing a profile.

Validation scope
----------------
There is no ``jsonschema`` in this repository -- not installed, not in any
``requirements.txt`` -- so :func:`validate` is a bounded evaluator for exactly
the keyword vocabulary the pinned contract uses. It is bounded in the way that
matters: :data:`SUPPORTED_KEYWORDS` is closed and an unrecognised keyword raises
:class:`UnsupportedContractKeyword` rather than being ignored. A validator that
skips what it does not understand reports "valid" for constraints it never
checked, which is worse than no validator at all.

Remote ``$ref`` is NOT followed, exactly as
``statecivics_contract_pin.branch_closure`` does not follow it: a remote ref
names a separate contract with its own pin, and chasing it here would silently
widen what this module claims to have checked. Unfollowed refs are not hidden
either -- every one encountered is reported in
:attr:`RecordValidation.unvalidated_remote_refs`, so "the KS-600 entity payload
was not validated here" is a value a caller and a test can read, not an omission
someone has to notice.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .statecivics_contract_pin import (
    BRANCH_ROOTS,
    DISPATCH_KEYS,
    ContractPinError,
    dispatch_subtree,
    load_contract,
    verify_branch,
)

__all__ = [
    "EXPECTED_DISPATCH_REQUIRED",
    "AdaptedManifest",
    "DispatchRule",
    "EntityCollectionCollision",
    "RecordBranchError",
    "RecordValidation",
    "UnsupportedContractKeyword",
    "adapt_manifest",
    "adapt_records",
    "classify_record",
    "dispatch_rule",
    "entity_collection_name",
    "validate",
]

#: Cross-check for the derived dispatch, NOT the source of it. See the module
#: docstring: :func:`dispatch_rule` reads the contract's own root ``if`` and
#: then asserts it equals this, so a contract that dispatches on some other key
#: is refused by name instead of quietly routing every record one way.
EXPECTED_DISPATCH_REQUIRED: tuple[str, ...] = ("record_kind",)

#: Every JSON Schema keyword :func:`validate` implements. Closed on purpose.
SUPPORTED_KEYWORDS: frozenset[str] = frozenset(
    {
        "$ref",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "enum",
        "format",
        "if",
        "then",
        "else",
        "items",
        "maxItems",
        "maxLength",
        "minItems",
        "minLength",
        "minimum",
        "not",
        "oneOf",
        "pattern",
        "properties",
        "required",
        "type",
        "uniqueItems",
    }
)

#: Keywords that carry no assertion. Listed so they are *known* to be ignored
#: rather than falling through the unknown-keyword refusal.
ANNOTATION_KEYWORDS: frozenset[str] = frozenset(
    {"$comment", "$defs", "$id", "$schema", "default", "description", "examples", "title"}
)

_LOCAL_REF = "#/$defs/"

_FORMATS = {
    "date": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "date-time": re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"),
    "uri": re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:"),
}


class UnsupportedContractKeyword(ContractPinError):
    """The contract uses a keyword this evaluator does not implement.

    Raised rather than ignored. An ignored keyword is an unchecked constraint
    reported as a pass.
    """


class RecordBranchError(ValueError):
    """A record failed the branch the contract's own dispatch sent it to.

    The message always names the branch and why, because "invalid record" on a
    two-branch contract is the failure mode this module was written to remove:
    an entity record judged against the document branch fails with a missing
    ``logical_document_id``, which reads as a data error and is a shape error.
    """


class EntityCollectionCollision(ValueError):
    """Entity points would land in the document/statute collection."""


@dataclass(frozen=True, slots=True)
class DispatchRule:
    """The contract's root routing predicate, as data.

    ``tag_keys``
        The keys whose presence selects the tagged arm -- read from the root
        ``if.required``.
    ``present_pin`` / ``absent_pin``
        The pin name (``"entity"`` / ``"document"``) each arm resolves to, via
        the ``$defs`` entry the arm ``$ref``s and :data:`BRANCH_ROOTS`.
    """

    tag_keys: tuple[str, ...]
    present_pin: str
    absent_pin: str
    present_ref: str
    absent_ref: str


def _arm_ref(arm: Any, which: str) -> str:
    if not isinstance(arm, dict) or set(arm) - {"$ref", "description", "$comment"} or "$ref" not in arm:
        raise ContractPinError(
            f"contract root {which!r} is not a single local $ref; this adapter routes by "
            f"the contract's own dispatch and cannot interpret {which!r}={arm!r}"
        )
    ref = arm["$ref"]
    if not isinstance(ref, str) or not ref.startswith(_LOCAL_REF):
        raise ContractPinError(f"contract root {which!r} $ref is not a local $defs reference: {ref!r}")
    return ref[len(_LOCAL_REF) :]


def dispatch_rule(schema: dict[str, Any]) -> DispatchRule:
    """Derive the routing rule from the contract itself.

    Reuses :func:`statecivics_contract_pin.dispatch_subtree`, so the object read
    here is byte-for-byte the object ``DISPATCH_SHA256`` pins -- the rule and
    the pin cannot describe different things.
    """
    routing = dispatch_subtree(schema)
    predicate = routing["if"]
    if not isinstance(predicate, dict):
        raise ContractPinError("contract root 'if' is not an object")
    required = predicate.get("required")
    if not isinstance(required, list) or not required or not all(isinstance(k, str) for k in required):
        raise ContractPinError(
            f"contract root if.required is not a non-empty list of property names: {required!r}"
        )
    tag_keys = tuple(required)
    if tag_keys != EXPECTED_DISPATCH_REQUIRED:
        raise ContractPinError(
            f"contract dispatches on {list(tag_keys)}, not {list(EXPECTED_DISPATCH_REQUIRED)}. "
            "This adapter routes records by tag presence; re-derive the routing "
            "deliberately before ingesting against this contract."
        )
    if set(predicate) - {"type", "required", "description", "$comment"}:
        raise ContractPinError(
            f"contract root 'if' constrains more than property presence: {sorted(predicate)}. "
            "Presence-only routing is what this adapter implements."
        )
    present_ref = _arm_ref(routing["then"], "then")
    absent_ref = _arm_ref(routing["else"], "else")
    by_root = {root: pin for pin, root in BRANCH_ROOTS.items()}
    try:
        present_pin = by_root[present_ref]
        absent_pin = by_root[absent_ref]
    except KeyError as exc:
        raise ContractPinError(
            f"contract dispatch targets $defs.{exc.args[0]}, which is not a pinned branch root "
            f"({sorted(BRANCH_ROOTS.values())} cover {sorted(BRANCH_ROOTS.keys())})"
        ) from None
    return DispatchRule(
        tag_keys=tag_keys,
        present_pin=present_pin,
        absent_pin=absent_pin,
        present_ref=present_ref,
        absent_ref=absent_ref,
    )


class _TagGate(Mapping):
    """A view exposing ONLY the dispatch's tag keys.

    Mirrors StateCivics' ``entity_projection._Gate``: the classifier is wrapped
    in this before it looks at anything, so "the dispatch cannot read a payload
    field" holds by construction rather than by reviewer discipline. A record
    kind this code does not implement must be refused before any field it might
    have moved or retyped is touched.
    """

    __slots__ = ("_keys", "_values")

    def __init__(self, source: Mapping, keys: tuple[str, ...]) -> None:
        self._keys = keys
        self._values = {key: source.get(key, _MISSING) for key in keys}

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self):
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<missing>"


_MISSING = _Missing()


def classify_record(record: Mapping, rule: DispatchRule) -> str:
    """Return the pin name of the branch this record belongs to.

    Presence of every tag key selects the tagged arm; absence of all of them
    selects the untagged arm. A record carrying *some* of the tag keys matches
    neither arm of a presence predicate, so it is refused rather than assigned.
    """
    gate = _TagGate(record, rule.tag_keys)
    present = [key for key in rule.tag_keys if gate[key] is not _MISSING]
    if len(present) == len(rule.tag_keys):
        return rule.present_pin
    if not present:
        return rule.absent_pin
    missing = [key for key in rule.tag_keys if gate[key] is _MISSING]
    raise RecordBranchError(
        f"record carries {present} but not {missing}; the contract routes on the presence of "
        f"all of {list(rule.tag_keys)}, so this record matches neither the "
        f"{rule.present_pin} branch nor the {rule.absent_pin} branch"
    )


# --------------------------------------------------------------------------
# Bounded JSON Schema evaluation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordValidation:
    """What :func:`validate` concluded, including what it declined to check."""

    errors: tuple[str, ...]
    unvalidated_remote_refs: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _type_matches(value: Any, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "null":
        return value is None
    raise UnsupportedContractKeyword(f"unsupported JSON Schema type {name!r}")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _check_keywords(schema: dict[str, Any]) -> None:
    unknown = sorted(set(schema) - SUPPORTED_KEYWORDS - ANNOTATION_KEYWORDS)
    if unknown:
        raise UnsupportedContractKeyword(
            f"contract uses JSON Schema keyword(s) {unknown} that this evaluator does not "
            "implement. Refusing rather than ignoring them: an ignored keyword is an "
            "unchecked constraint reported as a pass."
        )


def _validate(
    value: Any,
    schema: Any,
    root: dict[str, Any],
    path: str,
    errors: list[str],
    remote: set[str],
) -> None:
    if schema is True:
        return
    if schema is False:
        errors.append(f"{path or '<record>'}: schema forbids any value here")
        return
    if not isinstance(schema, dict):
        raise UnsupportedContractKeyword(f"schema at {path!r} is neither an object nor a boolean")
    _check_keywords(schema)

    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref.startswith(_LOCAL_REF):
            name = ref[len(_LOCAL_REF) :]
            target = root.get("$defs", {}).get(name)
            if target is None:
                raise ContractPinError(f"contract is missing $defs.{name}")
            _validate(value, target, root, path, errors, remote)
        else:
            # Deliberately not followed. See the module docstring.
            remote.add(ref)

    if "type" in schema:
        names = schema["type"]
        names = [names] if isinstance(names, str) else list(names)
        if not any(_type_matches(value, name) for name in names):
            errors.append(f"{path or '<record>'}: expected type {names}, got {type(value).__name__}")
            return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path or '<record>'}: expected const {_canonical(schema['const'])}, got {_canonical(value)}")
    if "enum" in schema and not any(value == option for option in schema["enum"]):
        errors.append(f"{path or '<record>'}: {_canonical(value)} is not one of {_canonical(schema['enum'])}")

    if isinstance(value, str):
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{path or '<record>'}: {value!r} does not match {pattern!r}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path or '<record>'}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path or '<record>'}: longer than maxLength {schema['maxLength']}")
        fmt = schema.get("format")
        if isinstance(fmt, str):
            checker = _FORMATS.get(fmt)
            if checker is None:
                raise UnsupportedContractKeyword(f"contract uses unimplemented format {fmt!r}")
            if checker.match(value) is None:
                errors.append(f"{path or '<record>'}: {value!r} is not a valid {fmt}")

    # `bool` is a Python int but is not a JSON number, so it must not be
    # compared against a numeric bound.
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and "minimum" in schema
        and value < schema["minimum"]
    ):
        errors.append(f"{path or '<record>'}: below minimum {schema['minimum']}")

    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path or '<record>'}: missing required property {name!r}")
        properties = schema.get("properties", {})
        for name, subschema in properties.items():
            if name in value:
                _validate(value[name], subschema, root, f"{path}.{name}" if path else name, errors, remote)
        if "additionalProperties" in schema:
            extra = sorted(set(value) - set(properties))
            allowed = schema["additionalProperties"]
            if allowed is False:
                for name in extra:
                    errors.append(f"{path or '<record>'}: property {name!r} is not permitted here")
            else:
                for name in extra:
                    _validate(value[name], allowed, root, f"{path}.{name}" if path else name, errors, remote)

    if isinstance(value, list):
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(item, schema["items"], root, f"{path}[{index}]", errors, remote)
        if schema.get("uniqueItems") and len({_canonical(item) for item in value}) != len(value):
            errors.append(f"{path or '<record>'}: items are not unique")
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path or '<record>'}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path or '<record>'}: more than maxItems {schema['maxItems']}")

    for subschema in schema.get("allOf", []):
        _validate(value, subschema, root, path, errors, remote)

    if "anyOf" in schema:
        branches = [_probe(value, sub, root, path, remote) for sub in schema["anyOf"]]
        if not any(not found for found in branches):
            errors.append(f"{path or '<record>'}: matched none of the anyOf branches")
    if "oneOf" in schema:
        matched = [sub for sub in schema["oneOf"] if not _probe(value, sub, root, path, remote)]
        if len(matched) != 1:
            errors.append(f"{path or '<record>'}: matched {len(matched)} oneOf branches, expected exactly 1")
    if "not" in schema and not _probe(value, schema["not"], root, path, remote):
        errors.append(f"{path or '<record>'}: matched a schema it must not match")

    if "if" in schema:
        if not _probe(value, schema["if"], root, path, remote):
            if "then" in schema:
                _validate(value, schema["then"], root, path, errors, remote)
        elif "else" in schema:
            _validate(value, schema["else"], root, path, errors, remote)


def _probe(value: Any, schema: Any, root: dict[str, Any], path: str, remote: set[str]) -> list[str]:
    found: list[str] = []
    _validate(value, schema, root, path, found, remote)
    return found


def validate(record: Any, schema: dict[str, Any], branch_root: str) -> RecordValidation:
    """Validate ``record`` against ONE named ``$defs`` entry of ``schema``.

    ``branch_root`` is a ``$defs`` key -- the value the contract's own dispatch
    arm points at, resolved by :func:`dispatch_rule`. Nothing here re-decides
    which branch applies.
    """
    defs = schema.get("$defs")
    if not isinstance(defs, dict) or branch_root not in defs:
        raise ContractPinError(f"contract is missing $defs.{branch_root}")
    errors: list[str] = []
    remote: set[str] = set()
    _validate(record, defs[branch_root], schema, "", errors, remote)
    return RecordValidation(errors=tuple(errors), unvalidated_remote_refs=tuple(sorted(remote)))


# --------------------------------------------------------------------------
# Adaptation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdaptedManifest:
    """Branch-separated, branch-validated records.

    There is deliberately no combined ``records`` accessor. The whole point is
    that a caller holding this object must name which branch it wants, so an
    entity projection cannot reach a document code path by being in the same
    sequence as a document record.
    """

    document_records: tuple[dict[str, Any], ...]
    entity_records: tuple[dict[str, Any], ...]
    verified_pins: tuple[str, ...]
    unvalidated_remote_refs: tuple[str, ...]
    rule: DispatchRule


def adapt_records(
    lines: list[tuple[int, dict[str, Any]]],
    schema: dict[str, Any],
    *,
    source: str = "<records>",
) -> AdaptedManifest:
    """Classify, validate and separate already-parsed records."""
    rule = dispatch_rule(schema)
    pin_to_root = {rule.present_pin: rule.present_ref, rule.absent_pin: rule.absent_ref}
    verified: list[str] = []
    # Routing is always verified: a routing change alone can redirect a record
    # to the other branch while both branch subtrees stay byte-identical.
    verify_branch(schema, "dispatch")
    verified.append("dispatch")

    buckets: dict[str, list[dict[str, Any]]] = {rule.present_pin: [], rule.absent_pin: []}
    remote: set[str] = set()
    for line_number, record in lines:
        if not isinstance(record, dict):
            raise RecordBranchError(f"{source}:{line_number}: expected a JSON object")
        try:
            pin = classify_record(record, rule)
        except RecordBranchError as exc:
            raise RecordBranchError(f"{source}:{line_number}: {exc}") from None
        if pin not in verified:
            # Verify a branch pin only when a record of that branch actually
            # arrives, matching ENFORCED_PINS: a consumer must not be blocked
            # by drift on a branch it never reads.
            verify_branch(schema, pin)
            verified.append(pin)
        result = validate(record, schema, pin_to_root[pin])
        remote.update(result.unvalidated_remote_refs)
        if not result.ok:
            raise RecordBranchError(
                f"{source}:{line_number}: record was routed to the {pin} branch "
                f"($defs.{pin_to_root[pin]}) by the contract's dispatch on "
                f"{list(rule.tag_keys)}, and is invalid there: "
                + "; ".join(result.errors)
                + f". The {pin} branch is not relaxed to admit a record from the other branch."
            )
        buckets[pin].append(record)

    return AdaptedManifest(
        document_records=tuple(buckets[rule.absent_pin]),
        entity_records=tuple(buckets[rule.present_pin]),
        verified_pins=tuple(verified),
        unvalidated_remote_refs=tuple(sorted(remote)),
        rule=rule,
    )


def adapt_manifest(path: Path, *, contract_schema: Path) -> AdaptedManifest:
    """Read a JSONL manifest and return its records separated by branch.

    ``contract_schema`` is required and positional-by-keyword for the same
    reason it is on the document consumer: an optional pin is not a pin.
    """
    schema = load_contract(contract_schema)
    payload = Path(path).read_bytes()
    if payload and not payload.endswith(b"\n"):
        raise RecordBranchError(f"{path}: JSONL manifest must end with a newline")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecordBranchError(f"{path}: manifest is not UTF-8") from exc
    lines: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            lines.append((line_number, json.loads(line)))
        except json.JSONDecodeError as exc:
            raise RecordBranchError(f"{path}:{line_number}: invalid JSON") from exc
    if not lines:
        raise RecordBranchError(f"{path}: manifest contains no records")
    return adapt_records(lines, schema, source=str(path))


# --------------------------------------------------------------------------
# Collection routing
# --------------------------------------------------------------------------


def entity_collection_name(
    adapter: Any,
    *,
    business_instance_id: str,
    document_embedding_profile_id: str,
    entity_embedding_profile_id: str,
) -> str:
    """Name the collection entity descriptor points may use, or refuse.

    ``adapter`` is a ``QdrantAdapter``. Its ``collection_name`` derives the
    collection from ``business_instance_id`` and ``embedding_profile_id`` only;
    ``vector_store_id`` is not an input. So a *new vector store* on the same
    instance and the same embedding profile resolves to the SAME collection the
    statute and fiscal document points already occupy, and the standing
    invariant -- entity projections never enter the shared statute collection --
    would be violated by a change that looks like it separated them.

    The only separator is a distinct embedding profile. Which profile is an
    owner decision (it is a new profile, not a rename), so both ids are
    arguments and the collision is refused rather than papered over.
    """
    document = adapter.collection_name(business_instance_id, document_embedding_profile_id)
    entity = adapter.collection_name(business_instance_id, entity_embedding_profile_id)
    if entity == document:
        raise EntityCollectionCollision(
            f"entity projections would land in {entity!r}, the same collection as document "
            f"points for instance {business_instance_id!r}. QdrantAdapter.collection_name takes "
            f"(business_instance_id, embedding_profile_id) and not vector_store_id, so a new "
            f"vector store does not separate them: profiles "
            f"{entity_embedding_profile_id!r} and {document_embedding_profile_id!r} must differ."
        )
    return entity


assert set(DISPATCH_KEYS) == {"if", "then", "else"}, (
    "this adapter reads the contract's root if/then/else; the pin module now names "
    f"a different routing key set: {DISPATCH_KEYS}"
)
