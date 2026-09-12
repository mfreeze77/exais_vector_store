"""WAVE-142: bounded retry around the Voyage embedding request.

No network. A fake async client plays a scripted sequence and records every
request. Follows the WAVE-131 convention in
`tests/test_embedding_request_batching.py`: synchronous tests driving
`asyncio.run`, a fake `httpx.AsyncClient`, no pytest-asyncio.

Motivating failure: one dropped TCP connect ended a 31,000-document run
(WAVE-140 - nine attempts, eight replays, five fatal errors in 13,272 calls
across httpx.ConnectError and httpx.ReadTimeout).
"""
from __future__ import annotations

import asyncio
import copy

import httpx
import pytest

from svs_common import providers as providers_mod
from svs_common.providers import (
    EmbeddingRetryExhausted,
    VoyageEmbeddingProvider,
    post_embedding_with_retry,
)

URL = "https://api.voyageai.com/v1/embeddings"


class _FakeResponse:
    def __init__(self, status_code: int, body, *, headers=None, raw_text=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self._raw_text = raw_text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(str(self.status_code), request=None, response=None)

    def json(self):
        if self._raw_text is not None:
            # a 200 whose body is not JSON: this is the parse failure path
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._body

    @property
    def text(self):
        import json as _json
        return self._raw_text if self._raw_text is not None else _json.dumps(self._body)


def _vectors(n: int, tokens: int = 7) -> dict:
    return {"data": [{"embedding": [0.1, 0.2], "index": i} for i in range(n)],
            "usage": {"total_tokens": tokens}}


class _FakeClient:
    """Plays outcomes in order. Raises when the script runs out, so an
    over-retrying regression fails loudly instead of silently returning 200."""

    def __init__(self, outcomes, *, timeout=None, **_):
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers=None, json=None):
        # R-B6: a DEEP COPY. Recording the reference made the replay-identity
        # assertion compare one dict with itself, so it stayed true even after
        # in-place mutation between attempts.
        self.requests.append({"url": url, "headers": headers,
                              "json": copy.deepcopy(json)})
        if not self.outcomes:
            raise AssertionError(
                f"unscripted request #{len(self.requests)} - more retries than the test expected")
        kind, value = self.outcomes.pop(0)
        if kind == "raise":
            raise value
        if kind == "status":
            code, hdrs = value if isinstance(value, tuple) else (value, {})
            return _FakeResponse(code, {"error": "boom"}, headers=hdrs)
        if kind == "unparseable":
            return _FakeResponse(200, None, raw_text="<html>gateway</html>")
        return _FakeResponse(200, _vectors(value))


async def _never_sleep(_d: float) -> None:
    return None


def _call(client, **kw):
    kw.setdefault("sleep", _never_sleep)
    kw.setdefault("jitter", lambda ceiling: ceiling)
    return asyncio.run(post_embedding_with_retry(
        client, URL, headers={}, json_payload={"input": ["x"]}, provider="voyage", **kw))


def _install(monkeypatch, client):
    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", lambda **kw: client)
    monkeypatch.setattr(providers_mod.asyncio, "sleep", _never_sleep)


# === F1(a): transport failure then success — usage counted exactly once =======

def test_retried_batch_counts_usage_once_returns_one_vector_per_input_and_replays_identically(monkeypatch):
    """R-B3: renamed. This does NOT prove where the retry wrap sits.

    The wrap-widening proof was withdrawn by the owner as structurally impossible:
    nothing retryable can occur after accumulate_embedding_usage, so wrapping
    `post` and wrapping `send` are indistinguishable for this error class. Both
    experiment outcomes stay pasted in WAVE-142 as the record of why.
    """
    client = _FakeClient([
        ("raise", httpx.ConnectError("all connection attempts failed")),
        ("ok", 3),
    ])
    _install(monkeypatch, client)
    result = asyncio.run(VoyageEmbeddingProvider(api_key="k").embed(
        ["a", "b", "c"], model="voyage-4", dimensions=2))
    assert len(client.requests) == 2
    assert len(result.data) == 3
    assert [d.index for d in result.data] == [0, 1, 2]
    assert result.usage.get("total_tokens") == 7, "usage accumulated once, not twice"
    # the retry must replay the identical batch, not a mutated one
    assert client.requests[0]["json"] == client.requests[1]["json"]


# === F1(b): a 200 whose body will not parse is NOT retried ===================

