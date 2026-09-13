"""The per-branch contract pin, and the enforcement that reads it.

A whole-file `contractSha256` went stale the moment either branch moved and
nothing computed it, so it misled rather than protected.  These tests hold the
replacement to the property that makes it worth having: each branch is pinned
independently, and ingestion refuses a branch it was not pinned against.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

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

    # R-P1/R-P7: enforcedAt is NOT checked against a list written here. A
    # hardcoded list of entrypoints is the defect that recurred twice -- it was
    # true when written and silently wrong once a third runner appeared. The
    # declaration is checked for exact set equality against the callers
    # discovered in the source by
    # test_every_load_manifest_caller_enforces_the_pin below; all this asserts
    # is that the two files agree with each other and that the list is present.
    assert pin["enforcedAt"], "contractPin declares no enforcement point"
    assert set(pin["enforcedAt"]) == set(
        yaml.safe_load(text)["source"]["connector"]["contractPin"]["enforcedAt"]
    )


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


#: R-P24. The fixture's own provenance. Everything else in this module is
#: computed FROM the fixture, so if the fixture is not the upstream file at the
#: pinned commit, every number below it is internally consistent and externally
#: meaningless.
FIXTURE_SHA256 = "899b541a8ba03431e0a129c09a8a3733b2d43057e4bb260b8bdb010dece2e8a7"
UPSTREAM_CONTRACT_PATH = "contracts/civic-impact/retrieval-export-record.schema.json"


def test_the_fixture_is_the_upstream_contract_at_the_pinned_commit() -> None:
    """R-P24. B's fixture IS A's file at the pinned commit, byte for byte, and
    that commit is really on A's history.

    Read through ``git show``, never through A's worktree: a worktree read is
    exactly what went stale and misled two people. ``SVS_STATECIVICS_REPO``
    unset is a FAILURE, not a skip (R-P5) -- a provenance check that evaporates
    on CI while reporting green is worse than no provenance check.
    """
    import hashlib

    upstream = statecivics_repo()
    commit = PINNED_CONTRACT_COMMIT

    blob = subprocess.run(
        ["git", "-C", str(upstream), "show", f"{commit}:{UPSTREAM_CONTRACT_PATH}"],
        capture_output=True, check=True,
    ).stdout
    local = FIXTURE.read_bytes()

    assert hashlib.sha256(blob).hexdigest() == FIXTURE_SHA256, (
        f"{UPSTREAM_CONTRACT_PATH} at {commit} is not the file this pin was "
        "computed from"
    )
    assert hashlib.sha256(local).hexdigest() == FIXTURE_SHA256, (
        f"{FIXTURE.name} no longer hashes to the recorded fixture digest"
    )
    assert local == blob, (
        f"{FIXTURE.name} is not byte-identical to {UPSTREAM_CONTRACT_PATH} at "
        f"{commit}; the pin is computed from a file upstream does not have"
    )

    # A digest proves the bytes; it does not prove the commit is real history.
    # A commit that is not an ancestor of `main` is a dangling or abandoned
    # object, and pinning to one is how a pin outlives the work it pinned.
    ancestry = subprocess.run(
        ["git", "-C", str(upstream), "merge-base", "--is-ancestor", commit, "main"],
        capture_output=True,
    )
    assert ancestry.returncode == 0, (
        f"{commit} is not an ancestor of StateCivics main; the contract pin "
        f"does not point at landed upstream history (git said: "
        f"{ancestry.stderr.decode().strip()!r})"
    )


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


# --- R-P7: the enforcement points are DISCOVERED, never enumerated ------------
#
# A hand-maintained list of the document consumer's callers went stale twice.
# Round one listed one entrypoint while a second ran unpinned; round two listed
# two while a third, kansas-fiscal-marker-handoff.py, ran unpinned. The fix is a
# construction: walk the tracked source, resolve every call to the consumer's
# load_manifest BY MODULE IDENTITY, and require the declaration to equal what
# was found. Nothing below names a caller, and nothing below skips one.

FISCAL_CONSUMER = (REPO / "scripts" / "release" / "kansas-fiscal-document-ingest.py").resolve()
CONSUMER_FUNCTION = "load_manifest"
PIN_FLAG = "--contract-schema"


class Unclassified(Exception):
    """The walker could not decide which module a call site reaches.

    This is never swallowed. A check that breaks must fail toward blocking, so
    an unresolvable call site fails the test rather than being skipped: the one
    thing worse than an unenforced caller is an unenforced caller the checker
    silently declined to look at.
    """


def _tracked_python_files() -> list[Path]:
    """Every Python file this repository would ship or review.

    ``--cached`` is what is committed, ``--others --exclude-standard`` is what a
    developer has added but not yet committed; together they are the source
    tree. Ignored trees (vendored upstream research checkouts) are not B's
    source and cannot become a runner.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "*.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    paths = {REPO / name for name in listing.split("\0") if name}
    # The repository's OWN suite -- the top-level tests/ directory -- is
    # excluded by SCOPE, not by name-matching a caller: it deliberately calls
    # the consumer both with and without a schema to prove both behaviours, and
    # it is not a runner that could appear in enforcedAt. The exclusion is
    # anchored at parts[0] because that is exactly what the justification
    # covers; a tests/ directory nested anywhere else (a connector's suite, a
    # vendored package's suite) belongs to some other component and is in scope
    # like every other tracked path.
    return sorted(
        p for p in paths
        if p.relative_to(REPO).parts[0] != "tests" and p.is_file()
    )


_SCOPE_BOUNDARIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

#: Scopes Python opens for an EXPRESSION. `_visit` descends into these
#: explicitly, with their own scope pushed through `_push`, so that class
#: scopes drop for them exactly as they do for a `def`.
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_EXPRESSION_SCOPES = (ast.Lambda,) + _COMPREHENSIONS


def _same_file(left: Path, right: Path) -> bool:
    """Filesystem IDENTITY, not path-string equality.

    R-P26/F4. ``Path.resolve()`` resolves symlinks but does NOT canonicalise
    case, and this tree lives on a case-insensitive filesystem. So
    ``scripts/release/Kansas-Fiscal-Document-Ingest.py`` and
    ``scripts/release/kansas-fiscal-document-ingest.py`` are THE SAME FILE --
    ``os.path.samefile`` says so, and importlib loads the same bytes from
    either -- while ``==`` on the two ``Path`` objects is False. Comparing the
    strings let a real caller of the fiscal consumer present itself as some
    other module and pass the gate in silence.

    A target that does not exist cannot be the consumer, because the consumer
    does exist; ``samefile`` raises ``OSError`` in that case rather than
    answering, so the fallback is plain equality, which keeps a non-existent
    spec target from crashing the walker while still answering False for
    everything that is not literally the consumer's own path.
    """
    try:
        return os.path.samefile(left, right)
    except OSError:
        return left == right


def _scope_nodes(statement: ast.AST):
    """``statement`` and every descendant that shares its scope.

    A nested def is yielded but never entered, so a function's own bindings
    never leak into the enclosing scope and cannot resolve a name that is not
    actually visible at a call site.
    """
    yield statement
    if isinstance(statement, _SCOPE_BOUNDARIES):
        return
    for child in ast.iter_child_nodes(statement):
        yield from _scope_nodes(child)


def _nested_scope_nodes(body: list[ast.stmt]):
    """Every node inside a scope NESTED within ``body``.

    Exactly what ``_scope_nodes`` refuses to enter. Ordinary bindings must stay
    out -- that refusal is Python's scoping and the whole reason a nested
    function's locals cannot resolve a name at an outer call site. Two forms
    are not ordinary: ``global`` and ``nonlocal`` reach back OUT of the scope
    they are written in and rebind a name in an enclosing one. They are the
    only declarations that do, so they are the only thing read from here.
    """
    for statement in body:
        for node in _scope_nodes(statement):
            if isinstance(node, _SCOPE_BOUNDARIES):
                for descendant in ast.walk(node):
                    if descendant is not node:
                        yield descendant


def _add_reaching_declarations(env, body, declaration, label) -> None:
    """Count every ``global``/``nonlocal`` NAME declared in a NESTED scope as a
    binding of NAME in THIS scope.

    R-P26, found in-round by the binding-form battery. ``_scope_env`` recorded
    a ``global`` only in the function that wrote it, so a module-level name
    assigned once at module scope and REWRITTEN by ``global`` inside any
    function looked bound exactly once, and form 2 resolved it CONFIDENTLY AND
    WRONGLY -- executed, in both directions, including the unsafe one where the
    call really does reach the fiscal consumer without a pin and the walker
    reports it as some other module and says nothing.

    A bare ``global x`` binds nothing by itself, so counting it is conservative
    by construction: it can only add a binding and therefore only ever refuse.
    """
    for node in _nested_scope_nodes(body):
        if isinstance(node, declaration):
            for name in node.names:
                env.setdefault(name, []).append(_Binding(node, node.lineno, label))


