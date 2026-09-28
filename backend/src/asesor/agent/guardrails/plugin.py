import logging
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from asesor.agent.guardrails.l1 import inspect_message
from asesor.agent.guardrails.l4 import inspect_reply, strip_pseudo_tool_calls
from asesor.agent.instruction import CANNED_JAILBREAK
from asesor.agent.language import detect_language
from asesor.agent.parts import visible_text
from asesor.agent.tools.envelope import error

logger = logging.getLogger(__name__)

# temp: no se persiste en la sesión; solo viaja en el state_delta del turno,
# que es de donde el traductor de SSE lee el evento guardrail.triggered.
GUARDRAIL_STATE_KEY = "temp:guardrail"
TOOL_CALLS_STATE_KEY = "temp:tool_calls"

TOO_LONG_REPLY = {
    "es": "Ese mensaje es muy largo para mí 😊 ¿Me lo resumes en pocas líneas para poder ayudarte?",
    "en": "That message is too long for me 😊 Could you sum it up in a few lines to help you?",
}


def _canned(text: str, layer: str, category: str | None) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part.from_text(text=text)]),
        turn_complete=True,
        # El state del callback no llega al state_delta del evento, así que el
        # marcador viaja por custom_metadata, que ADK sí copia al Event.
        custom_metadata={GUARDRAIL_STATE_KEY: {"layer": layer, "category": category}},
    )


def _last_user_text(llm_request: LlmRequest) -> str:
    for content in reversed(list(llm_request.contents or [])):
        if content.role != "user" or not content.parts:
            continue
        text = "".join(part.text or "" for part in content.parts)
        if text:
            return text
    return ""


class GuardrailPlugin(BasePlugin):
    """L1 y L4 de specs/07-guardrails.md, más el tope de tool calls de L3.

    L1 y L3 son deterministas y fail-closed; L4 revisa la salida completa. El
    clasificador L2 es P1 y todavía no está implementado.
    """

    def __init__(self, canary_token: str, max_tool_calls: int) -> None:
        super().__init__(name="guardrails")
        self._canary_token = canary_token
        self._max_tool_calls = max_tool_calls

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        message = _last_user_text(llm_request)
        if not message:
            return None

        verdict = inspect_message(message)
        if not verdict.blocked:
            return None

        logger.info("L1 bloqueó un mensaje: %s (%s)", verdict.category, verdict.reason)

        language = detect_language(message)
        if verdict.category == "too_long":
            return _canned(TOO_LONG_REPLY[language], "L1", verdict.category)
        return _canned(CANNED_JAILBREAK[language], "L1", verdict.category)

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        # Los parciales se revisan enteros al final: filtrar delta por delta
        # dejaría pasar una fuga partida entre dos fragmentos.
        if llm_response.partial:
            return None

        text = visible_text(llm_response.content)
        if not text:
            return None

        cleaned = strip_pseudo_tool_calls(text)
        if cleaned != text:
            logger.warning("el modelo escribió una llamada a tool como texto")
            # Si la respuesta ERA solo la llamada, no hay nada bueno que
            # dejar: `_canned("")` reemplaza igual (devolver None aquí
            # dejaba pasar el texto ORIGINAL sin recortar -- "Returning
            # None allows the original response to be used", per ADK).
            return _canned(cleaned, "L4", "pseudo_tool_call")

        verdict = inspect_reply(text, self._canary_token, CANNED_JAILBREAK)
        if not verdict.blocked or verdict.replacement is None:
            return None

        logger.warning("L4 reemplazó una respuesta: %s", verdict.category)
        return _canned(verdict.replacement, "L4", verdict.category)

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> dict[str, Any] | None:
        used = int(tool_context.state.get(TOOL_CALLS_STATE_KEY) or 0) + 1
        tool_context.state[TOOL_CALLS_STATE_KEY] = used

        if used > self._max_tool_calls:
            logger.warning("L3 cortó un loop de tools en la llamada %s", used)
            return error(
                "TOOL_CALL_LIMIT",
                f"Se alcanzó el máximo de {self._max_tool_calls} herramientas por turno",
            )

        return None
