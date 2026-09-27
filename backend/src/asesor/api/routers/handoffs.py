from fastapi import APIRouter, Request

from asesor.api.dependencies import Admin
from asesor.api.dtos import HandoffDto, UpdateHandoffRequest
from asesor.api.errors import ConflictError, NotFoundError
from asesor.application.handoff_service import (
    HandoffNotFoundError,
    InvalidHandoffTransitionError,
)
from asesor.domain.entities import Handoff
from asesor.domain.enums import HandoffStatus
from asesor.infrastructure.container import Container

router = APIRouter(prefix="/api/v1/handoffs", tags=["handoffs"])


def _to_dto(handoff: Handoff) -> HandoffDto:
    return HandoffDto(
        id=handoff.id,
        ticket=handoff.ticket,
        session_id=handoff.session_id,
        user_id=handoff.user_id,
        reason=handoff.reason.value,
        requirement_summary=handoff.requirement_summary,
        preferred_channel=handoff.preferred_channel.value if handoff.preferred_channel else None,
        urgency=handoff.urgency.value if handoff.urgency else None,
        status=handoff.status.value,
        created_at=handoff.created_at,
    )


@router.get("", response_model=list[HandoffDto])
async def list_handoffs(
    request: Request, _: Admin, status: HandoffStatus | None = None
) -> list[HandoffDto]:
    container: Container = request.app.state.container
    handoffs = await container.handoff_service.list(status)
    return [_to_dto(handoff) for handoff in handoffs]


@router.patch("/{handoff_id}", response_model=HandoffDto)
async def update_handoff(
    request: Request, _: Admin, handoff_id: int, body: UpdateHandoffRequest
) -> HandoffDto:
    container: Container = request.app.state.container
    try:
        handoff = await container.handoff_service.change_status(
            handoff_id, HandoffStatus(body.status)
        )
    except HandoffNotFoundError as exc:
        raise NotFoundError(exc.message) from exc
    except InvalidHandoffTransitionError as exc:
        raise ConflictError(exc.message) from exc

    return _to_dto(handoff)