def _visit_nodes(node: ast.AST):
    """``node`` and every descendant ``_visit`` should classify in THIS scope.

    ``_scope_nodes`` with one addition: it also stops at a lambda or a
    comprehension. Those open real scopes, and ``_visit`` descends into them
    explicitly so their own env goes on through ``_push`` -- which is what
    makes an enclosing CLASS scope drop for them, exactly as it does for a
    ``def``.

    Binding COLLECTION (``_scope_env``) deliberately keeps using
    ``_scope_nodes``, which does NOT stop here, so a lambda parameter or a
    comprehension target is still counted in the enclosing scope as well. That
    over-counting only ever refuses, and it is retained.
    """
    yield node
    if isinstance(node, _SCOPE_BOUNDARIES + _EXPRESSION_SCOPES):
        return
    for child in ast.iter_child_nodes(node):
        yield from _visit_nodes(child)


def _definition_time_expressions(node: ast.AST):
    """The sub-expressions of a ``def``/``class`` that run in the ENCLOSING scope.

    Python evaluates decorators, parameter defaults, annotations and base
    classes when the ``def``/``class`` statement itself executes, in the scope
    that contains it -- not inside the scope the statement opens. A positional
    default is a genuine executing call.

    They are therefore yielded so the caller can visit them with the ENCLOSING
    ``envs``. Resolving a default's names against the function's own scope would
    invent bindings that are not visible where the expression actually runs, so
    ``_scope_nodes``'s refusal to enter a scope boundary is preserved: only
    ``node.body`` is walked under the new scope.
    """
    yield from node.decorator_list
    if isinstance(node, ast.ClassDef):
        yield from node.bases
        for keyword in node.keywords:
            yield keyword.value
        return
    arguments = node.args
    for default in (*arguments.defaults, *arguments.kw_defaults):
        if default is not None:
            yield default
    for argument in (*arguments.posonlyargs, *arguments.args,
                     *arguments.kwonlyargs, arguments.vararg, arguments.kwarg):
        if argument is not None and argument.annotation is not None:
            yield argument.annotation
    if node.returns is not None:
        yield node.returns


class _Binding:
    """One place a name is bound, and the node resolution should read for it.

    ``node`` is what the value of the name is, when the form even has one: an
    ``Assign``'s right-hand side, an ``Import`` statement.  Forms that bind
    without a statically readable value -- a ``for`` target, a parameter, an
    ``except`` name -- store the binding statement itself, which every
    resolver below then refuses.  Refusing is the point: the name is bound, so
    it must be counted, and it is not resolvable, so it must not resolve.
    """

    __slots__ = ("node", "lineno", "form")

    def __init__(self, node: ast.AST, lineno: int, form: str) -> None:
        self.node = node
        self.lineno = lineno
        self.form = form


# R-P16. A write into the namespace MAPPING rebinds names without any binding
# target for the visitor below to see, and so does executing generated source.
# Neither can be attributed to a particular name, so a module containing one
# resolves nothing at all. This is a module-wide guard rather than a binding
# form precisely because it is not attributable.
_NAMESPACE_BUILTINS = frozenset({"globals", "locals", "vars"})
_EXECUTORS = frozenset({"exec", "eval"})
_OPAQUE = "*namespace-write*"


def _is_namespace_write(node: ast.AST) -> bool:
    # R-P26/F3. `from X import *` binds every public name X exports, and which
    # names those are is a property of ANOTHER module at import time. It is not
    # attributable to any one name here -- which is the definition of this
    # guard -- and `_scope_env`'s ImportFrom arm could not see it at all: for a
    # star the alias node's `name` is the literal "*", so it bound a name
    # spelled "*" and left `load_manifest` looking bound exactly once. A module
    # that defines `load_manifest` and then star-imports over it was granted
    # form 1 while Python called somebody else's function.
    if isinstance(node, ast.ImportFrom):
        if any(alias.name == "*" for alias in node.names):
            return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in _EXECUTORS:
            return True
    targets: tuple[ast.AST, ...] = ()
    if isinstance(node, ast.Assign):
        targets = tuple(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = (node.target,)
    elif isinstance(node, ast.Delete):
        targets = tuple(node.targets)
    for target in targets:
        if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Call)
                and isinstance(target.value.func, ast.Name)
                and target.value.func.id in _NAMESPACE_BUILTINS):
            return True
    return False


def _bound_names(target: ast.AST):
    """Every ``Name`` a binding target binds. Tuples and stars are UNPACKED.

    ``Attribute`` and ``Subscript`` targets bind no name in this scope; they
    mutate an object, which is a different question.
    """
    if isinstance(target, ast.Name):
        yield target
    elif isinstance(target, ast.Starred):
        yield from _bound_names(target.value)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _bound_names(element)


def _parameters(node: ast.AST):
    """The ``arg`` nodes a ``def``/``lambda`` binds in the scope it opens."""
    arguments = node.args
    for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs,
                     arguments.vararg, arguments.kwarg):
        if argument is not None:
            yield argument


def _scope_env(body: list[ast.stmt], parameters=()) -> dict[str, list[_Binding]]:
    """R-P16/R-P17. Every name this scope binds, and EVERY place it binds it.

    ONE visitor, every binding form Python has: ``Assign``, ``AnnAssign``,
    ``AugAssign``, ``NamedExpr``, ``Import``/``ImportFrom``, ``for`` targets,
    ``with ... as``, ``except ... as``, ``def``/``async def``/``class`` names,
    ``global``/``nonlocal`` declarations, ``match`` captures, and parameters.
    Tuple and starred targets are unpacked.

    The walk is ``_scope_nodes``, so a rebinding in EITHER arm of an ``if``, in
    a branch that cannot run, or textually AFTER the call all count. That is
    what makes flow sensitivity a refusal instead of a guess: the env carries a
    list per name and ``_lookup`` refuses any name whose list is longer than
    one, rather than silently keeping whichever binding came last.

    Lambdas and comprehensions open their own scopes, but ``_scope_nodes``
    walks their bodies as part of THIS scope (they are expressions, not
    ``_SCOPE_BOUNDARIES``), so a call inside one is resolved against this env.
    Their parameters and ``for`` targets are therefore recorded HERE, which
    over-counts a name that is only lambda-local. Over-counting refuses; not
    counting would resolve ``lambda ingest: ingest.load_manifest(...)`` against
    an unrelated module-level ``ingest``, which is a wrong answer given
    confidently. Refusing is the posture.
    """
    env: dict[str, list[_Binding]] = {}

    def bind(name: str, node: ast.AST, lineno: int, form: str) -> None:
        env.setdefault(name, []).append(_Binding(node, lineno, form))

    for argument in parameters:
        bind(argument.arg, argument, argument.lineno, "parameter")

    for statement in body:
        for node in _scope_nodes(statement):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in _bound_names(target):
                        bind(name.id, node.value, name.lineno, "assignment")
            elif isinstance(node, ast.AnnAssign):
                value = node.value if node.value is not None else node
                for name in _bound_names(node.target):
                    bind(name.id, value, name.lineno, "annotated assignment")
            elif isinstance(node, ast.AugAssign):
                for name in _bound_names(node.target):
                    bind(name.id, node, name.lineno, "augmented assignment")
            elif isinstance(node, ast.NamedExpr):
                for name in _bound_names(node.target):
                    bind(name.id, node.value, name.lineno, "walrus")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bind(alias.asname or alias.name.split(".")[0], node,
                         node.lineno, "import")
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                for name in _bound_names(node.target):
                    bind(name.id, node, name.lineno, "for target")
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        for name in _bound_names(item.optional_vars):
                            bind(name.id, node, name.lineno, "with target")
            elif isinstance(node, ast.ExceptHandler):
                if node.name:
                    bind(node.name, node, node.lineno, "except handler")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bind(node.name, node, node.lineno, "def/class statement")
            elif isinstance(node, ast.Global):
                for name in node.names:
                    bind(name, node, node.lineno, "global declaration")
            elif isinstance(node, ast.Nonlocal):
                for name in node.names:
                    bind(name, node, node.lineno, "nonlocal declaration")
            elif isinstance(node, (ast.MatchAs, ast.MatchStar)):
                if node.name:
                    bind(node.name, node, node.lineno, "match capture")
            elif isinstance(node, ast.MatchMapping):
                if node.rest:
                    bind(node.rest, node, node.lineno, "match mapping rest")
            elif isinstance(node, ast.Lambda):
                for argument in _parameters(node):
                    bind(argument.arg, argument, argument.lineno, "lambda parameter")
            elif isinstance(node, ast.comprehension):
                for name in _bound_names(node.target):
                    bind(name.id, node.target, name.lineno, "comprehension target")
    return env


class _Scope:
    """One scope in a chain, and WHAT KIND of scope it is.

    The kind is load-bearing because Python's name resolution is not "every
    enclosing block". A ``class`` body is a scope, but it is NOT part of the
    enclosing chain any nested ``def`` searches: a method does not see the
    names its class body binds. Round six pushed class-body bindings into
    method scopes, so the walker's scope order was not Python's IN BOTH
    DIRECTIONS -- a class attribute could resolve a method's alias to the wrong
    module (a confident wrong answer), and a class attribute bound twice could
    refuse a method the language would have resolved cleanly (a false refusal).
    """

    __slots__ = ("env", "kind")

    def __init__(self, env: dict[str, list[_Binding]], kind: str) -> None:
        self.env = env
        self.kind = kind


