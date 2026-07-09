# WAVE-025 OpenAI Output Guard Citation Redaction

## Summary

Implement the scaffolded `pii_secret_citation_guard_v1` output guard for
OpenAI-compatible vector-store search and Responses file-search output. The
guard redacts obvious PII/secret patterns from returned text while preserving
OpenAI-style citation annotations and visible `【n†source】` markers.

Repo references checked on 2026-07-08:

- `docs/TICKET_TRAIL.md`: SVS-015 Output redaction/citation guard is
  ready-to-build.
- `configs/retrieval-profiles.yaml`: `hybrid_rrf_secure_v2` declares
  `output_guard: pii_secret_citation_guard_v1`.
- `docs/planning-specs/FULL_REPO_SPEC.md`: final output should verify
  citations and redact disallowed sensitive output.
- OpenAI docs: file-search annotations appear in output text, while
  `file_search_call.results` is included only when requested.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W25-001 | Complete | Implementation/Test | Redacted sensitive text in OpenAI-compatible retrieval output without breaking citation annotations. |

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## W25-001 Acceptance Criteria

- [x] OpenAI-compatible vector-store search redacts obvious secrets and PII from
  returned text content while preserving result-level annotations, citations,
  scores, attributes, and metadata.
- [x] Responses file-search output redacts the same sensitive patterns before
  marker insertion, so annotation `index` values still point at the visible
  citation marker.
- [x] `include=["file_search_call.results"]` returns guarded result text rather
  than leaking raw sensitive snippets.
- [x] The OpenAI-core annotation object remains limited to
  `{type, index, file_id, filename}`; richer guard metadata stays outside that
  object.
- [x] Empty/no-match Responses behavior and non-sensitive retrieval output remain
  unchanged.
- [x] Focused tests cover search content redaction, Responses marker-index
  stability after redaction, included search-result redaction, and annotation
  shape preservation.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py
27 passed in 0.45s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py
49 passed in 1.45s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -q packages apps tests
exit 0

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
140 passed, 2 warnings in 4.34s

git diff --check
exit 0
```

## Notes

This ticket does not add ingestion-time PII detection, database migrations,
provider moderation calls, model generation, API-key behavior, tenant/RLS
changes, or admin UI controls.
