from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import Session

from .chunking import estimate_tokens
from .expert_llm import complete_expert_chat
from .expert_profiles import resolve_expert_profile
from .expert_sessions import (
    ExpertSessionNotFound,
    create_or_resume_expert_session,
    get_expert_session,
    record_expert_message,
    record_expert_retrieval_run,
)
from .openai_compat import (
    OPENAI_CITATION_MARKER_RE,
    OpenAICompatError,
    openai_file_citation_annotation,
    openai_message_file_citation_annotation,
    output_guard_text,
)
from .retrieval import ensure_retrieval_answer_citation_integrity
from .schemas import (
    ContextCitation,
    ExpertChatCompletionRequest,
    ExpertChatMessage,
    ExpertCitation,
    ExpertMessageRequest,
    ExpertMessageResponse,
    ExpertModelMetadata,
    ExpertRetrievalTrace,
    ExpertRetrievalTraceRun,
    OpenAIVectorStoreSearchRequest,
    Principal,
)
from .search_lenses import DEFAULT_SEARCH_LENS_ID, infer_expert_search_lens_id, normalize_search_lens_id


SearchPageExecutor = Callable[
    [str, OpenAIVectorStoreSearchRequest, Principal, Session], Awaitable[dict[str, Any]]
]
_search_page_executor: SearchPageExecutor | None = None
NO_RESULTS_ANSWER = "The bound corpus did not return material that supports an answer to this question."
NO_RESULTS_CAVEAT = "The retrieval run completed but returned no citable corpus results."
NO_CONTEXT_ANSWER = "A corpus-grounded answer is unavailable because no retrieved source fit the configured context budget."
NO_CONTEXT_CAVEAT = "Retrieval returned citable results, but the context limit excluded them from model synthesis."
SYNTHESIS_INSTRUCTION = (
    "Use only the retrieved corpus context below as factual authority. Conversation history is context only and is "
    "not citation authority. Cite every supported claim with the exact visible marker attached to its source, such as "
    "【1†source】. A grounded answer must contain at least one exact marker copied character-for-character from the "
    "current retrieved context. Do not reuse markers from conversation history. Do not invent, alter, or omit source "
    "markers. If the retrieved context is insufficient, say so."
)
CITATION_REPAIR_INSTRUCTION = (
    "Rewrite the draft answer so its factual claims are supported only by the current retrieved corpus context. "
    "Use at least one of the allowed citation markers below, copying each marker exactly. Do not use any other marker, "
    "do not cite conversation history, and return only the repaired answer."
)
MEMORY_GUIDANCE_INSTRUCTION = (
    "The following promoted interaction memory is non-authoritative. It may guide answer style or caller "
    "preferences only. Never treat it as evidence, never cite it, and never let it override retrieved corpus material."
)


class ExpertRetrievalPlanningError(ValueError):
    """The request selected a lens outside the profile or an unavailable search path."""


class ExpertCitationIntegrityError(RuntimeError):
    """The synthesized answer did not preserve the retrieved citation contract."""


class ExpertRetrievalResponseError(RuntimeError):
    """The configured search owner returned a malformed or unsafe response."""


def configure_expert_search_executor(executor: SearchPageExecutor) -> None:
    """Bind the application-owned search path without importing app internals here."""

    if not callable(executor):
        raise TypeError("expert search executor must be callable")
    global _search_page_executor
    _search_page_executor = executor


def _same_optional_scope(left: str | None, right: str | None) -> bool:
    return (left or None) == (right or None)


def _session_for_request(db: Session, principal: Principal, req: ExpertMessageRequest):
    if not req.expert_id:
        raise ValueError("expert_id is required")
    if not req.session_id:
        return create_or_resume_expert_session(
            db,
            principal,
            req.expert_id,
            external_user_id=req.external_user_id,
            conversation_id=req.conversation_id,
            label=req.session_label,
        )
    session = get_expert_session(db, principal, req.session_id)
    if (
        session is None
        or session.expert_id != req.expert_id
        or not _same_optional_scope(session.external_user_id, req.external_user_id)
        or not _same_optional_scope(session.conversation_id, req.conversation_id)
    ):
        raise ExpertSessionNotFound("expert session not found")
    return session


