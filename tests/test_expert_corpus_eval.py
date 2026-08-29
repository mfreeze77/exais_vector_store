from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

from svs_api.main import app
from svs_common.expert_profiles import (
    KANSAS_COURT_DECISIONS_VECTOR_STORE_ID,
    TOPEKA_MUNICIPAL_CODE_VECTOR_STORE_ID,
    expert_profile_definition,
)
from svs_common.schemas import ExpertMessageResponse, OpenAIVectorStoreSearchResultsPage


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evals" / "expert-sessions" / "run_eval.py"
FIXTURE = ROOT / "evals" / "expert-sessions" / "golden.json"


def load_module():
    spec = importlib.util.spec_from_file_location("expert_session_comparison_eval", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["expert_session_comparison_eval"] = module
    spec.loader.exec_module(module)
    return module


def test_repository_eval_compares_two_tough_cases_per_corpus_and_passes():
    module = load_module()

    proof = module.run_eval(module.load_fixture(FIXTURE))

    assert proof["status"] == "pass"
    assert proof["proof_mode"] == "deterministic_fixture"
    assert proof["live_corpus_verified"] is False
    assert proof["live_provider_verified"] is False
    assert proof["registry_authority"] == {
        "kansas_courts": {
            "expert_id": "kansas-court-decisions",
            "vector_store_ids": [KANSAS_COURT_DECISIONS_VECTOR_STORE_ID],
        },
        "topeka_municipal_code": {
            "expert_id": "topeka-municipal-code",
            "vector_store_ids": [TOPEKA_MUNICIPAL_CODE_VECTOR_STORE_ID],
        },
    }
    assert proof["case_count"] == 4
    assert [case["corpus"] for case in proof["cases"]].count("kansas_courts") == 2
    assert [case["corpus"] for case in proof["cases"]].count("topeka_municipal_code") == 2
    assert all(all(case["checks"].values()) for case in proof["cases"])


def test_eval_fixtures_validate_against_current_raw_and_expert_api_contracts():
    module = load_module()
    fixture = module.load_fixture(FIXTURE)

    for case in fixture["cases"]:
        raw = OpenAIVectorStoreSearchResultsPage.model_validate(case["raw_search_response"])
        expert = ExpertMessageResponse.model_validate(case["expert_session_response"])
        assert raw.data
        assert expert.citations
        assert expert.retrieval_trace.status == "completed"


def test_eval_expert_ids_match_corpus_and_resolve_shared_profile_registry():
    module = load_module()
    fixture = module.load_fixture(FIXTURE)
    assert "expected_experts_by_corpus" not in fixture
    proof = module.run_eval(fixture)
    registry_authority = proof["registry_authority"]
    expected_store_by_corpus = {
        "kansas_courts": KANSAS_COURT_DECISIONS_VECTOR_STORE_ID,
        "topeka_municipal_code": TOPEKA_MUNICIPAL_CODE_VECTOR_STORE_ID,
    }

    for case in fixture["cases"]:
        expert_id = case["expert_session_response"]["expert_id"]
        assert expert_id == registry_authority[case["corpus"]]["expert_id"]
        definition = expert_profile_definition(expert_id)
        assert definition is not None
        assert {binding.vector_store_id for binding in definition.vector_store_bindings} == {
            expected_store_by_corpus[case["corpus"]]
        }


@pytest.mark.parametrize("case_index", range(4))
@pytest.mark.parametrize("mutation", ["unregistered", "wrong_corpus"])
def test_eval_rejects_unregistered_or_wrong_corpus_expert_for_every_case(case_index, mutation):
    module = load_module()
    fixture = module.load_fixture(FIXTURE)
    case = fixture["cases"][case_index]
    if mutation == "unregistered":
        expert_id = "unregistered-eval-expert"
    else:
        expert_id = (
            "topeka-municipal-code"
            if case["corpus"] == "kansas_courts"
            else "kansas-court-decisions"
        )
    case["expert_session_response"]["expert_id"] = expert_id

    with pytest.raises(module.ExpertCorpusEvalError, match="expert_id does not resolve to the registry profile"):
        module.run_eval(fixture)


@pytest.mark.parametrize("case_index", range(4))
@pytest.mark.parametrize("trace_name", ["raw", "expert"])
@pytest.mark.parametrize("binding_mutation", ["fictional", "other_expert"])
def test_eval_rejects_unregistered_trace_bindings_for_every_case(
    case_index,
    trace_name,
    binding_mutation,
):
    module = load_module()
    fixture = module.load_fixture(FIXTURE)
    case = fixture["cases"][case_index]
    if binding_mutation == "fictional":
        vector_store_id = "vs_fictional_eval_binding"
    else:
        vector_store_id = (
            TOPEKA_MUNICIPAL_CODE_VECTOR_STORE_ID
            if case["corpus"] == "kansas_courts"
            else KANSAS_COURT_DECISIONS_VECTOR_STORE_ID
        )
    trace = (
        case["raw_retrieval_trace"]
        if trace_name == "raw"
        else case["expert_session_response"]["retrieval_trace"]
    )
    for run in trace["runs"]:
        run["vector_store_id"] = vector_store_id

    with pytest.raises(module.ExpertCorpusEvalError, match="vector_store_id is not registered"):
        module.run_eval(fixture)


@pytest.mark.parametrize("trace_name", ["raw", "expert"])
def test_eval_checks_every_trace_run_binding_not_only_the_first(trace_name):
    module = load_module()
    fixture = module.load_fixture(FIXTURE)
    case = fixture["cases"][0]
    trace = (
        case["raw_retrieval_trace"]
        if trace_name == "raw"
        else case["expert_session_response"]["retrieval_trace"]
    )
    invalid_run = copy.deepcopy(trace["runs"][0])
    invalid_run["vector_store_id"] = "vs_fictional_second_run"
    trace["runs"].append(invalid_run)

    with pytest.raises(module.ExpertCorpusEvalError, match="vector_store_id is not registered"):
        module.run_eval(fixture)


def test_eval_corpus_identity_is_anchored_to_registry_store_constants():
    module = load_module()
    fixture = module.load_fixture(FIXTURE)
    fixture["cases"][0]["corpus"] = "topeka_municipal_code"

    with pytest.raises(module.ExpertCorpusEvalError, match="registry profile for corpus"):
        module.run_eval(fixture)


def test_eval_output_preserves_markers_urls_graph_metadata_and_caveats():
    module = load_module()

    proof = module.run_eval(module.load_fixture(FIXTURE))

    for case in proof["cases"]:
        raw = case["comparison"]["raw_search"]
        expert = case["comparison"]["expert_session"]
        assert expert["caveats"]
        assert expert["relationship_types"]
        assert expert["vector_store_ids"] == raw["vector_store_ids"]
        assert expert["vector_store_ids"] == proof["registry_authority"][case["corpus"]][
            "vector_store_ids"
        ]
        assert set(expert["relationship_types"]) <= set(raw["relationship_types"])
        assert all(citation["url"].startswith("https://") for citation in raw["citations"])
        assert all(citation["url"].startswith("https://") for citation in expert["citations"])
        assert all(citation["marker"] for citation in expert["citations"])
        assert any(citation["graph_relationships"] for citation in expert["citations"])
        assert case["checks"]["expert_graph_metadata_is_retrieved"] is True


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    [
        (
            lambda fixture: fixture["cases"][0]["expert_session_response"].update(
                {"answer": "The answer lost its markers."}
            ),
            "citation_markers_complete",
        ),
        (
            lambda fixture: fixture["cases"][0]["expert_session_response"]["citations"][0].update(
                {"url": "https://unretrieved.example.test/opinion.pdf"}
            ),
            "expert_urls_are_retrieved",
        ),
        (
            lambda fixture: [
                relationship.update({"relation_type": "unrelated"})
                for citation in fixture["cases"][0]["expert_session_response"]["citations"]
                for relationship in citation.get("graph_relationships", [])
            ],
            "expert_graph_metadata_preserved",
        ),
    ],
)
def test_eval_fails_adversarial_evidence_drift(mutation, failed_check):
    module = load_module()
    fixture = copy.deepcopy(module.load_fixture(FIXTURE))
    mutation(fixture)

    proof = module.run_eval(fixture)

    assert proof["status"] == "fail"
    assert proof["cases"][0]["checks"][failed_check] is False


