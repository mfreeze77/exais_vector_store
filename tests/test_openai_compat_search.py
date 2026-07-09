import json

import pytest
from pydantic import ValidationError

from svs_common.openai_compat import (
    apply_openai_ranking_options,
    encode_vector_store_search_next_page,
    ensure_openai_response_citation_integrity,
    OpenAICompatError,
    extract_responses_input_text,
    file_attribute_payload,
    openai_file_citation_annotation,
    openai_file_citation_marker_at,
    openai_message_file_citation_annotation,
    openai_model_citation_marker,
    openai_model_citation_source_id,
    openai_responses_file_search_response,
    openai_response_citation_references,
    openai_response_sse_events,
    openai_response_stream_events,
    openai_filter_to_internal,
    openai_search_options_to_search_request_kwargs,
    RESPONSES_FILE_SEARCH_RESULTS_INCLUDE,
    response_with_file_search_include,
    responses_compact_response,
    responses_continuation_query,
    responses_file_search_tools,
    responses_include_search_results,
    responses_input_token_count,
    responses_input_items,
    responses_input_items_page,
    responses_output_text,
    responses_previous_context_text,
    safe_file_attributes,
    extract_openai_model_citations,
    strip_openai_model_citations,
    validate_openai_file_citation_annotation,
    validate_responses_file_search_tool_choice,
    vector_store_search_next_page_offset,
    vector_store_search_page_window,
    vector_store_search_results_page,
)
from svs_common.schemas import (
    ChunkRecord,
    OpenAIFileCitationAnnotation,
    OpenAIMessageFileCitationAnnotation,
    OpenAIResponseFileSearchTool,
    OpenAIVectorStoreSearchRequest,
)


def test_openai_search_maps_max_num_results_to_top_k():
    req = OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=17)

    kwargs = openai_search_options_to_search_request_kwargs(req)

    assert kwargs["query"] == "payment terms"
    assert kwargs["top_k"] == 17


def test_openai_search_keeps_top_k_alias_for_existing_exais_scripts():
    req = OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=17, top_k=5)

    kwargs = openai_search_options_to_search_request_kwargs(req)

    assert kwargs["top_k"] == 5


def test_openai_search_accepts_next_page_cursor_and_records_metadata():
    cursor = encode_vector_store_search_next_page(2)
    req = OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=2, next_page=cursor)

    kwargs = openai_search_options_to_search_request_kwargs(req)

    assert vector_store_search_next_page_offset(cursor) == 2
    assert kwargs["top_k"] == 2
    assert kwargs["search_metadata"]["openai_compat"]["next_page"] == cursor


def test_openai_search_rejects_invalid_next_page_cursor():
    with pytest.raises(OpenAICompatError, match="not a valid vector store search cursor"):
        vector_store_search_next_page_offset("bad-cursor")


def test_openai_search_page_window_returns_opaque_next_page_token():
    req = OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=2)
    chunks = [
        ChunkRecord(id=f"chk_{index}", document_id=f"doc_{index}", ordinal=index, text=f"chunk {index}", score=1.0)
        for index in range(4)
    ]

    first_page, cursor = vector_store_search_page_window(req, chunks)
    second_req = OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=2, next_page=cursor)
    second_page, next_cursor = vector_store_search_page_window(second_req, chunks)

    assert [chunk.id for chunk in first_page] == ["chk_0", "chk_1"]
    assert cursor is not None
    assert vector_store_search_next_page_offset(cursor) == 2
    assert [chunk.id for chunk in second_page] == ["chk_2", "chk_3"]
    assert next_cursor is None


def test_openai_search_rejects_out_of_range_max_num_results():
    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=51)


def test_openai_search_rejects_unknown_fields_instead_of_ignoring_them():
    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(query="payment terms", unsupported_option=True)


def test_openai_file_citation_annotation_contract_is_strict():
    annotation = {
        "type": "file_citation",
        "index": len("Answer "),
        "file_id": "file_contract",
        "filename": "contract.md",
    }

    assert openai_file_citation_annotation(
        file_id="file_contract",
        filename="contract.md",
        index=len("Answer "),
    ) == annotation
    assert validate_openai_file_citation_annotation(annotation, context="contract") == annotation
    assert openai_file_citation_marker_at("Answer 【1†source】", annotation["index"], context="contract") == "【1†source】"

    with pytest.raises(OpenAICompatError, match="strict OpenAI file_citation fields"):
        validate_openai_file_citation_annotation({**annotation, "quote": "not in Responses core"}, context="contract")

    with pytest.raises(OpenAICompatError, match="non-negative integer"):
        validate_openai_file_citation_annotation({**annotation, "index": -1}, context="contract")

    with pytest.raises(OpenAICompatError, match="non-empty string"):
        openai_file_citation_annotation(file_id=" ", filename="contract.md", index=0)

    with pytest.raises(OpenAICompatError, match="non-empty string"):
        validate_openai_file_citation_annotation({**annotation, "filename": ""}, context="contract")

    with pytest.raises(OpenAICompatError, match="visible source marker"):
        openai_file_citation_marker_at("Answer 【1†source】", 0, context="contract")

    with pytest.raises(ValidationError):
        OpenAIFileCitationAnnotation(type="file_citation", index=-1, file_id="file_contract", filename="contract.md")

    with pytest.raises(ValidationError):
        OpenAIFileCitationAnnotation(type="file_citation", index=0, file_id="file_contract", filename=" ")


def test_openai_message_file_citation_annotation_exports_replacement_span():
    annotation = {
        "type": "file_citation",
        "index": len("Answer "),
        "file_id": "file_contract",
        "filename": "contract.md",
    }
    marker = "【1†source】"

    message_annotation = openai_message_file_citation_annotation(
        annotation=annotation,
        start_index=annotation["index"],
        end_index=annotation["index"] + len(marker),
        text=marker,
    )

    assert message_annotation == {
        "type": "file_citation",
        "start_index": annotation["index"],
        "end_index": annotation["index"] + len(marker),
        "text": marker,
        "file_citation": {"file_id": "file_contract"},
    }
    assert OpenAIMessageFileCitationAnnotation.model_validate(message_annotation).model_dump(mode="python") == (
        message_annotation
    )
    with pytest.raises(OpenAICompatError, match="span must match text length"):
        openai_message_file_citation_annotation(
            annotation=annotation,
            start_index=annotation["index"],
            end_index=annotation["index"] + len(marker) + 1,
            text=marker,
        )


def test_openai_model_citation_marker_contract_matches_recommended_format():
    source_id = openai_model_citation_source_id(0)
    marker = openai_model_citation_marker(source_id, locator="L8-L13")
    multi_marker = openai_model_citation_marker(["turn0file0", "turn0file1"])
    text = f"Support one. {marker} Support two. {multi_marker}"

    assert source_id == "turn0file0"
    assert marker == "\ue200cite\ue202turn0file0\ue202L8-L13\ue201"
    assert multi_marker == "\ue200cite\ue202turn0file0\ue202turn0file1\ue201"
    assert extract_openai_model_citations(text) == [
        {
            "raw": marker,
            "family": "cite",
            "source_ids": ["turn0file0"],
            "locator": "L8-L13",
            "start": text.index(marker),
            "end": text.index(marker) + len(marker),
        },
        {
            "raw": multi_marker,
            "family": "cite",
            "source_ids": ["turn0file0", "turn0file1"],
            "locator": None,
            "start": text.index(multi_marker),
            "end": text.index(multi_marker) + len(multi_marker),
        },
    ]
    assert strip_openai_model_citations(text) == "Support one.  Support two. "

    with pytest.raises(OpenAICompatError, match="line range"):
        openai_model_citation_marker(source_id, locator="Paragraph 4")

    with pytest.raises(OpenAICompatError, match="source_id"):
        openai_model_citation_marker("turn0 file0")


