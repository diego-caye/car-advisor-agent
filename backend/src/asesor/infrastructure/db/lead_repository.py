from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from asesor.domain.entities import Lead, LeadUpdate
from asesor.domain.enums import (
    InterestLevel,
    Powertrain,
    PreferredChannel,
    PrimaryUse,
    VehicleType,
)
from asesor.infrastructure.db.engine import SessionFactory
from asesor.infrastructure.db.models import LeadRow


def _to_domain(row: LeadRow) -> Lead:
    return Lead(
        user_id=row.user_id,
        name=row.name,
        phone=row.phone,
        email=row.email,
        preferred_channel=PreferredChannel(row.preferred_channel)
        if row.preferred_channel
        else None,
        contact_consent=row.contact_consent,
        primary_use=PrimaryUse(row.primary_use) if row.primary_use else None,
        vehicle_type_interest=(
            VehicleType(row.vehicle_type_interest) if row.vehicle_type_interest else None
        ),
        powertrain_interest=(
            Powertrain(row.powertrain_interest) if row.powertrain_interest else None
        ),
        interest_level=InterestLevel(row.interest_level) if row.interest_level else None,
    )


class SqlLeadRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get(self, user_id: UUID) -> Lead | None:
        async with self._session_factory() as session:
            row = await session.scalar(select(LeadRow).where(LeadRow.user_id == user_id))
            return _to_domain(row) if row else None

    async def upsert(self, user_id: UUID, update: LeadUpdate) -> Lead:
        changes: dict[str, Any] = {
            key: (value.value if hasattr(value, "value") else value)
            for key, value in update.as_dict().items()
            if value is not None
        }

        async with self._session_factory() as session, session.begin():
            statement = (
                pg_insert(LeadRow)
                .values(user_id=user_id, **changes)
                .on_conflict_do_update(
                    index_elements=[LeadRow.user_id],
                    set_={**changes, "updated_at": func.now()},
                )
                .returning(LeadRow)
            )
            row = (await session.scalars(statement)).one()
            return _to_domain(row)
