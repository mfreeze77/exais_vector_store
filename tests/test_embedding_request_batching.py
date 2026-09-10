"""Regression tests for WAVE-131: unbatched embedding requests.

Before the fix, OpenAIEmbeddingProvider.embed posted every chunk of a document
in a single request. OpenAI caps an embeddings request at 300,000 tokens and
answers a larger one with HTTP 400 "max_tokens_per_request", which the provider
turned into a 500, making the 16 largest Kansas Governor's Budget Report volumes
un-indexable. These tests assert the batching contract the fix introduces:
inputs are split across requests, and the vectors come back one per input in
input order.
"""
from __future__ import annotations

import asyncio

import pytest

import svs_common.providers as providers_mod
from svs_common.providers import (
    DEFAULT_EMBEDDING_BATCH_TOKEN_BUDGET,
    EMBEDDING_CHARS_PER_TOKEN,
    OPENAI_MAX_INPUTS_PER_REQUEST,
    OPENAI_MAX_TOKENS_PER_REQUEST,
    CohereEmbeddingProvider,
    EmbeddingBatchError,
    OpenAIEmbeddingProvider,
    VoyageEmbeddingProvider,
    estimate_embedding_tokens,
    plan_embedding_batches,
)


class _FakeOpenAI:
    """Stands in for the embeddings endpoint, enforcing the real token cap.

    Every request is recorded so a test can assert how the inputs were split,
    and vectors are returned in a deliberately shuffled order tagged with the
    request-local index, which is how the real endpoint identifies them.
    """

    def __init__(self, *, token_cap: int = OPENAI_MAX_TOKENS_PER_REQUEST, shuffle: bool = True):
        self.token_cap = token_cap
        self.shuffle = shuffle
        self.requests: list[list[str]] = []

    def tokens(self, text: str) -> int:
        # One token per two characters: matches the provider's own estimate, so
        # the budget arithmetic under test is exercised without a tokenizer.
        return max(1, len(text) // 2)

    def post(self, batch: list[str]) -> tuple[int, dict]:
        self.requests.append(list(batch))
        total = sum(self.tokens(text) for text in batch)
        if total > self.token_cap:
            return 400, {
                "error": {
                    "message": f"Requested {total} tokens, max {self.token_cap} tokens per request",
                    "type": "max_tokens_per_request",
                    "code": "max_tokens_per_request",
                }
            }
        if len(batch) > OPENAI_MAX_INPUTS_PER_REQUEST:
            return 400, {"error": {"message": "too many inputs", "code": "invalid_request_error"}}
        items = [
            {"index": index, "embedding": [float(len(text)), float(index)]}
            for index, text in enumerate(batch)
        ]
        if self.shuffle:
            items = list(reversed(items))
        return 200, {"model": "text-embedding-3-small", "data": items, "usage": {"total_tokens": total}}


def _install(monkeypatch: pytest.MonkeyPatch, fake, *, payload_key: str = "input"):
    class _FakeResponse:
        def __init__(self, status_code: int, body: dict):
            self.status_code = status_code
            self._body = body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError(f"unexpected {self.status_code} reached raise_for_status")

        def json(self):
            return self._body

    class _FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            status, body = fake.post(json[payload_key])
            return _FakeResponse(status, body)

    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", _FakeAsyncClient)


def _inputs(count: int, chars: int) -> list[str]:
    # Each input is distinct, so a reordering shows up as a mismatched vector.
    return [f"{index:06d}" + "x" * (chars - 6) for index in range(count)]


# --- the regression itself -----------------------------------------------------

def test_document_larger_than_the_token_cap_is_split_and_stays_in_order(monkeypatch):
    """The pre-fix failure: one request over 300,000 tokens, 400, un-indexable."""
    # 700 inputs x 2,000 chars = 700,000 estimated tokens, 2.3x the hard cap.
    texts = _inputs(700, 2000)
    estimated = sum(estimate_embedding_tokens(text) for text in texts)
    assert estimated > OPENAI_MAX_TOKENS_PER_REQUEST

    fake = _FakeOpenAI()
    _install(monkeypatch, fake)
    provider = OpenAIEmbeddingProvider("sk-test-not-real")

    response = asyncio.run(provider.embed(texts, "text-embedding-3-small", 2))

    # More than one request was needed, and none of them was rejected.
    assert len(fake.requests) > 1
    assert all(sum(fake.tokens(t) for t in batch) <= OPENAI_MAX_TOKENS_PER_REQUEST for batch in fake.requests)

    # One vector per input, in input order, with nothing dropped or repeated.
    assert len(response.data) == len(texts)
    assert [item.index for item in response.data] == list(range(len(texts)))
    # The fake tags each vector with its request-local index and returns the
    # batch reversed; the provider must undo both to stay aligned with `texts`.
    expected = []
    for batch in fake.requests:
        expected.extend([float(len(text)), float(index)] for index, text in enumerate(batch))
    assert [item.embedding for item in response.data] == expected

    # The concatenation of the batches must reproduce the input list exactly.
    assert [text for batch in fake.requests for text in batch] == texts


def test_batches_respect_the_token_budget_not_a_fixed_input_count(monkeypatch):
    """A count-based batch still fails on long chunks; the budget must be tokens."""
    # 40 inputs of 40,000 chars: only 40 items, but 800,000 estimated tokens.
    texts = _inputs(40, 40000)
    fake = _FakeOpenAI()
    _install(monkeypatch, fake)

    response = asyncio.run(OpenAIEmbeddingProvider("sk-test-not-real").embed(texts, "m", 2))

    assert len(fake.requests) > 1
    assert max(len(batch) for batch in fake.requests) < len(texts)
    assert len(response.data) == len(texts)
    assert [text for batch in fake.requests for text in batch] == texts


def test_usage_is_summed_across_batches(monkeypatch):
    texts = _inputs(700, 2000)
    fake = _FakeOpenAI()
    _install(monkeypatch, fake)

    response = asyncio.run(OpenAIEmbeddingProvider("sk-test-not-real").embed(texts, "m", 2))

    assert response.usage["total_tokens"] == sum(fake.tokens(text) for text in texts)


def test_underestimated_batch_is_bisected_rather_than_failed(monkeypatch):
    """Backstop for content the character estimate under-counts."""
    # The endpoint's real cost is 8x the provider's estimate, so the first
    # planned batch is rejected and must be split until it fits.
    class _Dense(_FakeOpenAI):
        def tokens(self, text: str) -> int:
            return max(1, len(text) * 4)

    texts = _inputs(400, 2000)
    fake = _Dense()
    _install(monkeypatch, fake)

    response = asyncio.run(OpenAIEmbeddingProvider("sk-test-not-real").embed(texts, "m", 2))

    assert any(
        sum(fake.tokens(t) for t in batch) > OPENAI_MAX_TOKENS_PER_REQUEST for batch in fake.requests
    ), "expected at least one rejected batch to prove bisection ran"
    assert len(response.data) == len(texts)
    assert [item.index for item in response.data] == list(range(len(texts)))
    accepted = [b for b in fake.requests if sum(fake.tokens(t) for t in b) <= OPENAI_MAX_TOKENS_PER_REQUEST]
    assert [text for batch in accepted for text in batch] == texts


def test_single_input_over_the_cap_fails_the_document(monkeypatch):
    """A chunk no batching can rescue must raise, not be dropped."""
    fake = _FakeOpenAI(token_cap=10)
    _install(monkeypatch, fake)

    with pytest.raises(EmbeddingBatchError, match="chunking profile must emit smaller chunks"):
        asyncio.run(OpenAIEmbeddingProvider("sk-test-not-real").embed(_inputs(1, 500), "m", 2))


def test_short_batch_response_raises_instead_of_truncating(monkeypatch):
    """A dropped vector must fail the document, never misalign the tail."""
    class _Lossy(_FakeOpenAI):
        def post(self, batch):
            status, body = super().post(batch)
            if status == 200:
                body["data"] = body["data"][:-1]
            return status, body

    _install(monkeypatch, _Lossy())

    with pytest.raises(EmbeddingBatchError, match="embeddings for a batch of"):
        asyncio.run(OpenAIEmbeddingProvider("sk-test-not-real").embed(_inputs(10, 100), "m", 2))


def test_duplicate_response_index_raises(monkeypatch):
    class _Duplicating(_FakeOpenAI):
        def post(self, batch):
            status, body = super().post(batch)
            if status == 200:
                for item in body["data"]:
                    item["index"] = 0
            return status, body

    _install(monkeypatch, _Duplicating())

    with pytest.raises(EmbeddingBatchError, match="duplicate embedding index"):
        asyncio.run(OpenAIEmbeddingProvider("sk-test-not-real").embed(_inputs(5, 100), "m", 2))


# --- the batch planner ---------------------------------------------------------

def test_batch_plan_covers_every_input_exactly_once_in_order():
    texts = _inputs(500, 1500)
    spans = plan_embedding_batches(texts, token_budget=DEFAULT_EMBEDDING_BATCH_TOKEN_BUDGET, max_inputs=2048)

    assert spans[0][0] == 0
    assert spans[-1][1] == len(texts)
    # contiguous, non-overlapping, ascending
    assert all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1))
    assert [text for start, end in spans for text in texts[start:end]] == texts


