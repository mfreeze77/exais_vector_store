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
them. The document side of that comparison is READ FROM THE INSTANCE TREE --
``instance.yaml`` for the business instance id and prefix, each store's own
source package for its ``ingestion.embeddingProfile`` -- so the collision fires
against any collection the instance declares, whatever the caller believes.
Round one took the document profile as an argument, which let a caller passing
some other profile receive the real shared statute collection with no collision
raised: a guard that asks the caller to supply the hazard it guards against.
Choosing the ENTITY profile remains an owner decision and stays an argument,
but an empty one is refused rather than resolved to a degenerate name.

Validation scope
----------------
There is no ``jsonschema`` in this repository -- not installed, not in any
``requirements.txt`` -- so :func:`validate` is a bounded evaluator for the
keyword vocabulary the pinned contract uses. WAVE-145 retires it in favour of
the real library; this is the bridge, and the bridge has to be honest about its
own edges, because round one was not.

Round one's failure is the reason this section is now three lists rather than
one. A single ``SUPPORTED_KEYWORDS`` set claimed ``const``, ``enum``, ``format``
and ``uniqueItems`` as supported while approximating all four, and a mutation
battery that covered each keyword BY NAME agreed with ``jsonschema`` on all of
them -- because naming a keyword and exercising its semantics are different
things. Quality control found six divergences inside those nominally-covered
classes, five of them fail-open and three reachable on the unmodified pinned
contract. The two decisive ones:

* ``if value != schema["const"]`` used Python equality, and ``True == 1``. So
  ``record_version: true`` satisfied ``const: 1`` and was admitted as a valid
  entity projection -- through the kind/version gate the contract itself calls
  "sufficient on its own to refuse an unknown kind or version".
* ``format: date`` was a shape regex, so ``2026-02-31``, ``2026-13-99`` and
  ``0000-99-99`` all passed, on both branches, through the real dispatch.

So the vocabulary is now split three ways and the split is load-bearing:

:data:`EXACT_KEYWORDS`
    Evaluated to the draft 2020-12 semantics. Equality is TYPED
    (:func:`_json_equal`): a boolean is never equal to a number, while an int
    and a float of the same mathematical value are equal. Dates are parsed by
    :mod:`datetime`, not shape-matched.
:data:`APPROXIMATED_KEYWORDS`
    Evaluated, but not to the letter of the specification. Every approximation
    actually exercised on a record is reported in
    :attr:`RecordValidation.unsupported_keyword_semantics` -- the same
    disclosure mechanism as ``unvalidated_remote_refs``, for the same reason.
:data:`ANNOTATION_KEYWORDS`
    Carry no assertion. Listed so they are *known* to be ignored.

Anything outside all three raises :class:`UnsupportedContractKeyword`. A
validator that skips what it does not understand reports "valid" for
constraints it never checked, which is worse than no validator at all -- and a
validator that *approximates* what it claims to support is that same defect one
layer down, which is what round one shipped.

What the two approximations are, precisely:

``pattern``
    JSON Schema specifies ECMA-262 regular expressions; this uses Python
    :mod:`re`, as ``jsonschema`` itself does. The dialects differ -- ``\\d`` is
    Unicode-wide in Python and ASCII-only in ECMA-262, and Python's ``$``
    matches before a trailing newline where ECMA-262's does not. Because
    ``jsonschema`` shares the behaviour, a cross-check against it CANNOT detect
    these divergences; only replacing the evaluator can.
``format: uri``
    A scheme-shape check, not RFC 3986. Stricter than ``jsonschema`` without the
    optional ``rfc3987`` package, which registers no ``uri`` checker at all, so
    this fails closed rather than open.

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
    "APPROXIMATED_KEYWORDS",
    "APPROXIMATION_TOKENS",
    "EXACT_FORMATS",
    "EXACT_KEYWORDS",
    "EXPECTED_DISPATCH_REQUIRED",
    "AdaptedManifest",
    "DispatchRule",
    "DocumentCollectionRosterIncomplete",
    "EntityCollectionCollision",
    "InstanceCollectionConfigError",
    "InstanceCollectionRoster",
    "RecordBranchError",
    "RecordValidation",
    "UnsupportedContractKeyword",
    "adapt_manifest",
    "adapt_records",
    "classify_record",
    "dispatch_rule",
    "entity_collection_name",
    "read_instance_collection_roster",
    "validate",
]

