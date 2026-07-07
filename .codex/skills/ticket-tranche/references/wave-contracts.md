# Wave contracts and gate criteria

Detailed input/output contract per wave and the exact criteria each gate enforces. The orchestrator
in SKILL.md references this when running a wave or a gate. Artifact field shapes live in
`artifact-schemas.md`.

---

## Wave 1 — Research / North-Star  (`researcher`)

**Purpose**: collapse a vague spec or chat intent into a coherent set of base tickets under one
explicit canonical goal. This wave sets the anchor everything downstream is measured against.

**Input**: research spec file, or the intent stated in terminal chat.
**Output**: `tickets.base.json`.

**Contract**
- Produce exactly one `canonical_goal` — concrete and singular. If the request is really two goals,
  say so and recommend two tranches rather than smuggling both into one north star.
- Each ticket is independently meaningful, has a checkable `acceptance`, and names `suspected_files`
  (best guess is fine; wave 2 verifies).
- Do not enrich or verify here. No code reading, no library claims. Speed and coverage, not depth.

**Gate 1 — deterministic** (`gate_check.py --stage 1`)
- `canonical_goal` present, non-empty.
- `tickets` non-empty; unique ids; each has `title`, `goal`, `acceptance`; `suspected_files` is a list.

**Gate 1 — critic**
- Does every ticket serve the canonical goal, or has scope crept? Flag tickets that don't ladder up.
- Is the canonical goal actually singular, or a disguised multi-goal? Flag for split.

---

## Wave 2 — Enrich / Verify  (`enricher`)

**Purpose**: ground each ticket against the real codebase and against verified external knowledge,
so wave 3 meshes facts, not guesses.

**Input**: `tickets.base.json` + repository.
**Output**: `tickets.enriched.json`.

**Contract**
- Carry every base ticket forward unchanged in identity (same `id`). Drop nothing; if a ticket turns
  out invalid, keep it and mark a `flag`, don't delete it.
- For each ticket, read the associated code and attach `code_refs` (`file`+`symbol` that actually
  resolve). Replace guessed `suspected_files` with real refs where they differ.
- When consulting websearch / an expert / OSS for library behavior or patterns, record each as an
  `external_claims` entry **with a `verification`** pointer to the real signature or source you
  checked it against. An unverified claim is the most dangerous thing you can pass forward — it
  becomes a hallucinated API baked into the contract. If you cannot verify, mark `verification`
  empty and add a `flag`; do not assert it as fact.

**Gate 2 — deterministic** (`gate_check.py --stage 2 --prev tickets.base.json [--repo-root .]`)
- No base ticket id dropped.
- Each ticket has at least one `code_ref` with both `file` and `symbol`; with `--repo-root`, files exist.
- Every `external_claims[*].verification` is non-empty.

**Gate 2 — critic**
- Do the code_refs actually correspond to what the ticket claims to change, or is the grounding
  superficial? Spot-check the riskiest ticket.
- Are any "verified" claims verified against the wrong thing (e.g., a different version)? Flag.

---

## Wave 3 — Converge / Build-Contract  (`mesher`)

**Purpose**: take all enriched tickets plus the canonical goal and resolve the *shared surface area*
before any code is written — the single biggest source of worker rework is tickets colliding on the
same helpers and interfaces. Then emit the addressable index.

**Input**: `tickets.enriched.json` + `canonical_goal`.
**Output**: `build-contract.json` + `stack.index.json`.

**Contract**
- Mesh shared functions: find every method/util more than one ticket needs, assign it a single
  `owner_file` and one `signature`, and point all consumers at it. No two tickets independently
  declare the same new function.
- Write the `file_modification_map`: every file to be touched, what changes, and which ticket(s)
  drive it. Mark new files `is_new: true`.
- Write `anti_duplication_rules` in imperative form ("All X goes through Y; do not inline Z").
- Give every ticket an `expected_output` and restate the integrated `end_goal`.
- Build `stack.index.json`: `file_to_tickets` and `symbol_to_tickets`. This is not optional — it is
  what lets the worker resolve an untraced edge in one hop.
- **Do not** pre-compute exhaustive change-closures into the contract. Coupling/blast-radius is
  resolved lazily by the worker through the index, scoped to the ticket it is on. Eager closure just
  moves the context-window cost; it does not remove it.

**Gate 3 — deterministic** (`gate_check.py --stage 3 --index stack.index.json [--repo-root .]`)
- `end_goal` and non-empty `anti_duplication_rules` present.
- `file_modification_map` non-empty; every file traces to >=1 ticket; non-new files exist (with `--repo-root`).
- Each `shared_functions` name has exactly one owner and one signature (mesh integrity).
- Every ticket has `expected_output`.
- Every modified file appears in `file_to_tickets`; `symbol_to_tickets` is non-empty.

**Gate 3 — critic**
- Does the integrated `end_goal` still equal the wave-1 `canonical_goal`, or did convergence quietly
  redefine the target? This is the highest-value drift check in the pipeline.
- Are the anti-duplication rules real constraints or vague platitudes? Flag rules a worker can't act on.

---

## Re-run protocol (all gates)

On gate failure, re-spawn the failing wave's agent with its original input **plus** the gate
findings appended, instructing it to fix only what failed. Cap 2 re-runs per wave. Still failing →
halt and surface to the human with the findings. Never advance a failed artifact; never patch it in
the orchestrator.