def test_openai_search_accepts_query_array():
    req = OpenAIVectorStoreSearchRequest(
        query=["  RunPod Marker warmup  ", "Voyage embeddings"],
        max_num_results=3,
    )

    kwargs = openai_search_options_to_search_request_kwargs(req)

    assert req.query == ["RunPod Marker warmup", "Voyage embeddings"]
    assert kwargs["query"] == ["RunPod Marker warmup", "Voyage embeddings"]
    assert kwargs["top_k"] == 3


def test_openai_search_rejects_invalid_query_arrays():
    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(query=[])

    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(query=["RunPod Marker warmup", " "])

    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(query=["RunPod Marker warmup", 123])


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


def test_openai_filter_supports_file_attribute_in_filter():
    assert openai_filter_to_internal({"type": "in", "key": "category", "value": ["blog", "announcement"]}) == {
        "file_attribute_filter_any": [
            {"category": "blog"},
            {"category": "announcement"},
        ]
    }


def test_openai_filter_supports_file_attribute_negation_filters():
    assert openai_filter_to_internal({"type": "ne", "key": "region", "value": "us"}) == {
        "file_attribute_not_filters": [{"key": "region", "value": "us"}]
    }
    assert openai_filter_to_internal({"type": "nin", "key": "category", "value": ["blog", "announcement"]}) == {
        "file_attribute_not_any": [{"key": "category", "values": ["blog", "announcement"]}]
    }


def test_openai_filter_supports_or_of_file_attribute_filters():
    raw_filter = {
        "type": "or",
        "filters": [
            {"type": "eq", "key": "region", "value": "us"},
            {"type": "in", "key": "category", "value": ["blog", "announcement"]},
        ],
    }

    assert openai_filter_to_internal(raw_filter) == {
        "file_attribute_filter_any": [
            {"region": "us"},
            {"category": "blog"},
            {"category": "announcement"},
        ]
    }


def test_openai_filter_supports_and_with_file_attribute_in_filter():
    raw_filter = {
        "type": "and",
        "filters": [
            {"type": "eq", "key": "region", "value": "us"},
            {"type": "in", "key": "category", "value": ["blog", "announcement"]},
        ],
    }

    assert openai_filter_to_internal(raw_filter) == {
        "file_attribute_filters": {"region": "us"},
        "file_attribute_filter_any": [
            {"category": "blog"},
            {"category": "announcement"},
        ],
    }


def test_openai_filter_supports_file_attribute_range_filters():
    assert openai_filter_to_internal({"type": "gte", "key": "created_at", "value": "2026-01-01"}) == {
        "file_attribute_ranges": [{"key": "created_at", "op": "gte", "value": "2026-01-01"}]
    }
    assert openai_filter_to_internal({"type": "lt", "key": "priority", "value": 10}) == {
        "file_attribute_ranges": [{"key": "priority", "op": "lt", "value": 10}]
    }


def test_openai_filter_supports_and_with_file_attribute_range_filters():
    raw_filter = {
        "type": "and",
        "filters": [
            {"type": "eq", "key": "region", "value": "us"},
            {"type": "gte", "key": "created_at", "value": "2026-01-01"},
            {"type": "lt", "key": "created_at", "value": "2026-02-01"},
        ],
    }

    assert openai_filter_to_internal(raw_filter) == {
        "file_attribute_filters": {"region": "us"},
        "file_attribute_ranges": [
            {"key": "created_at", "op": "gte", "value": "2026-01-01"},
            {"key": "created_at", "op": "lt", "value": "2026-02-01"},
        ],
    }


def test_openai_filter_supports_and_with_file_attribute_negation_filters():
    raw_filter = {
        "type": "and",
        "filters": [
            {"type": "eq", "key": "region", "value": "us"},
            {"type": "ne", "key": "status", "value": "draft"},
            {"type": "nin", "key": "category", "value": ["blog", "announcement"]},
        ],
    }

    assert openai_filter_to_internal(raw_filter) == {
        "file_attribute_filters": {"region": "us"},
        "file_attribute_not_filters": [{"key": "status", "value": "draft"}],
        "file_attribute_not_any": [{"key": "category", "values": ["blog", "announcement"]}],
    }


def test_openai_filter_rejects_sensitive_file_attribute_filter():
    with pytest.raises(OpenAICompatError, match="sensitive"):
        openai_filter_to_internal({"type": "eq", "key": "api_key", "value": "must-not-index"})


def test_openai_filter_rejects_sensitive_file_attribute_in_filter():
    with pytest.raises(OpenAICompatError, match="sensitive"):
        openai_filter_to_internal({"type": "in", "key": "api_key", "value": ["must-not-index"]})


def test_openai_filter_rejects_sensitive_file_attribute_negation_filter():
    with pytest.raises(OpenAICompatError, match="sensitive"):
        openai_filter_to_internal({"type": "ne", "key": "api_key", "value": "must-not-index"})

    with pytest.raises(OpenAICompatError, match="sensitive"):
        openai_filter_to_internal({"type": "nin", "key": "api_key", "value": ["must-not-index"]})


def test_openai_filter_rejects_internal_or_filters():
    with pytest.raises(OpenAICompatError, match="file attribute"):
        openai_filter_to_internal({
            "type": "or",
            "filters": [
                {"type": "eq", "key": "document_id", "value": "doc_1"},
                {"type": "eq", "key": "region", "value": "us"},
            ],
        })


def test_openai_filter_rejects_invalid_range_filters():
    with pytest.raises(OpenAICompatError, match="file attributes only"):
        openai_filter_to_internal({"type": "gte", "key": "document_id", "value": "doc_1"})

    with pytest.raises(OpenAICompatError, match="string or number"):
        openai_filter_to_internal({"type": "gte", "key": "active", "value": True})

    with pytest.raises(OpenAICompatError, match="string or number"):
        openai_filter_to_internal({"type": "gte", "key": "category", "value": ["blog"]})

    with pytest.raises(OpenAICompatError, match="sensitive"):
        openai_filter_to_internal({"type": "gte", "key": "api_key", "value": "sk-proj-redacted"})


def test_openai_filter_rejects_invalid_negation_filters():
    with pytest.raises(OpenAICompatError, match="file attributes only"):
        openai_filter_to_internal({"type": "ne", "key": "document_id", "value": "doc_1"})

    with pytest.raises(OpenAICompatError, match="file attributes only"):
        openai_filter_to_internal({"type": "nin", "key": "document_id", "value": ["doc_1"]})

    with pytest.raises(OpenAICompatError, match="string, number, or boolean"):
        openai_filter_to_internal({"type": "ne", "key": "region", "value": ["us"]})

    with pytest.raises(OpenAICompatError, match="non-empty value list"):
        openai_filter_to_internal({"type": "nin", "key": "region", "value": []})


