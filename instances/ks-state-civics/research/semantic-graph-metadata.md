# Semantic passages and the law-and-money graph

Reviewed 2026-09-10 against ExAIS `0456b74`. This is an implementation handoff,
not a claim that the retained Session Laws have been indexed or graph-connected.

## Intended retrieval

Index eligible retained Markdown for ordinary semantic and lexical retrieval.
The complete graph and full K.S.A. harvest are not prerequisites for document
search. New source records still need the existing custody, extraction and
publication checks; document eligibility and verified provision-level evidence
are separate requirements. Extend the existing source packages and ingestion,
preserving actual CPU-extraction provenance and separate statute/source policies.

For a question such as “What happened to supplemental state aid in FY2026?”:

1. Semantic/lexical search finds relevant legal clauses and budget explanations.
2. Returned source revisions and exact locators identify the retained passages;
   reviewed span-to-entity bindings connect the precise supporting evidence to
   graph entities. A surrounding chunk is retrieval context, not the legal span.
3. Typed graph traversal retrieves legal actions, their fiscal values/context,
   agency/fund/account relationships and supporting evidence. Exact identifiers
   can also initiate traversal, followed by supporting document search.
4. The answer checks values against canonical records and verified evidence,
   cites the source, and preserves unresolved links. The literal legal account
   `652-00-1000-0840` remains unresolved until a reviewed composite crosswalk exists.

WAVE-135 owns combined retrieval; adding tags alone does not make an agent call
both paths. Similarity generates candidates, not confirmed edges or authority
arithmetic. Entity descriptions may also be embedded under WAVE-134, separately
from document chunks; the KanView CSV observations remain structured records.

The [completed K.S.A. inventory](statute-harvest-handoff.md) now verifies 31,079
retained Markdown files. A 400-byte cutoff would discard real short provisions
and keep some metadata-only documents; do not use it as an embedding filter.
Statutes need their own source policy and section/subsection coordinate path:
they have no PDF page markers and cannot use the fiscal-only page profile.
History counts must distinguish 72,753 raw manifest occurrences from 72,733 after
deduplicating the six repeated document groups. All remain unresolved.

## Metadata to retain and return

These are semantic requirements, not a new upstream schema. Reuse actual source,
span, provision, derivation, publication and snapshot contracts/IDs.

| Level | Metadata | Purpose |
|---|---|---|
| Source/document | Existing logical document and source revision IDs, raw PDF and derived text hashes, official URL, source family, jurisdiction, publication date | Identify exactly which retained source a hit represents. |
| Passage | Source/extraction revision, PDF page(s), printed-page label when known, exact page-local lines/offsets with convention, selected-text hash, supported section/subsection labels | Resolve a passage back to unchanged evidence. Search chunk identity is not a provision ID. |
| Canonical links | Reviewed exact span-to-provision/action bindings, plus actual bill/version and agency/fund/account references where delivered | Connect specific evidence to graph records. A containing chunk may overlap several spans; a reference cannot imply its whole text supports one action. Missing bindings stay absent/unresolved. |
| Time and context | Supported legislative session, fiscal year(s), effective/as-of dates; action type and fiscal stage/metric on their owning records | Separate authority, lapse, proposed budget, observed spending and historical versions. Do not stamp every passage in a multi-year book with one fiscal year or action. |
| Verification and eligibility | Bound locator-verification result/derivation; distinct publication, resolution and lifecycle state | Explain what was checked and prevent withdrawn/stale evidence from remaining usable. Verification does not itself grant publication. |
| Search representation | Chunker/search-normalization version, original text range mapping, embedding profile/model/dimensions and indexed-text hash | Rebuild and query the right index while preserving exact evidence. |

The ingestion API already accepts `source_identity` and document `attributes`.
`kansas-fiscal-document-ingest.py:_record_attributes` already sends source
revision/hash, export identity/digest, citation URL, jurisdiction, artifact type
and exporter identity. Preserve these; do not create duplicate ownership fields.
Document-level metadata is not automatically precise passage metadata. Verify
the complete upload → chunk → search-result → citation path and retain native
typed graph references rather than squeezing a relationship graph into flat
file attributes.

Do not add frontmatter or synthetic tags to the hash-bound original Markdown.
Keep metadata alongside the source. A separately versioned search representation
may normalize whitespace and line-break hyphenation, provided each result maps
back to exact original text and offsets. Embed useful wording and sourced labels;
UUIDs and hashes primarily support joins, integrity and filtering.

The manager's current-cell inventory reports 13,181 chunks with no populated
page or character columns. The existing `ParsedChunk`/database fields already
represent those coordinates; no new locator columns are needed. The first
implementation increment therefore fills them through ingestion. This reported
inventory is not an independent ExAIS database query, and an offline parser
fix does not backfill those live rows by itself.

Tier 3 follows reviewed span-to-action bindings. Section 96(j)'s 314-character
clause and the neighboring section 96(i) can fit in one retrieval chunk. Resolve
and verify the specific span before citing an action; never choose a canonical
reference from a label such as “supplemental state aid.” Overlap with a reviewed
span is a way to locate candidate evidence, not proof of a new relationship.

## Measured ingestion gap before a bulk run

The measurements below describe the default chunkers at `0456b74`; those
defaults remain unchanged. The later bounded WAVE-134 increment adds an explicit
`statecivics_page_markdown_v1` opt-in to populate the existing coordinate columns
and exact retrieval metadata, preserving model selection. See the
[coordinate implementation proof](../../../.tranche/statecivics-semantic-graph/aligned/wave-134-document-coordinate-proof.md)
and [operator workflow](../../../docs/FISCAL_GRAPH_OPERATOR.md#retained-markdown-ingestion-with-coordinates).
This does not mean the live chunk rows have been re-ingested.

`kansas-fiscal-document-ingest.py` currently sends retained text using
`markdown_docs_v1`. Its generic heading chunker does not preserve the CPU
extractor's `<!-- page N -->` coordinates. Simply switching to the existing
PDF-Markdown mode also fails: its marker regex expects `page:` or `page=`, and
its fallback can mistake ordinary `Page N` text for a page marker.

Root executed both chunkers on the actual retained Book 2, SHA-256
`3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7`,
with 1,072 page markers:

| Existing chunker | Chunks | Observed $4M lapse passage metadata |
|---|---:|---|
| `markdown_heading_chunks` | 804 | Two overlapping hits, ordinals 276/277; page unset, line range 1–52920. |
| `pdf_markdown_external_chunks` | 739 | Hit ordinal 254; page **214**, line range 1–52920, although the verified clause is on PDF page **358**. |

These are local parser results, not live search results. Neither path supplies
character origins for these chunks. Existing oversized splitting rejoins words,
so its text must not masquerade as an exact retained quotation.

Reproduction (existing image, read-only mounts, zero provider requests):

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

Observed exit 0 in 0.52 seconds. No files, database or indexes were mutated.

Before bulk embedding, WAVE-134 must route these sources through bounded
page/section-aware chunking with exact original-coordinate mapping. Parse page
boundaries before splitting and retain multi-page/multi-section coverage where
a chunk spans them. Verify the complete real clause and its neighboring lapse,
then correction/replay behavior. A standalone span verifier does not repair an
ingestion chunker's output.

Also inspect the actual ingestion plan's embedding profile: repository defaults
differ (`markdown_docs_v1` declares OpenAI small/1536; PDF-Markdown declares
Voyage-4/1024). Select the agreed source/store profile explicitly and encode
queries compatibly. Graph joins use canonical IDs and do not require equal
embedding dimensions across source stores. This review makes no model switch,
provider request or bulk ingestion claim.
