# Jurisdiction Document Release Contract

Version `1.0.0`. This is the interface a consumer implements to publish ExAIS
source documents. It is jurisdiction-neutral: Topeka is the first producer, not
a variant of the schema.

- Release manifest schema: [`contracts/jurisdiction-document-release.schema.json`](../contracts/jurisdiction-document-release.schema.json)
- Document record schema: [`contracts/jurisdiction-source-document.schema.json`](../contracts/jurisdiction-source-document.schema.json)
- Shared code: [`scripts/release/jurisdiction_release_contract.py`](../scripts/release/jurisdiction_release_contract.py)
- Producer: [`scripts/release/topeka-source-release-export.py`](../scripts/release/topeka-source-release-export.py)
- Validator: [`scripts/release/jurisdiction-release-validate.py`](../scripts/release/jurisdiction-release-validate.py)
- Retained-input audit: [`scripts/release/topeka-retained-input-audit.py`](../scripts/release/topeka-retained-input-audit.py)

All of these run offline. They do not embed, do not call an ExAIS API, and do
not touch a StateCivics database, so a consumer can validate a delivered bundle
with no credentials and no ExAIS deployment.

Their only third-party dependency is `jsonschema`, already declared in every
`apps/*/requirements.txt`. Schema validation is **not** hand-rolled: an earlier
revision of this contract shipped its own draft 2020-12 evaluator, and it
accepted `true` against `const: 1` and `enum: [1]` (Python makes `True == 1`),
ignored `multipleOf` entirely, and treated `[1, 1.0]` as unique. Its
keyword-coverage guard had itself listed `multipleOf` as supported while never
implementing it — the exact failure a guard like that cannot catch. Run these
through the repository's Docker path (`Dockerfile.ci`).

## Presence semantics

Three states, and they are not interchangeable:

| State | How it is expressed | Meaning |
| --- | --- | --- |
| Required | property present and non-null | the producer must supply it |
| Known absence | `null` on a nullable property | the producer determined there is no value |
| Unknown | an explicit `"unknown"` enum member, or `availability: "unavailable"` with a `reason` | the producer does not know |

Unknown is **never** expressed by omission or by `null`. `publisher_number: null`
means "the publisher issued no number for this instrument" — the Standard Traffic
Ordinance — and is not a reason to drop the document. `status.value: "unknown"`
means no evidence of legal status was found, which is different from `"adopted"`.

## Bundle layout

```text
<bundle>/
  release-manifest.json
  documents/<source_document_id with ':' replaced by '__'>/
    record.json          the document record
    verbatim.{json,md}   untouched extractor/parser output
    normalized.{txt,md}  readable text
    structured.json      components (blocks, tables, definitions, headings)
    files/<original>     retained publisher bytes, when they travel in the bundle
```

Originals may instead be referenced by `reference_uri` + hash (`--reference-originals`).
The manifest marks each file `present: true|false`; the validator requires a
resolvable `reference_uri` for anything not present.

## Identity

| Concept | Shape | Derived from |
| --- | --- | --- |
| Jurisdiction | `ks:city:topeka` | canonical consumer mapping; legacy `ks-topeka` recorded in `aliases` |
| Collection | `ks:city:topeka:<slug>` | one registered publisher master list or category |
| Document | `<collection_id>:<type>:<publisher key>` | the publisher's own key (ordinance number, citation, or file stem) |
| Version | `<source_document_id>@<retained original sha256[:16]>` | the publisher's retained bytes |
| Component | UUIDv5 over `source_component_key` | the WAVE-119 workbench namespace, unchanged |

Identity is never derived from checkout commit, normalized text, chunk order or
row position. New publisher bytes produce a **new version of the same document**,
not a new document. Existing IDs are mapped in `identity.legacy_ids`, not replaced.

## Registered collections

Declared once in `jurisdiction_release_contract.TOPEKA_COLLECTIONS`; routing,
tests and the audit all derive from that registry rather than repeating a list.

| Collection ID | Master source | Listing category |
| --- | --- | --- |
| `ks:city:topeka:municipal-code` | `https://topeka.municipal.codes/TMC` | — |
| `ks:city:topeka:ordinances` | `https://topeka.gov/community/ordinances/index.php` | `ordinance` |
| `ks:city:topeka:charter-ordinances` | same listing | `charter_ordinance` |
| `ks:city:topeka:resolutions` | `https://topeka.gov/community/resolutions/index.php` | `resolution` |

