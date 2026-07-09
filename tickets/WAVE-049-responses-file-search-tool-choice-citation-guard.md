# WAVE-049 Responses File Search Tool Choice Citation Guard

## Summary

Make Responses file-search citations respect OpenAI `tool_choice` semantics.
The deterministic `/v1/responses` file-search facade should only emit
file-search calls and `file_citation` annotations when the request leaves
`file_search` available or explicitly forces it.

## Background

Official OpenAI references checked on 2026-07-08:

- Responses create reference: `include` supports `file_search_call.results`,
  and `file_search_call` output items expose `queries`, `status`, `type`, and
  optional `results`.
- File-search guide: Responses file search returns a `file_search_call` output
  item plus a message with file citation annotations.
- Tool-choice reference text: `none` means the model will not call tools,
  `auto` may call tools, `required` must call at least one tool, and an object
  can force a particular tool.

Prior citation waves implemented strict `file_citation` annotation objects,
visible OpenAI-style citation markers, result include parity, duplicate result
dedupe, native annotation mirrors, streaming citation events, stream resume, and
stream obfuscation parity. This ticket closes a trust gap: unsupported or
conflicting `tool_choice` values must not silently produce file-search
citations.

## Scope

- Add a Responses file-search `tool_choice` validator.
- Accept omitted `tool_choice`, `auto`, `required`, the forced
  `{"type": "file_search"}` hosted-tool object, and `allowed_tools` objects
  whose allowed tool list includes `file_search`.
- Reject `none`, non-file-search forced tools, non-supported string choices,
  and malformed objects with HTTP 422.
- Call the validator before executing vector-store search.
- Preserve existing JSON, stored response, and streaming citation shapes for
  supported choices.
- Update focused helper/route tests, docs, trail, and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Adding non-`file_search` tools.
- Generating no-tool model prose for `tool_choice: "none"`.
- Changing the strict OpenAI `file_citation` annotation object.
- Changing included `file_search_call.results` fields.
- Changing API key, tenant, indexing, provider, or deployment behavior.

## Acceptance Criteria

- [x] Supported file-search choices continue to return OpenAI-shaped
  `file_search_call` output and strict `file_citation` annotations.
- [x] `tool_choice: "none"` returns 422 and does not execute search.
- [x] Forced non-file-search tool choices return 422 and does not execute search.
- [x] Malformed `tool_choice` values return 422 with a clear compatibility
  error.
- [x] Existing streaming and non-streaming citation shapes remain unchanged.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
68 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
245 passed, 2 warnings

git diff --check
pass
```
