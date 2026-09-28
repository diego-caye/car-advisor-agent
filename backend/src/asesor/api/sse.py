import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from google.adk.events import Event

from asesor.agent.guardrails.plugin import GUARDRAIL_STATE_KEY
from asesor.agent.parts import visible_text
from asesor.domain.enums import ToolStatus

logger = logging.getLogger(__name__)

LEAD_TOOL_NAME = "guardar_lead"
HANDOFF_TOOL_NAME = "solicitar_contacto_humano"
CONFIRMATION_CALL_NAME = "adk_request_confirmation"
UPSTREAM_ERROR_MESSAGE = "No pudimos generar la respuesta. Reintenta en unos segundos."
EMPTY_REPLY_FALLBACK = "Disculpa, se me fue la idea 😅 ¿Me lo repites?"


@dataclass(frozen=True, slots=True)
class SseEvent:
    event: str
    data: dict[str, Any]

    def encode(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.event}\ndata: {payload}\n\n"


@dataclass(slots=True)
class TurnMetrics:
    started_at: float = field(default_factory=time.perf_counter)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str | None = None

    def observe(self, event: Event) -> None:
        usage = event.usage_metadata
        if usage is not None:
            self.tokens_in += usage.prompt_token_count or 0
            self.tokens_out += usage.candidates_token_count or 0
        if event.model_version:
            self.model = event.model_version

    @property
    def latency_ms(self) -> int:
        return int((time.perf_counter() - self.started_at) * 1000)


def _confirmation_event(call: Any) -> SseEvent:
    """Translates ADK's adk_request_confirmation into the spec 02 contract."""
    args = dict(call.args or {})
    payload = dict((args.get("toolConfirmation") or {}).get("payload") or {})
    return SseEvent(
        "hitl.confirmation_required",
        {
            "confirmation_id": call.id,
            "motivo": payload.get("motivo"),
            "resumen": payload.get("resumen"),
            "canal_preferido": payload.get("canal_preferido"),
            "urgencia": payload.get("urgencia"),
        },
    )


def _text_of(event: Event) -> str:
    return visible_text(event.content)


async def translate(events: AsyncIterator[Event], trace_id: str) -> AsyncIterator[SseEvent]:
    metrics = TurnMetrics()
    tool_started_at: dict[str, float] = {}
    reported_error = False
    # The model's text is buffered instead of being forwarded fragment by
    # fragment: L4 can only judge the complete response, and once a delta has
    # been streamed there's no way to retract it from the client (spec 07 §1).
    buffered = ""
    last_text = ""
    last_event_id = ""
    # Spec 02 §2: a turn with a pending HITL closes the stream when it asks
    # for confirmation, with no further events. The iteration over `events`
    # itself isn't cut short (interrupting it halfway triggers GeneratorExit
    # inside ADK's own context managers -- OpenTelemetry contextvars bound to
    # the Task that drives the generator -- which takes down the actual turn:
    # reproduced with the HITL ATs). `events` keeps being drained to the end
    # so ADK can close its own resources normally, but nothing is
    # translated/emitted after the confirmation -- without this cutoff, ADK
    # sometimes keeps generating events from the SAME invocation after
    # requesting it (seen live with gemma4:12b: the same turn ends in a real
    # message.completed with text, minutes later, while the confirmation card
    # is still pending on screen).
    confirmation_pending = False

    async for event in events:
        if confirmation_pending:
            continue
        metrics.observe(event)
        last_event_id = event.id or last_event_id

        triggered = (event.custom_metadata or {}).get(GUARDRAIL_STATE_KEY)
        if isinstance(triggered, dict):
            # Whatever had already been buffered is discarded: the good
            # response is the one that replaces the guardrail.
            buffered = ""
            yield SseEvent(
                "guardrail.triggered",
                {"layer": triggered.get("layer"), "category": triggered.get("category")},
            )

        if event.error_code:
            # The provider's detail may carry endpoints, keys, or traces: it
            # goes to the log, never to the client.
            logger.warning(
                "upstream error %s: %s",
                event.error_code,
                event.error_message,
                extra={"trace_id": trace_id},
            )
            reported_error = True
            yield SseEvent(
                "error",
                {"code": event.error_code, "message": UPSTREAM_ERROR_MESSAGE, "retryable": True},
            )
            continue

        for call in event.get_function_calls():
            if call.name == CONFIRMATION_CALL_NAME:
                yield _confirmation_event(call)
                confirmation_pending = True
                break
            tool_started_at[call.name or ""] = time.perf_counter()
            yield SseEvent("tool.started", {"name": call.name})

        if confirmation_pending:
            continue

        for response in event.get_function_responses():
            name = response.name or ""
            started = tool_started_at.pop(name, None)
            duration_ms = int((time.perf_counter() - started) * 1000) if started else 0
            payload = response.response if isinstance(response.response, dict) else {}
            status = str(payload.get("status", ToolStatus.OK.value))

            yield SseEvent(
                "tool.finished",
                {"name": name, "status": status, "duration_ms": duration_ms},
            )

            data = payload.get("data") or {}

            if name == LEAD_TOOL_NAME and status == ToolStatus.OK.value:
                yield SseEvent(
                    "lead.updated",
                    {"lead": data.get("lead"), "etapa": data.get("etapa")},
                )

            if name == HANDOFF_TOOL_NAME and data.get("handoff_id"):
                yield SseEvent(
                    "handoff.created",
                    {
                        "handoff_id": data.get("handoff_id"),
                        "ticket": data.get("ticket"),
                        "motivo": data.get("motivo"),
                        "status": data.get("status"),
                        "ya_existia": data.get("ya_existia", False),
                    },
                )

        text = _text_of(event)
        if text:
            if event.partial:
                buffered += text
            else:
                # The non-partial response already went through L4, so it's
                # the one that counts.
                last_text = text

    if confirmation_pending:
        return

    final_text = last_text or buffered
    if final_text:
        yield SseEvent("message.delta", {"delta": final_text})
    elif not reported_error:
        # A turn with no visible text leaves an empty bubble. Happens when
        # the model only emits reasoning: seen with Gemma 4 via Ollama.
        logger.warning("turn with no visible text", extra={"trace_id": trace_id})
        yield SseEvent("message.delta", {"delta": EMPTY_REPLY_FALLBACK})

    yield SseEvent(
        "message.completed",
        {
            "message_id": last_event_id,
            "trace_id": trace_id,
            "latency_ms": metrics.latency_ms,
            "tokens_in": metrics.tokens_in,
            "tokens_out": metrics.tokens_out,
            "model": metrics.model,
        },
    )