#: Cross-check for the derived dispatch, NOT the source of it. See the module
#: docstring: :func:`dispatch_rule` reads the contract's own root ``if`` and
#: then asserts it equals this, so a contract that dispatches on some other key
#: is refused by name instead of quietly routing every record one way.
EXPECTED_DISPATCH_REQUIRED: tuple[str, ...] = ("record_kind",)

#: Keywords evaluated to the draft 2020-12 semantics. Nothing is listed here
#: that the evaluator only approximates -- that claim is what round one got
#: wrong, and it is the reason ``const``/``enum``/``format``/``uniqueItems``
#: needed real implementations rather than a rename.
EXACT_KEYWORDS: frozenset[str] = frozenset(
    {
        "$ref",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "else",
        "enum",
        "if",
        "items",
        "maxItems",
        "maxLength",
        "minItems",
        "minLength",
        "minimum",
        "not",
        "oneOf",
        "properties",
        "required",
        "then",
        "type",
        "uniqueItems",
    }
)

#: Evaluated, but NOT to the letter of the specification. Every one of these
#: actually exercised on a record is reported in
#: :attr:`RecordValidation.unsupported_keyword_semantics`. ``format`` is listed
#: per-format, because ``date`` and ``date-time`` are now exact and ``uri`` is
#: not; claiming the whole keyword either way would be false.
APPROXIMATED_KEYWORDS: frozenset[str] = frozenset({"pattern", "format"})

#: The exact tokens :attr:`RecordValidation.unsupported_keyword_semantics` can
#: contain. ``format`` disaggregates: only ``uri`` is approximate.
APPROXIMATION_TOKENS: tuple[str, ...] = ("format:uri", "pattern")

#: Formats evaluated exactly, by parsing rather than by shape.
EXACT_FORMATS: frozenset[str] = frozenset({"date", "date-time"})

#: Keywords that carry no assertion. Listed so they are *known* to be ignored
#: rather than falling through the unknown-keyword refusal.
ANNOTATION_KEYWORDS: frozenset[str] = frozenset(
    {"$comment", "$defs", "$id", "$schema", "default", "description", "examples", "title"}
)

#: Backwards-compatible alias for the union this module will accept at all.
KNOWN_KEYWORDS: frozenset[str] = EXACT_KEYWORDS | APPROXIMATED_KEYWORDS | ANNOTATION_KEYWORDS

_LOCAL_REF = "#/$defs/"

#: RFC 3339 full-date. The regex fixes the SHAPE only; the calendar is then
#: checked by ``datetime.date.fromisoformat``, which is what refuses 2026-02-31.
#: The shape check is still needed because Python 3.11+ ``fromisoformat`` also
#: accepts forms RFC 3339 does not, such as ``20260701`` and ``2026-W27-1``.
_DATE_SHAPE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

#: RFC 3339 date-time. The offset is REQUIRED -- a local time with no offset is
#: not an instant, and accepting one silently invents a timezone.
_DATE_TIME_SHAPE = re.compile(
    r"\A(?P<date>\d{4}-\d{2}-\d{2})[Tt](?P<time>\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    r"(?P<offset>[Zz]|[+-]\d{2}:\d{2})\Z"
)

#: Scheme shape only. Disclosed as an approximation; see the module docstring.
_URI_SHAPE = re.compile(r"\A[A-Za-z][A-Za-z0-9+.-]*:")


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
    """What :func:`validate` concluded, including what it declined to check.

    ``unsupported_keyword_semantics`` is the second disclosure channel, built on
    the same principle as ``unvalidated_remote_refs``: every constraint this
    evaluator only approximated, on the record actually validated, is a value
    the caller can read and a test can pin. Round one had no such channel and
    called four approximations "supported".
    """

    errors: tuple[str, ...]
    unvalidated_remote_refs: tuple[str, ...]
    unsupported_keyword_semantics: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_number(value: Any) -> bool:
    """A JSON number. ``bool`` is a Python ``int`` and is NOT a JSON number."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_matches(value: Any, name: str) -> bool:
    if name == "integer":
        # Draft 2020-12: "integer" matches any number with a zero fractional
        # part, so 48211.0 IS an integer. Rejecting it was a fail-CLOSED
        # divergence found by quality control.
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and value.is_integer()
    if name == "number":
        return _is_number(value)
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


def _json_equal(left: Any, right: Any) -> bool:
    """Draft 2020-12 equality, which is TYPED.

    Two instances are equal when they are of the same JSON type and equal
    within it -- with the single numeric exception that an integer and a float
    of the same mathematical value ARE equal. Booleans are their own type, so
    ``True`` never equals ``1``.

    Python's ``==`` gets this wrong in exactly the way that matters here:
    ``True == 1`` is True, so ``record_version: true`` satisfied ``const: 1``
    and passed the contract's kind/version gate.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if left is None or right is None:
        return left is None and right is None
    if _is_number(left) and _is_number(right):
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(_json_equal(left[k], right[k]) for k in left)
    return False


