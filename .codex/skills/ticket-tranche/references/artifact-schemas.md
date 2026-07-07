# Artifact schemas

The four artifacts that flow through the pipeline. These are the output contracts the gate enforces.
Keep them stable — the worker and the gate script both depend on these exact field names.

## `tickets.base.json`  (wave 1 output)

```json
{
  "canonical_goal": "Single concrete objective for the whole tranche. The north star.",
  "tickets": [
    {
      "id": "T-001",
      "title": "Short imperative title",
      "goal": "What this ticket accomplishes, in service of canonical_goal.",
      "acceptance": "Observable, checkable condition for 'done'.",
      "suspected_files": ["src/foo.ts", "src/bar.ts"]
    }
  ]
}
```

## `tickets.enriched.json`  (wave 2 output)

Carries every base ticket forward (same ids), adding grounding. Drops nothing.

```json
{
  "canonical_goal": "carried forward unchanged",
  "tickets": [
    {
      "id": "T-001",
      "title": "...",
      "goal": "...",
      "acceptance": "...",
      "suspected_files": ["src/foo.ts"],
      "code_refs": [
        { "file": "src/foo.ts", "symbol": "FooService.handle", "note": "current behavior" }
      ],
      "external_claims": [
        {
          "claim": "library X exposes retry(opts) with exponential backoff",
          "source": "https://... or expert/websearch",
          "verification": "checked against node_modules/x/index.d.ts:retry signature"
        }
      ],
      "patterns": [
        { "name": "circuit-breaker", "source": "https://...", "applies_to": "T-001" }
      ]
    }
  ]
}
```

Rule the gate enforces: every `external_claims[*].verification` is non-empty. An unverified claim is
flagged for re-check, never admitted silently.

## `build-contract.json`  (wave 3 output, primary)

```json
{
  "end_goal": "Restatement of canonical_goal as the integrated end state.",
  "shared_functions": [
    {
      "name": "withRetry",
      "signature": "withRetry<T>(fn: () => Promise<T>, opts: RetryOpts): Promise<T>",
      "owner_file": "src/lib/retry.ts",
      "is_new": true,
      "used_by": ["T-001", "T-004"]
    }
  ],
  "file_modification_map": [
    { "file": "src/foo.ts", "ticket_ids": ["T-001"], "is_new": false, "what": "inject withRetry around handle()" },
    { "file": "src/lib/retry.ts", "ticket_ids": ["T-001", "T-004"], "is_new": true, "what": "new shared util" }
  ],
  "anti_duplication_rules": [
    "All retry logic goes through src/lib/retry.ts:withRetry. Do not inline retry loops.",
    "Do not add a second HTTP client; extend src/lib/http.ts."
  ],
  "tickets": [
    { "id": "T-001", "expected_output": "FooService.handle wrapped in withRetry; unit test proves 3 retries on 503." }
  ]
}
```

`shared_functions` is the mesh result: each shared method has exactly one `owner_file` and one
`signature`. Two tickets needing the same new function reference the one owner — they never each
declare their own. The gate fails on multiple owners or conflicting signatures for one name.

## `stack.index.json`  (wave 3 output, addressability)

The lookup layer that makes the residual gap a one-hop query for the worker.

```json
{
  "file_to_tickets": {
    "src/foo.ts": ["T-001"],
    "src/lib/retry.ts": ["T-001", "T-004"]
  },
  "symbol_to_tickets": {
    "FooService.handle": ["T-001"],
    "withRetry": ["T-001", "T-004"]
  }
}
```

Every file in `file_modification_map` must appear in `file_to_tickets`. `symbol_to_tickets` must be
non-empty so the worker can resolve "what touches this symbol?" without crawling the repo.
