# Topeka Municipal Code Vector Store

This vector store belongs to the `ks-state-civics` instance and is intended to hold both:

- `topeka-codified-code`: current Topeka Municipal Code sections from the codified code host.
- `topeka-ordinances`: official ordinance PDFs from the City of Topeka Document Center.

The split is deliberate. Codified sections are the best source for current-law answers. Ordinance PDFs are the best source for amendment history, adoption language, repeals, and official legislative trail.

Status: full codified-code corpus and official ordinance PDF corpus seeded locally. The caller-facing local vector store is `vs_d4185d1004604f08a55299fa` (`City of Topeka Municipal Code`) for the `https://topks.statecivics.ai/local` surface.

Local proof from 2026-08-28:

- `2,702` codified-code section documents.
- `364` official ordinance PDF documents with retained Markdown extractions.
- `3,066` total documents.
- `3,066` distinct official source URLs.
- `6,153` active chunks.
- `6,153` indexed chunks.
- `10/10` Topeka recall checks passed with public citations.
- `5/5` ordinance PDF recall checks passed with official PDF citations.
- `24` deeper Topeka API searches completed with zero API errors after search hardening. `19` passed the basic citation/content gate; `5` were marked for review because broad phrasing needed tighter legal-query terms or caller-side answer framing.
- Topeka graph load/search is locally verified through the ExAIS API: `4,969`
  graph nodes, `10,167` graph edges, and explicit
  `municipal_code_structure`, `municipal_code_cross_reference`, and
  `municipal_code_history` searches return graph-expanded cited chunks.

The previous pilot store, `vs_268b119a2cd84b568af62155`, contains partial data and should not be used as the full Topeka caller-facing store.

Caller-route status:

- ExAIS API search is locally verified against the clean store.
- `https://topks.statecivics.ai/local` is recorded as the intended consumer surface, but the public caller route itself is not yet wired or DNS-verified from this machine.
- Caller agents should ask legal-search-style queries with section names, exact code terms, ordinance numbers, and known chapter identifiers when available. Broad consumer phrasing can return related sections that are not the best legal answer.

Citation policy:

- Codified code records set document `source_uri` from `source_url`.
- Ordinance PDF records set document `source_uri` from `pdf_url`.
- Extracted markdown/html artifacts are retained in the seed folder for reproducibility and optional caller-hosted display.

Graph policy:

- Aggregate graph artifact proof currently provides `CONTAINS`, `REFERENCES`, `DEFINES`, `HAS_ORDINANCE_HISTORY`, `ORDINANCE_AMENDS_SECTION`, and `SAME_ORDINANCE` edges with citation URLs.
- Ordinance PDF semantic search and Topeka municipal-code graph lenses are live
  locally in the KS Civics Docker cell.
- The Kansas court-decision query planner is intentionally disabled for this store so ordinance numbers and municipal-code dates are not misread as court docket/date filters.

Do not treat the ordinance PDFs as a replacement for the codified code. Do not treat the codified code as enough for legal provenance without the ordinance PDFs.