def test_openai_filter_rejects_or_with_range_filters():
    with pytest.raises(OpenAICompatError, match="or filters"):
        openai_filter_to_internal({
            "type": "or",
            "filters": [
                {"type": "eq", "key": "region", "value": "us"},
                {"type": "gte", "key": "created_at", "value": "2026-01-01"},
            ],
        })


def test_openai_filter_rejects_or_with_negation_filters():
    with pytest.raises(OpenAICompatError, match="or filters"):
        openai_filter_to_internal({
            "type": "or",
            "filters": [
                {"type": "eq", "key": "region", "value": "us"},
                {"type": "ne", "key": "status", "value": "draft"},
            ],
        })


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


def test_openai_search_records_ranker_none_metadata():
    kwargs = openai_search_options_to_search_request_kwargs(
        OpenAIVectorStoreSearchRequest(
            query="q",
            ranking_options={"ranker": "none", "score_threshold": 0.2},
        )
    )

    assert kwargs["search_metadata"]["openai_compat"]["ranker"] == "none"
    assert kwargs["search_metadata"]["openai_compat"]["score_threshold"] == 0.2


def test_openai_search_accepts_hybrid_ranking_weights_metadata():
    kwargs = openai_search_options_to_search_request_kwargs(
        OpenAIVectorStoreSearchRequest(
            query="q",
            ranking_options={
                "ranker": "auto",
                "hybrid_search": {"embedding_weight": 0.75, "text_weight": 0.25},
            },
        )
    )

    assert kwargs["search_metadata"]["openai_compat"]["hybrid_search"] == {
        "embedding_weight": 0.75,
        "text_weight": 0.25,
    }


def test_openai_search_accepts_rrf_hybrid_weight_aliases():
    req = OpenAIVectorStoreSearchRequest(
        query="q",
        ranking_options={
            "ranker": "auto",
            "hybrid_search": {"rrf_embedding_weight": 0.2, "rrf_text_weight": 0.8},
        },
    )

    assert req.ranking_options.hybrid_search.embedding_weight == 0.2
    assert req.ranking_options.hybrid_search.text_weight == 0.8


def test_openai_search_rejects_empty_or_zero_hybrid_weights():
    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(query="q", ranking_options={"hybrid_search": {}})

    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(
            query="q",
            ranking_options={"hybrid_search": {"embedding_weight": 0, "text_weight": 0}},
        )


def test_openai_search_rejects_negative_hybrid_weight():
    with pytest.raises(ValidationError):
        OpenAIVectorStoreSearchRequest(
            query="q",
            ranking_options={"hybrid_search": {"embedding_weight": -0.1}},
        )


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
        page_start=2,
        page_end=3,
        heading_path=["RunPod", "Warmup"],
        score=0.42,
    )

    page = vector_store_search_results_page(
        req,
        [chunk],
        {
            "doc_1": {
                "file_id": "vsf_1",
                "title": "Marker ticket",
                "filename": "marker-ticket.md",
                "source_uri": "https://docs.example.test/marker-ticket.md",
                "attributes": {"source": "tickets"},
            }
        },
    )

    marker = "【1†source】"
    result_text = f"RunPod Marker retries after endpoint warmup. {marker}"
    marker_index = result_text.index(marker)
    annotation = {
        "type": "file_citation",
        "index": marker_index,
        "file_id": "vsf_1",
        "filename": "marker-ticket.md",
    }

    assert page["object"] == "vector_store.search_results.page"
    assert page["has_more"] is False
    assert page["next_page"] is None
    assert page["data"][0]["file_id"] == "vsf_1"
    assert page["data"][0]["filename"] == "marker-ticket.md"
    assert page["data"][0]["attributes"] == {"source": "tickets"}
    assert page["data"][0]["content"] == [{
        "type": "text",
        "text": result_text,
        "annotations": [annotation],
    }]
    assert page["data"][0]["annotations"] == [annotation]
    assert page["data"][0]["citation"]["annotation"] == annotation
    assert page["data"][0]["citation"]["marker"] == marker
    assert page["data"][0]["citation"]["start_index"] == marker_index
    assert page["data"][0]["citation"]["end_index"] == marker_index + len(marker)
    assert page["data"][0]["citation"]["message_annotation"] == {
        "type": "file_citation",
        "start_index": marker_index,
        "end_index": marker_index + len(marker),
        "text": marker,
        "file_citation": {"file_id": "vsf_1"},
    }
    assert page["data"][0]["citation"]["model_source_id"] == "turn0file0"
    assert page["data"][0]["citation"]["model_marker"] == "\ue200cite\ue202turn0file0\ue201"
    assert page["data"][0]["citation"]["type"] == "file_citation"
    assert page["data"][0]["citation"]["chunk_id"] == "chk_1"
    assert page["data"][0]["citation"]["document_id"] == "doc_1"
    assert page["data"][0]["citation"]["title"] == "Marker ticket"
    assert page["data"][0]["citation"]["page_start"] == 2
    assert page["data"][0]["citation"]["page_end"] == 3
    assert page["data"][0]["citation"]["heading_path"] == ["RunPod", "Warmup"]
    assert page["data"][0]["citation"]["url"] == "https://docs.example.test/marker-ticket.md"
    assert page["citations"] == [page["data"][0]["citation"]]


def test_search_results_page_keeps_openai_citations_when_content_excluded():
    req = OpenAIVectorStoreSearchRequest(query="runpod marker", include_content=False)
    chunk = ChunkRecord(
        id="chk_1",
        document_id="doc_1",
        file_id="vsf_1",
        filename="marker-ticket.md",
        ordinal=0,
        text="RunPod Marker retries after endpoint warmup. Contact alice@example.com.",
        score=0.42,
    )

    page = vector_store_search_results_page(req, [chunk], {})

    assert page["data"][0]["content"] == []
    assert page["data"][0]["annotations"] == [{
        "type": "file_citation",
        "index": 0,
        "file_id": "vsf_1",
        "filename": "marker-ticket.md",
    }]
    assert page["data"][0]["citation"]["annotation"] == page["data"][0]["annotations"][0]
    assert page["data"][0]["citation"]["chunk_id"] == "chk_1"
    assert "output_guard" not in page["data"][0]


def test_search_results_page_redacts_sensitive_output_without_changing_citation_shape():
    req = OpenAIVectorStoreSearchRequest(query="incident contact", max_num_results=3)
    chunk = ChunkRecord(
        id="chk_sensitive",
        document_id="doc_sensitive",
        ordinal=0,
        text=(
            "Escalate to alice@example.com at 913-555-1212. "
            "password=hunter2 token=abcdef0123456789 sk-proj-abcdefghijklmnop"
        ),
        score=0.9,
    )

    page = vector_store_search_results_page(
        req,
        [chunk],
        {
            "doc_sensitive": {
                "file_id": "file_sensitive",
                "filename": "incident.md",
                "attributes": {"region": "us"},
            }
        },
    )

    item = page["data"][0]
    text = item["content"][0]["text"]
    annotation = item["content"][0]["annotations"][0]

    assert "alice@example.com" not in text
    assert "913-555-1212" not in text
    assert "hunter2" not in text
    assert "abcdef0123456789" not in text
    assert "sk-proj-abcdefghijklmnop" not in text
    assert "[REDACTED_EMAIL]" in text
    assert "[REDACTED_PHONE]" in text
    assert "[REDACTED_SECRET]" in text
    marker = "【1†source】"
    marker_index = text.index(marker)
    assert text.endswith(marker)
    assert item["score"] == 0.9
    assert item["attributes"] == {"region": "us"}
    assert item["citation"]["chunk_id"] == "chk_sensitive"
    assert item["citation"]["annotation"] == annotation
    assert item["citation"]["marker"] == marker
    assert annotation == {
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_sensitive",
        "filename": "incident.md",
    }
    assert set(annotation) == {"type", "index", "file_id", "filename"}
    assert item["output_guard"]["id"] == "pii_secret_citation_guard_v1"


