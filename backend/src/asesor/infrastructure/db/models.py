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
    nombre: Mapped[str | None] = mapped_column(String(80), default=None)
    telefono: Mapped[str | None] = mapped_column(String(20), default=None)
    email: Mapped[str | None] = mapped_column(String(254), default=None)
    canal_preferido: Mapped[str | None] = mapped_column(String(16), default=None)
    consentimiento_contacto: Mapped[bool] = mapped_column(Boolean, default=False)
    uso_principal: Mapped[str | None] = mapped_column(String(16), default=None)
    tipo_vehiculo_interes: Mapped[str | None] = mapped_column(String(16), default=None)
    motorizacion_interes: Mapped[str | None] = mapped_column(String(16), default=None)
    nivel_interes: Mapped[str | None] = mapped_column(String(8), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HandoffRow(Base):
    __tablename__ = "handoffs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), index=True)
    motivo: Mapped[str] = mapped_column(String(24))
    resumen_requerimiento: Mapped[str] = mapped_column(Text)
    canal_preferido: Mapped[str | None] = mapped_column(String(16), default=None)
    urgencia: Mapped[str | None] = mapped_column(String(8), default=None)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Idempotency from spec 03: at most one OPEN handoff per session.
        Index(
            "ux_handoffs_one_open_per_session",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )


class SessionTitleRow(Base):
    """A conversation's title, kept outside the ADK session on purpose.

    Storing it as session state (an append_event with state_delta) competed
    for the same optimistic lock as the chat turn: if the title was being
    written while a following turn in the same session was still in flight,
    that turn's own append would come back rejected with StaleSessionError —
    a sidebar decoration taking down the actual response. A separate table
    doesn't share that lock with anything.
    """

    __tablename__ = "session_titles"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackRow(Base):
    """User's 👍/👎 feedback on a turn (spec 02, spec 08 S4).

    Write-only, nothing inside the app reads it back: it lives here to have
    its own backup even without Langfuse configured (the `user-feedback`
    score is also sent there, but that's best-effort).
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
    """An evaluated criterion of a turn (spec 08 S5), one row per criterion.

    Same as feedback: only written from EvaluationService, nothing inside
    the app reads it back. The score is also sent to Langfuse (best-effort);
    this table is the own backup that survives without that.
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
    categoria: Mapped[str] = mapped_column(String(16), index=True)
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
