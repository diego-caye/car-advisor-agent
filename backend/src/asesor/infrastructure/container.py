import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from google.adk.models import Gemini
from google.adk.models.base_llm import BaseLlm
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, DatabaseSessionService
from sqlalchemy.ext.asyncio import AsyncEngine

from asesor.agent.factory import APP_NAME, create_adk_app, create_agent
from asesor.application.evaluation_service import EvaluationService
from asesor.application.handoff_service import HandoffService
from asesor.application.knowledge_service import KnowledgeService
from asesor.application.lead_service import LeadService
from asesor.application.title_service import TitleService
from asesor.config import (
    DEFAULT_MODEL_ID,
    EmbeddingsProviderName,
    LlmProviderName,
    ModelChoice,
    Settings,
    UnknownModelError,
)
from asesor.domain.knowledge import EmbeddingsPort
from asesor.infrastructure.db.engine import create_engine, create_session_factory
from asesor.infrastructure.db.evaluation_repository import SqlEvaluationRepository
from asesor.infrastructure.db.feedback_repository import SqlFeedbackRepository
from asesor.infrastructure.db.handoff_repository import SqlHandoffRepository
from asesor.infrastructure.db.kb_repository import PgVectorRetriever
from asesor.infrastructure.db.lead_repository import SqlLeadRepository
from asesor.infrastructure.db.session_title_repository import SqlSessionTitleRepository
from asesor.infrastructure.embeddings.gemini import GeminiEmbeddings
from asesor.infrastructure.embeddings.ollama import OllamaEmbeddings
from asesor.infrastructure.llm.ollama_discovery import OllamaModelInfo, discover_ollama_models
from asesor.infrastructure.llm.resilient import ResilientLlm

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    lead_service: LeadService
    handoff_service: HandoffService
    knowledge_service: KnowledgeService
    title_service: TitleService
    session_titles: SqlSessionTitleRepository
    feedback: SqlFeedbackRepository
    evaluation_service: EvaluationService
    session_service: BaseSessionService
    runners: "RunnerRegistry"

    @property
    def runner(self) -> Runner:
        return self.runners.get(None)


def build_catalog(
    settings: Settings, discovered_ollama: Sequence[OllamaModelInfo]
) -> list[ModelChoice]:
    """The selector's actual catalog: what's declared by hand (typically Gemini,
    since the API does need a key and there's no way to "discover" it
    locally) plus whatever Ollama reports having installed right now.

    Ollama models aren't declared in MODEL_CHOICES: they're discovered at
    startup (discover_ollama_models), so the list never gets out of sync
    with what's actually *pulled* — nor does it include embeddings-only
    models, which come pre-filtered.
    """
    static = [
        choice for choice in settings.model_choices if choice.provider is not LlmProviderName.OLLAMA
    ]
    dynamic = [
        ModelChoice(
            id=info.name,
            label=info.name,
            provider=LlmProviderName.OLLAMA,
            model=f"ollama_chat/{info.name}",
            supports_tools=info.supports_tools,
            supports_thinking=info.supports_thinking,
        )
        for info in discovered_ollama
    ]
    catalog = [*static, *dynamic]

    if not catalog:
        catalog = [
            ModelChoice(
                id=DEFAULT_MODEL_ID,
                label=settings.agent_model,
                provider=settings.llm_provider,
                model=settings.agent_model,
            )
        ]

    return catalog


def _default_choice_id(catalog: Sequence[ModelChoice], settings: Settings) -> str:
    """The model configured in AGENT_MODEL, if it appears in the catalog.

    It's not simply "the first option": with the Ollama catalog built by
    discovery, the order depends on whatever the server listed, not on any
    declared intent. The only stable thing is AGENT_MODEL.
    """
    agent_model = settings.agent_model.removeprefix("ollama_chat/")
    for option in catalog:
        if option.model.removeprefix("ollama_chat/") == agent_model:
            return option.id
    return catalog[0].id if catalog else DEFAULT_MODEL_ID


