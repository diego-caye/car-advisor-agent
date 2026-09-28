from google.adk.apps.llm_event_summarizer import LlmEventSummarizer

from asesor.agent.factory import create_adk_app, create_agent
from asesor.config import Settings
from asesor.infrastructure.llm.fake import FakeAdkLlm


def test_create_adk_app_usa_el_modelo_liviano_para_compactar(settings: Settings) -> None:
    """Without an explicit `summarizer`, ADK defaults to the agent's own big
    model for summarizing (agent.canonical_model, verified by reading
    google/adk/apps/compaction.py) -- right when the conversation is already
    long, the worst moment to add another call to the main model. This test
    pins down that `create_adk_app` passes the lightweight model instead,
    not that ADK "guesses" the right one.
    """
    agent_model = FakeAdkLlm(model="agente-grande")
    summarizer_model = FakeAdkLlm(model="modelo-liviano")

    agent = create_agent(
        settings,
        lead_service=None,  # type: ignore[arg-type]
        handoff_service=None,  # type: ignore[arg-type]
        knowledge_service=None,  # type: ignore[arg-type]
        model=agent_model,
    )
    app = create_adk_app(settings, agent, summarizer_model)

    config = app.events_compaction_config
    assert config is not None
    assert isinstance(config.summarizer, LlmEventSummarizer)
    assert config.summarizer._llm is summarizer_model
    assert config.summarizer._llm is not agent_model
    assert config.token_threshold == settings.memory_compaction_token_threshold
    assert config.event_retention_size == settings.memory_compaction_keep_recent
