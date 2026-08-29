# WAVE-123 Expert Conversation Sessions Kickoff

You are the senior dev manager for WAVE-123 in the ExAIS Vector Store repo.
Your job is to complete the full expert-conversation-session wave end to end by
managing one worker coder and one independent quality-control agent.

Repository:

```text
C:\Users\mfrie\Ai_Projects\exais_vector_store
```

Starting point:

```text
branch: main
base commit: 50cd72c Add expert conversation sessions ticket wave
primary ticket: tickets/WAVE-123-expert-conversation-sessions.md
build contract: .tranche/expert-conversation-sessions/build-contract.json
stack index: .tranche/expert-conversation-sessions/stack.index.json
```

## Mission

Build the ExAIS server-side expert layer:

```text
caller agent
  -> ask named ExAIS expert
  -> ExAIS expert plans retrieval
  -> semantic search / graph lenses / citation expansion
  -> cited answer + trace + caveats
  -> scoped session memory and feedback
```

The caller should not need to learn repeated vector-store/lens/graph/citation
tool choreography. The caller sends natural language to a named expert. ExAIS
owns the expert behavior, retrieval choices, citations, session state, memory,
feedback, tenant isolation, audit trail, and model-provider routing.

## Hard Boundary

Codex-like sessions are a product pattern, not the production runtime.

Do not make customer-facing ExAIS endpoints depend on an operator's personal
Codex, Claude Code, OpenCode, desktop agent, browser session, or subscription.
All live customer expert use must run inside ExAIS server-side code under ExAIS
API-key, tenant, and business-instance boundaries.

The LLM driver must be provider-agnostic. Route expert chat/generation through
one internal ExAIS client and model-gateway boundary. Do not call OpenAI,
Anthropic, Gemini, Groq, Ollama, Codex, Claude Code, or OpenCode SDKs directly
from API route handlers.

## Required Reading

Read these before delegating or coding:

```text
tickets/codex-agents/MAIN_ORCHESTRATOR_AGENT.md
tickets/codex-agents/TICKET_IMPLEMENTATION_AGENT.md
tickets/codex-agents/QUALITY_CONTROL_AGENT.md
tickets/WAVE-123-expert-conversation-sessions.md
.tranche/expert-conversation-sessions/build-contract.json
.tranche/expert-conversation-sessions/stack.index.json
docs/API.md
docs/CALLER_AGENT_INTEGRATION.md
docs/SECURITY.md
docs/JURISDICTION_VECTOR_STORE_PLAYBOOK.md
```

For each sub-ticket, also read every primary file named under that sub-ticket
before delegating implementation.

## Execution Rules

- Run one implementation ticket at a time unless you prove no file or behavior
  contention.
- Treat migrations/RLS, tenant isolation, API-key behavior, provider routing,
  retrieval behavior, and citation integrity as serial work.
- After every implementation ticket, run independent QC before moving on.
- Do not mark the wave complete until all T-001 through T-007 acceptance
  criteria pass and proof is recorded.
- If a worker hits product ambiguity, tenant-boundary uncertainty, provider
  selection uncertainty, or a proof-required test that cannot run, stop and
  report the blocker.
- Preserve raw vector-store search endpoints. Expert sessions are an additional
  caller primitive, not a replacement.

## Ticket Order

Use this order unless code inspection proves a better dependency chain:

1. T-001 Define Expert Profile Registry.
2. T-002 Persist Expert Sessions And Forks.
3. T-003 Add Provider-Agnostic Expert LLM Client.
4. T-004 Implement Expert Message API.
5. T-005 Wire Expert Retrieval Planner.
6. T-006 Govern Expert Memory And Feedback.
7. T-007 Document Caller MCP Contract And Evals.

Reasoning:

- T-001 defines which experts exist and which stores/lenses/models they may use.
- T-002 creates the durable state needed for resume/fork/feedback.
- T-003 gives the expert engine a swappable model driver.
- T-004 exposes the route contract.
- T-005 fills in the expert turn behavior over existing retrieval/graph code.
- T-006 locks feedback and memory safety after the flow exists.
- T-007 updates caller docs and proves quality against real store use cases.

## Worker Coder Prompt

Use this exact shape for each implementation delegation:

