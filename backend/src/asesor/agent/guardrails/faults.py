import asyncio
from enum import StrEnum
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from asesor.agent.tools.envelope import error, no_results

FAULT_STATE_KEY = "temp:fault"


class Fault(StrEnum):
    TOOL_ERROR = "tool_error"
    MODEL_429 = "model_429"
    MODEL_TIMEOUT = "model_timeout"
    RAG_DOWN = "rag_down"


class InjectedModelError(RuntimeError):
    """Model failure triggered on purpose, to demonstrate the fallbacks."""

    def __init__(self, fault: Fault) -> None:
        super().__init__(f"fault injection: {fault.value}")
        self.fault = fault


def parse_fault(raw: str | None) -> Fault | None:
    if not raw:
        return None
    try:
        return Fault(raw.strip().lower())
    except ValueError:
        return None


class FaultInjectionPlugin(BasePlugin):
    """Only registered if APP_ENV=dev and ENABLE_FAULT_INJECTION=true."""

    def __init__(self) -> None:
        super().__init__(name="fault-injection")

    # Model failures are NOT injected here: ADK catches plugin exceptions and
    # turns them into a turn error, so ResilientLlm would never see the 429
    # or be able to fall back. They're injected inside ResilientLlm, by
    # reading fault_context's contextvar.

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> dict[str, Any] | None:
        fault = parse_fault(tool_context.state.get(FAULT_STATE_KEY))

        if fault is Fault.RAG_DOWN and tool.name == "search_knowledge_base":
            await asyncio.sleep(0)
            return no_results()

        if fault is Fault.TOOL_ERROR:
            return error(
                "TOOL_UNAVAILABLE",
                "La herramienta no está disponible en este momento",
                retryable=True,
            )

        return None