Membership is decided by the publisher's listing category; a bare URL falls back
to the registry's host/path rules. Text inside a document never routes it — a
charter ordinance quoted inside an ordinary ordinance does not move that
ordinance. Host aliases (`s3.us-east-1.amazonaws.com/files.topeka.gov/…`) and UI
fragments (`#undefined`) canonicalise away, so they cannot mint a second document
or a second store. A URL matching no registered collection is refused rather than
given a store of its own.

## Evidence and coordinates

Each document declares its coordinate conventions explicitly. `utf8_char_offset`
is a half-open `[start, end)` range of Unicode codepoints into the named artifact.

A coordinate that was not measured is published as
`availability: "unavailable"` with a reason, and carries no locator and no quote.
**PDF page numbers are unavailable for every ordinance and charter-ordinance
document in this contract**: the retained Marker Markdown has no page boundary
markers, and Markdown line numbers are not page numbers. The validator rejects an
unavailable reference that smuggles in a coordinate anyway.

An `available` reference must resolve: the validator re-reads the artifact bytes
and requires `text[start:end] == quote`. A reference that does not resolve is a
release defect, not a warning.

## Meaning is separate from source fact

`meaning.relationships` carries `resolved: true|false` plus a `basis` and an
`evidence_ref`. A textual citation match publishes as `resolved: false`; only a
publisher-attributed link (an ordinance-history row printed on the code page)
publishes as `resolved: true`. No fuzzy join becomes authoritative by default.

`extraction_quality` (measured) and `review` (human) are distinct. Successful
extraction never implies review, adoption, legal completeness or a final outcome.

## Readiness

Seven independent stages: `acquisition`, `extraction`, `validation`, `review`,
`artifact_publication`, `vector_indexing`, `graph`. A consumer may publish a
validated document while vector and graph work is still pending, and a later
stage failing never retracts an earlier one.

## Updates

`update.outcomes` classifies every released document as `unchanged`, `new` or
`changed`, and lists documents that became `unavailable`. **Disappearance from a
publisher listing is not a repeal** — the validator rejects an `unavailable`
reason that claims one. A `changed` entry retains its `prior_version_id`.

Stale consumers are detected by comparing the held `document_version_id` against
the released one for the same `source_document_id`. `payload_sha256` excludes
volatile readiness fields, so re-exporting unchanged content reproduces the same
value and a consumer can skip re-import.

## Commands

```bash
# audit the retained inputs (offline; exit 0 only when every record reconciles)
python scripts/release/topeka-retained-input-audit.py --output <report.json>

# export a release
python scripts/release/topeka-source-release-export.py \
  --select tmc:14.40.010 --select ordinance:20407 --select charter-ordinance:126 \
  --output-dir <bundle> --release-id <id> --bundle-kind starter

# validate a delivered bundle, from anywhere
python scripts/release/jurisdiction-release-validate.py --bundle <bundle> --output <report.json>

# the whole refresh loop, wired: discover -> acquire -> destinations -> export -> validate
python scripts/release/topeka-collection-refresh.py --dry-run
python scripts/release/topeka-collection-refresh.py --execute --offline   # skips publisher stages
```

`--bundle-kind fixture` labels a demonstration bundle; `--expect-kind production`
makes the validator refuse anything that is not a durable production release.

## Compatibility with the WAVE-119 workbench projection

`structured.json` components reuse WAVE-119's `exais.workbench_component.v1`
shape and its UUIDv5 namespace, so a component minted here is the same UUID the
workbench projection mints for the same `source_component_key`.

Known gaps, not yet closed:

- WAVE-119 keys components as `ks-topeka:tmc:<citation>:marker:<label>`; this
  contract keys them as `<source_document_id>:block:<ordinal>`. The same section
  therefore yields different component UUIDs under the two schemes. A consumer
  needing both must map through `source_component_key`, which both record.
- WAVE-119 projects the full code hierarchy (code → title → chapter → section)
  from `url-manifest.jsonl`. This contract projects a single document's subtree
  and does not emit ancestor components.
- WAVE-119 emits `slices.jsonl` and `component-relations.jsonl`. This contract
  carries relations as `meaning.relationships` on the document instead, because
  they must travel with their evidence.

## What this contract does not establish

- Collection completeness. `collections[].coverage.state` is `partial` until a
  discovery pass supplies a `discovered_count` to reconcile against; the
  validator rejects a `complete` claim without one.
- Vector or graph availability. Both are reported per document as readiness
  stages, and are `pending` in any release that has not been ingested.
- Legal effect. Extracted text is source content, not a reviewed legal fact.
