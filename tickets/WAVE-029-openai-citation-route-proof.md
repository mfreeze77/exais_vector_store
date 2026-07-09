# WAVE-029 OpenAI Citation Route Proof

## Summary

Lock the OpenAI-style citation contract at the `/v1/responses` route boundary.
Earlier W18/W20 work added the formatter and marker behavior; this ticket adds
focused route-level proof that OpenAI-compatible clients receive citations in
the same place and shape they expect from Responses file search.

Official OpenAI references checked on 2026-07-08:

- Responses OpenAPI example for `file_search` output: `output_text.annotations`
  with `type`, `index`, `file_id`, and `filename`.
- File search guide: `file_search_call.results` is included only when requested.
- Assistants message annotation guidance: file-search annotations refer to
  uploaded files and visible generated source markers such as `【13†source】`.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W29-001 | Complete | Test/Proof | Add route-level regression tests for OpenAI-style Responses file-search citations and include gating. |

## W29-001 Acceptance Criteria

- [x] `POST /v1/responses` returns an assistant `output_text` content part with
  `annotations` containing OpenAI-core `file_citation` objects.
- [x] Each annotation `index` points to the visible `【n†source】` marker in the
  returned text.
- [x] Annotation objects stay limited to `type`, `index`, `file_id`, and
  `filename`; ExAIS chunk/vector-store proof stays outside the OpenAI-core
  annotation object.
- [x] Without `include`, returned `file_search_call` output hides search result
  bodies while still returning visible citations.
- [x] With `include=["file_search_call.results"]`, the route returns both
  `results` and `search_results` for current and cookbook-style clients.
- [x] Multi-result Responses output emits ordered OpenAI-style markers such as
  `【1†source】` and `【2†source】`, with each annotation index pointing to its
  own visible marker.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_responses_routes.py
2 passed, 2 warnings in 3.03s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
29 passed, 2 warnings in 3.22s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
161 passed, 2 warnings in 3.83s

git diff --check
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
30 passed, 2 warnings in 2.94s
```

## Notes

This ticket does not add model prose generation or streaming Responses output.
It pins the deterministic retrieval-summary citation contract that OpenAI-style
clients consume today. The 2026-07-08 follow-up proof added multi-citation
numbering and annotation-index regression coverage after citation parity was
called out as a critical compatibility requirement.
