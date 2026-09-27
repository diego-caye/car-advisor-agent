import logging

from asesor.domain.enums import KbCategory
from asesor.domain.knowledge import EmbeddingsPort, KnowledgeRetriever, RetrievedChunk

logger = logging.getLogger(__name__)


class EmbeddingModelMismatchError(RuntimeError):
    pass


class KnowledgeService:
    def __init__(
        self,
        embeddings: EmbeddingsPort,
        retriever: KnowledgeRetriever,
        min_score: float,
    ) -> None:
        self._embeddings = embeddings
        self._retriever = retriever
        self._min_score = min_score

    async def search(
        self, query: str, *, category: KbCategory | None, top_k: int
    ) -> list[RetrievedChunk]:
        """Return chunks above the score floor, or an empty list (no_results)."""
        embedding = await self._embeddings.embed_query(query)
        chunks = await self._retriever.search(embedding, category=category, top_k=top_k)
        accepted = self._above_floor(chunks)

        if not accepted and category is not None:
            # El LLM elige la categoría y a veces se equivoca: pedir CARROCERIAS
            # como SEGMENTOS deja fuera justo los fragmentos buenos. El filtro es
            # una optimización, no una condición: si no da nada, se reintenta sin él.
            logger.info("sin resultados en %s, reintentando sin filtro", category.value)
            chunks = await self._retriever.search(embedding, category=None, top_k=top_k)
            accepted = self._above_floor(chunks)

        return accepted

    def _above_floor(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not chunks or chunks[0].score < self._min_score:
            return []
        return [chunk for chunk in chunks if chunk.score >= self._min_score]

    async def verify_embedding_model(self) -> None:
        """Fail fast if the KB was ingested with another model: distinct vector spaces."""
        stored = await self._retriever.stored_embedding_model()
        if stored is None:
            logger.warning("La base de conocimiento está vacía: corre scripts/ingest_kb.py")
            return

        if stored != self._embeddings.model_name:
            raise EmbeddingModelMismatchError(
                f"La KB fue ingerida con '{stored}' pero EMBEDDINGS_MODEL es "
                f"'{self._embeddings.model_name}'. Son espacios vectoriales distintos y sus "
                "distancias no son comparables: vuelve a ingerir la KB "
                "(uv run python scripts/ingest_kb.py) o restaura el modelo anterior."
            )