def test_f1b_unparseable_200_is_not_retried_and_usage_is_not_accumulated(monkeypatch):
    seen: list[dict] = []
    real_accumulate = providers_mod.accumulate_embedding_usage

    def _spy(usage, payload):
        seen.append(payload)
        return real_accumulate(usage, payload)

    monkeypatch.setattr(providers_mod, "accumulate_embedding_usage", _spy)
    client = _FakeClient([("unparseable", None), ("ok", 3)])
    _install(monkeypatch, client)
    with pytest.raises(ValueError):
        asyncio.run(VoyageEmbeddingProvider(api_key="k").embed(
            ["a", "b", "c"], model="voyage-4", dimensions=2))
    assert len(client.requests) == 1, "a parse failure is not a transport failure; no retry"
    # R-B3: the clause this test is named for, now actually asserted
    assert seen == [], "usage must not be accumulated when the body never parsed"


# === F2/F3: wall-clock deadline, clamped rather than abandoned ===============

def test_f2_deadline_counts_request_time_not_just_sleep():
    """The clock advances inside post, so the deadline trips on request time alone."""
    ticks = {"t": 0.0}

    class _SlowClient(_FakeClient):
        async def post(self, url, *, headers=None, json=None):
            ticks["t"] += 40.0          # each request burns 40s of wall clock
            return await super().post(url, headers=headers, json=json)

    client = _SlowClient([("raise", httpx.ConnectError("x"))] * 6)
    with pytest.raises(EmbeddingRetryExhausted):
        _call(client, max_attempts=6, backoff_sec=0.0, deadline_sec=100.0,
              clock=lambda: ticks["t"])
    assert len(client.requests) == 3, "40+40+40 > 100s deadline, stops on the third"


def test_f3_backoff_larger_than_remaining_deadline_is_clamped_not_abandoned():
    slept: list[float] = []

    async def _record(d):
        slept.append(d)

    client = _FakeClient([("raise", httpx.ConnectError("x")), ("ok", 1)])
    resp = _call(client, max_attempts=3, backoff_sec=100.0, deadline_sec=5.0,
                 sleep=_record, clock=lambda: 0.0)
    assert resp.status_code == 200, "the final attempt still happens"
    assert slept == [5.0], "slept the remainder instead of giving up"


# === F4: one failure shape for transport and status exhaustion ==============

def test_f4_transport_exhaustion_raises_embedding_retry_exhausted():
    client = _FakeClient([("raise", httpx.ConnectError("all connection attempts failed"))] * 4)
    with pytest.raises(EmbeddingRetryExhausted) as err:
        _call(client, max_attempts=4)
    assert len(client.requests) == 4
    assert isinstance(err.value.__cause__, httpx.ConnectError)
    assert err.value.status_code is None


def test_f4_status_exhaustion_raises_the_same_type_with_status_and_body():
    client = _FakeClient([("status", 503)] * 4)
    with pytest.raises(EmbeddingRetryExhausted) as err:
        _call(client, max_attempts=4)
    assert len(client.requests) == 4
    assert err.value.status_code == 503
    assert "boom" in (err.value.body_snippet or ""), "carries a body snippet"


# === F5: Retry-After wins over computed backoff ==============================

def test_f5_retry_after_seconds_is_honoured_instead_of_backoff():
    slept: list[float] = []

    async def _record(d):
        slept.append(d)

    client = _FakeClient([("status", (429, {"Retry-After": "2"})), ("ok", 1)])
    resp = _call(client, max_attempts=3, backoff_sec=30.0, deadline_sec=600.0,
                 sleep=_record, clock=lambda: 0.0)
    assert resp.status_code == 200
    assert slept == [2.0], "Retry-After 2 sleeps 2, not the 30s backoff"


def test_rb1_http_date_is_measured_against_the_wall_clock_not_the_monotonic_one():
    """R-B1. The monotonic clock is pinned far from the epoch on purpose: the
    round-2 test passed only because clock=0.0 coincided with the Unix epoch."""
    from email.utils import formatdate
    slept: list[float] = []

    async def _record(d):
        slept.append(d)

    wall = 1_700_000_000.0          # a realistic epoch
    mono = 633_122.0                # a realistic monotonic, nowhere near it
    client = _FakeClient([("status", (429, {"Retry-After": formatdate(wall + 2, usegmt=True)})),
                          ("ok", 1)])
    resp = _call(client, max_attempts=3, backoff_sec=30.0, deadline_sec=600.0,
                 sleep=_record, clock=lambda: mono, wall_clock=lambda: wall)
    assert resp.status_code == 200
    assert slept == [2.0], f"a date 2s ahead must sleep 2s, got {slept}"


