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
them. The document side of that comparison is RESOLVED FOR THE TARGET
DEPLOYMENT: the collection prefix from the adapter's own settings -- the same
object ``QdrantAdapter.collection_name`` reads, ``svs_`` in the running fiscal
cell -- and the profiles from BOTH places the instance declares them, each
source package's ``ingestion.embeddingProfile`` and
``models.preferredEmbeddingProfiles``. Both are needed: the running cell holds
two document collections, and a roster built from source packages alone finds
only one of them. ``instance.yaml``'s ``storage.qdrant.collectionPrefix`` is
NOT consulted -- nothing in this repository reads it, it says ``ks_civics_``
where the deployment says ``svs_``, and deriving names from it produced
collection names that do not exist. That mismatch is WAVE-146.

An entity store is not a document store: ``entity_store_slugs`` are excluded
from the document side, so the guard can never fire against the entity store
itself. Missing profiles are tracked per SOURCE, never per store, so a sibling
source that declares one cannot mask one that does not. Choosing the ENTITY
profile remains an owner decision and stays an argument, but an empty one is
refused rather than resolved to a degenerate name.

Validation scope
----------------
Validation is ``jsonschema`` 4.25.1 with ``FormatChecker`` passed EXPLICITLY and
``rfc3339-validator`` installed, pinned in every ``apps/*/requirements.txt`` that
ships this package. The version matches repo A's ``pyproject.toml`` pin, so the
producer and this consumer judge the same record by the same implementation --
which is the whole point of the composition milestone.

There WAS a hand-written evaluator here. It is gone, and WAVE-145 records why in
full: it shipped fail-open in four keywords it claimed to support, a 44-case
mutation battery organised by keyword NAME agreed with ``jsonschema`` on every
one of them, and quality control found six divergences inside those same
classes -- ``True == 1`` in Python, so ``record_version: true`` satisfied
``const: 1`` and passed the contract's own kind/version gate; ``format: date``
was a shape regex, so ``2026-02-31`` passed on both branches. A round-two patch
fixed those four semantically and was itself replaced by this migration, because
a validator maintained by hand is a standing invitation to that defect class and
the next divergence would also have sat inside something a battery "covered".

``format`` is passed a checker EXPLICITLY because draft 2020-12 treats it as an
annotation by default: a validator built without one reports ``2026-02-31`` as a
valid ``date``. Which formats actually assert is READ from the checker registry
(:data:`ASSERTED_FORMATS`), not assumed.

Two things are still not checked to the letter, and both are DISCLOSED in
:attr:`RecordValidation.unsupported_keyword_semantics` rather than claimed:

``pattern``
    JSON Schema specifies ECMA-262 regular expressions; ``jsonschema`` uses
    Python :mod:`re`. ``backslash-d`` is Unicode-wide in Python and ASCII-only in
    ECMA-262, and Python's ``$`` matches before a trailing newline where
    ECMA-262's does not. WAVE-145 predicted this entry would SURVIVE the
    migration for exactly this reason, and it did.
``format: uri``
    ``jsonschema`` registers no ``uri`` checker without the optional ``rfc3987``
    package, which is GPLv3 and therefore not a dependency this product can
    take. So a ``uri``-formatted field is DECLARED and NOT CHECKED. On this
    contract the exposure is nil -- ``citation_url`` also carries
    ``pattern: ^https?://`` -- but that is a fact about this contract, not about
    the keyword, so it is reported every time the branch declares it.

The vocabulary itself is still guarded, now against the library's OWN validator
table rather than a hand-written list. ``jsonschema`` IGNORES an unrecognised
keyword, exactly as the specification requires; that is correct of a validator
and wrong of a consumer, because a typo or a later-draft keyword becomes a
constraint nobody checks and nobody is told about.

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .statecivics_contract_pin import (
    BRANCH_ROOTS,
    DISPATCH_KEYS,
    ContractPinError,
    dispatch_subtree,
    load_contract,
    verify_branch,
)

__all__ = [
    "ACTION_LIFECYCLE_STATES",
    "ANNOTATION_KEYWORDS",
    "ASSERTED_FORMATS",
    "CANDIDATE_ELIGIBILITY_STATUS",
    "CANDIDATE_PATH",
    "ENTITY_PATHS",
    "EXPECTED_DISPATCH_REQUIRED",
    "FORMAT_CHECKER",
    "KNOWN_ELIGIBILITY_STATUSES",
    "KNOWN_KEYWORDS",
    "LIVE_ELIGIBILITY_STATUSES",
    "LIVE_PATH",
    "PAYLOAD_AGREEMENT_KEYS",
    "REMOVE_ACTION",
    "UPSERT_ACTION",
    "AdaptedManifest",
    "CallerSuppliedCollectionRefused",
    "CandidateRecordRefused",
    "DeploymentIndexSettings",
    "DispatchRule",
    "DocumentCollectionRosterIncomplete",
    "EntityCollectionCollision",
    "EnvelopePayloadMismatch",
    "InstanceCollectionConfigError",
    "InstanceCollectionRoster",
    "RecordBranchError",
    "RecordValidation",
    "RemovalRecordNotStageable",
    "StagedEntities",
    "UnknownEligibilityStatus",
    "UnsupportedContractKeyword",
    "adapt_manifest",
    "adapt_records",
    "admit_entity_records",
    "assert_envelope_payload_agreement",
    "branch_subtree",
    "candidate_collection_name",
    "classify_record",
    "deployment_index_settings",
    "dispatch_rule",
    "eligibility_status",
    "entity_collection_name",
    "entity_path_for",
    "read_instance_collection_roster",
    "resolve_staging_collection",
    "stage_entity_descriptors",
    "validate",
]

#: Cross-check for the derived dispatch, NOT the source of it. See the module
#: docstring: :func:`dispatch_rule` reads the contract's own root ``if`` and
#: then asserts it equals this, so a contract that dispatches on some other key
#: is refused by name instead of quietly routing every record one way.
EXPECTED_DISPATCH_REQUIRED: tuple[str, ...] = ("record_kind",)


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
# Validation, by jsonschema
# --------------------------------------------------------------------------

#: Keywords the draft's own vocabulary asserts, taken FROM the library rather
#: than listed here. A hand-written list is what round one shipped.
_ASSERTING_KEYWORDS: frozenset[str] = frozenset(Draft202012Validator.VALIDATORS)

#: Keywords that carry no assertion in draft 2020-12. Listed so they are
#: *known* to be inert rather than falling through the vocabulary refusal.
ANNOTATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "$anchor",
        "$comment",
        "$defs",
        "$dynamicAnchor",
        "$id",
        "$schema",
        "$vocabulary",
        "default",
        "deprecated",
        "description",
        "examples",
        "readOnly",
        "title",
        "writeOnly",
    }
)

#: Keywords with no validator entry of their own because a SIBLING keyword
#: applies them: ``if`` evaluates ``then`` and ``else``. They assert, so they
#: are known; they are listed separately so it is clear why the library's table
#: does not name them.
_SIBLING_APPLIED_KEYWORDS: frozenset[str] = frozenset({"then", "else"})

#: Everything this module will accept in a contract at all.
KNOWN_KEYWORDS: frozenset[str] = (
    _ASSERTING_KEYWORDS | _SIBLING_APPLIED_KEYWORDS | ANNOTATION_KEYWORDS
)

#: The one format checker registry, built once. ``FormatChecker`` is passed
#: EXPLICITLY: draft 2020-12 treats ``format`` as an annotation by default, so a
#: validator constructed without this reports a malformed date as valid. With
#: ``rfc3339-validator`` installed, ``date`` and ``date-time`` assert; which
#: formats actually assert is READ from this object rather than assumed.
FORMAT_CHECKER = FormatChecker()

#: Formats the installed checker registry actually asserts.
ASSERTED_FORMATS: frozenset[str] = frozenset(FORMAT_CHECKER.checkers)

_LOCAL_REF = "#/$defs/"


class UnsupportedContractKeyword(ContractPinError):
    """The contract uses a keyword outside the draft 2020-12 vocabulary.

    ``jsonschema`` IGNORES an unrecognised keyword, exactly as the
    specification says it must. That is correct of a validator and wrong of a
    consumer: a typo, or a keyword from a later draft, becomes a constraint
    nobody checks and nobody is told about. So the vocabulary is checked here,
    against the library's OWN validator table rather than a hand-written list.
    """


@dataclass(frozen=True, slots=True)
class RecordValidation:
    """What :func:`validate` concluded, including what it did not check.

    Two disclosure channels, both reported rather than swallowed:

    ``unvalidated_remote_refs``
        Remote ``$ref``s, deliberately not resolved.
    ``unsupported_keyword_semantics``
        Constraints the branch declares that this validator does not check
        exactly. This survived the migration to ``jsonschema``, as WAVE-145
        predicted it would, because two of its entries are properties of the
        library and not of the evaluator it replaced.
    """

    errors: tuple[str, ...]
    unvalidated_remote_refs: tuple[str, ...]
    unsupported_keyword_semantics: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _walk_schema(node: Any):
    """Every subschema object reachable inside one schema, including itself."""
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key in {"properties", "$defs", "patternProperties", "dependentSchemas"}:
                if isinstance(value, dict):
                    for sub in value.values():
                        yield from _walk_schema(sub)
            elif key in {"allOf", "anyOf", "oneOf", "prefixItems"}:
                if isinstance(value, list):
                    for sub in value:
                        yield from _walk_schema(sub)
            elif key in {
                "if",
                "then",
                "else",
                "not",
                "items",
                "contains",
                "additionalProperties",
                "propertyNames",
                "unevaluatedItems",
                "unevaluatedProperties",
            }:
                yield from _walk_schema(value)


def branch_subtree(schema: dict[str, Any], branch_root: str) -> list[dict[str, Any]]:
    """Every subschema object a branch reaches, following LOCAL refs only.

    Local-only, for the same reason ``statecivics_contract_pin.branch_closure``
    is local-only: a remote ref names a separate contract with its own pin.
    """
    defs = schema.get("$defs")
    if not isinstance(defs, dict) or branch_root not in defs:
        raise ContractPinError(f"contract is missing $defs.{branch_root}")
    pending = [branch_root]
    seen_defs: set[str] = set()
    objects: list[dict[str, Any]] = []
    while pending:
        name = pending.pop()
        if name in seen_defs:
            continue
        if name not in defs:
            raise ContractPinError(f"contract is missing $defs.{name}")
        seen_defs.add(name)
        for node in _walk_schema(defs[name]):
            objects.append(node)
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith(_LOCAL_REF):
                pending.append(ref[len(_LOCAL_REF) :])
    return objects


def _check_vocabulary(objects: list[dict[str, Any]]) -> None:
    unknown = sorted({key for node in objects for key in node} - KNOWN_KEYWORDS)
    if unknown:
        raise UnsupportedContractKeyword(
            f"contract uses JSON Schema keyword(s) {unknown} that are outside the draft "
            "2020-12 vocabulary. jsonschema would ignore them silently, which turns a "
            "constraint into one nobody checks and nobody is told about."
        )


def _remote_refs(objects: list[dict[str, Any]]) -> set[str]:
    return {
        node["$ref"]
        for node in objects
        if isinstance(node.get("$ref"), str) and not node["$ref"].startswith(_LOCAL_REF)
    }


def _declared_approximations(objects: list[dict[str, Any]]) -> set[str]:
    """What this branch declares that is NOT checked to the letter.

    Derived from the schema and from the installed checker registry, so it stays
    true as either changes -- it is not a list someone has to remember to edit.
    """
    found: set[str] = set()
    for node in objects:
        if isinstance(node.get("pattern"), str):
            # ECMA-262 by specification, Python `re` in this library. See the
            # module docstring; a cross-check against jsonschema cannot see it.
            found.add("pattern")
        fmt = node.get("format")
        if isinstance(fmt, str) and fmt not in ASSERTED_FORMATS:
            found.add(f"format:{fmt}")
    return found


def _registry(remote: set[str]) -> Any:
    """Always-true stubs for every remote ref, keyed by base URI.

    NOT a resolution of those contracts. Each names a separate contract with its
    own pin, and resolving one here would silently widen what this module claims
    to have checked while leaving the pin unchanged. The refs are reported
    instead, in :attr:`RecordValidation.unvalidated_remote_refs`.
    """
    registry = Registry()
    merged: dict[str, dict[str, Any]] = {}
    for ref in remote:
        base, _, pointer = ref.partition("#")
        stub = merged.setdefault(base, {})
        node = stub
        for segment in [s for s in pointer.split("/") if s]:
            node = node.setdefault(segment, {})
    for base, contents in merged.items():
        registry = registry.with_resource(
            base, Resource(contents=contents, specification=DRAFT202012)
        )
    return registry


def _branch_validator(schema: dict[str, Any], branch_root: str, remote: set[str]) -> Any:
    document = {key: value for key, value in schema.items() if key not in DISPATCH_KEYS}
    document["$ref"] = f"{_LOCAL_REF}{branch_root}"
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(
        document, registry=_registry(remote), format_checker=FORMAT_CHECKER
    )


def validate(record: Any, schema: dict[str, Any], branch_root: str) -> RecordValidation:
    """Validate ``record`` against ONE named ``$defs`` entry of ``schema``.

    ``branch_root`` is a ``$defs`` key -- the value the contract's own dispatch
    arm points at, resolved by :func:`dispatch_rule`. Nothing here re-decides
    which branch applies.

    The top-level ``if``/``then``/``else`` is removed from the document handed
    to the validator, and replaced by a ``$ref`` to the named branch. The
    dispatch has already run, in :func:`classify_record`, which reads the tag
    keys and nothing else; leaving the routing in place would let a declarative
    validator re-decide it with no notion of "first".
    """
    objects = branch_subtree(schema, branch_root)
    _check_vocabulary(objects)
    remote = _remote_refs(objects)
    validator = _branch_validator(schema, branch_root, remote)
    errors = tuple(
        f"{'.'.join(str(part) for part in error.absolute_path) or '<record>'}: {error.message}"
        for error in validator.iter_errors(record)
    )
    return RecordValidation(
        errors=errors,
        unvalidated_remote_refs=tuple(sorted(remote)),
        unsupported_keyword_semantics=tuple(sorted(_declared_approximations(objects))),
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
        if pin == rule.present_pin:
            # Cross-field, after schema validation and before any routing. The
            # two contracts each accept a self-contradictory record; only a rule
            # that relates them can refuse it.
            try:
                assert_envelope_payload_agreement(record)
            except EnvelopePayloadMismatch as exc:
                raise EnvelopePayloadMismatch(f"{source}:{line_number}: {exc}") from None
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
class DeploymentIndexSettings:
    """The collection-naming inputs OF THE TARGET DEPLOYMENT.

    Not of the checked-in instance YAML. ``instance.yaml`` declares
    ``storage.qdrant.collectionPrefix``, and NOTHING in this repository reads
    it: the prefix a running cell uses is ``QDRANT_COLLECTION_PREFIX`` from its
    environment, defaulted to ``svs_`` by ``config.Settings`` and by
    ``scripts/release/generate-cell-env.py``. The two disagree today for
    ``ks-state-civics`` (``ks_civics_`` in YAML, ``svs_`` in the running fiscal
    cell), which is WAVE-146; deriving names from the YAML produced collection
    names the deployment does not have, which is how a guard came to report
    safety about a cell that does not exist.

    So the prefix is taken from the adapter's OWN settings -- the same object
    ``QdrantAdapter.collection_name`` reads -- and the YAML's value is never
    consulted for it.
    """

    business_instance_id: str
    collection_prefix: str


@dataclass(frozen=True, slots=True)
class InstanceCollectionRoster:
    """Every DOCUMENT collection the target deployment resolves for an instance.

    Built by reading the instance tree for profiles and the deployment settings
    for the prefix, never by taking a caller's word for either. Round two took
    the document profile as an ARGUMENT, so a caller who passed any profile
    other than the statute one got the real shared collection back with no
    collision raised -- a guard that asked the caller to supply the thing it was
    meant to protect against.

    ``entity_store_slugs`` are EXCLUDED from ``document_collections`` rather
    than absent from the tree: an entity store is not a document store, and a
    guard that compared an entity collection against itself would refuse the
    only arrangement that is actually correct.
    """

    settings: DeploymentIndexSettings
    #: "<store slug>:<profile>" -> collection name, document stores only.
    document_collections: dict[str, str]
    #: Sources that declare no embedding profile, as "<store>/<source>" pairs.
    #: Tracked per SOURCE, never per store: a store with two source packages,
    #: one declaring a profile and one not, would otherwise report as fully
    #: declared and hide the second. The roster cannot be proved complete while
    #: this is non-empty.
    undeclared_profile_sources: tuple[str, ...]
    #: Stores classified as entity stores and therefore not document stores.
    entity_store_slugs: tuple[str, ...]
    #: Profiles contributed by ``models.preferredEmbeddingProfiles``, which is
    #: where the instance declares a profile no source package names.
    preferred_profiles: tuple[str, ...]

    @property
    def undeclared_profile_stores(self) -> tuple[str, ...]:
        """The distinct stores owning at least one undeclared source."""
        return tuple(sorted({pair.split("/", 1)[0] for pair in self.undeclared_profile_sources}))


class InstanceCollectionConfigError(ValueError):
    """The instance tree or the deployment settings cannot be read."""


class DocumentCollectionRosterIncomplete(ValueError):
    """A document source declares no embedding profile, so it cannot be avoided.

    Refusing here is the point. A non-collision guard that cannot enumerate what
    it must not collide with does not have an answer, and reporting "no
    collision" because a source was invisible is exactly the fail-open shape
    this module keeps being asked to remove.
    """


def deployment_index_settings(instance_root: Path, adapter: Any) -> DeploymentIndexSettings:
    """The business instance id from the tree, the prefix from the deployment."""
    import yaml

    root = Path(instance_root)
    instance_file = root / "instance.yaml"
    if not instance_file.is_file():
        raise InstanceCollectionConfigError(f"no instance.yaml under {root}")
    instance = yaml.safe_load(instance_file.read_text(encoding="utf-8")) or {}
    business_instance_id = (instance.get("metadata") or {}).get("businessInstanceId")
    if not business_instance_id:
        raise InstanceCollectionConfigError(f"{instance_file}: metadata.businessInstanceId is missing")
    prefix = getattr(adapter.settings, "qdrant_collection_prefix", None)
    if not isinstance(prefix, str) or not prefix:
        raise InstanceCollectionConfigError(
            "the adapter's settings declare no qdrant_collection_prefix, so the collections "
            "this deployment resolves cannot be named"
        )
    return DeploymentIndexSettings(
        business_instance_id=str(business_instance_id), collection_prefix=prefix
    )


def read_instance_collection_roster(
    instance_root: Path,
    adapter: Any,
    *,
    entity_store_slugs: tuple[str, ...] = (),
) -> InstanceCollectionRoster:
    """Resolve one instance's document collections for the target deployment.

    Profiles come from two declared places, because the runtime uses both:

    * each source package's ``ingestion.embeddingProfile``; and
    * ``models.preferredEmbeddingProfiles`` in ``instance.yaml``, which is where
      ``openai_text_embedding_3_small_1536`` is declared -- the profile behind
      the SECOND document collection in the running fiscal cell. A roster built
      from source packages alone finds only the Voyage one and would never
      enumerate, let alone guard against, the other.

    Names are computed by the SAME ``adapter.collection_name`` a real ingestion
    calls, so this roster is what that deployment resolves to rather than a
    reconstruction of it.
    """
    import yaml

    root = Path(instance_root)
    settings = deployment_index_settings(root, adapter)
    instance = yaml.safe_load((root / "instance.yaml").read_text(encoding="utf-8")) or {}

    entity_slugs = tuple(sorted(set(entity_store_slugs)))
    collections: dict[str, str] = {}

    preferred = (instance.get("models") or {}).get("preferredEmbeddingProfiles") or {}
    if not isinstance(preferred, dict):
        raise InstanceCollectionConfigError(
            f"{root / 'instance.yaml'}: models.preferredEmbeddingProfiles must be a mapping"
        )
    preferred_profiles = tuple(sorted({str(v) for v in preferred.values() if v}))
    for profile in preferred_profiles:
        collections[f"models.preferredEmbeddingProfiles:{profile}"] = adapter.collection_name(
            settings.business_instance_id, profile
        )

    undeclared: list[str] = []
    stores_dir = root / "vector-stores"
    if not stores_dir.is_dir():
        raise InstanceCollectionConfigError(f"no vector-stores directory under {root}")
    for store_dir in sorted(p for p in stores_dir.iterdir() if p.is_dir()):
        if store_dir.name in entity_slugs:
            # An entity store is not a document store. It is skipped entirely --
            # neither enumerated as a collection to avoid, nor counted as an
            # undeclared document source.
            continue
        sources = sorted(store_dir.glob("sources/*/source.yaml"))
        if not sources:
            undeclared.append(f"{store_dir.name}/<no source package>")
            continue
        for source_file in sources:
            package = yaml.safe_load(source_file.read_text(encoding="utf-8")) or {}
            profile = (package.get("ingestion") or {}).get("embeddingProfile")
            if not profile:
                # Per SOURCE. A sibling that declares one must not mask this.
                undeclared.append(f"{store_dir.name}/{source_file.parent.name}")
                continue
            collections[f"{store_dir.name}:{profile}"] = adapter.collection_name(
                settings.business_instance_id, str(profile)
            )

    return InstanceCollectionRoster(
        settings=settings,
        document_collections=collections,
        undeclared_profile_sources=tuple(undeclared),
        entity_store_slugs=entity_slugs,
        preferred_profiles=preferred_profiles,
    )