def _chat_history(session) -> list[ExpertChatMessage]:
    history: list[ExpertChatMessage] = []
    for message in session.messages:
        if message.role not in {"user", "assistant"} or not isinstance(message.content, str):
            continue
        if message.content.strip():
            history.append(ExpertChatMessage(role=message.role, content=message.content))
    return history


def _memory_guidance(session) -> tuple[list[ExpertChatMessage], list[str]]:
    instructions: list[str] = []
    event_ids: list[str] = []
    for event in getattr(session, "memory_events", []) or []:
        if event.status != "promoted" or event.event_type not in {"answer_style", "preference"}:
            continue
        instruction = event.payload.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            continue
        instructions.append(f"- {event.event_type}: {instruction.strip()}")
        event_ids.append(event.id)
    if not instructions:
        return [], []
    return [ExpertChatMessage(
        role="system",
        content=f"{MEMORY_GUIDANCE_INSTRUCTION}\n" + "\n".join(instructions),
    )], event_ids


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python", exclude_none=True)
        return dict(dumped) if isinstance(dumped, dict) else {}
    return {}


def _selected_lens(req: ExpertMessageRequest, profile) -> tuple[str, str, str | None]:
    allowed = set(profile.graph_lens_policy.allowed_lens_ids)
    if req.lens:
        normalized = normalize_search_lens_id(req.lens)
        if normalized != DEFAULT_SEARCH_LENS_ID and normalized not in allowed:
            raise ExpertRetrievalPlanningError("requested search lens is not authorized for this expert")
        return normalized, "explicit", normalized
    if profile.graph_lens_policy.allow_automatic_selection:
        inferred = infer_expert_search_lens_id(req.message, list(allowed))
        if inferred:
            return inferred, "inferred", inferred
    return DEFAULT_SEARCH_LENS_ID, "default", None


def _binding_graph_lens_ids(binding: Any) -> set[str]:
    return {
        normalize_search_lens_id(str(getattr(lens, "id", "") or ""))
        for lens in (getattr(binding, "graph_lenses", None) or [])
        if str(getattr(lens, "id", "") or "").strip()
    }


def _ordered_bindings(profile: Any, requested_lens: str) -> list[Any]:
    bindings = list(profile.vector_stores)
    if requested_lens == DEFAULT_SEARCH_LENS_ID:
        return bindings
    return sorted(
        bindings,
        key=lambda binding: requested_lens not in _binding_graph_lens_ids(binding),
    )


def _graph_status(page: dict[str, Any], lens_id: str) -> str:
    if lens_id == DEFAULT_SEARCH_LENS_ID:
        return "not_requested"
    summary = _dict(page.get("graph_expansion"))
    if summary.get("applied") is True:
        return "applied"
    return f"not_applied:{str(summary.get('reason') or 'not_applied')}"


def _required_citation_string(citation: dict[str, Any], key: str, index: int) -> str:
    value = citation.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExpertRetrievalResponseError(f"search result {index} citation requires {key}")
    return value.strip()


