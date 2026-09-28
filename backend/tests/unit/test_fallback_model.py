from google.adk.models.google_llm import Gemini
from google.adk.models.lite_llm import LiteLlm

from asesor.config import AppEnv, LlmProviderName, ModelChoice, Settings
from asesor.infrastructure.container import build_fallback_model

BASE = {
    "app_env": AppEnv.TEST,
    "database_url": "postgresql+asyncpg://asesor:asesor@localhost:5432/asesor",
    "admin_token": "t",
    "agent_model": "ollama_chat/gemma4:latest",
    "guardrail_model": "ollama_chat/qwen3:4b-instruct",
    "eval_model": "ollama_chat/qwen3:4b-instruct",
    "fallback_model": "ollama_chat/llama3.2:3b",
    "embeddings_provider": "ollama",
    "embeddings_model": "embeddinggemma:300m",
    "ollama_api_base": "http://ollama-fake:11434",
    "llm_provider": "ollama",
    "guardrail_canary_token": "CANARY",
}


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def test_respaldo_de_ollama_es_litellm_aunque_el_principal_sea_gemini() -> None:
    """Real bug, seen live: the fallback's provider is dictated by
    FALLBACK_MODEL itself, not by the provider of the chosen primary model.
    It used to branch on choice.provider and this built a
    Gemini(model="ollama_chat/llama3.2:3b") -- a real 404 against the Gemini
    API when selecting Gemini from the selector with an Ollama fallback
    configured (this project's default case)."""
    settings = make(fallback_model="ollama_chat/llama3.2:3b")
    choice = ModelChoice(
        id="gemini", label="Gemini", provider=LlmProviderName.GEMINI, model="gemini-3.8-flash"
    )

    fallback = build_fallback_model(settings, choice)

    assert isinstance(fallback, LiteLlm)
    assert fallback.model == "ollama_chat/llama3.2:3b"


def test_respaldo_de_gemini_es_gemini_aunque_el_principal_sea_ollama() -> None:
    settings = make(fallback_model="gemini-3.8-flash")
    choice = ModelChoice(
        id="gemma4:latest",
        provider=LlmProviderName.OLLAMA,
        label="gemma4:latest",
        model="ollama_chat/gemma4:latest",
    )

    fallback = build_fallback_model(settings, choice)

    assert isinstance(fallback, Gemini)
    assert fallback.model == "gemini-3.8-flash"


def test_sin_respaldo_si_coincide_con_el_principal() -> None:
    settings = make(fallback_model="ollama_chat/gemma4:latest")
    choice = ModelChoice(
        id="gemma4:latest",
        provider=LlmProviderName.OLLAMA,
        label="gemma4:latest",
        model="ollama_chat/gemma4:latest",
    )

    assert build_fallback_model(settings, choice) is None