def _push(envs: tuple[_Scope, ...], env, kind: str) -> tuple[_Scope, ...]:
    """The chain a new ``def``/``class`` scope actually searches.

    Python: local scope, then enclosing FUNCTION scopes, then module, then
    builtins. Class scopes never appear in that chain, not even for a class
    nested directly inside another class, so entering ANY new scope drops every
    class scope already on the chain before appending the new one. Code written
    DIRECTLY in a class body does see that class's own bindings, which is
    exactly the innermost entry this returns.
    """
    return tuple(scope for scope in envs if scope.kind != "class") + (_Scope(env, kind),)


def _lookup(name: str, envs: tuple[_Scope, ...], where) -> ast.AST:
    """R-P17. Resolve ``name`` to the ONE binding that is provably its binding.

    The multiplicity refusal fires HERE, for the name actually being resolved,
    never while the env is built. Building it at env-build time would block
    every module that rebinds any ordinary variable -- a loop accumulator, a
    reassigned counter -- and the check would be useless. Measured over the
    tracked tree, this placement gives zero false positives; at env-build time
    the identical rule blocks 122 of the 152 tracked modules.
    """
    for scope in envs:
        env = scope.env
        if _OPAQUE in env:
            lines = sorted({binding.lineno for binding in env[_OPAQUE]})
            raise Unclassified(
                f"{where}: the module writes into its own namespace mapping, "
                f"executes generated source, or star-imports (lines {lines}); "
                "no name in it is provably bound once"
            )
    for scope in reversed(envs):
        bindings = scope.env.get(name)
        if not bindings:
            continue
        if len(bindings) > 1:
            raise Unclassified(
                f"{where}: {name!r} is bound more than once in its scope "
                f"(lines {sorted(binding.lineno for binding in bindings)}, as "
                f"{sorted({binding.form for binding in bindings})}); which "
                "binding reaches this call is ambiguous"
            )
        binding = bindings[0]
        if binding.form in ("global declaration", "nonlocal declaration"):
            raise Unclassified(
                f"{where}:{binding.lineno}: {name!r} is declared "
                f"{binding.form.split()[0]}, so it is bound somewhere this "
                "scope cannot see and its value here is ambiguous"
            )
        return binding.node
    raise Unclassified(f"name {name!r} is not bound in any enclosing scope")


