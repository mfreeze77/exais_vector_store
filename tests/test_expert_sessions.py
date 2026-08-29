from __future__ import annotations

from datetime import datetime, timezone
import inspect
from pathlib import Path

import pytest

import svs_common.expert_sessions as expert_sessions
from svs_common.expert_sessions import (
    DEFAULT_EXPERT_MEMORY_POLICY,
    ExpertSessionNotFound,
    create_or_resume_expert_session,
    delete_expert_memory_event,
    expert_session_key,
    extract_candidate_memory_events,
    fork_expert_session,
    promote_expert_memory_event,
    record_expert_feedback,
    record_expert_memory_event,
    record_expert_retrieval_run,
)
from svs_common.schemas import ExpertMemoryCandidateInput, ExpertMemoryPolicy, ExpertTurnRecord, Principal
from svs_common.security import ExpertInteractionSensitiveDataError


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


class _Rows:
    def __init__(self, *, row=None, rows=None, scalar=None, rowcount: int = 1):
        self.row = row
        self.rows = list(rows or [])
        self.scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class _Db:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        if not self.results:
            return _Rows(row=None, rows=[], scalar=0, rowcount=0)
        result = self.results.pop(0)
        if isinstance(result, _Rows):
            return result
        if isinstance(result, list):
            return _Rows(rows=result)
        return _Rows(row=result)


def _principal(**changes) -> Principal:
    values = {
        "tenant_id": "tenant_a",
        "business_instance_id": "biz_a",
        "user_id": "user_a",
        "api_key_id": "key_a",
    }
    values.update(changes)
    return Principal(**values)


def _session_row(**changes):
    row = {
        "id": "exps_parent",
        "session_key": "expsk_parent",
        "expert_id": "ks_state_civics",
        "api_key_id": "key_a",
        "user_id": "user_a",
        "external_user_id": "caller_user_a",
        "conversation_id": "conversation_a",
        "label": "Kansas question",
        "parent_session_id": None,
        "status": "active",
        "metadata": {"source": "test"},
        "created_at": NOW,
        "updated_at": NOW,
        "last_active_at": NOW,
    }
    row.update(changes)
    return row


def _message_row(**changes):
    row = {
        "id": "exmsg_parent",
        "session_id": "exps_parent",
        "message_id": None,
        "role": "user",
        "content": {"text": "What does home rule mean?"},
        "sequence_no": 0,
        "metadata": {},
        "created_at": NOW,
    }
    row.update(changes)
    return row


def _tool_row(**changes):
    row = {
        "id": "extool_parent",
        "session_id": "exps_parent",
        "message_id": "exmsg_parent",
        "tool_name": "search_vector_store",
        "status": "completed",
        "input": {"query": "home rule"},
        "output": {"result_ids": ["chunk_1"]},
        "error": None,
        "sequence_no": 0,
        "created_at": NOW,
        "completed_at": NOW,
    }
    row.update(changes)
    return row


def _retrieval_row(**changes):
    row = {
        "id": "exret_parent",
        "session_id": "exps_parent",
        "message_id": "exmsg_parent",
        "tool_call_id": "extool_parent",
        "sequence_no": 0,
        "payload": {
            "message_id": "exmsg_parent",
            "tool_call_id": "extool_parent",
            "query": "home rule",
            "citations": [{"chunk_id": "chunk_1"}],
        },
        "created_at": NOW,
    }
    row.update(changes)
    return row


def _memory_row(**changes):
    row = {
        "id": "exmem_parent",
        "session_id": "exps_parent",
        "source_message_id": "exmsg_parent",
        "source_feedback_id": "exfb_parent",
        "event_type": "answer_style",
        "status": "candidate",
        "payload": {
            "memory_type": "answer_style",
            "instruction": "Prefer concise answers",
            "authority": "none",
            "citation_eligible": False,
        },
        "confidence": 0.9,
        "created_at": NOW,
        "promoted_at": None,
        "deleted_at": None,
    }
    row.update(changes)
    return row


def _compact(sql: str) -> str:
    return " ".join(sql.split())


