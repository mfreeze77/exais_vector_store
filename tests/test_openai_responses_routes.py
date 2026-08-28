from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from svs_api import main as api_main
from svs_common.openai_compat import OpenAICompatError, vector_store_search_results_page
from svs_common.schemas import ChunkRecord, OpenAIVectorStoreSearchRequest, Principal, SearchResponse


class _Db:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.committed = False
        self.rows = list(rows or [])
        self.calls = []

    def commit(self) -> None:
        self.committed = True

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        row = self.rows.pop(0) if self.rows else None

        class _Rows:
            def mappings(self):
                return self

            def first(self):
                return row

        return _Rows()


def _principal() -> Principal:
    return Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user",
        api_key_id="ak_test",
        scopes=["retrieval:read"],
    )


@pytest.fixture(autouse=True)
def _disable_route_rate_limits(monkeypatch):
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)


def _search_page(req: OpenAIVectorStoreSearchRequest) -> dict[str, Any]:
    chunk = ChunkRecord(
        id="chk_route_citation",
        document_id="doc_route_citation",
        ordinal=0,
        text="Route-level citation proof should keep OpenAI annotations minimal.",
        metadata={"source": "test"},
        page_start=4,
        page_end=4,
        heading_path=["OpenAI", "Citations"],
        score=0.87,
    )
    return vector_store_search_results_page(
        req,
        [chunk],
        {
            "doc_route_citation": {
                "file_id": "file_route_citation",
                "filename": "route-citation.md",
                "title": "Route Citation Proof",
                "attributes": {"topic": "citations"},
            }
        },
    )


async def _stream_body(response: StreamingResponse) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def _sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        event_type = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
        event = json.loads("".join(data_lines))
        assert event["type"] == event_type
        events.append(event)
    return events


def test_create_response_returns_openai_citations_without_results_by_default(monkeypatch):
    db = _Db()
    stored: dict[str, Any] = {}

    async def fake_search(vector_store_id, req, principal, db_session):
        assert vector_store_id == "vs_route"
        assert req.query == "Where is the citation?"
        assert req.rewrite_query is True
        assert req.include_content is True
        assert req.include_metadata is True
        return _search_page(req)

    def fake_store(db_session, principal, *, response_payload, input_items, request_payload):
        stored["response_payload"] = response_payload
        stored["input_items"] = input_items
        stored["request_payload"] = request_payload

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "_store_openai_response", fake_store)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Where is the citation?",
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        db,
    ))

    file_search_call = response["output"][0]
    content = response["output"][1]["content"][0]
    marker = "【1†source】"
    marker_index = content["text"].index(marker)

    assert file_search_call["type"] == "file_search_call"
    assert file_search_call["queries"] == ["Where is the citation"]
    assert file_search_call["results"] is None
    assert file_search_call["search_results"] is None
    assert content["type"] == "output_text"
    assert content["text"][marker_index:marker_index + len(marker)] == marker
    assert content["annotations"] == [{
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }]
    assert set(content["annotations"][0]) == {"type", "index", "file_id", "filename"}
    assert response["citations"][0]["marker"] == marker
    assert response["citations"][0]["annotation"] == content["annotations"][0]
    assert response["citations"][0]["chunk_id"] == "chk_route_citation"
    assert response["citations"][0]["page_start"] == 4
    assert stored["response_payload"]["output"][0]["results"][0]["file_id"] == "file_route_citation"
    assert stored["response_payload"]["output"][0]["search_results"][0]["file_id"] == "file_route_citation"
    assert stored["request_payload"]["input"] == "Where is the citation?"
    assert db.committed is True


def test_create_response_uses_previous_response_context_for_file_search(monkeypatch):
    previous_input_items = [{
        "id": "msg_prev",
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "What did the first answer cover?"}],
    }]
    previous_answer = "The first answer covered RunPod Marker warmup retries. 【1†source】"
    previous_annotation = {
        "type": "file_citation",
        "index": previous_answer.index("【1†source】"),
        "file_id": "file_prev",
        "filename": "previous.md",
    }
    previous_response = {
        "id": "resp_prev",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [{
            "type": "message",
            "id": "msg_prev_answer",
            "status": "completed",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": previous_answer,
                "annotations": [previous_annotation],
            }],
        }],
        "citations": [{"annotation": previous_annotation, "marker": "【1†source】"}],
    }
    db = _Db([{
        "id": "resp_prev",
        "response": previous_response,
        "input_items": previous_input_items,
        "deleted_at": None,
    }])
    captured_requests: list[OpenAIVectorStoreSearchRequest] = []
    stored: dict[str, Any] = {}

    async def fake_search(vector_store_id, req, principal, db_session):
        assert vector_store_id == "vs_route"
        captured_requests.append(req)
        return _search_page(req)

    def fake_store(db_session, principal, *, response_payload, input_items, request_payload):
        stored["response_payload"] = response_payload
        stored["input_items"] = input_items
        stored["request_payload"] = request_payload

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "_store_openai_response", fake_store)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "previous_response_id": "resp_prev",
            "input": "How does that affect retries?",
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        db,
    ))

    query = captured_requests[0].query
    assert query.startswith("How does that affect retries?\n\n")
    assert "What did the first answer cover?" in query
    assert "RunPod Marker warmup retries" in query
    assert "【1†source】" not in query
    assert response["previous_response_id"] == "resp_prev"
    assert stored["response_payload"]["previous_response_id"] == "resp_prev"
    assert [item["id"] for item in stored["input_items"]] == ["msg_prev", stored["input_items"][1]["id"]]
    assert stored["input_items"][0] == previous_input_items[0]
    assert stored["input_items"][1]["content"] == [{"type": "input_text", "text": "How does that affect retries?"}]
    assert stored["request_payload"]["previous_response_id"] == "resp_prev"
    assert db.committed is True


def test_create_response_rejects_previous_response_with_conversation(monkeypatch):
    search_called = False

    async def fake_search(*args, **kwargs):
        nonlocal search_called
        search_called = True
        return {}

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.create_response(
            {
                "model": "gpt-5.4-mini",
                "previous_response_id": "resp_prev",
                "conversation": "conv_123",
                "input": "How does that affect retries?",
                "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
            },
            _principal(),
            _Db(),
        ))

    assert exc.value.status_code == 422
    assert "previous_response_id cannot be used with conversation" in exc.value.detail
    assert search_called is False


def test_create_response_missing_previous_response_fails_before_search(monkeypatch):
    search_called = False

    async def fake_search(*args, **kwargs):
        nonlocal search_called
        search_called = True
        return {}

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.create_response(
            {
                "model": "gpt-5.4-mini",
                "previous_response_id": "resp_missing",
                "input": "How does that affect retries?",
                "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
            },
            _principal(),
            _Db(),
        ))

    assert exc.value.status_code == 404
    assert "Response not found: resp_missing" in exc.value.detail
    assert search_called is False