def _equality_key(value: Any) -> Any:
    """A hashable key under :func:`_json_equal`'s equality.

    Booleans get their own tag so ``true`` and ``1`` do not collide; numbers are
    keyed by mathematical value so ``1`` and ``1.0`` DO collide, which is what
    draft 2020-12 requires of ``uniqueItems``.
    """
    if isinstance(value, bool):
        return ("bool", value)
    if value is None:
        return ("null",)
    if _is_number(value):
        return ("number", float(value))
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("array", tuple(_equality_key(item) for item in value))
    if isinstance(value, dict):
        return ("object", tuple(sorted((k, _equality_key(v)) for k, v in value.items())))
    raise UnsupportedContractKeyword(f"cannot compare a {type(value).__name__} as JSON")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _valid_date(value: str) -> bool:
    """RFC 3339 full-date, calendar included.

    The shape regex alone accepted 2026-02-31, 2026-13-99 and 0000-99-99.
    """
    from datetime import date

    if _DATE_SHAPE.match(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_date_time(value: str) -> bool:
    """RFC 3339 date-time: real calendar date, real clock time, real offset."""
    from datetime import datetime

    match = _DATE_TIME_SHAPE.match(value)
    if match is None:
        return False
    offset = match.group("offset")
    normalised = f"{match.group('date')}T{match.group('time')}" + (
        "+00:00" if offset in {"Z", "z"} else offset
    )
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return False
    # Belt and braces: the shape requires an offset, so a naive result would
    # mean the parser disagreed with the regex about what it just read.
    return parsed.utcoffset() is not None


def _check_keywords(schema: dict[str, Any]) -> None:
    unknown = sorted(set(schema) - KNOWN_KEYWORDS)
    if unknown:
        raise UnsupportedContractKeyword(
            f"contract uses JSON Schema keyword(s) {unknown} that this evaluator does not "
            "implement. Refusing rather than ignoring them: an ignored keyword is an "
            "unchecked constraint reported as a pass."
        )


class _Disclosures:
    """What the evaluator did not check exactly, accumulated as it goes.

    Two channels, both reported rather than swallowed: remote ``$ref``s it did
    not follow, and approximated keyword semantics it actually exercised.
    """

    __slots__ = ("approximations", "remote")

    def __init__(self) -> None:
        self.remote: set[str] = set()
        self.approximations: set[str] = set()


def _validate(
    value: Any,
    schema: Any,
    root: dict[str, Any],
    path: str,
    errors: list[str],
    seen: _Disclosures,
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
            _validate(value, target, root, path, errors, seen)
        else:
            # Deliberately not followed. See the module docstring.
            seen.remote.add(ref)

    if "type" in schema:
        names = schema["type"]
        names = [names] if isinstance(names, str) else list(names)
        if not any(_type_matches(value, name) for name in names):
            errors.append(f"{path or '<record>'}: expected type {names}, got {type(value).__name__}")
            return

    # TYPED equality. `True == 1` in Python, so `value != schema["const"]`
    # admitted `record_version: true` against `const: 1`.
    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(
            f"{path or '<record>'}: expected const {_canonical(schema['const'])}, "
            f"got {_canonical(value)}"
        )
    if "enum" in schema and not any(_json_equal(value, option) for option in schema["enum"]):
        errors.append(f"{path or '<record>'}: {_canonical(value)} is not one of {_canonical(schema['enum'])}")

    if isinstance(value, str):
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            # Python `re`, exactly as jsonschema does it, and exactly as
            # ECMA-262 does NOT. Disclosed, not silently claimed.
            seen.approximations.add("pattern")
            if re.search(pattern, value) is None:
                errors.append(f"{path or '<record>'}: {value!r} does not match {pattern!r}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path or '<record>'}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path or '<record>'}: longer than maxLength {schema['maxLength']}")
        fmt = schema.get("format")
        if isinstance(fmt, str):
            if fmt == "date":
                valid = _valid_date(value)
            elif fmt == "date-time":
                valid = _valid_date_time(value)
            elif fmt == "uri":
                seen.approximations.add("format:uri")
                valid = _URI_SHAPE.match(value) is not None
            else:
                raise UnsupportedContractKeyword(f"contract uses unimplemented format {fmt!r}")
            if not valid:
                errors.append(f"{path or '<record>'}: {value!r} is not a valid {fmt}")

    # `bool` is a Python int but is not a JSON number, so it must not be
    # compared against a numeric bound.
    if _is_number(value) and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path or '<record>'}: below minimum {schema['minimum']}")

    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path or '<record>'}: missing required property {name!r}")
        properties = schema.get("properties", {})
        for name, subschema in properties.items():
            if name in value:
                _validate(value[name], subschema, root, f"{path}.{name}" if path else name, errors, seen)
        if "additionalProperties" in schema:
            extra = sorted(set(value) - set(properties))
            allowed = schema["additionalProperties"]
            if allowed is False:
                for name in extra:
                    errors.append(f"{path or '<record>'}: property {name!r} is not permitted here")
            else:
                for name in extra:
                    _validate(value[name], allowed, root, f"{path}.{name}" if path else name, errors, seen)

    if isinstance(value, list):
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(item, schema["items"], root, f"{path}[{index}]", errors, seen)
        # Typed equality again: [true, 1] IS unique, [1, 1.0] is NOT.
        if schema.get("uniqueItems") and len({_equality_key(item) for item in value}) != len(value):
            errors.append(f"{path or '<record>'}: items are not unique")
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path or '<record>'}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path or '<record>'}: more than maxItems {schema['maxItems']}")

    for subschema in schema.get("allOf", []):
        _validate(value, subschema, root, path, errors, seen)

    if "anyOf" in schema:
        branches = [_probe(value, sub, root, path, seen) for sub in schema["anyOf"]]
        if not any(not found for found in branches):
            errors.append(f"{path or '<record>'}: matched none of the anyOf branches")
    if "oneOf" in schema:
        matched = [sub for sub in schema["oneOf"] if not _probe(value, sub, root, path, seen)]
        if len(matched) != 1:
            errors.append(f"{path or '<record>'}: matched {len(matched)} oneOf branches, expected exactly 1")
    if "not" in schema and not _probe(value, schema["not"], root, path, seen):
        errors.append(f"{path or '<record>'}: matched a schema it must not match")

    if "if" in schema:
        if not _probe(value, schema["if"], root, path, seen):
            if "then" in schema:
                _validate(value, schema["then"], root, path, errors, seen)
        elif "else" in schema:
            _validate(value, schema["else"], root, path, errors, seen)


