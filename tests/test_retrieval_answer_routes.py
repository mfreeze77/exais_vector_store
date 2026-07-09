from __future__ import annotations

import asyncio

from svs_api import main as api_main
from svs_common.schemas import ContextCitation, ChunkRecord, Principal, RetrievalAnswerRequest, RetrievalAnswerResponse


class _Db:
    committed = False

    def commit(self):
        self.committed = True


def _principal() -> Principal:
    return Principal(
        tenant_id="tenant",
        business_instance_id="biz-dev",
        scopes=["retrieval:read"],
        max_security_level=5,
    )


def test_native_retrieval_answer_route_returns_typed_payload(monkeypatch):
    db = _Db()
    captured: dict[str, object] = {}
    refreshed: list[str] = []

    async def fake_answer(db_session, principal, req):
        captured["req"] = req
        captured["principal"] = principal
        return RetrievalAnswerResponse(
            query=req.query,
            answer="Answer 【1†source】",
            citations=[
                ContextCitation(
                    chunk_id="chk_route",
                    document_id="doc_route",
                    file_id="file_route",
                    filename="route.md",
                    marker="【1†source】",
                    annotation={
                        "type": "file_citation",
                        "index": len("Answer "),
                        "file_id": "file_route",
                        "filename": "route.md",
                    },
                )
            ],
            chunks=[
                ChunkRecord(
                    id="chk_route",
                    document_id="doc_route",
                    file_id="file_route",
                    filename="route.md",
                    ordinal=1,
                    text="Route answer proof.",
                )
            ],
            context="Route answer proof. 【1†source】",
            token_estimate=8,
            audit_event_id="aud_route",
        )

    monkeypatch.setattr(api_main.retrieval, "answer", fake_answer)
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda db_session, principal, action: None)
    monkeypatch.setattr(
        api_main,
        "_refresh_vector_store_activity_or_404",
        lambda db_session, principal, vector_store_id: refreshed.append(vector_store_id),
    )

    response = asyncio.run(api_main.retrieval_answer(RetrievalAnswerRequest(query="route answer", vector_store_id="vs_route"), _principal(), db))

    assert isinstance(captured["req"], RetrievalAnswerRequest)
    assert captured["req"].query == "route answer"
    assert captured["req"].vector_store_id == "vs_route"
    assert captured["principal"].tenant_id == "tenant"
    assert refreshed == ["vs_route"]
    assert response.answer == "Answer 【1†source】"
    assert response.citations[0].annotation["index"] == len("Answer ")
    assert db.committed is True
