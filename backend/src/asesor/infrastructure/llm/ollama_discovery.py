import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OllamaModelInfo:
    """A chat model installed in Ollama, with its real capabilities."""

    name: str  # exactly as Ollama returns it, e.g. "gemma4:12b"
    supports_tools: bool
    supports_thinking: bool


async def discover_ollama_models(api_base: str, timeout: float = 10.0) -> list[OllamaModelInfo]:
    """Chat models currently installed in Ollama, via /api/tags + /api/show.

    None of this is declared by hand: the Ollama selector's catalog comes
    from whatever the server reports having *pulled*, so it never gets out
    of sync with reality (a deleted model, a new one, a tag different from
    the last time someone touched the .env).

    /api/show returns `capabilities`, a list like ["completion", "tools",
    "thinking"] or ["embedding"]. Models without "completion" are discarded
    (embeddings-only ones, like embeddinggemma, aren't usable for chat and
    would only clutter the selector).

    If Ollama doesn't respond (turned off, still starting up, wrong URL), an
    empty list is returned instead of taking down the backend's startup: the
    selector is left without local options, it's not a fatal failure.
    """
    async with httpx.AsyncClient(base_url=api_base, timeout=timeout) as client:
        try:
            tags_response = await client.get("/api/tags")
            tags_response.raise_for_status()
        except httpx.HTTPError:
            logger.warning("could not list Ollama models at %s", api_base, exc_info=True)
            return []

        names = [entry["name"] for entry in tags_response.json().get("models", [])]

        models: list[OllamaModelInfo] = []
        for name in names:
            try:
                show_response = await client.post("/api/show", json={"model": name})
                show_response.raise_for_status()
            except httpx.HTTPError:
                logger.warning("could not query /api/show for %s", name, exc_info=True)
                continue

            capabilities = set(show_response.json().get("capabilities") or [])
            if "completion" not in capabilities:
                continue

            models.append(
                OllamaModelInfo(
                    name=name,
                    supports_tools="tools" in capabilities,
                    supports_thinking="thinking" in capabilities,
                )
            )

        return models
