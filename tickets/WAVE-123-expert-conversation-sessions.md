# WAVE-123 Expert Conversation Sessions

## Summary

Add a server-side ExAIS expert-conversation layer so caller agents can ask a
named vector-store expert in natural language instead of repeatedly learning
semantic search, graph lenses, citation handling, and store-specific caveats.
ExAIS remains the authority for tenant isolation, API keys, sessions, memory,
retrieval, graph use, citations, audit, and provider-agnostic LLM execution.

## Background

The current caller contract exposes strong raw retrieval primitives:
OpenAI-compatible vector-store search, Responses file-search parity, citation
guards, graph load/search lenses, and instance-scoped API keys. That works, but
it still asks the caller agent to behave like a retrieval engineer on every
turn.

The desired product shape is different:

```text
caller agent
  -> ask named ExAIS expert
  -> ExAIS expert plans retrieval
  -> semantic search / graph lenses / citation expansion
  -> cited answer + trace + caveats
  -> scoped session memory and feedback
```

This should borrow the useful parts of Codex-like workflows: session resume,
session fork, durable tool history, feedback loops, and model comparison. It
must not make the customer-facing runtime depend on an operator's personal
Codex, Claude Code, OpenCode, or desktop agent session.

The LLM client that drives the expert loop must be provider-agnostic. Expert
code should call one internal ExAIS chat/generation contract, with provider and
model selected by policy through the model-gateway boundary.

## Scope

- Add an expert profile registry that maps `expert_id` to allowed vector stores,
  system prompt, graph-lens policy, citation policy, caveat policy, tool limits,
  and model policy.
- Add server-owned expert sessions with messages, tool calls, retrieval runs,
  feedback records, memory events, and session forks.
- Add a provider-agnostic expert chat/generation client contract.
- Add caller-facing expert routes:
  - `GET /v1/experts`
  - `GET /v1/experts/{expert_id}`
  - `POST /v1/experts/{expert_id}/messages`
  - `POST /v1/experts/{expert_id}/sessions/{session_id}/fork`
  - `POST /v1/experts/{expert_id}/feedback`
- Add an expert engine that can call existing semantic search, graph-lens
  search, citation expansion, and output/citation guard paths.
- Add memory governance so caller feedback can improve future expert behavior
  without becoming authoritative law.
- Document a thin MCP/caller adapter contract:
  `list_exais_experts`, `ask_exais_expert`, and
  `submit_expert_feedback`.
- Add eval proof that compares raw search against expert-session answers for
  Kansas courts and Topeka municipal-code fixtures.

## Out Of Scope

- Replacing existing raw vector-store search endpoints.
- Making learned interaction memory a legal source.
- Cross-tenant, cross-business-instance, cross-API-key, or cross-user memory.
- Direct caller access to Qdrant, Postgres, MinIO, RunPod Marker, embedding
  providers, or model providers.
- Production dependence on an operator's personal Codex/Claude/OpenCode
  account, session, or fork.
- A separate graph database.
- A fully autonomous legal citator claim.
- Public deployment or DNS changes.

## Ticket Stack

### T-001 Define Expert Profile Registry

Create the registry contract that binds a named ExAIS expert to allowed vector
stores, prompts, graph lenses, citation policy, answer caveats, model policy,
and tool limits.

Acceptance:

- [x] Expert profiles can be listed and resolved under the request principal.
- [x] Invalid or cross-scope vector-store bindings fail closed before retrieval
  or LLM calls.
- [x] Store-supported graph lenses are discoverable through the profile without
  duplicating lens logic.

Primary files:

- `packages/svs_common/svs_common/expert_profiles.py`
- `packages/svs_common/svs_common/search_lenses.py`
- `packages/svs_common/svs_common/schemas.py`
- `apps/api/svs_api/main.py`
- `tests/test_expert_profiles.py`

### T-002 Persist Expert Sessions And Forks

Add tenant-scoped persistence for expert sessions, messages, tool calls,
retrieval runs, feedback, memory events, and forks.

Acceptance:

- [x] Sessions are keyed by principal, expert, API key, caller external user,
  and caller conversation ID.