def test_eval_rejects_swapped_urls_across_otherwise_valid_citation_ids():
    module = load_module()
    fixture = copy.deepcopy(module.load_fixture(FIXTURE))
    citations = fixture["cases"][0]["expert_session_response"]["citations"]
    citations[0]["url"], citations[1]["url"] = citations[1]["url"], citations[0]["url"]

    proof = module.run_eval(fixture)
    checks = proof["cases"][0]["checks"]

    assert proof["status"] == "fail"
    assert checks["expert_identities_are_retrieved"] is True
    assert checks["expert_urls_are_retrieved"] is True
    assert checks["expert_citations_are_retrieved"] is False


def test_eval_rejects_graph_relationship_moved_to_another_retrieved_citation():
    module = load_module()
    fixture = copy.deepcopy(module.load_fixture(FIXTURE))
    citations = fixture["cases"][0]["expert_session_response"]["citations"]
    relationships = citations[0].pop("graph_relationships")
    citations[1]["graph_relationships"] = relationships

    proof = module.run_eval(fixture)
    checks = proof["cases"][0]["checks"]

    assert proof["status"] == "fail"
    assert checks["expert_citations_are_retrieved"] is True
    assert checks["expert_graph_metadata_preserved"] is True
    assert checks["expert_graph_metadata_is_retrieved"] is False


