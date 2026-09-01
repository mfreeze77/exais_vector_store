from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import jsonb_param, jsonb_text
from .ids import new_id
from .openai_compat import OPENAI_CITATION_MARKER_RE
from .security import sanitize_expert_interaction_data
from .schemas import (
    EXPERT_FEEDBACK_TYPES,
    ExpertFeedbackRecord,
    ExpertMessage,
    ExpertMemoryEvent,
    ExpertMemoryPolicy,
    ExpertRetrievalRun,
    ExpertSession,
    ExpertToolCall,
    ExpertTurnRecord,
    Principal,
)


DEFAULT_EXPERT_MEMORY_POLICY = ExpertMemoryPolicy()
_EXPERT_MEMORY_TYPES = {"retrieval_strategy", "answer_style", "preference"}


class ExpertSessionNotFound(LookupError):
    """Raised when a session is absent from the complete caller scope."""


def _required(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _principal_scope(principal: Principal) -> dict[str, str | None]:
    return {
        "tenant_id": _required(principal.tenant_id, "principal.tenant_id"),
        "biz_id": _required(principal.business_instance_id, "principal.business_instance_id"),
        "api_key_id": _optional(principal.api_key_id),
        "user_id": _optional(principal.user_id),
    }


def expert_session_key(
    principal: Principal,
    expert_id: str,
    external_user_id: str | None,
    conversation_id: str | None,
) -> str:
    """Return a stable, non-reversible key for one complete caller scope."""

    scope = _principal_scope(principal)
    identity = {
        "version": 1,
        "tenant_id": scope["tenant_id"],
        "business_instance_id": scope["biz_id"],
        "api_key_id": scope["api_key_id"],
        "user_id": scope["user_id"],
        "expert_id": _required(expert_id, "expert_id"),
        "external_user_id": _optional(external_user_id),
        "conversation_id": _optional(conversation_id),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"expsk_{hashlib.sha256(encoded).hexdigest()}"


def _session_params(principal: Principal, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_principal_scope(principal),
        "session_id": row["id"],
        "session_key": row["session_key"],
        "expert_id": row["expert_id"],
        "external_user_id": row["external_user_id"],
        "conversation_id": row["conversation_id"],
    }


def _session_row(
    db: Session,
    principal: Principal,
    session_id: str,
    *,
    for_update: bool = False,
) -> Mapping[str, Any] | None:
    params = {**_principal_scope(principal), "session_id": _required(session_id, "session_id")}
    lock = " FOR UPDATE" if for_update else ""
    return db.execute(
        text(
            """
            SELECT id, session_key, expert_id, api_key_id, user_id,
                   external_user_id, conversation_id, label, parent_session_id,
                   status, metadata, created_at, updated_at, last_active_at
            FROM expert_sessions
            WHERE id=:session_id
              AND tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND status <> 'deleted'
            """
            + lock
        ),
        params,
    ).mappings().first()


def _message_rows(db: Session, principal: Principal, session: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return db.execute(
        text(
            """
            SELECT id, session_id, role, content, sequence_no, metadata, created_at
            FROM expert_messages
            WHERE tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
            ORDER BY sequence_no ASC, id ASC
            """
        ),
        _session_params(principal, session),
    ).mappings().all()


def _tool_call_rows(db: Session, principal: Principal, session: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return db.execute(
        text(
            """
            SELECT id, session_id, message_id, tool_name, status, input, output,
                   error, sequence_no, created_at, completed_at
            FROM expert_tool_calls
            WHERE tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
            ORDER BY sequence_no ASC, id ASC
            """
        ),
        _session_params(principal, session),
    ).mappings().all()


def _retrieval_rows(db: Session, principal: Principal, session: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return db.execute(
        text(
            """
            SELECT id, session_id, message_id, tool_call_id, sequence_no, payload, created_at
            FROM expert_retrieval_runs
            WHERE tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
            ORDER BY sequence_no ASC, id ASC
            """
        ),
        _session_params(principal, session),
    ).mappings().all()


def _memory_rows(db: Session, principal: Principal, session: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return db.execute(
        text(
            """
            SELECT id, session_id, source_message_id, source_feedback_id, event_type,
                   status, payload, confidence, created_at, promoted_at, deleted_at
            FROM expert_memory_events
            WHERE tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
            ORDER BY created_at ASC, id ASC
            """
        ),
        _session_params(principal, session),
    ).mappings().all()


def _memory_event(item: Mapping[str, Any]) -> ExpertMemoryEvent:
    return ExpertMemoryEvent(
        id=item["id"],
        session_id=item["session_id"],
        source_message_id=item["source_message_id"],
        source_feedback_id=item["source_feedback_id"],
        event_type=item["event_type"],
        status=item["status"],
        payload=dict(item["payload"] or {}),
        confidence=item["confidence"],
        created_at=item["created_at"],
        promoted_at=item["promoted_at"],
        deleted_at=item["deleted_at"],
    )


def _hydrate_session(db: Session, principal: Principal, row: Mapping[str, Any]) -> ExpertSession:
    messages = [
        ExpertMessage(
            id=item["id"],
            session_id=item["session_id"],
            role=item["role"],
            content=item["content"],
            sequence_no=item["sequence_no"],
            metadata=dict(item["metadata"] or {}),
            created_at=item["created_at"],
        )
        for item in _message_rows(db, principal, row)
    ]
    tool_calls = [
        ExpertToolCall(
            id=item["id"],
            session_id=item["session_id"],
            message_id=item["message_id"],
            tool_name=item["tool_name"],
            status=item["status"],
            input=dict(item["input"] or {}),
            output=item["output"],
            error=item["error"],
            sequence_no=item["sequence_no"],
            created_at=item["created_at"],
            completed_at=item["completed_at"],
        )
        for item in _tool_call_rows(db, principal, row)
    ]
    retrieval_runs = [
        ExpertRetrievalRun(
            id=item["id"],
            session_id=item["session_id"],
            message_id=item["message_id"],
            tool_call_id=item["tool_call_id"],
            sequence_no=item["sequence_no"],
            payload=dict(item["payload"] or {}),
            created_at=item["created_at"],
        )
        for item in _retrieval_rows(db, principal, row)
    ]
    memory_events = [_memory_event(item) for item in _memory_rows(db, principal, row)]
    return ExpertSession(
        id=row["id"],
        session_key=row["session_key"],
        expert_id=row["expert_id"],
        api_key_id=row["api_key_id"],
        user_id=row["user_id"],
        external_user_id=row["external_user_id"],
        conversation_id=row["conversation_id"],
        label=row["label"],
        parent_session_id=row["parent_session_id"],
        status=row["status"],
        metadata=dict(row["metadata"] or {}),
        messages=messages,
        tool_calls=tool_calls,
        retrieval_runs=retrieval_runs,
        memory_events=memory_events,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_active_at=row["last_active_at"],
    )


def get_expert_session(db: Session, principal: Principal, session_id: str) -> ExpertSession | None:
    """Load prompt-relevant history from the caller's exact authenticated scope."""

    row = _session_row(db, principal, session_id)
    return _hydrate_session(db, principal, row) if row else None


def create_or_resume_expert_session(
    db: Session,
    principal: Principal,
    expert_id: str,
    *,
    external_user_id: str | None = None,
    conversation_id: str | None = None,
    label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExpertSession:
    """Create the full-scope session once, or resume its stored context."""

    scope = _principal_scope(principal)
    normalized_expert_id = _required(expert_id, "expert_id")
    normalized_external_user_id = _optional(external_user_id)
    normalized_conversation_id = _optional(conversation_id)
    key = expert_session_key(
        principal,
        normalized_expert_id,
        normalized_external_user_id,
        normalized_conversation_id,
    )
    params = {
        **scope,
        "id": new_id("exps"),
        "session_key": key,
        "expert_id": normalized_expert_id,
        "external_user_id": normalized_external_user_id,
        "conversation_id": normalized_conversation_id,
        "label": _optional(label),
        "metadata": jsonb_param(metadata or {}),
    }
    row = db.execute(
        jsonb_text(
            """
            INSERT INTO expert_sessions(
              id, tenant_id, business_instance_id, api_key_id, user_id,
              expert_id, external_user_id, conversation_id, session_key, label, metadata
            ) VALUES (
              :id, :tenant_id, :biz_id, :api_key_id, :user_id,
              :expert_id, :external_user_id, :conversation_id, :session_key, :label,
              CAST(:metadata AS jsonb)
            )
            ON CONFLICT (tenant_id, business_instance_id, session_key) DO UPDATE
              SET updated_at=now(), last_active_at=now()
              WHERE expert_sessions.api_key_id IS NOT DISTINCT FROM EXCLUDED.api_key_id
                AND expert_sessions.user_id IS NOT DISTINCT FROM EXCLUDED.user_id
                AND expert_sessions.expert_id=EXCLUDED.expert_id
                AND expert_sessions.external_user_id IS NOT DISTINCT FROM EXCLUDED.external_user_id
                AND expert_sessions.conversation_id IS NOT DISTINCT FROM EXCLUDED.conversation_id
                AND expert_sessions.status <> 'deleted'
            RETURNING id, session_key, expert_id, api_key_id, user_id,
                      external_user_id, conversation_id, label, parent_session_id,
                      status, metadata, created_at, updated_at, last_active_at
            """,
            "metadata",
        ),
        params,
    ).mappings().first()
    if not row:
        raise ExpertSessionNotFound("expert session scope does not match the caller")
    return _hydrate_session(db, principal, row)


def _next_sequence(
    db: Session,
    principal: Principal,
    session: Mapping[str, Any],
    table: str,
) -> int:
    if table not in {"expert_messages", "expert_tool_calls", "expert_retrieval_runs"}:
        raise ValueError("unsupported expert history table")
    value = db.execute(
        text(
            f"""
            SELECT coalesce(max(sequence_no), -1) + 1
            FROM {table}
            WHERE tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
            """
        ),
        _session_params(principal, session),
    ).scalar_one()
    return int(value)


def _touch_session(db: Session, principal: Principal, session: Mapping[str, Any]) -> None:
    db.execute(
        text(
            """
            UPDATE expert_sessions
            SET updated_at=now(), last_active_at=now()
            WHERE id=:session_id
              AND tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_key=:session_key
            """
        ),
        _session_params(principal, session),
    )


def record_expert_message(
    db: Session,
    principal: Principal,
    session_id: str,
    *,
    role: str,
    content: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    normalized_role = _required(role, "role")
    if normalized_role not in {"system", "user", "assistant", "tool"}:
        raise ValueError("role must be system, user, assistant, or tool")
    session = _session_row(db, principal, session_id, for_update=True)
    if not session:
        raise ExpertSessionNotFound("expert session not found")
    message_id = new_id("exmsg")
    params = {
        **_session_params(principal, session),
        "id": message_id,
        "role": normalized_role,
        "content": jsonb_param(content),
        "sequence_no": _next_sequence(db, principal, session, "expert_messages"),
        "metadata": jsonb_param(metadata or {}),
    }
    db.execute(
        jsonb_text(
            """
            INSERT INTO expert_messages(
              id, tenant_id, business_instance_id, api_key_id, user_id,
              expert_id, external_user_id, conversation_id, session_id, session_key,
              role, content, sequence_no, metadata
            ) VALUES (
              :id, :tenant_id, :biz_id, :api_key_id, :user_id,
              :expert_id, :external_user_id, :conversation_id, :session_id, :session_key,
              :role, CAST(:content AS jsonb), :sequence_no, CAST(:metadata AS jsonb)
            )
            """,
            "content",
            "metadata",
        ),
        params,
    )
    _touch_session(db, principal, session)
    return message_id


def record_expert_tool_call(
    db: Session,
    principal: Principal,
    session_id: str,
    *,
    tool_name: str,
    input: dict[str, Any] | None = None,
    output: Any | None = None,
    status: str = "completed",
    error: str | None = None,
    message_id: str | None = None,
) -> str:
    normalized_status = _required(status, "status")
    if normalized_status not in {"pending", "running", "completed", "failed"}:
        raise ValueError("invalid expert tool-call status")
    session = _session_row(db, principal, session_id, for_update=True)
    if not session:
        raise ExpertSessionNotFound("expert session not found")
    call_id = new_id("extool")
    params = {
        **_session_params(principal, session),
        "id": call_id,
        "message_id": _optional(message_id),
        "tool_name": _required(tool_name, "tool_name"),
        "status": normalized_status,
        "input": jsonb_param(input or {}),
        "output": jsonb_param(output),
        "error": error,
        "sequence_no": _next_sequence(db, principal, session, "expert_tool_calls"),
    }
    db.execute(
        jsonb_text(
            """
            INSERT INTO expert_tool_calls(
              id, tenant_id, business_instance_id, api_key_id, user_id,
              expert_id, external_user_id, conversation_id, session_id, session_key,
              message_id, tool_name, status, input, output, error, sequence_no, completed_at
            ) VALUES (
              :id, :tenant_id, :biz_id, :api_key_id, :user_id,
              :expert_id, :external_user_id, :conversation_id, :session_id, :session_key,
              :message_id, :tool_name, :status, CAST(:input AS jsonb), CAST(:output AS jsonb),
              :error, :sequence_no, CASE WHEN :status IN ('completed', 'failed') THEN now() END
            )
            """,
            "input",
            "output",
        ),
        params,
    )
    _touch_session(db, principal, session)
    return call_id


def record_expert_retrieval_run(
    db: Session,
    principal: Principal,
    session_id: str,
    payload: dict[str, Any],
) -> str:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    session = _session_row(db, principal, session_id, for_update=True)
    if not session:
        raise ExpertSessionNotFound("expert session not found")
    run_id = new_id("exret")
    params = {
        **_session_params(principal, session),
        "id": run_id,
        "message_id": _optional(payload.get("message_id")),
        "tool_call_id": _optional(payload.get("tool_call_id")),
        "sequence_no": _next_sequence(db, principal, session, "expert_retrieval_runs"),
        "payload": jsonb_param(payload),
    }
    db.execute(
        jsonb_text(
            """
            INSERT INTO expert_retrieval_runs(
              id, tenant_id, business_instance_id, api_key_id, user_id,
              expert_id, external_user_id, conversation_id, session_id, session_key,
              message_id, tool_call_id, sequence_no, payload
            ) VALUES (
              :id, :tenant_id, :biz_id, :api_key_id, :user_id,
              :expert_id, :external_user_id, :conversation_id, :session_id, :session_key,
              :message_id, :tool_call_id, :sequence_no, CAST(:payload AS jsonb)
            )
            """,
            "payload",
        ),
        params,
    )
    _touch_session(db, principal, session)
    return run_id


def _scoped_child_exists(
    db: Session,
    principal: Principal,
    session: Mapping[str, Any],
    *,
    table: str,
    record_id: str,
) -> bool:
    if table not in {"expert_messages", "expert_feedback"}:
        raise ValueError("unsupported expert session child table")
    row = db.execute(
        text(
            f"""
            SELECT id
            FROM {table}
            WHERE id=:record_id
              AND tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
            """
        ),
        {**_session_params(principal, session), "record_id": record_id},
    ).first()
    return row is not None


def _combined_guard_metadata(*guards: dict[str, Any] | None) -> dict[str, Any] | None:
    totals: dict[str, int] = {}
    for guard in guards:
        for item in (guard or {}).get("redactions") or []:
            kind = item.get("type")
            count = item.get("count")
            if isinstance(kind, str) and isinstance(count, int):
                totals[kind] = totals.get(kind, 0) + count
    if not totals:
        return None
    return {
        "id": "pii_secret_citation_guard_v1",
        "redactions": [{"type": kind, "count": totals[kind]} for kind in sorted(totals)],
    }


def _record_governance_audit(
    db: Session,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    session: Mapping[str, Any],
    metadata: dict[str, Any],
) -> str:
    audit_id = new_id("aud")
    db.execute(
        jsonb_text(
            """
            INSERT INTO audit_events(
              id, tenant_id, business_instance_id, user_id, api_key_id,
              event_type, action, resource_type, resource_id, metadata
            ) VALUES (
              :id, :tenant_id, :biz_id, :user_id, :api_key_id,
              'expert_governance', :action, :resource_type, :resource_id,
              CAST(:metadata AS jsonb)
            )
            """,
            "metadata",
        ),
        {
            **_principal_scope(principal),
            "id": audit_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "metadata": jsonb_param({
                "session_id": session["id"],
                "expert_id": session["expert_id"],
                "external_user_id": session["external_user_id"],
                "conversation_id": session["conversation_id"],
                **metadata,
            }),
        },
    )
    return audit_id


def record_expert_turn_accounting(
    db: Session,
    principal: Principal,
    response: Any,
    *,
    external_user_id: str | None = None,
    conversation_id: str | None = None,
) -> tuple[str, str]:
    """Write one usage event and one audit event for a completed expert turn.

    WAVE-125: both rows carry ``user_id`` and ``api_key_id`` from the principal so
    a user-bound key is attributed natively; ``external_user_id`` and
    ``conversation_id`` stay in metadata as the caller-side correlation ids.
    Returns ``(usage_event_id, audit_event_id)``.
    """

    scope = _principal_scope(principal)
    model_metadata = getattr(response, "model_metadata", None)
    usage = getattr(model_metadata, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", 0) or (input_tokens + output_tokens))
    retrieval_trace = getattr(response, "retrieval_trace", None)
    retrieval_status = getattr(retrieval_trace, "status", None)
    retrieval_runs = len(getattr(retrieval_trace, "runs", None) or [])
    expert_id = str(getattr(response, "expert_id", "") or "")
    session_id = str(getattr(response, "session_id", "") or "")
    provider = getattr(model_metadata, "provider", None)
    model = getattr(model_metadata, "model", None)
    correlation = {
        "expert_id": expert_id,
        "session_id": session_id,
        "external_user_id": _optional(external_user_id),
        "conversation_id": _optional(conversation_id),
    }
    usage_id = new_id("use")
    db.execute(
        jsonb_text(
            """
            INSERT INTO usage_events(
              id, tenant_id, business_instance_id, user_id, api_key_id,
              event_type, quantity, unit, provider, model, metadata
            ) VALUES (
              :id, :tenant_id, :biz_id, :user_id, :api_key_id,
              'expert.message', :quantity, 'token', :provider, :model, CAST(:metadata AS jsonb)
            )
            """,
            "metadata",
        ),
        {
            **scope,
            "id": usage_id,
            "quantity": total_tokens,
            "provider": provider,
            "model": model,
            "metadata": jsonb_param({
                **correlation,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "retrieval_status": retrieval_status,
                "retrieval_runs": retrieval_runs,
                "citation_count": len(getattr(response, "citations", None) or []),
                "model_profile_id": getattr(model_metadata, "model_profile_id", None),
            }),
        },
    )
    audit_id = new_id("aud")
    db.execute(
        jsonb_text(
            """
            INSERT INTO audit_events(
              id, tenant_id, business_instance_id, user_id, api_key_id,
              event_type, action, resource_type, resource_id, security_level, metadata
            ) VALUES (
              :id, :tenant_id, :biz_id, :user_id, :api_key_id,
              'expert', 'message', 'expert_session', :resource_id, :security_level, CAST(:metadata AS jsonb)
            )
            """,
            "metadata",
        ),
        {
            **scope,
            "id": audit_id,
            "resource_id": session_id or None,
            "security_level": principal.max_security_level,
            "metadata": jsonb_param({
                **correlation,
                "usage_event_id": usage_id,
                "retrieval_status": retrieval_status,
                "model_profile_id": getattr(model_metadata, "model_profile_id", None),
            }),
        },
    )
    return usage_id, audit_id


def record_expert_feedback(
    db: Session,
    principal: Principal,
    session_id: str,
    *,
    feedback_type: str,
    rating: int | None = None,
    comment: str | None = None,
    payload: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> str:
    """Persist guarded feedback only when its optional message has the exact session scope."""

    normalized_feedback_type = _required(feedback_type, "feedback_type")
    if normalized_feedback_type not in EXPERT_FEEDBACK_TYPES:
        raise ValueError("unsupported expert feedback type")
    session = _session_row(db, principal, session_id, for_update=True)
    if not session:
        raise ExpertSessionNotFound("expert session not found")
    normalized_message_id = _optional(message_id)
    if normalized_message_id and not _scoped_child_exists(
        db,
        principal,
        session,
        table="expert_messages",
        record_id=normalized_message_id,
    ):
        raise ExpertSessionNotFound("expert feedback message not found")
    if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5):
        raise ValueError("rating must be an integer between 1 and 5")
    guarded_comment, comment_guard = sanitize_expert_interaction_data(comment)
    guarded_payload, payload_guard = sanitize_expert_interaction_data(payload or {})
    redaction = _combined_guard_metadata(comment_guard, payload_guard)
    if redaction:
        guarded_payload = {**guarded_payload, "redaction": redaction}
    feedback_id = new_id("exfb")
    db.execute(
        jsonb_text(
            """
            INSERT INTO expert_feedback(
              id, tenant_id, business_instance_id, api_key_id, user_id,
              expert_id, external_user_id, conversation_id, session_id, session_key,
              message_id, feedback_type, rating, comment, payload
            ) VALUES (
              :id, :tenant_id, :biz_id, :api_key_id, :user_id,
              :expert_id, :external_user_id, :conversation_id, :session_id, :session_key,
              :message_id, :feedback_type, :rating, :comment, CAST(:payload AS jsonb)
            )
            """,
            "payload",
        ),
        {
            **_session_params(principal, session),
            "id": feedback_id,
            "message_id": normalized_message_id,
            "feedback_type": normalized_feedback_type,
            "rating": rating,
            "comment": guarded_comment,
            "payload": jsonb_param(guarded_payload),
        },
    )
    _record_governance_audit(
        db,
        principal,
        action="feedback_created",
        resource_type="expert_feedback",
        resource_id=feedback_id,
        session=session,
        metadata={
            "feedback_type": normalized_feedback_type,
            "message_id": normalized_message_id,
            "redacted": redaction is not None,
        },
    )
    _touch_session(db, principal, session)
    return feedback_id


def record_expert_memory_event(
    db: Session,
    principal: Principal,
    session_id: str,
    *,
    event_type: str,
    payload: dict[str, Any],
    confidence: float | None = None,
    source_message_id: str | None = None,
    source_feedback_id: str | None = None,
    event_id: str | None = None,
) -> str:
    """Persist a typed, non-authoritative candidate after source and content governance."""

    normalized_event_type = _required(event_type, "event_type")
    if normalized_event_type not in _EXPERT_MEMORY_TYPES:
        raise ValueError("unsupported expert memory type")
    if confidence is None or not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    if not isinstance(payload, dict):
        raise ValueError("expert memory payload must be an object")
    session = _session_row(db, principal, session_id, for_update=True)
    if not session:
        raise ExpertSessionNotFound("expert session not found")
    normalized_message_id = _optional(source_message_id)
    normalized_feedback_id = _optional(source_feedback_id)
    for table, record_id, label in (
        ("expert_messages", normalized_message_id, "source message"),
        ("expert_feedback", normalized_feedback_id, "source feedback"),
    ):
        if record_id and not _scoped_child_exists(
            db,
            principal,
            session,
            table=table,
            record_id=record_id,
        ):
            raise ExpertSessionNotFound(f"expert memory {label} not found")
    guarded_payload, guard = sanitize_expert_interaction_data(payload)
    if OPENAI_CITATION_MARKER_RE.search(json.dumps(guarded_payload, ensure_ascii=False)):
        raise ValueError("expert memory cannot contain citation markers")
    governed_payload = {
        **guarded_payload,
        "memory_type": normalized_event_type,
        "authority": "none",
        "citation_eligible": False,
    }
    if guard:
        governed_payload["redaction"] = guard
    memory_event_id = _required(event_id, "event_id") if event_id is not None else new_id("exmem")
    db.execute(
        jsonb_text(
            """
            INSERT INTO expert_memory_events(
              id, tenant_id, business_instance_id, api_key_id, user_id,
              expert_id, external_user_id, conversation_id, session_id, session_key,
              source_message_id, source_feedback_id, event_type, status, payload, confidence
            ) VALUES (
              :id, :tenant_id, :biz_id, :api_key_id, :user_id,
              :expert_id, :external_user_id, :conversation_id, :session_id, :session_key,
              :source_message_id, :source_feedback_id, :event_type, 'candidate',
              CAST(:payload AS jsonb), :confidence
            )
            """,
            "payload",
        ),
        {
            **_session_params(principal, session),
            "id": memory_event_id,
            "source_message_id": normalized_message_id,
            "source_feedback_id": normalized_feedback_id,
            "event_type": normalized_event_type,
            "payload": jsonb_param(governed_payload),
            "confidence": confidence,
        },
    )
    _record_governance_audit(
        db,
        principal,
        action="memory_candidate_created",
        resource_type="expert_memory_event",
        resource_id=memory_event_id,
        session=session,
        metadata={
            "memory_type": normalized_event_type,
            "source_message_id": normalized_message_id,
            "source_feedback_id": normalized_feedback_id,
            "confidence": confidence,
            "redacted": guard is not None,
            "citation_eligible": False,
        },
    )
    _touch_session(db, principal, session)
    return memory_event_id


def extract_candidate_memory_events(
    turn: ExpertTurnRecord,
    policy: ExpertMemoryPolicy,
) -> list[ExpertMemoryEvent]:
    """Build inert, typed candidates from explicit caller input; this function never persists."""

    if not policy.enabled:
        return []
    if len(turn.memory_candidates) > policy.max_candidates_per_turn:
        raise ValueError("memory candidate count exceeds policy")
    allowed = set(policy.allowed_memory_types)
    events: list[ExpertMemoryEvent] = []
    for candidate in turn.memory_candidates:
        if candidate.memory_type not in allowed:
            raise ValueError("memory candidate type is not allowed by policy")
        guarded_instruction, guard = sanitize_expert_interaction_data(candidate.instruction)
        if OPENAI_CITATION_MARKER_RE.search(guarded_instruction):
            raise ValueError("expert memory cannot contain citation markers")
        payload: dict[str, Any] = {
            "memory_type": candidate.memory_type,
            "instruction": guarded_instruction,
            "authority": "none",
            "citation_eligible": False,
        }
        if guard:
            payload["redaction"] = guard
        events.append(ExpertMemoryEvent(
            id=new_id("exmem"),
            session_id=turn.session_id,
            source_message_id=turn.source_message_id,
            source_feedback_id=turn.source_feedback_id,
            event_type=candidate.memory_type,
            status="candidate",
            payload=payload,
            confidence=candidate.confidence,
        ))
    return events


def get_expert_feedback_record(
    db: Session,
    principal: Principal,
    session_id: str,
    feedback_id: str,
) -> ExpertFeedbackRecord | None:
    session = _session_row(db, principal, session_id)
    if not session:
        return None
    row = db.execute(
        text(
            """
            SELECT id, session_id, message_id, feedback_type, rating, comment, payload, created_at
            FROM expert_feedback
            WHERE id=:record_id
              AND tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
            """
        ),
        {**_session_params(principal, session), "record_id": _required(feedback_id, "feedback_id")},
    ).mappings().first()
    if not row:
        return None
    return ExpertFeedbackRecord(
        id=row["id"],
        session_id=row["session_id"],
        message_id=row["message_id"],
        feedback_type=row["feedback_type"],
        rating=row["rating"],
        comment=row["comment"],
        payload=dict(row["payload"] or {}),
        created_at=row["created_at"],
    )


def list_expert_memory_events(
    db: Session,
    principal: Principal,
    session_id: str,
) -> list[ExpertMemoryEvent]:
    session = _session_row(db, principal, session_id)
    if not session:
        raise ExpertSessionNotFound("expert session not found")
    return [_memory_event(row) for row in _memory_rows(db, principal, session)]


def _memory_event_row(
    db: Session,
    principal: Principal,
    session: Mapping[str, Any],
    memory_event_id: str,
    *,
    for_update: bool = False,
) -> Mapping[str, Any] | None:
    lock = " FOR UPDATE" if for_update else ""
    return db.execute(
        text(
            """
            SELECT id, session_id, source_message_id, source_feedback_id, event_type,
                   status, payload, confidence, created_at, promoted_at, deleted_at
            FROM expert_memory_events
            WHERE id=:record_id
              AND tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
            """
            + lock
        ),
        {
            **_session_params(principal, session),
            "record_id": _required(memory_event_id, "memory_event_id"),
        },
    ).mappings().first()


def promote_expert_memory_event(
    db: Session,
    principal: Principal,
    session_id: str,
    memory_event_id: str,
    *,
    policy: ExpertMemoryPolicy,
    explicit_opt_in: bool,
) -> ExpertMemoryEvent:
    if not policy.enabled:
        raise ValueError("expert memory policy is disabled")
    if policy.promotion_requires_explicit_opt_in and explicit_opt_in is not True:
        raise ValueError("memory promotion requires explicit opt-in")
    session = _session_row(db, principal, session_id, for_update=True)
    if not session:
        raise ExpertSessionNotFound("expert session not found")
    row = _memory_event_row(db, principal, session, memory_event_id, for_update=True)
    if not row:
        raise ExpertSessionNotFound("expert memory event not found")
    if row["event_type"] not in set(policy.allowed_memory_types):
        raise ValueError("memory candidate type is not allowed by policy")
    confidence = row["confidence"]
    if confidence is None or float(confidence) < policy.minimum_promotion_confidence:
        raise ValueError("memory candidate confidence is below promotion policy")
    if row["status"] == "promoted":
        return _memory_event(row)
    if row["status"] != "candidate":
        raise ValueError("only candidate memory can be promoted")
    promoted = db.execute(
        text(
            """
            UPDATE expert_memory_events
            SET status='promoted', promoted_at=now(), deleted_at=NULL
            WHERE id=:record_id
              AND tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
              AND status='candidate'
            RETURNING id, session_id, source_message_id, source_feedback_id, event_type,
                      status, payload, confidence, created_at, promoted_at, deleted_at
            """
        ),
        {**_session_params(principal, session), "record_id": row["id"]},
    ).mappings().first()
    if not promoted:
        raise ExpertSessionNotFound("expert memory event not found")
    _record_governance_audit(
        db,
        principal,
        action="memory_promoted",
        resource_type="expert_memory_event",
        resource_id=row["id"],
        session=session,
        metadata={
            "memory_type": row["event_type"],
            "confidence": confidence,
            "explicit_opt_in": True,
            "citation_eligible": False,
        },
    )
    _touch_session(db, principal, session)
    return _memory_event(promoted)


def delete_expert_memory_event(
    db: Session,
    principal: Principal,
    session_id: str,
    memory_event_id: str,
) -> ExpertMemoryEvent:
    session = _session_row(db, principal, session_id, for_update=True)
    if not session:
        raise ExpertSessionNotFound("expert session not found")
    row = _memory_event_row(db, principal, session, memory_event_id, for_update=True)
    if not row:
        raise ExpertSessionNotFound("expert memory event not found")
    if row["status"] == "deleted":
        return _memory_event(row)
    tombstone = {
        "memory_type": row["event_type"],
        "authority": "none",
        "citation_eligible": False,
        "deleted": True,
    }
    deleted = db.execute(
        jsonb_text(
            """
            UPDATE expert_memory_events
            SET status='deleted', payload=CAST(:payload AS jsonb), deleted_at=now()
            WHERE id=:record_id
              AND tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND api_key_id IS NOT DISTINCT FROM :api_key_id
              AND user_id IS NOT DISTINCT FROM :user_id
              AND expert_id=:expert_id
              AND external_user_id IS NOT DISTINCT FROM :external_user_id
              AND conversation_id IS NOT DISTINCT FROM :conversation_id
              AND session_id=:session_id
              AND session_key=:session_key
            RETURNING id, session_id, source_message_id, source_feedback_id, event_type,
                      status, payload, confidence, created_at, promoted_at, deleted_at
            """,
            "payload",
        ),
        {
            **_session_params(principal, session),
            "record_id": row["id"],
            "payload": jsonb_param(tombstone),
        },
    ).mappings().first()
    if not deleted:
        raise ExpertSessionNotFound("expert memory event not found")
    _record_governance_audit(
        db,
        principal,
        action="memory_deleted",
        resource_type="expert_memory_event",
        resource_id=row["id"],
        session=session,
        metadata={
            "memory_type": row["event_type"],
            "payload_scrubbed": True,
            "citation_eligible": False,
        },
    )
    _touch_session(db, principal, session)
    return _memory_event(deleted)


def fork_expert_session(
    db: Session,
    principal: Principal,
    session_id: str,
    *,
    label: str | None = None,
) -> ExpertSession:
    """Copy prompt-relevant history into a child without updating the parent."""

    parent = _session_row(db, principal, session_id, for_update=True)
    if not parent:
        raise ExpertSessionNotFound("expert session not found")

    parent_messages = _message_rows(db, principal, parent)
    parent_tool_calls = _tool_call_rows(db, principal, parent)
    parent_retrieval_runs = _retrieval_rows(db, principal, parent)
    child_id = new_id("exps")
    child_conversation_id = f"{parent['conversation_id'] or 'session'}:fork:{child_id}"
    child_key = expert_session_key(
        principal,
        parent["expert_id"],
        parent["external_user_id"],
        child_conversation_id,
    )
    scope = _principal_scope(principal)
    child_label = _optional(label) if label is not None else parent["label"]
    db.execute(
        jsonb_text(
            """
            INSERT INTO expert_sessions(
              id, tenant_id, business_instance_id, api_key_id, user_id,
              expert_id, external_user_id, conversation_id, session_key, label,
              parent_session_id, metadata
            ) VALUES (
              :id, :tenant_id, :biz_id, :api_key_id, :user_id,
              :expert_id, :external_user_id, :conversation_id, :session_key, :label,
              :parent_session_id, CAST(:metadata AS jsonb)
            )
            """,
            "metadata",
        ),
        {
            **scope,
            "id": child_id,
            "expert_id": parent["expert_id"],
            "external_user_id": parent["external_user_id"],
            "conversation_id": child_conversation_id,
            "session_key": child_key,
            "label": child_label,
            "parent_session_id": parent["id"],
            "metadata": jsonb_param(dict(parent["metadata"] or {})),
        },
    )

    child_scope = {
        **scope,
        "session_id": child_id,
        "session_key": child_key,
        "expert_id": parent["expert_id"],
        "external_user_id": parent["external_user_id"],
        "conversation_id": child_conversation_id,
    }
    message_ids: dict[str, str] = {}
    for item in parent_messages:
        copied_id = new_id("exmsg")
        message_ids[item["id"]] = copied_id
        db.execute(
            jsonb_text(
                """
                INSERT INTO expert_messages(
                  id, tenant_id, business_instance_id, api_key_id, user_id,
                  expert_id, external_user_id, conversation_id, session_id, session_key,
                  source_message_id, role, content, sequence_no, metadata
                ) VALUES (
                  :id, :tenant_id, :biz_id, :api_key_id, :user_id,
                  :expert_id, :external_user_id, :conversation_id, :session_id, :session_key,
                  :source_message_id, :role, CAST(:content AS jsonb), :sequence_no,
                  CAST(:metadata AS jsonb)
                )
                """,
                "content",
                "metadata",
            ),
            {
                **child_scope,
                "id": copied_id,
                "source_message_id": item["id"],
                "role": item["role"],
                "content": jsonb_param(item["content"]),
                "sequence_no": item["sequence_no"],
                "metadata": jsonb_param(dict(item["metadata"] or {})),
            },
        )

    tool_call_ids: dict[str, str] = {}
    for item in parent_tool_calls:
        copied_id = new_id("extool")
        tool_call_ids[item["id"]] = copied_id
        db.execute(
            jsonb_text(
                """
                INSERT INTO expert_tool_calls(
                  id, tenant_id, business_instance_id, api_key_id, user_id,
                  expert_id, external_user_id, conversation_id, session_id, session_key,
                  message_id, source_tool_call_id, tool_name, status, input, output,
                  error, sequence_no, completed_at
                ) VALUES (
                  :id, :tenant_id, :biz_id, :api_key_id, :user_id,
                  :expert_id, :external_user_id, :conversation_id, :session_id, :session_key,
                  :message_id, :source_tool_call_id, :tool_name, :status,
                  CAST(:input AS jsonb), CAST(:output AS jsonb), :error, :sequence_no,
                  :completed_at
                )
                """,
                "input",
                "output",
            ),
            {
                **child_scope,
                "id": copied_id,
                "message_id": message_ids.get(item["message_id"]),
                "source_tool_call_id": item["id"],
                "tool_name": item["tool_name"],
                "status": item["status"],
                "input": jsonb_param(dict(item["input"] or {})),
                "output": jsonb_param(item["output"]),
                "error": item["error"],
                "sequence_no": item["sequence_no"],
                "completed_at": item["completed_at"],
            },
        )

    for item in parent_retrieval_runs:
        copied_payload = dict(item["payload"] or {})
        if copied_payload.get("message_id"):
            copied_payload["message_id"] = message_ids.get(copied_payload["message_id"])
        if copied_payload.get("tool_call_id"):
            copied_payload["tool_call_id"] = tool_call_ids.get(copied_payload["tool_call_id"])
        db.execute(
            jsonb_text(
                """
                INSERT INTO expert_retrieval_runs(
                  id, tenant_id, business_instance_id, api_key_id, user_id,
                  expert_id, external_user_id, conversation_id, session_id, session_key,
                  message_id, tool_call_id, source_retrieval_run_id, sequence_no, payload
                ) VALUES (
                  :id, :tenant_id, :biz_id, :api_key_id, :user_id,
                  :expert_id, :external_user_id, :conversation_id, :session_id, :session_key,
                  :message_id, :tool_call_id, :source_retrieval_run_id, :sequence_no,
                  CAST(:payload AS jsonb)
                )
                """,
                "payload",
            ),
            {
                **child_scope,
                "id": new_id("exret"),
                "message_id": message_ids.get(item["message_id"]),
                "tool_call_id": tool_call_ids.get(item["tool_call_id"]),
                "source_retrieval_run_id": item["id"],
                "sequence_no": item["sequence_no"],
                "payload": jsonb_param(copied_payload),
            },
        )

    db.execute(
        text(
            """
            INSERT INTO expert_session_forks(
              id, tenant_id, business_instance_id, api_key_id, user_id,
              expert_id, external_user_id, conversation_id,
              parent_session_id, parent_session_key, child_session_id, child_session_key, label
            ) VALUES (
              :id, :tenant_id, :biz_id, :api_key_id, :user_id,
              :expert_id, :external_user_id, :conversation_id,
              :parent_session_id, :parent_session_key, :child_session_id, :child_session_key, :label
            )
            """
        ),
        {
            **scope,
            "id": new_id("exfork"),
            "expert_id": parent["expert_id"],
            "external_user_id": parent["external_user_id"],
            "conversation_id": child_conversation_id,
            "parent_session_id": parent["id"],
            "parent_session_key": parent["session_key"],
            "child_session_id": child_id,
            "child_session_key": child_key,
            "label": child_label,
        },
    )
    child = _session_row(db, principal, child_id)
    if not child:
        raise RuntimeError("forked expert session was not visible in caller scope")
    return _hydrate_session(db, principal, child)