def _callee_name(func: ast.AST) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _eval_path(node: ast.AST, envs: tuple[dict[str, ast.AST], ...], own: Path):
    """Symbolically evaluate a path-valued expression.

    Understands exactly the pathlib vocabulary this tree uses to point at
    another script. Anything else raises, which blocks.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return _eval_path(_lookup(node.id, envs, own), envs, own)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _eval_path(node.left, envs, own)
        right = _eval_path(node.right, envs, own)
        if not isinstance(left, Path):
            raise Unclassified("path division on a non-path left operand")
        return left / right
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        return Path(_eval_path(node.value, envs, own)).parent
    if isinstance(node, ast.Subscript):
        value = node.value
        index = node.slice
        if (isinstance(value, ast.Attribute) and value.attr == "parents"
                and isinstance(index, ast.Constant) and isinstance(index.value, int)):
            return Path(_eval_path(value.value, envs, own)).parents[index.value]
        raise Unclassified("unsupported subscript in a path expression")
    if isinstance(node, ast.Call):
        func = node.func
        if (isinstance(func, ast.Name) and func.id == "Path" and len(node.args) == 1
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "__file__"):
            return own
        if isinstance(func, ast.Attribute):
            base = _eval_path(func.value, envs, own)
            if func.attr == "resolve":
                return Path(base).resolve()
            if func.attr == "absolute":
                return Path(base).absolute()
            if func.attr == "with_name" and len(node.args) == 1:
                return Path(base).parent / _eval_path(node.args[0], envs, own)
            if func.attr == "joinpath":
                result = Path(base)
                for argument in node.args:
                    result = result / _eval_path(argument, envs, own)
                return result
        raise Unclassified(f"unsupported call in a path expression: {ast.dump(node)[:90]}")
    raise Unclassified(f"unsupported path expression: {ast.dump(node)[:90]}")


def _spec_target(node: ast.AST, envs, own: Path) -> Path | None:
    """If ``node`` is ``spec_from_file_location(name, target)``, return target."""
    if not isinstance(node, ast.Call) or _callee_name(node.func) != "spec_from_file_location":
        return None
    if len(node.args) < 2:
        raise Unclassified("spec_from_file_location without a file argument")
    return Path(_eval_path(node.args[1], envs, own)).resolve()


class _Module:
    """One source file, and the module identity of every name it binds."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # R-P22. There is no precomputed factory table and no
        # `defines_consumer_function` flag. Both were resolution facts decided
        # at construction time, away from the names actually being resolved:
        # the table was indexed by callee name with no check that the name was
        # still bound to the function that filled it in, and the flag answered
        # "does this module define load_manifest at top level?" for a call site
        # whose own scope chain might bind the name to something else entirely.
        # Every such fact is now derived inside `_module_identity`, for the one
        # name being resolved, at the moment it is resolved.
        # R-P10. The ONE record of what the classifier actually looked at.
        # `_block_on_unresolved_references` complements against this and
        # nothing else, so there is no second predicate to keep in step.
        self.classified_call_funcs: set[int] = set()
        # R-P16. Not a binding form -- a namespace-mapping write cannot be
        # attributed to any one name -- so it is a module-wide guard injected
        # into the module env and refused at LOOKUP time like everything else.
        self.namespace_writes = [
            node for node in ast.walk(self.tree) if _is_namespace_write(node)
        ]

    def module_env(self) -> dict[str, list[_Binding]]:
        env = _scope_env(self.tree.body)
        _add_reaching_declarations(
            env, self.tree.body, ast.Global,
            "global rebinding declared in a nested scope")
        if self.namespace_writes:
            env[_OPAQUE] = [
                _Binding(node, node.lineno, "namespace write")
                for node in self.namespace_writes
            ]
        return env

    def _module_scope(self) -> tuple[_Scope, ...]:
        return (_Scope(self.module_env(), "module"),)

    # ------------------------------------------------------------------
    # R-P22. THE CHOKE POINT.
    #
    # Every call site that becomes a module identity passes through
    # `_module_identity` and through nothing else. Six rounds failed because
    # the defect kept relocating to whichever enumerated surface the previous
    # round had not hardened -- callers, then spellings, then traversals, then
    # alias binding, then the resolution paths the refusal happened to be
    # wired into. The answer is not a seventh enumeration. It is a BOUND: three
    # forms are accepted, each stated in full below, and every other program
    # raises `Unclassified`. A form is accepted only when every name in its
    # chain is bound exactly once under the R-P16 binding visitor, applied AT
    # RESOLUTION TIME to the names actually being resolved.
    # ------------------------------------------------------------------

    def _module_identity(self, node: ast.Call, envs) -> tuple[Path, str]:
        """The file the module reached by ``node``'s callee was loaded from.

        Raises `Unclassified` for every program outside the three forms. There
        is deliberately no fallback branch: a program the walker cannot place
        in a form is refused, never guessed at.
        """
        func = node.func
        if isinstance(func, ast.Name):
            return self._form_one(node, envs)
        if not isinstance(func, ast.Attribute):
            raise Unclassified(
                f"{self.path}:{node.lineno}: {CONSUMER_FUNCTION} is called "
                "through neither a bare name nor an attribute of a name"
            )
        if not isinstance(func.value, ast.Name):
            raise Unclassified(
                f"{self.path}:{node.lineno}: {CONSUMER_FUNCTION} is called on a "
                "non-name expression; its module cannot be resolved"
            )
        alias = func.value.id
        bound = _lookup(alias, envs, self.path)
        if isinstance(bound, (ast.Import, ast.ImportFrom)):
            raise Unclassified(
                f"{self.path}:{node.lineno}: {alias!r} is an imported module; "
                "its file identity is not statically resolvable here"
            )
        if not isinstance(bound, ast.Call):
            raise Unclassified(
                f"{self.path}:{node.lineno}: {alias!r} is not bound to a call, "
                f"so it is neither form 2 nor form 3: {ast.dump(bound)[:110]}"
            )
        if _callee_name(bound.func) == "module_from_spec":
            return self._form_three(alias, bound, envs)
        if isinstance(bound.func, ast.Name):
            return self._form_two(alias, bound.func.id, node, envs)
        raise Unclassified(
            f"{self.path}:{node.lineno}: {alias!r} is bound to a call of "
            f"{ast.dump(bound.func)[:80]}, which is neither a module-scope "
            "factory name (form 2) nor module_from_spec (form 3)"
        )

    # --- form 1 -------------------------------------------------------------

    def _form_one(self, node: ast.Call, envs) -> tuple[Path, str]:
        """A bare ``load_manifest(...)`` that provably reaches THIS module's own
        top-level definition of that name.

        The name is resolved through the ordinary scope chain, so a local
        ``from ... import load_manifest``, a parameter, a ``for`` target or any
        other shadowing binding is found FIRST and refused -- it is not the
        module's top-level ``def``. Round six's bare-call branch consulted no
        environment at all: it asked only whether the module had a top-level
        ``def`` of the name somewhere, and answered `self.path` for a call that
        a shadowing binding sent somewhere else entirely.
        """
        binding = _lookup(CONSUMER_FUNCTION, envs, self.path)
        if not (isinstance(binding, (ast.FunctionDef, ast.AsyncFunctionDef))
                and binding.name == CONSUMER_FUNCTION
                and any(binding is statement for statement in self.tree.body)):
            raise Unclassified(
                f"{self.path}:{node.lineno}: bare {CONSUMER_FUNCTION}() does "
                "not resolve to a top-level def of that name in this module; "
                f"the name is bound here by {ast.dump(binding)[:100]}"
            )
        if binding.decorator_list:
            raise Unclassified(
                f"{self.path}:{binding.lineno}: {CONSUMER_FUNCTION} is "
                f"decorated ({len(binding.decorator_list)} decorator(s)), so "
                "the name does not necessarily reach the body written under "
                "it and the module this call lands in cannot be read from it"
            )
        return self.path, "form 1 (bare call in the defining module)"

    # --- form 2 -------------------------------------------------------------

    def _form_two(self, alias: str, factory: str, node: ast.Call, envs) -> tuple[Path, str]:
        """``alias = factory()`` where ``factory`` is a module-scope, UNDECORATED
        ``def`` with exactly one spec target.

        Every clause is checked here, at resolution time, for this factory
        name, IN THE SCOPE CHAIN THE CALL SITE ACTUALLY HAS. Round six read a
        table built at construction time and indexed it by callee name, so a
        factory name REBOUND after its ``def``
        (``_load_fiscal = _load_other``) still answered with the def's target,
        and a DECORATED factory -- whose decorator may return anything at all
        -- answered with the target of a body that no longer runs.

        R-P26/F1. This then resolved the factory name against a FABRICATED
        chain -- ``self._module_scope()``, hardcoded -- rather than the ``envs``
        it was handed. The ALIAS binding was flow-sensitive; the factory name
        the alias pointed at was not, so a LOCAL rebinding of the factory name
        was invisible:

            def main():
                _load_other = _load_fiscal
                ingest = _load_other()
                return ingest.load_manifest(Path("m"))

        Every stated precondition of form 2 held, the walker answered
        ``kscourts-ingest.py``, and the call reached the fiscal consumer, which
        raised ``--contract-schema is required``. A parameter default
        (``def run(_load_other=_load_fiscal)``) did the same. Resolving through
        ``envs`` finds the local binding first; it is not a module-level ``def``,
        so it refuses.
        """
        definition = _lookup(factory, envs, self.path)
        if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise Unclassified(
                f"{self.path}:{node.lineno}: {alias!r} is bound to {factory}(), "
                f"but in this scope chain {factory!r} is not bound to a def: "
                f"{ast.dump(definition)[:100]}"
            )
        if not any(definition is statement for statement in self.tree.body):
            raise Unclassified(
                f"{self.path}:{node.lineno}: {factory!r} is not defined at "
                "module scope, so what the call reaches is ambiguous"
            )
        if definition.decorator_list:
            raise Unclassified(
                f"{self.path}:{definition.lineno}: {factory!r} is decorated "
                f"({len(definition.decorator_list)} decorator(s)), so its "
                "return value is the decorator's, not its body's, and the "
                "module it yields cannot be read from the body"
            )
        factory_env = _scope_env(definition.body, _parameters(definition))
        _add_reaching_declarations(
            factory_env, definition.body, ast.Nonlocal,
            "nonlocal rebinding declared in a nested scope")
        factory_envs = _push(self._module_scope(), factory_env, "function")
        # Two clauses, both required: the factory MENTIONS exactly one module,
        # and the module it RETURNS is that one. Either alone is satisfiable by
        # a function that builds a decoy spec and hands back something else.
        mentioned = self._sole_spec_target(definition, factory_envs)
        returned = self._factory_return_target(definition, factory_envs)
        if not _same_file(mentioned, returned):
            raise Unclassified(
                f"{self.path}:{definition.lineno}: {factory}() builds a spec "
                f"for {mentioned} but returns the module loaded from "
                f"{returned}; what it yields is not what it names"
            )
        return returned, f"form 2 (alias {alias!r} <- {factory}() -> spec target)"

    def _module_from_spec_target(self, expression, envs, where: str) -> Path:
        """The file behind ``module_from_spec(X)``, or behind a name bound to one.

        The single implementation of form 3's chain. Form 2 uses it too, on the
        factory's RETURN value, so "this factory yields that module" is decided
        by what the factory actually hands back rather than by what it merely
        mentions.
        """
        node = expression
        if isinstance(node, ast.Name):
            node = _lookup(node.id, envs, self.path)
        if not (isinstance(node, ast.Call)
                and _callee_name(node.func) == "module_from_spec"):
            raise Unclassified(
                f"{where}: not a module_from_spec(...) call: "
                f"{ast.dump(node)[:100]}"
            )
        if len(node.args) != 1 or node.keywords:
            raise Unclassified(
                f"{where}: module_from_spec is called with {len(node.args)} "
                f"positional and {len(node.keywords)} keyword argument(s); "
                "exactly one positional spec is accepted"
            )
        argument = node.args[0]
        if not isinstance(argument, ast.Name):
            raise Unclassified(
                f"{where}: module_from_spec's argument is not a name bound to a "
                "spec, so the spec cannot be resolved through the binding visitor"
            )
        spec_node = _lookup(argument.id, envs, self.path)
        if not (isinstance(spec_node, ast.Call)
                and _callee_name(spec_node.func) == "spec_from_file_location"):
            raise Unclassified(
                f"{where}: {argument.id!r} is not bound to a "
                f"spec_from_file_location(...) call: {ast.dump(spec_node)[:100]}"
            )
        target = _spec_target(spec_node, envs, self.path)
        if target is None:
            raise Unclassified(
                f"{where}: the spec bound to {argument.id!r} has no resolvable "
                "file target"
            )
        return target

    def _factory_return_target(self, definition, envs) -> Path:
        """The module the factory actually RETURNS.

        R-P26, found in-round. "Builds exactly one spec" is a claim about what
        a function MENTIONS, not about what it yields, and the two come apart:

            def _decoy():
                spec = spec_from_file_location("d", <kscourts-ingest.py>)
                return _fiscal          # built elsewhere, at module scope

        One spec target, undecorated, module-scope, every name bound once --
        squarely inside accepted form 2 -- and the walker answered
        `kscourts-ingest.py` for a call that reaches the FISCAL consumer with no
        pin, then said nothing. A SILENT PASS, the exact outcome this check
        exists to prevent. Requiring every `return` in the factory's own scope
        to be form 3 closes it: what the factory hands back is what its
        identity is.
        """
        returns = [node for statement in definition.body
                   for node in _scope_nodes(statement)
                   if isinstance(node, ast.Return)]
        if not returns:
            raise Unclassified(
                f"{self.path}:{definition.lineno}: {definition.name}() has no "
                "return statement in its own scope, so it yields no module"
            )
        targets = set()
        for node in returns:
            if node.value is None:
                raise Unclassified(
                    f"{self.path}:{node.lineno}: {definition.name}() has a bare "
                    "`return`, so on that path it yields no module"
                )
            targets.add(self._module_from_spec_target(
                node.value, envs, f"{self.path}:{node.lineno}"))
        if len(targets) != 1:
            raise Unclassified(
                f"{self.path}:{definition.lineno}: {definition.name}() returns "
                f"{len(targets)} different modules "
                f"({sorted(str(t) for t in targets)})"
            )
        return next(iter(targets))

    def _sole_spec_target(self, definition, envs) -> Path:
        """The ONE file ``definition`` builds a module spec from.

        Resolution time, for this one function: nothing is computed for the
        other functions in the module, so a sibling helper that happens to
        build two specs cannot refuse a caller that never touches it.
        """
        targets = set()
        for sub in ast.walk(definition):
            target = _spec_target(sub, envs, self.path)
            if target is not None:
                targets.add(target)
        if len(targets) != 1:
            raise Unclassified(
                f"{self.path}:{definition.lineno}: {definition.name}() builds "
                f"{len(targets)} module spec(s) "
                f"({sorted(str(t) for t in targets)}); its return value is not "
                "provably one module"
            )
        return next(iter(targets))

    # --- form 3 -------------------------------------------------------------

    def _form_three(self, alias: str, bound: ast.Call, envs) -> tuple[Path, str]:
        """``alias = module_from_spec(X)`` with ``X = spec_from_file_location(...)``.

        The INLINE spelling of form 2, with no factory function to name. It is
        required, not a convenience: `scripts/release/kansas-statute-rollout.py`
        binds its consumer alias exactly this way, and it is a real fiscal
        enforcement point. Every name in the chain -- the alias, the spec name,
        and whatever the path argument reads -- goes through `_lookup`, so each
        must be bound exactly once under the same discipline.
        """
        target = self._module_from_spec_target(
            bound, envs, f"{self.path}:{bound.lineno}")
        return target, f"form 3 (alias {alias!r} <- module_from_spec -> spec target)"

    def call_sites(self) -> list[dict]:
        """Every call to a function named ``load_manifest``, each carrying the
        resolved file of the module it actually reaches."""
        found: list[dict] = []
        self.classified_call_funcs = set()
        # Order is load-bearing: the classifier runs first so that the set it
        # fills in IS the exemption set the blocker then complements. If
        # `_walk` raises part way, the record is partial and MORE references
        # block -- the check fails toward blocking either way.
        self._visit_body(self.tree.body, self._module_scope(), found)
        self._block_on_unresolved_references()
        return found

    def _block_on_unresolved_references(self) -> None:
        """Block on every reference to the consumer function that the CLASSIFIER
        did not see.

        R-P10. The exemption set is not computed here. It IS
        ``self.classified_call_funcs``, which ``_classify`` writes at the one
        point it commits to a call. There is exactly one traversal, ``_visit``,
        and exactly one line that decides what "the walker resolved this"
        means; this rule is its complement, so whatever the classifier did not
        resolve blocks.

        Round four computed the exemption set here instead, from a SECOND
        ``ast.walk`` over the whole module tree, while classification entered
        through ``_walk``/``_scope_nodes``, which yields a ``def``/``class`` and
        then returns without visiting its ``decorator_list``, ``args.defaults``,
        ``args.kw_defaults``, annotations or ``ClassDef.bases``. Those positions
        were exempted by one traversal and never reached by the other, so the
        identical expression ``ingest.load_manifest(Path("m"))`` failed in
        statement position and passed SILENTLY in five of them. Two predicates
        maintained separately diverge. There is now only one.
        """
        for node in ast.walk(self.tree):
            if id(node) in self.classified_call_funcs:
                continue
            if isinstance(node, ast.Attribute) and node.attr == CONSUMER_FUNCTION:
                shape = "an attribute reference the classifier never resolved"
            elif (isinstance(node, ast.Name) and node.id == CONSUMER_FUNCTION
                    and isinstance(node.ctx, ast.Load)):
                shape = "a bare name load the classifier never resolved"
            elif (isinstance(node, ast.Subscript)
                    and isinstance(node.slice, ast.Constant)
                    and node.slice.value == CONSUMER_FUNCTION):
                shape = f"a subscript by the constant {CONSUMER_FUNCTION!r}"
            else:
                continue
            raise Unclassified(
                f"{self.path}:{node.lineno}: {CONSUMER_FUNCTION} appears as "
                f"{shape}. The function object can be bound to another name and "
                "called where the walker never sees it, so whether that call "
                "passes contract_schema cannot be decided statically."
            )

    def _walk(self, node, envs, found) -> None:
        """Walk the body of the ``def``/``class`` ``node`` opens.

        A ``def``'s PARAMETERS seed the env it opens: without them a parameter
        named like a module-level alias would fall through to the module env
        and resolve to the wrong module -- a confident wrong answer, the very
        thing R-P16 exists to convert into a refusal.

        The new chain comes from `_push`, which applies Python's rule that a
        ``class`` scope is not part of the chain any nested scope searches.
        """
        if isinstance(node, ast.ClassDef):
            env = _scope_env(node.body)
            kind = "class"
        else:
            env = _scope_env(node.body, _parameters(node))
            kind = "function"
        # A nested `nonlocal` rebinds a name in THIS scope, the same way a
        # nested `global` rebinds one at module scope.
        _add_reaching_declarations(
            env, node.body, ast.Nonlocal,
            "nonlocal rebinding declared in a nested scope")
        self._visit_body(node.body, _push(envs, env, kind), found)

    def _visit_body(self, body, envs, found) -> None:
        for statement in body:
            self._visit(statement, envs, found)

    def _visit(self, node_or_expression, envs, found) -> None:
        """Classify every call under ``node_or_expression`` that runs in ``envs``.

        This is the walker's only traversal. Every ``Call`` it reaches is
        handed to ``_classify``, which records the ones it commits to; the
        blocker's exemption set is that record and nothing else.
        """
        for node in _visit_nodes(node_or_expression):
            if isinstance(node, _EXPRESSION_SCOPES):
                self._visit_expression_scope(node, envs, found)
            elif isinstance(node, _SCOPE_BOUNDARIES):
                # R-P11. A decorator, a parameter default, an annotation and a
                # class base all execute where the `def`/`class` is WRITTEN, at
                # definition time, so they are visited with the enclosing
                # `envs` -- never with the new scope's env, which `_walk`
                # builds only for `node.body` on the next line. Resolving a
                # default's names against the inner scope would produce wrong
                # resolutions; `_scope_nodes` still refuses to enter the
                # boundary, so inner bindings do not leak outward.
                for outer in _definition_time_expressions(node):
                    self._visit(outer, envs, found)
                self._walk(node, envs, found)
            elif isinstance(node, ast.Call):
                site = self._classify(node, envs)
                if site is not None:
                    found.append(site)

    def _visit_expression_scope(self, node, envs, found) -> None:
        """A lambda or a comprehension: its own scope, pushed through ``_push``.

        R-P26/F2. ``_push`` already dropped class scopes when entering a
        ``def``, which is Python's rule -- but a lambda and a comprehension
        never went through ``_push`` at all, so inside a CLASS BODY they kept
        resolving against the class scope Python skips:

            ingest = _load_fiscal()

            class Runner:
                ingest = _load_other()
                results = [ingest.load_manifest(Path("m")) for _ in range(1)]

        Python evaluates that comprehension in a scope whose parent chain is
        module-only, so the call reaches the FISCAL consumer. The walker
        answered ``kscourts-ingest.py`` and the gate stayed green. The lambda
        twin behaved identically.

        This also corrects the reasoning ``_scope_env`` records for itself:
        counting a lambda parameter or comprehension target in the ENCLOSING
        scope over-counts, and over-counting refuses -- true in a module or
        function body, but NOT inside a class body, where the enclosing entry
        the walker consulted was the class scope. There it UNDER-counted,
        hiding the module-level binding Python actually uses. Routing these
        scopes through ``_push`` is what makes that argument sound again.

        Definition-time sub-expressions keep the ENCLOSING chain: a lambda's
        parameter defaults, and a comprehension's FIRST iterable, are evaluated
        where the expression is written, not inside the scope it opens.
        """
        if isinstance(node, ast.Lambda):
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self._visit(default, envs, found)
            env: dict[str, list[_Binding]] = {}
            for argument in _parameters(node):
                env.setdefault(argument.arg, []).append(
                    _Binding(argument, argument.lineno, "lambda parameter"))
            self._visit(node.body, _push(envs, env, "function"), found)
            return

        generators = node.generators
        # Python evaluates the FIRST iterable in the enclosing scope.
        if generators:
            self._visit(generators[0].iter, envs, found)
        env = {}
        for generator in generators:
            for name in _bound_names(generator.target):
                env.setdefault(name.id, []).append(
                    _Binding(generator.target, name.lineno, "comprehension target"))
        inner = _push(envs, env, "function")
        for index, generator in enumerate(generators):
            if index:
                self._visit(generator.iter, inner, found)
            for condition in generator.ifs:
                self._visit(condition, inner, found)
        if isinstance(node, ast.DictComp):
            self._visit(node.key, inner, found)
            self._visit(node.value, inner, found)
        else:
            self._visit(node.elt, inner, found)

    def _classify(self, node: ast.Call, envs) -> dict | None:
        func = node.func
        # R-P12. The consumer's name written as a string INSIDE this call's
        # arguments means the callee is selected at runtime by that string.
        # Exact equality, no substring. This is one rule where there were
        # three names: it covers `getattr(mod, "load_manifest")`,
        # `operator.attrgetter("load_manifest")` and a dispatch table built in
        # place, and covers the fourth such builtin nobody has written yet.
        for argument in (*node.args, *(kw.value for kw in node.keywords)):
            for inner in ast.walk(argument):
                if (isinstance(inner, ast.Constant)
                        and isinstance(inner.value, str)
                        and inner.value == CONSUMER_FUNCTION):
                    raise Unclassified(
                        f"{self.path}:{node.lineno}: the string "
                        f"{CONSUMER_FUNCTION!r} is passed as an argument, so the "
                        "callee it names is chosen at runtime and whether that "
                        "call passes contract_schema cannot be decided statically"
                    )
        if _callee_name(func) != CONSUMER_FUNCTION:
            return None
        # R-P10. THE exemption set, recorded at the one point the classifier
        # commits to a call: past this line the call is either resolved to a
        # module file or explicitly refused below. Recording in `_walk`
        # instead -- i.e. for every call merely walked past -- would exempt
        # `TABLE["load_manifest"](...)`, whose `func` the classifier is handed
        # but cannot name; that shape was blocked in round four and must stay
        # blocked. Executed: see test_the_name_as_a_string_blocks[dict-dispatch].
        self.classified_call_funcs.add(id(func))
        # R-P22. The ONE way a call site becomes a module identity. There is no
        # second branch, here or anywhere else, that can answer this question.
        target, how = self._module_identity(node, envs)
        keywords = {kw.arg for kw in node.keywords}
        if None in keywords and "contract_schema" not in keywords:
            raise Unclassified(
                f"{self.path}:{node.lineno}: contract_schema may be hidden in a "
                "**kwargs splat; the call cannot be judged statically"
            )
        schema = next((kw.value for kw in node.keywords if kw.arg == "contract_schema"), None)
        passes_schema = schema is not None and not (
            isinstance(schema, ast.Constant) and schema.value is None
        )
        return {
            "file": self.path,
            "lineno": node.lineno,
            "resolved_callee": target,
            "resolution": how,
            "is_fiscal_consumer": _same_file(target, FISCAL_CONSUMER),
            "passes_contract_schema": passes_schema,
        }


