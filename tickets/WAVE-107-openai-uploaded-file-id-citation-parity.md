# WAVE-107 OpenAI Uploaded File ID Citation Parity

## Goal

Tighten OpenAI citation mimicry at the file-identity boundary. Responses and
vector-store citation payloads already use the strict OpenAI `file_citation`
shape, but newly uploaded `/v1/files` objects still used underscore
`file_...` IDs. Current OpenAI file and file-search citation examples use
hyphenated `file-...` file IDs, so new ExAIS uploads should follow that public
shape while preserving legacy local lookup.

## OpenAI references

Official OpenAI references checked on 2026-07-09:

- Files API OpenAPI spec for `GET|POST /v1/files` examples:
  https://api.openai.com/v1/files
- Responses API OpenAPI spec for file-search citation examples:
  https://api.openai.com/v1/responses
- Assistants message annotation guidance for `file_citation`:
  https://developers.openai.com/api/docs/assistants/deep-dive#message-annotations

## Scope

- Add a dedicated OpenAI file-ID generator for new `/v1/files` uploads using
  the current `file-...` public prefix.
- Preserve existing document/file lookup paths so stored `file_...` IDs and
  legacy document IDs remain resolvable.
- Add focused regression coverage for the new file ID prefix.
- Update OpenAI compatibility docs and tracker notes so file-search citations
  inherit the current OpenAI-style uploaded file ID shape.

## Out of scope

- Changing vector-store IDs, vector-store-file IDs, file-batch IDs, response
  IDs, API-key IDs, or internal ExAIS document/chunk IDs.
- Rewriting existing stored file IDs.
- Changing citation annotation fields, marker placement, retrieval ranking,
  indexing, tenant policy, API-key behavior, rate limits, or idempotency
  semantics.

## Acceptance criteria

- [x] New `/v1/files` uploads generate `file-...` public file IDs.
- [x] Legacy `file_...` file IDs remain represented in tests and resolvable by
  existing metadata-backed lookup paths.
- [x] Strict OpenAI `file_citation` annotations continue to use only `type`,
  `index`, `file_id`, and `filename`.
- [x] Focused file, citation, Responses route, and OpenAPI tests pass.

## Changed files

- `apps/api/svs_api/main.py`
- `tests/test_openai_files.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-107-openai-uploaded-file-id-citation-parity.md`

## Verification

Focused files/citation/OpenAPI verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openapi_contract.py
```

Result: `184 passed, 2 warnings in 5.78s`.

Compile verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
```

Result: pass.

Broad non-integration verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
```

Result: `424 passed, 2 warnings in 6.78s`.

## Quality control

Acceptance criteria:

- [pass] New `/v1/files` uploads generate `file-...` public file IDs.
- [pass] Legacy `file_...` IDs remain represented by existing file object/list
  tests and metadata-backed lookup code remains unchanged.
- [pass] Strict OpenAI `file_citation` annotations remain unchanged and the
  focused citation suite passed.
- [pass] Compile, broad non-integration, and whitespace verification passed.

Findings:

- None.

Required fixes before next ticket:

- None.

Whitespace verification:

```powershell
git diff --check
```

Result: pass.
