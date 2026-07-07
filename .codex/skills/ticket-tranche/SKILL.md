---
name: ticket-tranche
description: >-
  Turn a research spec or a feature goal into an executable, indexed ticket stack using a
  three-wave subagent pipeline (research to draft, enrich to verify, converge to build-contract),
  with a deterministic quality/drift gate between every wave. Use this whenever the user wants to
  plan a multi-ticket feature, build a ticket tranche, decompose a goal into tickets, prep a work
  plan for an autonomous worker agent, mesh shared code before a build, or mentions waves, tranches,
  ticket stacks, or build contracts -- even if they don't say the word "skill". Works in both Claude
  Code and Codex via subagent-per-wave.
---

# Ticket Tranche

Produce a build-ready, addressable ticket stack from a goal. This skill is an **orchestrator**: it
sequences three waves, dispatches one subagent per wave, and runs a hard gate between waves. The
subagents do the work; this file just conducts.

## Mental model (read once, then act)

- **Subagents are the leaves.** Each wave is one specialized subagent with clean context and a
  single responsibility. Keep them flat (depth 1). A wave agent must never spawn its own children —
  nested subagents risk exponential token/latency blowup, and the orchestration lives here, not
  inside a leaf.
- **The filesystem is the bus.** Waves hand off through artifacts on disk, never by re-passing
  payloads through the orchestrator's context. Wave N reads wave N-1's artifact, writes its own.
- **The gate is the only place correction happens.** No live nudging during a wave. After a wave
  returns, the gate validates its artifact; on failure the wave re-runs (bounded). This is why a
  clean run needs no babysitting — there is nothing to babysit between gates.
- **The point is not a perfect plan.** At any real codebase size you cannot trace every edge. The
  goal is a good plan plus an *addressable* stack so the worker resolves the residual gap in one
  lookup instead of crawling the repo. Wave 3's index is what makes that hop cheap.

## One-time setup: install the wave agents

Agent definitions are per-tool. Install the set that matches the environment:

- **Codex**: copy `agents/codex/*.toml` into `~/.codex/agents/`. Agents are referenced by name.
  Adjust the `model` line in each to a model you actually run. (Subagent TOML keys are version-
  sensitive — confirm against your Codex version's `codex/subagents` docs if a key is rejected.)
- **Claude Code**: copy `agents/claude/*.md` into `.claude/agents/` (project) or `~/.claude/agents/`
  (user). Adjust the `model:` field as desired.

Both sets carry identical instructions; only the packaging differs. The four agents are
`researcher`, `enricher`, `mesher`, and `critic`.

Pick a tranche working directory (default `./.tranche/<slug>/`). All artifacts land there.

## The pipeline

Run the three waves in order. After each wave, run the gate (next section) before proceeding.
Spawn exactly one subagent per wave. Give each agent its input artifact path and its output
artifact path explicitly — do not let it infer paths.

### Wave 1 — Research / North-Star  → `researcher`

- **Input**: the research spec (file) or the intent captured from terminal chat.
- **Spawn**: `researcher` with the intent and output path `tickets.base.json`.
- **Output**: `tickets.base.json` — a top-level `canonical_goal` (the north star for the whole
  tranche) plus base tickets, each with `id`, `title`, `goal`, `acceptance`, `suspected_files`.
- The `canonical_goal` is the anchor every later gate checks drift against. It must be concrete
  and singular, not a list of features.
- **Gate 1.**

### Wave 2 — Enrich / Verify  → `enricher`

- **Input**: `tickets.base.json` + the actual repository.
- **Spawn**: `enricher` with input `tickets.base.json`, output `tickets.enriched.json`, repo root.
- **Output**: `tickets.enriched.json` — every base ticket carried forward (no id dropped), each
  enriched with `code_refs` (real `file`+`symbol` pairs that resolve), `external_claims` (library/
  API facts and OSS patterns), and for each claim a `verification` pointer to the real signature or
  source it was checked against.
- **Why verification is mandatory**: wave 2 pulls in unverified web/expert claims. If wave 3 meshes
  a hallucinated API into the contract, a dumb worker executes the wrong plan flawlessly. Any claim
  with empty `verification` is flagged, not silently admitted — the gate rejects on unverified
  claims.
- **Gate 2.**

### Wave 3 — Converge / Build-Contract  → `mesher`

- **Input**: `tickets.enriched.json` + `canonical_goal`.
- **Spawn**: `mesher` with input `tickets.enriched.json`, outputs `build-contract.json` and
  `stack.index.json`.
- **Output**:
  - `build-contract.json` — `end_goal`; `shared_functions` (meshed: one owner per shared
    method/util, no two tickets independently declaring the same new function); `file_modification_map`
    (every file to touch, mapped to the ticket ids that touch it); `anti_duplication_rules`; and per
    ticket an `expected_output`.
  - `stack.index.json` — the addressable index: `file -> ticket_ids` and `symbol -> ticket_ids`,
    so the worker does one-hop lookup when it hits an untraced edge.
- **Do not eagerly pre-compute every change-closure into the contract** — that just relocates the
  context-window tax. The index enables the worker to compute the closure *lazily*, scoped to the
  one ticket it's on, when it actually hits an edge.
- **Gate 3.**

Output of the skill is `build-contract.json` + `stack.index.json` (plus the upstream artifacts for
audit). That is the worker's input.

## The gate (between every wave)

The gate is deterministic-first, judgment-second. Run both layers; the wave does not advance until
both pass.

1. **Deterministic layer** — run the script. It checks structure, continuity, traceability, and
   coverage — the things that are machine-verifiable and must never be left to vibes:
   ```bash
   python scripts/gate_check.py --stage <1|2|3> \
       --artifact <this wave's artifact> \
       [--prev <previous wave's artifact>] \
       [--index <stack.index.json>] \
       [--repo-root <path>]
   ```
   Nonzero exit = hard fail. It prints findings as JSON.

2. **Critic layer** — spawn the `critic` subagent on the artifact + `canonical_goal`. It judges the
   things a script can't: scope creep away from the canonical goal, semantic contradictions between
   waves, intent quietly lost. It returns `PASS` or `FAIL` with specific, actionable fixes.

**On failure**: re-run the failing wave's subagent with the critic's findings appended to its input.
Cap at 2 re-runs per wave. If it still fails, stop and surface to the human — do not advance a
broken artifact, and do not improvise a fix in the orchestrator.

Defense in depth: each wave agent also self-checks its own output against its schema before
returning. That catches malformed output cheaply inside the wave; the gate is the authoritative
cross-wave check.

## Worker handoff (downstream, out of scope here)

The worker is spawned separately and consumes `build-contract.json` + `stack.index.json`. Its one
non-negotiable reflex: when it hits an edge the contract didn't cover, **query the index first**
(symbol/file -> tickets), not the codebase. That keeps the residual gap cheap regardless of repo
size. If ground truth contradicts the contract, it halts at that boundary and kicks back rather than
improvising.

## Cost discipline

Subagent workflows cost more than single-thread runs — every child runs its own model and tool
loop. Keep depth at 1, give the cheap/fast model to `researcher` and `critic`, reserve the stronger
model for `enricher` and `mesher`. Measure rework-ratio and survived-to-commit per tranche so the
gates have to earn their token premium; if a tranche is small enough that wave 3 doesn't pay for
itself, run 2 waves.

## References

- `references/wave-contracts.md` — full per-wave input/output contract and exact gate criteria.
- `references/artifact-schemas.md` — JSON shapes for all four artifacts.
- `agents/codex/*.toml`, `agents/claude/*.md` — the four wave-agent definitions for each tool.
