# WAVE-090 Responses File Search Default Result Count

## Objective

Match OpenAI Responses `file_search` behavior when callers omit
`max_num_results`: default to 20 retrieved results for the Responses tool path.

## Evidence Anchors

- OpenAI file-search guide shows a Responses request whose `file_search` tool
  omits `max_num_results`; the resulting response tool object carries
  `max_num_results: 20`.
  https://developers.openai.com/api/docs/guides/tools-file-search
- `packages/svs_common/svs_common/schemas.py`
- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Scope

- Set the Responses `file_search` tool default `max_num_results` to 20.
- Keep explicit `max_num_results` values authoritative and bounded to 1..50.
- Keep direct vector-store search request defaults unchanged.
- Document the omitted-field behavior.

## Non-Goals

- Changing direct vector-store search defaults.
- Changing ranking, retrieval, citation shapes, API-key behavior, database
  migrations, provider routing, deployment, tenant isolation, or admin UI.

## Acceptance

- [x] `OpenAIResponseFileSearchTool` defaults `max_num_results` to 20.
- [x] `responses_file_search_tools` defaults omitted `max_num_results` to 20.
- [x] Explicit Responses `file_search.max_num_results` values still pass
  through unchanged.
- [x] Docs describe the default.

## Proof

- Focused OpenAI/Responses/OpenAPI:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openapi_contract.py`
  passed with `121 passed, 2 warnings in 4.73s`.
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  passed.
- Broad non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  passed with `390 passed, 2 warnings in 5.33s`.
- Whitespace:
  `git diff --check` passed.