def _probe(value: Any, schema: Any, root: dict[str, Any], path: str, seen: _Disclosures) -> list[str]:
    found: list[str] = []
    _validate(value, schema, root, path, found, seen)
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
    seen = _Disclosures()
    _validate(record, defs[branch_root], schema, "", errors, seen)
    return RecordValidation(
        errors=tuple(errors),
        unvalidated_remote_refs=tuple(sorted(seen.remote)),
        unsupported_keyword_semantics=tuple(sorted(seen.approximations)),
    )


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
    unsupported_keyword_semantics: tuple[str, ...]
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
    approximations: set[str] = set()
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
        approximations.update(result.unsupported_keyword_semantics)
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
        unsupported_keyword_semantics=tuple(sorted(approximations)),
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


@dataclass(frozen=True, slots=True)
class InstanceCollectionRoster:
    """Every document collection an instance's own config says it writes to.

    Built by reading the instance tree, never by taking a caller's word for it.
    Round one took the document profile as an ARGUMENT, so a caller who passed
    any profile other than the statute one got the real shared statute
    collection back with no collision raised -- a guard that asked the caller to
    supply the thing it was meant to protect against.
    """

    business_instance_id: str
    collection_prefix: str
    #: vector store slug -> collection name, for stores that declare a profile.
    document_collections: dict[str, str]
    #: Stores whose source package declares no ``ingestion.embeddingProfile``.
    #: The roster cannot be proved complete while this is non-empty.
    undeclared_profile_stores: tuple[str, ...]


class InstanceCollectionConfigError(ValueError):
    """The instance tree cannot be read, or disagrees with the live settings."""


class DocumentCollectionRosterIncomplete(ValueError):
    """A document store declares no embedding profile, so it cannot be avoided.

    Refusing here is the point. A non-collision guard that cannot enumerate what
    it must not collide with does not have an answer, and reporting "no
    collision" because a store was invisible is exactly the fail-open shape this
    module keeps being asked to remove.
    """