class RunnerRegistry:
    """One Runner per catalog model, created the first time it's requested.

    The application services and the session service are shared: the only
    thing that changes between runners is the model the agent uses, so a
    conversation can switch models without losing its history or its lead
    record.
    """

    def __init__(
        self, build: Callable[[ModelChoice], Runner], settings: Settings, catalog: list[ModelChoice]
    ) -> None:
        self._build = build
        self._catalog = catalog
        self._default_id = _default_choice_id(catalog, settings)
        self._runners: dict[str, Runner] = {}

    @property
    def catalog(self) -> list[ModelChoice]:
        return self._catalog

    @property
    def default_id(self) -> str:
        return self._default_id

    def choice(self, model_id: str | None) -> ModelChoice:
        wanted = model_id or self._default_id
        for option in self._catalog:
            if option.id == wanted:
                return option
        raise UnknownModelError(wanted)

    def get(self, model_id: str | None) -> Runner:
        option = self.choice(model_id)
        if option.id not in self._runners:
            logger.info("creating runner for model %s (%s)", option.id, option.model)
            self._runners[option.id] = self._build(option)
        return self._runners[option.id]

    async def close(self) -> None:
        for runner in self._runners.values():
            await runner.close()
        self._runners.clear()


def build_embeddings(settings: Settings) -> EmbeddingsPort:
    if settings.embeddings_provider is EmbeddingsProviderName.GEMINI:
        return GeminiEmbeddings(
            model=settings.embeddings_model,
            api_key=settings.google_api_key,
            use_vertexai=settings.google_genai_use_vertexai,
        )

    if settings.ollama_api_base is None:
        raise ValueError("EMBEDDINGS_PROVIDER=ollama requires OLLAMA_API_BASE")

    return OllamaEmbeddings(model=settings.embeddings_model, api_base=settings.ollama_api_base)


def _ollama_kwargs(settings: Settings, *, think: bool) -> dict[str, object]:
    # num_ctx always: without it Ollama silently truncates the context.
    kwargs: dict[str, object] = {
        "api_base": settings.ollama_api_base,
        "num_ctx": settings.ollama_context_length,
    }
    # think only where it applies: sending it to a model without that
    # capability returns 400 "does not support thinking" (ADR-003).
    if think and settings.ollama_think is not None:
        kwargs["think"] = settings.ollama_think
    return kwargs


def build_base_model(settings: Settings, choice: ModelChoice) -> BaseLlm:
    if choice.provider is LlmProviderName.OLLAMA:
        # The ollama_chat/ prefix is validated by Settings for AGENT_MODEL and
        # built by build_catalog for the rest of the options. think only if
        # the option itself supports thinking (supports_thinking, discovered
        # live): sending it to a model without that capability returns 400
        # "does not support thinking" (ADR-003) — it used to always be sent.
        return LiteLlm(
            model=choice.model, **_ollama_kwargs(settings, think=choice.supports_thinking)
        )

    return Gemini(model=choice.model)


def build_fallback_model(settings: Settings, choice: ModelChoice) -> BaseLlm | None:
    if settings.fallback_model == choice.model:
        return None

    # The fallback's provider is dictated by FALLBACK_MODEL itself (its
    # ollama_chat/ prefix), not by the provider of this choice's primary
    # model: they're independent -- the catalog mixes Gemini and Ollama
    # options (spec 11), and FALLBACK_MODEL is a single, global one, used as
    # the fallback for any of them. Branching on choice.provider used to
    # build a Gemini(model="ollama_chat/...") when the chosen primary was
    # Gemini and the configured fallback was an Ollama one -- a real 404
    # against the Gemini API, seen live when selecting Gemini from the
    # selector.
    if settings.fallback_model.startswith("ollama_chat/"):
        return LiteLlm(model=settings.fallback_model, **_ollama_kwargs(settings, think=False))

    return Gemini(model=settings.fallback_model)


