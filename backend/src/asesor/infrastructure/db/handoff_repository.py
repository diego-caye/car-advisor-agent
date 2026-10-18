from uuid import UUID

from sqlalchemy import select

from asesor.domain.entities import Handoff
from asesor.domain.enums import HandoffReason, HandoffStatus, PreferredChannel, Urgency
from asesor.infrastructure.db.engine import SessionFactory
from asesor.infrastructure.db.models import HandoffRow


def _to_domain(row: HandoffRow) -> Handoff:
    return Handoff(
        id=row.id,
        session_id=row.session_id,
        user_id=row.user_id,
        reason=HandoffReason(row.reason),
        requirement_summary=row.requirement_summary,
        preferred_channel=PreferredChannel(row.preferred_channel)
        if row.preferred_channel
        else None,
        urgency=Urgency(row.urgency) if row.urgency else None,
        status=HandoffStatus(row.status),
        created_at=row.created_at,
    )


class SqlHandoffRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def find_open(self, session_id: str) -> Handoff | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(HandoffRow).where(
                    HandoffRow.session_id == session_id,
                    HandoffRow.status == HandoffStatus.OPEN.value,
                )
            )
            return _to_domain(row) if row else None

    async def get(self, handoff_id: int) -> Handoff | None:
        async with self._session_factory() as session:
            row = await session.get(HandoffRow, handoff_id)
            return _to_domain(row) if row else None

    async def create(
        self,
        *,
        session_id: str,
        user_id: UUID,
        reason: HandoffReason,
        requirement_summary: str,
        preferred_channel: PreferredChannel | None,
        urgency: Urgency | None,
    ) -> Handoff:
        async with self._session_factory() as session, session.begin():
            row = HandoffRow(
                session_id=session_id,
                user_id=user_id,
                reason=reason.value,
                requirement_summary=requirement_summary,
                preferred_channel=preferred_channel.value if preferred_channel else None,
                urgency=urgency.value if urgency else None,
                status=HandoffStatus.OPEN.value,
            )
            session.add(row)
            await session.flush()
            return _to_domain(row)

    async def list(self, status: HandoffStatus | None = None) -> list[Handoff]:
        statement = select(HandoffRow).order_by(HandoffRow.created_at.desc())
        if status is not None:
            statement = statement.where(HandoffRow.status == status.value)

        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
            return [_to_domain(row) for row in rows]

    async def set_status(self, handoff_id: int, status: HandoffStatus) -> Handoff:
        async with self._session_factory() as session, session.begin():
            row = await session.get(HandoffRow, handoff_id, with_for_update=True)
            if row is None:
                raise LookupError(handoff_id)
            row.status = status.value
            await session.flush()
            return _to_domain(row)
