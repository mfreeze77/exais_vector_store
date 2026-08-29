#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_FIXTURE = Path(__file__).with_name("golden.json")
MARKER_PATTERN = re.compile(r"【(?P<index>[1-9][0-9]*)†source】")
SUPPORTED_CORPORA = frozenset({"kansas_courts", "topeka_municipal_code"})


class ExpertCorpusEvalError(ValueError):
    pass


def _shared_registry_authority():
    package_root = Path(__file__).resolve().parents[2] / "packages" / "svs_common"
    package_root_text = str(package_root)
    if package_root_text not in sys.path:
        sys.path.insert(0, package_root_text)
    try:
        from svs_common.expert_profiles import (
            EXPERT_PROFILE_REGISTRY,
            KANSAS_COURT_DECISIONS_VECTOR_STORE_ID,
            TOPEKA_MUNICIPAL_CODE_VECTOR_STORE_ID,
            expert_profile_definition,
        )
    except ModuleNotFoundError as exc:
        raise ExpertCorpusEvalError(
            "shared expert profile registry dependencies are unavailable"
        ) from exc

    expected_store_by_corpus = {
        "kansas_courts": KANSAS_COURT_DECISIONS_VECTOR_STORE_ID,
        "topeka_municipal_code": TOPEKA_MUNICIPAL_CODE_VECTOR_STORE_ID,
    }
    profile_by_corpus = {}
    for corpus, vector_store_id in expected_store_by_corpus.items():
        profiles = [
            profile
            for profile in EXPERT_PROFILE_REGISTRY
            if any(
                binding.vector_store_id == vector_store_id
                for binding in profile.vector_store_bindings
            )
        ]
        if len(profiles) != 1:
            raise ExpertCorpusEvalError(
                f"shared expert registry must define exactly one profile for corpus {corpus}"
            )
        profile_by_corpus[corpus] = profiles[0]
    return profile_by_corpus, expert_profile_definition


