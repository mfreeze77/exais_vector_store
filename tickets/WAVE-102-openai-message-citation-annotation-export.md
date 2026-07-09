# WAVE-102 OpenAI Message Citation Annotation Export

## Goal

Mimic OpenAI citation behavior for renderer clients that expect replacement-span
message annotations, while preserving the strict Responses API
`output_text.annotations` contract already implemented by ExAIS.

## OpenAI references

Official OpenAI references checked on 2026-07-09:

- Responses file search guide: file-search output returns assistant
  `output_text.annotations` `file_citation` objects:
  https://developers.openai.com/api/docs/guides/tools-file-search
- Assistants message annotation reference/deep dive: file citations expose
  `start_index`, `end_index`, `text`, and nested `file_citation.file_id` for
  replacement rendering:
  https://developers.openai.com/api/docs/assistants/deep-dive#message-annotations
- Citation Formatting guide: model-facing citations use `\ue200` / `\ue202` /
  `\ue201` marker delimiters and source IDs:
  https://developers.openai.com/api/docs/guides/citation-formatting

## Scope

- Add a typed `OpenAIMessageFileCitationAnnotation` schema for the
  Assistants-style replacement-span citation object.
- Export `message_annotation` beside native citation proof for Responses,
  direct vector-store search, context-pack, and retrieval-answer citations.
- Extend citation-reference helpers so the strict Responses annotation and the
  message-annotation replacement object are derived from the same marker span.
- Keep OpenAI-facing `output_text.annotations` strict:
  `type`, `index`, `file_id`, and `filename` only.

## Out of scope

- Adding Assistants API thread/message routes.
- Adding non-OpenAI fields to `output_text.annotations` or streaming
  `response.output_text.annotation.added` events.
- Changing retrieval ranking, filters, API-key behavior, vector-store routes,
  indexing, provider routing, or tenant/security policy.

## Acceptance criteria

- [x] Responses native `citations[]` entries expose `message_annotation` with
  `type`, `start_index`, `end_index`, `text`, and nested
  `file_citation.file_id`.
- [x] Direct vector-store search native citation proof exposes the same
  `message_annotation` shape.
- [x] Native context-pack and retrieval-answer citations preserve the
  message-annotation replacement span.
- [x] `/openapi.json` advertises `OpenAIMessageFileCitationAnnotation` as a
  named component and references it from native citation proof.
- [x] Strict OpenAI-facing `file_citation` annotations remain limited to
  `type`, `index`, `file_id`, and `filename`.

## Changed files

- `packages/svs_common/svs_common/openai_compat.py`
- `packages/svs_common/svs_common/retrieval.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openapi_contract.py`
- `tests/test_retrieval_profile_resolution.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-102-openai-message-citation-annotation-export.md`

## Verification

Focused citation/OpenAPI/retrieval verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py tests/test_retrieval_answer_routes.py tests/test_openapi_contract.py
```

Result: `145 passed, 2 warnings in 5.25s`.

Compile verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
```

Result: pass.

Broad non-integration verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
```

Result: `413 passed, 2 warnings in 5.95s`.

## Quality control

Acceptance criteria:

- [pass] Responses native `citations[]` entries expose the OpenAI
  message-annotation replacement shape.
- [pass] Direct vector-store search native citation proof exposes the same
  `message_annotation` shape.
- [pass] Native context-pack and retrieval-answer citations preserve the
  message-annotation replacement span.
- [pass] `/openapi.json` advertises `OpenAIMessageFileCitationAnnotation`.
- [pass] Strict OpenAI-facing `output_text.annotations` remain unchanged.
- [pass] Focused, compile, broad non-integration, and whitespace verification
  passed.

Findings:

- None.

Required fixes before next ticket:

- None.

Whitespace verification:

```powershell
git diff --check
```

Result: pass.
