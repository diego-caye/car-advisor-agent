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
        """Searches the automotive knowledge base before explaining technical topics.

        Use it whenever the user asks about body types, segments, powertrains,
        transmissions, fuel economy, maintenance, or safety. If the search returns
        no results, say so honestly instead of guessing.

        Args:
            query: The question or topic to search for, up to 300 characters.
            category: Optional filter. One of BODY_TYPES, SEGMENTS, POWERTRAIN,
                TRANSMISSION, FUEL_ECONOMY, MAINTENANCE, SAFETY, USAGE, GLOSSARY.
            top_k: How many chunks to fetch, 1 to 8. Defaults to 4.

        Returns:
            The chunks found with their title and source, or no_results.
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
            # A downed RAG follows the same path as no_results (spec 07 §3):
            # the turn doesn't break and the agent uses the honest phrase.
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
