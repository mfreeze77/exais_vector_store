# ExAIS Expert Conversation Sessions Tranche Intent

## Goal

Design the next ExAIS Vector Store ticket wave for server-side expert
conversation sessions. Caller agents should ask a named ExAIS expert in natural
language instead of repeatedly learning low-level semantic, graph, lens, and
citation search tooling. ExAIS must own tenant isolation, sessions, memory,
retrieval, citations, audit, and provider routing. The LLM client that drives
the expert loop must be provider-agnostic.

## Product Boundary

- Customer-facing runtime must not depend on an operator's personal Codex,
  Claude Code, OpenCode, or desktop coding-agent session.
- Codex-like capabilities are desired as product patterns: session resume,
  session fork, durable tool history, feedback loops, and model comparison.
- All live expert answer generation happens inside the ExAIS server-side
  runtime under ExAIS API-key and tenant boundaries.
- The caller-side primitive should be simple:
  `POST /v1/experts/{expert_id}/messages`.
- The MCP adapter should be thin:
  `list_exais_experts`, `ask_exais_expert`, and optional
  `submit_expert_feedback`.

## Known Current Anchors

- Existing API principal, API-key, and scope resolution lives in
  `packages/svs_common/svs_common/auth.py` and `apps/api/svs_api/main.py`.
- Existing model gateway owns embeddings/rerank/token routes under
  `apps/model_gateway/svs_model_gateway/main.py`.
- Existing OpenAI-compatible Responses routes already support stored responses,
  `previous_response_id`, conversation conflict validation, and compaction.
- Existing direct vector-store search exposes graph lenses through
  `/v1/vector_stores/{vector_store_id}/search_lenses` and graph loading through
  `/v1/vector_stores/{vector_store_id}/graph`.
- Caller documentation lives in `docs/CALLER_AGENT_INTEGRATION.md` and
  `docs/API.md`.

## External Patterns To Consider

- LiteLLM: provider-agnostic gateway/model routing reference.
- OpenAI Agents SDK or Pydantic AI: typed server-side expert tool loop
  reference.
- LangGraph: thread checkpoints plus long-term store split.
- Mem0: extracted feedback/preference memory pattern.
- Graphiti/Zep: temporal episode/fact/provenance pattern.
- Dify: conversation feedback and productized chat API patterns.
- OpenCodex, Claude Code Router, OpenCode, OpenHands: reference patterns for
  provider routing, sessions, forks, subagents, tools, permissions, and resume.

## Desired Ticket Wave Output

Create the next numbered wave after `WAVE-122`. The wave should be build-ready
and include focused tickets for:

- Expert profile registry and store binding contract.
- Provider-agnostic LLM client/model policy abstraction.
- Expert session, message, tool-call, retrieval-run, feedback, memory-event,
  and fork persistence.
- Server-side expert message route with natural-language input and cited
  answer output.
- Expert retrieval planner integration with semantic search, graph lenses, and
  citation policy.
- MCP/caller contract documentation and test harness comparing raw search
  versus expert answers.

## Non-goals

- Do not add production dependence on Codex/Claude/OpenCode desktop sessions.
- Do not replace raw vector-store search endpoints.
- Do not let learned memory become authoritative law.
- Do not allow cross-tenant or cross-api-key memory.
- Do not expose Qdrant/Postgres/MinIO directly to caller agents.
- Do not implement the code in this tranche; produce the ticket wave and build
  contract only.
