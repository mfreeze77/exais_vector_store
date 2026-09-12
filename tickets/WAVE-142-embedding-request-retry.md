# WAVE-142 Bounded Retry For The Embedding Request

Status: in progress; QC round 1 FAIL, owner decisions F1-F6 applied, awaiting QC round 2. Owner: ExAIS. Dependency: WAVE-140 (defect recorded, deliberately not fixed there).

## Why this is a new ticket, not WAVE-141

WAVE-141 is caller pacing and is complete; WAVE-140 is the rollout and is
complete, and its own scope rule forbids broadening provider code for
throughput, so it recorded this defect and isolated it rather than fixing it.
Landing new code on either would reopen a complete ticket. This is a distinct
concern — resilience, not pacing or rate limiting — so it gets its own id.

## Summary

`provider.embed()` batches one HTTP request per document and had **no retry**.
One dropped TCP connect ended the entire run. The WAVE-140 rollout needed nine
attempts and eight replays to index 28,812 documents, absorbing **five fatal
errors in 13,272 calls** of two classes: `httpx.ConnectError` (never connected,
at 19:12:27, 19:22:37, 19:31:30, 20:00:45, 20:32:02, 22:05:57 and 22:15:16) and
`httpx.ReadTimeout` (connected, no answer, at 21:43:14). A retry belongs around
the request; a supervisor restarting the process is not one.

A failed *connect* means the request never reached the provider, so retrying it
cannot double-submit. This is **not** the 429 case WAVE-141 addressed, where the
request did land and pacing was the correct answer.

## Changes

`packages/svs_common/svs_common/providers.py`

- `post_embedding_with_retry()` — retries `httpx.ConnectError`,
  `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout`, `ReadError`,
  `WriteError`, `RemoteProtocolError`, plus HTTP 429 and 5xx. Every other 4xx is
  returned to the caller untouched.
- Full-jitter exponential backoff (`uniform(0, base * 2**(n-1))`), so concurrent
  callers do not re-collide on the same schedule.
- Bounded twice: by attempt count and by a total wait budget. Exhausting either
  re-raises the original transport error, so an exhausted retry fails with the
  same exception type the caller saw before this existed.
- Each retry logs provider, attempt number, cause and the delay.

`packages/svs_common/svs_common/config.py`

- `embedding_max_attempts` (5), `embedding_retry_backoff_sec` (1.0),
  `embedding_retry_max_total_wait_sec` (60.0), following the existing
  `marker_max_attempts` / `marker_retry_backoff_sec` naming already in the file.

## Scope discipline

Applied at **one call site**, the Voyage provider, because that is the only
provider with observed failures. `providers.py` had no retry convention before
this — WAVE-131 says so explicitly and its bisection backstop is documented as
"not a retry policy". Extending retry to OpenAI, Cohere or
`GenericEndpointEmbeddingProvider` is a separate decision needing its own
evidence, not a free generalization.

The retry wraps **only** `client.post`, not the surrounding `send` closure. That
boundary is the idempotency guarantee: `send` also calls
`accumulate_embedding_usage` and parses the body, so retrying across those lines
would add the same batch's tokens more than once on a parse failure.

## Test

`tests/test_embedding_retry.py`, 7 cases, no network. Follows the WAVE-131
convention — synchronous tests driving `asyncio.run` with a fake
`httpx.AsyncClient`, no new test dependency.

Covered: transport failures then success; 429/500/502/503 retried; attempts cap
raises the original `ConnectError`; the total-wait budget stops early; a 400
reaches the caller unretried so `embed_in_order` can still bisect; 401/403/404/422
unretried; and a retried batch yields three vectors in order with usage counted
once.

Confirmed the tests catch the defect: with the call site reverted to a direct
`client.post` and the helper left in place, the idempotency test fails with
`httpx.ConnectError: all connection attempts failed` — the production failure.

Suite before: **1356 passed, 144 skipped, 31 errors**. After: **1363 passed, 144
skipped, 31 errors**. The 31 errors are pre-existing in
`test_kansas_statute_rollout.py` / `test_kansas_statute_tranches.py` and are
unchanged by this work. The +7 is derived two ways: the suite delta (1363-1356)
and running the new file alone (7 passed).

