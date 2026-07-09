from __future__ import annotations

from svs_api import main as api_main
from svs_common.schemas import (
    OpenAIAdminApiKey,
    OpenAIAdminApiKeyCreateRequest,
    OpenAIAdminApiKeyCreateResponse,
    OpenAIAdminApiKeyDeletedResponse,
    OpenAIAdminApiKeyListResponse,
    OpenAIFile,
    OpenAIFileDeletedResponse,
    OpenAIFileListResponse,
    OpenAIProjectApiKey,
    OpenAIProjectApiKeyDeletedResponse,
    OpenAIProjectApiKeyListResponse,
    OpenAIMessageFileCitationAnnotation,
    OpenAIResponseObject,
    OpenAIResponseRequest,
    OpenAIResponseStreamEvent,
    OpenAIVectorStoreFileContentResponse,
    OpenAIVectorStoreFileDeletedResponse,
    OpenAIVectorStoreFileBatch,
    OpenAIVectorStoreFileBatchFilesPage,
    OpenAIVectorStoreFileListResponse,
    OpenAIVectorStoreSearchResultsPage,
    VectorStoreDeletedResponse,
    VectorStoreListResponse,
    VectorStoreResponse,
)


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _request_schema(spec: dict, path: str) -> dict:
    return spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]