def discover_load_manifest_call_sites() -> list[dict]:
    sites: list[dict] = []
    for path in _tracked_python_files():
        sites.extend(_Module(path).call_sites())
    return sites


# --- R-P10/R-P11: the coupling is CHECKED, not reviewed ------------------------
#
# Round four's exemption set was computed by its own `ast.walk` of the whole
# module while classification entered through `_walk`/`_scope_nodes`, which
# yields a def/class and returns without visiting its decorators, defaults,
# annotations or bases. The identical expression failed in statement position
# and passed SILENTLY in five others. The tests below make that class of
# divergence a red suite instead of a review finding.

_TARGET_CONSUMER = "target-consumer.py"

_FIXTURE_PREAMBLE = f"""\
import importlib.util
from pathlib import Path


def _load_ingest():
    spec = importlib.util.spec_from_file_location(
        "ingest", Path(__file__).parent / {_TARGET_CONSUMER!r})
    return importlib.util.module_from_spec(spec)


ingest = _load_ingest()
"""

# ONE expression. The positions are the only thing that varies.
_THE_CALL = 'ingest.load_manifest(Path("m"))'

SEVEN_POSITIONS = {
    "1-statement": f"{_THE_CALL}\n",
    "2-decorator": f"@{_THE_CALL}\ndef decorated():\n    pass\n",
    "3-positional-default": f"def positional(manifest={_THE_CALL}):\n    pass\n",
    "4-keyword-only-default": f"def keyword_only(*, manifest={_THE_CALL}):\n    pass\n",
    "5-annotation": f"def annotated(manifest: {_THE_CALL}) -> None:\n    pass\n",
    "6-class-base": f"class Derived({_THE_CALL}):\n    pass\n",
    "7-lambda-body": f"loader = lambda: {_THE_CALL}\n",
}


