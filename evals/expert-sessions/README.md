# Expert Session Comparison Eval

This eval compares repository fixtures shaped like the existing raw
`POST /v1/vector_stores/{vector_store_id}/search` response with fixtures shaped
like the named expert-session `POST /v1/experts/{expert_id}/messages` response.
It covers two Kansas court questions and two Topeka municipal-code questions.
The harness imports the shared expert-profile registry, anchors each corpus to
the registry's exported vector-store constant, and derives the unique profile
that owns that binding. The golden file does not own a parallel
corpus-to-expert map. Both raw and expert retrieval traces must use a vector
store registered to the resolved profile.

The sources and relationships are grounded in repository evidence:

- `docs/KS_STATE_CIVICS_LIVE_DEMO_OUTPUT.md` records the two State v. Harris
  source PDFs and docket `116515`;
- `docs/KS_STATE_CIVICS_GRAPH_CITATION_BACKLINKS.md` records the loaded-graph
  State v. Robinson backlink and its limited-citator caveat;
- the Topeka source-package citation maps record the official Ordinance 20340
  and Ordinance 20407 PDF URLs; and
- existing Topeka GraphRAG route tests establish the section URLs and
  `ORDINANCE_AMENDS_SECTION` relationship shape.

Run the deterministic comparison from the repository root:

```powershell
python evals/expert-sessions/run_eval.py
```

To retain the JSON proof outside the source fixture, use:

```powershell
python evals/expert-sessions/run_eval.py --output .tmp/expert-session-eval.json
```

The command checks that both paths cover non-empty expected facts, every expert
citation's combined identity-and-URL key came from a raw retrieved result,
answer markers align with typed citations, and each graph relationship record
came from that same matched raw citation. Graph-capable cases require declared
relationship expectations and actual graph evidence. Caveats must remain
present. Output intentionally preserves citation markers, source URLs, graph
relationship metadata, and caveats for inspection.

## Claim Boundary

This is deterministic, repository-backed fixture proof. It does not call a
running ExAIS cell, current vector-store corpus, model gateway, or external LLM
provider. A passing result must keep `proof_mode="deterministic_fixture"`,
`live_corpus_verified=false`, and `live_provider_verified=false`. Run a separate
authenticated live-cell eval before claiming current corpus, graph, latency, or
provider behavior.