def test_create_response_returns_cached_idempotency_response_without_search(monkeypatch):
    cached = {
        "id": "resp_cached",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [],
        "citations": [],
    }

    async def fail_search(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip retrieval")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fail_search)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Where is the citation?",
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        _Db(),
        idempotency_key="idem_response",
    ))

    assert response == cached


def test_create_response_streams_cached_idempotency_response(monkeypatch):
    cached = {
        "id": "resp_cached",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [
            {
                "type": "message",
                "id": "msg_cached",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Cached answer", "annotations": []}],
            }
        ],
        "citations": [],
    }

    async def fail_search(*args, **kwargs):
        raise AssertionError("cached idempotency stream should skip retrieval")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fail_search)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Where is the citation?",
            "stream": True,
            "stream_options": {"include_obfuscation": False},
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        _Db(),
        idempotency_key="idem_response_stream",
    ))

    assert isinstance(response, StreamingResponse)
    events = _sse_events(asyncio.run(_stream_body(response)))
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["id"] == "resp_cached"
    assert events[-1]["response"]["output"][0]["content"][0]["text"] == "Cached answer"
    assert all("obfuscation" not in event for event in events)


def test_count_response_input_tokens_returns_openai_shape_without_retrieval(monkeypatch):
    async def fail_search(*args, **kwargs):
        raise AssertionError("input token counting should not execute retrieval")

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fail_search)

    payload = {
        "model": "gpt-5.4-mini",
        "input": [{
            "role": "user",
            "content": [{"type": "input_text", "text": "Where is the citation?"}],
        }],
        "instructions": "Use file_search results only.",
        "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"], "max_num_results": 10}],
    }
    base = api_main.count_response_input_tokens(
        {"input": payload["input"], "instructions": payload["instructions"]},
        _principal(),
    )

    response = api_main.count_response_input_tokens(payload, _principal())

    assert response["object"] == "response.input_tokens"
    assert response["input_tokens"] > base["input_tokens"] > 0


def test_count_response_input_tokens_requires_retrieval_read_scope():
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user",
        api_key_id="ak_test",
        scopes=[],
    )

    with pytest.raises(HTTPException) as exc:
        api_main.count_response_input_tokens({"input": "Where is the citation?"}, principal)

    assert exc.value.status_code == 403


def test_compact_response_returns_openai_compaction_without_retrieval(monkeypatch):
    async def fail_search(*args, **kwargs):
        raise AssertionError("compact should not execute retrieval")

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fail_search)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)
    monkeypatch.setattr(api_main, "new_id", lambda prefix: {
        "resp": "resp_compact_route",
        "cmp": "cmp_compact_route",
        "msg": "msg_compact_route",
    }[prefix])

    response = api_main.compact_response(
        {
            "model": "gpt-5.4",
            "input": [
                {"role": "user", "content": "Summarize this project."},
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Detailed answer to compact."}],
                },
            ],
        },
        _principal(),
    )

    assert response["id"] == "resp_compact_route"
    assert response["object"] == "response.compaction"
    assert response["created_at"] == 1710000000
    assert response["output"][0]["role"] == "user"
    assert response["output"][0]["content"] == [{"type": "input_text", "text": "Summarize this project."}]
    assert response["output"][1]["id"] == "cmp_compact_route"
    assert response["output"][1]["type"] == "compaction"
    assert response["output"][1]["encrypted_content"].startswith("svs_compaction_v1_")
    assert "Detailed answer" not in response["output"][1]["encrypted_content"]
    assert response["usage"]["total_tokens"] > response["usage"]["input_tokens"] > 0


def test_compact_response_requires_retrieval_read_scope():
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user",
        api_key_id="ak_test",
        scopes=[],
    )

    with pytest.raises(HTTPException) as exc:
        api_main.compact_response({"model": "gpt-5.4"}, principal)

    assert exc.value.status_code == 403


def test_compact_response_rejects_invalid_payload():
    with pytest.raises(HTTPException) as exc:
        api_main.compact_response({"input": "Missing model"}, _principal())

    assert exc.value.status_code == 422
    assert "model must be a non-empty string" in exc.value.detail


def test_create_response_streams_openai_sse_citations(monkeypatch):
    db = _Db()
    stored: dict[str, Any] = {}

    async def fake_search(vector_store_id, req, principal, db_session):
        assert vector_store_id == "vs_route"
        return _search_page(req)

    def fake_store(db_session, principal, *, response_payload, input_items, request_payload):
        stored["response_payload"] = response_payload
        stored["request_payload"] = request_payload

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "_store_openai_response", fake_store)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Where is the citation?",
            "stream": True,
            "include": ["file_search_call.results"],
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        db,
    ))

    assert isinstance(response, StreamingResponse)
    body = asyncio.run(_stream_body(response))
    events = _sse_events(body)
    event_types = [event["type"] for event in events]

    assert event_types[:2] == ["response.created", "response.in_progress"]
    assert "response.file_search_call.searching" in event_types
    assert "response.output_text.delta" in event_types
    assert "response.output_text.annotation.added" in event_types
    assert "response.output_text.done" in event_types
    assert event_types[-1] == "response.completed"
    assert event_types.index("response.output_text.annotation.added") < event_types.index("response.output_text.done")
    assert event_types.index("response.output_text.done") < event_types.index("response.content_part.done")

    file_search_added = next(
        event
        for event in events
        if event["type"] == "response.output_item.added"
        and event["item"].get("type") == "file_search_call"
    )
    assert file_search_added["item"]["type"] == "file_search_call"
    assert file_search_added["item"]["id"].startswith("fs_")
    assert file_search_added["item"]["status"] == "in_progress"
    assert file_search_added["item"]["queries"] == []
    assert file_search_added["item"]["results"] is None
    assert file_search_added["item"]["search_results"] is None
    file_search_done = next(
        event
        for event in events
        if event["type"] == "response.output_item.done"
        and event["item"].get("type") == "file_search_call"
    )
    assert file_search_done["item"]["id"] == file_search_added["item"]["id"]
    assert file_search_done["item"]["queries"] == ["Where is the citation"]
    assert file_search_done["item"]["results"][0]["file_id"] == "file_route_citation"

    delta_event = next(event for event in events if event["type"] == "response.output_text.delta")
    assert isinstance(delta_event["obfuscation"], str)
    assert delta_event["obfuscation"]
    annotation_event = next(event for event in events if event["type"] == "response.output_text.annotation.added")
    text_done = next(event for event in events if event["type"] == "response.output_text.done")
    completed = events[-1]["response"]
    content = completed["output"][1]["content"][0]
    marker_index = content["text"].index("【1†source】")

    assert annotation_event["annotation"] == {
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }
    assert text_done["text"] == content["text"]
    assert "annotations" not in text_done
    assert content["annotations"] == [annotation_event["annotation"]]
    assert completed["citations"][0]["annotation"] == annotation_event["annotation"]
    assert completed["output"][0]["results"][0]["file_id"] == "file_route_citation"
    assert stored["request_payload"]["stream"] is True
    assert db.committed is True