def entity_collection_name(
    adapter: Any,
    *,
    instance_root: Path,
    entity_embedding_profile_id: str,
    entity_store_slugs: tuple[str, ...] = (),
    document_profile_catalog: tuple[str, ...] = (),
) -> str:
    """Name the collection entity descriptor points may use, or refuse.

    ``adapter`` is a ``QdrantAdapter``. Its ``collection_name`` derives the
    collection from ``business_instance_id`` and ``embedding_profile_id`` only;
    ``vector_store_id`` is not an input. So a *new vector store* on the same
    instance and the same embedding profile resolves to the SAME collection the
    statute and fiscal document points already occupy, and the standing
    invariant -- entity projections never enter the shared statute collection --
    would be violated by a change that looks like it separated them.

    The document side is resolved for the TARGET DEPLOYMENT and never passed
    in: the collision fires against any document collection that deployment
    resolves, whatever the caller believes. ``entity_store_slugs`` names the
    stores that are entity stores; they are excluded from the document side, so
    the guard can never fire against the entity store itself.

    The optional document_profile_catalog is the server's complete model
    registry: document ingestion refuses a profile absent from that registry.
    It bounds dynamic routing and fallbacks even when a source package has not
    declared its profile. Source declarations still contribute their names.
    Without that runtime catalog, every source must still declare a profile.

    An empty or non-string entity profile is refused rather than resolved to
    the degenerate ``<prefix><instance>_`` name.
    """
    if not isinstance(entity_embedding_profile_id, str) or not entity_embedding_profile_id.strip():
        raise InstanceCollectionConfigError(
            f"entity_embedding_profile_id must be a non-empty profile id, got "
            f"{entity_embedding_profile_id!r}. An empty profile resolves to a degenerate "
            "collection name shared by every store with an empty profile."
        )
    roster = read_instance_collection_roster(
        instance_root, adapter, entity_store_slugs=entity_store_slugs
    )
    if roster.undeclared_profile_sources and not document_profile_catalog:
        raise DocumentCollectionRosterIncomplete(
            f"{list(roster.undeclared_profile_sources)} declare no ingestion.embeddingProfile "
            f"under {Path(instance_root)}, so the document collections this deployment resolves "
            "cannot be enumerated and a non-collision cannot be proved. Declare the profile "
            "each one actually uses -- do not declare one the runtime does not use -- or this "
            "check is reporting safety it did not establish."
        )
    entity = adapter.collection_name(
        roster.settings.business_instance_id, entity_embedding_profile_id
    )
    documents = dict(roster.document_collections)
    for profile in document_profile_catalog:
        if not isinstance(profile, str) or not profile.strip():
            raise InstanceCollectionConfigError("document profile catalog contains an empty profile")
        documents[f"registry:{profile}"] = adapter.collection_name(
            roster.settings.business_instance_id, profile
        )
    collided = sorted(key for key, name in documents.items() if name == entity)
    if collided:
        raise EntityCollectionCollision(
            f"entity projections would land in {entity!r}, which this deployment already "
            f"resolves as the document collection for {collided} on business instance "
            f"{roster.settings.business_instance_id!r}. QdrantAdapter.collection_name takes "
            "(business_instance_id, embedding_profile_id) and not vector_store_id, so a new "
            f"vector store does not separate them: the entity profile "
            f"{entity_embedding_profile_id!r} must differ from every document profile this "
            "deployment resolves."
        )
    return entity