```text
You are running as: TICKET_IMPLEMENTATION_AGENT

Assigned ticket:
- tickets/WAVE-123-expert-conversation-sessions.md
- Sub-ticket: {T-00X title}

Must read first:
- tickets/WAVE-123-expert-conversation-sessions.md
- .tranche/expert-conversation-sessions/build-contract.json
- .tranche/expert-conversation-sessions/stack.index.json
- {all primary files listed for this sub-ticket}
- {all existing tests listed for this sub-ticket}

Scope:
- Implement only this sub-ticket.
- Respect the shared functions and anti-duplication rules in the build contract.
- Do not start later sub-tickets.
- Do not change raw vector-store search behavior unless this sub-ticket
  explicitly requires it.
- Do not weaken tenant isolation, RLS, API-key scope checks, provider routing,
  citation integrity, or output guards.

Expected proof:
- Changed files list.
- Verification commands and results.
- Acceptance checklist for this sub-ticket.
- Ticket proof notes to append under WAVE-123 if the repo convention requires
  proof notes.

Stop when:
- The sub-ticket implementation is complete and proof is recorded.
- A blocker is found.
- Acceptance criteria are ambiguous.
- Required verification cannot run.
```

## Quality Control Prompt

Run QC after each implementation sub-ticket:

```text
You are running as: QUALITY_CONTROL_AGENT

Ticket reviewed:
- tickets/WAVE-123-expert-conversation-sessions.md
- Sub-ticket: {T-00X title}

Evidence provided:
- Changed files: {worker changed files}
- Verification commands and outputs: {worker proof}
- Proof notes: {worker proof notes}

Review requirements:
- Scope matches only the assigned sub-ticket.
- Acceptance criteria are satisfied.
- Code anchors and shared functions from the build contract were respected.
- Tests or proof match the sub-ticket verification needs.
- No unrelated tenant isolation, API-key, RLS, retrieval, graph, provider,
  citation, security, deployment, Docker, or admin UI changes were introduced.
- No fake verification commands or invented results.
- Production-safety claims are backed by proof.

Return exactly one decision:
- PASS
- PASS WITH NOTES
- FAIL
- BLOCKED
```

Continue only on `PASS` or `PASS WITH NOTES`.

## Required Implementation Shape

Create these shared owners. Do not duplicate them elsewhere:

```text
packages/svs_common/svs_common/expert_profiles.py
  resolve_expert_profile(db, principal, expert_id)

packages/svs_common/svs_common/expert_sessions.py
  expert_session_key(principal, expert_id, external_user_id, conversation_id)
  fork_expert_session(db, principal, session_id, label=None)
  record_expert_retrieval_run(db, principal, session_id, payload)
  extract_candidate_memory_events(turn, policy)

packages/svs_common/svs_common/expert_llm.py
  complete_expert_chat(req)

packages/svs_common/svs_common/expert_engine.py
  run_expert_turn(db, principal, req)
```

Expected new test files:

```text
tests/test_expert_profiles.py
tests/test_expert_sessions.py
tests/test_expert_llm_client.py
tests/test_expert_messages_routes.py
tests/test_expert_corpus_eval.py
```

Expected migration:

```text
migrations/versions/003_expert_conversation_sessions.py
```

## Security Rules

- Expert memory is scoped by tenant, business instance, API key, expert, caller
  user, and session/conversation.
- Feedback is interaction evidence, not law.
- Promoted memory must be opt-in, typed, confidence-scored, deletable, and
  audit-visible.
- Expert answers may cite only retrieved corpus/source-package material.
- Memory may guide retrieval strategy or answer style, but it must not be used
  as standalone legal authority.
- Cross-scope reads must fail closed before retrieval or model calls.
- Caller-side MCP tools must remain thin HTTP adapters.

## Verification

Start with targeted tests per sub-ticket. End with Docker-first proof:

```powershell
python scripts/release/local-proof.py --cell ks-state-civics
```

If local host Python is missing modules, use the repo's Docker proof pattern
from `tickets/README.md` and existing wave tickets:

```powershell
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q
```

Also run:

```powershell
python -m compileall -f -q packages apps tests
git diff --check
```

Final proof must include:

- Unit tests for profile resolution, session/fork isolation, provider-agnostic
  fixture model behavior, expert message routes, memory/feedback governance,
  and expert evals.
- OpenAPI proof that expert routes have named request/response components.
- A caller-style example using a bearer key and
  `POST /v1/experts/{expert_id}/messages`.
- Evidence that existing raw vector-store search still works.
- Evidence that citation URLs and graph relationship metadata survive expert
  synthesis.

## Done Definition

The wave is complete only when:

- T-001 through T-007 pass implementation and independent QC.
- WAVE-123 acceptance criteria are checked off.
- Proof notes are appended to the ticket.
- The final verification suite passes or any non-run proof is explicitly
  explained.
- The working tree is clean after commit.

Recommended final commit message:

```text
Implement expert conversation sessions
```