def test_create_response_stream_options_can_disable_obfuscation(monkeypatch):
    async def fake_search(vector_store_id, req, principal, db_session):
        return _search_page(req)

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "_store_openai_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Where is the citation?",
            "stream": True,
            "stream_options": {"include_obfuscation": False},
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        _Db(),
    ))

    events = _sse_events(asyncio.run(_stream_body(response)))
    delta_event = next(event for event in events if event["type"] == "response.output_text.delta")
    annotation_event = next(event for event in events if event["type"] == "response.output_text.annotation.added")

    assert "obfuscation" not in delta_event
    assert "obfuscation" not in annotation_event
    assert annotation_event["annotation"]["type"] == "file_citation"


def test_create_response_rejects_invalid_stream_obfuscation_option():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.create_response(
            {
                "model": "gpt-5.4-mini",
                "input": "Where is the citation?",
                "stream": True,
                "stream_options": {"include_obfuscation": "false"},
                "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
            },
            _principal(),
            _Db(),
        ))

    assert exc.value.status_code == 422
    assert "include_obfuscation must be a boolean" in exc.value.detail


def test_create_response_rejects_non_boolean_stream_value():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.create_response(
            {
                "model": "gpt-5.4-mini",
                "input": "Where is the citation?",
                "stream": "true",
                "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
            },
            _principal(),
            _Db(),
        ))

    assert exc.value.status_code == 422
    assert "stream must be a boolean" in exc.value.detail


def test_create_response_reports_planned_file_search_queries(monkeypatch):
    db = _Db()
    stored: dict[str, Any] = {}
    captured_requests: list[OpenAIVectorStoreSearchRequest] = []

    async def fake_search(vector_store_id, req, principal, db_session):
        assert vector_store_id == "vs_route"
        captured_requests.append(req)
        return _search_page(req)

    def fake_store(db_session, principal, *, response_payload, input_items, request_payload):
        stored["response_payload"] = response_payload

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "_store_openai_response", fake_store)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Can you find RunPod Marker warmup and Voyage embeddings?",
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        db,
    ))

    planned_queries = ["RunPod Marker warmup", "Voyage embeddings"]
    file_search_call = response["output"][0]

    assert [req.query for req in captured_requests] == ["Can you find RunPod Marker warmup and Voyage embeddings?"]
    assert all(req.rewrite_query is True for req in captured_requests)
    assert file_search_call["queries"] == planned_queries
    assert file_search_call["results"] is None
    assert file_search_call["search_results"] is None
    assert stored["response_payload"]["output"][0]["queries"] == planned_queries
    assert stored["response_payload"]["output"][0]["results"][0]["file_id"] == "file_route_citation"
    assert stored["response_payload"]["output"][0]["search_results"][0]["file_id"] == "file_route_citation"


def test_create_response_include_returns_file_search_results_and_annotations(monkeypatch):
    async def fake_search(vector_store_id, req, principal, db_session):
        return _search_page(req)

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "_store_openai_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Where is the citation?",
            "include": ["file_search_call.results"],
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        _Db(),
    ))

    file_search_call = response["output"][0]
    content = response["output"][1]["content"][0]
    marker_index = content["text"].index("【1†source】")

    assert file_search_call["results"][0]["file_id"] == "file_route_citation"
    assert file_search_call["search_results"][0]["file_id"] == "file_route_citation"
    assert file_search_call["search_results"] == file_search_call["results"]
    assert set(file_search_call["results"][0]) == {"file_id", "filename", "score", "text", "attributes"}
    assert "citation" not in file_search_call["results"][0]
    assert response["citations"][0]["chunk_id"] == "chk_route_citation"
    assert response["citations"][0]["annotation"] == content["annotations"][0]
    assert content["annotations"] == [{
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }]


def test_create_response_accepts_file_search_tool_choice_without_changing_citations(monkeypatch):
    async def fake_search(vector_store_id, req, principal, db_session):
        return _search_page(req)

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "_store_openai_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Where is the citation?",
            "tool_choice": {"type": "file_search"},
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        _Db(),
    ))

    content = response["output"][1]["content"][0]
    marker_index = content["text"].index("【1†source】")

    assert response["tool_choice"] == {"type": "file_search"}
    assert content["annotations"] == [{
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }]


def test_create_response_accepts_allowed_tools_file_search_tool_choice(monkeypatch):
    async def fake_search(vector_store_id, req, principal, db_session):
        return _search_page(req)

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "_store_openai_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    tool_choice = {
        "type": "allowed_tools",
        "mode": "required",
        "tools": [{"type": "file_search"}],
    }

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Where is the citation?",
            "tool_choice": tool_choice,
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
        },
        _principal(),
        _Db(),
    ))

    assert response["tool_choice"] == tool_choice
    assert response["output"][1]["content"][0]["annotations"][0]["type"] == "file_citation"


@pytest.mark.parametrize(
    "tool_choice, detail",
    [
        ("none", "tool_choice 'none'"),
        ({"type": "web_search_preview"}, "only file_search choices"),
        ({"type": "allowed_tools", "mode": "required", "tools": [{"type": "web_search_preview"}]}, "must include file_search"),
    ],
)
def test_create_response_rejects_tool_choices_that_cannot_emit_file_citations(monkeypatch, tool_choice, detail):
    search_called = False

    async def fake_search(vector_store_id, req, principal, db_session):
        nonlocal search_called
        search_called = True
        return _search_page(req)

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.create_response(
            {
                "model": "gpt-5.4-mini",
                "input": "Where is the citation?",
                "tool_choice": tool_choice,
                "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
            },
            _principal(),
            _Db(),
        ))

    assert exc.value.status_code == 422
    assert detail in exc.value.detail
    assert search_called is False


def test_create_response_rejects_generated_citation_integrity_failure_before_store(monkeypatch):
    db = _Db()
    store_called = False
    original_builder = api_main.openai_responses_file_search_response

    async def fake_search(vector_store_id, req, principal, db_session):
        return _search_page(req)

    def broken_response(*args, **kwargs):
        response = original_builder(*args, **kwargs)
        response["output"][1]["content"][0]["annotations"][0]["index"] = 0
        return response

    def fake_store(*args, **kwargs):
        nonlocal store_called
        store_called = True

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "openai_responses_file_search_response", broken_response)
    monkeypatch.setattr(api_main, "_store_openai_response", fake_store)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.create_response(
            {
                "model": "gpt-5.4-mini",
                "input": "Where is the citation?",
                "tools": [{"type": "file_search", "vector_store_ids": ["vs_route"]}],
            },
            _principal(),
            db,
        ))

    assert exc.value.status_code == 500
    assert "citation integrity check failed" in exc.value.detail
    assert store_called is False
    assert db.committed is False


