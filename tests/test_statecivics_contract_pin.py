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


def _scope_env(body: list[ast.stmt]) -> dict[str, ast.AST]:
    env: dict[str, ast.AST] = {}
    for statement in body:
        for node in _scope_nodes(statement):
            if isinstance(node, ast.Assign) and node.value is not None:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
                env[node.target.id] = node.value
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    env[alias.asname or alias.name.split(".")[0]] = node
    return env


def _lookup(name: str, envs: tuple[dict[str, ast.AST], ...]) -> ast.AST:
    for env in reversed(envs):
        if name in env:
            return env[name]
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
        return _eval_path(_lookup(node.id, envs), envs, own)
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
        self.defines_consumer_function = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == CONSUMER_FUNCTION
            for node in self.tree.body
        )
        # R-P10. The ONE record of what the classifier actually looked at.
        # `_block_on_unresolved_references` complements against this and
        # nothing else, so there is no second predicate to keep in step.
        self.classified_call_funcs: set[int] = set()
        self.factories = self._module_factories()

    def _module_factories(self) -> dict[str, Path]:
        """Functions that load and return a module from an explicit file.

        ``_load_ingest_command()`` and ``load_ingest_module()`` differ only in
        name; both are recognised by what they DO -- build a spec from a file
        path -- so a fourth one with any name is recognised too.
        """
        module_env = _scope_env(self.tree.body)
        factories: dict[str, Path] = {}
        for node in self.tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            envs = (module_env, _scope_env(node.body))
            targets = set()
            for sub in ast.walk(node):
                target = _spec_target(sub, envs, self.path)
                if target is not None:
                    targets.add(target)
            if len(targets) == 1:
                factories[node.name] = next(iter(targets))
            elif len(targets) > 1:
                raise Unclassified(
                    f"{self.path}: {node.name}() loads more than one module "
                    f"({sorted(str(t) for t in targets)}); its return value is ambiguous"
                )
        return factories

    def _resolve_module_name(self, name: str, envs) -> Path:
        """Resolve a name bound to a module object to the FILE it was loaded
        from. Name equality is never consulted; only the spec target is."""
        bound = _lookup(name, envs)
        if isinstance(bound, (ast.Import, ast.ImportFrom)):
            raise Unclassified(
                f"{name!r} is an imported module; its file identity is not "
                "statically resolvable here"
            )
        if isinstance(bound, ast.Call):
            callee = _callee_name(bound.func)
            if callee in self.factories:
                return self.factories[callee]
            if callee == "module_from_spec" and bound.args:
                spec_argument = bound.args[0]
                if isinstance(spec_argument, ast.Name):
                    spec_node = _lookup(spec_argument.id, envs)
                else:
                    spec_node = spec_argument
                target = _spec_target(spec_node, envs, self.path)
                if target is not None:
                    return target
            target = _spec_target(bound, envs, self.path)
            if target is not None:
                return target
        raise Unclassified(
            f"{name!r} is bound to an expression the walker cannot resolve to a "
            f"module file: {ast.dump(bound)[:120]}"
        )

    def call_sites(self) -> list[dict]:
        """Every call to a function named ``load_manifest``, each carrying the
        resolved file of the module it actually reaches."""
        found: list[dict] = []
        self.classified_call_funcs = set()
        # Order is load-bearing: the classifier runs first so that the set it
        # fills in IS the exemption set the blocker then complements. If
        # `_walk` raises part way, the record is partial and MORE references
        # block -- the check fails toward blocking either way.
        self._walk(self.tree.body, (), found)
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

    def _walk(self, body, envs, found) -> None:
        """Walk a scope's ``body``. ``envs`` is the ENCLOSING scope chain."""
        envs = envs + (_scope_env(body),)
        for statement in body:
            self._visit(statement, envs, found)

    def _visit(self, node_or_expression, envs, found) -> None:
        """Classify every call under ``node_or_expression`` that runs in ``envs``.

        This is the walker's only traversal. Every ``Call`` it reaches is
        handed to ``_classify``, which records the ones it commits to; the
        blocker's exemption set is that record and nothing else.
        """
        for node in _scope_nodes(node_or_expression):
            if isinstance(node, _SCOPE_BOUNDARIES):
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
                self._walk(node.body, envs, found)
            elif isinstance(node, ast.Call):
                site = self._classify(node, envs)
                if site is not None:
                    found.append(site)

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
        if isinstance(func, ast.Attribute):
            if not isinstance(func.value, ast.Name):
                raise Unclassified(
                    f"{self.path}:{node.lineno}: load_manifest is called on a "
                    "non-name expression; its module cannot be resolved"
                )
            target = self._resolve_module_name(func.value.id, envs)
            how = f"alias {func.value.id!r} -> importlib spec target"
        else:
            if not self.defines_consumer_function:
                raise Unclassified(
                    f"{self.path}:{node.lineno}: bare load_manifest() in a module "
                    "that does not define it"
                )
            target = self.path
            how = "bare call inside the defining module"
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
            "is_fiscal_consumer": target == FISCAL_CONSUMER,
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


