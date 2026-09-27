from collections.abc import Sequence

from sqlalchemy import select

from asesor.domain.enums import KbCategory
from asesor.domain.knowledge import RetrievedChunk
from asesor.infrastructure.db.engine import SessionFactory
from asesor.infrastructure.db.models import KbChunkRow


class PgVectorRetriever:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def search(
        self,
        embedding: Sequence[float],
        *,
        category: KbCategory | None,
        top_k: int,
    ) -> list[RetrievedChunk]:
        distance = KbChunkRow.embedding.cosine_distance(list(embedding))
        statement = select(KbChunkRow, distance.label("distance")).order_by(distance).limit(top_k)

        if category is not None:
            statement = statement.where(KbChunkRow.category == category.value)

        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()

        return [
            RetrievedChunk(
                chunk_id=row.chunk_id,
                title=row.title,
                category=KbCategory(row.category),
                source=row.source,
                content=row.content,
                # pgvector devuelve distancia coseno en [0, 2]; el score es la similitud.
                score=1.0 - float(row_distance),
            )
            for row, row_distance in rows
        ]

    async def stored_embedding_model(self) -> str | None:
        async with self._session_factory() as session:
            model: str | None = await session.scalar(select(KbChunkRow.embedding_model).limit(1))
            return model
