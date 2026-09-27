from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from asesor.domain.knowledge import EMBEDDING_DIMENSIONS


class Base(DeclarativeBase):
    pass


class LeadRow(Base):
    __tablename__ = "leads"

    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(80), default=None)
    phone: Mapped[str | None] = mapped_column(String(20), default=None)
    email: Mapped[str | None] = mapped_column(String(254), default=None)
    preferred_channel: Mapped[str | None] = mapped_column(String(16), default=None)
    contact_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    primary_use: Mapped[str | None] = mapped_column(String(16), default=None)
    vehicle_type_interest: Mapped[str | None] = mapped_column(String(16), default=None)
    powertrain_interest: Mapped[str | None] = mapped_column(String(16), default=None)
    interest_level: Mapped[str | None] = mapped_column(String(8), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HandoffRow(Base):
    __tablename__ = "handoffs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), index=True)
    reason: Mapped[str] = mapped_column(String(24))
    requirement_summary: Mapped[str] = mapped_column(Text)
    preferred_channel: Mapped[str | None] = mapped_column(String(16), default=None)
    urgency: Mapped[str | None] = mapped_column(String(8), default=None)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Idempotencia de spec 03: como maximo un handoff OPEN por sesion.
        Index(
            "ux_handoffs_one_open_per_session",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )


class SessionTitleRow(Base):
    """El título de una conversación, fuera de la sesión de ADK a propósito.

    Guardarlo como estado de sesión (un append_event con state_delta) competía
    por el mismo lock optimista que el turno de chat: si el título se escribía
    mientras un turno siguiente en la misma sesión seguía en vuelo, el append
    del propio turno salía rechazado con StaleSessionError — un adorno de la
    barra lateral tumbando la respuesta real. Una tabla aparte no comparte ese
    candado con nada.
    """

    __tablename__ = "session_titles"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackRow(Base):
    """Feedback 👍/👎 del usuario sobre un turno (spec 02, spec 08 S4).

    Solo se escribe, nada dentro de la app lo vuelve a leer: vive aquí para
    tener un respaldo propio incluso sin Langfuse configurado (el score
    `user-feedback` se manda ahí también, pero eso es best-effort).
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), index=True)
    trace_id: Mapped[str] = mapped_column(String(64))
    score: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationRow(Base):
    """Un criterio evaluado de un turno (spec 08 S5), una fila por criterio.

    Igual que feedback: solo se escribe desde EvaluationService, nada dentro
    de la app la vuelve a leer. El score tambien se manda a Langfuse
    (best-effort); esta tabla es el respaldo propio que sobrevive sin eso.
    """

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    criterio: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)
    justificacion: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbChunkRow(Base):
    __tablename__ = "kb_chunks"

    chunk_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "ix_kb_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
