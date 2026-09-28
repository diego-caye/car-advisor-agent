from collections.abc import Sequence
from typing import Any, cast

from google import genai
from google.genai import types

from asesor.domain.knowledge import EMBEDDING_DIMENSIONS

# gemini-embedding-2 doesn't accept task_type: the task goes as an
# instruction in the text (gotcha from specs/11-llm-providers.md §2).
_MODELS_WITHOUT_TASK_TYPE = ("gemini-embedding-2",)

_QUERY_INSTRUCTION = "Consulta de búsqueda sobre asesoría automotriz: "
_DOCUMENT_INSTRUCTION = "Documento de referencia sobre asesoría automotriz: "


class GeminiEmbeddings:
    def __init__(self, model: str, api_key: str | None, use_vertexai: bool = False) -> None:
        self._model = model
        self._client = (
            genai.Client(vertexai=True) if use_vertexai else genai.Client(api_key=api_key)
        )

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def _supports_task_type(self) -> bool:
        return not self._model.startswith(_MODELS_WITHOUT_TASK_TYPE)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(list(texts), task_type="RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text], task_type="RETRIEVAL_QUERY")
        return vectors[0]

    async def _embed(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        if self._supports_task_type:
            config = types.EmbedContentConfig(
                task_type=task_type, output_dimensionality=EMBEDDING_DIMENSIONS
            )
            payload = texts
        else:
            config = types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS)
            prefix = _QUERY_INSTRUCTION if task_type == "RETRIEVAL_QUERY" else _DOCUMENT_INSTRUCTION
            payload = [prefix + text for text in texts]

        response = await self._client.aio.models.embed_content(
            model=self._model,
            # list[str] is invariant with respect to the union the SDK declares.
            contents=cast("Any", payload),
            config=config,
        )

        embeddings = response.embeddings or []
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Embeddings API returned {len(embeddings)} vectors for {len(texts)} inputs"
            )

        return [list(embedding.values or []) for embedding in embeddings]