# --------------------------------------------------------------------------
# Live and candidate entity paths
# --------------------------------------------------------------------------

#: The two destinations an entity projection can be staged for.
LIVE_PATH = "live"
CANDIDATE_PATH = "candidate"
ENTITY_PATHS: tuple[str, ...] = (LIVE_PATH, CANDIDATE_PATH)

#: ``eligibility.status`` values the LIVE entity store admits. Read from the
#: record's own copied review columns; this module never sets or defaults them.
LIVE_ELIGIBILITY_STATUSES: frozenset[str] = frozenset({"reviewed", "published"})

#: The status that routes a record to the candidate-only path.
CANDIDATE_ELIGIBILITY_STATUS = "candidate"

#: Every status either path recognises. A value outside this is refused rather
#: than routed: an unrecognised review state is not evidence of a safe one.
KNOWN_ELIGIBILITY_STATUSES: frozenset[str] = LIVE_ELIGIBILITY_STATUSES | {
    CANDIDATE_ELIGIBILITY_STATUS
}


#: Where each entity type's KS-600 payload keeps the three fields the envelope
#: also carries. Both halves of a record state identity, revision and review
#: state; a record in which they disagree is not two opinions, it is one record
#: that is wrong.
PAYLOAD_AGREEMENT_KEYS: dict[str, dict[str, str]] = {
    "provision_reference": {
        "entity_logical_id": "provision_reference_logical_id",
        "entity_revision": "provision_reference_revision",
        "eligibility.status": "status",
    },
    "appropriation_action": {
        "entity_logical_id": "appropriation_action_id",
        "entity_revision": "revision",
        "eligibility.status": "status",
    },
}


