from svs_common.config import Settings
from svs_api import main


class FakeDb:
    def __init__(self, ok=True):
        self.ok = ok

    def execute(self, _sql):
        if not self.ok:
            raise RuntimeError("db unavailable")
        return 1


class FakeQdrant:
    def __init__(self, ok=True):
        self.ok = ok

    def healthcheck(self):
        return self.ok, None if self.ok else "qdrant unavailable"


def test_readyz_payload_requires_db(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(svs_dense_backend="disabled", svs_index_strict=False))

    payload = main.readiness_payload(FakeDb(ok=False), FakeQdrant(ok=True))

    assert payload == {"ready": False, "db": False}


def test_readyz_payload_requires_qdrant_when_strict_dense_indexing(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(svs_dense_backend="qdrant", svs_index_strict=True))

    payload = main.readiness_payload(FakeDb(ok=True), FakeQdrant(ok=False))

    assert payload == {"ready": False, "db": True, "qdrant": False}


def test_readyz_payload_skips_qdrant_when_not_required(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(svs_dense_backend="disabled", svs_index_strict=False))

    payload = main.readiness_payload(FakeDb(ok=True), FakeQdrant(ok=False))

    assert payload == {"ready": True, "db": True}
