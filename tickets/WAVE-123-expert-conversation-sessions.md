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

### Post-deployment integration proof

Completed on 2026-08-28 after explicit authorization to deploy, debug, and
polish the long-running `ks-state-civics` local cell.

- Created a pre-deployment PostgreSQL/custom-format rollback bundle and prior
  image-pin/manifest snapshot under
  `.release/cells/ks-state-civics/wave123-rollback-20260828-212710`. The dump
  size is 305,932,176 bytes, its SHA-256 is
  `5AE94FFC0DEC3067663A72CC3EEA9E6EC8F93091EE451B9CA102598D9E3D596D`,
  and `pg_restore --list` validated its archive catalog.
- Applied Alembic head `003_expert_conversation_sessions`. All seven expert
  tables have RLS and FORCE RLS enabled; runtime role `svs_app` is neither
  superuser nor `BYPASSRLS`.
- Replaced the default external fallback profile with pinned
  `gpt-5.5-2026-04-23`, added native Anthropic Messages API support for
  `claude-sonnet-5`, and kept both behind the shared model-gateway contract.
  GPT-5.5 uses `max_completion_tokens`; Sonnet 5 omits its deprecated
  `temperature` parameter. Both adapters completed live authenticated probes.
- The default policy used GPT-5.5 after the unconfigured private Qwen profile.
  An isolated policy probe with OpenAI intentionally unavailable continued to
  Sonnet 5 and returned successfully. No credential value was printed or
  persisted in registry metadata.
- Live bearer calls over the cell network returned `200` for raw Kansas and
  Topeka searches, an initial Kansas expert turn, a resumed Kansas turn, and a
  Topeka expert turn. The final acceptance turns returned respectively four,
  two, and three citations, all with source URLs, using
  `gpt-5.5-2026-04-23`.
- Idempotent replay returned the identical cached expert response. A second API
  key received `404` for the first key's session, and a key without
  `retrieval:read` received `403` for expert discovery.
- Feedback PII was redacted, memory remained non-authoritative and
  non-citation-eligible, explicit promotion was applied to the resumed turn,
  deletion produced a tombstone, and a fork preserved parentage. Governance
  audit rows recorded feedback creation plus memory candidate, promotion, and
  deletion actions. All temporary acceptance keys were revoked.
- Live conversation testing exposed an exact-marker reliability failure on a
  resumed turn. The model still failed closed with `502`; remediation added a
  single bounded citation-format repair against only current retrieved
  markers, revalidation, combined usage/latency accounting, and a disclosure
  caveat. The expanded targeted regression gate passed `147 passed`.
- Final active digests after remediation are API
  `sha256:3bb1121c40d559a96b29cc3bd5a1c537807686f93a534d2a969889534c190c2b`,
  worker
  `sha256:2bceb3dae7d94fb711878747682e23f0cb2cfd3b809a1c10a55f7c411911ccbb`,
  model gateway
  `sha256:3090125bbaa38a5ea286aeadda026dd646f80d1669378a1d3e316f065581d4ab`,
  and unchanged admin UI
  `sha256:81bf557407e36eacf5bf23ee67bc03cb1957d6a91c3552b3755e848120b48dbb`.

Updated claim boundary: WAVE-123 now has live local-cell corpus, model-gateway,
GPT-5.5, Sonnet-5 fallback, bearer, session, fork, feedback, memory, citation,
and RLS evidence. External models remain denied for security levels above 3;
those requests require a configured private provider and fail closed otherwise.
Windows host-port forwarding remains unavailable on this workstation, so live
HTTP acceptance used the cell network. This is a local Docker-cell deployment,
not evidence of an external customer/VPS production rollout.

Post-remediation final verification:

- `python scripts/release/cell-access-proof.py --cell ks-state-civics` returned
  API `200` and admin UI `200` through the cell-network fallback; the Windows
  host route remained explicitly unavailable.
- `python scripts/release/local-proof.py --cell ks-state-civics` passed cell
  readiness, Docker compile, `828 passed, 7 skipped`, and the admin UI
  production build. The skips remain the explicit opt-in integration tests
  enumerated by pytest.
- Compose inspection and live container checks proved `ANTHROPIC_API_KEY` is
  present in the model gateway and blank in API and worker containers.