def test_create_response_dedupes_duplicate_results_across_vector_stores(monkeypatch):
    calls: list[str] = []

    async def fake_search(vector_store_id, req, principal, db_session):
        calls.append(vector_store_id)
        return _search_page(req)

    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fake_search)
    monkeypatch.setattr(api_main, "_store_openai_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)

    response = asyncio.run(api_main.create_response(
        {
            "model": "gpt-5.4-mini",
            "input": "Where is the citation?",
            "include": ["file_search_call.results"],
            "tools": [{"type": "file_search", "vector_store_ids": ["vs_route_a", "vs_route_b"]}],
        },
        _principal(),
        _Db(),
    ))

    file_search_call = response["output"][0]
    content = response["output"][1]["content"][0]
    marker_index = content["text"].index("【1†source】")

    assert calls == ["vs_route_a", "vs_route_b"]
    assert len(file_search_call["results"]) == 1
    assert file_search_call["search_results"] == file_search_call["results"]
    assert len(content["annotations"]) == 1
    assert content["annotations"][0]["index"] == marker_index
    assert response["citations"][0]["chunk_id"] == "chk_route_citation"
    assert response["citations"][0]["annotation"] == content["annotations"][0]
    assert response["citations"][0]["vector_store_ids"] == ["vs_route_a", "vs_route_b"]


def test_get_response_streams_stored_payload_with_citations():
    annotation = {
        "type": "file_citation",
        "index": 22,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }
    stored_response = {
        "id": "resp_route",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [
            {
                "type": "message",
                "id": "msg_route",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": "Stored citation proof 【1†source】",
                    "annotations": [annotation],
                }],
            }
        ],
        "citations": [{"annotation": annotation, "marker": "【1†source】"}],
    }
    db = _Db([{"id": "resp_route", "response": stored_response, "input_items": [], "deleted_at": None}])

    response = api_main.get_response("resp_route", include=None, stream=True, principal=_principal(), db=db)

    assert isinstance(response, StreamingResponse)
    events = _sse_events(asyncio.run(_stream_body(response)))
    delta_event = next(event for event in events if event["type"] == "response.output_text.delta")
    assert isinstance(delta_event["obfuscation"], str)
    assert delta_event["obfuscation"]
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["output"][0]["content"][0]["annotations"] == [annotation]
    assert any(event["type"] == "response.output_text.annotation.added" for event in events)


@pytest.mark.parametrize("stream", [False, True])
def test_get_response_rejects_stored_payload_with_bad_citation_index(stream):
    annotation = {
        "type": "file_citation",
        "index": 0,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }
    stored_response = {
        "id": "resp_route",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [
            {
                "type": "message",
                "id": "msg_route",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": "Stored citation proof 【1†source】",
                    "annotations": [annotation],
                }],
            }
        ],
        "citations": [{"annotation": annotation, "marker": "【1†source】"}],
    }
    db = _Db([{"id": "resp_route", "response": stored_response, "input_items": [], "deleted_at": None}])

    with pytest.raises(HTTPException) as exc:
        api_main.get_response("resp_route", include=None, stream=stream, principal=_principal(), db=db)

    assert exc.value.status_code == 500
    assert "Stored Responses citation integrity check failed" in exc.value.detail
    assert "annotation index does not point at a visible source marker" in exc.value.detail


def test_get_response_rejects_stored_payload_missing_native_citation_proof():
    annotation = {
        "type": "file_citation",
        "index": 22,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }
    stored_response = {
        "id": "resp_route",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [
            {
                "type": "message",
                "id": "msg_route",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": "Stored citation proof 【1†source】",
                    "annotations": [annotation],
                }],
            }
        ],
    }
    db = _Db([{"id": "resp_route", "response": stored_response, "input_items": [], "deleted_at": None}])

    with pytest.raises(HTTPException) as exc:
        api_main.get_response("resp_route", include=None, stream=False, principal=_principal(), db=db)

    assert exc.value.status_code == 500
    assert "Stored Responses citation integrity check failed" in exc.value.detail
    assert "output annotations require native citation proof" in exc.value.detail


def test_get_response_stream_include_obfuscation_false_omits_delta_obfuscation():
    annotation = {
        "type": "file_citation",
        "index": 22,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }
    stored_response = {
        "id": "resp_route",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [
            {
                "type": "message",
                "id": "msg_route",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": "Stored citation proof 【1†source】",
                    "annotations": [annotation],
                }],
            }
        ],
        "citations": [{"annotation": annotation, "marker": "【1†source】"}],
    }
    db = _Db([{"id": "resp_route", "response": stored_response, "input_items": [], "deleted_at": None}])

    response = api_main.get_response(
        "resp_route",
        include=None,
        stream=True,
        include_obfuscation=False,
        principal=_principal(),
        db=db,
    )

    events = _sse_events(asyncio.run(_stream_body(response)))
    delta_event = next(event for event in events if event["type"] == "response.output_text.delta")
    annotation_event = next(event for event in events if event["type"] == "response.output_text.annotation.added")

    assert "obfuscation" not in delta_event
    assert "obfuscation" not in annotation_event
    assert annotation_event["annotation"] == annotation


def test_get_response_stream_starting_after_resumes_citation_events():
    annotation = {
        "type": "file_citation",
        "index": 22,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }
    stored_response = {
        "id": "resp_route",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "completed_at": 1710000000,
        "output": [
            {
                "type": "file_search_call",
                "id": "fs_route",
                "status": "completed",
                "queries": ["stored citation"],
                "results": None,
            },
            {
                "type": "message",
                "id": "msg_route",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": "Stored citation proof 【1†source】",
                    "annotations": [annotation],
                }],
            },
        ],
        "citations": [{"annotation": annotation, "marker": "【1†source】"}],
    }

    initial_db = _Db([{"id": "resp_route", "response": stored_response, "input_items": [], "deleted_at": None}])
    initial_response = api_main.get_response(
        "resp_route",
        include=None,
        stream=True,
        starting_after=None,
        principal=_principal(),
        db=initial_db,
    )
    initial_events = _sse_events(asyncio.run(_stream_body(initial_response)))
    cursor = next(event["sequence_number"] for event in initial_events if event["type"] == "response.output_text.delta")

    resumed_db = _Db([{"id": "resp_route", "response": stored_response, "input_items": [], "deleted_at": None}])
    resumed_response = api_main.get_response(
        "resp_route",
        include=None,
        stream=True,
        starting_after=cursor,
        principal=_principal(),
        db=resumed_db,
    )

    assert isinstance(resumed_response, StreamingResponse)
    events = _sse_events(asyncio.run(_stream_body(resumed_response)))
    assert events[0]["type"] == "response.output_text.annotation.added"
    assert events[0]["annotation"] == annotation
    assert all(event["sequence_number"] > cursor for event in events)
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["output"][1]["content"][0]["annotations"] == [annotation]


