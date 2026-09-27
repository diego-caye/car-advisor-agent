from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from asesor.domain.enums import (
    HandoffReason,
    HandoffStatus,
    InterestLevel,
    Powertrain,
    PreferredChannel,
    PrimaryUse,
    Stage,
    Urgency,
    VehicleType,
)


@dataclass(frozen=True, slots=True)
class Lead:
    user_id: UUID
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    preferred_channel: PreferredChannel | None = None
    contact_consent: bool = False
    primary_use: PrimaryUse | None = None
    vehicle_type_interest: VehicleType | None = None
    powertrain_interest: Powertrain | None = None
    interest_level: InterestLevel | None = None

    def merge(self, update: "LeadUpdate") -> "Lead":
        changes = {k: v for k, v in update.as_dict().items() if v is not None}
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class LeadUpdate:
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    preferred_channel: PreferredChannel | None = None
    contact_consent: bool | None = None
    primary_use: PrimaryUse | None = None
    vehicle_type_interest: VehicleType | None = None
    powertrain_interest: Powertrain | None = None
    interest_level: InterestLevel | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "phone": self.phone,
            "email": self.email,
            "preferred_channel": self.preferred_channel,
            "contact_consent": self.contact_consent,
            "primary_use": self.primary_use,
            "vehicle_type_interest": self.vehicle_type_interest,
            "powertrain_interest": self.powertrain_interest,
            "interest_level": self.interest_level,
        }

    def is_empty(self) -> bool:
        return all(value is None for value in self.as_dict().values())

    def carries_contact_data(self) -> bool:
        return self.phone is not None or self.email is not None


@dataclass(frozen=True, slots=True)
class Handoff:
    id: int
    session_id: str
    user_id: UUID
    reason: HandoffReason
    requirement_summary: str
    status: HandoffStatus
    created_at: datetime
    preferred_channel: PreferredChannel | None = None
    urgency: Urgency | None = None

    @property
    def ticket(self) -> str:
        return f"TICK-{self.id:05d}"


_ALLOWED_HANDOFF_TRANSITIONS: dict[HandoffStatus, frozenset[HandoffStatus]] = {
    HandoffStatus.OPEN: frozenset({HandoffStatus.IN_PROGRESS, HandoffStatus.CLOSED}),
    HandoffStatus.IN_PROGRESS: frozenset({HandoffStatus.CLOSED}),
    HandoffStatus.CLOSED: frozenset(),
}


def can_transition(current: HandoffStatus, target: HandoffStatus) -> bool:
    return target in _ALLOWED_HANDOFF_TRANSITIONS[current]


@dataclass(frozen=True, slots=True)
class DialogState:
    stage: Stage = Stage.NEW
    just_browsing: bool = False
    previous_stage: Stage | None = None