def _fixture_module(tmp_path: Path, name: str, source: str) -> tuple[Path, Path]:
    target = tmp_path / _TARGET_CONSUMER
    target.write_text(
        "def load_manifest(path, *, contract_schema=None):\n    return path\n"
    )
    module_path = tmp_path / f"{name}.py"
    module_path.write_text(_FIXTURE_PREAMBLE + source)
    return module_path, target.resolve()


class _Observed:
    """What one run of the walker over one fixture actually did.

    ``handed_all``     -- every call ``_classify`` was given, by ``id(func)``.
    ``handed``         -- of those, the ones whose callee NAMES the consumer.
                          This is the population where being exempt from
                          blocking is even meaningful, so it is the set R-P18
                          requires the exemption set to equal.
    ``exempted``       -- ``_Module.classified_call_funcs``, the record
                          ``_block_on_unresolved_references`` complements.
    ``syntactic``      -- every consumer-named call in the fixture's OWN parse,
                          found independently of the walker. Membership in
                          ``handed`` is checked against this, so the assertion
                          does not depend on how many calls a fixture happens
                          to contain.
    """

    __slots__ = ("outcome", "handed_all", "handed", "exempted", "syntactic", "module")


def _outcome(module_path: Path, target: Path, monkeypatch) -> _Observed:
    """Run the walker over one fixture and report what it did."""
    handed_all: list[int] = []
    handed_named: list[int] = []
    original = _Module._classify

    def spy(self, node, envs):
        handed_all.append(id(node.func))
        if _callee_name(node.func) == CONSUMER_FUNCTION:
            handed_named.append(id(node.func))
        return original(self, node, envs)


    monkeypatch.setattr(_Module, "_classify", spy)

    module = _Module(module_path)
    outcome = "SILENT"
    try:
        sites = module.call_sites()
    except Unclassified:
        outcome = "BLOCKED"
    else:
        if any(site["resolved_callee"] == target for site in sites):
            outcome = "CLASSIFIED"
    observed = _Observed()
    observed.outcome = outcome
    observed.handed_all = set(handed_all)
    observed.handed = set(handed_named)
    observed.exempted = module.classified_call_funcs
    observed.syntactic = {
        id(node.func) for node in ast.walk(module.tree)
        if isinstance(node, ast.Call) and _callee_name(node.func) == CONSUMER_FUNCTION
    }
    observed.module = module
    return observed


@pytest.mark.parametrize("position", sorted(SEVEN_POSITIONS), ids=sorted(SEVEN_POSITIONS))
def test_no_position_of_the_same_call_passes_silently(position, tmp_path, monkeypatch) -> None:
    """R-P11. The same expression, seven places Python will execute it.

    A positional default is a real executing call: Python evaluates defaults at
    definition time, in the enclosing scope. So are a decorator, a keyword-only
    default, an annotation without ``from __future__ import annotations``, a
    class base and a lambda body.
    """
    module_path, target = _fixture_module(
        tmp_path, position.replace("-", "_"), SEVEN_POSITIONS[position]
    )
    seen = _outcome(module_path, target, monkeypatch)

    # (a) R-P10. Nothing is exempt that the classifier was not handed AT ALL.
    # This is exactly what round four violated: its exemption set was computed
    # by a second `ast.walk` and covered these six positions, which `_walk`
    # never visited, so the set contained ids the classifier had never seen.
    assert seen.exempted <= seen.handed_all, (
        f"{position}: {len(seen.exempted - seen.handed_all)} call(s) are exempt "
        "from blocking that the classifier was never handed; a separately "
        "computed exemption set has come back"
    )
    # (a2) R-P18. MEMBERSHIP, not a count. Every consumer-named call in the
    # fixture's own parse reached the classifier, and the exemption set is
    # exactly the calls that reached it -- equal as sets of node ids, in both
    # directions. A count is fixture-specific and a subset clause is vacuous;
    # this is neither, and it is what fails if `_walk` stops visiting a
    # position or if the exemption set is ever computed anywhere else.
    assert seen.syntactic, f"{position}: the fixture contains no {CONSUMER_FUNCTION} call"
    assert seen.syntactic <= seen.handed, (
        f"{position}: {len(seen.syntactic - seen.handed)} {CONSUMER_FUNCTION} "
        "call(s) present in the fixture's parse were never handed to the "
        "classifier; the walker does not visit this position"
    )
    assert seen.exempted == seen.handed, (
        f"{position}: the exemption set and the consumer calls the classifier "
        f"was handed differ by {len(seen.exempted ^ seen.handed)} node(s); the "
        "blocker is no longer the classifier's complement"
    )
    # (b) The invariant that holds whether or not `_walk` descends into
    # definition-time expressions: unseen means blocked, never silent.
    assert seen.outcome != "SILENT", (
        f"{position}: {_THE_CALL} was neither classified nor blocked. It is the "
        "identical expression that fails in statement position."
    )
    # And, since `_walk` now visits those positions, the stronger result: the
    # call is resolved to its module, not merely refused.
    assert seen.outcome == "CLASSIFIED", f"{position}: expected CLASSIFIED, got {seen.outcome}"


@pytest.mark.parametrize(
    "spelling",
    [
        'getattr(ingest, "load_manifest")(Path("m"))',
        'import operator\noperator.attrgetter("load_manifest")(ingest)(Path("m"))',
        'TABLE = {"load_manifest": print}\nTABLE["load_manifest"](Path("m"))',
    ],
    ids=["getattr", "operator.attrgetter", "dict-dispatch"],
)
def test_the_name_as_a_string_blocks(spelling, tmp_path, monkeypatch) -> None:
    """R-P12. One rule, not a list of the builtins that do this.

    Any ``ast.Constant`` equal to the consumer's name EXACTLY, anywhere inside a
    call's arguments, means the callee is chosen at runtime by that string.
    Round four named ``getattr`` and caught it while its twin
    ``operator.attrgetter("load_manifest")`` passed silently.
    """
    module_path, target = _fixture_module(tmp_path, "by_string", spelling + "\n")
    seen = _outcome(module_path, target, monkeypatch)
    assert seen.exempted <= seen.handed_all
    assert seen.exempted == seen.handed, (
        f"{spelling!r}: the exemption set is no longer the classifier's complement"
    )
    assert not seen.exempted, f"{spelling!r} exempted a callee it could not resolve"
    assert seen.outcome == "BLOCKED", f"{spelling!r} was not blocked: {seen.outcome}"


