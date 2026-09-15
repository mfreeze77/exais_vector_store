# Topeka source document releases

Clean document releases published under the
[jurisdiction document release contract](../../../../../docs/JURISDICTION_DOCUMENT_RELEASE_CONTRACT.md)
(v1.0.0). StateCivics consumes these released artifacts under `ks:city:topeka`;
it does not read the ExAIS database or reconstruct documents from search chunks.

## `topeka-source-2026-09-15-r1` (starter)

Three real documents from the retained corpus, one per master collection
represented, chosen so the set demonstrates a real cross-collection link rather
than three unrelated files.

| Document | Collection | Version |
| --- | --- | --- |
| TMC 14.40.010 "Adoption of 2021 International Fire Code." | `ks:city:topeka:municipal-code` | `…:tmc:14.40.010@b4402bc01b8101bf` |
| Ordinance 20407 | `ks:city:topeka:ordinances` | `…:ordinance:20407@1c2df1f61e25ddf4` |
| Charter Ordinance 126 | `ks:city:topeka:charter-ordinances` | `…:charter-ordinance:126@f4754ab0c48657d5` |

Ordinance 20407 is the instrument the publisher's own ordinance-history row
attributes TMC 14.40.010 to, so the bundle carries both ends of one evidenced
relationship. That link publishes as `resolved: true` from the code side (the
publisher asserts it); the reverse direction, derived from citation text inside
the ordinance, publishes as `resolved: false`.

Release identity:

| Field | Value |
| --- | --- |
| `release_id` | `topeka-source-2026-09-15-r1` |
| manifest SHA-256 | `666bfa7f2f88d852f727acff984c68f1fd34894ee340649b1ee4d72ce9242faf` |
| `inventory_sha256` | `99de2e5f0fd302c2237a8a61365a75e9ccfcd5e6183d1c7698c33352263ab7b5` |
| producer commit | `51917941852d07cc1ac26f80a93149cf38777426` (clean worktree) |
| documents / files | 3 / 15 |
| validation | PASS, 0 errors, 0 warnings — [proof](proofs/topeka-source-2026-09-15-r1-validation.json) |

Retained originals (the publisher's HTML capture and both PDFs) travel inside
the bundle, so it validates end to end with no access to the seed or object
store. Full-corpus releases will reference originals by URI and hash instead
(`--reference-originals`); the manifest marks each file `present: true|false`
and the validator requires a resolvable `reference_uri` for anything absent.

## Reproduce and verify

```bash
python scripts/release/topeka-source-release-export.py \
  --select tmc:14.40.010 --select ordinance:20407 --select charter-ordinance:126 \
  --output-dir instances/ks-state-civics/vector-stores/topeka-municipal-code/releases/topeka-source-2026-09-15-r1 \
  --release-id topeka-source-2026-09-15-r1 --bundle-kind starter

python scripts/release/jurisdiction-release-validate.py \
  --bundle instances/ks-state-civics/vector-stores/topeka-municipal-code/releases/topeka-source-2026-09-15-r1
```

Re-export reproduces every content artifact and every `payload_sha256`
byte-identically; only `release.released_at` and `release.producer` move. The
export was verified both on the host and through the repository's Docker image,
which produced identical artifacts (the image has no `git`, so a Docker-run
export records `commit: unknown, dirty_worktree: true` and the validator warns —
the committed bundle here was produced on the host from a clean tree).

## Pending

- **Resolution 9749** joins this release as soon as the resolutions collector
  exists. The initial three-document handoff was not held for it.
- Vector indexing and graph readiness are `pending` on every document. Nothing
  here has been ingested through the ExAIS API, embedded, or graph-loaded.
- `coverage.state` is `partial` for all three collections. This release
  establishes the contract, not collection completeness.
- No `durable_pointers` are recorded yet: the bundle's durable location is this
  Git path. An object-store copy plus backup is assignment 4's work.
