import pytest
from pydantic import ValidationError

from svs_common.openai_compat import (
    apply_openai_ranking_options,
    OpenAICompatError,
    file_attribute_payload,
    openai_filter_to_internal,
    openai_search_options_to_search_request_kwargs,
    safe_file_attributes,
    vector_store_search_results_page,
)
from svs_common.schemas import ChunkRecord, OpenAIVectorStoreSearchRequest


def test_openai_search_maps_max_num_results_to_top_k():
    req = OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=17)

    kwargs = openai_search_options_to_search_request_kwargs(req)

    assert kwargs["query"] == "payment terms"
    assert kwargs["top_k"] == 17


def test_openai_search_keeps_top_k_alias_for_existing_exais_scripts():
    req = OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=17, top_k=5)

    kwargs = openai_search_options_to_search_request_kwargs(req)

    assert kwargs["top_k"] == 5


def test_openai_search_rejects_out_of_range_max_num_results():
    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=51)


def test_openai_search_rejects_unknown_fields_instead_of_ignoring_them():
    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(query="payment terms", unsupported_option=True)


def test_openai_filter_supports_and_of_supported_eq_filters():
    raw_filter = {
        "type": "and",
        "filters": [
            {"type": "eq", "key": "classification", "value": "tenant_private"},
            {"type": "eq", "key": "document_id", "value": "doc_123"},
        ],
    }

    assert openai_filter_to_internal(raw_filter) == {
        "classification": "tenant_private",
        "document_id": "doc_123",
    }


def test_openai_filter_supports_file_attribute_filter():
    assert openai_filter_to_internal({"type": "eq", "key": "region", "value": "us"}) == {
        "file_attribute_filters": {"region": "us"}
    }


def test_openai_filter_rejects_sensitive_file_attribute_filter():
    with pytest.raises(OpenAICompatError, match="sensitive"):
        openai_filter_to_internal({"type": "eq", "key": "api_key", "value": "must-not-index"})


def test_openai_search_accepts_rewrite_and_score_threshold_metadata():
    kwargs = openai_search_options_to_search_request_kwargs(
        OpenAIVectorStoreSearchRequest(
            query="q",
            rewrite_query=True,
            ranking_options={"ranker": "auto", "score_threshold": 0.2},
        )
    )

    assert kwargs["search_metadata"]["openai_compat"]["rewrite_query"] is True
    assert kwargs["search_metadata"]["openai_compat"]["score_threshold"] == 0.2


def test_safe_file_attribute_payload_skips_secrets_and_nested_values():
    attrs = {
        "region": "us",
        "priority": 3,
        "api_key": "must-not-copy",
        "nested": {"no": "objects"},
    }

    assert safe_file_attributes(attrs) == {"region": "us", "priority": 3}
    assert file_attribute_payload(attrs) == {
        "file_attr_region_c697d2981b": "us",
        "file_attr_priority_3092a5f0db": 3,
    }


def test_file_attribute_payload_key_avoids_collisions():
    assert file_attribute_payload({"a.b": "one", "a-b": "two"}) == {
        "file_attr_a_b_2e7336dc8e": "one",
        "file_attr_a_b_d44362d67d": "two",
    }


def test_openai_filter_rejects_non_primitive_values():
    with pytest.raises(OpenAICompatError, match="must compare"):
        openai_filter_to_internal({"type": "eq", "key": "region", "value": ["us"]})


def test_openai_ranking_options_normalize_and_threshold_scores():
    req = OpenAIVectorStoreSearchRequest(query="runpod marker", ranking_options={"ranker": "auto", "score_threshold": 0.5})
    chunks = [
        ChunkRecord(id="chk_1", document_id="doc_1", ordinal=0, text="best", score=10.0),
        ChunkRecord(id="chk_2", document_id="doc_2", ordinal=1, text="weak", score=2.0),
    ]

    ranked = apply_openai_ranking_options(req, chunks)

    assert [ch.id for ch in ranked] == ["chk_1"]
    assert ranked[0].score == 1.0


def test_search_results_page_returns_file_level_metadata():
    req = OpenAIVectorStoreSearchRequest(query="runpod marker", max_num_results=3)
    chunk = ChunkRecord(
        id="chk_1",
        document_id="doc_1",
        ordinal=0,
        text="RunPod Marker retries after endpoint warmup.",
        metadata={"chunker": "pdf_markdown_external_chunks"},
        score=0.42,
    )

    page = vector_store_search_results_page(
        req,
        [chunk],
        {
            "doc_1": {
                "file_id": "vsf_1",
                "filename": "marker-ticket.md",
                "attributes": {"source": "tickets"},
            }
        },
    )

    assert page["object"] == "vector_store.search_results.page"
    assert page["has_more"] is False
    assert page["next_page"] is None
    assert page["data"][0]["file_id"] == "vsf_1"
    assert page["data"][0]["filename"] == "marker-ticket.md"
    assert page["data"][0]["attributes"] == {"source": "tickets"}
    assert page["data"][0]["content"] == [{"type": "text", "text": "RunPod Marker retries after endpoint warmup."}]