- [x] Resume preserves prior user/assistant/tool/retrieval context.
- [x] Fork creates a new session that records parentage without mutating the
  parent.
- [x] Cross-tenant, cross-business-instance, cross-API-key, and cross-user
  session reads fail closed.

Primary files:

- `migrations/versions/003_expert_conversation_sessions.py`
- `packages/svs_common/svs_common/expert_sessions.py`
- `packages/svs_common/svs_common/auth.py`
- `tests/test_expert_sessions.py`
- `tests/test_openai_tenant_leakage_guards.py`

### T-003 Add Provider-Agnostic Expert LLM Client

Introduce one internal chat/generation client abstraction for expert reasoning.
The abstraction must support fixture-backed tests and multiple providers without
coupling expert behavior to one vendor SDK.

Acceptance:

- [x] Expert code calls one internal client contract.
- [x] Provider/model selection is profile or policy driven.
- [x] The route records provider, model, latency, token/usage metadata, and
  fallback information.
- [x] Embedding and rerank provider behavior is unchanged.
- [x] Fixture provider proves deterministic tests without live credentials.

Primary files:

- `packages/svs_common/svs_common/expert_llm.py`
- `apps/model_gateway/svs_model_gateway/main.py`
- `packages/svs_common/svs_common/model_registry.py`
- `packages/svs_common/svs_common/providers.py`
- `tests/test_expert_llm_client.py`

### T-004 Implement Expert Message API

Add the caller-facing natural-language expert request route and typed response
shape.

Acceptance:

- [x] `POST /v1/experts/{expert_id}/messages` requires bearer auth and
  `retrieval:read`.
- [x] The route returns `expert_id`, `session_id`, optional `parent_session_id`,
  answer text, citations, retrieval trace, model metadata, caveats, and
  follow-up suggestions.
- [x] OpenAPI exposes named request and response components.
- [x] Route handlers do not expose storage credentials or backend service URLs.

Primary files:

- `apps/api/svs_api/main.py`
- `packages/svs_common/svs_common/schemas.py`
- `packages/svs_common/svs_common/request_controls.py`
- `tests/test_expert_messages_routes.py`
- `tests/test_openapi_contract.py`

### T-005 Wire Expert Retrieval Planner

Create the server-side expert tool loop that turns natural language into scoped
semantic searches, graph-lens searches, citation expansion, and answer
synthesis.

Acceptance:

- [x] The expert engine can call existing vector-store search paths.
- [x] Explicit store graph lenses can be selected by the expert profile and
  natural-language request.
- [x] Every retrieval run is persisted with query, filters, lens, graph status,
  result IDs, and citation metadata.
- [x] Citation integrity and PII/secret output guards apply to expert answers.
- [x] Existing raw search behavior is unchanged when no expert route is used.

Primary files:

