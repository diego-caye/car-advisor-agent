from uuid import UUID

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.apps._configs import ResumabilityConfig
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models.base_llm import BaseLlm
from google.adk.plugins.base_plugin import BasePlugin

from asesor.agent.guardrails.faults import FaultInjectionPlugin
from asesor.agent.guardrails.plugin import GuardrailPlugin
from asesor.agent.instruction import render_instruction
from asesor.agent.state import read_dialog_state
from asesor.agent.tools.handoff_tools import make_request_human_handoff
from asesor.agent.tools.knowledge_tools import make_search_knowledge_base
from asesor.agent.tools.lead_tools import make_save_lead
from asesor.application.handoff_service import HandoffService
from asesor.application.knowledge_service import KnowledgeService
from asesor.application.lead_service import LeadService
from asesor.config import Settings

APP_NAME = "asesor"
AGENT_NAME = "luis"


def create_agent(
    settings: Settings,
    lead_service: LeadService,
    handoff_service: HandoffService,
    knowledge_service: KnowledgeService,
    model: str | BaseLlm | None = None,
) -> Agent:
    async def instruction_provider(ctx: ReadonlyContext) -> str:
        dialog = read_dialog_state(ctx.state)
        snapshot = await lead_service.get_snapshot(UUID(ctx.user_id), dialog.stage)
        return render_instruction(snapshot, dialog, settings.guardrail_canary_token)

    return Agent(
        name=AGENT_NAME,
        model=model or settings.agent_model,
        description="Asesor automotriz virtual que orienta sin presionar.",
        instruction=instruction_provider,
        tools=[
            make_save_lead(lead_service),
            make_request_human_handoff(handoff_service),
            make_search_knowledge_base(knowledge_service),
        ],
    )


def create_plugins(settings: Settings) -> list[BasePlugin]:
    plugins: list[BasePlugin] = [
        GuardrailPlugin(settings.guardrail_canary_token, settings.max_tool_calls_per_turn)
    ]
    if settings.fault_injection_active:
        plugins.append(FaultInjectionPlugin())
    return plugins


def create_adk_app(settings: Settings, agent: Agent, summarizer_model: BaseLlm) -> App:
    return App(
        name=APP_NAME,
        root_agent=agent,
        plugins=create_plugins(settings),
        events_compaction_config=EventsCompactionConfig(
            # Without `summarizer`, ADK defaults to the agent's own model
            # (agent.canonical_model) for summarizing -- the big model, in
            # the same synchronous call that closes the turn (compaction.py,
            # verified by reading the source). The lightweight model (the
            # same one that titles conversations) is passed here on purpose:
            # summarizing isn't a task for the main model, and with a local
            # model already at its token limit in heavy turns (ADR-003
            # finding #9), adding another call to the big model right when
            # the conversation is already long would be the worst possible
            # moment to slow it down.
            summarizer=LlmEventSummarizer(llm=summarizer_model),
            token_threshold=settings.memory_compaction_token_threshold,
            event_retention_size=settings.memory_compaction_keep_recent,
        ),
        # Necessary so that tool confirmation can pause and resume the turn
        # (F3 spike, ADR-002).
        resumability_config=ResumabilityConfig(is_resumable=True),
    )