def test_cancel_response_marks_background_payload_cancelled_and_preserves_citations():
    annotation = {
        "type": "file_citation",
        "index": 22,
        "file_id": "file_route_citation",
        "filename": "route-citation.md",
    }
    stored_response = {
        "id": "resp_route",
        "object": "response",
        "created_at": 1710000000,
        "status": "in_progress",
        "background": True,
        "output": [
            {
                "type": "message",
                "id": "msg_route",
                "status": "in_progress",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": "Stored citation proof 【1†source】",
                    "annotations": [annotation],
                }],
            }
        ],
        "citations": [{"annotation": annotation, "marker": "【1†source】"}],
    }
    db = _Db([{"id": "resp_route", "response": stored_response, "input_items": [], "deleted_at": None}])

    response = api_main.cancel_response("resp_route", _principal(), db)

    assert response["status"] == "cancelled"
    assert response["output"][0]["status"] == "cancelled"
    assert response["output"][0]["content"][0]["annotations"] == [annotation]
    assert response["citations"][0]["annotation"] == annotation
    assert db.committed is True
    update_sql, update_params = db.calls[1]
    assert "UPDATE openai_responses" in update_sql
    assert "status='cancelled'" in update_sql
    assert json.loads(update_params["response"])["status"] == "cancelled"


def test_cancel_response_requires_background_response():
    stored_response = {
        "id": "resp_route",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "background": False,
        "output": [],
    }
    db = _Db([{"id": "resp_route", "response": stored_response, "input_items": [], "deleted_at": None}])

    with pytest.raises(HTTPException) as exc:
        api_main.cancel_response("resp_route", _principal(), db)

    assert exc.value.status_code == 400
    assert "Only background Responses can be cancelled" in exc.value.detail
    assert db.committed is False
    assert len(db.calls) == 1


def test_cancel_response_deleted_row_returns_404():
    db = _Db([{"id": "resp_route", "response": {"background": True}, "input_items": [], "deleted_at": "now"}])

    with pytest.raises(HTTPException) as exc:
        api_main.cancel_response("resp_route", _principal(), db)

    assert exc.value.status_code == 404
    assert "Response not found: resp_route" in exc.value.detail
    assert db.committed is False


def test_cancel_response_returns_cached_idempotency_response(monkeypatch):
    cached = {"id": "resp_cached", "object": "response", "status": "cancelled", "background": True}

    def fail_get_row(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip response cancel lookup")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "_get_openai_response_row", fail_get_row)

    response = api_main.cancel_response(
        "resp_cached",
        _principal(),
        _Db(),
        idempotency_key="idem_response_cancel",
    )

    assert response == cached


def test_delete_response_returns_cached_idempotency_response(monkeypatch):
    cached = {"id": "resp_cached", "object": "response", "deleted": True}

    def fail_get_row(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip response delete lookup")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "_get_openai_response_row", fail_get_row)

    response = api_main.delete_response(
        "resp_cached",
        _principal(),
        _Db(),
        idempotency_key="idem_response_delete",
    )

    assert response == cached


def test_openai_vector_store_search_page_runs_planned_subqueries(monkeypatch):
    calls = []

    async def fake_retrieval_search(db_session, principal, search_req):
        calls.append(search_req)
        ordinal = len(calls)
        return SearchResponse(
            query=search_req.query,
            results=[
                ChunkRecord(
                    id=f"chk_planned_{ordinal}",
                    document_id=f"doc_planned_{ordinal}",
                    ordinal=0,
                    text=f"Evidence for {search_req.query}",
                    score=0.9 - (ordinal * 0.1),
                )
            ],
        )

    def fake_file_lookup(db_session, principal, vector_store_id, document_ids):
        return {
            "doc_planned_1": {
                "file_id": "file_planned_1",
                "filename": "runpod-marker.md",
            },
            "doc_planned_2": {
                "file_id": "file_planned_2",
                "filename": "voyage-embeddings.md",
            },
        }

    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "_vector_store_file_lookup", fake_file_lookup)
    monkeypatch.setattr(api_main.retrieval, "search", fake_retrieval_search)

    page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_route",
        OpenAIVectorStoreSearchRequest(
            query="Can you find RunPod Marker warmup and Voyage embeddings?",
            rewrite_query=True,
            max_num_results=10,
        ),
        _principal(),
        _Db(),
    ))

    assert [call.query for call in calls] == ["RunPod Marker warmup", "Voyage embeddings"]
    assert all(call.vector_store_id == "vs_route" for call in calls)
    assert all(call.filters["vector_store_id"] == "vs_route" for call in calls)
    assert all(call.search_metadata["openai_compat"]["subqueries"] == ["RunPod Marker warmup", "Voyage embeddings"] for call in calls)
    assert page["search_query"] == "RunPod Marker warmup and Voyage embeddings"
    assert [item["file_id"] for item in page["data"]] == ["file_planned_1", "file_planned_2"]
    assert [item["citation"]["chunk_id"] for item in page["data"]] == ["chk_planned_1", "chk_planned_2"]


def test_openai_vector_store_search_page_applies_instance_query_planner_filters(monkeypatch):
    calls = []

    async def fake_retrieval_search(db_session, principal, search_req):
        calls.append(search_req)
        return SearchResponse(
            query=search_req.query,
            results=[
                ChunkRecord(
                    id="chk_ks_docket",
                    document_id="doc_ks_docket",
                    ordinal=0,
                    text="Evidence for State v. Perez",
                    score=0.9,
                )
            ],
        )

    def fake_file_lookup(db_session, principal, vector_store_id, document_ids):
        return {
            "doc_ks_docket": {
                "file_id": "file_ks_docket",
                "filename": "State v. Perez.pdf",
            },
        }

    monkeypatch.setenv("SVS_QUERY_PLANNER_PROFILE_ID", "ks_civics_legal_v1")
    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "_vector_store_file_lookup", fake_file_lookup)
    monkeypatch.setattr(api_main.retrieval, "search", fake_retrieval_search)

    page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_route",
        OpenAIVectorStoreSearchRequest(
            query="Find State v. Perez docket 80739",
            max_num_results=10,
        ),
        _principal(),
        _Db(),
    ))

    assert [call.query for call in calls] == ["State v. Perez"]
    assert calls[0].filters == {
        "vector_store_id": "vs_route",
        "file_attribute_filters": {"docket_number": "80739"},
    }
    assert calls[0].search_metadata["openai_compat"]["query_planner_profile_id"] == "ks_civics_legal_v1"
    assert calls[0].search_metadata["openai_compat"]["planned_filters"] == [
        {"file_attribute_filters": {"docket_number": "80739"}}
    ]
    assert page["search_query"] == "State v. Perez"
    assert page["data"][0]["file_id"] == "file_ks_docket"


