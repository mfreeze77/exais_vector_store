# Topeka Municipal Code Scraper

A focused Python client for scraping the public Topeka Municipal Code at `https://topeka.municipal.codes/TMC` into **clean legal text** plus **GraphRAG-ready graph files**.

It deliberately does **not** embed, vectorize, run an LLM, or require a graph database.

## Output

A successful crawl writes:

```text
output/topeka/
├── manifest.json
├── crawl_report.json
├── sections.jsonl
├── definitions.jsonl
├── nodes.jsonl
├── edges.jsonl
├── citation-url-map.jsonl
├── url-manifest.jsonl
└── expected-fetch-urls.jsonl
```

Optional `--archive-raw` also writes fetched HTML under `output/topeka/raw/`. Optional `--archive-network` writes per-page request/response metadata under `output/topeka/network/`.

### `sections.jsonl`

One record per code section. Each record contains:

- deterministic `id`
- citation and title
- exact cleaned section text
- ordered content blocks, including table text in document order
- structured tables
- linked images/attachments when present
- internal TMC references
- ordinance-history references when detectable
- source/version metadata
- SHA-256 hashes
- extracted definition node IDs

### `definitions.jsonl`

Definition records split from definition-heavy sections, with the full definition text and stable IDs. Multi-paragraph definitions are kept together.

### `nodes.jsonl` and `edges.jsonl`

Portable GraphRAG data. No vendor database format is imposed.

Node types include code hierarchy pages, sections, definitions, ordinance references, and unresolved internal reference targets.

Graph nodes and graph-edge properties preserve `source_url` and `citation_url` where available so graph expansion can return the same canonical TMC URLs as semantic search citations.

Edge types:

- `CONTAINS` — code hierarchy
- `REFERENCES` — one code location links/cites another TMC location
- `DEFINES` — section defines a term
- `HAS_ORDINANCE_HISTORY` — section history references an ordinance

### `citation-url-map.jsonl`

One row per parsed page, section, and definition. Each row includes stable identity fields plus:

- `source_url`
- `citation_url`
- `content_hash` when available
- `source_html_hash` when available

Ingestion should set ExAIS document `source_uri` from the section row's `citation_url`.

## Install

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e .
```

For development/tests:

```bash
pip install -e '.[dev]'
pytest
```

For Playwright browser fetching:

```bash
pip install -e '.[browser]'
python -m playwright install chromium
```

## Run

```bash
topeka-code-scraper --output ./output/topeka
```

Equivalent module invocation:

```bash
python -m topeka_code_scraper --output ./output/topeka
```

A conservative delay is enabled by default:

```bash
topeka-code-scraper \
  --output ./output/topeka \
  --delay 0.75 \
  --retries 4
```

Smoke-test only a few pages:

```bash
topeka-code-scraper --max-pages 10 --output ./output/smoke
```

Archive source HTML for reproducibility:

```bash
topeka-code-scraper --archive-raw --output ./output/topeka
```

Fetch through stock Playwright Chromium, archive rendered HTML, and save network proof:

```bash
topeka-code-scraper \
  --fetcher playwright \
  --archive-raw \
  --archive-network \
  --output ./output/topeka
```

This mode uses a normal isolated Chromium browser context. It does not use stealth plugins, captcha solving, proxy rotation, or challenge-circumvention code.

Import operator-owned HTML captures instead of fetching live pages:

```bash
topeka-code-scraper \
  --capture-manifest ./captures/pages.jsonl \
  --capture-root ./captures \
  --url-list ./seed/raw/topeka_municipal_code_urls.csv \
  --url-list-levels Section,Subsection \
  --manifest-only \
  --archive-raw \
  --archive-network \
  --output ./output/topeka
```

Each capture manifest row must contain a canonical TMC `url` and either inline `html` or an `html_path` relative to `--capture-root`:

```json
{"url":"https://topeka.municipal.codes/TMC/18.55.010","html_path":"html/18.55.010.html","status_code":200,"retrieved_at":"2026-08-28T00:00:00Z","source":"operator_authorized_route"}
```

This is the shim for an operator-owned authorized export, browser capture, Cloudflare Worker route, or other route. The acquisition method stays outside this repository. Captures that are challenge-only pages are rejected and recorded as failures; cookies, credentials, storage state, bypass code, proxy logic, and route secrets do not belong in Git.

## Example section record

```json
{
  "id": "ks-topeka:tmc:18.55.010",
  "jurisdiction_id": "ks-topeka",
  "code": "TMC",
  "citation": "18.55.010",
  "title": "A definitions",
  "source_url": "https://topeka.municipal.codes/TMC/18.55.010",
  "text": "...clean legal text...",
  "blocks": [
    {"order": 0, "kind": "paragraph", "text": "..."}
  ],
  "references": [
    {
      "url": "https://topeka.municipal.codes/TMC/5.135",
      "target_id": "ks-topeka:tmc:5.135",
      "text": "5.135"
    }
  ],
  "version": {
    "ordinance": "20671",
    "passed_date": "July 14, 2026"
  },
  "content_hash": "..."
}
```

## GraphRAG loading

Each JSONL line is a complete object. A graph loader only needs:

```text
node.id
node.type
node.label
node.properties

edge.source
edge.target
edge.type
edge.properties
```

The repo includes `examples/load_networkx.py` as a minimal loader. The same data can be mapped directly into Neo4j, Memgraph, FalkorDB, Kuzu, or another graph engine.

## Parser strategy

The scraper is designed around the public `municipal.codes` hierarchy rather than the authenticated eCode360 API:

1. Start at `/TMC`.
2. Follow only canonical URLs on the same host whose path remains under `/TMC`.
3. Classify pages from their primary heading (`Title`, `Division`, `Chapter`, `Article`, or section citation).
4. Strip search/navigation/footer boilerplate.
5. Stop section extraction before the current-through/disclaimer footer.
6. Preserve ordered paragraphs/list items and tables.
7. Record internal code hyperlinks as graph references.
8. Parse definitions and ordinance-history references without changing the source text.

The deterministic public IDs intentionally do not depend on ICC/eCode360 internal GUIDs.

## Operational behavior

- Default request delay: 0.75 seconds.
- Retry/backoff for 408/425/429/5xx responses.
- Same-host `/TMC` URL allowlist prevents the crawler from wandering off-site.
- Query strings and fragments are removed from canonical source URLs.
- Failures are recorded in `crawl_report.json`; one bad page does not destroy the rest of the crawl.
- A total failure that fetches zero pages exits non-zero (`2`) so cron/CI cannot mistake an empty corpus for success.
- A crawl that fetches pages but extracts zero code sections exits non-zero (`3`) unless `--allow-zero-sections` is set.
- `--max-pages` provides a safe smoke-test mode.
- `--fetcher playwright` accepts rendered code pages that contain real TMC text and section links, but fails challenge-only pages.
- `--capture-manifest` parses operator-owned HTML captures and applies the same challenge-page rejection, parser, exporter, graph, citation, and quality-gate path as live fetches.
- `citation-url-map.jsonl` is always emitted so downstream citation URLs can be audited separately from parsed text.

## Scope

This package is intentionally narrow: **scraping and clean graph-ready data only**. It does not include vector embeddings, RAG, chat, PostgreSQL, Qdrant, or Neo4j deployment code.

Review the source site's terms and your intended use before production crawling or redistribution.
