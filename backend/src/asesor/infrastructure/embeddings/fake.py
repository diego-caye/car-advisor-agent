import math
import re
import unicodedata
from collections.abc import Sequence

from asesor.domain.knowledge import EMBEDDING_DIMENSIONS

_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbeddings:
    """Hashed bag-of-words, deterministic and network-free.

    It's not a semantic model: two texts are similar if they share words. It's
    enough for the RAG tests, where what's being verified is the wiring
    (threshold, category filter, ordering) and not embedding quality.
    """

    def __init__(self, model_name: str = "fake-embeddings") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS

        for word in _WORD.findall(_normalize(text)):
            if len(word) < 3:
                continue
            vector[_bucket(word)] += 1.0

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            vector[0] = 1.0
            return vector

        return [value / norm for value in vector]


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _bucket(word: str) -> int:
    # Stable hash across processes: Python's hash() is randomized by PYTHONHASHSEED.
    value = 0
    for char in word:
        value = (value * 131 + ord(char)) % EMBEDDING_DIMENSIONS
    return value
