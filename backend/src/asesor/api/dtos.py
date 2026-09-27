from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateSessionResponse(BaseModel):
    session_id: str


class SessionSummary(BaseModel):
    titulo: str | None = None
    session_id: str
    last_update_time: datetime
    stage: str


class HandoffDecision(BaseModel):
    kind: Literal["handoff"] = "handoff"
    ticket: str
    ya_existia: bool


class DeclinedDecision(BaseModel):
    kind: Literal["declined"] = "declined"
    reason: str


MessageDecision = Annotated[HandoffDecision | DeclinedDecision, Field(discriminator="kind")]


class MessageDto(BaseModel):
    role: str
    content: str
    created_at: datetime
    # Eco persistente de una confirmación HITL ya resuelta (spec 02, 03 §3):
    # sin esto, recargar una conversación con handoff perdía el aviso de
    # "derivado"/"ahora no" y quedaba como si el mensaje del agente nunca
    # hubiera pasado por ahí.
    decision: MessageDecision | None = None


class LeadDto(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    preferred_channel: str | None = None
    contact_consent: bool = False
    primary_use: str | None = None
    vehicle_type_interest: str | None = None
    powertrain_interest: str | None = None
    interest_level: str | None = None


class LeadResponse(BaseModel):
    lead: LeadDto | None
    stage: str
    just_browsing: bool


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=2000)
    model_id: str | None = None


class FeedbackRequest(BaseModel):
    session_id: str
    trace_id: str
    score: Literal[1, -1]
    message: str = Field(min_length=1, max_length=4000)
    comment: str | None = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    ok: bool = True


class FeedbackDto(BaseModel):
    id: int
    session_id: str
    trace_id: str
    score: int
    message: str
    comment: str | None = None
    created_at: datetime


class ModelOption(BaseModel):
    id: str
    label: str
    provider: str
    model: str
    available: bool
    is_default: bool
    supports_tools: bool
    supports_thinking: bool


class ConfirmationRequest(BaseModel):
    session_id: str
    confirmation_id: str
    approved: bool
    comment: str | None = Field(default=None, max_length=500)
    # Reanudar con el mismo modelo que pidió la confirmación: cambiar a mitad
    # de un turno pausado mezclaría dos modelos en la misma respuesta.
    model_id: str | None = None


class HandoffDto(BaseModel):
    id: int
    ticket: str
    session_id: str
    user_id: UUID
    reason: str
    requirement_summary: str
    preferred_channel: str | None = None
    urgency: str | None = None
    status: str
    created_at: datetime


class UpdateHandoffRequest(BaseModel):
    status: Literal["IN_PROGRESS", "CLOSED"]


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    db: str
    llm: str
    detail: dict[str, Any] | None = None