def test_responses_input_text_extracts_common_message_shapes():
    raw_input = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "What changed in the runbook?"},
                {"type": "input_file", "file_id": "file_ignore"},
            ],
        }
    ]

    assert extract_responses_input_text(raw_input) == "What changed in the runbook?"


def test_responses_input_items_normalize_string_and_message_shapes():
    assert responses_input_items("What changed?", item_id="msg_input") == [{
        "id": "msg_input",
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "What changed?"}],
    }]

    items = responses_input_items(
        [{"role": "user", "content": [{"type": "input_text", "text": "Where is it?"}]}],
        item_id="msg_input",
    )

    assert items == [{
        "id": "msg_input_0",
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "Where is it?"}],
    }]


def test_responses_previous_context_text_and_continuation_query():
    previous_response = {
        "output": [{
            "type": "message",
            "content": [{
                "type": "output_text",
                "text": "Prior answer mentions RunPod warmup. \ue200cite\ue202turn0file0\ue201 【1†source】",
                "annotations": [],
            }],
        }]
    }
    previous_input_items = [{
        "id": "msg_prev",
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "What did the first result say?"}],
    }]

    assert responses_output_text(previous_response) == "Prior answer mentions RunPod warmup."
    context = responses_previous_context_text(previous_response, previous_input_items)
    query = responses_continuation_query("How does that affect retries?", context)

    assert "What did the first result say?" in context
    assert "Prior answer mentions RunPod warmup." in context
    assert "【1†source】" not in context
    assert "\ue200cite" not in context
    assert query.startswith("How does that affect retries?\n\n")
    assert "RunPod warmup" in query


def test_responses_input_items_page_supports_order_limit_and_after():
    items = [
        {"id": "msg_1", "type": "message", "role": "user", "content": []},
        {"id": "msg_2", "type": "message", "role": "user", "content": []},
        {"id": "msg_3", "type": "message", "role": "user", "content": []},
    ]

    page = responses_input_items_page(items, limit=1, order="desc")
    assert page["data"] == [items[2]]
    assert page["first_id"] == "msg_3"
    assert page["last_id"] == "msg_3"
    assert page["has_more"] is True

    after_page = responses_input_items_page(items, limit=2, order="desc", after="msg_3")
    assert [item["id"] for item in after_page["data"]] == ["msg_2", "msg_1"]
    assert after_page["has_more"] is False


def test_responses_file_search_tools_validate_openai_shape():
    tools = responses_file_search_tools([
        {
            "type": "file_search",
            "vector_store_ids": ["vs_123"],
            "max_num_results": 3,
            "filters": {"type": "eq", "key": "region", "value": "us"},
        }
    ])

    assert tools == [{
        "type": "file_search",
        "vector_store_ids": ["vs_123"],
        "filters": {"type": "eq", "key": "region", "value": "us"},
        "max_num_results": 3,
        "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
    }]


def test_responses_file_search_tools_default_to_openai_result_count():
    tools = responses_file_search_tools([{
        "type": "file_search",
        "vector_store_ids": ["vs_123"],
    }])

    assert OpenAIResponseFileSearchTool(vector_store_ids=["vs_123"]).max_num_results == 20
    assert tools[0]["max_num_results"] == 20


def test_responses_file_search_tools_reject_unsupported_tools():
    with pytest.raises(OpenAICompatError, match="only file_search"):
        responses_file_search_tools([{"type": "web_search_preview"}])


def test_responses_file_search_tool_choice_accepts_file_search_choices():
    for tool_choice in (
        None,
        "auto",
        "required",
        {"type": "file_search"},
        {"type": "allowed_tools", "mode": "auto", "tools": [{"type": "file_search"}]},
        {"type": "allowed_tools", "mode": "required", "tools": [{"type": "file_search"}]},
    ):
        validate_responses_file_search_tool_choice(tool_choice)


@pytest.mark.parametrize(
    "tool_choice",
    [
        "none",
        "web_search_preview",
        {"type": "web_search_preview"},
        {"type": "function", "name": "lookup"},
        {"type": "allowed_tools", "mode": "auto", "tools": [{"type": "web_search_preview"}]},
        {"type": "allowed_tools", "mode": "none", "tools": [{"type": "file_search"}]},
        {"type": "allowed_tools", "mode": "auto", "tools": []},
        {"type": "allowed_tools", "mode": "auto", "tools": ["file_search"]},
        {},
        7,
    ],
)
def test_responses_file_search_tool_choice_rejects_non_file_search_choices(tool_choice):
    with pytest.raises(OpenAICompatError):
        validate_responses_file_search_tool_choice(tool_choice)


def test_responses_include_accepts_current_and_cookbook_file_search_results_paths():
    assert responses_include_search_results(["file_search_call.results"]) is True
    assert responses_include_search_results([RESPONSES_FILE_SEARCH_RESULTS_INCLUDE]) is True
    assert responses_include_search_results(["output[*].file_search_call.results"]) is True
    assert responses_include_search_results(None) is False

    with pytest.raises(OpenAICompatError, match="Unsupported Responses include paths"):
        responses_include_search_results(["message.output_text.logprobs"])


def test_responses_input_token_count_counts_text_and_tools():
    text_only = responses_input_token_count({"input": "Short support question"})
    with_tools = responses_input_token_count({
        "input": [{
            "role": "user",
            "content": [{"type": "input_text", "text": "Short support question"}],
        }],
        "instructions": "Answer from retrieved files only.",
        "tools": [{"type": "file_search", "vector_store_ids": ["vs_123"], "max_num_results": 5}],
    })

    assert text_only > 0
    assert with_tools > text_only


def test_responses_input_token_count_rejects_non_object_payload():
    with pytest.raises(OpenAICompatError, match="payload must be an object"):
        responses_input_token_count(["not", "an", "object"])


def test_responses_compact_response_returns_openai_compaction_shape():
    payload = {
        "model": "gpt-5.4",
        "input": [
            {
                "role": "user",
                "content": "Create a simple landing page.",
            },
            {
                "id": "msg_assistant",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Assistant details that should compact."}],
            },
        ],
    }

    response = responses_compact_response(
        payload=payload,
        response_id="resp_compact",
        compaction_id="cmp_compact",
        item_id="msg_compact",
        created_at=1710000000,
    )

    assert response["id"] == "resp_compact"
    assert response["object"] == "response.compaction"
    assert response["created_at"] == 1710000000
    assert response["output"][0] == {
        "id": "msg_compact_0",
        "type": "message",
        "status": "completed",
        "role": "user",
        "content": [{"type": "input_text", "text": "Create a simple landing page."}],
    }
    compaction = response["output"][1]
    assert compaction["id"] == "cmp_compact"
    assert compaction["type"] == "compaction"
    assert compaction["encrypted_content"].startswith("svs_compaction_v1_")
    assert "Assistant details" not in compaction["encrypted_content"]
    assert response["usage"]["input_tokens"] > 0
    assert response["usage"]["output_tokens"] > 0
    assert response["usage"]["total_tokens"] == response["usage"]["input_tokens"] + response["usage"]["output_tokens"]


