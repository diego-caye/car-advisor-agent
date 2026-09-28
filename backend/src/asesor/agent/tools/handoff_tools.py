from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field, ValidationError

from asesor.agent.language import detect_language
from asesor.agent.state import STAGE_KEY, STAGE_PREVIA_KEY, read_dialog_state
from asesor.agent.tools.envelope import error, ok
from asesor.application.handoff_service import HandoffService
from asesor.domain.enums import HandoffReason, PreferredChannel, Stage, Urgency
from asesor.domain.errors import DomainError

RequestHumanHandoff = Callable[..., Awaitable[dict[str, Any]]]

CONFIRMATION_HINT = {
    "es": "¿Confirmas que derivemos tu solicitud a un asesor humano?",
    "en": "Can you confirm you'd like us to hand your request off to a human advisor?",
}


class _HandoffArgs(BaseModel):
    reason: HandoffReason
    requirement_summary: str = Field(min_length=10, max_length=500)
    preferred_channel: PreferredChannel | None = None
    urgency: Urgency | None = None


def make_request_human_handoff(handoff_service: HandoffService) -> RequestHumanHandoff:
    async def request_human_handoff(
        tool_context: ToolContext,
        reason: str,
        requirement_summary: str,
        preferred_channel: str | None = None,
        urgency: str | None = None,
    ) -> dict[str, Any]:
        """Hands the user off to a human advisor, with their prior confirmation.

        Use it when the user asks for a test drive or a formal quote, wants to buy
        and talk to a person, expresses dissatisfaction, or the topic exceeds what
        you can guide them through. The user must confirm before it executes.

        Args:
            reason: One of TEST_DRIVE, FORMAL_QUOTE, IMMEDIATE_PURCHASE,
                DISSATISFACTION, OUT_OF_SCOPE.
            requirement_summary: Summary of what they need, 10 to 500 characters.
            preferred_channel: One of WHATSAPP, CALL, EMAIL, CHAT.
            urgency: One of LOW, MEDIUM, HIGH.

        Returns:
            The request's status and its ticket number once it's created.
        """
        try:
            args = _HandoffArgs(
                reason=reason,
                requirement_summary=requirement_summary,
                preferred_channel=preferred_channel,
                urgency=urgency,
            )
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(part) for part in first["loc"])
            return error("VALIDATION_ERROR", f"{field}: {first['msg']}")

        session_id = tool_context.session.id
        dialog = read_dialog_state(tool_context.state)
        confirmation = tool_context.tool_confirmation

        if confirmation is None:
            tool_context.state[STAGE_PREVIA_KEY] = dialog.stage.value
            tool_context.state[STAGE_KEY] = Stage.HANDOFF_PENDING.value
            tool_context.request_confirmation(
                hint=CONFIRMATION_HINT[detect_language(args.requirement_summary)],
                payload={
                    "reason": args.reason.value,
                    "resumen": args.requirement_summary,
                    "preferred_channel": args.preferred_channel.value
                    if args.preferred_channel
                    else None,
                    "urgency": args.urgency.value if args.urgency else None,
                },
            )
            return ok({"pendiente_de_confirmacion": True})

        if not confirmation.confirmed:
            tool_context.state[STAGE_KEY] = (
                tool_context.state.get(STAGE_PREVIA_KEY) or Stage.NEW.value
            )
            return ok({"cancelado": True})

        try:
            handoff, created = await handoff_service.open_or_get(
                session_id=session_id,
                user_id=UUID(tool_context.user_id),
                reason=args.reason,
                requirement_summary=args.requirement_summary,
                preferred_channel=args.preferred_channel,
                urgency=args.urgency,
            )
        except DomainError as exc:
            return error(exc.code, exc.message, retryable=exc.retryable)

        tool_context.state[STAGE_KEY] = Stage.HANDED_OFF.value

        return ok(
            {
                "handoff_id": handoff.id,
                "ticket": handoff.ticket,
                "reason": handoff.reason.value,
                "status": handoff.status.value,
                "ya_existia": not created,
            }
        )

    return request_human_handoff
