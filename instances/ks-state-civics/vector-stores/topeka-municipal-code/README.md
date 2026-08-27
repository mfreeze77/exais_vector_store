# Topeka Municipal Code Vector Store

This vector store belongs to the `ks-state-civics` instance and is intended to hold both:

- `topeka-codified-code`: current Topeka Municipal Code sections from the codified code host.
- `topeka-ordinances`: official ordinance PDFs from the City of Topeka Document Center.

The split is deliberate. Codified sections are the best source for current-law answers. Ordinance PDFs are the best source for amendment history, adoption language, repeals, and official legislative trail.

Status: pilot seeded. The live local vector store is `vs_268b119a2cd84b568af62155`; it currently contains a one-section codified-code pilot seed, not the full Topeka Municipal Code corpus.

Citation policy:

- Codified code records set document `source_uri` from `source_url`.
- Ordinance PDF records set document `source_uri` from `pdf_url`.
- Extracted markdown/html artifacts are retained in the seed folder for reproducibility and optional caller-hosted display.

Graph policy:

- Codified-code graph data provides `CONTAINS`, `REFERENCES`, `DEFINES`, and `HAS_ORDINANCE_HISTORY` edges.
- Ordinance PDF parsing should add cross-source edges such as `ORDINANCE_AMENDS_SECTION`, `ORDINANCE_REPEALS_SECTION`, `ORDINANCE_ADOPTS_CODE`, and `SECTION_HAS_HISTORY`.

Do not treat the ordinance PDFs as a replacement for the codified code. Do not treat the codified code as enough for legal provenance without the ordinance PDFs.