## Not done here

- No embedding job was re-run; this ticket spends nothing.
- Resume-from-checkpoint behaviour is untouched.
- Retry for the other providers, which needs its own evidence.


## Owner decisions on QC round 1, applied 2026-09-12

QC round 1 returned FAIL with six findings. All six accepted by the owner.

- **F1** — the idempotency test was vacuous. Replaced with two tests: (a) attempt 1
  raises ConnectError from `client.post`, attempt 2 succeeds, usage accumulated
  exactly once and one vector per input; (b) a 200 whose body will not parse is
  NOT retried, fails with the parse error, usage not accumulated.
- **F2** — `max_total_wait_sec` bounded only backoff sleep. Replaced by
  `embedding_retry_deadline_sec` (default 300): wall clock from the first attempt,
  covering request time as well as sleep, checked before every retry.
- **F3** — the budget aborted instead of clamping. Each sleep is now clamped to the
  remaining deadline; a backoff larger than the remainder sleeps the remainder and
  still makes the final attempt. The test that enshrined the abort is deleted.
- **F4** — exhaustion was asymmetric. Both transport and 429/5xx exhaustion now
  raise `EmbeddingRetryExhausted`, carrying the last status and body snippet and
  chaining the transport error as `__cause__`. One failure shape.
- **F5** — 429 ignored `Retry-After`. Now honoured when present and parseable, as
  seconds or an HTTP-date, clamped to the remaining deadline; otherwise backoff.
- **F6** — a retried `ReadTimeout` may double-bill upstream.

### F6 owner decision, recorded verbatim

> F6 ReadTimeout may double-bill at the vendor → retry ReadTimeout, at most 2
> timeout retries per batch, and log each at WARNING as possible_double_bill with
> batch id and token count so spend is auditable. Rationale: a dead 31k run costs
> more than one re-billed batch.

Implemented as `embedding_max_timeout_retries` (default 2), counted separately
from the attempt cap, with a `batch_id` (16 hex chars of the sha256 of the batch
text, non-secret and stable) and the estimated token count on every log line.

## F1 widening experiment — the ordered proof, and what it actually showed

The brief required proving F1(a) and F1(b) go red when the retry wraps the whole
`send` closure. **Run, and they do not both go red.** Reported rather than
presented as passing.

**Widening 1 — wrap `send`, retry the same transport errors:** both F1(a) and
F1(b) **pass**. `2 passed, 13 deselected`.

**Widening 2 — wrap `send`, retry on any `Exception` (the naive over-broad shape):**
F1(b) goes red, F1(a) still passes:

```
    def test_f1b_unparseable_200_is_not_retried_and_usage_is_not_accumulated(monkeypatch):
        client = _FakeClient([("unparseable", None), ("ok", 3)])
        _install(monkeypatch, client)
>       with pytest.raises(ValueError):
E       Failed: DID NOT RAISE <class 'ValueError'>

tests/test_embedding_retry.py:127: Failed
FAILED tests/test_embedding_retry.py::test_f1b_unparseable_200_is_not_retried_and_usage_is_not_accumulated
1 failed, 1 passed, 13 deselected in 0.33s
```

**Why F1(a) cannot discriminate, and no test can:** nothing retryable can happen
after `accumulate_embedding_usage`. In `send`, the only failure after that line is
`ordered_batch_vectors`, which raises a non-transport error. So with a
transport-only retryable set, the narrow and wide wraps are *behaviourally
identical* for usage accounting, and a test asserting "usage counted once" passes
under both by construction. F1(a) is still worth keeping as a plain regression
test — it proves usage is counted once and vectors are not duplicated — but it is
not evidence for the wrap boundary, and should not be cited as such.

F1(b) does earn its place: it catches the naive broad widening, which is the shape
that would actually double-count.

## Test

`tests/test_embedding_retry.py`, **15 cases**, no network, repo `asyncio.run`
convention. Suite before **1356 passed / 144 skipped / 31 errors**; after **1371 /
144 / 31**. The +15 derived two ways: suite delta (1371-1356) and the file alone
(15 passed). The 31 errors are pre-existing in the statute-rollout tests and
unchanged in count.
