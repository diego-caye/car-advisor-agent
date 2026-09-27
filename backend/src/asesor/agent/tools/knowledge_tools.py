from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from asesor.agent.tools.envelope import error, no_results, ok
from asesor.application.knowledge_service import KnowledgeService
from asesor.domain.enums import KbCategory

SearchKnowledgeBase = Callable[..., Awaitable[dict[str, Any]]]


class _SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    category: KbCategory | None = None
    top_k: int = Field(default=4, ge=1, le=8)


def make_search_knowledge_base(knowledge_service: KnowledgeService) -> SearchKnowledgeBase:
    async def search_knowledge_base(
        query: str,
        category: str | None = None,
        top_k: int = 4,
    ) -> dict[str, Any]:
        """Busca en la guía técnica automotriz antes de explicar temas técnicos.

        Úsala siempre que el usuario pregunte por carrocerías, segmentos,
        motorizaciones, transmisiones, consumo, mantenimiento o seguridad. Si la
        búsqueda no devuelve resultados, dilo con honestidad en vez de suponer.

        Args:
            query: La pregunta o el tema a buscar, hasta 300 caracteres.
            category: Filtro opcional. Una de BODY_TYPES, SEGMENTS, POWERTRAIN,
                TRANSMISSION, FUEL_ECONOMY, MAINTENANCE, SAFETY, USAGE, GLOSSARY.
            top_k: Cuántos fragmentos traer, de 1 a 8. Por defecto 4.

        Returns:
            Los fragmentos encontrados con su título y fuente, o no_results.
        """
        try:
            args = _SearchArgs(query=query, category=category, top_k=top_k)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(part) for part in first["loc"])
            return error("VALIDATION_ERROR", f"{field}: {first['msg']}")

        try:
            chunks = await knowledge_service.search(
                args.query, category=args.category, top_k=args.top_k
            )
        except Exception:
            # RAG caído sigue el mismo camino que no_results (spec 07 §3): el turno
            # no se rompe y el agente usa la frase honesta.
            return no_results()

        if not chunks:
            return no_results()

        return ok(
            {
                "resultados": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "title": chunk.title,
                        "category": chunk.category.value,
                        "source": chunk.source,
                        "score": round(chunk.score, 4),
                        "content": chunk.content,
                    }
                    for chunk in chunks
                ]
            }
        )

    return search_knowledge_base