def load_fixture(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExpertCorpusEvalError("fixture could not be loaded") from exc
    if not isinstance(payload, dict):
        raise ExpertCorpusEvalError("fixture must be an object")
    return payload


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExpertCorpusEvalError(f"{name} must be an object")
    return value


def _require_non_empty_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ExpertCorpusEvalError(f"{name} must be a non-empty array")
    return value


def _require_non_empty_string_list(value: Any, name: str) -> list[str]:
    items = _require_non_empty_list(value, name)
    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ExpertCorpusEvalError(f"{name} must contain non-empty strings")
        normalized.append(item.strip())
    return normalized


def _citation_identity(citation: dict[str, Any]) -> str:
    for field in ("chunk_id", "document_id", "file_id"):
        value = citation.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ExpertCorpusEvalError("citation requires chunk_id, document_id, or file_id")


def _graph_relationships(citation: dict[str, Any]) -> list[dict[str, Any]]:
    relationships = citation.get("graph_relationships")
    if relationships is not None:
        return [
            _require_object(value, "graph relationship")
            for value in _require_non_empty_list(relationships, "graph_relationships")
        ]
    expansion = citation.get("graph_expansion")
    if expansion is None:
        return []
    return [_require_object(expansion, "graph_expansion")]


def _relation_type(relationship: dict[str, Any]) -> str:
    value = relationship.get("relation_type") or relationship.get("edge_type")
    if not isinstance(value, str) or not value.strip():
        raise ExpertCorpusEvalError("graph relationship requires relation_type or edge_type")
    return value.strip()


def _citation_proof(citation: dict[str, Any]) -> dict[str, Any]:
    url = citation.get("url")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise ExpertCorpusEvalError("citation requires an absolute source URL")
    relationships = _graph_relationships(citation)
    return {
        "identity": _citation_identity(citation),
        "marker": citation.get("marker"),
        "url": url,
        "graph_relationships": relationships,
    }


def _citation_key(citation: dict[str, Any]) -> tuple[str, str]:
    return citation["identity"], citation["url"]


def _relationship_record(relationship: dict[str, Any]) -> str:
    return json.dumps(relationship, sort_keys=True, separators=(",", ":"))


def _validate_trace_bindings(
    trace: Any,
    *,
    case_id: str,
    trace_name: str,
    registered_vector_store_ids: set[str],
) -> list[dict[str, Any]]:
    trace_object = _require_object(trace, f"{case_id}.{trace_name}")
    runs = [
        _require_object(value, f"{case_id}.{trace_name}.run")
        for value in _require_non_empty_list(
            trace_object.get("runs"),
            f"{case_id}.{trace_name}.runs",
        )
    ]
    for run in runs:
        vector_store_id = run.get("vector_store_id")
        if (
            not isinstance(vector_store_id, str)
            or vector_store_id != vector_store_id.strip()
            or vector_store_id not in registered_vector_store_ids
        ):
            raise ExpertCorpusEvalError(
                f"{case_id}.{trace_name} vector_store_id is not registered to the resolved expert"
            )
    return runs


def validate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    if fixture.get("schema_version") != 1:
        raise ExpertCorpusEvalError("schema_version must be 1")
    if fixture.get("proof_mode") != "deterministic_fixture":
        raise ExpertCorpusEvalError("proof_mode must be deterministic_fixture")
    if fixture.get("live_corpus_verified") is not False:
        raise ExpertCorpusEvalError("live_corpus_verified must be false")
    if fixture.get("live_provider_verified") is not False:
        raise ExpertCorpusEvalError("live_provider_verified must be false")

    profile_by_corpus, expert_profile_definition = _shared_registry_authority()

    cases = _require_non_empty_list(fixture.get("cases"), "cases")
    seen_ids: set[str] = set()
    corpus_counts = {corpus: 0 for corpus in SUPPORTED_CORPORA}
    for value in cases:
        case = _require_object(value, "case")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ExpertCorpusEvalError("case id must be a non-empty string")
        if case_id in seen_ids:
            raise ExpertCorpusEvalError("case ids must be unique")
        seen_ids.add(case_id)
        corpus = case.get("corpus")
        if corpus not in corpus_counts:
            raise ExpertCorpusEvalError("case corpus is unsupported")
        corpus_counts[corpus] += 1
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ExpertCorpusEvalError(f"{case_id}: question is required")
        _require_non_empty_string_list(
            case.get("expected_answer_terms"),
            f"{case_id}.expected_answer_terms",
        )
        graph_capable = case.get("graph_capable")
        if not isinstance(graph_capable, bool):
            raise ExpertCorpusEvalError(f"{case_id}.graph_capable must be a boolean")
        expected_graph_relationships = case.get("expected_graph_relationships")
        if graph_capable:
            _require_non_empty_string_list(
                expected_graph_relationships,
                f"{case_id}.expected_graph_relationships",
            )
        elif expected_graph_relationships is not None:
            _require_non_empty_string_list(
                expected_graph_relationships,
                f"{case_id}.expected_graph_relationships",
            )
        _require_object(case.get("raw_search_response"), f"{case_id}.raw_search_response")
        expert_response = _require_object(
            case.get("expert_session_response"),
            f"{case_id}.expert_session_response",
        )
        expert_id = expert_response.get("expert_id")
        definition = (
            expert_profile_definition(expert_id)
            if isinstance(expert_id, str) and expert_id.strip()
            else None
        )
        expected_definition = profile_by_corpus[corpus]
        if (
            definition is None
            or expert_id != definition.id
            or definition.id != expected_definition.id
        ):
            raise ExpertCorpusEvalError(
                f"{case_id}: expert_id does not resolve to the registry profile for corpus {corpus}"
            )
        registered_vector_store_ids = {
            binding.vector_store_id for binding in definition.vector_store_bindings
        }
        _validate_trace_bindings(
            case.get("raw_retrieval_trace"),
            case_id=case_id,
            trace_name="raw_retrieval_trace",
            registered_vector_store_ids=registered_vector_store_ids,
        )
        expert_trace = _require_object(
            expert_response.get("retrieval_trace"),
            f"{case_id}.expert_session_response.retrieval_trace",
        )
        _validate_trace_bindings(
            expert_trace,
            case_id=case_id,
            trace_name="expert_session_response.retrieval_trace",
            registered_vector_store_ids=registered_vector_store_ids,
        )
    if any(count < 2 for count in corpus_counts.values()):
        raise ExpertCorpusEvalError("fixture requires at least two tough questions per corpus")
    return profile_by_corpus


def score_case(case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case["id"])
    raw = _require_object(case["raw_search_response"], f"{case_id}.raw_search_response")
    if raw.get("object") != "vector_store.search_results.page":
        raise ExpertCorpusEvalError(f"{case_id}: raw search object is invalid")
    raw_rows = _require_non_empty_list(raw.get("data"), f"{case_id}.raw_search_response.data")
    raw_citations: list[dict[str, Any]] = []
    raw_text: list[str] = []
    for row_value in raw_rows:
        row = _require_object(row_value, f"{case_id}.raw result")
        citation = _require_object(row.get("citation"), f"{case_id}.raw result citation")
        raw_citations.append(_citation_proof(citation))
        for content_value in row.get("content") or []:
            content = _require_object(content_value, f"{case_id}.raw result content")
            if isinstance(content.get("text"), str):
                raw_text.append(content["text"])

    expert = _require_object(case["expert_session_response"], f"{case_id}.expert_session_response")
    raw_trace = _require_object(case["raw_retrieval_trace"], f"{case_id}.raw_retrieval_trace")
    answer = expert.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ExpertCorpusEvalError(f"{case_id}: expert answer is required")
    expert_values = _require_non_empty_list(expert.get("citations"), f"{case_id}.expert citations")
    expert_citations = [
        _citation_proof(_require_object(value, f"{case_id}.expert citation"))
        for value in expert_values
    ]
    caveats = _require_non_empty_list(expert.get("caveats"), f"{case_id}.caveats")
    if not all(isinstance(value, str) and value.strip() for value in caveats):
        raise ExpertCorpusEvalError(f"{case_id}: caveats must be non-empty strings")

    raw_citation_keys = {_citation_key(value) for value in raw_citations}
    expert_citation_keys = {_citation_key(value) for value in expert_citations}
    raw_identities = {identity for identity, _url in raw_citation_keys}
    expert_identities = {identity for identity, _url in expert_citation_keys}
    raw_urls = {value["url"] for value in raw_citations}
    expert_urls = {value["url"] for value in expert_citations}
    expected_markers = [f"【{index}†source】" for index in range(1, len(expert_citations) + 1)]
    actual_markers = MARKER_PATTERN.findall(answer)
    citation_markers = [value["marker"] for value in expert_citations]

    raw_relationships = {
        _relation_type(relationship)
        for citation in raw_citations
        for relationship in citation["graph_relationships"]
    }
    expert_relationships = {
        _relation_type(relationship)
        for citation in expert_citations
        for relationship in citation["graph_relationships"]
    }
    raw_relationships_by_citation: dict[tuple[str, str], set[str]] = {}
    for citation in raw_citations:
        raw_relationships_by_citation.setdefault(_citation_key(citation), set()).update(
            _relationship_record(relationship)
            for relationship in citation["graph_relationships"]
        )
    expert_graph_metadata_is_retrieved = all(
        {
            _relationship_record(relationship)
            for relationship in citation["graph_relationships"]
        }
        <= raw_relationships_by_citation.get(_citation_key(citation), set())
        for citation in expert_citations
    )
    expected_relationships = {
        value.strip()
        for value in case.get("expected_graph_relationships") or []
    }
    expected_terms = [value.strip().lower() for value in case["expected_answer_terms"]]
    raw_haystack = " ".join(raw_text).lower()
    answer_haystack = answer.lower()

    checks = {
        "raw_expected_fact_coverage": all(term in raw_haystack for term in expected_terms),
        "expert_expected_fact_coverage": all(term in answer_haystack for term in expected_terms),
        "expert_citations_are_retrieved": expert_citation_keys <= raw_citation_keys,
        "expert_identities_are_retrieved": expert_identities <= raw_identities,
        "expert_urls_are_retrieved": expert_urls <= raw_urls,
        "citation_markers_complete": (
            actual_markers == [str(index) for index in range(1, len(expert_citations) + 1)]
            and citation_markers == expected_markers
        ),
        "raw_graph_metadata_preserved": expected_relationships <= raw_relationships,
        "expert_graph_metadata_preserved": expected_relationships <= expert_relationships,
        "expert_graph_metadata_is_retrieved": expert_graph_metadata_is_retrieved,
        "caveats_preserved": bool(caveats),
    }
    return {
        "id": case_id,
        "corpus": case["corpus"],
        "question": case["question"],
        "passed": all(checks.values()),
        "checks": checks,
        "comparison": {
            "raw_search": {
                "vector_store_ids": sorted(
                    {run["vector_store_id"] for run in raw_trace["runs"]}
                ),
                "result_count": len(raw_rows),
                "citations": raw_citations,
                "relationship_types": sorted(raw_relationships),
            },
            "expert_session": {
                "expert_id": expert.get("expert_id"),
                "vector_store_ids": sorted(
                    {
                        run["vector_store_id"]
                        for run in expert["retrieval_trace"]["runs"]
                    }
                ),
                "session_id": expert.get("session_id"),
                "citations": expert_citations,
                "relationship_types": sorted(expert_relationships),
                "caveats": caveats,
            },
        },
    }


def run_eval(fixture: dict[str, Any]) -> dict[str, Any]:
    profile_by_corpus = validate_fixture(fixture)
    cases = [score_case(value) for value in fixture["cases"]]
    return {
        "schema_version": 1,
        "eval_id": fixture.get("id"),
        "proof_mode": "deterministic_fixture",
        "live_corpus_verified": False,
        "live_provider_verified": False,
        "registry_authority": {
            corpus: {
                "expert_id": profile.id,
                "vector_store_ids": sorted(
                    {binding.vector_store_id for binding in profile.vector_store_bindings}
                ),
            }
            for corpus, profile in sorted(profile_by_corpus.items())
        },
        "claim_boundary": (
            "This run validates repository fixtures and contracts only; it does not prove "
            "the current live corpus, graph, model gateway, or external provider."
        ),
        "status": "pass" if all(value["passed"] for value in cases) else "fail",
        "case_count": len(cases),
        "cases": cases,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare deterministic raw-search fixtures with expert-session answers."
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        proof = run_eval(load_fixture(args.fixture))
    except ExpertCorpusEvalError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 2
    rendered = json.dumps(proof, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    return 0 if proof["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