@pytest.mark.parametrize("expected_terms", [[], [""], ["   "]])
def test_eval_rejects_empty_or_blank_expected_answer_terms(expected_terms):
    module = load_module()
    fixture = module.load_fixture(FIXTURE)
    fixture["cases"][0]["expected_answer_terms"] = expected_terms

    with pytest.raises(module.ExpertCorpusEvalError, match="expected_answer_terms"):
        module.run_eval(fixture)


@pytest.mark.parametrize("expected_relationships", [[], [""], ["   "]])
def test_eval_rejects_empty_or_blank_expected_graph_relationships(expected_relationships):
    module = load_module()
    fixture = module.load_fixture(FIXTURE)
    fixture["cases"][0]["expected_graph_relationships"] = expected_relationships

    with pytest.raises(module.ExpertCorpusEvalError, match="expected_graph_relationships"):
        module.run_eval(fixture)


def test_eval_fails_when_graph_capable_case_removes_all_graph_evidence():
    module = load_module()
    fixture = copy.deepcopy(module.load_fixture(FIXTURE))
    case = fixture["cases"][0]
    for row in case["raw_search_response"]["data"]:
        row["citation"].pop("graph_expansion", None)
        row["citation"].pop("graph_relationships", None)
    for citation in case["expert_session_response"]["citations"]:
        citation.pop("graph_expansion", None)
        citation.pop("graph_relationships", None)

    proof = module.run_eval(fixture)
    checks = proof["cases"][0]["checks"]

    assert proof["status"] == "fail"
    assert checks["raw_graph_metadata_preserved"] is False
    assert checks["expert_graph_metadata_preserved"] is False


@pytest.mark.parametrize("field", ["live_corpus_verified", "live_provider_verified"])
def test_eval_rejects_false_live_claims(field):
    module = load_module()
    fixture = module.load_fixture(FIXTURE)
    fixture[field] = True

    with pytest.raises(module.ExpertCorpusEvalError, match=f"{field} must be false"):
        module.run_eval(fixture)


def test_caller_docs_define_thin_recommended_expert_mcp_contract():
    caller_doc = (ROOT / "docs" / "CALLER_AGENT_INTEGRATION.md").read_text(encoding="utf-8")
    section = caller_doc.split("## Recommended MCP-facing expert tools", 1)[1].split(
        "## Processing boundary", 1
    )[0]

    assert "`list_exais_experts`" in section
    assert "`ask_exais_expert`" in section
    assert "`submit_expert_feedback`" in section
    assert "GET /v1/experts" in section
    assert "POST /v1/experts/{expert_id}/messages" in section
    assert "POST /v1/experts/{expert_id}/feedback" in section
    assert "Use expert sessions first" in section
    assert "never tool arguments" in section
    assert "provider SDK calls" in section
    assert "citation construction or repair" in section
    assert "personal Codex" in section

    playbook = (ROOT / "docs" / "JURISDICTION_VECTOR_STORE_PLAYBOOK.md").read_text(
        encoding="utf-8"
    )
    assert "Each graph-capable vector store should define an optional expert profile and an\neval set." in playbook
    assert "compare the raw search\n  evidence with the expert-session answer" in playbook

    api_doc = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    assert "`list_exais_experts`, `ask_exais_expert`, and `submit_expert_feedback`" in api_doc
    assert "python evals/expert-sessions/run_eval.py" in api_doc


def test_expert_mcp_http_mappings_use_named_openapi_components():
    schema = app.openapi()
    list_operation = schema["paths"]["/v1/experts"]["get"]
    ask_operation = schema["paths"]["/v1/experts/{expert_id}/messages"]["post"]
    feedback_operation = schema["paths"]["/v1/experts/{expert_id}/feedback"]["post"]

    assert list_operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ExpertProfileListResponse")
    assert ask_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ExpertMessageRequest"
    )
    assert ask_operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ExpertMessageResponse")
    assert feedback_operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ExpertFeedbackRequest")
    assert feedback_operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ExpertFeedbackResponse")