class EnvelopePayloadMismatch(ValueError):
    """The envelope and its KS-600 payload disagree about the same fact.

    JSON Schema cannot express this. The envelope is validated against the
    retrieval-export contract and the payload against its own KS-600 contract,
    and nothing relates them -- so a record whose envelope says ``published``
    while its payload says ``candidate`` satisfies BOTH schemas and is still a
    record that cannot be true. Quality control found exactly that, and found it
    reaching the embedding and index callbacks.

    The revision form of it is worse, because it is what a half-applied as-of
    selection leaves behind: a revision-2 envelope wrapping a revision-1
    payload. A stale fixture upstream produced that shape by accident, which is
    the evidence that it is reachable rather than theoretical.
    """


def _envelope_value(record: Mapping, field: str) -> Any:
    if field == "eligibility.status":
        eligibility = record.get("eligibility")
        return eligibility.get("status") if isinstance(eligibility, dict) else None
    return record.get(field)


#: The ingestion actions an entity record can declare, and what each one means
#: for the payload. Keyed on ``ingestion.action``, NOT on whether a payload
#: happens to be present, and NOT on ``record_kind`` -- which says the record is
#: an entity projection and says nothing about upsert versus removal.
UPSERT_ACTION = "upsert"
REMOVE_ACTION = "remove"