def test_expert_session_key_is_stable_and_partitions_every_identity_dimension():
    principal = _principal()
    baseline = expert_session_key(principal, "ks_state_civics", "caller_user_a", "conversation_a")

    assert baseline == expert_session_key(principal, " ks_state_civics ", " caller_user_a ", " conversation_a ")
    assert baseline.startswith("expsk_")
    assert "tenant_a" not in baseline
    variants = {
        expert_session_key(_principal(tenant_id="tenant_b"), "ks_state_civics", "caller_user_a", "conversation_a"),
        expert_session_key(_principal(business_instance_id="biz_b"), "ks_state_civics", "caller_user_a", "conversation_a"),
        expert_session_key(_principal(api_key_id="key_b"), "ks_state_civics", "caller_user_a", "conversation_a"),
        expert_session_key(_principal(user_id="user_b"), "ks_state_civics", "caller_user_a", "conversation_a"),
        expert_session_key(principal, "county_records", "caller_user_a", "conversation_a"),
        expert_session_key(principal, "ks_state_civics", "caller_user_b", "conversation_a"),
        expert_session_key(principal, "ks_state_civics", "caller_user_a", "conversation_b"),
    }
    assert baseline not in variants
    assert len(variants) == 7


def test_create_or_resume_hydrates_prior_message_tool_and_retrieval_context(monkeypatch):
    monkeypatch.setattr(expert_sessions, "new_id", lambda prefix: f"{prefix}_created")
    db = _Db(results=[
        _session_row(),
        [
            _message_row(),
            _message_row(
                id="exmsg_assistant",
                role="assistant",
                content={"text": "Home rule is limited by state law."},
                sequence_no=1,
            ),
        ],
        [_tool_row()],
        [_retrieval_row()],
    ])

    session = create_or_resume_expert_session(
        db,
        _principal(),
        "ks_state_civics",
        external_user_id="caller_user_a",
        conversation_id="conversation_a",
        label="Kansas question",
    )

    assert session.id == "exps_parent"
    assert session.messages[0].content == {"text": "What does home rule mean?"}
    assert session.messages[1].role == "assistant"
    assert session.messages[1].content == {"text": "Home rule is limited by state law."}
    assert session.tool_calls[0].output == {"result_ids": ["chunk_1"]}
    assert session.retrieval_runs[0].payload["citations"] == [{"chunk_id": "chunk_1"}]
    insert_sql, params = db.calls[0]
    compact = _compact(insert_sql)
    assert "ON CONFLICT (tenant_id, business_instance_id, session_key) DO UPDATE" in compact
    assert "expert_sessions.api_key_id IS NOT DISTINCT FROM EXCLUDED.api_key_id" in compact
    assert "expert_sessions.user_id IS NOT DISTINCT FROM EXCLUDED.user_id" in compact
    assert params["tenant_id"] == "tenant_a"
    assert params["biz_id"] == "biz_a"
    assert params["api_key_id"] == "key_a"
    assert params["user_id"] == "user_a"
    assert params["external_user_id"] == "caller_user_a"
    assert params["conversation_id"] == "conversation_a"


def test_record_retrieval_run_requires_scoped_session_and_preserves_payload(monkeypatch):
    monkeypatch.setattr(expert_sessions, "new_id", lambda prefix: f"{prefix}_created")
    db = _Db(results=[
        _session_row(),
        _Rows(scalar=3),
        _Rows(),
        _Rows(),
    ])
    payload = {
        "message_id": "exmsg_parent",
        "tool_call_id": "extool_parent",
        "query": "home rule",
        "result_ids": ["chunk_1"],
        "citations": [{"chunk_id": "chunk_1", "source_url": "https://example.test/source"}],
    }

    run_id = record_expert_retrieval_run(db, _principal(), "exps_parent", payload)

    assert run_id == "exret_created"
    session_sql, session_params = db.calls[0]
    assert "FOR UPDATE" in _compact(session_sql)
    assert session_params == {
        "tenant_id": "tenant_a",
        "biz_id": "biz_a",
        "api_key_id": "key_a",
        "user_id": "user_a",
        "session_id": "exps_parent",
    }
    insert_sql, insert_params = db.calls[2]
    assert "INSERT INTO expert_retrieval_runs" in insert_sql
    assert insert_params["sequence_no"] == 3
    assert '"source_url":"https://example.test/source"' in insert_params["payload"]


