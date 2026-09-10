# StateCivics fiscal GraphRAG operator path

**Acceptance reopened after real-corpus inspection (2026-09-10).** The v1 path
below assumes PDF-backed evidence for every entity. The retained KanView corpus
shows that assumption is wrong for account/agency/fund observations, and the
current narrative chunks lack the assumed page fields. See
[the real-data correction and reproducible audit](FISCAL_GRAPH_REAL_DATA.md).
The commands below describe the implemented v1 mechanics; they are not a ready
activation path for the real State Civics fiscal graph.

The [agreed StateCivics handoff](STATECIVICS_LAW_MONEY_ALIGNMENT.md) supersedes
those design assumptions. WAVE-133/134 must consume KS-650's extension of the
existing upstream exporter, including typed structured evidence, provision
references from KS-600, and action/fact lineage through derivation records.
WAVE-135/136 must prove useful real-source paths and answers before WAVE-132's
integrated activation gate can pass. The commands below remain legacy v1
mechanics, not the corrected contract or a request to activate it.

This path activates only the Kansas StateCivics fiscal document store. It does
not enable graph expansion for other projects or stores.

The legacy adapter accepts `statecivics.fiscal-graph-publisher.v1`, a provisional
ExAIS envelope. Do not implement it as a parallel upstream contract: KS-650 owns
the second record kind in the existing StateCivics exporter, and WAVE-133/134
will adapt that output. The legacy adapter does not validate every semantic
invariant in the upstream ORM models. StateCivics does not produce this envelope. Its legacy records
must contain canonical record bodies and hashes, a completed relationship-export
run with exporter commit and input/output set hashes, explicit review/publication assertions, source revision and SourceSpan
identities, canonical locator and quote hashes, and the exact quoted text. ExAIS
checks their shape, declared canonical-body hashes, and document bindings. It
does not validate the full meaning of opaque canonical records or certify that
a human review occurred.

Build with a current chunk inventory exported from the target store. Each row
must include `chunk_id`, `content`, integer `page_start`/`page_end`,
`current: true`, `active: true`, and the
existing file identities `logical_document_id`, `source_revision_id`, and
`source_content_hash_sha256`. The initial adapter supports PDF locators with
either `page` or `page_start`/`page_end`. Every quoted span must occur exactly
once in exactly one chunk whose page bounds contain the declared span and with
the exact document/revision/hash tuple. Missing, ambiguous, stale, withdrawn,
uppercase/malformed hash, quote/span-content hash, locator hash/page, and source
mismatches fail. This position guarantee combines publisher-supplied span truth
with exact quote presence and chunk page bounds; it is not independent review
of the original source or the publisher's canonical decision.

Inputs are bounded before record scanning: at most 1,000 publisher nodes, 2,000
relationships, 5,000 chunk inventory rows, and 16 MiB per JSON input file.
Relationship `eligibility.source_refs` must be distinct and exactly equal the
SourceSpan citations emitted from `evidence_record_ids`; no reviewed source
reference is silently discarded.

```console
python scripts/release/kansas-fiscal-graphrag.py build \
  --publisher publisher.json --chunks current-chunks.json \
  --vector-store-id vs_actual --output fiscal-artifact.json
python scripts/release/kansas-fiscal-graphrag.py validate --artifact fiscal-artifact.json
python scripts/release/kansas-fiscal-graphrag.py load \
  --artifact fiscal-artifact.json --api https://cell.example --token-env SVS_OPERATOR_KEY
```

`load` is offline dry-run by default and makes no request. Review its output,
the binding report, both artifact digests, upstream evidence, and the resolved
store/profile scope. `--apply` performs the authenticated load. The token is
read only from the named environment variable and is never printed. URLs must
use HTTPS, except localhost HTTP, and cannot contain credentials, paths,
queries, or fragments. Store IDs are validated before URL construction.
Authenticated redirects are rejected, and HTTP error bodies are not printed.
Loads always stage with `replace=false`.
`fixture_only` is accepted only by offline `build --allow-fixture` and
`validate --allow-fixture`; it is rejected by load and evaluation.

Evaluate the explicit lens after an authorized load:

```console
python scripts/release/kansas-fiscal-graphrag.py evaluate \
  --artifact fiscal-artifact.json --api https://cell.example \
  --query "Trace the enacted appropriation to its supporting budget document" \
  --expected-relation-id RELATION_ID --apply
```

Evaluation sends `lens=fiscal_relationships`, the artifact's separate
`inputs.derivation_run_id`, and `relationship=all`. It passes only when every
operator-supplied expected relationship ID is returned. The run selector never
enters ordinary file filters. Before serving, the operator must bind the same
run in the fiscal store attribute and use a separate, strict fiscal profile
manifest selected by `SVS_CELL_GRAPH_PROFILE_PATH`. Disable that profile to
roll back expansion; ordinary document search remains available.

The artifact may contain only the six contract node types and five directed
relations. It never sums chunks into fiscal totals. A real activation requires
the actual reviewed publisher envelope, custody and current-source proof,
read-only store identity proof, dry-run/load/read/ACL/correction evidence, and
complete expected relationship IDs. Fixture output or open ticket status is not
publication evidence.
