from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from svs_common.db import set_rls_context
from svs_common.expert_sessions import (
    create_or_resume_expert_session,
    fork_expert_session,
    get_expert_session,
    record_expert_message,
    record_expert_feedback,
    record_expert_memory_event,
    record_expert_retrieval_run,
    record_expert_tool_call,
)
from svs_common.schemas import Principal


pytestmark = pytest.mark.skipif(
    os.getenv("SVS_RUN_EXPERT_SESSION_INTEGRATION") != "1",
    reason="set SVS_RUN_EXPERT_SESSION_INTEGRATION=1 against a disposable migrated Postgres",
)

DATABASE_URL = os.getenv(
    "SVS_EXPERT_SESSION_TEST_DATABASE_URL",
    "postgresql+psycopg://svs_app:svs_app_dev_password@localhost:5432/svs",
)
OWNER_DATABASE_URL = os.getenv(
    "SVS_EXPERT_SESSION_TEST_OWNER_DATABASE_URL",
    "postgresql+psycopg://svs_owner:svs_owner_dev_password@localhost:5432/svs",
)

EXPERT_TABLES = {
    "expert_sessions",
    "expert_messages",
    "expert_tool_calls",
    "expert_retrieval_runs",
    "expert_feedback",
    "expert_memory_events",
    "expert_session_forks",
}


def _principal(**changes) -> Principal:
    values = {
        "tenant_id": "ten_dev",
        "business_instance_id": "biz_dev",
        "user_id": "usr_dev",
        "api_key_id": "key_t002_a",
    }
    values.update(changes)
    return Principal(**values)