def test_responses_compact_response_rejects_invalid_payloads():
    with pytest.raises(OpenAICompatError, match="payload must be an object"):
        responses_compact_response(
            payload=["not", "object"],
            response_id="resp_compact",
            compaction_id="cmp_compact",
            item_id="msg_compact",
            created_at=1710000000,
        )
    with pytest.raises(OpenAICompatError, match="model must be a non-empty string"):
        responses_compact_response(
            payload={"input": "Missing model"},
            response_id="resp_compact",
            compaction_id="cmp_compact",
            item_id="msg_compact",
            created_at=1710000000,
        )
    with pytest.raises(OpenAICompatError, match="does not support streaming"):
        responses_compact_response(
            payload={"model": "gpt-5.4", "stream": True},
            response_id="resp_compact",
            compaction_id="cmp_compact",
            item_id="msg_compact",
            created_at=1710000000,
        )


def test_responses_file_search_response_places_citations_on_output_text():
    req = OpenAIVectorStoreSearchRequest(query="runpod marker")
    chunk = ChunkRecord(
        id="chk_1",
        document_id="doc_1",
        ordinal=0,
        text="RunPod Marker retries after endpoint warmup.",
        score=0.8,
    )
    page = vector_store_search_results_page(
        req,
        [chunk],
        {
            "doc_1": {
                "file_id": "file_abc",
                "title": "Marker ticket",
                "filename": "marker-ticket.md",
                "source_uri": "https://docs.example.test/marker-ticket.md",
                "attributes": {"region": "us"},
            }
        },
    )

    response = openai_responses_file_search_response(
        payload={
            "model": "gpt-5.4-mini",
            "input": "What changed?",
            "include": [RESPONSES_FILE_SEARCH_RESULTS_INCLUDE],
        },
        query="What changed?",
        tools=[{
            "type": "file_search",
            "vector_store_ids": ["vs_123"],
            "filters": None,
            "max_num_results": 10,
            "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
        }],
        search_pages=[{"vector_store_id": "vs_123", "page": page}],
        response_id="resp_test",
        message_id="msg_test",
        file_search_call_id="fs_test",
        created_at=1710000000,
        include_search_results=True,
    )

    assert response["object"] == "response"
    assert response["status"] == "completed"
    assert response["output"][0]["type"] == "file_search_call"
    assert response["output"][0]["results"][0]["file_id"] == "file_abc"
    assert response["output"][0]["search_results"][0]["file_id"] == "file_abc"
    assert response["output"][0]["search_results"] == response["output"][0]["results"]
    assert set(response["output"][0]["results"][0]) == {"file_id", "filename", "score", "text", "attributes"}
    assert "citation" not in response["output"][0]["results"][0]
    assert "vector_store_id" not in response["output"][0]["results"][0]
    content = response["output"][1]["content"][0]
    assert content["type"] == "output_text"
    marker = "【1†source】"
    assert "[1]" not in content["text"]
    assert content["text"].count(marker) == 1
    citation_index = content["text"].index(marker)
    assert content["text"][citation_index:citation_index + len(marker)] == marker
    assert content["annotations"] == [{
        "type": "file_citation",
        "index": citation_index,
        "file_id": "file_abc",
        "filename": "marker-ticket.md",
    }]
    assert response["citations"][0]["index"] == citation_index
    assert response["citations"][0]["marker"] == marker
    assert response["citations"][0]["start_index"] == citation_index
    assert response["citations"][0]["end_index"] == citation_index + len(marker)
    assert response["citations"][0]["annotation"] == content["annotations"][0]
    assert response["citations"][0]["message_annotation"] == {
        "type": "file_citation",
        "start_index": citation_index,
        "end_index": citation_index + len(marker),
        "text": marker,
        "file_citation": {"file_id": "file_abc"},
    }
    assert set(response["citations"][0]["annotation"]) == {"type", "index", "file_id", "filename"}
    assert response["citations"][0]["chunk_id"] == "chk_1"
    assert response["citations"][0]["vector_store_id"] == "vs_123"
    assert response["citations"][0]["model_source_id"] == "turn0file0"
    assert response["citations"][0]["model_marker"] == "\ue200cite\ue202turn0file0\ue201"

    stripped = response_with_file_search_include(response, include_search_results=False)
    assert stripped["output"][0]["results"] is None
    assert stripped["output"][0]["search_results"] is None

    included = response_with_file_search_include(response, include_search_results=True)
    assert included["output"][0]["results"][0]["file_id"] == "file_abc"
    assert included["output"][0]["search_results"][0]["file_id"] == "file_abc"
    assert "output_guard" not in response


def test_responses_file_search_citations_match_openai_guide_contract():
    req = OpenAIVectorStoreSearchRequest(query="citation contract")
    chunk = ChunkRecord(
        id="chk_contract",
        document_id="doc_contract",
        ordinal=0,
        text="Contract proof text for OpenAI file-search citation rendering.",
        score=0.91,
    )
    page = vector_store_search_results_page(
        req,
        [chunk],
        {
            "doc_contract": {
                "file_id": "file_contract",
                "filename": "citation-contract.md",
                "attributes": {"topic": "citations"},
            }
        },
    )

    response = openai_responses_file_search_response(
        payload={
            "model": "gpt-5.4-mini",
            "input": "Show the citation contract.",
            "include": ["file_search_call.results"],
        },
        query="Show the citation contract.",
        tools=[{
            "type": "file_search",
            "vector_store_ids": ["vs_contract"],
            "filters": None,
            "max_num_results": 10,
            "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
        }],
        search_pages=[{"vector_store_id": "vs_contract", "page": page}],
        response_id="resp_contract",
        message_id="msg_contract",
        file_search_call_id="fs_contract",
        created_at=1710000000,
        include_search_results=True,
    )

    file_search_call = response["output"][0]
    message = response["output"][1]
    content = message["content"][0]
    annotation = content["annotations"][0]
    marker = "【1†source】"
    marker_index = content["text"].index(marker)

    assert set(file_search_call) == {"type", "id", "status", "queries", "results", "search_results"}
    assert file_search_call["type"] == "file_search_call"
    assert file_search_call["id"] == "fs_contract"
    assert file_search_call["status"] == "completed"
    assert file_search_call["queries"] == ["Show the citation contract."]
    assert file_search_call["results"] == file_search_call["search_results"]
    assert set(file_search_call["results"][0]) == {"file_id", "filename", "score", "text", "attributes"}
    assert file_search_call["results"][0]["file_id"] == "file_contract"
    assert file_search_call["results"][0]["filename"] == "citation-contract.md"
    assert "citation" not in file_search_call["results"][0]
    assert "vector_store_id" not in file_search_call["results"][0]

    assert set(message) == {"type", "id", "status", "role", "content"}
    assert message["type"] == "message"
    assert set(content) == {"type", "text", "annotations"}
    assert content["type"] == "output_text"
    assert content["text"][marker_index:marker_index + len(marker)] == marker
    assert annotation == {
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_contract",
        "filename": "citation-contract.md",
    }
    assert set(annotation) == {"type", "index", "file_id", "filename"}
    assert response["citations"][0]["annotation"] == annotation
    assert response["citations"][0]["marker"] == marker

    events = openai_response_stream_events(response, include_obfuscation=False)
    annotation_event = next(event for event in events if event["type"] == "response.output_text.annotation.added")
    assert set(annotation_event) == {
        "type",
        "sequence_number",
        "item_id",
        "output_index",
        "content_index",
        "annotation_index",
        "annotation",
    }
    assert annotation_event["item_id"] == "msg_contract"
    assert annotation_event["output_index"] == 1
    assert annotation_event["content_index"] == 0
    assert annotation_event["annotation_index"] == 0
    assert annotation_event["annotation"] == annotation