def build_title_model(settings: Settings, model: str | BaseLlm | None = None) -> BaseLlm:
    """Model for titling conversations: the lightweight one, not the agent's.

    It's a trivial, background task; spending the big model on it would only
    add latency and GPU load without improving the result.
    """
    if isinstance(model, BaseLlm):
        return model

    if settings.llm_provider is LlmProviderName.OLLAMA:
        return LiteLlm(model=settings.guardrail_model, **_ollama_kwargs(settings, think=False))

    return Gemini(model=settings.guardrail_model)


def build_eval_model(settings: Settings, model: str | BaseLlm | None = None) -> BaseLlm:
    """Judge for the post-turn background evaluation (spec 08 S5): EVAL_MODEL,
    not the agent's -- it's a classification task, not a conversation.
    """
    if isinstance(model, BaseLlm):
        return model

    if settings.llm_provider is LlmProviderName.OLLAMA:
        return LiteLlm(model=settings.eval_model, **_ollama_kwargs(settings, think=False))

    return Gemini(model=settings.eval_model)


def build_llm(settings: Settings, model: str | BaseLlm | None, choice: ModelChoice) -> BaseLlm:
    """Wraps the model with retries and fallback (spec 07 §3).

    Tests inject their own BaseLlm and also get wrapped, so the retry and
    fallback path is the same one that runs in production.
    """
    if isinstance(model, BaseLlm):
        # In tests the fallback is the same test double, to exercise the
        # fallback path without needing a second model.
        return ResilientLlm(model=model.model, primary=model, fallback=model)

    primary = build_base_model(settings, choice)
    return ResilientLlm(
        model=primary.model, primary=primary, fallback=build_fallback_model(settings, choice)
    )


async def build_container(
    settings: Settings,
    session_service: BaseSessionService | None = None,
    model: str | BaseLlm | None = None,
    embeddings: EmbeddingsPort | None = None,
    title_model: BaseLlm | None = None,
    eval_model: BaseLlm | None = None,
) -> Container:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    lead_service = LeadService(SqlLeadRepository(session_factory))
    handoff_service = HandoffService(SqlHandoffRepository(session_factory))
    knowledge_service = KnowledgeService(
        embeddings or build_embeddings(settings),
        PgVectorRetriever(session_factory),
        settings.rag_min_score,
    )

    sessions = session_service or DatabaseSessionService(db_url=settings.database_url)
    session_titles = SqlSessionTitleRepository(session_factory)
    # A single lightweight model for the two utility tasks that aren't the
    # conversation itself (titling, summarizing to compact): building it
    # twice would be two identical LiteLlm/Gemini instances for no reason.
    utility_model = build_title_model(settings, title_model)
    title_service = TitleService(utility_model, session_titles)
    feedback = SqlFeedbackRepository(session_factory)
    evaluation_service = EvaluationService(
        build_eval_model(settings, eval_model), SqlEvaluationRepository(session_factory), settings
    )

    # Async and only if OLLAMA_API_BASE is set: it's not configured in tests
    # (they use Gemini + a fake BaseLlm), so this doesn't hit the network for
    # them. If Ollama is down or slow to start, discover_ollama_models
    # already returns [] instead of taking down the backend's startup.
    discovered = (
        await discover_ollama_models(settings.ollama_api_base) if settings.ollama_api_base else []
    )
    catalog = build_catalog(settings, discovered)

    def build_runner(choice: ModelChoice) -> Runner:
        agent = create_agent(
            settings,
            lead_service,
            handoff_service,
            knowledge_service,
            build_llm(settings, model, choice),
        )
        return Runner(app=create_adk_app(settings, agent, utility_model), session_service=sessions)

    return Container(
        settings=settings,
        engine=engine,
        lead_service=lead_service,
        handoff_service=handoff_service,
        knowledge_service=knowledge_service,
        title_service=title_service,
        session_titles=session_titles,
        feedback=feedback,
        evaluation_service=evaluation_service,
        session_service=sessions,
        runners=RunnerRegistry(build_runner, settings, catalog),
    )


async def close_container(container: Container) -> None:
    await container.runners.close()
    await container.engine.dispose()


__all__ = ["APP_NAME", "Container", "build_container", "build_embeddings", "close_container"]