def test_rb1_http_date_in_the_past_sleeps_zero():
    from email.utils import formatdate
    slept: list[float] = []

    async def _record(d):
        slept.append(d)

    # R-B11: the wall clock is pinned in the year 2100 and the date is 60s BEFORE
    # it - so the date is in the REAL future. An implementation ignoring the
    # injected clock would compute a large positive sleep and fail here.
    wall = 4_102_444_800.0            # 2100-01-01
    client = _FakeClient([("status", (429, {"Retry-After": formatdate(wall - 60, usegmt=True)})),
                          ("ok", 1)])
    _call(client, max_attempts=3, backoff_sec=30.0, deadline_sec=600.0,
          sleep=_record, clock=lambda: 633_122.0, wall_clock=lambda: wall)
    assert slept == [0.0], f"a date already past on the INJECTED clock means do not wait: {slept}"


def test_rb2_retry_after_longer_than_the_remaining_deadline_does_not_retry():
    """R-B2: clamping would retry inside a window the server explicitly closed."""
    client = _FakeClient([("status", (429, {"Retry-After": "600"}))])
    with pytest.raises(EmbeddingRetryExhausted) as err:
        _call(client, max_attempts=5, backoff_sec=1.0, deadline_sec=30.0, clock=lambda: 0.0)
    assert len(client.requests) == 1, "must not retry at all"
    assert err.value.status_code == 429
    assert "600" in str(err.value), "the Retry-After value belongs in the message"


def test_f5_unparseable_retry_after_falls_back_to_backoff():
    slept: list[float] = []

    async def _record(d):
        slept.append(d)

    client = _FakeClient([("status", (429, {"Retry-After": "soon-ish"})), ("ok", 1)])
    _call(client, max_attempts=3, backoff_sec=4.0, deadline_sec=600.0,
          sleep=_record, clock=lambda: 0.0)
    assert slept == [4.0], "falls back to the computed backoff"


# === F6: read timeouts are capped and logged as possible_double_bill ========

def test_f6_read_timeout_retries_are_capped_separately(caplog):
    client = _FakeClient([("raise", httpx.ReadTimeout("timed out"))] * 8)
    with caplog.at_level("WARNING"):
        with pytest.raises(EmbeddingRetryExhausted):
            _call(client, max_attempts=8, max_timeout_retries=2)
    assert len(client.requests) == 3, "2 timeout retries allowed, the third gives up"


def test_f6_possible_double_bill_is_logged_with_batch_id_and_tokens(caplog):
    client = _FakeClient([("raise", httpx.ReadTimeout("timed out")), ("ok", 1)])
    with caplog.at_level("WARNING"):
        _call(client, max_attempts=3, batch_id="abc123", batch_tokens=4242)
    lines = [r.getMessage() for r in caplog.records if "possible_double_bill" in r.getMessage()]
    assert lines, "a read-timeout retry must log possible_double_bill"
    assert "abc123" in lines[0] and "4242" in lines[0]


def test_f6_connect_error_is_not_logged_as_possible_double_bill(caplog):
    client = _FakeClient([("raise", httpx.ConnectError("x")), ("ok", 1)])
    with caplog.at_level("WARNING"):
        _call(client, max_attempts=3)
    assert not [r for r in caplog.records if "possible_double_bill" in r.getMessage()], \
        "a connect that never landed cannot have been billed"


# === unchanged guarantees ===================================================

def test_rb4_double_bill_log_carries_the_real_batch_id_and_tokens_through_embed(monkeypatch, caplog):
    """R-B4 / QC finding 6: the round-2 tests passed literals straight to the
    helper, so a dropped or misnamed argument would log batch=unknown tokens=None
    while staying green. This drives the real provider."""
    import hashlib
    from svs_common.providers import estimate_embedding_tokens

    texts = ["alpha", "beta", "gamma"]
    expected_id = hashlib.sha256("\x00".join(texts).encode("utf-8")).hexdigest()[:16]
    expected_tokens = sum(estimate_embedding_tokens(t) for t in texts)

    client = _FakeClient([("raise", httpx.ReadTimeout("timed out")), ("ok", 3)])
    _install(monkeypatch, client)
    with caplog.at_level("WARNING"):
        asyncio.run(VoyageEmbeddingProvider(api_key="k").embed(
            texts, model="voyage-4", dimensions=2))

    lines = [r.getMessage() for r in caplog.records if "possible_double_bill" in r.getMessage()]
    assert lines, "a read-timeout retry through embed() must log possible_double_bill"
    assert f"batch={expected_id}" in lines[0], lines[0]
    assert f"tokens={expected_tokens}" in lines[0], lines[0]
    assert "batch=unknown" not in lines[0] and "tokens=None" not in lines[0]