def test_responses_file_search_citations_are_client_replaceable_markers():
    req = OpenAIVectorStoreSearchRequest(query="client citation rendering")
    chunk = ChunkRecord(
        id="chk_render",
        document_id="doc_render",
        ordinal=0,
        text="Client renderers replace the visible source marker with their citation UI.",
        score=0.87,
    )
    page = vector_store_search_results_page(
        req,
        [chunk],
        {"doc_render": {"file_id": "file_render", "filename": "rendering.md"}},
    )

    response = openai_responses_file_search_response(
        payload={"model": "gpt-5.4-mini", "input": "How should citations render?"},
        query="How should citations render?",
        tools=[{
            "type": "file_search",
            "vector_store_ids": ["vs_render"],
            "filters": None,
            "max_num_results": 10,
            "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
        }],
        search_pages=[{"vector_store_id": "vs_render", "page": page}],
        response_id="resp_render",
        message_id="msg_render",
        file_search_call_id="fs_render",
        created_at=1710000000,
        include_search_results=False,
    )

    content = response["output"][1]["content"][0]
    references = openai_response_citation_references(response)
    annotation = content["annotations"][0]
    marker = references[0]["text"]
    marker_index = annotation["index"]
    message_annotation = {
        "type": "file_citation",
        "start_index": marker_index,
        "end_index": marker_index + len(marker),
        "text": "【1†source】",
        "file_citation": {"file_id": annotation["file_id"]},
    }
    annotation_event = next(
        event
        for event in openai_response_stream_events(response, include_obfuscation=False)
        if event["type"] == "response.output_text.annotation.added"
    )

    assert references == [{
        "output_index": 1,
        "content_index": 0,
        "annotation_index": 0,
        "start_index": marker_index,
        "end_index": marker_index + len(marker),
        "text": "【1†source】",
        "annotation": annotation,
        "message_annotation": message_annotation,
    }]
    assert content["text"][marker_index:marker_index + len(marker)] == marker
    assert response["citations"][0]["marker"] == marker
    assert response["citations"][0]["start_index"] == marker_index
    assert response["citations"][0]["end_index"] == marker_index + len(marker)
    assert response["citations"][0]["annotation"] == annotation
    assert response["citations"][0]["message_annotation"] == message_annotation
    assert set(annotation) == {"type", "index", "file_id", "filename"}
    assert "text" not in annotation
    assert annotation_event["annotation"] == annotation


def test_responses_citation_integrity_guard_accepts_valid_response():
    req = OpenAIVectorStoreSearchRequest(query="runpod marker")
    chunk = ChunkRecord(
        id="chk_integrity",
        document_id="doc_integrity",
        ordinal=0,
        text="Integrity proof text.",
        score=0.8,
    )
    page = vector_store_search_results_page(
        req,
        [chunk],
        {"doc_integrity": {"file_id": "file_integrity", "filename": "integrity.md"}},
    )
    response = openai_responses_file_search_response(
        payload={"model": "gpt-5.4-mini", "input": "What changed?"},
        query="What changed?",
        tools=[{
            "type": "file_search",
            "vector_store_ids": ["vs_123"],
            "filters": None,
            "max_num_results": 10,
            "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
        }],
        search_pages=[{"vector_store_id": "vs_123", "page": page}],
        response_id="resp_integrity",
        message_id="msg_integrity",
        file_search_call_id="fs_integrity",
        created_at=1710000000,
        include_search_results=True,
    )

    ensure_openai_response_citation_integrity(response)


def test_responses_citation_integrity_guard_accepts_same_index_multi_citations():
    marker_index = len("Shared cited answer ")
    first_annotation = {
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_first",
        "filename": "first-source.md",
    }
    second_annotation = {
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_second",
        "filename": "second-source.md",
    }
    response = {
        "id": "resp_same_index",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [
            {
                "type": "file_search_call",
                "id": "fs_same_index",
                "status": "completed",
                "queries": ["same index citations"],
                "results": None,
                "search_results": None,
            },
            {
                "type": "message",
                "id": "msg_same_index",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": "Shared cited answer 【1†source】",
                    "annotations": [first_annotation, second_annotation],
                }],
            },
        ],
        "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        "citations": [
            {"annotation": first_annotation, "marker": "【1†source】", "chunk_id": "chk_first"},
            {"annotation": second_annotation, "marker": "【1†source】", "chunk_id": "chk_second"},
        ],
    }

    ensure_openai_response_citation_integrity(response)
    events = openai_response_stream_events(response, include_obfuscation=False)
    annotation_events = [
        event for event in events if event["type"] == "response.output_text.annotation.added"
    ]

    assert [event["annotation_index"] for event in annotation_events] == [0, 1]
    assert [event["annotation"] for event in annotation_events] == [first_annotation, second_annotation]
    assert {event["annotation"]["index"] for event in annotation_events} == {marker_index}
    assert all(set(event["annotation"]) == {"type", "index", "file_id", "filename"} for event in annotation_events)
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["citations"][1]["annotation"] == second_annotation


def test_responses_citation_integrity_guard_rejects_extra_annotation_fields():
    annotation = {
        "type": "file_citation",
        "index": len("Answer "),
        "file_id": "file_bad",
        "filename": "bad.md",
        "quote": "extra",
    }
    response = {
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": "Answer 【1†source】", "annotations": [annotation]}],
        }],
        "citations": [{"annotation": annotation, "marker": "【1†source】"}],
    }

    with pytest.raises(OpenAICompatError, match="strict OpenAI file_citation fields"):
        ensure_openai_response_citation_integrity(response)


def test_responses_citation_integrity_guard_rejects_bad_marker_index():
    annotation = {
        "type": "file_citation",
        "index": 0,
        "file_id": "file_bad",
        "filename": "bad.md",
    }
    response = {
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": "Answer 【1†source】", "annotations": [annotation]}],
        }],
        "citations": [{"annotation": annotation, "marker": "Answer"}],
    }

    with pytest.raises(OpenAICompatError, match="visible source marker"):
        ensure_openai_response_citation_integrity(response)


def test_responses_citation_integrity_guard_rejects_orphan_visible_marker():
    annotation = {
        "type": "file_citation",
        "index": len("Answer "),
        "file_id": "file_good",
        "filename": "good.md",
    }
    response = {
        "output": [{
            "type": "message",
            "content": [{
                "type": "output_text",
                "text": "Answer 【1†source】 orphan 【2†source】",
                "annotations": [annotation],
            }],
        }],
        "citations": [{"annotation": annotation, "marker": "【1†source】"}],
    }

    with pytest.raises(OpenAICompatError, match="visible source marker has no OpenAI file_citation annotation"):
        ensure_openai_response_citation_integrity(response)


