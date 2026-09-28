from typing import cast

import pytest
from google.adk.runners import Runner

from asesor.config import AppEnv, ModelChoice, Settings, UnknownModelError
from asesor.infrastructure.container import RunnerRegistry, build_catalog
from asesor.infrastructure.llm.ollama_discovery import OllamaModelInfo

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


def _fake_build(choice: ModelChoice) -> Runner:
    """No building a real ADK Runner here: only which id RunnerRegistry asked
    for matters, not what it returns. The cast is explicit, not a blind
    `# type: ignore`."""
    return cast(Runner, object())


def test_los_modelos_de_ollama_no_se_declaran_a_mano_se_descubren() -> None:
    """MODEL_CHOICES doesn't need to (and shouldn't) list Ollama models:
    build_catalog takes them from what discover_ollama_models reported, not
    from static configuration — so the selector never gets out of sync with
    what's actually installed.
    """
    settings = make()
    discovered = [
        OllamaModelInfo(name="gemma4:latest", supports_tools=True, supports_thinking=True),
        OllamaModelInfo(name="qwen3:4b-instruct", supports_tools=True, supports_thinking=False),
    ]

    catalog = build_catalog(settings, discovered)

    assert {c.id for c in catalog} == {"gemma4:latest", "qwen3:4b-instruct"}
    qwen = next(c for c in catalog if c.id == "qwen3:4b-instruct")
    assert qwen.model == "ollama_chat/qwen3:4b-instruct"
    assert qwen.supports_thinking is False


def test_los_modelos_de_solo_embeddings_no_deberian_llegar_aqui() -> None:
    """discover_ollama_models already filters them out; build_catalog
    doesn't check again, so this documents the contract: whatever arrives,
    gets in.
    """
    settings = make()
    discovered = [
        OllamaModelInfo(name="embeddinggemma:300m", supports_tools=False, supports_thinking=False)
    ]

    catalog = build_catalog(settings, discovered)

    assert len(catalog) == 1
    assert catalog[0].id == "embeddinggemma:300m"


def test_las_entradas_estaticas_no_ollama_se_conservan() -> None:
    settings = make(
        model_choices=[
            ModelChoice(
                id="gemini", label="Gemini 3.8 Flash", provider="gemini", model="gemini-3.8-flash"
            )
        ]
    )

    catalog = build_catalog(settings, [])

    assert [c.id for c in catalog] == ["gemini"]


def test_una_entrada_ollama_en_model_choices_se_ignora() -> None:
    """Ollama is dynamic or it isn't: an Ollama entry declared by hand in
    MODEL_CHOICES is discarded, so it doesn't compete on id with what's
    discovered.
    """
    settings = make(
        model_choices=[
            ModelChoice(id="viejo", label="viejo", provider="ollama", model="ollama_chat/viejo")
        ]
    )
    discovered = [
        OllamaModelInfo(name="gemma4:latest", supports_tools=True, supports_thinking=True)
    ]

    catalog = build_catalog(settings, discovered)

    assert [c.id for c in catalog] == ["gemma4:latest"]


def test_sin_nada_configurado_cae_al_agent_model() -> None:
    settings = make()

    catalog = build_catalog(settings, [])

    assert len(catalog) == 1
    assert catalog[0].model == settings.agent_model


def test_el_default_es_el_agent_model_no_el_primero_de_la_lista() -> None:
    settings = make(agent_model="ollama_chat/qwen3:4b")
    discovered = [
        OllamaModelInfo(name="gemma4:latest", supports_tools=True, supports_thinking=True),
        OllamaModelInfo(name="qwen3:4b", supports_tools=True, supports_thinking=True),
    ]
    catalog = build_catalog(settings, discovered)

    registry = RunnerRegistry(_fake_build, settings, catalog)

    assert registry.default_id == "qwen3:4b"
    assert registry.choice(None).id == "qwen3:4b"


def test_choice_desconocida_lanza_unknown_model_error() -> None:
    settings = make()
    catalog = build_catalog(settings, [])
    registry = RunnerRegistry(_fake_build, settings, catalog)

    with pytest.raises(UnknownModelError):
        registry.choice("no-existe")


def test_get_reusa_el_runner_ya_construido_para_el_mismo_modelo() -> None:
    settings = make()
    discovered = [
        OllamaModelInfo(name="gemma4:latest", supports_tools=True, supports_thinking=True)
    ]
    catalog = build_catalog(settings, discovered)

    calls: list[str] = []

    def build(choice: ModelChoice) -> Runner:
        calls.append(choice.id)
        return _fake_build(choice)

    registry = RunnerRegistry(build, settings, catalog)

    first = registry.get("gemma4:latest")
    second = registry.get("gemma4:latest")

    assert first is second
    assert calls == ["gemma4:latest"]