def test_expert_tables_are_forced_rls_and_runtime_role_cannot_bypass_scope():
    owner_engine = create_engine(OWNER_DATABASE_URL, future=True)
    try:
        with owner_engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT relname, relrowsecurity, relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='public'
                      AND relkind='r'
                      AND relname = ANY(:tables)
                    """
                ),
                {"tables": list(EXPERT_TABLES)},
            ).all()
            role = connection.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='svs_app'")
            ).one()
    finally:
        owner_engine.dispose()

    assert {row[0] for row in rows} == EXPERT_TABLES
    assert all(row[1] and row[2] for row in rows)
    assert role == (False, False)


def test_resume_fork_and_cross_scope_reads_against_runtime_role():
    engine = create_engine(DATABASE_URL, future=True)
    suffix = uuid.uuid4().hex
    external_user_id = f"caller_{suffix}"
    conversation_id = f"conversation_{suffix}"
    principal = _principal()
    try:
        with Session(engine) as db:
            set_rls_context(db, principal)
            session = create_or_resume_expert_session(
                db,
                principal,
                "ks_state_civics",
                external_user_id=external_user_id,
                conversation_id=conversation_id,
                label="Live RLS proof",
            )
            message_id = record_expert_message(
                db,
                principal,
                session.id,
                role="user",
                content={"text": "What is the home-rule standard?"},
            )
            tool_call_id = record_expert_tool_call(
                db,
                principal,
                session.id,
                message_id=message_id,
                tool_name="search_vector_store",
                input={"query": "home rule"},
                output={"result_ids": ["chunk_live_1"]},
            )
            record_expert_retrieval_run(
                db,
                principal,
                session.id,
                {
                    "message_id": message_id,
                    "tool_call_id": tool_call_id,
                    "query": "home rule",
                    "result_ids": ["chunk_live_1"],
                    "citations": [{"chunk_id": "chunk_live_1", "source_url": "https://example.test/live"}],
                },
            )
            record_expert_message(
                db,
                principal,
                session.id,
                role="assistant",
                content={"text": "Home rule is limited by controlling state law."},
            )
            feedback_id = record_expert_feedback(
                db,
                principal,
                session.id,
                message_id=message_id,
                feedback_type="helpful",
                rating=1,
                payload={"source": "live-proof"},
            )
            record_expert_memory_event(
                db,
                principal,
                session.id,
                source_message_id=message_id,
                source_feedback_id=feedback_id,
                event_type="answer_style",
                payload={"instruction": "Prefer concise answers"},
                confidence=0.75,
            )
            db.commit()

        with Session(engine) as db:
            set_rls_context(db, principal)
            resumed = create_or_resume_expert_session(
                db,
                principal,
                "ks_state_civics",
                external_user_id=external_user_id,
                conversation_id=conversation_id,
            )
            assert resumed.id == session.id
            assert [message.content for message in resumed.messages] == [
                {"text": "What is the home-rule standard?"},
                {"text": "Home rule is limited by controlling state law."},
            ]
            assert resumed.tool_calls[0].output == {"result_ids": ["chunk_live_1"]}
            assert resumed.retrieval_runs[0].payload["citations"] == [
                {"chunk_id": "chunk_live_1", "source_url": "https://example.test/live"}
            ]
            parent_counts_before = tuple(
                db.execute(
                    text(f"SELECT count(*) FROM {table} WHERE session_id=:session_id"),
                    {"session_id": resumed.id},
                ).scalar_one()
                for table in ("expert_messages", "expert_tool_calls", "expert_retrieval_runs")
            )
            forked = fork_expert_session(db, principal, resumed.id, label="Alternative path")
            parent_counts_after = tuple(
                db.execute(
                    text(f"SELECT count(*) FROM {table} WHERE session_id=:session_id"),
                    {"session_id": resumed.id},
                ).scalar_one()
                for table in ("expert_messages", "expert_tool_calls", "expert_retrieval_runs")
            )
            assert parent_counts_before == parent_counts_after == (2, 1, 1)
            assert forked.id != resumed.id
            assert forked.parent_session_id == resumed.id
            assert forked.conversation_id != resumed.conversation_id
            assert [message.role for message in forked.messages] == ["user", "assistant"]
            assert len(forked.messages) == 2
            assert len(forked.tool_calls) == len(forked.retrieval_runs) == 1
            assert forked.retrieval_runs[0].payload["message_id"] == forked.messages[0].id
            assert forked.retrieval_runs[0].payload["tool_call_id"] == forked.tool_calls[0].id
            assert forked.retrieval_runs[0].payload["citations"] == resumed.retrieval_runs[0].payload["citations"]
            assert db.execute(
                text(
                    """
                    SELECT count(*) FROM expert_session_forks
                    WHERE parent_session_id=:parent_id AND child_session_id=:child_id
                    """
                ),
                {"parent_id": resumed.id, "child_id": forked.id},
            ).scalar_one() == 1
            assert db.execute(
                text("SELECT count(*) FROM expert_feedback WHERE session_id=:session_id"),
                {"session_id": forked.id},
            ).scalar_one() == 0
            assert db.execute(
                text("SELECT count(*) FROM expert_memory_events WHERE session_id=:session_id"),
                {"session_id": forked.id},
            ).scalar_one() == 0
            assert db.execute(
                text("SELECT count(*) FROM expert_feedback WHERE session_id=:session_id"),
                {"session_id": resumed.id},
            ).scalar_one() == 1
            assert db.execute(
                text("SELECT count(*) FROM expert_memory_events WHERE session_id=:session_id"),
                {"session_id": resumed.id},
            ).scalar_one() == 1
            other_external_user = create_or_resume_expert_session(
                db,
                principal,
                "ks_state_civics",
                external_user_id=f"other_{external_user_id}",
                conversation_id=conversation_id,
            )
            other_conversation = create_or_resume_expert_session(
                db,
                principal,
                "ks_state_civics",
                external_user_id=external_user_id,
                conversation_id=f"other_{conversation_id}",
            )
            assert other_external_user.id not in {resumed.id, forked.id}
            assert other_conversation.id not in {resumed.id, forked.id, other_external_user.id}
            db.commit()

        for out_of_scope in (
            _principal(tenant_id="tenant_other"),
            _principal(business_instance_id="biz_other"),
            _principal(api_key_id="key_t002_b"),
            _principal(user_id="user_other"),
        ):
            with Session(engine) as db:
                set_rls_context(db, out_of_scope)
                assert get_expert_session(db, out_of_scope, session.id) is None
    finally:
        engine.dispose()