def test_record_retrieval_run_fails_closed_when_session_is_out_of_scope():
    db = _Db(results=[None])

    with pytest.raises(ExpertSessionNotFound):
        record_expert_retrieval_run(db, _principal(api_key_id="key_other"), "exps_parent", {"query": "x"})

    assert len(db.calls) == 1
    sql, params = db.calls[0]
    assert "api_key_id IS NOT DISTINCT FROM :api_key_id" in sql
    assert "user_id IS NOT DISTINCT FROM :user_id" in sql
    assert params["api_key_id"] == "key_other"


def test_fork_copies_context_records_parentage_and_never_updates_parent(monkeypatch):
    counters: dict[str, int] = {}

    def _new_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}_{counters[prefix]}"

    monkeypatch.setattr(expert_sessions, "new_id", _new_id)
    child = _session_row(
        id="exps_1",
        session_key=expert_session_key(
            _principal(),
            "ks_state_civics",
            "caller_user_a",
            "conversation_a:fork:exps_1",
        ),
        conversation_id="conversation_a:fork:exps_1",
        label="Alternative",
        parent_session_id="exps_parent",
    )
    child_message = _message_row(id="exmsg_1", session_id="exps_1")
    child_assistant_message = _message_row(
        id="exmsg_2",
        session_id="exps_1",
        role="assistant",
        content={"text": "Home rule is limited by state law."},
        sequence_no=1,
    )
    child_tool = _tool_row(id="extool_1", session_id="exps_1", message_id="exmsg_1")
    child_retrieval = _retrieval_row(
        id="exret_1",
        session_id="exps_1",
        message_id="exmsg_1",
        tool_call_id="extool_1",
    )
    db = _Db(results=[
        _session_row(),
        [
            _message_row(),
            _message_row(
                id="exmsg_assistant",
                role="assistant",
                content={"text": "Home rule is limited by state law."},
                sequence_no=1,
            ),
        ],
        [_tool_row()],
        [_retrieval_row()],
        _Rows(),
        _Rows(),
        _Rows(),
        _Rows(),
        _Rows(),
        _Rows(),
        child,
        [child_message, child_assistant_message],
        [child_tool],
        [child_retrieval],
    ])

    forked = fork_expert_session(db, _principal(), "exps_parent", label="Alternative")

    assert forked.id == "exps_1"
    assert forked.parent_session_id == "exps_parent"
    assert forked.conversation_id == "conversation_a:fork:exps_1"
    assert [message.role for message in forked.messages] == ["user", "assistant"]
    assert [message.content for message in forked.messages] == [
        {"text": "What does home rule mean?"},
        {"text": "Home rule is limited by state law."},
    ]
    assert forked.retrieval_runs[0].payload["citations"] == [{"chunk_id": "chunk_1"}]
    calls = [(_compact(sql), params) for sql, params in db.calls]
    child_insert = next(params for sql, params in calls if sql.startswith("INSERT INTO expert_sessions"))
    message_insert = next(params for sql, params in calls if sql.startswith("INSERT INTO expert_messages"))
    tool_insert = next(params for sql, params in calls if sql.startswith("INSERT INTO expert_tool_calls"))
    retrieval_insert = next(params for sql, params in calls if sql.startswith("INSERT INTO expert_retrieval_runs"))
    fork_insert = next(params for sql, params in calls if sql.startswith("INSERT INTO expert_session_forks"))
    assert child_insert["parent_session_id"] == "exps_parent"
    assert message_insert["source_message_id"] == "exmsg_parent"
    assert {
        params["source_message_id"]
        for sql, params in calls
        if sql.startswith("INSERT INTO expert_messages")
    } == {"exmsg_parent", "exmsg_assistant"}
    assert tool_insert["source_tool_call_id"] == "extool_parent"
    assert retrieval_insert["source_retrieval_run_id"] == "exret_parent"
    assert '"message_id":"exmsg_1"' in retrieval_insert["payload"]
    assert '"tool_call_id":"extool_1"' in retrieval_insert["payload"]
    assert '"citations":[{"chunk_id":"chunk_1"}]' in retrieval_insert["payload"]
    assert fork_insert["parent_session_id"] == "exps_parent"
    assert fork_insert["child_session_id"] == "exps_1"
    assert not any(sql.startswith("UPDATE expert_sessions") for sql, _ in calls)
    assert not any(
        sql.startswith("INSERT INTO expert_feedback") or sql.startswith("INSERT INTO expert_memory_events")
        for sql, _ in calls
    )