def read_instance_collection_roster(instance_root: Path, adapter: Any) -> InstanceCollectionRoster:
    """Read one instance's declared document collections off disk.

    ``instance_root`` is an ``instances/<slug>/`` directory. The business
    instance id and the Qdrant collection prefix come from ``instance.yaml``;
    each store's embedding profile comes from its own source package's
    ``ingestion.embeddingProfile``. The names are then computed by the SAME
    ``adapter.collection_name`` a real ingestion would call, so this roster is
    what that deployment actually resolves to, not a reconstruction of it.
    """
    import yaml

    root = Path(instance_root)
    instance_file = root / "instance.yaml"
    if not instance_file.is_file():
        raise InstanceCollectionConfigError(f"no instance.yaml under {root}")
    instance = yaml.safe_load(instance_file.read_text(encoding="utf-8")) or {}
    business_instance_id = (instance.get("metadata") or {}).get("businessInstanceId")
    if not business_instance_id:
        raise InstanceCollectionConfigError(f"{instance_file}: metadata.businessInstanceId is missing")
    declared_prefix = ((instance.get("storage") or {}).get("qdrant") or {}).get("collectionPrefix")
    if not declared_prefix:
        raise InstanceCollectionConfigError(f"{instance_file}: storage.qdrant.collectionPrefix is missing")
    live_prefix = getattr(adapter.settings, "qdrant_collection_prefix", None)
    if live_prefix != declared_prefix:
        raise InstanceCollectionConfigError(
            f"{instance_file} declares collectionPrefix {declared_prefix!r} but the adapter's "
            f"settings use {live_prefix!r}. The names this roster would compute would not be "
            "the ones that deployment writes to, so the collision check would be answering "
            "about a different cell."
        )

    collections: dict[str, str] = {}
    undeclared: list[str] = []
    stores_dir = root / "vector-stores"
    if not stores_dir.is_dir():
        raise InstanceCollectionConfigError(f"no vector-stores directory under {root}")
    for store_dir in sorted(p for p in stores_dir.iterdir() if p.is_dir()):
        profiles: set[str] = set()
        for source_file in sorted(store_dir.glob("sources/*/source.yaml")):
            package = yaml.safe_load(source_file.read_text(encoding="utf-8")) or {}
            profile = (package.get("ingestion") or {}).get("embeddingProfile")
            if profile:
                profiles.add(str(profile))
        if not profiles:
            undeclared.append(store_dir.name)
            continue
        for profile in sorted(profiles):
            collections[f"{store_dir.name}:{profile}"] = adapter.collection_name(
                business_instance_id, profile
            )
    return InstanceCollectionRoster(
        business_instance_id=business_instance_id,
        collection_prefix=declared_prefix,
        document_collections=collections,
        undeclared_profile_stores=tuple(undeclared),
    )


def entity_collection_name(
    adapter: Any,
    *,
    instance_root: Path,
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

    The document side is read from the instance's own config, never passed in:
    the collision fires against ANY collection the instance declares, whatever
    the caller believes. The entity profile stays a caller argument because
    choosing it is an owner decision (it is a new profile, not a rename), but an
    empty or missing one is refused rather than resolved to the degenerate
    ``<prefix><instance>_`` name.
    """
    if not isinstance(entity_embedding_profile_id, str) or not entity_embedding_profile_id.strip():
        raise InstanceCollectionConfigError(
            f"entity_embedding_profile_id must be a non-empty profile id, got "
            f"{entity_embedding_profile_id!r}. An empty profile resolves to a degenerate "
            "collection name shared by every store with an empty profile."
        )
    roster = read_instance_collection_roster(instance_root, adapter)
    if roster.undeclared_profile_stores:
        raise DocumentCollectionRosterIncomplete(
            f"{list(roster.undeclared_profile_stores)} declare no ingestion.embeddingProfile in "
            f"any source package under {Path(instance_root)}, so the document collections for "
            "this instance cannot be enumerated and a non-collision cannot be proved. Declare "
            "the profile, or this check is reporting safety it did not establish."
        )
    entity = adapter.collection_name(roster.business_instance_id, entity_embedding_profile_id)
    collided = sorted(key for key, name in roster.document_collections.items() if name == entity)
    if collided:
        raise EntityCollectionCollision(
            f"entity projections would land in {entity!r}, which is already the document "
            f"collection for {collided} on instance {roster.business_instance_id!r}. "
            "QdrantAdapter.collection_name takes (business_instance_id, embedding_profile_id) "
            "and not vector_store_id, so a new vector store does not separate them: the entity "
            f"profile {entity_embedding_profile_id!r} must differ from every declared document "
            "profile."
        )
    return entity


assert set(DISPATCH_KEYS) == {"if", "then", "else"}, (
    "this adapter reads the contract's root if/then/else; the pin module now names "
    f"a different routing key set: {DISPATCH_KEYS}"
)
