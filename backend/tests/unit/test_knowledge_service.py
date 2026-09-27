from collections.abc import Sequence

import pytest

from asesor.application.knowledge_service import EmbeddingModelMismatchError, KnowledgeService
from asesor.domain.enums import KbCategory
from asesor.domain.knowledge import RetrievedChunk
from asesor.infrastructure.embeddings.fake import FakeEmbeddings


class StubRetriever:
    def __init__(self, chunks: list[RetrievedChunk], model: str | None) -> None:
        self.chunks = chunks
        self.model = model
        self.last_category: KbCategory | None = None

    async def search(
        self, embedding: Sequence[float], *, category: KbCategory | None, top_k: int
    ) -> list[RetrievedChunk]:
        self.last_category = category
        return self.chunks[:top_k]

    async def stored_embedding_model(self) -> str | None:
        return self.model


def chunk(chunk_id: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        title="t",
        category=KbCategory.BODY_TYPES,
        source="s.md",
        content="c",
        score=score,
    )


async def test_devuelve_vacio_si_el_mejor_score_no_alcanza_el_umbral() -> None:
    retriever = StubRetriever([chunk("a", 0.40), chunk("b", 0.30)], "fake-embeddings")
    service = KnowledgeService(FakeEmbeddings(), retriever, min_score=0.55)

    assert await service.search("q", category=None, top_k=4) == []


async def test_filtra_los_que_quedan_bajo_el_umbral() -> None:
    retriever = StubRetriever([chunk("a", 0.80), chunk("b", 0.20)], "fake-embeddings")
    service = KnowledgeService(FakeEmbeddings(), retriever, min_score=0.55)

    result = await service.search("q", category=None, top_k=4)

    assert [c.chunk_id for c in result] == ["a"]


async def test_propaga_el_filtro_de_categoria() -> None:
    retriever = StubRetriever([chunk("a", 0.90)], "fake-embeddings")
    service = KnowledgeService(FakeEmbeddings(), retriever, min_score=0.5)

    await service.search("q", category=KbCategory.POWERTRAIN, top_k=2)

    assert retriever.last_category is KbCategory.POWERTRAIN


async def test_verifica_que_el_modelo_de_embeddings_coincide() -> None:
    service = KnowledgeService(
        FakeEmbeddings(), StubRetriever([], "gemini-embedding-001"), min_score=0.5
    )

    with pytest.raises(EmbeddingModelMismatchError, match=r"re-?ing|ingerir"):
        await service.verify_embedding_model()


async def test_una_kb_vacia_no_bloquea_el_arranque() -> None:
    service = KnowledgeService(FakeEmbeddings(), StubRetriever([], None), min_score=0.5)

    await service.verify_embedding_model()


async def test_modelo_coincidente_no_lanza() -> None:
    service = KnowledgeService(
        FakeEmbeddings(), StubRetriever([], "fake-embeddings"), min_score=0.5
    )

    await service.verify_embedding_model()


class CategoryAwareRetriever:
    """Devuelve resultados solo cuando NO se filtra por categoría."""

    def __init__(self) -> None:
        self.categories_requested: list[KbCategory | None] = []

    async def search(
        self, embedding: Sequence[float], *, category: KbCategory | None, top_k: int
    ) -> list[RetrievedChunk]:
        self.categories_requested.append(category)
        return [] if category is not None else [chunk("a", 0.80)]

    async def stored_embedding_model(self) -> str | None:
        return "fake-embeddings"


async def test_reintenta_sin_filtro_si_la_categoria_no_da_resultados() -> None:
    retriever = CategoryAwareRetriever()
    service = KnowledgeService(FakeEmbeddings(), retriever, min_score=0.5)

    result = await service.search("q", category=KbCategory.SEGMENTS, top_k=4)

    assert [c.chunk_id for c in result] == ["a"]
    assert retriever.categories_requested == [KbCategory.SEGMENTS, None]


async def test_no_reintenta_si_ya_venia_sin_filtro() -> None:
    retriever = StubRetriever([], "fake-embeddings")
    service = KnowledgeService(FakeEmbeddings(), retriever, min_score=0.5)

    assert await service.search("q", category=None, top_k=4) == []