def _response_schema(spec: dict, path: str, method: str = "post") -> dict:
    return spec["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]


def _ref_names_in(schema) -> set[str]:
    if isinstance(schema, dict):
        names = {_ref_name(schema["$ref"])} if "$ref" in schema else set()
        for value in schema.values():
            names.update(_ref_names_in(value))
        return names
    if isinstance(schema, list):
        names: set[str] = set()
        for value in schema:
            names.update(_ref_names_in(value))
        return names
    return set()


def test_responses_create_openapi_uses_named_request_component():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    schema = _request_schema(spec, "/v1/responses")
    assert _ref_name(schema["$ref"]) == "OpenAIResponseRequest"

    component = spec["components"]["schemas"]["OpenAIResponseRequest"]
    props = component["properties"]
    expected_fields = {
        "model",
        "input",
        "tools",
        "tool_choice",
        "include",
        "previous_response_id",
        "conversation",
        "instructions",
        "store",
        "stream",
        "stream_options",
        "background",
    }
    assert expected_fields.issubset(props)

    tool_schema = props["tools"]["anyOf"][0]["items"]["$ref"]
    tool_component = spec["components"]["schemas"][_ref_name(tool_schema)]
    assert {"type", "vector_store_ids", "filters", "max_num_results", "ranking_options"}.issubset(
        tool_component["properties"]
    )
    max_results = tool_component["properties"]["max_num_results"]
    assert max_results["default"] == 20
    assert max_results["minimum"] == 1
    assert max_results["maximum"] == 50

    response_content = spec["paths"]["/v1/responses"]["post"]["responses"]["200"]["content"]
    assert "application/json" in response_content
    assert "text/event-stream" in response_content


def test_responses_utility_routes_use_named_request_components():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    assert _ref_name(_request_schema(spec, "/v1/responses/input_tokens")["$ref"]) == "OpenAIResponseInputTokensRequest"
    assert _ref_name(_request_schema(spec, "/v1/responses/compact")["$ref"]) == "OpenAIResponseCompactRequest"


def test_responses_json_routes_use_named_response_components():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    expected_refs = {
        ("/v1/responses", "post"): "OpenAIResponseObject",
        ("/v1/responses/{response_id}", "get"): "OpenAIResponseObject",
        ("/v1/responses/{response_id}/cancel", "post"): "OpenAIResponseObject",
        ("/v1/responses/input_tokens", "post"): "OpenAIResponseInputTokensResponse",
        ("/v1/responses/compact", "post"): "OpenAIResponseCompactionResponse",
        ("/v1/responses/{response_id}", "delete"): "OpenAIResponseDeletedResponse",
        ("/v1/responses/{response_id}/input_items", "get"): "OpenAIResponseInputItemsPage",
    }

    for (path, method), component_name in expected_refs.items():
        assert _ref_name(_response_schema(spec, path, method)["$ref"]) == component_name

    assert "text/event-stream" in spec["paths"]["/v1/responses"]["post"]["responses"]["200"]["content"]
    assert "text/event-stream" in spec["paths"]["/v1/responses/{response_id}"]["get"]["responses"]["200"]["content"]


def test_responses_openapi_exposes_openai_file_citation_annotation_shape():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()
    components = spec["components"]["schemas"]

    annotation = components["OpenAIFileCitationAnnotation"]
    assert set(annotation["properties"]) == {"type", "index", "file_id", "filename"}
    assert set(annotation["required"]) == {"type", "index", "file_id", "filename"}
    assert annotation["additionalProperties"] is False
    assert annotation["properties"]["type"]["const"] == "file_citation"
    assert annotation["properties"]["index"]["minimum"] == 0
    assert annotation["properties"]["file_id"]["minLength"] == 1
    assert annotation["properties"]["filename"]["minLength"] == 1

    message_annotation = components["OpenAIMessageFileCitationAnnotation"]
    assert set(message_annotation["properties"]) == {
        "type",
        "start_index",
        "end_index",
        "text",
        "file_citation",
    }
    assert set(message_annotation["required"]) == {
        "type",
        "start_index",
        "end_index",
        "text",
        "file_citation",
    }
    assert message_annotation["additionalProperties"] is False
    assert message_annotation["properties"]["type"]["const"] == "file_citation"
    assert message_annotation["properties"]["start_index"]["minimum"] == 0
    assert message_annotation["properties"]["end_index"]["minimum"] == 0
    assert _ref_name(message_annotation["properties"]["file_citation"]["$ref"]) == "OpenAIMessageFileCitation"

    output_text = components["OpenAIResponseOutputTextContent"]
    assert _ref_name(output_text["properties"]["annotations"]["items"]["$ref"]) == "OpenAIFileCitationAnnotation"

    message_item = components["OpenAIResponseMessageItem"]
    assert "OpenAIResponseOutputTextContent" in _ref_names_in(message_item["properties"]["content"])

    native_citation = components["OpenAINativeCitation"]
    assert "OpenAIFileCitationAnnotation" in _ref_names_in(native_citation["properties"]["annotation"])
    assert "OpenAIMessageFileCitationAnnotation" in _ref_names_in(native_citation["properties"]["message_annotation"])
    assert native_citation["properties"]["start_index"]["anyOf"][0]["minimum"] == 0
    assert native_citation["properties"]["end_index"]["anyOf"][0]["minimum"] == 0

    response_object = components["OpenAIResponseObject"]
    assert {"OpenAIResponseFileSearchCallItem", "OpenAIResponseMessageItem"}.issubset(
        _ref_names_in(response_object["properties"]["output"])
    )

    file_search_call = components["OpenAIResponseFileSearchCallItem"]
    assert "OpenAIResponseFileSearchResult" in _ref_names_in(file_search_call["properties"]["results"])


def test_responses_openapi_exposes_openai_citation_stream_event_shape():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()
    components = spec["components"]["schemas"]

    for path, method in (("/v1/responses", "post"), ("/v1/responses/{response_id}", "get")):
        stream_schema = spec["paths"][path][method]["responses"]["200"]["content"]["text/event-stream"]["schema"]
        assert _ref_name(stream_schema["$ref"]) == "OpenAIResponseStreamEvent"
        assert _ref_name(_response_schema(spec, path, method)["$ref"]) == "OpenAIResponseObject"

    stream_event = components["OpenAIResponseStreamEvent"]
    assert "OpenAIResponseOutputTextAnnotationAddedEvent" in _ref_names_in(stream_event)
    assert "OpenAIResponseContentPartDoneEvent" in _ref_names_in(stream_event)
    assert "OpenAIResponseCompletedEvent" in _ref_names_in(stream_event)

    annotation_event = components["OpenAIResponseOutputTextAnnotationAddedEvent"]
    assert annotation_event["properties"]["type"]["const"] == "response.output_text.annotation.added"
    assert set(annotation_event["required"]) == {
        "type",
        "item_id",
        "output_index",
        "content_index",
        "annotation_index",
        "annotation",
    }
    assert annotation_event["properties"]["output_index"]["minimum"] == 0
    assert annotation_event["properties"]["content_index"]["minimum"] == 0
    assert annotation_event["properties"]["annotation_index"]["minimum"] == 0
    assert _ref_name(annotation_event["properties"]["annotation"]["$ref"]) == "OpenAIFileCitationAnnotation"

    content_done = components["OpenAIResponseContentPartDoneEvent"]
    assert "OpenAIResponseOutputTextContent" in _ref_names_in(content_done["properties"]["part"])
    completed = components["OpenAIResponseCompletedEvent"]
    assert _ref_name(completed["properties"]["response"]["$ref"]) == "OpenAIResponseObject"

    event = OpenAIResponseStreamEvent.model_validate({
        "type": "response.output_text.annotation.added",
        "sequence_number": 8,
        "item_id": "msg_stream",
        "output_index": 1,
        "content_index": 0,
        "annotation_index": 0,
        "annotation": {
            "type": "file_citation",
            "index": 42,
            "file_id": "file_stream",
            "filename": "stream.md",
        },
    })
    assert event.root.annotation.file_id == "file_stream"


def test_vector_store_routes_use_named_openapi_response_components():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    expected_refs = {
        ("/v1/vector_stores", "post"): "VectorStoreResponse",
        ("/v1/vector_stores", "get"): "VectorStoreListResponse",
        ("/v1/vector_stores/{vector_store_id}", "get"): "VectorStoreResponse",
        ("/v1/vector_stores/{vector_store_id}", "post"): "VectorStoreResponse",
        ("/v1/vector_stores/{vector_store_id}", "patch"): "VectorStoreResponse",
        ("/v1/vector_stores/{vector_store_id}", "delete"): "VectorStoreDeletedResponse",
    }

    for (path, method), component_name in expected_refs.items():
        assert _ref_name(_response_schema(spec, path, method)["$ref"]) == component_name

    components = spec["components"]["schemas"]
    store = components["VectorStoreResponse"]
    assert store["properties"]["object"]["default"] == "vector_store"
    assert {"id", "object", "status", "bytes", "file_counts", "created_at", "metadata"}.issubset(
        store["properties"]
    )

    page = components["VectorStoreListResponse"]
    assert page["properties"]["object"]["default"] == "list"
    assert _ref_name(page["properties"]["data"]["items"]["$ref"]) == "VectorStoreResponse"

    deleted = components["VectorStoreDeletedResponse"]
    assert deleted["properties"]["object"]["default"] == "vector_store.deleted"
    assert {"id", "object", "deleted"}.issubset(deleted["properties"])


def test_vector_store_response_models_preserve_openai_payload_shape():
    store = {
        "id": "vs_contract",
        "object": "vector_store",
        "name": "Contracts",
        "status": "completed",
        "bytes": 12,
        "usage_bytes": 12,
        "file_counts": {"in_progress": 0, "completed": 1, "failed": 0, "cancelled": 0, "total": 1},
        "attributes": {"region": "us"},
        "metadata": {"region": "us"},
        "created_at": 1710000000,
    }
    page = {
        "object": "list",
        "data": [store],
        "first_id": "vs_contract",
        "last_id": "vs_contract",
        "has_more": False,
    }
    deleted = {"id": "vs_contract", "object": "vector_store.deleted", "deleted": True}

    assert VectorStoreResponse.model_validate(store).model_dump(mode="python", exclude_unset=True) == store
    assert VectorStoreListResponse.model_validate(page).model_dump(mode="python", exclude_unset=True) == page
    assert VectorStoreDeletedResponse.model_validate(deleted).model_dump(mode="python", exclude_unset=True) == deleted


def test_openai_file_routes_use_named_openapi_response_components():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    expected_refs = {
        ("/v1/files", "post"): "OpenAIFile",
        ("/v1/files", "get"): "OpenAIFileListResponse",
        ("/v1/files/{file_id}", "get"): "OpenAIFile",
        ("/v1/files/{file_id}", "delete"): "OpenAIFileDeletedResponse",
    }

    for (path, method), component_name in expected_refs.items():
        assert _ref_name(_response_schema(spec, path, method)["$ref"]) == component_name

    components = spec["components"]["schemas"]
    file_component = components["OpenAIFile"]
    assert file_component["properties"]["object"]["default"] == "file"
    assert {"id", "object", "bytes", "created_at", "filename", "purpose", "expires_at"}.issubset(
        file_component["properties"]
    )

    page = components["OpenAIFileListResponse"]
    assert page["properties"]["object"]["default"] == "list"
    assert _ref_name(page["properties"]["data"]["items"]["$ref"]) == "OpenAIFile"

    deleted = components["OpenAIFileDeletedResponse"]
    assert deleted["properties"]["object"]["default"] == "file"
    assert {"id", "object", "deleted"}.issubset(deleted["properties"])

    content = spec["paths"]["/v1/files/{file_id}/content"]["get"]["responses"]["200"]["content"]
    assert "text/plain" in content
    assert "application/json" not in content


def test_openai_file_response_models_preserve_payload_shape():
    file_object = {
        "id": "file_contract",
        "object": "file",
        "bytes": 123,
        "created_at": 1710000000,
        "filename": "contract.md",
        "purpose": "assistants",
    }
    expiring_file = {**file_object, "id": "file_expiring", "expires_at": 1710003600}
    page = {
        "object": "list",
        "data": [file_object, expiring_file],
        "first_id": "file_contract",
        "last_id": "file_expiring",
        "has_more": False,
    }
    deleted = {"id": "file_contract", "object": "file", "deleted": True}

    assert OpenAIFile.model_validate(file_object).model_dump(mode="python", exclude_unset=True) == file_object
    assert OpenAIFile.model_validate(expiring_file).model_dump(mode="python", exclude_unset=True) == expiring_file
    assert OpenAIFileListResponse.model_validate(page).model_dump(mode="python", exclude_unset=True) == page
    assert OpenAIFileDeletedResponse.model_validate(deleted).model_dump(mode="python", exclude_unset=True) == deleted


def test_vector_store_search_openapi_uses_named_response_component():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    request_schema = _request_schema(spec, "/v1/vector_stores/{vector_store_id}/search")
    assert _ref_name(request_schema["$ref"]) == "OpenAIVectorStoreSearchRequest"
    assert _ref_name(_response_schema(spec, "/v1/vector_stores/{vector_store_id}/search")["$ref"]) == (
        "OpenAIVectorStoreSearchResultsPage"
    )

    components = spec["components"]["schemas"]
    page = components["OpenAIVectorStoreSearchResultsPage"]
    assert _ref_name(page["properties"]["data"]["items"]["$ref"]) == "OpenAIVectorStoreSearchResult"
    assert "OpenAIVectorStoreSearchCitation" in _ref_names_in(page["properties"]["citations"])

    result = components["OpenAIVectorStoreSearchResult"]
    assert _ref_name(result["properties"]["annotations"]["items"]["$ref"]) == "OpenAIFileCitationAnnotation"
    assert "OpenAIVectorStoreSearchContent" in _ref_names_in(result["properties"]["content"])
    assert "OpenAIVectorStoreSearchCitation" in _ref_names_in(result["properties"]["citation"])
    assert "OpenAIVectorStoreSearchCitation" in _ref_names_in(result["properties"]["citations"])

    content = components["OpenAIVectorStoreSearchContent"]
    assert content["properties"]["type"]["const"] == "text"
    assert _ref_name(content["properties"]["annotations"]["items"]["$ref"]) == "OpenAIFileCitationAnnotation"

    citation = components["OpenAIVectorStoreSearchCitation"]
    assert "OpenAIFileCitationAnnotation" in _ref_names_in(citation["properties"]["annotation"])
    assert "OpenAIMessageFileCitationAnnotation" in _ref_names_in(citation["properties"]["message_annotation"])
    assert citation["properties"]["start_index"]["anyOf"][0]["minimum"] == 0
    assert citation["properties"]["end_index"]["anyOf"][0]["minimum"] == 0


def test_vector_store_search_page_model_preserves_citation_payload_shape():
    annotation = {
        "type": "file_citation",
        "index": 42,
        "file_id": "file_search_contract",
        "filename": "search-contract.md",
    }
    message_annotation = {
        "type": "file_citation",
        "start_index": 42,
        "end_index": 52,
        "text": "【1†source】",
        "file_citation": {"file_id": "file_search_contract"},
    }
    citation = {
        "type": "file_citation",
        "index": 42,
        "file_id": "file_search_contract",
        "filename": "search-contract.md",
        "chunk_id": "chk_search_contract",
        "document_id": "doc_search_contract",
        "marker": "【1†source】",
        "start_index": 42,
        "end_index": 52,
        "annotation": annotation,
        "message_annotation": message_annotation,
        "page_start": 3,
        "heading_path": ["Search", "Contract"],
    }
    payload = {
        "object": "vector_store.search_results.page",
        "search_query": "citation contract",
        "data": [{
            "file_id": "file_search_contract",
            "filename": "search-contract.md",
            "score": 0.91,
            "attributes": {"topic": "contracts"},
            "content": [{
                "type": "text",
                "text": "Direct search citation proof. 【1†source】",
                "annotations": [annotation],
            }],
            "annotations": [annotation],
            "citation": citation,
            "citations": [citation],
            "output_guard": {"id": "pii_secret_citation_guard_v1", "redactions": []},
        }],
        "citations": [citation],
        "has_more": False,
        "next_page": None,
    }

    dumped = OpenAIVectorStoreSearchResultsPage.model_validate(payload).model_dump(
        mode="python",
        exclude_unset=True,
    )
    assert dumped == payload
    assert OpenAIMessageFileCitationAnnotation.model_validate(message_annotation).model_dump(mode="python") == (
        message_annotation
    )


def test_file_batch_routes_use_named_openapi_response_components():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    expected_refs = {
        ("/v1/vector_stores/{vector_store_id}/file_batches", "post"): "OpenAIVectorStoreFileBatch",
        ("/v1/vector_stores/{vector_store_id}/file_batches/{batch_id}", "get"): "OpenAIVectorStoreFileBatch",
        ("/v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel", "post"): "OpenAIVectorStoreFileBatch",
        ("/v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/files", "get"): (
            "OpenAIVectorStoreFileBatchFilesPage"
        ),
    }

    for (path, method), component_name in expected_refs.items():
        assert _ref_name(_response_schema(spec, path, method)["$ref"]) == component_name

    components = spec["components"]["schemas"]
    batch = components["OpenAIVectorStoreFileBatch"]
    assert batch["properties"]["object"]["default"] == "vector_store.file_batch"
    assert _ref_name(batch["properties"]["file_counts"]["anyOf"][0]["$ref"]) == "OpenAIVectorStoreFileBatchCounts"

    counts = components["OpenAIVectorStoreFileBatchCounts"]
    assert {"in_progress", "completed", "failed", "cancelled", "total"}.issubset(counts["properties"])

    page = components["OpenAIVectorStoreFileBatchFilesPage"]
    assert page["properties"]["object"]["default"] == "list"
    assert _ref_name(page["properties"]["data"]["items"]["$ref"]) == "OpenAIVectorStoreFile"

    file_component = components["OpenAIVectorStoreFile"]
    assert file_component["properties"]["object"]["default"] == "vector_store.file"
    assert {"id", "object", "vector_store_id", "status", "usage_bytes", "created_at", "last_error"}.issubset(
        file_component["properties"]
    )
    assert "OpenAIVectorStoreFileLastError" in _ref_names_in(file_component["properties"]["last_error"])


def test_file_batch_response_models_preserve_openai_payload_shape():
    batch = {
        "id": "vsfb_contract",
        "object": "vector_store.file_batch",
        "vector_store_id": "vs_contract",
        "status": "completed",
        "file_counts": {
            "in_progress": 0,
            "completed": 1,
            "failed": 0,
            "cancelled": 0,
            "total": 1,
        },
        "created_at": 1710000000,
    }
    page = {
        "object": "list",
        "data": [{
            "id": "file_contract",
            "object": "vector_store.file",
            "vector_store_id": "vs_contract",
            "status": "completed",
            "usage_bytes": 123,
            "created_at": 1710000001,
            "last_error": None,
            "attributes": {"region": "us"},
        }],
        "first_id": "file_contract",
        "last_id": "file_contract",
        "has_more": False,
    }

    assert OpenAIVectorStoreFileBatch.model_validate(batch).model_dump(mode="python", exclude_unset=True) == batch
    assert OpenAIVectorStoreFileBatchFilesPage.model_validate(page).model_dump(mode="python", exclude_unset=True) == page


def test_vector_store_file_routes_use_named_openapi_response_components():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    expected_refs = {
        ("/v1/vector_stores/{vector_store_id}/files", "post"): "OpenAIVectorStoreFile",
        ("/v1/vector_stores/{vector_store_id}/files", "get"): "OpenAIVectorStoreFileListResponse",
        ("/v1/vector_stores/{vector_store_id}/files/{file_id}", "get"): "OpenAIVectorStoreFile",
        ("/v1/vector_stores/{vector_store_id}/files/{file_id}", "post"): "OpenAIVectorStoreFile",
        ("/v1/vector_stores/{vector_store_id}/files/{file_id}", "patch"): "OpenAIVectorStoreFile",
        ("/v1/vector_stores/{vector_store_id}/files/{file_id}", "delete"): "OpenAIVectorStoreFileDeletedResponse",
        ("/v1/vector_stores/{vector_store_id}/files/{file_id}/content", "get"): (
            "OpenAIVectorStoreFileContentResponse"
        ),
    }

    for (path, method), component_name in expected_refs.items():
        assert _ref_name(_response_schema(spec, path, method)["$ref"]) == component_name

    components = spec["components"]["schemas"]
    page = components["OpenAIVectorStoreFileListResponse"]
    assert page["properties"]["object"]["default"] == "list"
    assert _ref_name(page["properties"]["data"]["items"]["$ref"]) == "OpenAIVectorStoreFile"

    deleted = components["OpenAIVectorStoreFileDeletedResponse"]
    assert deleted["properties"]["object"]["default"] == "vector_store.file.deleted"
    assert deleted["properties"]["deleted"]["default"] is True

    content = components["OpenAIVectorStoreFileContentResponse"]
    assert content["properties"]["object"]["default"] == "vector_store.file_content"
    assert _ref_name(content["properties"]["data"]["items"]["$ref"]) == "OpenAIVectorStoreFileContentItem"


def test_vector_store_file_response_models_preserve_openai_payload_shape():
    page = {
        "object": "list",
        "data": [{
            "id": "file_contract",
            "object": "vector_store.file",
            "vector_store_id": "vs_contract",
            "status": "completed",
            "usage_bytes": 123,
            "created_at": 1710000001,
            "last_error": None,
            "attributes": {"region": "us"},
        }],
        "first_id": "file_contract",
        "last_id": "file_contract",
        "has_more": False,
    }
    deleted = {
        "id": "file_contract",
        "object": "vector_store.file.deleted",
        "deleted": True,
    }
    content = {
        "object": "vector_store.file_content",
        "data": [{"type": "text", "text": "parsed content"}],
    }

    assert OpenAIVectorStoreFileListResponse.model_validate(page).model_dump(mode="python", exclude_unset=True) == page
    assert OpenAIVectorStoreFileDeletedResponse.model_validate(deleted).model_dump(mode="python", exclude_unset=True) == deleted
    assert OpenAIVectorStoreFileContentResponse.model_validate(content).model_dump(mode="python", exclude_unset=True) == content


def test_project_api_key_routes_use_named_response_components():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    assert _ref_name(_response_schema(
        spec,
        "/v1/organization/projects/{project_id}/api_keys",
        "get",
    )["$ref"]) == "OpenAIProjectApiKeyListResponse"
    assert _ref_name(_response_schema(
        spec,
        "/v1/organization/projects/{project_id}/api_keys/{api_key_id}",
        "get",
    )["$ref"]) == "OpenAIProjectApiKey"
    assert _ref_name(_response_schema(
        spec,
        "/v1/organization/projects/{project_id}/api_keys/{api_key_id}",
        "delete",
    )["$ref"]) == "OpenAIProjectApiKeyDeletedResponse"

    components = spec["components"]["schemas"]
    project_key = components["OpenAIProjectApiKey"]
    assert {"object", "redacted_value", "name", "created_at", "last_used_at", "id", "owner"}.issubset(
        project_key["properties"]
    )
    assert "api_key" not in project_key["properties"]
    assert "key_hash" not in project_key["properties"]
    assert "scopes" not in project_key["properties"]
    assert "max_security_level" not in project_key["properties"]

    project_key_list = components["OpenAIProjectApiKeyListResponse"]
    assert _ref_name(project_key_list["properties"]["data"]["items"]["$ref"]) == "OpenAIProjectApiKey"
    deleted = components["OpenAIProjectApiKeyDeletedResponse"]
    assert deleted["properties"]["object"]["default"] == "organization.project.api_key.deleted"


def test_admin_api_key_routes_use_named_response_components():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    assert _ref_name(_request_schema(
        spec,
        "/v1/organization/admin_api_keys",
    )["$ref"]) == "OpenAIAdminApiKeyCreateRequest"
    assert _ref_name(_response_schema(
        spec,
        "/v1/organization/admin_api_keys",
        "post",
    )["$ref"]) == "OpenAIAdminApiKeyCreateResponse"
    assert _ref_name(_response_schema(
        spec,
        "/v1/organization/admin_api_keys",
        "get",
    )["$ref"]) == "OpenAIAdminApiKeyListResponse"
    assert _ref_name(_response_schema(
        spec,
        "/v1/organization/admin_api_keys/{key_id}",
        "get",
    )["$ref"]) == "OpenAIAdminApiKey"
    assert _ref_name(_response_schema(
        spec,
        "/v1/organization/admin_api_keys/{key_id}",
        "delete",
    )["$ref"]) == "OpenAIAdminApiKeyDeletedResponse"

    components = spec["components"]["schemas"]
    create_request = components["OpenAIAdminApiKeyCreateRequest"]
    assert set(create_request["properties"]) == {"name", "expires_in_seconds"}
    assert set(create_request["required"]) == {"name"}
    assert create_request["additionalProperties"] is False
    assert create_request["properties"]["name"]["minLength"] == 1
    expires_schema = next(
        branch
        for branch in create_request["properties"]["expires_in_seconds"]["anyOf"]
        if branch.get("type") == "integer"
    )
    assert expires_schema["minimum"] == 1
    assert expires_schema["maximum"] == 31536000

    create_response = components["OpenAIAdminApiKeyCreateResponse"]
    assert {"object", "id", "name", "redacted_value", "created_at", "expires_at", "last_used_at", "owner", "value"}.issubset(
        create_response["properties"]
    )
    assert "api_key" not in create_response["properties"]
    assert "key_hash" not in create_response["properties"]
    assert "scopes" not in create_response["properties"]
    assert "max_security_level" not in create_response["properties"]

    admin_key = components["OpenAIAdminApiKey"]
    assert {"object", "id", "name", "redacted_value", "created_at", "expires_at", "last_used_at", "owner"}.issubset(
        admin_key["properties"]
    )
    assert "value" not in admin_key["properties"]
    assert "api_key" not in admin_key["properties"]
    assert "key_hash" not in admin_key["properties"]
    assert "scopes" not in admin_key["properties"]
    assert "max_security_level" not in admin_key["properties"]

    admin_key_list = components["OpenAIAdminApiKeyListResponse"]
    assert _ref_name(admin_key_list["properties"]["data"]["items"]["$ref"]) == "OpenAIAdminApiKey"
    deleted = components["OpenAIAdminApiKeyDeletedResponse"]
    assert deleted["properties"]["object"]["default"] == "organization.admin_api_key.deleted"


def test_project_api_key_models_preserve_openai_payload_shape():
    payload = {
        "object": "organization.project.api_key",
        "redacted_value": "svs_live_...123456",
        "name": "retrieval",
        "created_at": 1710000000,
        "id": "key_123456",
        "owner": {"type": "user", "user": {"id": "user_abc"}},
    }
    page = {"object": "list", "data": [payload], "first_id": "key_123456", "last_id": "key_123456", "has_more": False}
    deleted = {"id": "key_123456", "object": "organization.project.api_key.deleted", "deleted": True}

    assert OpenAIProjectApiKey.model_validate(payload).model_dump(mode="python", exclude_unset=True) == payload
    assert OpenAIProjectApiKeyListResponse.model_validate(page).model_dump(mode="python", exclude_unset=True) == page
    assert OpenAIProjectApiKeyDeletedResponse.model_validate(deleted).model_dump(
        mode="python",
        exclude_unset=True,
    ) == deleted


def test_admin_api_key_models_preserve_openai_payload_shape():
    create_request = {"name": "New Admin Key", "expires_in_seconds": 2592000}
    assert OpenAIAdminApiKeyCreateRequest.model_validate(create_request).model_dump(
        mode="python",
        exclude_unset=True,
    ) == create_request
    assert OpenAIAdminApiKeyCreateRequest.model_validate({"name": "  New Admin Key  "}).name == "New Admin Key"

    payload = {
        "object": "organization.admin_api_key",
        "id": "key_123456",
        "name": "Main Admin Key",
        "redacted_value": "svs_live_...123456",
        "created_at": 1710000000,
        "expires_at": 1710003600,
        "last_used_at": 1710000100,
        "owner": {"type": "user", "object": "organization.user", "id": "user_abc", "role": "owner"},
    }
    page = {"object": "list", "data": [payload], "first_id": "key_123456", "last_id": "key_123456", "has_more": False}
    created = {**payload, "value": "svs_live_created_secret"}
    deleted = {"id": "key_123456", "object": "organization.admin_api_key.deleted", "deleted": True}

    assert OpenAIAdminApiKeyCreateResponse.model_validate(created).model_dump(
        mode="python",
        exclude_unset=True,
    ) == created
    assert OpenAIAdminApiKey.model_validate(payload).model_dump(mode="python", exclude_unset=True) == payload
    assert OpenAIAdminApiKeyListResponse.model_validate(page).model_dump(mode="python", exclude_unset=True) == page
    assert OpenAIAdminApiKeyDeletedResponse.model_validate(deleted).model_dump(
        mode="python",
        exclude_unset=True,
    ) == deleted


def test_response_object_model_preserves_openai_citation_payload_shape():
    annotation = {
        "type": "file_citation",
        "index": 7,
        "file_id": "file_contract",
        "filename": "contract.md",
    }
    message_annotation = {
        "type": "file_citation",
        "start_index": 7,
        "end_index": 17,
        "text": "【1†source】",
        "file_citation": {"file_id": "file_contract"},
    }
    payload = {
        "id": "resp_contract",
        "object": "response",
        "created_at": 1710000000,
        "status": "completed",
        "output": [
            {
                "type": "file_search_call",
                "id": "fs_contract",
                "status": "completed",
                "queries": ["contract citations"],
                "results": None,
            },
            {
                "type": "message",
                "id": "msg_contract",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": "Answer 【1†source】",
                    "annotations": [annotation],
                }],
            },
        ],
        "citations": [{
            "annotation": annotation,
            "marker": "【1†source】",
            "start_index": 7,
            "end_index": 17,
            "message_annotation": message_annotation,
            "chunk_id": "chk_contract",
            "page_start": 1,
        }],
    }

    dumped = OpenAIResponseObject.model_validate(payload).model_dump(mode="python", exclude_unset=True)
    assert dumped == payload


def test_response_request_payload_export_preserves_omitted_defaults():
    assert OpenAIResponseRequest(model="gpt-test", input="hello").to_compat_payload() == {
        "model": "gpt-test",
        "input": "hello",
    }
    assert OpenAIResponseRequest(model="gpt-test", input="hello", store=None).to_compat_payload() == {
        "model": "gpt-test",
        "input": "hello",
        "store": None,
    }