def test_openai_vector_store_search_page_skips_court_planner_for_topeka_code(monkeypatch):
    calls = []

    async def fake_retrieval_search(db_session, principal, search_req):
        calls.append(search_req)
        return SearchResponse(
            query=search_req.query,
            results=[
                ChunkRecord(
                    id="chk_topeka_code",
                    document_id="doc_topeka_code",
                    ordinal=0,
                    text="Ordinance 20625 amended Topeka property maintenance vegetation rules.",
                    score=0.9,
                )
            ],
        )

    def fake_file_lookup(db_session, principal, vector_store_id, document_ids):
        return {
            "doc_topeka_code": {
                "file_id": "file_topeka_code",
                "filename": "TMC-8.60.150.md",
            },
        }

    monkeypatch.setenv("SVS_QUERY_PLANNER_PROFILE_ID", "ks_civics_legal_v1")
    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "_vector_store_file_lookup", fake_file_lookup)
    monkeypatch.setattr(api_main.retrieval, "search", fake_retrieval_search)

    page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_topeka",
        OpenAIVectorStoreSearchRequest(
            query="Which Topeka property maintenance vegetation section was amended by Ordinance 20625 passed December 16 2025?",
            max_num_results=10,
        ),
        _principal(),
        _Db([{"attributes": {"corpus": "topeka_municipal_code", "source_collection": "topeka-municipal-code"}}]),
    ))

    assert [call.query for call in calls] == [
        "Which Topeka property maintenance vegetation section was amended by Ordinance 20625 passed December 16 2025"
    ]
    assert calls[0].filters == {"vector_store_id": "vs_topeka"}
    assert calls[0].search_metadata["openai_compat"]["query_planner_profile_id"] is None
    assert calls[0].search_metadata["openai_compat"]["planned_filters"] == [{}]
    assert page["data"][0]["file_id"] == "file_topeka_code"


def test_openai_vector_store_search_page_diversifies_legal_exact_duplicate_documents(monkeypatch):
    calls = []

    async def fake_retrieval_search(db_session, principal, search_req):
        calls.append(search_req)
        return SearchResponse(
            query=search_req.query,
            results=[
                ChunkRecord(id="chk_harris_a_1", document_id="doc_harris_a", ordinal=0, text="Harris A 1", score=0.99),
                ChunkRecord(id="chk_harris_a_2", document_id="doc_harris_a", ordinal=1, text="Harris A 2", score=0.98),
                ChunkRecord(id="chk_harris_a_3", document_id="doc_harris_a", ordinal=2, text="Harris A 3", score=0.97),
                ChunkRecord(id="chk_harris_b_1", document_id="doc_harris_b", ordinal=0, text="Harris B 1", score=0.50),
                ChunkRecord(id="chk_harris_a_4", document_id="doc_harris_a", ordinal=3, text="Harris A 4", score=0.49),
            ],
        )

    def fake_file_lookup(db_session, principal, vector_store_id, document_ids):
        return {
            "doc_harris_a": {
                "file_id": "file_harris_a",
                "filename": "State v. Harris A.pdf",
                "attributes": {"docket_number": "116515"},
            },
            "doc_harris_b": {
                "file_id": "file_harris_b",
                "filename": "State v. Harris B.pdf",
                "attributes": {"docket_number": "116515"},
            },
        }

    monkeypatch.setenv("SVS_QUERY_PLANNER_PROFILE_ID", "ks_civics_legal_v1")
    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "_vector_store_file_lookup", fake_file_lookup)
    monkeypatch.setattr(api_main.retrieval, "search", fake_retrieval_search)

    page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_route",
        OpenAIVectorStoreSearchRequest(
            query="State v. Harris docket 116515",
            max_num_results=3,
        ),
        _principal(),
        _Db(),
    ))

    assert calls[0].top_k == 51
    assert calls[0].search_metadata["openai_compat"]["legal_exact_document_diversity"] is True
    assert calls[0].search_metadata["openai_compat"]["search_fetch_limit"] == 51
    assert [item["file_id"] for item in page["data"]] == ["file_harris_a", "file_harris_b", "file_harris_a"]
    assert [item["citation"]["chunk_id"] for item in page["data"]] == ["chk_harris_a_1", "chk_harris_b_1", "chk_harris_a_2"]


def test_openai_vector_store_search_page_keeps_graphrag_disabled(monkeypatch):
    calls = []

    async def fake_retrieval_search(db_session, principal, search_req):
        calls.append(search_req)
        return SearchResponse(
            query=search_req.query,
            results=[
                ChunkRecord(id="chk_direct", document_id="doc_direct", ordinal=0, text="Direct vector hit", score=0.9),
            ],
        )

    def fail_graph_relation_lookup(*args, **kwargs):
        raise AssertionError("disabled GraphRAG must not query graph tables")

    def fake_file_lookup(db_session, principal, vector_store_id, document_ids):
        return {"doc_direct": {"file_id": "file_direct", "filename": "direct.pdf"}}

    monkeypatch.setenv("SVS_QUERY_PLANNER_PROFILE_ID", "ks_civics_legal_v1")
    monkeypatch.delenv("SVS_KSCOURTS_GRAPHRAG_ENABLED", raising=False)
    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "_vector_store_file_lookup", fake_file_lookup)
    monkeypatch.setattr(api_main, "_kscourts_graphrag_relation_rows", fail_graph_relation_lookup)
    monkeypatch.setattr(api_main.retrieval, "search", fake_retrieval_search)

    page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_route",
        OpenAIVectorStoreSearchRequest(
            query="related cases for State v. Harris docket 116515",
            max_num_results=5,
        ),
        _principal(),
        _Db(),
    ))

    assert len(calls) == 1
    assert "graph_expansion" not in page
    assert [item["file_id"] for item in page["data"]] == ["file_direct"]