_REACHING = {
    "global-rebind-to-other": (
        "ingest = _load_fiscal()\n"
        "\n\n"
        "def _swap():\n"
        "    global ingest\n"
        "    ingest = _load_other()\n"
        "\n\n"
        "_swap()\n"
        'ingest.load_manifest(Path("m"))\n'
    ),
    "global-rebind-to-fiscal": (
        "ingest = _load_other()\n"
        "\n\n"
        "def _swap():\n"
        "    global ingest\n"
        "    ingest = _load_fiscal()\n"
        "\n\n"
        "_swap()\n"
        'ingest.load_manifest(Path("m"))\n'
    ),
    "nonlocal-rebind": (
        "def outer():\n"
        "    ingest = _load_other()\n"
        "\n"
        "    def _swap():\n"
        "        nonlocal ingest\n"
        "        ingest = _load_fiscal()\n"
        "\n"
        "    _swap()\n"
        '    ingest.load_manifest(Path("m"))\n'
    ),
}

_REACHING_PREAMBLE = f"""\
import importlib.util
from pathlib import Path


def _load_fiscal():
    spec = importlib.util.spec_from_file_location(
        "ingest", Path(__file__).parent / {_TARGET_CONSUMER!r})
    return importlib.util.module_from_spec(spec)


def _load_other():
    spec = importlib.util.spec_from_file_location(
        "other", Path(__file__).parent / "other-consumer.py")
    return importlib.util.module_from_spec(spec)


"""


@pytest.mark.parametrize("shape", sorted(_REACHING), ids=sorted(_REACHING))
def test_a_nested_global_or_nonlocal_rebinding_refuses(shape, tmp_path) -> None:
    """R-P26. The two binding forms that reach OUT of the scope they are in.

    ``_scope_nodes`` deliberately stops at a scope boundary, because that is
    Python's own rule and the reason a nested function's locals cannot resolve
    a name at an outer call site. ``global`` and ``nonlocal`` are the two
    declarations that break that containment: written inside a function, they
    rebind a name in an ENCLOSING scope. Counted only where they were written,
    the enclosing name looked bound exactly once and the choke point resolved
    it CONFIDENTLY AND WRONGLY -- a program squarely inside accepted form 2.

    Both directions were executed and both are covered here, including the
    unsafe one -- ``global-rebind-to-fiscal``, where the call really does reach
    the fiscal consumer with no pin and the walker previously reported some
    other module and said nothing at all.
    """
    (tmp_path / _TARGET_CONSUMER).write_text(
        "def load_manifest(path, *, contract_schema=None):\n    return path\n"
    )
    (tmp_path / "other-consumer.py").write_text(
        "def load_manifest(path):\n    return path\n"
    )
    module_path = tmp_path / f"reaching_{shape.replace('-', '_')}.py"
    module_path.write_text(_REACHING_PREAMBLE + _REACHING[shape])

    with pytest.raises(Unclassified, match="bound more than once"):
        _Module(module_path).call_sites()


_YIELDS_WHAT_IT_NAMES = {
    "decorated-consumer-def": (
        "fiscal = _load_fiscal()\n"
        "\n\n"
        "def swap(fn):\n"
        "    return fiscal\n"
        "\n\n"
        "@swap\n"
        "def load_manifest(path, *, contract_schema=None):\n"
        "    return path\n"
        "\n\n"
        'load_manifest(Path("m"))\n'
    ),
    "factory-returns-a-decoy": (
        "_fiscal_spec = importlib.util.spec_from_file_location(\n"
        '    "f", Path(__file__).parent / ' + repr(_TARGET_CONSUMER) + ")\n"
        "_fiscal = importlib.util.module_from_spec(_fiscal_spec)\n"
        "\n\n"
        "def _decoy():\n"
        "    spec = importlib.util.spec_from_file_location(\n"
        '        "d", Path(__file__).parent / "other-consumer.py")\n'
        "    return _fiscal\n"
        "\n\n"
        "ingest = _decoy()\n"
        'ingest.load_manifest(Path("m"))\n'
    ),
    "factory-returns-an-imported-module": (
        "import json\n"
        "\n\n"
        "def _decoy():\n"
        "    spec = importlib.util.spec_from_file_location(\n"
        '        "d", Path(__file__).parent / ' + repr(_TARGET_CONSUMER) + ")\n"
        "    return json\n"
        "\n\n"
        "ingest = _decoy()\n"
        'ingest.load_manifest(Path("m"))\n'
    ),
}


@pytest.mark.parametrize("shape", sorted(_YIELDS_WHAT_IT_NAMES),
                         ids=sorted(_YIELDS_WHAT_IT_NAMES))
def test_a_form_must_yield_the_module_it_names(shape, tmp_path) -> None:
    """R-P26. What a program MENTIONS is not what it YIELDS.

    Both shapes here sit squarely inside an accepted form -- undecorated
    module-scope factory, exactly one spec target, every name bound once -- and
    both resolved CONFIDENTLY AND WRONGLY before these clauses existed.

    ``factory-returns-a-decoy`` is the unsafe direction, executed: the factory
    names ``other-consumer.py`` and hands back the FISCAL consumer, so the call
    really does reach the pinned consumer with no schema and the walker
    reported another module and said nothing at all.

    ``decorated-consumer-def`` is the same defect on the bare-call path: a
    decorator can replace the function the ``def`` wrote, so the name no longer
    reaches the body under it.
    """
    (tmp_path / _TARGET_CONSUMER).write_text(
        "def load_manifest(path, *, contract_schema=None):\n    return path\n"
    )
    (tmp_path / "other-consumer.py").write_text(
        "def load_manifest(path):\n    return path\n"
    )
    module_path = tmp_path / f"yields_{shape.replace('-', '_')}.py"
    module_path.write_text(_REACHING_PREAMBLE + _YIELDS_WHAT_IT_NAMES[shape])

    with pytest.raises(Unclassified):
        _Module(module_path).call_sites()


_FINAL_QC = {
    # F1 -- the factory NAME resolved against a fabricated chain.
    "F1-factory-rebound-in-a-local-scope": (
        "def main():\n"
        "    _load_other = _load_fiscal\n"
        "    ingest = _load_other()\n"
        '    return ingest.load_manifest(Path("m"))\n'
        "\n\n"
        "main()\n"
    ),
    "F1-factory-rebound-by-a-parameter-default": (
        "def run(_load_other=_load_fiscal):\n"
        "    ingest = _load_other()\n"
        '    return ingest.load_manifest(Path("m"))\n'
        "\n\n"
        "run()\n"
    ),
    # F3 -- a star import rebinds the consumer name without being counted.
    "F3-star-import-over-the-defining-module": (
        "def load_manifest(path, *, contract_schema=None):\n"
        "    return path\n"
        "\n\n"
        "from some_shim import *\n"
        "\n"
        'load_manifest(Path("m"))\n'
    ),
}


@pytest.mark.parametrize("shape", sorted(_FINAL_QC), ids=sorted(_FINAL_QC))
def test_final_qc_confident_wrong_answers_now_refuse(shape, tmp_path) -> None:
    """R-P26/F1,F3. Found by final QC, each proven by running the program.

    In every one of these the walker named a NON-fiscal module, the gate stayed
    GREEN, and the call reached the fiscal consumer's ``load_manifest`` with no
    ``contract_schema`` -- which refused at runtime with
    ``--contract-schema is required``. Every stated precondition of the form
    held; the walker's answer was simply wrong.

    F1: the ALIAS binding was flow-sensitive, but the FACTORY NAME it pointed
    at was resolved against a hardcoded module scope, so a local rebinding --
    by assignment or by parameter default -- was invisible.

    F3: ``_scope_env``'s ImportFrom arm bound ``alias.asname or
    alias.name.split(".")[0]``, which for a star import is the literal ``"*"``.
    The module still showed ``load_manifest`` bound exactly once and form 1 was
    granted, while Python's star import had rebound it.
    """
    (tmp_path / _TARGET_CONSUMER).write_text(
        "def load_manifest(path, *, contract_schema=None):\n    return path\n"
    )
    (tmp_path / "other-consumer.py").write_text(
        "def load_manifest(path):\n    return path\n"
    )
    module_path = tmp_path / f"qc_{shape.replace('-', '_')}.py"
    module_path.write_text(_REACHING_PREAMBLE + _FINAL_QC[shape])

    with pytest.raises(Unclassified):
        _Module(module_path).call_sites()


_CLASS_SCOPE_IS_SKIPPED = {
    "comprehension": (
        "ingest = _load_fiscal()\n"
        "\n\n"
        "class Runner:\n"
        "    ingest = _load_other()\n"
        '    results = [ingest.load_manifest(Path("m")) for _ in range(1)]\n'
    ),
    "lambda": (
        "ingest = _load_fiscal()\n"
        "\n\n"
        "class Runner:\n"
        "    ingest = _load_other()\n"
        '    go = (lambda: ingest.load_manifest(Path("m")))()\n'
    ),
}


@pytest.mark.parametrize("shape", sorted(_CLASS_SCOPE_IS_SKIPPED),
                         ids=sorted(_CLASS_SCOPE_IS_SKIPPED))
