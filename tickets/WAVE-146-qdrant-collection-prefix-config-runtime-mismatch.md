# WAVE-146: instance.yaml declares a Qdrant collection prefix the runtime does not use

Status: filed 2026-09-13, not started. Owner decision required. Parent: WAVE-134.

## Summary

`instances/ks-state-civics/instance.yaml` declares
`storage.qdrant.collectionPrefix: ks_civics_`. No runtime code path reads it,
and the deployment holding this instance's points uses `svs_`. Decide which is
authoritative and make the other agree, or delete the declaration.

## Background

WAVE-134 lane B needed to name the document collections an entity projection
must never land in. Round two derived them from `instance.yaml` and produced
`ks_civics_biz_ks_state_civics_voyage_4_docs_1024` — a collection that does not
exist. The owner then measured the running fiscal cell directly.

Measured facts, each from a named source:

- **Runtime, `exais-vector-store-ks-fiscal-local-qdrant-1` (host 16333)** holds
  exactly two collections:
  `svs_biz_ks_state_civics_voyage_4_docs_1024` (83,858 points) and
  `svs_biz_ks_state_civics_openai_text_embedding_3_small_1536` (12,579 points).
- **Runtime container environment**,
  `docker inspect exais-vector-store-ks-fiscal-local-api-1`:
  `QDRANT_COLLECTION_PREFIX=svs_`, no `SVS_INDEX_VERSION`.
- **`packages/svs_common/svs_common/config.py:31`**:
  `qdrant_collection_prefix: str = 'svs_'`.
- **`scripts/release/generate-cell-env.py`** writes `QDRANT_COLLECTION_PREFIX:
  "svs_"` in both its local and production blocks.
- **`.env.example:30`** and **`.env.production.example:35`**: `svs_`.
- **`instances/ks-state-civics/instance.yaml`**: `collectionPrefix: ks_civics_`.
- **`.release/cells/ks-state-civics/.env.cell`**:
  `QDRANT_COLLECTION_PREFIX=ks_civics_` — so the *ks-state-civics* cell env
  agrees with the YAML, while the *ks-fiscal-local* cell that actually holds the
  points does not.
- **Nothing in the repository reads `collectionPrefix`.** `grep -rn
  collectionPrefix --include=*.py` returns only WAVE-134's own adapter and
  tests. Every runtime name comes from `Settings.qdrant_collection_prefix`,
  which is populated from the environment.

So this is not one cell disagreeing with itself. It is two cells — a declared
`ks-state-civics` cell and the running `ks-fiscal-local` cell — carrying the
same instance's data under different prefixes, with a YAML field that no code
consults sitting between them.

## Why this is an owner decision, not a patch

Both directions destroy something:

- Changing `instance.yaml` to `svs_` makes it agree with the running fiscal cell
  and DISAGREE with `.release/cells/ks-state-civics/.env.cell`, which is the
  production cell's own configuration.
- Changing the running cell to `ks_civics_` orphans 96,437 indexed points. They
  would have to be re-embedded to reappear under the new names, and WAVE-134's
  standing constraint is that nothing re-embeds.
- Deleting `collectionPrefix` from `instance.yaml` is the smallest change and
  loses a declaration that a reader currently believes. It is only correct if
  nothing is ever meant to read it.

## Scope

- Decide which prefix is authoritative for the `ks-state-civics` instance, and
  whether `ks-fiscal-local` is a separate deployment that legitimately differs.
- Make the surviving declarations agree, or remove the unread one.
- If `instance.yaml` is meant to be authoritative, give something the job of
  reading it — an unread declaration is a comment with a colon in it.

## Out Of Scope

- Re-embedding, re-indexing, or any move of existing points. Nothing re-embeds.
- Changing `QdrantAdapter.collection_name`.
- WAVE-134's guard, which already resolves names from the deployment settings
  and therefore does not depend on this being fixed.

## Prior Art

- **Code** — [packages/svs_common/svs_common/qdrant_adapter.py](../packages/svs_common/svs_common/qdrant_adapter.py): `collection_name` — the only place a collection name is formed.
- **Code** — [packages/svs_common/svs_common/config.py](../packages/svs_common/svs_common/config.py): `Settings.qdrant_collection_prefix`, default `svs_`.
- **Code** — [packages/svs_common/svs_common/statecivics_record_adapter.py](../packages/svs_common/svs_common/statecivics_record_adapter.py): `deployment_index_settings` — takes the prefix from settings and documents why it ignores the YAML. Shared file owner: WAVE-134.
- **Config** — [scripts/release/generate-cell-env.py](../scripts/release/generate-cell-env.py): writes the runtime value.

## Acceptance Criteria

- One authoritative source for the prefix per deployment, stated in the ticket
  log with the decision and its reason.
- No declaration in the tree that names a prefix no deployment uses.
- `tests/test_statecivics_record_adapter.py::test_the_statute_collection_is_resolved_for_the_target_deployment`
  updated if and only if the decision changes what the deployment resolves. It
  currently asserts both values and names this ticket, so it is a live record of
  the disagreement rather than a test that hides it.
- No points moved, deleted or re-embedded.

## Verification

```sh
# regime: corpus vars UNSET
pytest -q tests/test_statecivics_record_adapter.py tests/test_index_versioning.py \
         tests/test_instance_source_packages.py
```

Plus a read-only confirmation that the running cell's collection names are
unchanged.

## Risks

Acting on the YAML without reading the runtime is what produced the round-two
error this ticket exists to record. Any fix must be checked against a live
`docker inspect` of the target cell, not against the checked-in file alone.

## Rollback

Revert the declaration change. No data is touched, so there is nothing else to
undo.

## Implementation Log

Filed by WAVE-134 lane B round three, in the same commit that names it, after
the owner measured the running cell and corrected the round-two finding.
