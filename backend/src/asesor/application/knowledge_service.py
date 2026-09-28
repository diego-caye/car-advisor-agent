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
            # The LLM picks the category and sometimes gets it wrong: asking
            # for BODY_TYPES as SEGMENTS leaves out exactly the good
            # chunks. The filter is an optimization, not a condition: if it
            # returns nothing, it's retried without it.
            logger.info("no results in %s, retrying without filter", category.value)
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
            logger.warning("The knowledge base is empty: run scripts/ingest_kb.py")
            return

        if stored != self._embeddings.model_name:
            raise EmbeddingModelMismatchError(
                f"The KB was ingested with '{stored}' but EMBEDDINGS_MODEL is "
                f"'{self._embeddings.model_name}'. These are different vector spaces and "
                "their distances aren't comparable: re-ingest the KB "
                "(uv run python scripts/ingest_kb.py) or restore the previous model."
            )