#: The lifecycle states each action is consistent with. An ``upsert`` is current
#: state; a ``remove`` is a retraction and must say which kind. A record whose
#: action and lifecycle disagree is refused rather than read under either.
ACTION_LIFECYCLE_STATES: dict[str, frozenset[str]] = {
    UPSERT_ACTION: frozenset({"current"}),
    REMOVE_ACTION: frozenset({"superseded", "withdrawn"}),
}
ACTION_REMOVAL_REQUIRED: dict[str, bool] = {UPSERT_ACTION: False, REMOVE_ACTION: True}


class RemovalRecordNotStageable(ValueError):
    """A tombstone was handed to descriptor staging.

    A removal record directs a DELETE. It is identity-minimal by construction --
    no entity, no description, no derivation -- so there is no descriptor text
    to embed and nothing to index. It is valid to ADAPT one; it is not valid to
    stage one. Letting it through would either crash on the missing description
    or, worse, embed something invented in its place.
    """


def _ingestion_action(record: Mapping) -> str:
    ingestion = record.get("ingestion")
    if not isinstance(ingestion, dict) or "action" not in ingestion:
        raise EnvelopePayloadMismatch(
            f"record {record.get('export_record_id')!r} declares no ingestion.action, so "
            "whether its payload should be present cannot be decided. Refusing rather than "
            "guessing from whether one happens to be there."
        )
    action = ingestion["action"]
    if action not in ACTION_LIFECYCLE_STATES:
        raise EnvelopePayloadMismatch(
            f"record {record.get('export_record_id')!r} declares ingestion.action {action!r}, "
            f"which is none of {sorted(ACTION_LIFECYCLE_STATES)}"
        )
    return action


