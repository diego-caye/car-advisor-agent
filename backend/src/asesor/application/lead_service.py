from dataclasses import dataclass, replace
from uuid import UUID

from asesor.domain.contact import normalize_phone
from asesor.domain.entities import Lead, LeadUpdate
from asesor.domain.enums import Stage
from asesor.domain.errors import ConsentRequiredError, EmptyUpdateError
from asesor.domain.ports import LeadRepository
from asesor.domain.stages import next_stage


@dataclass(frozen=True, slots=True)
class LeadSnapshot:
    lead: Lead
    stage: Stage


class LeadService:
    def __init__(self, repository: LeadRepository) -> None:
        self._repository = repository

    async def get_snapshot(self, user_id: UUID, current_stage: Stage) -> LeadSnapshot:
        lead = await self._repository.get(user_id) or Lead(user_id=user_id)
        return LeadSnapshot(lead=lead, stage=next_stage(current_stage, lead))

    async def apply_update(
        self, user_id: UUID, update: LeadUpdate, current_stage: Stage
    ) -> LeadSnapshot:
        if update.is_empty():
            raise EmptyUpdateError

        if update.carries_contact_data() and not update.contact_consent:
            raise ConsentRequiredError

        if update.phone is not None:
            update = replace(update, phone=normalize_phone(update.phone))

        lead = await self._repository.upsert(user_id, update)
        return LeadSnapshot(lead=lead, stage=next_stage(current_stage, lead))