def test_batch_plan_honours_the_token_budget():
    texts = _inputs(100, 2000)
    spans = plan_embedding_batches(texts, token_budget=5000, max_inputs=None)

    for start, end in spans:
        span = texts[start:end]
        estimated = sum(estimate_embedding_tokens(t) for t in span)
        # A span may exceed the budget only when it is a single oversized input.
        assert estimated <= 5000 or len(span) == 1


def test_batch_plan_honours_the_input_count_cap():
    texts = _inputs(50, 10)
    spans = plan_embedding_batches(texts, token_budget=10_000_000, max_inputs=7)

    assert max(end - start for start, end in spans) <= 7
    assert [text for start, end in spans for text in texts[start:end]] == texts


def test_batch_plan_never_drops_an_oversized_input():
    texts = ["x" * 10, "y" * 10_000_000, "z" * 10]
    spans = plan_embedding_batches(texts, token_budget=100, max_inputs=None)

    assert [text for start, end in spans for text in texts[start:end]] == texts


def test_empty_input_makes_no_request(monkeypatch):
    fake = _FakeOpenAI()
    _install(monkeypatch, fake)

    response = asyncio.run(OpenAIEmbeddingProvider("sk-test-not-real").embed([], "m", 2))

    assert fake.requests == []
    assert response.data == []


