from collections.abc import AsyncIterator
from uuid import UUID

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, Session
from google.adk.tools.tool_confirmation import ToolConfirmation
from google.genai import types

from asesor.agent.factory import APP_NAME
from asesor.agent.guardrails.faults import FAULT_STATE_KEY, Fault
from asesor.infrastructure.fault_context import use_fault

CONFIRMATION_CALL_NAME = "adk_request_confirmation"


class SessionNotFoundError(LookupError):
    pass


class ChatService:
    def __init__(self, runner: Runner, session_service: BaseSessionService) -> None:
        self._runner = runner
        self._session_service = session_service

    async def create_session(self, user_id: UUID) -> str:
        session = await self._session_service.create_session(
            app_name=APP_NAME, user_id=str(user_id)
        )
        return session.id

    async def list_sessions(self, user_id: UUID) -> list[Session]:
        response = await self._session_service.list_sessions(
            app_name=APP_NAME, user_id=str(user_id)
        )
        return list(response.sessions)

    async def get_session(self, user_id: UUID, session_id: str) -> Session:
        session = await self._session_service.get_session(
            app_name=APP_NAME, user_id=str(user_id), session_id=session_id
        )
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    async def delete_session(self, user_id: UUID, session_id: str) -> None:
        # get_session first so as not to reveal the existence of other users'
        # sessions: if it's not the user's, it comes back 404 just as if it
        # didn't exist.
        await self.get_session(user_id, session_id)
        await self._session_service.delete_session(
            app_name=APP_NAME, user_id=str(user_id), session_id=session_id
        )

    async def run_turn(
        self, user_id: UUID, session_id: str, message: str, fault: Fault | None = None
    ) -> AsyncIterator[Event]:
        content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
        async for event in self._run(user_id, session_id, content, fault):
            yield event

    async def resume_with_confirmation(
        self, user_id: UUID, session_id: str, confirmation_id: str, approved: bool
    ) -> AsyncIterator[Event]:
        """Resumes the paused turn by answering ADK's tool confirmation.

        The format is fixed by ADK: a user function response called
        `adk_request_confirmation`, with the id of the confirmation call
        (F3 spike, ADR-002).
        """
        answer = ToolConfirmation(confirmed=approved)
        part = types.Part.from_function_response(
            name=CONFIRMATION_CALL_NAME, response=answer.model_dump(mode="json")
        )
        if part.function_response is not None:
            part.function_response.id = confirmation_id

        async for event in self._run(user_id, session_id, types.Content(role="user", parts=[part])):
            yield event

    async def _run(
        self,
        user_id: UUID,
        session_id: str,
        content: types.Content,
        fault: Fault | None = None,
    ) -> AsyncIterator[Event]:
        await self.get_session(user_id, session_id)

        with use_fault(fault):
            async for event in self._runner.run_async(
                user_id=str(user_id),
                session_id=session_id,
                new_message=content,
                state_delta={FAULT_STATE_KEY: fault.value} if fault else None,
                run_config=RunConfig(streaming_mode=StreamingMode.SSE),
            ):
                yield event
