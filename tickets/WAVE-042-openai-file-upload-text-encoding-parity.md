# WAVE-042 OpenAI File Upload Text Encoding Parity

## Summary

Expand OpenAI-compatible `/v1/files` text upload decoding from UTF-8-only to the
current OpenAI-supported text encodings: UTF-8, UTF-16, and ASCII.

## Background

Official OpenAI reference checked on 2026-07-08:

- The file-search guide's supported-files section says `text/` MIME type
  encodings must be one of `utf-8`, `utf-16`, or `ascii`.

ExAIS currently decodes non-PDF `/v1/files` uploads as UTF-8 only and returns
415 for other text encodings. That unnecessarily rejects UTF-16 text files that
OpenAI-compatible clients may upload for vector-store file search.

## Scope

- Add a small upload decoding helper for OpenAI-compatible text uploads.
- Accept UTF-8, UTF-8 with BOM, ASCII, and UTF-16 text bytes.
- Keep PDF routing through the existing Marker path.
- Keep binary or unsupported encodings fail-closed with HTTP 415.
- Update docs from UTF-8-only to UTF-8/UTF-16/ASCII text support.
- Add focused tests for helper behavior and `/v1/files` route wiring.

## Code Anchors

- `apps/api/svs_api/main.py`
- `tests/test_openai_files.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `tickets/WAVE-016-openai-files-upload-parity.md`

## Out Of Scope

- Adding new binary parsers.
- Changing native `/api/v1/documents/upload` decode behavior.
- Changing PDF/Marker conversion behavior.
- New database migrations, provider routing, API key behavior, tenant isolation
  behavior, deployment work, or admin UI work.

## Acceptance Criteria

- [x] `/v1/files` accepts UTF-16 text uploads and ingests decoded text.
- [x] UTF-8, UTF-8 BOM, and ASCII text uploads remain accepted.
- [x] Unsupported binary bytes still fail with HTTP 415.
- [x] Error messages and docs describe UTF-8, UTF-16, ASCII text support plus
  configured PDF conversion.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py
15 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
217 passed, 2 warnings

git diff --check
pass
```