def _outcome(module_path: Path, target: Path, monkeypatch) -> tuple[str, set[int], set[int]]:
    """Run the walker over one fixture and report what it did.

    Returns the outcome and the two sets that R-P10 requires to be the same
    one: what ``_classify`` was actually handed, and the exemption set the
    blocker complements against.
    """
    handed_to_classify: list[int] = []
    original = _Module._classify

    def spy(self, node, envs):
        handed_to_classify.append(id(node.func))
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
    return outcome, set(handed_to_classify), module.classified_call_funcs


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
    outcome, handed, exempted = _outcome(module_path, target, monkeypatch)

    # (a) R-P10. Nothing is exempt that the classifier was not handed. This is
    # exactly what round four violated: its exemption set was computed by a
    # second `ast.walk` and covered these six positions, which `_walk` never
    # visited, so the set contained ids the classifier had never seen.
    assert exempted <= handed, (
        f"{position}: {len(exempted - handed)} call(s) are exempt from blocking "
        "that the classifier was never handed; a separately computed exemption "
        "set has come back"
    )
    # And here the exemption is precisely the one `ingest.load_manifest` callee
    # in the fixture -- the preamble's other calls resolve to nothing and are
    # exempt from nothing.
    assert len(exempted) == 1, f"{position}: exempted {len(exempted)} callees, expected 1"
    # (b) The invariant that holds whether or not `_walk` descends into
    # definition-time expressions: unseen means blocked, never silent.
    assert outcome != "SILENT", (
        f"{position}: {_THE_CALL} was neither classified nor blocked. It is the "
        "identical expression that fails in statement position."
    )
    # And, since `_walk` now visits those positions, the stronger result: the
    # call is resolved to its module, not merely refused.
    assert outcome == "CLASSIFIED", f"{position}: expected CLASSIFIED, got {outcome}"


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
    outcome, handed, exempted = _outcome(module_path, target, monkeypatch)
    assert exempted <= handed
    assert not exempted, f"{spelling!r} exempted a callee it could not resolve"
    assert outcome == "BLOCKED", f"{spelling!r} was not blocked: {outcome}"


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
    """The enforcement points are computed from the source, not declared.

    Three properties, all of them constructions:

    1. Every call to the fiscal document consumer's ``load_manifest`` passes a
       ``contract_schema``. The consumer is identified by the FILE a call
       resolves to -- the importlib ``spec_from_file_location`` target behind
       the alias -- so ``kscourts-ingest.py``'s unrelated function of the same
       name is excluded because it resolves elsewhere, not because anything
       here knows its name.
    2. ``contractPin.enforcedAt`` equals the discovered caller set exactly, in
       both directions and in every file that declares it. A fourth caller
       fails this with no human updating a list; so does a stale entry.
    3. Anything the walker cannot classify raises ``Unclassified`` and fails
       the test, so breaking the checker blocks rather than quietly passing.

       There is exactly ONE traversal, ``_visit``. ``_classify`` records
       ``id(func)`` for each call it commits to, and
       ``_block_on_unresolved_references`` blocks on every reference to the
       name that is not in THAT record. The blocker is the classifier's
       complement, not a second opinion about the same question, because two
       predicates maintained separately diverge -- which is precisely how round
       four exempted decorators and defaults that its classifier never visited.

       DETECTED. Each item below was executed against a fixture module, not
       reasoned about --

       * every call in the seven positions Python actually evaluates the
         expression in -- statement, decorator, positional default,
         keyword-only default, annotation, class base, lambda body -- all
         resolved to their module file, none silent
         (``test_no_position_of_the_same_call_passes_silently``);
       * a call the walker cannot resolve to a module file (the alias is an
         imported module, the callee is a non-name expression, the factory
         loads more than one module);
       * a call whose ``contract_schema`` might be hidden in a ``**kwargs``
         splat;
       * the name written as a string literal inside any call's arguments, by
         exact equality -- which is one rule where there were three names, and
         blocks ``getattr(mod, "load_manifest")``,
         ``operator.attrgetter("load_manifest")`` and an inline dispatch table
         alike (``test_the_name_as_a_string_blocks``);
       * ANY reference to the name outside a call the classifier resolved --
         an attribute, a bare name load, or a subscript by the string literal.
         That is the complement of the classifier's own record, so alias
         assignment, ``functools.partial``, ``TABLE["load_manifest"]()`` and
         ``runpy.run_path(...)["load_manifest"]`` all land here without being
         named anywhere in this file. All four were executed as mutations.

       NOT DETECTED. Claimed no more broadly than this, because each was
       executed and observed to pass silently --

       * a callee named by a string this walker never sees as a literal in
         call-argument position: ``getattr(mod, "load_" + "manifest")``, a
         computed dispatch key, ``exec`` of generated source, and -- the case
         the string rule does NOT reach -- a literal bound to a variable first,
         ``NAME = "load_manifest"`` then ``getattr(mod, NAME)``;
       * anything outside the scope of ``_tracked_python_files``: this repo's
         own top-level ``tests/`` (excluded by ``parts[0] == "tests"``, because
         it deliberately calls the consumer both ways), git-ignored trees,
         non-Python runners, and any caller living in another repository;
       * whether the value passed as ``contract_schema`` is the RIGHT schema.
         This proves an argument is PASSED. It does not prove it is correct.

       Nothing broader is claimed. Three previous versions of this list each
       asserted something false, so every line above names the test or mutation
       that produced it.

       The residual is bounded, and the bound is executed rather than asserted:
       the consumer raises ``FiscalIngestError`` when ``contract_schema`` is
       ``None`` (``test_the_consumer_refuses_a_missing_schema_at_runtime``), so
       a caller this walker misses still cannot ingest unverified. It would
       ship CI-green and die on an operator's first invocation -- round two's
       failure mode, which is what this check exists to catch first.
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