- `packages/svs_common/svs_common/expert_engine.py`
- `packages/svs_common/svs_common/retrieval.py`
- `packages/svs_common/svs_common/query_planner.py`
- `packages/svs_common/svs_common/search_lenses.py`
- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_expert_messages_routes.py`
- `tests/test_openai_compat_search.py`

### T-006 Govern Expert Memory And Feedback

Store caller corrections and interaction feedback in a way that can improve
future expert behavior but cannot silently become legal authority.

Acceptance:

- [x] Feedback is scoped to tenant, business instance, API key, expert, caller
  user, and session.
- [x] Promoted memory is opt-in, typed, confidence-scored, deletable, and
  audit-visible.
- [x] Memory may guide retrieval strategy or answer style, but expert answers
  may cite only retrieved corpus/source-package material.
- [x] Feedback and memory routes redact or reject obvious PII/secrets according
  to existing security policy.

Primary files:

- `packages/svs_common/svs_common/expert_sessions.py`
- `packages/svs_common/svs_common/security.py`
- `apps/api/svs_api/main.py`
- `docs/SECURITY.md`
- `tests/test_expert_sessions.py`
- `tests/test_security.py`

### T-007 Document Caller MCP Contract And Evals

Make expert sessions the recommended caller primitive while preserving raw
search for advanced callers.

Acceptance:

- [x] `docs/CALLER_AGENT_INTEGRATION.md` documents
  `list_exais_experts`, `ask_exais_expert`, and
  `submit_expert_feedback`.
- [x] `docs/JURISDICTION_VECTOR_STORE_PLAYBOOK.md` says each graph-capable
  vector store should define an optional expert profile and eval set.
- [x] Evals compare raw search versus expert-session answers on tough Kansas
  courts and Topeka municipal-code questions.
- [x] Eval output preserves citations, source URLs, graph relationship metadata,
  and caveats.

Primary files:

- `docs/CALLER_AGENT_INTEGRATION.md`
- `docs/JURISDICTION_VECTOR_STORE_PLAYBOOK.md`
- `tests/test_expert_corpus_eval.py`
- `evals/`

## Shared Functions

- `resolve_expert_profile(db, principal, expert_id)`
- `expert_session_key(principal, expert_id, external_user_id, conversation_id)`
- `fork_expert_session(db, principal, session_id, label=None)`
- `complete_expert_chat(req)`
- `run_expert_turn(db, principal, req)`
- `record_expert_retrieval_run(db, principal, session_id, payload)`
- `extract_candidate_memory_events(turn, policy)`

## Anti-Duplication Rules

- All expert profile resolution goes through
  `packages/svs_common/svs_common/expert_profiles.py`.
- All expert session, fork, feedback, and memory persistence goes through
  `packages/svs_common/svs_common/expert_sessions.py`.
- All expert chat/generation calls go through
  `packages/svs_common/svs_common/expert_llm.py` and the model-gateway boundary.
- Route handlers must not call OpenAI, Anthropic, Gemini, Groq, Ollama, Codex,
  Claude Code, OpenCode, or provider SDKs directly.
- All expert retrieval uses existing
  `retrieval.py`, `query_planner.py`, `search_lenses.py`, and
  `openai_compat.py` paths.
- Feedback and memory events are not legal sources.
- Caller-side MCP tools are thin HTTP adapters only.

## External References

- LiteLLM: <https://github.com/BerriAI/litellm>
- Pydantic AI: <https://github.com/pydantic/pydantic-ai>
- OpenAI Agents SDK: <https://github.com/openai/openai-agents-python>
- Mastra: <https://github.com/mastra-ai/mastra>
- LangGraph: <https://github.com/langchain-ai/langgraph>
- Mem0: <https://github.com/mem0ai/mem0>
- Graphiti/Zep: <https://github.com/getzep/graphiti>
- Dify: <https://github.com/langgenius/dify>
- OpenCodex: <https://github.com/lidge-jun/opencodex>
- Claude Code Router: <https://github.com/musistudio/claude-code-router>
- OpenCode: <https://github.com/anomalyco/opencode>
- OpenHands: <https://github.com/OpenHands/OpenHands>

These are references for patterns. Adopting any dependency must be a deliberate
implementation decision inside T-003 or a follow-up ticket.

## Build Contract Artifacts

Generated tranche artifacts:

- `.tranche/expert-conversation-sessions/intent.md`
- `.tranche/expert-conversation-sessions/tickets.base.json`
- `.tranche/expert-conversation-sessions/tickets.enriched.json`
- `.tranche/expert-conversation-sessions/build-contract.json`
- `.tranche/expert-conversation-sessions/stack.index.json`

## Dependencies

- WAVE-116 Instance-Scoped Caller Vector Store Lifecycle.
- WAVE-120 GraphRAG Search Lenses.
- WAVE-122 Topeka Municipal Code GraphRAG API Handler.
- Existing API-key principal and scope enforcement.
- Existing model-gateway provider routing.
- Existing citation integrity and output guard behavior.

## Verification

Planning gates:

```powershell
python .codex\skills\ticket-tranche\scripts\gate_check.py --stage 1 --artifact .tranche\expert-conversation-sessions\tickets.base.json
python .codex\skills\ticket-tranche\scripts\gate_check.py --stage 2 --artifact .tranche\expert-conversation-sessions\tickets.enriched.json --prev .tranche\expert-conversation-sessions\tickets.base.json --repo-root .
python .codex\skills\ticket-tranche\scripts\gate_check.py --stage 3 --artifact .tranche\expert-conversation-sessions\build-contract.json --index .tranche\expert-conversation-sessions\stack.index.json --repo-root .
```

Implementation proof must include:

```powershell
python scripts/release/local-proof.py --cell ks-state-civics
```

or the narrower Docker proof commands named by each implementation sub-ticket.

## Planning Proof

Completed on 2026-08-28.

- Stage 1 tranche gate: passed.
- Stage 2 tranche gate: passed.
- Stage 3 tranche gate: passed.

Subagent orchestration note: the generic subagent pool was at thread limit when
this wave was created, so the main orchestrator generated the artifacts locally
using the `ticket-tranche` contract and verified them with the deterministic
gate script.

## Implementation Proof

Completed on 2026-08-28 from `main` at base commit `50cd72c`.

Independent ticket gates:

- T-001: `PASS`. Profile listing/resolution, principal-scoped store binding,
  graph-lens discovery, OpenAPI, and documentation checks passed.
- T-002: `PASS`. Session/resume/fork isolation and FORCE RLS passed; a fresh
  disposable PostgreSQL 17 database migrated to
  `003_expert_conversation_sessions`, and the runtime-role integration test
  passed `2 passed` with no published host port.
- T-003: `PASS WITH NOTES` after malformed-success/fallback remediation.
  Provider selection, fixture completion, fallback, usage metadata, and
  embedding/rerank regressions passed. No external provider call was made.
- T-004: `PASS WITH NOTES`. Bearer/scope, typed message/fork routes,
  idempotency, failure normalization, and named OpenAPI contracts passed. The
  then-deferred retrieval implementation was completed and accepted in T-005.
- T-005: `PASS WITH NOTES` after adversarial remediation. Executor invocations,
  context tokens, result persistence, response validation, binding-local lens
  policy, graph status, citations, and raw-search regressions passed. No live
  corpus, live graph, or external provider call was made in the ticket gate.
- T-006: `PASS WITH NOTES` after adversarial remediation. Full caller scope,
  opt-in typed memory, confidence/policy gates, scrubbed deletion, audit
  metadata, PII/secret rejection before persistence, and memory/citation
  separation passed. Live PostgreSQL proof was run at final-wave scope.
- T-007: `PASS` after eval-provenance remediation. The deterministic comparison
  passed four cases (two Kansas courts and two Topeka municipal-code cases),
  with registry-authoritative expert/store bindings, combined citation
  identity/URL and same-citation graph provenance, caveats, and both
  live-verification flags set to `false`.

Final verification:

- Combined expert/API/security/raw-search target: `350 passed` with two existing
  FastAPI lifespan deprecation warnings.
- `python evals/expert-sessions/run_eval.py`: `pass`, four cases,
  `live_corpus_verified=false`, `live_provider_verified=false`.
- `python scripts/release/local-proof.py --cell ks-state-civics`: cell readiness
  `{"ready":true,"db":true,"qdrant":true}`; Docker compile passed; Python
  suite `824 passed, 7 skipped`; admin UI production build passed. The seven
  skips are explicit opt-in integration tests, not hidden failures.
- Fresh disposable PostgreSQL 17.11 proof: Alembic head
  `003_expert_conversation_sessions`; expert session/RLS integration
  `2 passed`; disposable container and network removed afterward.
- Bearer-style caller proof: an in-process HTTP
  `POST /v1/experts/kansas-court-decisions/messages` returned `200` and retained
  its session ID, citation URL, and `cited_by` graph relationship. Downstream
  retrieval/model behavior was fixture-backed for this caller-contract proof.
- Existing raw-search coverage, named OpenAPI components, citation integrity,
  output guards, and graph metadata preservation passed in the combined and
  full suites.

Claim boundary: these results prove repository behavior, Docker release proof,
and disposable PostgreSQL RLS behavior. The KS cell readiness check did not
deploy this uncommitted implementation into the long-running cell, and no live
KS corpus expert answer, live model-gateway call, or external provider call was
performed. External-provider behavior remains an explicit post-deployment
integration proof item.
