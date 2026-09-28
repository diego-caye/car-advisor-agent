from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from google.adk.tools import ToolContext
from pydantic import BaseModel, ValidationError

from asesor.agent.state import SOLO_MIRANDO_KEY, STAGE_KEY, read_dialog_state
from asesor.agent.tools.envelope import error, ok
from asesor.application.lead_service import LeadService
from asesor.domain.entities import LeadUpdate
from asesor.domain.enums import (
    InterestLevel,
    Powertrain,
    PreferredChannel,
    PrimaryUse,
    VehicleType,
)
from asesor.domain.errors import DomainError

SaveLead = Callable[..., Awaitable[dict[str, Any]]]


class _SaveLeadArgs(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    preferred_channel: PreferredChannel | None = None
    contact_consent: bool | None = None
    primary_use: PrimaryUse | None = None
    vehicle_type_interest: VehicleType | None = None
    powertrain_interest: Powertrain | None = None
    interest_level: InterestLevel | None = None
    just_browsing: bool | None = None

    def to_update(self) -> LeadUpdate:
        return LeadUpdate(**self.model_dump(exclude={"just_browsing"}))


def make_save_lead(lead_service: LeadService) -> SaveLead:
    async def save_lead(
        tool_context: ToolContext,
        name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        preferred_channel: str | None = None,
        contact_consent: bool | None = None,
        primary_use: str | None = None,
        vehicle_type_interest: str | None = None,
        powertrain_interest: str | None = None,
        interest_level: str | None = None,
        just_browsing: bool | None = None,
    ) -> dict[str, Any]:
        """Saves or updates the user's lead record with whatever data they share.

        Call it as soon as the user gives their name, primary use, the vehicle type
        or powertrain they're interested in, or when you notice their interest level
        changed. Update only the fields you know: send null for everything else.

        Args:
            name: User's name, 1 to 80 characters.
            phone: Peruvian 9-digit mobile number or a number in international format.
            email: User's email address.
            preferred_channel: One of WHATSAPP, CALL, EMAIL, CHAT.
            contact_consent: true if the user explicitly agreed to be contacted.
                Required if you send phone or email.
            primary_use: One of CITY, WORK, FAMILY, TRAVEL, MIXED.
            vehicle_type_interest: One of SUV, SEDAN, HATCHBACK, PICKUP, VAN,
                CROSSOVER, OTHER.
            powertrain_interest: One of GASOLINE, DIESEL, HYBRID, ELECTRIC,
                LPG_CNG, UNDEFINED.
            interest_level: One of LOW, MEDIUM, HIGH, inferred from the conversation.
            just_browsing: true the first time the user says they're just
                looking/comparing, with no intent to move forward yet. It can go
                alone, with no other field. Once set, it stays that way for the
                rest of the conversation: no need to send it again.

        Returns:
            The updated lead record and the dialog stage.
        """
        try:
            args = _SaveLeadArgs(
                name=name,
                phone=phone,
                email=email,
                preferred_channel=preferred_channel,
                contact_consent=contact_consent,
                primary_use=primary_use,
                vehicle_type_interest=vehicle_type_interest,
                powertrain_interest=powertrain_interest,
                interest_level=interest_level,
                just_browsing=just_browsing,
            )
        except ValidationError as exc:
            return error("VALIDATION_ERROR", _first_message(exc))

        if args.just_browsing:
            # Lives in the session state (dialog state), not in the user's
            # record: it's an intent for this conversation, not a lead field.
            tool_context.state[SOLO_MIRANDO_KEY] = True

        dialog = read_dialog_state(tool_context.state)
        update = args.to_update()

        if args.just_browsing and update.is_empty():
            # Called only to flag that the user is "just looking", with no
            # new lead data -- valid, it shouldn't fall into EMPTY_UPDATE.
            snapshot = await lead_service.get_snapshot(UUID(tool_context.user_id), dialog.stage)
        else:
            try:
                snapshot = await lead_service.apply_update(
                    UUID(tool_context.user_id), update, dialog.stage
                )
            except DomainError as exc:
                return error(exc.code, exc.message, retryable=exc.retryable)
            tool_context.state[STAGE_KEY] = snapshot.stage.value

        return ok(
            {
                "lead": {
                    "name": snapshot.lead.name,
                    "preferred_channel": snapshot.lead.preferred_channel,
                    "primary_use": snapshot.lead.primary_use,
                    "vehicle_type_interest": snapshot.lead.vehicle_type_interest,
                    "powertrain_interest": snapshot.lead.powertrain_interest,
                    "interest_level": snapshot.lead.interest_level,
                    "contact_consent": snapshot.lead.contact_consent,
                },
                "stage": snapshot.stage.value,
            }
        )

    return save_lead


def _first_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    return f"{field}: {first['msg']}"