def test_vector_store_search_lenses_returns_court_graph_contract(monkeypatch):
    monkeypatch.setenv("SVS_QUERY_PLANNER_PROFILE_ID", "ks_civics_legal_v1")
    monkeypatch.setenv("SVS_KSCOURTS_GRAPHRAG_ENABLED", "true")
    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_main,
        "_vector_store_attributes_for_search",
        lambda *args, **kwargs: {"source_collection": "kscourts-decisions"},
    )
    monkeypatch.setattr(
        api_main,
        "_graph_coverage_for_vector_store",
        lambda *args, **kwargs: {
            "documents_indexed": 16484,
            "active_chunks": 116200,
            "node_count": 390,
            "edge_count": 404,
            "node_type_counts": {"opinion": 52, "case": 338},
            "edge_type_counts": {"cites_case": 404},
        },
    )

    payload = api_main.vector_store_search_lenses("vs_kscourts", _principal(), object())

    lenses = {lens["id"]: lens for lens in payload["data"]}
    assert payload["default_lens"] == "semantic"
    assert lenses["semantic"]["status"] == "available"
    assert lenses["court_citator"]["status"] == "available"
    assert lenses["court_citator"]["relation_types"] == [
        "cited_by",
        "cited_authority",
        "same_docket",
        "related_party",
    ]
    assert lenses["court_citator"]["coverage"]["documents_indexed"] == 16484
    assert lenses["court_citator"]["coverage"]["edge_type_counts"]["cites_case"] == 404
    assert any("not a proven full-corpus Kansas citator" in warning for warning in lenses["court_citator"]["warnings"])


def test_openai_vector_store_search_page_adds_opt_in_graphrag_expansion(monkeypatch):
    metadata = {
        "profile": "kscourts_postgres_graph_v1",
        "relation_type": "same_docket",
        "edge_id": "edge_same_docket",
        "source_document_id": "doc_direct",
        "target_document_id": "doc_related",
        "attributes": {"docket_number": "116515"},
        "provenance": {"extraction_method": "metadata", "confidence": 1.0},
    }

    async def fake_retrieval_search(db_session, principal, search_req):
        return SearchResponse(
            query=search_req.query,
            results=[
                ChunkRecord(id="chk_direct", document_id="doc_direct", ordinal=0, text="Direct vector hit", score=0.9),
                ChunkRecord(id="chk_other", document_id="doc_other", ordinal=0, text="Other vector hit", score=0.8),
            ],
        )

    def fake_relation_rows(db_session, principal, vector_store_id, seed_document_ids, *, limit):
        assert vector_store_id == "vs_route"
        assert seed_document_ids[:1] == ["doc_direct"]
        return [{
            "edge_id": "edge_same_docket",
            "relation_type": "same_docket",
            "seed_document_id": "doc_direct",
            "related_document_id": "doc_related",
            "attributes": {"docket_number": "116515"},
            "provenance": {"extraction_method": "metadata", "confidence": 1.0},
        }]

    def fake_hydrate(db_session, principal, vector_store_id, relation_rows, existing_document_ids, *, limit):
        assert existing_document_ids == {"doc_direct", "doc_other"}
        chunk = ChunkRecord(
            id="chk_related",
            document_id="doc_related",
            ordinal=0,
            text="Graph-expanded same-docket opinion",
            score=0.65,
            source="kscourts_graphrag_expansion",
            citation={"graph_expansion": metadata},
        )
        return [chunk], {"chk_related": metadata}

    def fake_file_lookup(db_session, principal, vector_store_id, document_ids):
        return {
            "doc_direct": {"file_id": "file_direct", "filename": "direct.pdf"},
            "doc_related": {"file_id": "file_related", "filename": "related.pdf"},
            "doc_other": {"file_id": "file_other", "filename": "other.pdf"},
        }

    monkeypatch.setenv("SVS_QUERY_PLANNER_PROFILE_ID", "ks_civics_legal_v1")
    monkeypatch.setenv("SVS_KSCOURTS_GRAPHRAG_ENABLED", "true")
    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_main,
        "_vector_store_attributes_for_search",
        lambda *args, **kwargs: {"source_collection": "kscourts-decisions"},
    )
    monkeypatch.setattr(
        api_main,
        "_graph_coverage_for_vector_store",
        lambda *args, **kwargs: {
            "documents_indexed": 16484,
            "active_chunks": 116200,
            "node_count": 390,
            "edge_count": 404,
            "node_type_counts": {"opinion": 52, "case": 338},
            "edge_type_counts": {"cites_case": 404},
        },
    )
    monkeypatch.setattr(api_main, "_vector_store_file_lookup", fake_file_lookup)
    monkeypatch.setattr(api_main, "_kscourts_graphrag_relation_rows", fake_relation_rows)
    monkeypatch.setattr(api_main, "_hydrate_kscourts_graphrag_chunks", fake_hydrate)
    monkeypatch.setattr(api_main.retrieval, "search", fake_retrieval_search)

    page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_route",
        OpenAIVectorStoreSearchRequest(
            query="related cases for State v. Harris docket 116515",
            max_num_results=5,
        ),
        _principal(),
        _Db(),
    ))

    assert [item["file_id"] for item in page["data"][:3]] == ["file_direct", "file_related", "file_other"]
    assert page["graph_expansion"]["enabled"] is True
    assert page["graph_expansion"]["lens"] == "court_citator"
    assert page["graph_expansion"]["applied"] is True
    assert page["graph_expansion"]["candidate_count"] == 1
    assert page["graph_expansion"]["inserted_chunk_count"] == 1
    assert page["graph_expansion"]["relation_types"] == ["same_docket"]
    assert page["graph_expansion"]["annotated_result_count"] == 1
    assert page["graph_expansion"]["coverage"]["documents_indexed"] == 16484
    assert page["graph_expansion"]["coverage"]["edge_type_counts"]["cites_case"] == 404
    assert page["graph_expansion"]["coverage"]["full_corpus_citator"] is False
    assert any(
        "not a proven full-corpus Kansas citator" in warning
        for warning in page["graph_expansion"]["warnings"]
    )
    assert page["search_lens"] == {
        "id": "court_citator",
        "status": "available",
        "source": "inferred",
        "inputs": {},
        "requires_graph": True,
    }
    graph_citation = page["data"][1]["citation"]["graph_expansion"]
    assert graph_citation["relation_type"] == "same_docket"
    assert graph_citation["edge_id"] == "edge_same_docket"
    assert graph_citation["source_document_id"] == "doc_direct"
    assert graph_citation["target_document_id"] == "doc_related"