def test_expert_session_migration_has_full_rls_upgrade_and_reversible_downgrade():
    path = ROOT / "migrations" / "versions" / "003_expert_conversation_sessions.py"
    source = path.read_text(encoding="utf-8")
    expected_tables = {
        "expert_sessions",
        "expert_messages",
        "expert_tool_calls",
        "expert_retrieval_runs",
        "expert_feedback",
        "expert_memory_events",
        "expert_session_forks",
    }

    for table in expected_tables:
        assert f'"{table}"' in source
        assert f"DROP TABLE IF EXISTS {table}" in source
    assert "ALTER TABLE %I ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE %I FORCE ROW LEVEL SECURITY" in source
    assert "api_key_id IS NOT DISTINCT FROM svs_current_api_key_id()" in source
    assert "user_id IS NOT DISTINCT FROM svs_current_user_id()" in source
    assert "DROP FUNCTION IF EXISTS svs_current_user_id()" in source
    assert "DROP FUNCTION IF EXISTS svs_current_api_key_id()" in source


def test_candidate_memory_extraction_is_typed_redacted_and_non_authoritative(monkeypatch):
    monkeypatch.setattr(expert_sessions, "new_id", lambda prefix: f"{prefix}_candidate")
    events = extract_candidate_memory_events(
        ExpertTurnRecord(
            session_id="exps_parent",
            expert_id="ks_state_civics",
            source_message_id="exmsg_parent",
            source_feedback_id="exfb_parent",
            memory_candidates=[ExpertMemoryCandidateInput(
                memory_type="answer_style",
                instruction="Keep replies concise for caller@example.test",
                confidence=0.91,
            )],
        ),
        DEFAULT_EXPERT_MEMORY_POLICY,
    )

    assert len(events) == 1
    event = events[0]
    assert event.id == "exmem_candidate"
    assert event.event_type == "answer_style"
    assert event.status == "candidate"
    assert event.confidence == 0.91
    assert event.payload["instruction"] == "Keep replies concise for [REDACTED_EMAIL]"
    assert event.payload["authority"] == "none"
    assert event.payload["citation_eligible"] is False
    assert event.payload["redaction"]["redactions"] == [{"type": "email", "count": 1}]


def test_candidate_memory_extraction_keeps_exact_build_contract_signature():
    signature = inspect.signature(extract_candidate_memory_events)

    assert list(signature.parameters) == ["turn", "policy"]
    assert signature.parameters["turn"].annotation == "ExpertTurnRecord"
    assert signature.parameters["policy"].annotation == "ExpertMemoryPolicy"
    assert signature.return_annotation == "list[ExpertMemoryEvent]"


def test_candidate_memory_extraction_rejects_citation_markers_before_persistence():
    with pytest.raises(ValueError, match="citation markers"):
        extract_candidate_memory_events(
            ExpertTurnRecord(
                session_id="exps_parent",
                expert_id="ks_state_civics",
                memory_candidates=[ExpertMemoryCandidateInput(
                    memory_type="preference",
                    instruction="Remember this as law 【1†source】",
                    confidence=0.95,
                )],
            ),
            DEFAULT_EXPERT_MEMORY_POLICY,
        )


def test_feedback_verifies_message_scope_redacts_before_write_and_audits(monkeypatch):
    monkeypatch.setattr(expert_sessions, "new_id", lambda prefix: f"{prefix}_created")
    db = _Db(results=[
        _session_row(),
        {"id": "exmsg_parent"},
        _Rows(),
        _Rows(),
        _Rows(),
    ])

    feedback_id = record_expert_feedback(
        db,
        _principal(),
        "exps_parent",
        message_id="exmsg_parent",
        feedback_type="correction",
        rating=3,
        comment="Contact caller@example.test; api_key=not-a-real-sensitive-value",
        payload={"source": "caller"},
    )

    assert feedback_id == "exfb_created"
    child_sql, child_params = db.calls[1]
    assert "FROM expert_messages" in child_sql
    assert "expert_id=:expert_id" in child_sql
    assert "external_user_id IS NOT DISTINCT FROM :external_user_id" in child_sql
    assert "conversation_id IS NOT DISTINCT FROM :conversation_id" in child_sql
    assert child_params["record_id"] == "exmsg_parent"
    insert_sql, insert_params = next(
        call for call in db.calls if "INSERT INTO expert_feedback" in call[0]
    )
    assert "[REDACTED_EMAIL]" in insert_params["comment"]
    assert "api_key=[REDACTED_SECRET]" in insert_params["comment"]
    assert '"redaction"' in insert_params["payload"]
    audit_sql, audit_params = next(call for call in db.calls if "INSERT INTO audit_events" in call[0])
    assert "expert_governance" in audit_sql
    assert audit_params["action"] == "feedback_created"
    assert "caller@example.test" not in audit_params["metadata"]


