Decision: PASS WITH NOTES

Ticket reviewed:
- `tickets/WAVE-133-fiscal-canonical-projection-contract.md`, base `0456b74`; docs/proof follow-up only. WAVE-133 remains open.
- WAVE-134 receives only a planning note; its implementation has not started. Shared chunker edits require explicit build-contract ownership before future implementation.
- Tracker/shared map: `build-contract.json` and `stack.index.json` in this directory.

Evidence reviewed:
- Diffs in `docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md`, `instances/ks-state-civics/research/session-law-extraction-readiness.md`, and WAVE-133/134 tickets.
- New [upstream recheck proof](wave-133-upstream-locator-recheck-proof.md) and [semantic/graph metadata handoff](../../../instances/ks-state-civics/research/semantic-graph-metadata.md).
- Upstream source hashes independently matched commit `37f5b1c9`: locator `e93a8e766217b98c67761988a6ab4c2dcb52ff8054699d59a01393fe35bc46fd`, artifact service `68cfaaec6b5f633165f3a3458be8c14935bd6f2db5913e84f5dd5c740ebcf497`, fiscal service `c1fb7651deef02985b8d3dc49268a267bb2a79b36172b6ca9fff02d84839da31`.
- Static inspection confirms missing-hash, duplicate-marker and empty-selection guards, and the fiscal caller still omitting `artifact_text`.
- Reviewed the independent extraction-quality agent's real-quote/helper probe and 14 rejected controls. This QC did not rerun that upstream helper probe or the manager's gate; its independent execution was the chunker probe below.

Acceptance criteria:
- [pass] Close only the three verified upstream helper findings; preserve historical evidence and distinguish helper checks from actual persisted spans, authoritative-text retrieval, verification metadata and graph integration.
- [pass] Explain semantic/lexical retrieval plus canonical graph traversal using source revisions, exact passages, reviewed entity references and separate verification/eligibility/lifecycle metadata. Similarity does not create canonical edges or authority arithmetic.
- [pass] Keep original hash-bound Markdown unchanged; normalized search text requires an exact-source mapping. Structured KanView observations stay structured. Missing account crosswalks and canonical references remain unresolved.
- [pass] Document concrete chunker failures against real retained bytes, without representing parser output as live search or embedding results. Confirm existing mode defaults differ and require explicit effective-profile selection rather than silently switching modes.
- [pass] No production code, provider, database, index, upstream data, corpus, deployment or activation changes. Runtime tests need not be repeated for this documentation-only increment.
- [pass] Local Markdown link review covered 76 paths/heading fragments with zero missing targets; `git diff --check` passed.
- [deferred] Authoritative-text caller wiring, verification metadata/export, canonical contracts/records, source-aware chunk mapping with assigned ownership, and full WAVE-133–136 integration/acceptance.

Findings:
- No blocking documentation or scope defect.
- The measured chunking gap prevents these current parser outputs from supporting exact provision citations. The new handoff correctly makes that a concrete implementation prerequisite while keeping eligible document search conceptually independent of the full graph.
- Manager-reported 453 passed / 66 skipped and the extraction-quality agent's 14-control helper result are clearly attributed; neither establishes deployed GraphRAG acceptance.

Required fixes before next ticket:
- None before committing this docs/proof increment. Preserve the deferred implementation/ownership gates; this review does not mark WAVE-133 complete or start WAVE-134.

## Independent chunker reproduction

Executed 2026-09-10, exit 0, 0.51 seconds. Existing image, read-only worktree/corpus, no network and zero embedding requests:

```sh
docker run --rm -i --platform linux/amd64 --network none --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-law-money:/work:ro \
  -v /Users/mfrieson/Developer/statecivics-ks599-cpu-output/session-laws:/session-laws:ro \
  -w /work -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/packages/svs_common \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 python - <<'PY'
import hashlib,json,re
from pathlib import Path
from svs_common.chunking import markdown_heading_chunks,pdf_markdown_external_chunks
raw=Path('/session-laws/markdown/2025-Session-Laws-Book-2.md').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7'
text=raw.decode('utf-8');results={}
for fn in (markdown_heading_chunks,pdf_markdown_external_chunks):
 chunks=fn(text)
 results[fn.__name__]={'chunks':len(chunks),'with_page_start':sum(c.page_start is not None for c in chunks),'with_char_start':sum(c.char_start is not None for c in chunks),'lapse_passage_hits':[{'ordinal':c.ordinal,'page_start':c.page_start,'page_end':c.page_end,'line_start':c.metadata.get('line_start'),'line_end':c.metadata.get('line_end')} for c in chunks if '$4,000,000 is hereby lapsed' in c.text]}
print(json.dumps({'source_pages':len(re.findall(r'^<!-- page [0-9]+ -->$',text,re.M)),'local_chunker_probe_only':True,'embedding_requests':0,'results':results},sort_keys=True))
PY
```

Observed:

- Source: 1,072 page markers, fixed expected extraction hash matched.
- `markdown_heading_chunks`: 804 chunks, zero page/character origins; lapse hits 276/277 with unset pages and lines 1–52920.
- `pdf_markdown_external_chunks`: 739 chunks, 585 with page metadata and zero character origins; lapse hit 254 with page 214 and lines 1–52920, versus the verified actual page 358.

Static inspection of `chunking.py` confirms `page:`/`page=` marker matching, ordinary `Page N` fallback and word-rejoining oversized splits. `kansas-fiscal-document-ingest.py` sends `markdown_docs_v1`; `configs/vectorization-modes.yaml` declares OpenAI small/1536 for that mode and Voyage-4/1024 for PDF-Markdown. These are repository defaults, not proof of a live store's effective configuration.

Only this QC artifact was written by this reviewer; no code change or commit was made.
