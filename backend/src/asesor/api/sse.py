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

LEAD_TOOL_NAME = "save_lead"
HANDOFF_TOOL_NAME = "request_human_handoff"
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
    """Traduce el adk_request_confirmation de ADK al contrato de spec 02."""
    args = dict(call.args or {})
    payload = dict((args.get("toolConfirmation") or {}).get("payload") or {})
    return SseEvent(
        "hitl.confirmation_required",
        {
            "confirmation_id": call.id,
            "reason": payload.get("reason"),
            "resumen": payload.get("resumen"),
            "preferred_channel": payload.get("preferred_channel"),
            "urgency": payload.get("urgency"),
        },
    )


def _text_of(event: Event) -> str:
    return visible_text(event.content)


async def translate(events: AsyncIterator[Event], trace_id: str) -> AsyncIterator[SseEvent]:
    metrics = TurnMetrics()
    tool_started_at: dict[str, float] = {}
    reported_error = False
    # El texto del modelo se acumula en vez de reenviarse fragmento a fragmento:
    # L4 solo puede juzgar la respuesta completa, y una vez transmitido un delta
    # ya no hay forma de retirarlo del cliente (spec 07 §1).
    buffered = ""
    last_text = ""
    last_event_id = ""
    # Spec 02 §2: un turno con HITL pendiente cierra el stream al pedir la
    # confirmación, sin más eventos. No se corta la iteración de `events` en
    # sí (interrumpirla a medias dispara GeneratorExit dentro de los context
    # managers propios de ADK -- contextvars de OpenTelemetry atados a la
    # Task que conduce el generador -- y tumba el turno real: reproducido
    # con los AT de HITL). Se sigue drenando `events` hasta el final para que
    # ADK cierre sus propios recursos con normalidad, pero se deja de
    # traducir/emitir cualquier cosa después de la confirmación -- sin este
    # corte, ADK a veces sigue generando eventos de la MISMA invocación
    # después de pedirla (visto en vivo con gemma4:12b: el mismo turno
    # termina en un message.completed real con texto, minutos después,
    # mientras la tarjeta de confirmación sigue pendiente en pantalla).
    confirmation_pending = False

    async for event in events:
        if confirmation_pending:
            continue
        metrics.observe(event)
        last_event_id = event.id or last_event_id

        triggered = (event.custom_metadata or {}).get(GUARDRAIL_STATE_KEY)
        if isinstance(triggered, dict):
            # Lo que ya se hubiera acumulado queda descartado: la respuesta
            # buena es la que sustituye el guardrail.
            buffered = ""
            yield SseEvent(
                "guardrail.triggered",
                {"layer": triggered.get("layer"), "category": triggered.get("category")},
            )

        if event.error_code:
            # El detalle del proveedor puede traer endpoints, claves o trazas:
            # va al log, nunca al cliente.
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
                    {"lead": data.get("lead"), "stage": data.get("stage")},
                )

            if name == HANDOFF_TOOL_NAME and data.get("handoff_id"):
                yield SseEvent(
                    "handoff.created",
                    {
                        "handoff_id": data.get("handoff_id"),
                        "ticket": data.get("ticket"),
                        "reason": data.get("reason"),
                        "status": data.get("status"),
                        "ya_existia": data.get("ya_existia", False),
                    },
                )

        text = _text_of(event)
        if text:
            if event.partial:
                buffered += text
            else:
                # La respuesta no parcial ya pasó por L4, así que es la que vale.
                last_text = text

    if confirmation_pending:
        return

    final_text = last_text or buffered
    if final_text:
        yield SseEvent("message.delta", {"delta": final_text})
    elif not reported_error:
        # Un turno sin texto visible deja una burbuja vacía. Pasa cuando el
        # modelo solo emite razonamiento: se ha visto con Gemma 4 vía Ollama.
        logger.warning("turno sin texto visible", extra={"trace_id": trace_id})
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