def test_default_budget_leaves_headroom_under_the_hard_cap():
    assert DEFAULT_EMBEDDING_BATCH_TOKEN_BUDGET < OPENAI_MAX_TOKENS_PER_REQUEST
    # The estimate must over-count realistic text: the Kansas fiscal corpus
    # measured 3.08 chars/token at the median, well above this divisor.
    assert EMBEDDING_CHARS_PER_TOKEN <= 2.0


# --- the other vendor providers share the batching contract --------------------

def test_voyage_provider_batches_and_preserves_order(monkeypatch):
    class _FakeVoyage(_FakeOpenAI):
        def post(self, batch):
            self.requests.append(list(batch))
            items = [
                {"index": index, "embedding": [float(len(text)), float(index)]}
                for index, text in enumerate(batch)
            ]
            return 200, {"data": list(reversed(items)), "usage": {"total_tokens": len(batch)}}

    texts = _inputs(2500, 200)
    fake = _FakeVoyage()
    _install(monkeypatch, fake)

    response = asyncio.run(VoyageEmbeddingProvider("vk-test-not-real").embed(texts, "voyage-4", 2))

    assert len(fake.requests) > 1
    assert max(len(batch) for batch in fake.requests) <= providers_mod.VOYAGE_MAX_INPUTS_PER_REQUEST
    assert len(response.data) == len(texts)
    assert [text for batch in fake.requests for text in batch] == texts


def test_cohere_provider_respects_its_input_cap(monkeypatch):
    class _FakeCohere(_FakeOpenAI):
        def post(self, batch):
            self.requests.append(list(batch))
            return 200, {
                "embeddings": {"float": [[float(len(t)), 0.0] for t in batch]},
                "meta": {"billed_units": {"input_tokens": len(batch)}},
            }

    texts = _inputs(300, 100)
    fake = _FakeCohere()
    _install(monkeypatch, fake, payload_key="texts")

    response = asyncio.run(CohereEmbeddingProvider("ck-test-not-real").embed(texts, "embed-v4.0", 2))

    assert max(len(batch) for batch in fake.requests) <= providers_mod.COHERE_MAX_INPUTS_PER_REQUEST
    assert len(response.data) == len(texts)
    assert response.usage["input_tokens"] == len(texts)
    assert [text for batch in fake.requests for text in batch] == texts
