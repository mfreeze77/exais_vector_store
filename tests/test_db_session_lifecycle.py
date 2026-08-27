from __future__ import annotations

import pytest

from svs_common import db as db_mod


class _FakeSession:
    def __init__(self, *, in_transaction: bool = True):
        self._in_transaction = in_transaction
        self.events: list[str] = []

    def in_transaction(self) -> bool:
        self.events.append("in_transaction")
        return self._in_transaction

    def rollback(self) -> None:
        self.events.append("rollback")
        self._in_transaction = False

    def close(self) -> None:
        self.events.append("close")


def _patch_session_factory(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> None:
    monkeypatch.setattr(db_mod, "get_engine", lambda: object())
    monkeypatch.setattr(db_mod, "_SessionLocal", lambda: session)


def test_get_session_rolls_back_open_transaction_before_close(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(in_transaction=True)
    _patch_session_factory(monkeypatch, session)

    gen = db_mod.get_session()
    assert next(gen) is session

    with pytest.raises(StopIteration):
        next(gen)

    assert session.events == ["in_transaction", "rollback", "close"]


def test_get_session_rolls_back_and_closes_after_exception(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(in_transaction=True)
    _patch_session_factory(monkeypatch, session)

    gen = db_mod.get_session()
    assert next(gen) is session

    with pytest.raises(RuntimeError, match="cancelled request"):
        gen.throw(RuntimeError("cancelled request"))

    assert session.events == ["rollback", "in_transaction", "close"]
