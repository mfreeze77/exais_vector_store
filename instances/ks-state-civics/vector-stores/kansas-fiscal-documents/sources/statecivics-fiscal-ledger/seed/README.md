# StateCivics fiscal-document seed

No custody objects, exported manifests, extracted documents, runtime state, or
credentials are checked into this directory.

At runtime, mount the StateCivics custody root read-only and provide the exact
exported JSONL manifest to `scripts/release/kansas-fiscal-document-ingest.py`.
ExAIS retains Marker output through its configured object store. Operator proof
belongs under `.release/cells/ks-state-civics/kansas-fiscal-documents/`, which is
not source data and must not be committed.
