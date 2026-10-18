from collections.abc import Sequence

import httpx

from asesor.domain.knowledge import EMBEDDING_DIMENSIONS

# embeddinggemma was trained with task prefixes: they separate "this is a
# query" from "this is a document" and improve recall. They go in the text
# because Ollama's embeddings API doesn't have a task_type parameter.
_QUERY_PREFIX = "task: search result | query: "
_DOCUMENT_PREFIX = "title: none | text: "

DEFAULT_TIMEOUT = 120.0


class OllamaEmbeddings:
    def __init__(self, model: str, api_base: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._model = model
        self._base_url = api_base.rstrip("/")
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed([_DOCUMENT_PREFIX + text for text in texts])

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([_QUERY_PREFIX + text])
        return vectors[0]

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": inputs},
            )
            response.raise_for_status()
            payload = response.json()

        vectors: list[list[float]] = payload.get("embeddings") or []
        if len(vectors) != len(inputs):
            raise RuntimeError(f"Ollama returned {len(vectors)} vectors for {len(inputs)} inputs")

        for vector in vectors:
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise RuntimeError(
                    f"Model '{self._model}' returns {len(vector)} dimensions, "
                    f"but the kb_chunks table expects {EMBEDDING_DIMENSIONS}"
                )

        return vectors
