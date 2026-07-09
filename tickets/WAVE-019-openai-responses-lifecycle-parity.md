# WAVE-019 OpenAI Responses Lifecycle Parity

## Summary

Close the next OpenAI SDK compatibility gap after `POST /v1/responses`: callers
should be able to retrieve, delete, and inspect input items for file-search
Responses objects by response ID.

Official OpenAI references checked on 2026-07-08:

- `/responses/{response_id}`
- `/responses/{response_id}/input_items`

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W19-001 | Complete | Implementation/Test | Persist file-search Responses objects and add retrieve/delete/input-items route parity under tenant/RLS scope. |

## W19-001 Acceptance Criteria

- [x] `POST /v1/responses` stores the created response when `store` is not
  explicitly `false`.
- [x] `GET /v1/responses/{response_id}` retrieves a stored response for the
  same tenant/business scope and supports the same non-streaming include guard
  as create.
- [x] `DELETE /v1/responses/{response_id}` marks the stored response deleted
  and returns `{id, object: "response", deleted: true}`.
- [x] Deleted or missing response IDs return 404 on retrieve and input-items.
- [x] `GET /v1/responses/{response_id}/input_items` returns an OpenAI-style
  list with stored user input items and supports `limit`, `order`, and `after`.
- [x] Response storage is backed by a tenant/business scoped table with RLS
  enabled and forced.
- [x] Focused tests and live proof cover Bearer API-key create, retrieve,
  input-items list, delete, and post-delete 404.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py
20 passed in 0.53s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py
29 passed, 2 warnings in 3.32s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
117 passed, 2 warnings in 4.24s

docker run --rm --network exais-vector-store-local_default --env-file .release/cells/local/.env.cell -v "${PWD}:/work" -w /work -e SVS_RUN_INTEGRATION=1 -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/integration/test_postgres_rls_and_worker.py::test_every_rls_table_is_forced
1 passed in 0.31s

git diff --check
<exit 0>
```

Live migration/proof against `exais-vector-store-local_default`:

```text
{'migration': '008_openai_responses_lifecycle.sql', 'applied': True}

{'api_key_prefix': 'svs_live_', 'vector_store_id': 'vs_04b0dd3b76ac4962b913a7eb', 'file_id': 'file_0950fdd846664eadbaf1a986', 'response_id': 'resp_458c094e046c4555a735d525', 'retrieved_object': 'response', 'input_items': {'first_id': 'msg_026fff25719e416d93dbe463_0', 'has_more': False}, 'annotation': {'type': 'file_citation', 'index': 32, 'file_id': 'file_0950fdd846664eadbaf1a986', 'filename': 'w19-responses-proof-5d813e560c.md'}, 'delete': {'id': 'resp_458c094e046c4555a735d525', 'object': 'response', 'deleted': True}, 'post_delete_status': 404, 'file_cleanup': {'id': 'file_0950fdd846664eadbaf1a986', 'object': 'file', 'deleted': True}}

{'store_false_response_id': 'resp_66244df075874dc8825895c1', 'retrieve_status': 404, 'file_cleanup': {'id': 'file_9a14840c0bef448c91009e07', 'object': 'file', 'deleted': True}}
```

## Notes

This ticket did not add model generation, streaming retrieval, cancellation, or
background execution. Stored response cancellation is covered by
`tickets/WAVE-062-openai-responses-cancel-parity.md`; background execution
remains out of scope.
