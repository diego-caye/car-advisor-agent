from uuid import UUID, uuid4

import pytest

from asesor.application.lead_service import LeadService
from asesor.domain.entities import Lead, LeadUpdate
from asesor.domain.enums import PrimaryUse, Stage, VehicleType
from asesor.domain.errors import ConsentRequiredError, EmptyUpdateError, InvalidPhoneError


class InMemoryLeadRepository:
    def __init__(self) -> None:
        self.leads: dict[UUID, Lead] = {}

    async def get(self, user_id: UUID) -> Lead | None:
        return self.leads.get(user_id)

    async def upsert(self, user_id: UUID, update: LeadUpdate) -> Lead:
        current = self.leads.get(user_id) or Lead(user_id=user_id)
        merged = current.merge(update)
        self.leads[user_id] = merged
        return merged


@pytest.fixture
def service() -> LeadService:
    return LeadService(InMemoryLeadRepository())


async def test_partial_update_keeps_previous_fields(service: LeadService) -> None:
    user = uuid4()

    await service.apply_update(user, LeadUpdate(name="Diego"), Stage.NEW)
    snapshot = await service.apply_update(
        user, LeadUpdate(primary_use=PrimaryUse.FAMILY), Stage.DISCOVERY
    )

    assert snapshot.lead.name == "Diego"
    assert snapshot.lead.primary_use is PrimaryUse.FAMILY


async def test_stage_is_recomputed_by_the_domain(service: LeadService) -> None:
    user = uuid4()

    snapshot = await service.apply_update(user, LeadUpdate(name="Diego"), Stage.NEW)
    assert snapshot.stage is Stage.DISCOVERY

    snapshot = await service.apply_update(
        user,
        LeadUpdate(primary_use=PrimaryUse.CITY, vehicle_type_interest=VehicleType.SUV),
        snapshot.stage,
    )
    assert snapshot.stage is Stage.CONCRETE_INTEREST


async def test_empty_update_is_rejected(service: LeadService) -> None:
    with pytest.raises(EmptyUpdateError):
        await service.apply_update(uuid4(), LeadUpdate(), Stage.NEW)


async def test_contact_data_without_consent_is_rejected(service: LeadService) -> None:
    with pytest.raises(ConsentRequiredError):
        await service.apply_update(uuid4(), LeadUpdate(phone="987654321"), Stage.NEW)

    with pytest.raises(ConsentRequiredError):
        await service.apply_update(uuid4(), LeadUpdate(email="a@b.com"), Stage.NEW)


async def test_contact_data_with_consent_is_normalized(service: LeadService) -> None:
    snapshot = await service.apply_update(
        uuid4(),
        LeadUpdate(phone="+51 987 654 321", contact_consent=True),
        Stage.NEW,
    )

    assert snapshot.lead.phone == "+51987654321"
    assert snapshot.lead.contact_consent is True


async def test_invalid_phone_is_rejected(service: LeadService) -> None:
    with pytest.raises(InvalidPhoneError):
        await service.apply_update(
            uuid4(),
            LeadUpdate(phone="123", contact_consent=True),
            Stage.NEW,
        )


async def test_snapshot_of_unknown_user_is_empty(service: LeadService) -> None:
    snapshot = await service.get_snapshot(uuid4(), Stage.NEW)

    assert snapshot.lead.name is None
    assert snapshot.stage is Stage.NEW
