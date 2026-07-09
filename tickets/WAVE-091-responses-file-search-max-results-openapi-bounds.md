# WAVE-091 Responses File Search Max Results OpenAPI Bounds

## Objective

Expose the Responses `file_search.max_num_results` default and bounds in the
generated OpenAPI request component so client generators see the same contract
that runtime validation already enforces.

## Evidence Anchors

- OpenAI file-search guide shows omitted `max_num_results` normalizing to 20 in
  the response tool object.
  https://developers.openai.com/api/docs/guides/tools-file-search
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Scope

- Add `minimum: 1`, `maximum: 50`, and `default: 20` to the generated
  `OpenAIResponseFileSearchTool.max_num_results` schema.
- Keep runtime helper validation and explicit value behavior unchanged.
- Keep direct vector-store search schema unchanged.
- Document the generated contract.

## Non-Goals

- Changing retrieval, ranking, citation shapes, API-key behavior, database
  migrations, provider routing, deployment, tenant isolation, or admin UI.
- Changing direct vector-store search defaults or bounds.

## Acceptance

- [x] `OpenAIResponseFileSearchTool.max_num_results` is declared with
  default 20 and bounds 1..50.
- [x] `/openapi.json` exposes default 20 plus minimum 1 and maximum 50.
- [x] Focused OpenAPI regression covers the generated schema.
- [x] Docs describe the generated contract.

## Proof

- Focused OpenAPI/Responses:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openapi_contract.py tests/test_openai_compat_search.py tests/test_openai_responses_routes.py`
  passed with `121 passed, 2 warnings in 4.01s`.
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  passed.
- Broad non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  passed with `390 passed, 2 warnings in 5.94s`.
- Whitespace:
  `git diff --check` passed.
