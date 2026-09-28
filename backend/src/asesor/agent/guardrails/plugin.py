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
from asesor.agent.parts import visible_text
from asesor.agent.tools.envelope import error

logger = logging.getLogger(__name__)

# temp: not persisted in the session; it only travels in the turn's
# state_delta, which is where the SSE translator reads the
# guardrail.triggered event from.
GUARDRAIL_STATE_KEY = "temp:guardrail"
TOOL_CALLS_STATE_KEY = "temp:tool_calls"

TOO_LONG_REPLY = (
    "Ese mensaje es muy largo para mí 😊 ¿Me lo resumes en pocas líneas para poder ayudarte?"
)


def _canned(text: str, layer: str, category: str | None) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part.from_text(text=text)]),
        turn_complete=True,
        # The callback's state doesn't reach the event's state_delta, so the
        # marker travels via custom_metadata, which ADK does copy to the Event.
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
    """L1 and L4 from specs/07-guardrails.md, plus L3's tool-call cap.

    L1 and L3 are deterministic and fail-closed; L4 reviews the complete
    output. The L2 classifier is P1 and not yet implemented.
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

        logger.info("L1 blocked a message: %s (%s)", verdict.category, verdict.reason)

        if verdict.category == "too_long":
            return _canned(TOO_LONG_REPLY, "L1", verdict.category)
        return _canned(CANNED_JAILBREAK, "L1", verdict.category)

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        # Partials are reviewed whole at the end: filtering delta by delta
        # would let a leak split across two fragments slip through.
        if llm_response.partial:
            return None

        text = visible_text(llm_response.content)
        if not text:
            return None

        cleaned = strip_pseudo_tool_calls(text)
        if cleaned != text:
            logger.warning("the model wrote a tool call as text")
            # If the response WAS just the call, there's nothing good left
            # to keep: `_canned("")` replaces it either way (returning None
            # here let the ORIGINAL, untrimmed text through -- "Returning
            # None allows the original response to be used", per ADK).
            return _canned(cleaned, "L4", "pseudo_tool_call")

        verdict = inspect_reply(text, self._canary_token, CANNED_JAILBREAK)
        if not verdict.blocked or verdict.replacement is None:
            return None

        logger.warning("L4 replaced a response: %s", verdict.category)
        return _canned(verdict.replacement, "L4", verdict.category)

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> dict[str, Any] | None:
        used = int(tool_context.state.get(TOOL_CALLS_STATE_KEY) or 0) + 1
        tool_context.state[TOOL_CALLS_STATE_KEY] = used

        if used > self._max_tool_calls:
            logger.warning("L3 cut off a tool-call loop at call %s", used)
            return error(
                "TOOL_CALL_LIMIT",
                f"Se alcanzó el máximo de {self._max_tool_calls} herramientas por turno",
            )

        return None