def test_qc5_giving_up_on_the_timeout_allowance_is_logged(caplog):
    """QC round-2 finding 5: that WARNING was never asserted."""
    client = _FakeClient([("raise", httpx.ReadTimeout("timed out"))] * 8)
    with caplog.at_level("WARNING"):
        with pytest.raises(EmbeddingRetryExhausted):
            _call(client, max_attempts=8, max_timeout_retries=2)
    assert [r for r in caplog.records if "read-timeout allowance" in r.getMessage()], \
        "giving up on the timeout allowance must say so"


def test_qc8_status_exhaustion_does_not_suppress_context():
    """QC round-2 finding 8: `raise ... from None` set __suppress_context__."""
    client = _FakeClient([("status", 503)] * 3)
    with pytest.raises(EmbeddingRetryExhausted) as err:
        _call(client, max_attempts=3)
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__ is False, "context must not be suppressed"


def test_qc8_a_final_transport_error_keeps_the_earlier_status_for_diagnosis():
    """QC round-2 finding 8: the status/body were wiped by a later transport error."""
    client = _FakeClient([("status", 503), ("raise", httpx.ConnectError("x"))])
    with pytest.raises(EmbeddingRetryExhausted) as err:
        _call(client, max_attempts=2)
    assert err.value.status_code == 503, "the earlier 503 must survive into the message"


def test_non_429_4xx_is_not_retried_and_reaches_the_caller():
    for status in (400, 401, 403, 404, 422):
        client = _FakeClient([("status", status)])
        resp = _call(client, max_attempts=5)
        assert resp.status_code == status
        assert len(client.requests) == 1, f"{status} must not be retried"


def test_400_token_cap_still_reaches_the_bisect_path(monkeypatch):
    """The helper sits between the POST and _is_token_cap_rejection; prove the
    400 still reaches embed_in_order's bisection rather than being swallowed."""
    body = {"error": {"message": "Requested 400000 tokens, max 300000 tokens per request",
                      "type": "max_tokens_per_request"}}

    class _CapClient(_FakeClient):
        async def post(self, url, *, headers=None, json=None):
            self.requests.append({"url": url, "headers": headers, "json": json})
            if len(self.requests) == 1:
                return _FakeResponse(400, body)
            return _FakeResponse(200, _vectors(len(json["input"])))

    client = _CapClient([])
    _install(monkeypatch, client)
    result = asyncio.run(VoyageEmbeddingProvider(api_key="k").embed(
        ["a", "b"], model="voyage-4", dimensions=2))
    # QC round-2 finding 2: "more than one request" is true for a plain retry too.
    # Bisection is proven by the SPLIT: the first request carries both inputs, a
    # later one carries a strict subset. A retry would replay ["a","b"] unchanged.
    sent = [r["json"]["input"] for r in client.requests]
    assert sent[0] == ["a", "b"], sent
    assert any(len(batch) < 2 for batch in sent[1:]), f"no split; looks like a retry: {sent}"
    assert len(result.data) == 2


def test_config_defaults_are_read_when_not_passed(monkeypatch):
    """Nothing else exercises settings.embedding_max_attempts by name."""
    client = _FakeClient([("raise", httpx.ConnectError("x"))] * 10)
    monkeypatch.setattr(providers_mod.asyncio, "sleep", _never_sleep)
    with pytest.raises(EmbeddingRetryExhausted):
        asyncio.run(post_embedding_with_retry(
            client, URL, headers={}, json_payload={}, provider="voyage",
            jitter=lambda c: 0.0))
    from svs_common.config import get_settings
    assert len(client.requests) == get_settings().embedding_max_attempts


# === round 4 rulings ========================================================