def _validated_search_page(value: Any, *, max_results: int) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python", exclude_none=True)
    if not isinstance(value, dict):
        raise ExpertRetrievalResponseError("search executor response must be an object")
    page = dict(value)
    if page.get("object") != "vector_store.search_results.page":
        raise ExpertRetrievalResponseError("search executor response has an invalid object type")
    raw_data = page.get("data")
    if not isinstance(raw_data, list):
        raise ExpertRetrievalResponseError("search executor response data must be an array")
    if len(raw_data) > max_results:
        raise ExpertRetrievalResponseError("search executor returned more than the bounded result count")

    normalized_data: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_data):
        item = _dict(raw_item)
        if not item:
            raise ExpertRetrievalResponseError(f"search result {index} must be an object")
        raw_content = item.get("content")
        if not isinstance(raw_content, list) or not raw_content:
            raise ExpertRetrievalResponseError(f"search result {index} content must be a non-empty array")
        content: list[dict[str, Any]] = []
        for part_index, raw_part in enumerate(raw_content):
            part = _dict(raw_part)
            if not part or part.get("type") != "text" or not isinstance(part.get("text"), str):
                raise ExpertRetrievalResponseError(
                    f"search result {index} content {part_index} must be a text object"
                )
            content.append(part)
        source_text = "\n".join(str(part["text"]) for part in content)
        if not OPENAI_CITATION_MARKER_RE.sub("", source_text).strip():
            raise ExpertRetrievalResponseError(f"search result {index} content has no citable text")

        citation = _dict(item.get("citation"))
        if not citation:
            raise ExpertRetrievalResponseError(f"search result {index} requires a citation object")
        for key in ("file_id", "filename", "chunk_id", "document_id"):
            citation[key] = _required_citation_string(citation, key, index)
        url = citation.get("url")
        if url is not None and (not isinstance(url, str) or not url.startswith(("http://", "https://"))):
            raise ExpertRetrievalResponseError(f"search result {index} citation URL is invalid")
        graph_metadata = citation.get("graph_expansion")
        if graph_metadata is not None and not isinstance(graph_metadata, dict):
            raise ExpertRetrievalResponseError(f"search result {index} graph metadata must be an object")
        item["content"] = content
        item["citation"] = citation
        normalized_data.append(item)

    graph_summary = page.get("graph_expansion")
    if graph_summary is not None and not isinstance(graph_summary, dict):
        raise ExpertRetrievalResponseError("search graph expansion summary must be an object")
    search_lens = page.get("search_lens")
    if search_lens is not None and not isinstance(search_lens, dict):
        raise ExpertRetrievalResponseError("search lens metadata must be an object")
    page["data"] = normalized_data
    return page