def _assert_action_lifecycle_agree(record: Mapping, action: str) -> None:
    """An action and a lifecycle that disagree describe two different records."""
    lifecycle = record.get("lifecycle")
    if not isinstance(lifecycle, dict) or "state" not in lifecycle:
        raise EnvelopePayloadMismatch(
            f"record {record.get('export_record_id')!r} declares ingestion.action {action!r} "
            "but carries no lifecycle.state to agree with it"
        )
    state = lifecycle["state"]
    allowed = ACTION_LIFECYCLE_STATES[action]
    if state not in allowed:
        raise EnvelopePayloadMismatch(
            f"refusing entity record {record.get('export_record_id')!r}: "
            f"ingestion.action={action!r} but lifecycle.state={state!r}, which is none of "
            f"{sorted(allowed)}. A record cannot be an upsert of current state and a "
            "retraction at the same time, and reading it as either would be a guess."
        )
    required = lifecycle.get("removal_required")
    expected = ACTION_REMOVAL_REQUIRED[action]
    if required is not expected:
        raise EnvelopePayloadMismatch(
            f"refusing entity record {record.get('export_record_id')!r}: "
            f"ingestion.action={action!r} implies lifecycle.removal_required={expected!r}, "
            f"but the record says {required!r}"
        )


def assert_envelope_payload_agreement(record: Mapping) -> None:
    """Refuse a record whose envelope and payload state different facts.

    A CROSS-FIELD rule, applied after schema validation and before any routing.
    It changes no schema and moves no digest: it relates two documents that each
    contract already accepts.

    **The payload requirement is decided by ``ingestion.action``, never by
    whether a payload is present.** An earlier revision returned silently when
    ``entity`` was missing, so a record that was NOT a tombstone -- lifecycle
    ``current``, ``action: upsert``, description intact -- but whose payload had
    been stripped skipped the check entirely and was embedded and indexed.
    Absence of the thing being checked was read as permission to skip the check.

    ``record_kind`` cannot be the discriminator either: it says the record is an
    entity projection and says nothing about upsert versus removal.

    A removal record is identity-minimal by construction, so there is nothing to
    agree with and it is skipped here -- but only once its action and lifecycle
    have been shown to agree that it really is one.
    """
    action = _ingestion_action(record)
    _assert_action_lifecycle_agree(record, action)
    payload = record.get("entity")

    if action == REMOVE_ACTION:
        if payload is not None:
            raise EnvelopePayloadMismatch(
                f"refusing entity record {record.get('export_record_id')!r}: it declares "
                "ingestion.action='remove' but carries an entity payload. A tombstone names "
                "what to delete and nothing else."
            )
        return

    if payload is None:
        raise EnvelopePayloadMismatch(
            f"refusing entity record {record.get('export_record_id')!r}: "
            f"ingestion.action={action!r} with lifecycle.state="
            f"{(record.get('lifecycle') or {}).get('state')!r} requires an entity payload, "
            "and it has none. A missing payload is not a tombstone -- a tombstone says so in "
            "its action -- and it is not permission to skip the agreement check."
        )
    if not isinstance(payload, dict):
        raise EnvelopePayloadMismatch(
            f"record {record.get('export_record_id')!r} has a non-object entity payload, so "
            "envelope/payload agreement cannot be established"
        )
    entity_type = record.get("entity_type")
    keys = PAYLOAD_AGREEMENT_KEYS.get(entity_type) if isinstance(entity_type, str) else None
    if keys is None:
        raise EnvelopePayloadMismatch(
            f"record {record.get('export_record_id')!r} declares entity_type {entity_type!r}, "
            f"for which no envelope/payload field mapping is known "
            f"({sorted(PAYLOAD_AGREEMENT_KEYS)}). Refusing rather than skipping the check: an "
            "unknown type is not evidence that the two halves agree."
        )
    for envelope_field, payload_field in keys.items():
        envelope_value = _envelope_value(record, envelope_field)
        if payload_field not in payload:
            raise EnvelopePayloadMismatch(
                f"record {record.get('export_record_id')!r} ({entity_type}): the payload has no "
                f"{payload_field!r} to compare with the envelope's {envelope_field} "
                f"={envelope_value!r}, so agreement cannot be established"
            )
        payload_value = payload[payload_field]
        if not _json_equal_scalar(envelope_value, payload_value):
            raise EnvelopePayloadMismatch(
                f"refusing entity record {record.get('export_record_id')!r} ({entity_type}): "
                f"envelope {envelope_field}={envelope_value!r} but payload "
                f"{payload_field}={payload_value!r}. Both schemas accept this record "
                "separately; nothing relates them, so the disagreement is invisible to "
                "validation and must be refused here."
            )