def test_responses_citation_integrity_guard_rejects_native_annotation_mismatch():
    annotation = {
        "type": "file_citation",
        "index": len("Answer "),
        "file_id": "file_good",
        "filename": "good.md",
    }
    response = {
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": "Answer 【1†source】", "annotations": [annotation]}],
        }],
        "citations": [{
            "annotation": {**annotation, "filename": "other.md"},
            "marker": "【1†source】",
        }],
    }

    with pytest.raises(OpenAICompatError, match="does not mirror"):
        ensure_openai_response_citation_integrity(response)


def test_responses_stream_events_include_openai_citation_annotations():
    annotation = {
        "type": "file_citation",
        "index": 42,
        "file_id": "file_stream",
        "filename": "stream-source.md",
    }
    response = {
        "id": "resp_stream",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [
            {
                "type": "file_search_call",
                "id": "fs_stream",
                "status": "completed",
                "queries": ["stream citation"],
                "results": None,
            },
            {
                "type": "message",
                "id": "msg_stream",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": "Streaming citation proof. 【1†source】",
                    "annotations": [annotation],
                }],
            },
        ],
        "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        "citations": [{"annotation": annotation, "marker": "【1†source】"}],
    }

    events = openai_response_stream_events(response)
    event_types = [event["type"] for event in events]

    assert event_types[:2] == ["response.created", "response.in_progress"]
    assert "response.file_search_call.in_progress" in event_types
    assert "response.file_search_call.searching" in event_types
    assert "response.file_search_call.completed" in event_types
    assert "response.output_text.delta" in event_types
    assert "response.output_text.annotation.added" in event_types
    assert "response.output_text.done" in event_types
    assert event_types[-1] == "response.completed"
    assert [event["sequence_number"] for event in events] == list(range(1, len(events) + 1))
    assert event_types.index("response.output_text.annotation.added") < event_types.index("response.output_text.done")
    assert event_types.index("response.output_text.done") < event_types.index("response.content_part.done")

    file_search_added = next(
        event
        for event in events
        if event["type"] == "response.output_item.added"
        and event["item"].get("type") == "file_search_call"
    )
    assert file_search_added["item"] == {
        "type": "file_search_call",
        "id": "fs_stream",
        "status": "in_progress",
        "queries": [],
        "results": None,
        "search_results": None,
    }
    file_search_done = next(
        event
        for event in events
        if event["type"] == "response.output_item.done"
        and event["item"].get("type") == "file_search_call"
    )
    assert file_search_done["item"]["queries"] == ["stream citation"]
    assert file_search_done["item"]["results"] is None

    delta_event = next(event for event in events if event["type"] == "response.output_text.delta")
    assert isinstance(delta_event["obfuscation"], str)
    assert delta_event["obfuscation"]
    annotation_event = next(event for event in events if event["type"] == "response.output_text.annotation.added")
    assert annotation_event["annotation"] == annotation
    assert "obfuscation" not in annotation_event
    text_done = next(event for event in events if event["type"] == "response.output_text.done")
    assert text_done["text"] == "Streaming citation proof. 【1†source】"
    assert "annotations" not in text_done
    content_done = next(event for event in events if event["type"] == "response.content_part.done")
    assert content_done["part"]["annotations"] == [annotation]
    completed = events[-1]["response"]
    assert completed["output"][1]["content"][0]["annotations"] == [annotation]
    assert completed["citations"][0]["annotation"] == annotation

    sse_payload = "".join(openai_response_sse_events(response))
    assert "event: response.output_text.annotation.added" in sse_payload
    parsed = [
        json.loads(line.removeprefix("data: "))
        for line in sse_payload.splitlines()
        if line.startswith("data: ")
    ]
    assert parsed[-1]["type"] == "response.completed"

    resumed_payload = "".join(openai_response_sse_events(response, starting_after=annotation_event["sequence_number"] - 1))
    resumed = [
        json.loads(line.removeprefix("data: "))
        for line in resumed_payload.splitlines()
        if line.startswith("data: ")
    ]
    assert resumed[0]["type"] == "response.output_text.annotation.added"
    assert resumed[0]["annotation"] == annotation
    assert all(event["sequence_number"] > annotation_event["sequence_number"] - 1 for event in resumed)

    unobfuscated_events = openai_response_stream_events(response, include_obfuscation=False)
    unobfuscated_delta = next(event for event in unobfuscated_events if event["type"] == "response.output_text.delta")
    assert "obfuscation" not in unobfuscated_delta
    unobfuscated_sse = "".join(openai_response_sse_events(response, include_obfuscation=False))
    assert '"obfuscation"' not in unobfuscated_sse


def test_responses_file_search_response_numbers_multiple_openai_citations():
    req = OpenAIVectorStoreSearchRequest(query="runpod marker")
    chunks = [
        ChunkRecord(
            id="chk_first",
            document_id="doc_first",
            ordinal=0,
            text="First source explains endpoint warmup behavior.",
            score=0.9,
        ),
        ChunkRecord(
            id="chk_second",
            document_id="doc_second",
            ordinal=1,
            text="Second source confirms retry behavior after warmup.",
            score=0.7,
        ),
    ]
    page = vector_store_search_results_page(
        req,
        chunks,
        {
            "doc_first": {
                "file_id": "file_first",
                "filename": "first-source.md",
            },
            "doc_second": {
                "file_id": "file_second",
                "filename": "second-source.md",
            },
        },
    )

    response = openai_responses_file_search_response(
        payload={
            "model": "gpt-5.4-mini",
            "input": "What confirms warmup retries?",
        },
        query="What confirms warmup retries?",
        tools=[{
            "type": "file_search",
            "vector_store_ids": ["vs_123"],
            "filters": None,
            "max_num_results": 10,
            "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
        }],
        search_pages=[{"vector_store_id": "vs_123", "page": page}],
        response_id="resp_multi",
        message_id="msg_multi",
        file_search_call_id="fs_multi",
        created_at=1710000000,
        include_search_results=False,
    )

    file_search_call = response["output"][0]
    content = response["output"][1]["content"][0]
    output_text = content["text"]
    first_marker = "【1†source】"
    second_marker = "【2†source】"
    first_index = output_text.index(first_marker)
    second_index = output_text.index(second_marker)

    assert first_index < second_index
    assert "[1]" not in output_text
    assert "[2]" not in output_text
    assert file_search_call["results"] is None
    assert file_search_call["search_results"] is None
    assert content["annotations"] == [
        {
            "type": "file_citation",
            "index": first_index,
            "file_id": "file_first",
            "filename": "first-source.md",
        },
        {
            "type": "file_citation",
            "index": second_index,
            "file_id": "file_second",
            "filename": "second-source.md",
        },
    ]
    assert [citation["marker"] for citation in response["citations"]] == [first_marker, second_marker]
    assert [citation["annotation"] for citation in response["citations"]] == content["annotations"]
    assert [citation["message_annotation"]["text"] for citation in response["citations"]] == [
        first_marker,
        second_marker,
    ]
    assert [citation["chunk_id"] for citation in response["citations"]] == ["chk_first", "chk_second"]