def test_feedback_fails_closed_when_message_is_not_in_same_scoped_session():
    db = _Db(results=[_session_row(), None])

    with pytest.raises(ExpertSessionNotFound, match="message not found"):
        record_expert_feedback(
            db,
            _principal(),
            "exps_parent",
            message_id="exmsg_other_scope",
            feedback_type="correction",
            comment="Wrong result",
        )

    assert len(db.calls) == 2
    assert not any("INSERT INTO expert_feedback" in sql for sql, _ in db.calls)


@pytest.mark.parametrize("feedback_type", ["arbitrary", "client_secret", "Bearer hidden-value"])
def test_feedback_owner_rejects_untyped_categories_before_any_database_call(feedback_type):
    db = _Db(results=[_session_row()])

    with pytest.raises(ValueError, match="unsupported expert feedback type"):
        record_expert_feedback(
            db,
            _principal(),
            "exps_parent",
            feedback_type=feedback_type,
            comment="Must not persist",
        )

    assert db.calls == []


@pytest.mark.parametrize("sensitive_key", ["client_secret", "aws_secret_access_key", "caller@example.test"])
def test_feedback_owner_rejects_sensitive_json_keys_without_persistence(sensitive_key):
    db = _Db(results=[_session_row()])

    with pytest.raises(ExpertInteractionSensitiveDataError, match="sensitive field"):
        record_expert_feedback(
            db,
            _principal(),
            "exps_parent",
            feedback_type="other",
            payload={sensitive_key: "must-not-persist"},
        )

    assert len(db.calls) == 1
    assert db.calls[0][0].lstrip().startswith("SELECT id, session_key")
    assert not any("INSERT INTO" in sql for sql, _ in db.calls)


@pytest.mark.parametrize("sensitive_key", ["clientSecret", "AWSSecretAccessKey", "785-555-1212"])
def test_memory_owner_rejects_sensitive_json_keys_without_persistence(sensitive_key):
    db = _Db(results=[_session_row()])

    with pytest.raises(ExpertInteractionSensitiveDataError, match="sensitive field"):
        record_expert_memory_event(
            db,
            _principal(),
            "exps_parent",
            event_type="preference",
            payload={"instruction": "safe", sensitive_key: "must-not-persist"},
            confidence=0.9,
        )

    assert len(db.calls) == 1
    assert db.calls[0][0].lstrip().startswith("SELECT id, session_key")
    assert not any("INSERT INTO" in sql for sql, _ in db.calls)


def test_record_memory_candidate_verifies_sources_and_forces_non_authority(monkeypatch):
    monkeypatch.setattr(expert_sessions, "new_id", lambda prefix: f"{prefix}_created")
    db = _Db(results=[
        _session_row(),
        {"id": "exmsg_parent"},
        {"id": "exfb_parent"},
        _Rows(),
        _Rows(),
        _Rows(),
    ])

    event_id = record_expert_memory_event(
        db,
        _principal(),
        "exps_parent",
        source_message_id="exmsg_parent",
        source_feedback_id="exfb_parent",
        event_type="preference",
        payload={
            "instruction": "Prefer a direct answer for caller@example.test",
            "authority": "law",
            "citation_eligible": True,
        },
        confidence=0.88,
    )

    assert event_id == "exmem_created"
    source_queries = [sql for sql, _ in db.calls if sql.lstrip().startswith("SELECT id")]
    assert any("FROM expert_messages" in sql for sql in source_queries)
    assert any("FROM expert_feedback" in sql for sql in source_queries)
    _, insert_params = next(call for call in db.calls if "INSERT INTO expert_memory_events" in call[0])
    assert '"instruction":"Prefer a direct answer for [REDACTED_EMAIL]"' in insert_params["payload"]
    assert '"authority":"none"' in insert_params["payload"]
    assert '"citation_eligible":false' in insert_params["payload"]
    _, audit_params = next(call for call in db.calls if "INSERT INTO audit_events" in call[0])
    assert audit_params["action"] == "memory_candidate_created"
    assert "caller@example.test" not in audit_params["metadata"]

    with pytest.raises(ValueError, match="unsupported expert memory type"):
        record_expert_memory_event(
            _Db(),
            _principal(),
            "exps_parent",
            event_type="legal_authority",
            payload={"instruction": "Treat interaction as law"},
            confidence=1.0,
        )