def test_rb6_the_fake_records_a_copy_so_replay_identity_is_real():
    """R-B6: recording the reference made the replay assertion a self-comparison.

    Mutating the payload in place between attempts must now be visible.
    """
    payload = {"input": ["a", "b"]}

    class _MutatingClient(_FakeClient):
        async def post(self, url, *, headers=None, json=None):
            # `finally`, because attempt 1 raises ConnectError out of super():
            # the mutation has to land between the two recordings either way.
            try:
                return await super().post(url, headers=headers, json=json)
            finally:
                json["input"] = ["MUTATED"]

    client = _MutatingClient([("raise", httpx.ConnectError("x")), ("ok", 1)])
    asyncio.run(post_embedding_with_retry(
        client, URL, headers={}, json_payload=payload, provider="voyage",
        sleep=_never_sleep, jitter=lambda c: c, max_attempts=3))
    assert client.requests[0]["json"] != client.requests[1]["json"], \
        "the deep copy must expose an in-place mutation between attempts"


def test_rb7_raising_from_inside_an_except_block_preserves_context():
    """R-B7: `from None` at the R-B2 site would suppress a caller's context."""
    client = _FakeClient([("status", (429, {"Retry-After": "600"}))])
    try:
        raise RuntimeError("the caller was already handling this")
    except RuntimeError:
        with pytest.raises(EmbeddingRetryExhausted) as err:
            _call(client, max_attempts=3, backoff_sec=1.0, deadline_sec=30.0,
                  clock=lambda: 0.0)
    assert isinstance(err.value.__context__, RuntimeError), err.value.__context__
    assert err.value.__suppress_context__ is False


def test_rb8_a_successful_batch_never_computes_the_batch_digest(monkeypatch):
    """R-B8: batch_id is lazy; the happy path must not pay for it."""
    calls: list[int] = []
    real_sha256 = providers_mod.hashlib.sha256

    def _spy(data=b""):
        calls.append(1)
        return real_sha256(data)

    monkeypatch.setattr(providers_mod.hashlib, "sha256", _spy)
    client = _FakeClient([("ok", 2)])
    _install(monkeypatch, client)
    asyncio.run(VoyageEmbeddingProvider(api_key="k").embed(
        ["a", "b"], model="voyage-4", dimensions=2))
    assert calls == [], "a clean request must never compute the batch digest"


def test_rb9_a_timeout_on_the_final_attempt_logs_no_double_bill(caplog):
    """R-B9: the line must mean a retry WILL happen."""
    client = _FakeClient([("raise", httpx.ReadTimeout("timed out"))])
    with caplog.at_level("WARNING"):
        with pytest.raises(EmbeddingRetryExhausted):
            _call(client, max_attempts=1, max_timeout_retries=2)
    assert not [r for r in caplog.records if "possible_double_bill" in r.getMessage()], \
        "no retry happened, so nothing may have been double billed"


def test_rb9_a_timeout_with_the_deadline_blown_logs_no_double_bill(caplog):
    client = _FakeClient([("raise", httpx.ReadTimeout("timed out"))] * 3)
    with caplog.at_level("WARNING"):
        with pytest.raises(EmbeddingRetryExhausted):
            _call(client, max_attempts=5, deadline_sec=0.0, clock=lambda: 0.0)
    assert not [r for r in caplog.records if "possible_double_bill" in r.getMessage()], \
        "the deadline stopped the retry, so no re-bill was risked"


def test_rb12_a_successful_batch_adds_no_extra_token_estimation(monkeypatch):
    """R-B12 / round-2 finding 7: batch_tokens was eager.

    `estimate_embedding_tokens` is legitimately called by WAVE-131's batcher to
    plan batches, so "never called" is the wrong claim. Laziness means the happy
    path adds NO calls beyond the batcher's, while a read-timeout retry does.
    """
    def _count(outcomes):
        calls: list[str] = []
        real = providers_mod.estimate_embedding_tokens

        def _spy(text):
            calls.append(text)
            return real(text)

        mp = pytest.MonkeyPatch()
        try:
            mp.setattr(providers_mod, "estimate_embedding_tokens", _spy)
            client = _FakeClient(outcomes)
            mp.setattr(providers_mod.httpx, "AsyncClient", lambda **kw: client)
            mp.setattr(providers_mod.asyncio, "sleep", _never_sleep)
            asyncio.run(VoyageEmbeddingProvider(api_key="k").embed(
                ["a", "b"], model="voyage-4", dimensions=2))
        finally:
            mp.undo()
        return len(calls)

    clean = _count([("ok", 2)])
    timed_out = _count([("raise", httpx.ReadTimeout("timed out")), ("ok", 2)])
    assert timed_out > clean, (
        f"the timeout path must pay for the token estimate and the clean path must "
        f"not: clean={clean} timed_out={timed_out}")
