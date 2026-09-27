from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from asesor.domain.enums import KbCategory

EMBEDDING_DIMENSIONS = 768


@dataclass(frozen=True, slots=True)
class KbChunk:
    chunk_id: str
    title: str
    category: KbCategory
    source: str
    content: str


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    title: str
    category: KbCategory
    source: str
    content: str
    score: float


class EmbeddingsPort(Protocol):
    @property
    def model_name(self) -> str: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class KnowledgeRetriever(Protocol):
    async def search(
        self,
        embedding: Sequence[float],
        *,
        category: KbCategory | None,
        top_k: int,
    ) -> list[RetrievedChunk]: ...

    async def stored_embedding_model(self) -> str | None: ...
