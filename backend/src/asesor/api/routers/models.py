from fastapi import APIRouter, Request

from asesor.api.dtos import ModelOption
from asesor.infrastructure.container import Container

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get("", response_model=list[ModelOption])
async def list_models(request: Request) -> list[ModelOption]:
    """Model selector catalog.

    For Ollama, this catalog doesn't come from configuration: it was
    discovered at startup against /api/tags + /api/show (see
    infrastructure.container), so it always reflects what's truly installed,
    with its real capabilities (supports_tools, supports_thinking).

    `available` is false for options whose provider isn't configured (Gemini
    without an API key, for example): the UI shows them disabled instead of
    hiding them, so it's clear what exists and why it can't be used.
    """
    container: Container = request.app.state.container
    settings = container.settings
    runners = container.runners

    return [
        ModelOption(
            id=option.id,
            label=option.label,
            provider=option.provider.value,
            model=option.model,
            available=settings.is_usable(option),
            is_default=option.id == runners.default_id,
            supports_tools=option.supports_tools,
            supports_thinking=option.supports_thinking,
        )
        for option in runners.catalog
    ]
