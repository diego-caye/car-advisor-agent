from datetime import UTC, datetime

from fastapi import APIRouter, Request

from asesor.agent.parts import visible_text
from asesor.agent.state import read_dialog_state
from asesor.api.dependencies import UserId
from asesor.api.dtos import (
    CreateSessionResponse,
    DeclinedDecision,
    HandoffDecision,
    LeadDto,
    LeadResponse,
    MessageDto,
    SessionSummary,
)
from asesor.api.errors import NotFoundError
from asesor.application.chat_service import ChatService, SessionNotFoundError
from asesor.infrastructure.container import Container

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

HANDOFF_TOOL_NAME = "request_human_handoff"


def _container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def _chat_service(request: Request) -> ChatService:
    container = _container(request)
    return ChatService(container.runner, container.session_service)


@router.post("", response_model=CreateSessionResponse)
async def create_session(request: Request, user_id: UserId) -> CreateSessionResponse:
    session_id = await _chat_service(request).create_session(user_id)
    return CreateSessionResponse(session_id=session_id)


@router.get("", response_model=list[SessionSummary])
async def list_sessions(request: Request, user_id: UserId) -> list[SessionSummary]:
    container = _container(request)
    sessions = await _chat_service(request).list_sessions(user_id)
    # A single round trip for all titles, not one per session (spec 06).
    titles = await container.session_titles.get_many([session.id for session in sessions])
    summaries = [
        SessionSummary(
            session_id=session.id,
            titulo=titles.get(session.id),
            last_update_time=datetime.fromtimestamp(session.last_update_time, tz=UTC),
            stage=read_dialog_state(session.state).stage.value,
        )
        for session in sessions
    ]
    return sorted(summaries, key=lambda s: s.last_update_time, reverse=True)


@router.delete("/{session_id}", status_code=204)
async def delete_session(request: Request, user_id: UserId, session_id: str) -> None:
    try:
        await _chat_service(request).delete_session(user_id, session_id)
    except SessionNotFoundError as exc:
        raise NotFoundError("Session not found") from exc
    # The title and the feedback live apart from the ADK session: deleting
    # the session doesn't drag them along on its own, they have to be
    # cleaned up by hand.
    container = _container(request)
    await container.session_titles.delete(session_id)
    await container.feedback.delete_for_session(session_id)


@router.get("/{session_id}/messages", response_model=list[MessageDto])
async def list_messages(request: Request, user_id: UserId, session_id: str) -> list[MessageDto]:
    try:
        session = await _chat_service(request).get_session(user_id, session_id)
    except SessionNotFoundError as exc:
        raise NotFoundError("Session not found") from exc

    messages: list[MessageDto] = []
    # The handoff's reason doesn't travel in its final response (see
    # handoff_tools.py: "cancelado" doesn't include it), but it does in the
    # args of the original call to the tool -- same id as its response(s),
    # the pending one and the final one (verified against a real session,
    # not from memory: ADK 2.x isn't written without checking the installed
    # package).
    reason_by_call_id: dict[str, str] = {}

    for event in session.events:
        if event.content is None:
            continue

        for call in event.get_function_calls():
            if call.name == HANDOFF_TOOL_NAME and call.id:
                reason = (call.args or {}).get("reason")
                if reason:
                    reason_by_call_id[call.id] = reason

        for response in event.get_function_responses():
            if response.name != HANDOFF_TOOL_NAME or not messages:
                continue
            data = response.response.get("data") if isinstance(response.response, dict) else None
            if not isinstance(data, dict):
                continue
            if data.get("ticket"):
                messages[-1].decision = HandoffDecision(
                    ticket=data["ticket"], ya_existia=bool(data.get("ya_existia", False))
                )
            elif data.get("cancelado"):
                # Reason unknown (shouldn't happen, see comment above): the
                # frontend's own card falls back to a generic label.
                reason = reason_by_call_id.get(response.id or "", "")
                messages[-1].decision = DeclinedDecision(reason=reason)

        text = visible_text(event.content)
        if not text or event.partial:
            continue
        messages.append(
            MessageDto(
                role="user" if event.content.role == "user" else "agent",
                content=text,
                created_at=datetime.fromtimestamp(event.timestamp, tz=UTC),
            )
        )
    return messages


@router.get("/{session_id}/lead", response_model=LeadResponse)
async def get_lead(request: Request, user_id: UserId, session_id: str) -> LeadResponse:
    container = _container(request)
    try:
        session = await _chat_service(request).get_session(user_id, session_id)
    except SessionNotFoundError as exc:
        raise NotFoundError("Session not found") from exc

    dialog = read_dialog_state(session.state)
    snapshot = await container.lead_service.get_snapshot(user_id, dialog.stage)
    lead = snapshot.lead

    return LeadResponse(
        lead=LeadDto(
            name=lead.name,
            phone=lead.phone,
            email=lead.email,
            preferred_channel=lead.preferred_channel,
            contact_consent=lead.contact_consent,
            primary_use=lead.primary_use,
            vehicle_type_interest=lead.vehicle_type_interest,
            powertrain_interest=lead.powertrain_interest,
            interest_level=lead.interest_level,
        ),
        stage=snapshot.stage.value,
        just_browsing=dialog.just_browsing,
    )
