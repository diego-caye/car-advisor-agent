from fastapi import APIRouter, Request

from asesor.api.dependencies import UserId
from asesor.api.dtos import FeedbackDto, FeedbackRequest, FeedbackResponse
from asesor.api.errors import NotFoundError
from asesor.application.chat_service import ChatService, SessionNotFoundError
from asesor.infrastructure.container import Container
from asesor.infrastructure.db.feedback_repository import FeedbackEntry
from asesor.infrastructure.telemetry import send_langfuse_score

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


def _container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def _to_dto(entry: FeedbackEntry) -> FeedbackDto:
    return FeedbackDto(
        id=entry.id,
        session_id=entry.session_id,
        trace_id=entry.trace_id,
        score=entry.score,
        message=entry.message,
        comment=entry.comment,
        created_at=entry.created_at,
    )


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    request: Request, user_id: UserId, body: FeedbackRequest
) -> FeedbackResponse:
    container = _container(request)

    try:
        await ChatService(container.runner, container.session_service).get_session(
            user_id, body.session_id
        )
    except SessionNotFoundError as exc:
        raise NotFoundError("Session not found") from exc

    await container.feedback.add(
        session_id=body.session_id,
        user_id=user_id,
        trace_id=body.trace_id,
        score=body.score,
        message=body.message,
        comment=body.comment,
    )

    # Best-effort: Langfuse allows attaching a score to an already-closed
    # trace (spec 08 S4). If it fails or isn't configured, the feedback was
    # already saved above -- it never blocks or fails the endpoint.
    await send_langfuse_score(
        container.settings,
        trace_id=body.trace_id,
        name="user-feedback",
        value=body.score,
        comment=body.comment,
    )

    return FeedbackResponse()


@router.get("", response_model=list[FeedbackDto])
async def list_feedback(request: Request, limit: int = 100) -> list[FeedbackDto]:
    # No admin_token on purpose: the project doesn't have a real auth model
    # anywhere else (X-User-Id is a UUID the client itself sets, trivial to
    # fake), so requiring a token from whoever is evaluating the challenge
    # just to see the feedback panel was friction with no real security
    # behind it -- at the human's request.
    container = _container(request)
    entries = await container.feedback.list(limit)
    return [_to_dto(entry) for entry in entries]


@router.delete("/{feedback_id}", status_code=204)
async def delete_feedback(request: Request, feedback_id: int) -> None:
    # Same criteria as the GET above: no admin_token or X-User-Id, it's a
    # review panel and the project doesn't have real auth anywhere else. It
    # would gate it if it deleted more than just the dev panel's row.
    container = _container(request)
    deleted = await container.feedback.delete(feedback_id)
    if not deleted:
        raise NotFoundError("Feedback not found")
