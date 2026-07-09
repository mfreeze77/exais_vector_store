# WAVE-056 Context Pack OpenAI Citation Markers

## Goal

Make native context-pack output mimic OpenAI file-search citation text more
closely by adding visible `【n†source】` markers to the returned context string
and setting each context citation annotation index to the marker offset.

## References

- OpenAI file-search guide: Responses file search exposes annotations in output
  text, and raw file-search results are included only when requested.
- OpenAI Responses reference: `output_text.annotations` file citations use the
  core fields `type`, `index`, `file_id`, and `filename`.
- Assistants annotation guidance: file-search annotations correspond to visible
  generated source-marker substrings such as `【13†source】`.

## Scope

- Update native `/api/v1/retrieval/context-pack` assembly only.
- Preserve existing context-pack chunk ordering, expansion, token trimming, ACL
  behavior, and relation metadata.
- Preserve OpenAI Responses and vector-store search citation shapes.
- Keep OpenAI-facing annotation objects strict: `type`, `index`, `file_id`,
  `filename`.

## Acceptance Criteria

- [x] Each included context chunk appends a visible OpenAI-style marker such as
  `【1†source】` to the returned `context` string.
- [x] Each `citations[].annotation.index` points to the exact marker offset in
  the returned `context` string.
- [x] Context citations expose the marker alongside the existing native citation
  metadata so downstream answer generation can preserve the marker.
- [x] Parent/neighbor expansion and context token trimming still return
  citations only for included chunks.
- [x] Existing Responses and direct vector-store search citation tests remain
  unchanged.

## Verification

- Focused retrieval/context-pack tests.
- Focused OpenAI compatibility citation tests.
- Full non-integration test suite.
- `python -m compileall -f -q packages apps tests`.
- `git diff --check`.

## Proof

Focused citation/context-pack verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
121 passed, 2 warnings
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Full non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
265 passed, 2 warnings
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.
- This ticket does not change OpenAI Responses or direct vector-store search
  citation shapes.