- Independent post-deployment QC returned `PASS WITH NOTES` after its own
  focused Docker gate (`258 passed`) and final Docker-first proof
  (`828 passed, 7 skipped`). Its only notes were the documented Windows
  host-forwarding limitation, the explicit opt-in skips covered by live-cell
  migration/RLS evidence, and the then-uncommitted working tree; no code fix was
  required.

### Referential follow-up and permanent caller-key polish

Completed on 2026-08-28 after persisted live answers showed that the first
Kansas and Topeka turns were useful and cited, but the referential continuation
`Summarize that answer...` planned retrieval from that underspecified sentence
alone and retrieved unrelated cases.

- Created active non-expiring caller key `key_ecd166f5c61e4f70bbfcef47` with
  only `retrieval:read` and `vector_stores:read`, security ceiling 3. PostgreSQL
  retains only its hash; the raw one-time value is stored outside the repository
  at `C:\Users\mfrie\.exais\keys\ks-state-civics-expert.json` with an ACL
  limited to the operator account. Authenticated expert discovery returned
  `200` with the registered Kansas and Topeka profiles.
- Referential retrieval now adds no more than four prior scoped messages and
  512 estimated tokens. Prior user messages may provide context; assistant text
  is eligible only when server-owned metadata proves positive citations,
  nonblank retrieval-run IDs, and completed or partial retrieval. Historical
  markers are stripped and the context is labeled as a search hint, not
  evidence. Current-turn retrieval remains the sole citation authority.
- Independent implementation QC initially returned `FAIL` because an early
  trigger also expanded self-contained named questions. The trigger was
  narrowed to explicit backward-reference phrases and re-QC returned `PASS`.
  Post-deployment QC then found that the phrase `the same` was still too broad;
  it returned `FAIL`, the phrase was removed, and implementation re-QC returned
  `PASS WITH NOTES`. Nine adversarial self-contained prompts now remain
  byte-for-byte unchanged through the search executor, persisted retrieval
  payload, and returned trace. Final independent post-deployment QC returned
  `PASS` after the corrected images and live positive and negative probes.
- Worker and independent-QC verification passed 18 focused referential tests,
  53 expert-message tests, and 845 non-integration tests, plus compile and diff
  checks.
- Published final immutable digests for API
  `sha256:8efad3e9f7ccb3b0251b296249e304cff910b7f0de0c013b7fa024bb64e10d3f`,
  worker
  `sha256:711d630f966b9a9835c9e080e6a9cd3a526db76fcc84b70b22c2db5c9dc6b977`,
  model gateway
  `sha256:941dd88d68808ced6931950757c5644142a9ab4ca0d2181a04f287c5b571ac19`,
  and unchanged admin UI
  `sha256:81bf557407e36eacf5bf23ee67bc03cb1957d6a91c3552b3755e848120b48dbb`.
  These four cell services are active and healthy. Instance-agent digest
  `sha256:ac20a90db03e87f7a35b364c1d15dbaaa9c7419992dd860b68d53c2e702d867d`
  was published and pinned for optional profile use; no instance-agent
  container was started.
  The prior pin and manifest snapshot is under
  `.release/cells/ks-state-civics/referential-followup-rollback-20260828-223331`.
- A fresh live two-turn call through the deployed API and the permanent key
  returned `200` twice using `openai/gpt-5.5-2026-04-23`, reused session
  `exps_527f9dcc19ed4f07a0944f27`, and cited the same exact Kansas opinion URL on
  both turns. The continuation returned the requested two-sentence Harris
  summary with current-run citations instead of the prior false-insufficiency
  response. A separate live same-session adversarial turn returned `200` and
  preserved `Does State v. Harris use the same statutory interpretation as
  State v. Smith?` byte-for-byte in its retrieval trace.
- Final Docker-first proof after deployment passed readiness
  `{"ready":true,"db":true,"qdrant":true}`, compileall, `845 passed, 7
  skipped`, and the admin UI production build with zero npm vulnerabilities.
  The skips remain the explicit opt-in PostgreSQL integration tests already
  covered by live migration/RLS evidence. Cell-network access proof returned
  `200` for both API and admin UI; Windows host-loopback forwarding remained
  unavailable and is recorded as an environment limitation.