def test_openai_vector_store_search_page_explicit_court_lens_forces_graphrag(monkeypatch):
    calls = []
    hydrated_relation_rows = []
    metadata = {
        "profile": "kscourts_postgres_graph_v1",
        "relation_type": "same_docket",
        "edge_id": "edge_same_docket",
        "source_document_id": "doc_direct",
        "target_document_id": "doc_related",
        "attributes": {"docket_number": "116515"},
        "provenance": {"extraction_method": "metadata", "confidence": 1.0},
    }

    async def fake_retrieval_search(db_session, principal, search_req):
        calls.append(search_req)
        return SearchResponse(
            query=search_req.query,
            results=[
                ChunkRecord(id="chk_direct", document_id="doc_direct", ordinal=0, text="Direct vector hit", score=0.9),
            ],
        )

    def fake_relation_rows(db_session, principal, vector_store_id, seed_document_ids, *, limit):
        return [
            {
                "edge_id": "edge_same_docket",
                "relation_type": "same_docket",
                "seed_document_id": "doc_direct",
                "related_document_id": "doc_related",
                "attributes": {"docket_number": "116515"},
                "provenance": {"extraction_method": "metadata", "confidence": 1.0},
            },
            {
                "edge_id": "edge_cited_by",
                "relation_type": "cited_by",
                "seed_document_id": "doc_direct",
                "related_document_id": "doc_citing",
                "attributes": {},
                "provenance": {},
            },
        ]

    def fake_hydrate(db_session, principal, vector_store_id, relation_rows, existing_document_ids, *, limit):
        hydrated_relation_rows.extend(relation_rows)
        chunk = ChunkRecord(
            id="chk_related",
            document_id="doc_related",
            ordinal=0,
            text="Graph-expanded same-docket opinion",
            score=0.65,
            source="kscourts_graphrag_expansion",
            citation={"graph_expansion": metadata},
        )
        return [chunk], {"chk_related": metadata}

    def fake_file_lookup(db_session, principal, vector_store_id, document_ids):
        return {
            "doc_direct": {"file_id": "file_direct", "filename": "direct.pdf"},
            "doc_related": {"file_id": "file_related", "filename": "related.pdf"},
        }

    monkeypatch.setenv("SVS_QUERY_PLANNER_PROFILE_ID", "ks_civics_legal_v1")
    monkeypatch.setenv("SVS_KSCOURTS_GRAPHRAG_ENABLED", "true")
    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_main,
        "_vector_store_attributes_for_search",
        lambda *args, **kwargs: {"source_collection": "kscourts-decisions"},
    )
    monkeypatch.setattr(
        api_main,
        "_graph_coverage_for_vector_store",
        lambda *args, **kwargs: {
            "documents_indexed": 16484,
            "active_chunks": 116200,
            "node_count": 390,
            "edge_count": 404,
            "node_type_counts": {"opinion": 52, "case": 338},
            "edge_type_counts": {"cites_case": 404},
        },
    )
    monkeypatch.setattr(api_main, "_vector_store_file_lookup", fake_file_lookup)
    monkeypatch.setattr(api_main, "_kscourts_graphrag_relation_rows", fake_relation_rows)
    monkeypatch.setattr(api_main, "_hydrate_kscourts_graphrag_chunks", fake_hydrate)
    monkeypatch.setattr(api_main.retrieval, "search", fake_retrieval_search)

    page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_route",
        OpenAIVectorStoreSearchRequest(
            query="State v. Harris",
            lens="court_citator",
            inputs={"docket_number": "116515", "relationship": "same_docket"},
            max_num_results=5,
        ),
        _principal(),
        _Db(),
    ))

    assert calls[0].query == "State v. Harris"
    assert calls[0].filters["file_attribute_filters"] == {"docket_number": "116515"}
    assert [row["relation_type"] for row in hydrated_relation_rows] == ["same_docket"]
    assert [item["file_id"] for item in page["data"][:2]] == ["file_direct", "file_related"]
    assert page["search_lens"]["id"] == "court_citator"
    assert page["search_lens"]["source"] == "explicit"
    assert page["graph_expansion"]["applied"] is True
    assert page["graph_expansion"]["relation_types"] == ["same_docket"]
    assert page["graph_expansion"]["coverage"]["edge_type_counts"] == {"cites_case": 404}


def test_openai_vector_store_search_page_rejects_unsupported_lens(monkeypatch):
    monkeypatch.setenv("SVS_QUERY_PLANNER_PROFILE_ID", "ks_civics_legal_v1")
    monkeypatch.setenv("SVS_KSCOURTS_GRAPHRAG_ENABLED", "true")
    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_main,
        "_vector_store_attributes_for_search",
        lambda *args, **kwargs: {"source_collection": "topeka-municipal-code", "corpus": "topeka_municipal_code"},
    )
    monkeypatch.setattr(
        api_main,
        "_graph_coverage_for_vector_store",
        lambda *args, **kwargs: {"node_count": 1, "edge_count": 1},
    )

    with pytest.raises(OpenAICompatError, match="not supported"):
        asyncio.run(api_main._openai_vector_store_search_page(
            "vs_topeka",
            OpenAIVectorStoreSearchRequest(query="State v. Harris", lens="court_citator"),
            _principal(),
            _Db(),
        ))


def test_openai_vector_store_search_page_accepts_query_array(monkeypatch):
    calls = []

    async def fake_retrieval_search(db_session, principal, search_req):
        calls.append(search_req)
        ordinal = len(calls)
        return SearchResponse(
            query=search_req.query,
            results=[
                ChunkRecord(
                    id=f"chk_multi_{ordinal}",
                    document_id=f"doc_multi_{ordinal}",
                    ordinal=0,
                    text=f"Evidence for {search_req.query}",
                    score=0.9 - (ordinal * 0.05),
                )
            ],
        )

    def fake_file_lookup(db_session, principal, vector_store_id, document_ids):
        return {
            "doc_multi_1": {
                "file_id": "file_multi_1",
                "filename": "runpod-marker.md",
            },
            "doc_multi_2": {
                "file_id": "file_multi_2",
                "filename": "voyage-embeddings.md",
            },
            "doc_multi_3": {
                "file_id": "file_multi_3",
                "filename": "api-key-scopes.md",
            },
        }

    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "_vector_store_file_lookup", fake_file_lookup)
    monkeypatch.setattr(api_main.retrieval, "search", fake_retrieval_search)

    page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_route",
        OpenAIVectorStoreSearchRequest(
            query=[
                "Can you find RunPod Marker warmup and Voyage embeddings?",
                "Show me API key scopes",
            ],
            rewrite_query=True,
            max_num_results=10,
        ),
        _principal(),
        _Db(),
    ))

    assert [call.query for call in calls] == ["RunPod Marker warmup", "Voyage embeddings", "API key scopes"]
    assert all(call.vector_store_id == "vs_route" for call in calls)
    assert all(call.filters["vector_store_id"] == "vs_route" for call in calls)
    assert all(
        call.search_metadata["openai_compat"]["effective_query"]
        == ["RunPod Marker warmup and Voyage embeddings", "API key scopes"]
        for call in calls
    )
    assert all(
        call.search_metadata["openai_compat"]["subqueries"]
        == ["RunPod Marker warmup", "Voyage embeddings", "API key scopes"]
        for call in calls
    )
    assert page["search_query"] == ["RunPod Marker warmup and Voyage embeddings", "API key scopes"]
    assert [item["file_id"] for item in page["data"]] == ["file_multi_1", "file_multi_2", "file_multi_3"]
    assert [item["citation"]["chunk_id"] for item in page["data"]] == ["chk_multi_1", "chk_multi_2", "chk_multi_3"]
