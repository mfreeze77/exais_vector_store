# Kansas Statutes source

This declares the Kansas StateCivics statute document path. The store ID is a
pending placeholder; no live store or source activation is asserted.
[Source package](sources/statecivics-statute-ledger/source.yaml) and
[source lock](sources/statecivics-statute-ledger/source.lock.json) reuse the
StateCivics document retrieval-export contract. Corpus bytes remain outside Git.

The retained harvest is ready for local preparation. See the
[full inventory and filter corrections](../../research/statute-harvest-handoff.md).
The separate [WAVE-137 implementation](../../../../tickets/WAVE-137-kansas-statute-document-ingestion.md)
adds statute-specific exact-coordinate parsing and extends the existing API runner.

## Prepare retained documents

Run these commands inside the project's container runtime with `svs_common`
available. `/statutes` and `/custody` are read-only mounts; `/proof` and `/state`
are separate writable output directories. The implementation proof records the
complete Docker invocation used against the retained corpus.

```sh
python scripts/release/kansas-statute-preflight.py \
  --manifest /statutes/manifests/statute_scrape_20260911_030653.json \
  --expected-manifest-sha256 17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2 \
  --corpus-root /statutes \
  --proof /proof/statute-preflight.json
```

Preparation verifies each retained Markdown hash, size and official URL, reconciles
exact duplicate harvest records and counts ordered unresolved history occurrences.
It preserves short substantive body regions. Empty regions and misplaced
History-only text are classified separately; byte length never decides eligibility.
Natural section/subsection boundaries retain exact source slices and document-local
line/character positions. Web-derived statutes have no invented PDF pages.
Character ranges select the exact original text; enclosing line ranges count LF
delimiters from one. Embedded carriage returns are preserved as source characters.
Body, History and annotation chunks have separate region labels so a retrieved
annotation is not presented as statutory text.

Preparation output is not a custody registration or retrieval-export record.
It supplies no canonical provision identity, resolved statute-to-bill edges,
publication permission or current-law determination. Historical metadata remains
available even when a source contributes no statute-body embedding.

## Plan an approved custody export

The [registrar handoff](registrar-handoff.md) identifies the shared upstream
services, six real source files and the first export/replay checks.

```sh
python scripts/release/kansas-fiscal-document-ingest.py \
  --source-family kansas-statutes \
  --cell ks-state-civics \
  --vector-store-slug kansas-statutes \
  --vector-store-name "Kansas Statutes" \
  --vector-store-id "$KANSAS_STATUTES_VECTOR_STORE_ID" \
  --knowledge-base-id kb_ks_civics \
  --manifest /handoff/kansas-statutes.jsonl \
  --custody-root /custody \
  --harvest-manifest /statutes/manifests/statute_scrape_20260911_030653.json \
  --harvest-manifest-sha256 17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2 \
  --harvest-root /statutes \
  --state /state/kansas-statutes.json \
  --proof /proof/statute-ingest-plan.json
```

The shared runner retains its fiscal default; the explicit family selects statute
validation and the dedicated source collection. Upstream records must target
`ks-state-civics/kansas-statutes` and agree with the retained harvest and custody
bytes. The raw harvest JSON must never be passed off as the approved export.

The statute profile requires existing `voyage_4_docs_1024` (Voyage-4, 1024
dimensions) through the normal provider/router. It does not change global or
fiscal defaults and must not silently fall back to another model. Before an
explicit apply, nonpersistent server preview must confirm the actual parser and
embedding profile. The normal API records usage and performs indexing; this
source adds no direct storage writes.

Removal/replay follows source identity, record digest, parser profile and bound
evidence context. A changed source/citation cannot silently reuse old chunk
provenance. A document newly excluded from the statute-body index must not leave
its older text searchable.

Live application requires the actual reviewed retrieval export/custody delivery
and the deployed consumer. The ticket records completed offline implementation
and independent QC; live readiness still requires an applied export and retrieval
recall proof. Migration 111's verification attestations are
independent of ordinary eligible document search; graph integration continues
under KS-600/650 and WAVE-133–136.

## Evidence versus search

Chunks preserve original text and coordinates. Section labels, official URLs,
source/extraction hashes and unresolved ordered History references are metadata.
A search hit is a candidate passage; canonical graph relationships and exact
verified legal support come from their upstream contracts and attestations.
This package leaves graph activation disabled and live recall proof pending.