def _json_equal_scalar(left: Any, right: Any) -> bool:
    """Typed equality for the scalars this rule compares.

    A boolean is never a number, for the same reason it is not in JSON Schema.
    An int and a float of equal mathematical value are equal, so a revision
    emitted as ``2.0`` still agrees with ``2``.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right


class CandidateRecordRefused(ValueError):
    """A candidate revision was offered to the LIVE entity store.

    This refusal is a deliverable, not an incident. A candidate is material a
    human has not signed off; the live entity store is what ordinary retrieval
    reads. The refusal is raised by :func:`admit_entity_records`, which runs to
    completion over the whole batch BEFORE :func:`stage_entity_descriptors`
    calls ``embed`` or ``index_write`` even once -- because a refusal that
    arrives after an embedding call has already spent money and written state,
    and "we refused it" would then be false about both.
    """


class UnknownEligibilityStatus(ValueError):
    """A record's ``eligibility.status`` is a value neither path recognises."""


def eligibility_status(record: Mapping) -> str:
    """The record's OWN copied review status, or refuse.

    Never defaulted. A record with no eligibility block is refused rather than
    treated as unreviewed-and-therefore-candidate or as reviewed-by-omission;
    both guesses are the exporter's job and it already did it.
    """
    eligibility = record.get("eligibility")
    if not isinstance(eligibility, dict) or "status" not in eligibility:
        raise UnknownEligibilityStatus(
            f"record {record.get('export_record_id')!r} carries no eligibility.status, so "
            "neither path can admit it. The status is copied from the row's own review "
            "columns upstream and is never defaulted here."
        )
    status = eligibility["status"]
    if not isinstance(status, str) or status not in KNOWN_ELIGIBILITY_STATUSES:
        raise UnknownEligibilityStatus(
            f"record {record.get('export_record_id')!r} has eligibility.status {status!r}, "
            f"which is none of {sorted(KNOWN_ELIGIBILITY_STATUSES)}. An unrecognised review "
            "state is not evidence of a safe one."
        )
    return status


def entity_path_for(record: Mapping) -> str:
    """Which path this record belongs to, by its own status."""
    return CANDIDATE_PATH if eligibility_status(record) == CANDIDATE_ELIGIBILITY_STATUS else LIVE_PATH


def admit_entity_records(
    records: Sequence[Mapping], *, path: str
) -> tuple[dict[str, Any], ...]:
    """Return the records ``path`` admits, or refuse by name.

    THE GATE. Pure: it reads records and raises. It performs no I/O, holds no
    client and calls nothing injected, so there is no arrangement of it that can
    spend money or write state before deciding.

    The whole batch is judged before anything is returned, so one candidate
    anywhere refuses the batch rather than letting the records ahead of it
    through first.
    """
    if path not in ENTITY_PATHS:
        raise ValueError(f"unknown entity path {path!r}; expected one of {list(ENTITY_PATHS)}")
    admitted: list[dict[str, Any]] = []
    for record in records:
        # Before the status is even read: a record whose two halves disagree has
        # no single status to route on. Repeated here and not only in
        # adapt_records because records can reach this gate without having been
        # read from a manifest, and every path to embedding runs through it.
        assert_envelope_payload_agreement(record)
        if (record.get("ingestion") or {}).get("action") == REMOVE_ACTION:
            raise RemovalRecordNotStageable(
                f"refusing entity record {record.get('export_record_id')!r} for descriptor "
                f"staging on the {path!r} path: ingestion.action='remove' directs a DELETE and "
                "the record carries no description to embed. A tombstone is valid to adapt and "
                "is not valid to stage."
            )
        status = eligibility_status(record)
        if path == LIVE_PATH and status == CANDIDATE_ELIGIBILITY_STATUS:
            raise CandidateRecordRefused(
                f"refusing entity record {record.get('export_record_id')!r} "
                f"({record.get('entity_type')} {record.get('entity_logical_id')!r} revision "
                f"{record.get('entity_revision')!r}) for the live entity store: "
                f"eligibility.status is {CANDIDATE_ELIGIBILITY_STATUS!r}, and the live store "
                f"admits only {sorted(LIVE_ELIGIBILITY_STATUSES)}. Stage it on the "
                f"{CANDIDATE_PATH!r} path instead. Nothing has been embedded or indexed."
            )
        if path == CANDIDATE_PATH and status != CANDIDATE_ELIGIBILITY_STATUS:
            # Symmetry matters: the candidate path is not a dumping ground, and
            # a reviewed revision quietly sitting there would be invisible to
            # the live store that should have had it.
            raise CandidateRecordRefused(
                f"refusing entity record {record.get('export_record_id')!r} for the candidate "
                f"path: eligibility.status is {status!r}, not "
                f"{CANDIDATE_ELIGIBILITY_STATUS!r}. It belongs on the {LIVE_PATH!r} path."
            )
        admitted.append(dict(record))
    return tuple(admitted)


class CallerSuppliedCollectionRefused(ValueError):
    """A caller named a collection that is not the one the guards resolve.

    The guards were built and then not wired to the function that actually
    calls embedding and indexing, which is the same as not having them: quality
    control drove ``stage_entity_descriptors`` with
    ``svs_biz_ks_state_civics_voyage_4_docs_1024`` -- the shared statute and
    document collection -- and it embedded and indexed into it. A guard nothing
    calls does not hold an invariant; it describes one.
    """


