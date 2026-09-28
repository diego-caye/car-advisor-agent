import logging
import random
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, Request
from fastapi.responses import StreamingResponse
from google.adk.events import Event

from asesor.agent.guardrails.faults import parse_fault
from asesor.api.dependencies import UserId
from asesor.api.dtos import ChatRequest, ConfirmationRequest
from asesor.api.errors import AppError, NotFoundError
from asesor.api.sse import SseEvent, translate
from asesor.application.chat_service import ChatService, SessionNotFoundError
from asesor.config import UnknownModelError
from asesor.infrastructure.container import Container
from asesor.infrastructure.telemetry import log_turn, turn_span

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


async def _stream(
    container: Container,
    session_id: str,
    user_id: UUID,
    events: AsyncIterator[Event],
    *,
    background: BackgroundTasks | None = None,
    user_message: str | None = None,
) -> AsyncIterator[str]:
    with turn_span(
        session_id=session_id, user_id=str(user_id), settings=container.settings
    ) as turn:
        completed: dict[str, Any] = {}
        reported_error = False
        final_text = ""
        used_rag = False

        try:
            async for sse_event in translate(events, turn.trace_id):
                if sse_event.event == "message.completed":
                    completed = dict(sse_event.data)
                elif sse_event.event == "message.delta":
                    final_text = str(sse_event.data.get("delta") or "")
                elif sse_event.event == "tool.started":
                    used_rag = used_rag or sse_event.data.get("name") == "search_knowledge_base"
                reported_error = reported_error or sse_event.event == "error"
                yield sse_event.encode()
        except Exception:
            logger.exception("chat turn failed", extra={"trace_id": turn.trace_id})
            turn.set("error", True)
            if not reported_error:
                yield SseEvent(
                    "error",
                    {
                        "code": "UPSTREAM_UNAVAILABLE",
                        "message": (
                            "No pudimos conectar con el asesor. Reintenta en unos segundos."
                        ),
                        "retryable": True,
                    },
                ).encode()
            return

        turn.set("tokens_in", int(completed.get("tokens_in", 0) or 0))
        turn.set("tokens_out", int(completed.get("tokens_out", 0) or 0))
        turn.set("latency_ms", int(completed.get("latency_ms", 0) or 0))

        log_turn(
            {
                "event": "chat.turn",
                "session_id": session_id,
                "user_id": str(user_id),
                "provider": container.settings.llm_provider.value,
                **completed,
            }
        )

        # Post-turn background evaluation (spec 08 §5): only if the turn
        # ended with real text (no HITL/error) is there a fresh user message
        # to evaluate -- chat/confirmations doesn't send one, so a turn
        # resumed via HITL is never sampled -- and sampling
        # (EVAL_SAMPLE_RATE) picked it.
        if (
            background is not None
            and user_message is not None
            and completed
            and final_text
            and random.random() < container.settings.eval_sample_rate
        ):
            background.add_task(
                container.evaluation_service.evaluate_turn,
                session_id=session_id,
                message_id=str(completed.get("message_id", "")),
                trace_id=turn.trace_id,
                user_message=user_message,
                agent_reply=final_text,
                used_rag=used_rag,
            )


async def _guarded_service(
    request: Request, user_id: UUID, session_id: str, model_id: str | None = None
) -> ChatService:
    container: Container = request.app.state.container

    try:
        runner = container.runners.get(model_id)
    except UnknownModelError as exc:
        raise AppError("UNKNOWN_MODEL", str(exc), http_status=422) from exc

    service = ChatService(runner, container.session_service)
    try:
        await service.get_session(user_id, session_id)
    except SessionNotFoundError as exc:
        raise NotFoundError("Session not found") from exc
    return service


@router.post("/stream")
async def chat_stream(
    request: Request,
    user_id: UserId,
    body: ChatRequest,
    background: BackgroundTasks,
    x_debug_fault: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    container: Container = request.app.state.container
    service = await _guarded_service(request, user_id, body.session_id, body.model_id)

    # The header is ignored outside of dev, even if it's sent (spec 07 §4).
    fault = parse_fault(x_debug_fault) if container.settings.fault_injection_active else None

    # In the background: titling the conversation shouldn't add latency to
    # the turn or break it if the lightweight model fails.
    background.add_task(
        container.title_service.ensure_title, user_id, body.session_id, body.message
    )

    events = service.run_turn(user_id, body.session_id, body.message, fault)
    return StreamingResponse(
        _stream(
            container,
            body.session_id,
            user_id,
            events,
            background=background,
            user_message=body.message,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
        background=background,
    )


@router.post("/confirmations")
async def chat_confirmation(
    request: Request, user_id: UserId, body: ConfirmationRequest
) -> StreamingResponse:
    container: Container = request.app.state.container
    service = await _guarded_service(request, user_id, body.session_id, body.model_id)

    events = service.resume_with_confirmation(
        user_id, body.session_id, body.confirmation_id, body.approved
    )
    return StreamingResponse(
        _stream(container, body.session_id, user_id, events),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