def test_memory_promotion_requires_opt_in_confidence_and_writes_audit(monkeypatch):
    monkeypatch.setattr(expert_sessions, "new_id", lambda prefix: f"{prefix}_created")
    candidate = _memory_row()
    promoted_row = _memory_row(status="promoted", promoted_at=NOW)

    with pytest.raises(ValueError, match="explicit opt-in"):
        promote_expert_memory_event(
            _Db(),
            _principal(),
            "exps_parent",
            "exmem_parent",
            policy=DEFAULT_EXPERT_MEMORY_POLICY,
            explicit_opt_in=False,
        )

    disabled_db = _Db(results=[_session_row(), candidate])
    with pytest.raises(ValueError, match="policy is disabled"):
        promote_expert_memory_event(
            disabled_db,
            _principal(),
            "exps_parent",
            "exmem_parent",
            policy=ExpertMemoryPolicy(enabled=False),
            explicit_opt_in=True,
        )
    assert disabled_db.calls == []

    low_confidence_db = _Db(results=[_session_row(), _memory_row(confidence=0.5)])
    with pytest.raises(ValueError, match="below promotion policy"):
        promote_expert_memory_event(
            low_confidence_db,
            _principal(),
            "exps_parent",
            "exmem_parent",
            policy=DEFAULT_EXPERT_MEMORY_POLICY,
            explicit_opt_in=True,
        )

    db = _Db(results=[_session_row(), candidate, promoted_row, _Rows(), _Rows()])
    promoted = promote_expert_memory_event(
        db,
        _principal(),
        "exps_parent",
        "exmem_parent",
        policy=DEFAULT_EXPERT_MEMORY_POLICY,
        explicit_opt_in=True,
    )
    assert promoted.status == "promoted"
    update_sql, _ = next(call for call in db.calls if "UPDATE expert_memory_events" in call[0])
    assert "AND status='candidate'" in update_sql
    _, audit_params = next(call for call in db.calls if "INSERT INTO audit_events" in call[0])
    assert audit_params["action"] == "memory_promoted"
    assert '"explicit_opt_in":true' in audit_params["metadata"]


def test_memory_delete_is_scoped_soft_delete_with_scrubbed_payload_and_audit(monkeypatch):
    monkeypatch.setattr(expert_sessions, "new_id", lambda prefix: f"{prefix}_created")
    deleted_row = _memory_row(
        status="deleted",
        payload={
            "memory_type": "answer_style",
            "authority": "none",
            "citation_eligible": False,
            "deleted": True,
        },
        promoted_at=NOW,
        deleted_at=NOW,
    )
    db = _Db(results=[
        _session_row(),
        _memory_row(status="promoted", promoted_at=NOW),
        deleted_row,
        _Rows(),
        _Rows(),
    ])

    deleted = delete_expert_memory_event(db, _principal(), "exps_parent", "exmem_parent")

    assert deleted.status == "deleted"
    assert deleted.payload == deleted_row["payload"]
    update_sql, update_params = next(call for call in db.calls if "UPDATE expert_memory_events" in call[0])
    assert "status='deleted'" in update_sql
    assert "deleted_at=now()" in update_sql
    assert "Prefer concise answers" not in update_params["payload"]
    _, audit_params = next(call for call in db.calls if "INSERT INTO audit_events" in call[0])
    assert audit_params["action"] == "memory_deleted"
    assert '"payload_scrubbed":true' in audit_params["metadata"]