def test_responses_file_search_response_redacts_results_and_preserves_marker_indexes():
    annotation = {
        "type": "file_citation",
        "index": 0,
        "file_id": "file_sensitive",
        "filename": "incident.md",
    }
    raw_page = {
        "object": "vector_store.search_results.page",
        "search_query": "incident contact",
        "data": [{
            "file_id": "file_sensitive",
            "filename": "incident.md",
            "score": 0.91,
            "attributes": {"region": "us"},
            "content": [{
                "type": "text",
                "text": "Reach bob@example.com. Authorization: Bearer abcdefghijklmnop. SSN 123-45-6789.",
                "annotations": [annotation],
            }],
            "annotations": [annotation],
            "citation": {
                "type": "file_citation",
                "index": 0,
                "file_id": "file_sensitive",
                "filename": "incident.md",
                "chunk_id": "chk_sensitive",
                "document_id": "doc_sensitive",
            },
        }],
        "has_more": False,
        "next_page": None,
    }

    response = openai_responses_file_search_response(
        payload={
            "model": "gpt-5.4-mini",
            "input": "Who is the contact?",
            "include": ["file_search_call.results"],
        },
        query="Who is the contact?",
        tools=[{
            "type": "file_search",
            "vector_store_ids": ["vs_sensitive"],
            "filters": None,
            "max_num_results": 10,
            "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
        }],
        search_pages=[{"vector_store_id": "vs_sensitive", "page": raw_page}],
        response_id="resp_sensitive",
        message_id="msg_sensitive",
        file_search_call_id="fs_sensitive",
        created_at=1710000000,
        include_search_results=True,
    )

    output_text = response["output"][1]["content"][0]["text"]
    result_text = response["output"][0]["results"][0]["text"]
    marker = "【1†source】"
    marker_index = output_text.index(marker)

    assert "bob@example.com" not in output_text
    assert "abcdefghijklmnop" not in output_text
    assert "123-45-6789" not in output_text
    assert "bob@example.com" not in result_text
    assert "abcdefghijklmnop" not in result_text
    assert "123-45-6789" not in result_text
    assert "[REDACTED_EMAIL]" in output_text
    assert "Bearer [REDACTED_SECRET]" in output_text
    assert "[REDACTED_SSN]" in output_text
    assert response["output"][1]["content"][0]["annotations"] == [{
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_sensitive",
        "filename": "incident.md",
    }]
    assert set(response["output"][1]["content"][0]["annotations"][0]) == {"type", "index", "file_id", "filename"}
    assert response["citations"][0]["index"] == marker_index
    assert response["citations"][0]["marker"] == marker
    assert response["citations"][0]["annotation"] == response["output"][1]["content"][0]["annotations"][0]
    assert response["citations"][0]["output_guard"]["id"] == "pii_secret_citation_guard_v1"
    assert response["output"][0]["search_results"] == response["output"][0]["results"]
    assert set(response["output"][0]["results"][0]) == {"file_id", "filename", "score", "text", "attributes"}
    assert "output_guard" not in response["output"][0]["results"][0]
    assert "citation" not in response["output"][0]["results"][0]
    assert response["output_guard"]["id"] == "pii_secret_citation_guard_v1"


def test_responses_file_search_response_dedupes_duplicate_items_across_vector_stores():
    def page_for(*, text: str, score: float) -> dict:
        return {
            "object": "vector_store.search_results.page",
            "search_query": "shared source",
            "data": [{
                "file_id": "file_shared",
                "filename": "shared.md",
                "score": score,
                "attributes": {"region": "us"},
                "content": [{"type": "text", "text": text, "annotations": []}],
                "annotations": [],
                "citation": {
                    "type": "file_citation",
                    "index": 0,
                    "file_id": "file_shared",
                    "filename": "shared.md",
                    "chunk_id": "chk_shared",
                    "document_id": "doc_shared",
                },
            }],
            "has_more": False,
            "next_page": None,
        }

    response = openai_responses_file_search_response(
        payload={
            "model": "gpt-5.4-mini",
            "input": "What is shared?",
            "include": ["file_search_call.results"],
        },
        query="What is shared?",
        tools=[{
            "type": "file_search",
            "vector_store_ids": ["vs_a", "vs_b"],
            "filters": None,
            "max_num_results": 10,
            "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
        }],
        search_pages=[
            {"vector_store_id": "vs_a", "page": page_for(text="Lower scored duplicate text.", score=0.61)},
            {"vector_store_id": "vs_b", "page": page_for(text="Higher scored duplicate text.", score=0.92)},
        ],
        response_id="resp_dupe",
        message_id="msg_dupe",
        file_search_call_id="fs_dupe",
        created_at=1710000000,
        include_search_results=True,
    )

    file_search_call = response["output"][0]
    content = response["output"][1]["content"][0]
    marker = "【1†source】"
    marker_index = content["text"].index(marker)

    assert content["text"].count(marker) == 1
    assert "Higher scored duplicate text." in content["text"]
    assert "Lower scored duplicate text." not in content["text"]
    assert content["annotations"] == [{
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_shared",
        "filename": "shared.md",
    }]
    assert len(file_search_call["results"]) == 1
    assert file_search_call["results"][0] == {
        "file_id": "file_shared",
        "filename": "shared.md",
        "score": 0.92,
        "text": "Higher scored duplicate text.",
        "attributes": {"region": "us"},
    }
    assert file_search_call["search_results"] == file_search_call["results"]
    assert response["citations"][0]["chunk_id"] == "chk_shared"
    assert response["citations"][0]["annotation"] == content["annotations"][0]
    assert response["citations"][0]["vector_store_id"] == "vs_b"
    assert response["citations"][0]["vector_store_ids"] == ["vs_a", "vs_b"]


def test_responses_file_search_response_keeps_distinct_chunks_from_same_file():
    raw_page = {
        "object": "vector_store.search_results.page",
        "search_query": "same file",
        "data": [
            {
                "file_id": "file_shared",
                "filename": "shared.md",
                "score": 0.9,
                "attributes": {},
                "content": [{"type": "text", "text": "First chunk.", "annotations": []}],
                "annotations": [],
                "citation": {
                    "type": "file_citation",
                    "index": 0,
                    "file_id": "file_shared",
                    "filename": "shared.md",
                    "chunk_id": "chk_first",
                },
            },
            {
                "file_id": "file_shared",
                "filename": "shared.md",
                "score": 0.8,
                "attributes": {},
                "content": [{"type": "text", "text": "Second chunk.", "annotations": []}],
                "annotations": [],
                "citation": {
                    "type": "file_citation",
                    "index": 0,
                    "file_id": "file_shared",
                    "filename": "shared.md",
                    "chunk_id": "chk_second",
                },
            },
        ],
        "has_more": False,
        "next_page": None,
    }

    response = openai_responses_file_search_response(
        payload={"model": "gpt-5.4-mini", "input": "What is in the file?"},
        query="What is in the file?",
        tools=[{
            "type": "file_search",
            "vector_store_ids": ["vs_a"],
            "filters": None,
            "max_num_results": 10,
            "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
        }],
        search_pages=[{"vector_store_id": "vs_a", "page": raw_page}],
        response_id="resp_distinct",
        message_id="msg_distinct",
        file_search_call_id="fs_distinct",
        created_at=1710000000,
        include_search_results=False,
    )

    output_text = response["output"][1]["content"][0]["text"]
    assert "【1†source】" in output_text
    assert "【2†source】" in output_text
    assert [citation["chunk_id"] for citation in response["citations"]] == ["chk_first", "chk_second"]