@dataclass(frozen=True, slots=True)
class StagedEntities:
    """What a staging run admitted and where it put it."""

    path: str
    collection: str
    records: tuple[dict[str, Any], ...]
    embedded: int


def resolve_staging_collection(
    adapter: Any,
    *,
    path: str,
    instance_root: Path,
    entity_embedding_profile_id: str,
    candidate_embedding_profile_id: str | None = None,
    entity_store_slugs: tuple[str, ...] = (),
    document_profile_catalog: tuple[str, ...] = (),
) -> str:
    """The collection ``path`` resolves to, through the guards, or refuse."""
    if path == LIVE_PATH:
        return entity_collection_name(
            adapter,
            instance_root=instance_root,
            entity_embedding_profile_id=entity_embedding_profile_id,
            entity_store_slugs=entity_store_slugs,
            document_profile_catalog=document_profile_catalog,
        )
    if path == CANDIDATE_PATH:
        if candidate_embedding_profile_id is None:
            raise InstanceCollectionConfigError(
                "the candidate path needs its own embedding profile: it must share a "
                "collection with neither the document stores nor the live entity store"
            )
        return candidate_collection_name(
            adapter,
            instance_root=instance_root,
            candidate_embedding_profile_id=candidate_embedding_profile_id,
            entity_embedding_profile_id=entity_embedding_profile_id,
            entity_store_slugs=entity_store_slugs,
            document_profile_catalog=document_profile_catalog,
        )
    raise ValueError(f"unknown entity path {path!r}; expected one of {list(ENTITY_PATHS)}")


def stage_entity_descriptors(
    records: Sequence[Mapping],
    *,
    path: str,
    adapter: Any,
    instance_root: Path,
    entity_embedding_profile_id: str,
    candidate_embedding_profile_id: str | None = None,
    entity_store_slugs: tuple[str, ...] = (),
    document_profile_catalog: tuple[str, ...] = (),
    collection: str | None = None,
    embed: Any,
    index_write: Any,
) -> StagedEntities:
    """Stage admitted entity descriptors, refusing BEFORE any call is made.

    This module holds no provider and no index client. ``embed`` and
    ``index_write`` are the caller's, are keyword-only and have NO defaults, so
    this function cannot be invoked into doing I/O by accident.

    TWO refusals run before the first ``embed``, and the ordering is structural
    rather than a convention:

    1. :func:`admit_entity_records` -- which now also enforces envelope/payload
       agreement -- over the WHOLE batch, so one bad record refuses the batch
       instead of embedding the clean ones ahead of it.
    2. :func:`resolve_staging_collection` -- the destination is RESOLVED HERE,
       through the collection guards, not accepted from the caller. ``collection``
       is an optional ASSERTION: if given it must equal what the guards resolve,
       and otherwise it is refused. It cannot select a destination.

    That second one is the round-five finding. The guards existed and this
    function did not call them, so a caller naming the shared document
    collection was embedded and indexed straight into it.
    """
    admitted = admit_entity_records(records, path=path)
    resolved = resolve_staging_collection(
        adapter,
        path=path,
        instance_root=instance_root,
        entity_embedding_profile_id=entity_embedding_profile_id,
        candidate_embedding_profile_id=candidate_embedding_profile_id,
        entity_store_slugs=entity_store_slugs,
        document_profile_catalog=document_profile_catalog,
    )
    if collection is not None and collection != resolved:
        raise CallerSuppliedCollectionRefused(
            f"caller named collection {collection!r} for the {path!r} path, but this "
            f"deployment resolves {resolved!r}. The destination is not a caller's to "
            "choose: a caller that could name it could name the shared document "
            "collection, which is exactly what happened. Nothing has been embedded or "
            "indexed."
        )
    vectors = [embed(record["description"]["text"]) for record in admitted]
    index_write(resolved, tuple(zip(admitted, vectors, strict=True)))
    return StagedEntities(
        path=path, collection=resolved, records=admitted, embedded=len(vectors)
    )


def candidate_collection_name(
    adapter: Any,
    *,
    instance_root: Path,
    candidate_embedding_profile_id: str,
    entity_embedding_profile_id: str,
    entity_store_slugs: tuple[str, ...] = (),
    document_profile_catalog: tuple[str, ...] = (),
) -> str:
    """Name the candidate-only collection, or refuse.

    A candidate point must share a collection with neither the document stores
    nor the LIVE entity store. The first is the standing invariant; the second
    is this ruling's: ordinary retrieval reads the live entity collection, so a
    candidate landing there is served whatever the eligibility gate decided
    earlier.
    """
    candidate = entity_collection_name(
        adapter,
        instance_root=instance_root,
        entity_embedding_profile_id=candidate_embedding_profile_id,
        entity_store_slugs=entity_store_slugs,
        document_profile_catalog=document_profile_catalog,
    )
    live = adapter.collection_name(
        deployment_index_settings(instance_root, adapter).business_instance_id,
        entity_embedding_profile_id,
    )
    if candidate == live:
        raise EntityCollectionCollision(
            f"candidate projections would land in {candidate!r}, the LIVE entity collection. "
            f"Ordinary retrieval reads that collection, so a candidate there is served "
            f"regardless of the eligibility gate: profiles "
            f"{candidate_embedding_profile_id!r} and {entity_embedding_profile_id!r} must differ."
        )
    return candidate


assert set(DISPATCH_KEYS) == {"if", "then", "else"}, (
    "this adapter reads the contract's root if/then/else; the pin module now names "
    f"a different routing key set: {DISPATCH_KEYS}"
)