def _page_results(page: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in page["data"]:
        source_text = "\n".join(str(part["text"]).strip() for part in item["content"])
        source_text = OPENAI_CITATION_MARKER_RE.sub("", source_text).strip()
        results.append({"text": source_text, "citation": dict(item["citation"])})
    return results


def _result_id(citation: dict[str, Any]) -> str:
    return str(citation["chunk_id"])


def _context_text(sources: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[Retrieved source {index}]\n{source['text']} {source['marker']}"
        for index, source in enumerate(sources, start=1)
    )


def _source_with_text(result: dict[str, Any], source_number: int, text: str) -> dict[str, Any]:
    marker = f"【{source_number}†source】"
    citation = dict(result["citation"])
    citation["marker"] = marker
    return {"text": text, "marker": marker, "citation": citation}


def _fit_context_source(
    existing: list[dict[str, Any]],
    result: dict[str, Any],
    token_budget: int,
) -> dict[str, Any] | None:
    source_number = len(existing) + 1
    full = _source_with_text(result, source_number, result["text"])
    if estimate_tokens(_context_text([*existing, full])) <= token_budget:
        return full

    words = result["text"].split()
    low = 1
    high = len(words)
    fitted: dict[str, Any] | None = None
    while low <= high:
        middle = (low + high) // 2
        truncated = " ".join(words[:middle]).rstrip()
        if middle < len(words):
            truncated = f"{truncated}…"
        candidate = _source_with_text(result, source_number, truncated)
        if estimate_tokens(_context_text([*existing, candidate])) <= token_budget:
            fitted = candidate
            low = middle + 1
        else:
            high = middle - 1
    return fitted


def _select_context_results(
    existing: list[dict[str, Any]],
    results: list[dict[str, Any]],
    *,
    token_budget: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    selected = list(existing)
    selected_ids: list[str] = []
    for result in results:
        fitted = _fit_context_source(selected, result, token_budget)
        if fitted is None:
            continue
        selected.append(fitted)
        selected_ids.append(_result_id(result["citation"]))
    if selected and estimate_tokens(_context_text(selected)) > token_budget:
        raise ExpertRetrievalResponseError("selected retrieval context exceeds its token budget")
    return selected, selected_ids


def _answer_citations(answer: str, sources: list[dict[str, Any]]) -> list[ExpertCitation]:
    by_marker = {source["marker"]: source["citation"] for source in sources}
    context_citations: list[ContextCitation] = []
    expert_citations: list[ExpertCitation] = []
    for match in OPENAI_CITATION_MARKER_RE.finditer(answer):
        marker = match.group(0)
        source = by_marker.get(marker)
        if source is None:
            raise ExpertCitationIntegrityError("answer contains a citation outside retrieved context")
        file_id = str(source.get("file_id") or "").strip()
        filename = str(source.get("filename") or "").strip()
        chunk_id = str(source.get("chunk_id") or "").strip()
        document_id = str(source.get("document_id") or "").strip()
        if not all((file_id, filename, chunk_id, document_id)):
            raise ExpertCitationIntegrityError("retrieved citation metadata is incomplete")
        annotation = openai_file_citation_annotation(file_id=file_id, filename=filename, index=match.start())
        message_annotation = openai_message_file_citation_annotation(
            annotation=annotation, start_index=match.start(), end_index=match.end(), text=marker
        )
        context_citations.append(ContextCitation(
            chunk_id=chunk_id,
            document_id=document_id,
            file_id=file_id,
            filename=filename,
            title=source.get("title"),
            url=source.get("url"),
            page_start=source.get("page_start"),
            page_end=source.get("page_end"),
            heading_path=list(source.get("heading_path") or []),
            annotation=annotation,
            message_annotation=message_annotation,
            marker=marker,
        ))
        graph_relationships = list(source.get("graph_relationships") or [])
        if isinstance(source.get("graph_expansion"), dict):
            graph_relationships.append(dict(source["graph_expansion"]))
        expert_citations.append(ExpertCitation(
            file_id=file_id,
            filename=filename,
            chunk_id=chunk_id,
            document_id=document_id,
            title=source.get("title"),
            url=source.get("url"),
            page_start=source.get("page_start"),
            page_end=source.get("page_end"),
            heading_path=list(source.get("heading_path") or []),
            score=source.get("score"),
            marker=marker,
            annotation=annotation,
            message_annotation=message_annotation,
            graph_relationships=graph_relationships,
        ))
    try:
        ensure_retrieval_answer_citation_integrity(answer, context_citations)
    except (OpenAICompatError, ValueError) as exc:
        raise ExpertCitationIntegrityError("answer citations failed integrity validation") from exc
    return expert_citations


def _model_metadata(completion) -> ExpertModelMetadata:
    return ExpertModelMetadata(
        policy_id=completion.policy_id,
        requested_model_profile_id=completion.requested_model_profile_id,
        model_profile_id=completion.model_profile_id,
        provider=completion.provider,
        model=completion.model,
        latency_ms=completion.latency_ms,
        usage=completion.usage,
        finish_reason=completion.finish_reason,
        fallback=completion.fallback,
    )


def _combine_completion_usage(first, final):
    """Keep final provider metadata while accounting for a bounded citation-repair call."""

    usage = final.usage.model_copy(update={
        "input_tokens": first.usage.input_tokens + final.usage.input_tokens,
        "output_tokens": first.usage.output_tokens + final.usage.output_tokens,
        "total_tokens": first.usage.total_tokens + final.usage.total_tokens,
    })
    fallback = final.fallback.model_copy(update={
        "attempts": [*first.fallback.attempts, *final.fallback.attempts],
    })
    return final.model_copy(update={
        "latency_ms": first.latency_ms + final.latency_ms,
        "usage": usage,
        "fallback": fallback,
    })


async def run_expert_turn(
    db: Session,
    principal: Principal,
    req: ExpertMessageRequest,
) -> ExpertMessageResponse:
    """Run bounded profile-authorized retrieval before corpus-grounded synthesis."""

    if not req.expert_id:
        raise ValueError("expert_id is required")
    search_executor = _search_page_executor
    if search_executor is None:
        raise ExpertRetrievalPlanningError("expert search executor is unavailable")

    profile = resolve_expert_profile(db, principal, req.expert_id)
    session = _session_for_request(db, principal, req)
    memory_guidance, applied_memory_event_ids = _memory_guidance(session)
    user_message_id = record_expert_message(db, principal, session.id, role="user", content=req.message)
    requested_lens, selection_source, requested_lens_id = _selected_lens(req, profile)
    max_attempts = profile.tool_limits.max_retrieval_runs
    attempts_used = 0
    successful_attempts = 0
    total_result_count = 0
    had_fallback = False
    traces: list[ExpertRetrievalTraceRun] = []
    sources: list[dict[str, Any]] = []

    def persist_failed_attempt(
        binding: Any,
        lens_id: str,
        *,
        graph_status: str,
        error_code: str,
        lens_inputs: dict[str, Any],
    ) -> None:
        payload = {
            "message_id": user_message_id,
            "query": req.message,
            "filters": {"vector_store_id": binding.vector_store_id},
            "requested_lens_id": requested_lens_id,
            "lens_id": lens_id,
            "lens_selection_source": selection_source,
            "lens_inputs": lens_inputs,
            "graph_status": graph_status,
            "result_count": 0,
            "result_ids": [],
            "selected_context_result_ids": [],
            "citations": [],
            "error_code": error_code,
        }
        run_id = record_expert_retrieval_run(db, principal, session.id, payload)
        traces.append(ExpertRetrievalTraceRun(
            retrieval_run_id=run_id,
            query=req.message,
            vector_store_id=binding.vector_store_id,
            lens_id=lens_id,
            requested_lens_id=requested_lens_id,
            lens_selection_source=selection_source,
            graph_status=graph_status,
            result_ids=[],
            selected_context_result_ids=[],
            citation_count=0,
        ))

    async def execute_attempt(
        binding: Any,
        lens_id: str,
        *,
        semantic_fallback: bool = False,
        binding_lens_fallback: bool = False,
    ) -> tuple[bool, bool]:
        nonlocal attempts_used, successful_attempts, total_result_count, had_fallback, sources

        if attempts_used >= max_attempts:
            return False, False
        attempts_used += 1
        if semantic_fallback or binding_lens_fallback:
            had_fallback = True
        fallback_available = (
            lens_id != DEFAULT_SEARCH_LENS_ID
            and selection_source == "inferred"
            and attempts_used < max_attempts
        )
        search_req = OpenAIVectorStoreSearchRequest(
            query=req.message,
            lens=lens_id,
            inputs=None if semantic_fallback or binding_lens_fallback else req.lens_inputs,
            max_num_results=profile.tool_limits.max_results_per_run,
        ).bind_graph_expansion_limit(profile.tool_limits.max_graph_expansions)

        try:
            raw_page = await search_executor(binding.vector_store_id, search_req, principal, db)
        except Exception as exc:
            if semantic_fallback:
                graph_status = "semantic_fallback_failed"
            elif binding_lens_fallback:
                graph_status = "binding_lens_unavailable_semantic_failed"
            elif fallback_available:
                graph_status = "unavailable_fallback_semantic"
            elif lens_id != DEFAULT_SEARCH_LENS_ID and selection_source == "inferred":
                graph_status = "unavailable_no_fallback_budget"
            else:
                graph_status = "failed"
            error_code = (
                "search_lens_unavailable"
                if isinstance(exc, OpenAICompatError) and lens_id != DEFAULT_SEARCH_LENS_ID
                else "search_executor_failed"
            )
            persist_failed_attempt(
                binding,
                lens_id,
                graph_status=graph_status,
                error_code=error_code,
                lens_inputs=search_req.inputs or {},
            )
            return False, fallback_available

        try:
            page = _validated_search_page(
                raw_page,
                max_results=profile.tool_limits.max_results_per_run,
            )
        except ExpertRetrievalResponseError:
            if semantic_fallback:
                graph_status = "semantic_fallback_failed"
            elif binding_lens_fallback:
                graph_status = "binding_lens_unavailable_semantic_failed"
            elif fallback_available:
                graph_status = "unavailable_fallback_semantic"
            elif lens_id != DEFAULT_SEARCH_LENS_ID and selection_source == "inferred":
                graph_status = "unavailable_no_fallback_budget"
            else:
                graph_status = "failed"
            persist_failed_attempt(
                binding,
                lens_id,
                graph_status=graph_status,
                error_code="invalid_search_response",
                lens_inputs=search_req.inputs or {},
            )
            return False, fallback_available

        results = _page_results(page)
        full_citations = [dict(result["citation"]) for result in results]
        result_ids = [_result_id(citation) for citation in full_citations]
        sources, selected_context_result_ids = _select_context_results(
            sources,
            results,
            token_budget=profile.tool_limits.max_context_tokens,
        )
        graph_status = (
            "binding_lens_unavailable_fallback_semantic"
            if binding_lens_fallback
            else _graph_status(page, lens_id)
        )
        payload = {
            "message_id": user_message_id,
            "query": req.message,
            "filters": {"vector_store_id": binding.vector_store_id},
            "requested_lens_id": requested_lens_id,
            "lens_id": lens_id,
            "lens_selection_source": selection_source,
            "lens_inputs": search_req.inputs or {},
            "graph_status": graph_status,
            "graph_expansion": _dict(page.get("graph_expansion")) or None,
            "result_count": len(results),
            "result_ids": result_ids,
            "selected_context_result_ids": selected_context_result_ids,
            "citations": full_citations,
        }
        run_id = record_expert_retrieval_run(db, principal, session.id, payload)
        traces.append(ExpertRetrievalTraceRun(
            retrieval_run_id=run_id,
            query=req.message,
            vector_store_id=binding.vector_store_id,
            lens_id=lens_id,
            requested_lens_id=requested_lens_id,
            lens_selection_source=selection_source,
            graph_status=graph_status,
            result_ids=result_ids,
            selected_context_result_ids=selected_context_result_ids,
            citation_count=len(full_citations),
        ))
        successful_attempts += 1
        total_result_count += len(results)
        if semantic_fallback or binding_lens_fallback:
            had_fallback = True
        return True, False

    for binding in _ordered_bindings(profile, requested_lens):
        if attempts_used >= max_attempts:
            break
        binding_supports_lens = requested_lens in _binding_graph_lens_ids(binding)
        if requested_lens != DEFAULT_SEARCH_LENS_ID and not binding_supports_lens:
            if selection_source == "explicit":
                continue
            actual_lens = DEFAULT_SEARCH_LENS_ID
            binding_lens_fallback = True
        else:
            actual_lens = requested_lens
            binding_lens_fallback = False

        succeeded, graph_fallback_available = await execute_attempt(
            binding,
            actual_lens,
            binding_lens_fallback=binding_lens_fallback,
        )
        if not succeeded and graph_fallback_available and attempts_used < max_attempts:
            had_fallback = True
            await execute_attempt(
                binding,
                DEFAULT_SEARCH_LENS_ID,
                semantic_fallback=True,
            )

    if successful_attempts == 0:
        raise ExpertRetrievalPlanningError("all bounded expert retrieval attempts failed or were unavailable")

    context = _context_text(sources)
    if context and estimate_tokens(context) > profile.tool_limits.max_context_tokens:
        raise ExpertRetrievalResponseError("selected retrieval context exceeds its token budget")
    synthesis_messages = [
        ExpertChatMessage(role="system", content=profile.system_prompt),
        ExpertChatMessage(role="system", content=SYNTHESIS_INSTRUCTION),
        *memory_guidance,
        *_chat_history(session),
        ExpertChatMessage(
            role="user",
            content=f"Question: {req.message}\n\nRetrieved corpus context:\n{context}",
        ),
    ]
    completion = await complete_expert_chat(ExpertChatCompletionRequest(
        messages=synthesis_messages,
        model_policy=profile.model_policy,
        security_level=principal.max_security_level,
    ))
    guarded_answer, output_guard = output_guard_text(completion.content)
    caveats = list(profile.caveats)
    citation_repair_used = False
    if not sources:
        citations: list[ExpertCitation] = []
        if total_result_count:
            answer = NO_CONTEXT_ANSWER
            caveats.append(NO_CONTEXT_CAVEAT)
        else:
            answer = NO_RESULTS_ANSWER
            caveats.append(NO_RESULTS_CAVEAT)
    else:
        answer = guarded_answer
        try:
            citations = _answer_citations(answer, sources)
            if profile.citation_policy.required and not citations:
                raise ExpertCitationIntegrityError("grounded expert answer requires retrieved citations")
        except ExpertCitationIntegrityError:
            allowed_markers = " ".join(source["marker"] for source in sources)
            repaired = await complete_expert_chat(ExpertChatCompletionRequest(
                messages=[
                    *synthesis_messages,
                    ExpertChatMessage(role="assistant", content=answer),
                    ExpertChatMessage(
                        role="user",
                        content=(
                            f"{CITATION_REPAIR_INSTRUCTION}\n\n"
                            f"Allowed markers: {allowed_markers}"
                        ),
                    ),
                ],
                model_policy=profile.model_policy,
                security_level=principal.max_security_level,
            ))
            completion = _combine_completion_usage(completion, repaired)
            answer, repair_output_guard = output_guard_text(repaired.content)
            output_guard = output_guard or repair_output_guard
            citations = _answer_citations(answer, sources)
            if profile.citation_policy.required and not citations:
                raise ExpertCitationIntegrityError("grounded expert answer requires retrieved citations")
            citation_repair_used = True
            caveats.append(
                "The initial synthesis failed citation formatting and was regenerated against the same retrieved context."
            )
    if output_guard:
        caveats.append("Sensitive output patterns were redacted by the ExAIS output guard.")

    trace_status = "partial" if had_fallback or successful_attempts < attempts_used else "completed"
    if trace_status == "partial":
        caveats.append("One or more bounded retrieval attempts used a fallback or failed; see the retrieval trace.")

    record_expert_message(
        db,
        principal,
        session.id,
        role="assistant",
        content=answer,
        metadata={
            "policy_id": completion.policy_id,
            "model_profile_id": completion.model_profile_id,
            "provider": completion.provider,
            "model": completion.model,
            "retrieval_status": trace_status,
            "retrieval_run_ids": [trace.retrieval_run_id for trace in traces],
            "citation_count": len(citations),
            "citation_repair_used": citation_repair_used,
            "output_guard": output_guard,
            "applied_memory_event_ids": applied_memory_event_ids,
        },
    )
    return ExpertMessageResponse(
        expert_id=profile.id,
        session_id=session.id,
        parent_session_id=session.parent_session_id,
        answer=answer,
        citations=citations,
        retrieval_trace=ExpertRetrievalTrace(status=trace_status, runs=traces),
        model_metadata=_model_metadata(completion),
        caveats=caveats,
        follow_up_suggestions=["Ask a narrower follow-up or select another profile-authorized search lens."],
    )
