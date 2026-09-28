import pytest
from pydantic import ValidationError

from asesor.config import AppEnv, EmbeddingsProviderName, LlmProviderName, Settings

BASE = {
    "app_env": AppEnv.TEST,
    "database_url": "postgresql+asyncpg://asesor:asesor@localhost:5432/asesor",
    "admin_token": "t",
    "google_api_key": "k",
    "agent_model": "gemini-3.8-flash",
    "guardrail_model": "gemini-3.5-flash-lite",
    "eval_model": "gemini-3.5-flash",
    "fallback_model": "gemini-3.7-flash",
    "embeddings_model": "gemini-embedding-001",
    "guardrail_canary_token": "CANARY",
}


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def test_sync_dsn_is_derived_from_async_dsn() -> None:
    assert make().database_url_sync == "postgresql+psycopg://asesor:asesor@localhost:5432/asesor"


def test_rejects_non_async_driver() -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        make(database_url="postgresql://asesor:asesor@localhost:5432/asesor")


def test_gemini_requires_api_key_unless_vertex() -> None:
    with pytest.raises(ValidationError, match="GOOGLE_API_KEY"):
        make(google_api_key=None)

    assert make(google_api_key=None, google_genai_use_vertexai=True).google_api_key is None


OLLAMA = {
    "llm_provider": LlmProviderName.OLLAMA,
    "ollama_api_base": "http://localhost:11434",
    "agent_model": "ollama_chat/gemma4:latest",
}


def test_ollama_requires_api_base() -> None:
    with pytest.raises(ValidationError, match="OLLAMA_API_BASE"):
        make(**{**OLLAMA, "ollama_api_base": None})

    assert make(**OLLAMA).llm_provider is LlmProviderName.OLLAMA


def test_ollama_rechaza_el_prefijo_equivocado() -> None:
    # ollama/ can cause tool-calling loops: only ollama_chat/ is valid.
    with pytest.raises(ValidationError, match="ollama_chat/"):
        make(**{**OLLAMA, "agent_model": "ollama/gemma4:latest"})

    with pytest.raises(ValidationError, match="ollama_chat/"):
        make(**{**OLLAMA, "agent_model": "gemma4:latest"})


def test_ollama_embeddings_require_api_base() -> None:
    with pytest.raises(ValidationError, match="OLLAMA_API_BASE"):
        make(embeddings_provider=EmbeddingsProviderName.OLLAMA)


def test_fault_injection_only_active_in_dev() -> None:
    assert make(enable_fault_injection=True, app_env=AppEnv.DEV).fault_injection_active is True
    assert make(enable_fault_injection=True, app_env=AppEnv.PROD).fault_injection_active is False
    assert make(enable_fault_injection=False, app_env=AppEnv.DEV).fault_injection_active is False


def test_telemetry_disabled_without_langfuse_keys() -> None:
    assert make().telemetry_enabled is False
    assert make(langfuse_public_key="pk", langfuse_secret_key="sk").telemetry_enabled is True


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [("true", True), ("false", False), ("low", "low"), ("HIGH", "high"), (None, None)],
)
def test_ollama_think_se_normaliza(raw: str | None, esperado: object) -> None:
    # Ollama rejects the string "true": it wants the boolean or a level.
    assert make(**{**OLLAMA, "ollama_think": raw}).ollama_think == esperado


def test_ollama_think_rechaza_un_nivel_invalido() -> None:
    with pytest.raises(ValidationError, match="OLLAMA_THINK"):
        make(**{**OLLAMA, "ollama_think": "altisimo"})