def test_a_class_body_is_invisible_inside_a_lambda_or_comprehension(
        shape, tmp_path) -> None:
    """R-P26/F2. ``_push`` dropped class scopes for a ``def`` and nothing else.

    A lambda and a comprehension open scopes of their own, and Python skips the
    class body for them exactly as it does for a method -- so the calls below
    reach the MODULE-level ``ingest``, the fiscal consumer, which refused at
    runtime with ``--contract-schema is required``. Neither expression went
    through ``_push``, so both resolved against the class attribute and the
    walker reported a non-fiscal module while the gate stayed green.

    The correct answer is not a refusal, it is the FISCAL consumer -- and with
    no schema passed, that is what turns the gate red.
    """
    (tmp_path / _TARGET_CONSUMER).write_text(
        "def load_manifest(path, *, contract_schema=None):\n    return path\n"
    )
    (tmp_path / "other-consumer.py").write_text(
        "def load_manifest(path):\n    return path\n"
    )
    module_path = tmp_path / f"classscope_{shape}.py"
    module_path.write_text(_REACHING_PREAMBLE + _CLASS_SCOPE_IS_SKIPPED[shape])

    sites = _Module(module_path).call_sites()
    assert len(sites) == 1, sites
    assert sites[0]["resolved_callee"] == (tmp_path / _TARGET_CONSUMER).resolve(), (
        "the class attribute resolved a scope Python skips"
    )
    assert not sites[0]["passes_contract_schema"]


def test_module_identity_is_filesystem_identity_not_a_path_string(tmp_path) -> None:
    """R-P26/F4. ``Path.resolve()`` does not canonicalise case.

    On this case-insensitive filesystem a caller can spell the consumer's
    filename with different capitalisation: importlib loads the same bytes,
    ``os.path.samefile`` says it is the same file, and ``Path.__eq__`` says it
    is not. ``is_fiscal_consumer`` was a bare ``==``, so a real caller of the
    fiscal consumer presented itself as some other module and passed in
    silence.
    """
    assert _same_file(FISCAL_CONSUMER, FISCAL_CONSUMER)

    cased = FISCAL_CONSUMER.with_name(
        "-".join(part.capitalize() for part in FISCAL_CONSUMER.stem.split("-"))
        + FISCAL_CONSUMER.suffix
    )
    assert cased.name == "Kansas-Fiscal-Document-Ingest.py", cased.name
    # Only meaningful where the filesystem really is case-insensitive.
    if not cased.exists():
        pytest.skip(f"{cased.name} does not resolve; filesystem is case-sensitive")
    assert cased != FISCAL_CONSUMER, "the two spellings are equal as paths"
    assert cased.resolve() != FISCAL_CONSUMER, "Path.resolve() canonicalised case"
    assert _same_file(cased, FISCAL_CONSUMER), "samefile did not see one file"

    # A target that does not exist must not crash the walker, and is not the
    # consumer.
    missing = tmp_path / "never-written.py"
    assert not _same_file(missing, FISCAL_CONSUMER)


def test_the_consumer_refuses_a_missing_schema_at_runtime() -> None:
    """The residual risk claimed in the docstring below, executed.

    A caller this walker misses cannot ingest unverified; it dies on the
    operator's first invocation. That is the bound on what the static check
    leaves uncovered, and it is checked here rather than asserted in prose.
    """
    import importlib.util
    import sys

    for extra in (FISCAL_CONSUMER.parent, REPO / "packages" / "svs_common"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    spec = importlib.util.spec_from_file_location("_fiscal_consumer", FISCAL_CONSUMER)
    consumer = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules at class-creation
    # time, so the module must be registered before its body runs.
    sys.modules[spec.name] = consumer
    try:
        spec.loader.exec_module(consumer)
    finally:
        sys.modules.pop(spec.name, None)
    with pytest.raises(consumer.FiscalIngestError, match="--contract-schema is required"):
        consumer.load_manifest(REPO / "does-not-exist.jsonl")


def _declared_enforced_at() -> dict[str, list[str]]:
    """Every contractPin.enforcedAt in every source package, found structurally."""
    def walk(node, path, out):
        if isinstance(node, dict):
            if "enforcedAt" in node:
                out[path + "/enforcedAt"] = node["enforcedAt"]
            for key, value in node.items():
                walk(value, f"{path}/{key}", out)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]", out)

    declarations: dict[str, list[str]] = {}
    for package in sorted(REPO.glob("instances/*/vector-stores/*/sources/*")):
        for name, loader in (("source.yaml", yaml.safe_load), ("source.lock.json", json.loads)):
            document = package / name
            if not document.exists():
                continue
            walk(loader(document.read_text()), str(document.relative_to(REPO)), declarations)
    return declarations


def test_every_load_manifest_caller_enforces_the_pin() -> None:
    """Every caller of the fiscal document consumer passes a contract schema.

    The walker resolves exactly three forms, listed below; every other
    reference raises `Unclassified`. It proves a schema argument is passed, not
    that the schema is correct.

    THE THREE FORMS. In all three, EVERY name in the chain must be bound
    EXACTLY ONCE by the R-P16 binding visitor -- which counts every form Python
    binds a name with, including a ``global``/``nonlocal`` rebinding declared
    in a NESTED scope -- resolved through PYTHON'S OWN SCOPE CHAIN AT THE CALL
    SITE. A class body is never part of the chain a nested scope searches, and
    a lambda and a comprehension open scopes of their own, so a class attribute
    is invisible inside them too. A module containing a star import, a write
    into its own namespace mapping, or an ``exec``/``eval`` resolves nothing at
    all: none of those can be attributed to a single name.

    Identity is compared by FILESYSTEM IDENTITY (``os.path.samefile``), not by
    path string: this tree is on a case-insensitive filesystem, where two
    spellings that differ only in case are one file.

      1. ``load_manifest(...)`` written bare, where the name resolves through
         that scope chain to an undecorated top-level ``def load_manifest`` in
         the module under inspection. Identity: that module's own file.

      2. ``alias.load_manifest(...)`` where ``alias`` is bound to ``factory()``
         and ``factory`` resolves through that SAME scope chain to an
         UNDECORATED top-level ``def`` that builds exactly one
         ``spec_from_file_location`` target AND RETURNS the module loaded from
         that same target, on every return in its own scope. Identity: that
         target.

      3. ``alias.load_manifest(...)`` where ``alias`` is bound to
         ``module_from_spec(X)`` and ``X`` is bound to a
         ``spec_from_file_location(...)`` call whose path argument the pathlib
         evaluator can resolve. The inline spelling of form 2, with no factory
         function. Identity: that target.

    NOT DETECTED. Each of these was EXECUTED against this walker and is not
    caught; the runtime refusal below is what covers them:

      * ``getattr(mod, "load_" + "manifest")`` -- the name is computed, so the
        R-P12 string rule never sees the literal.
      * ``NAME = "load_manifest"`` then ``getattr(mod, NAME)`` -- the literal is
        bound to a variable, outside the call's own arguments.
      * a computed dispatch key, and ``"".join([...])`` spelling the name.
      * ``exec``/``eval`` of generated source, a write into a namespace
        mapping, and ``from X import *``. (In the module under inspection each
        of these is a module-wide REFUSAL; in ANOTHER module it is invisible.)
      * ``ingest.__dict__["load_" + "manifest"]`` and ``vars()`` subscripted by
        a computed key.
      * cross-module namespace mutation -- module A rebinding a name inside
        module B.
      * anything outside ``_tracked_python_files``: an untracked or ignored
        file, a notebook, a shell heredoc.
      * a spec target that does not EXIST when the walker runs -- a path
        built at runtime, or a file generated later. ``os.path.samefile``
        cannot answer for a missing path, so identity falls back to path
        equality there; a case-variant spelling of a not-yet-existing consumer
        would compare unequal.
      * two case-variant spellings of the SAME file inside one factory. The
        spec-target set counts them as two targets, so the factory refuses
        rather than resolving -- a refusal, not a wrong answer, but recorded
        here because it is not the behaviour the clause reads as promising.
      * schema CORRECTNESS. The walker proves an argument is passed. Whether it
        names the right contract is `verify_contract`'s job, not this one's.

    The residual risk this leaves is bounded and is checked by execution in
    ``test_the_consumer_refuses_a_missing_schema_at_runtime``: the consumer
    REFUSES a missing schema at runtime, so a caller the walker misses cannot
    ingest unverified -- it dies on its first invocation.
    """
    sites = discover_load_manifest_call_sites()
    assert sites, "the walker found no load_manifest calls at all; it is broken"

    fiscal = [site for site in sites if site["is_fiscal_consumer"]]
    assert fiscal, "no caller of the fiscal document consumer was resolved; the walker is broken"

    unpinned = [
        f"{site['file'].relative_to(REPO)}:{site['lineno']}"
        for site in fiscal
        if not site["passes_contract_schema"]
    ]
    assert not unpinned, (
        "these callers of the fiscal document consumer's load_manifest do not "
        f"pass a contract_schema: {unpinned}"
    )

    discovered = {
        f"{site['file'].relative_to(REPO)} {PIN_FLAG}" for site in fiscal
    }
    declarations = _declared_enforced_at()
    assert declarations, "no contractPin.enforcedAt declaration was found to check"
    for where, declared in sorted(declarations.items()):
        assert set(declared) == discovered, (
            f"{where} does not match the callers discovered in the source.\n"
            f"  declared but not a discovered caller: {sorted(set(declared) - discovered)}\n"
            f"  a discovered caller but not declared: {sorted(discovered - set(declared))}"
        )
