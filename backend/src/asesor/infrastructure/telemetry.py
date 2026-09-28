import base64
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from asesor.config import Settings

logger = logging.getLogger("asesor.turn")

_SERVICE_NAME = "asesor-automotriz"


def _langfuse_host(settings: Settings) -> str:
    return (settings.langfuse_host or "https://cloud.langfuse.com").rstrip("/")


def _langfuse_auth_header(settings: Settings) -> str:
    credentials = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}"
    token = base64.b64encode(credentials.encode()).decode()
    return f"Basic {token}"


def setup_telemetry(settings: Settings) -> None:
    """Wire OTel to Langfuse. Without keys the provider stays un-exported (no-op)."""
    provider = TracerProvider(resource=Resource.create({"service.name": _SERVICE_NAME}))

    if settings.telemetry_enabled:
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=f"{_langfuse_host(settings)}/api/public/otel/v1/traces",
                    headers={"Authorization": _langfuse_auth_header(settings)},
                )
            )
        )

    trace.set_tracer_provider(provider)

    from openinference.instrumentation.google_adk import GoogleADKInstrumentor

    GoogleADKInstrumentor().instrument(tracer_provider=provider)


async def send_langfuse_score(
    settings: Settings, *, trace_id: str, name: str, value: float, comment: str | None = None
) -> None:
    """Attaches a score to an already-closed trace (spec 08 S4/S5, verified live
    against `POST /api/public/scores`: the "legacy" trace-reading API is
    deprecated for new orgs, but the score-writing one is still alive).

    No-op without keys. Never raises if Langfuse doesn't respond: a score is
    observability decoration, it shouldn't take down the response to the user
    or the background evaluation turn that triggers it.
    """
    if not settings.telemetry_enabled:
        return

    payload: dict[str, Any] = {
        "traceId": trace_id,
        "name": name,
        "value": value,
        "dataType": "NUMERIC",
    }
    if comment:
        payload["comment"] = comment

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{_langfuse_host(settings)}/api/public/scores",
                json=payload,
                headers={"Authorization": _langfuse_auth_header(settings)},
            )
            response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("could not send score %r to Langfuse", name, exc_info=True)


@dataclass(slots=True)
class TurnTrace:
    trace_id: str
    span: trace.Span

    def set(self, key: str, value: Any) -> None:
        self.span.set_attribute(key, value)


@contextmanager
def turn_span(*, session_id: str, user_id: str, settings: Settings) -> Iterator[TurnTrace]:
    tracer = trace.get_tracer(_SERVICE_NAME)
    with tracer.start_as_current_span("chat.turn") as span:
        context = span.get_span_context()
        trace_id = format(context.trace_id, "032x") if context.trace_id else ""
        span.set_attribute("session_id", session_id)
        span.set_attribute("user_id", user_id)
        span.set_attribute("provider", settings.llm_provider.value)
        span.set_attribute("model", settings.agent_model)
        yield TurnTrace(trace_id=trace_id, span=span)


def log_turn(payload: dict[str, Any]) -> None:
    logger.info(json.dumps(payload, ensure_ascii=False, default=str))
