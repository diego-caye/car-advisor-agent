# Notes · Verified ADK 2.x API

Verified by introspecting the installed package on 2026-09-15. **Version: `google-adk==2.9.1`** (pinned exactly in `backend/pyproject.toml`). Don't write ADK from memory: if the version is bumped, re-verify this table.

## 1. Agent

```python
from google.adk.agents import Agent  # Agent is LlmAgent
```

| Field | Verified type |
|---|---|
| `instruction` | `str \| Callable[[ReadonlyContext], str \| Awaitable[str]]` |
| `global_instruction` | same as `instruction` |
| `model` | `str \| BaseLlm` |
| `tools` | `list[Callable \| BaseTool \| BaseToolset]` |
| `generate_content_config` | `genai_types.GenerateContentConfig \| None` |

**Decision:** we use `instruction` **as a callable**, not as a string with `{state_key}` placeholders. Reason: the lead record is injected as JSON, and JSON's `{}` braces collide with ADK's placeholder templating. The callable receives `ReadonlyContext` and assembles the text (spec 05 §1).

`ReadonlyContext` exposes: `state`, `user_id`, `session`, `invocation_id`, `agent_name`, `user_content`, `run_config`.

## 2. Runner and streaming

```python
Runner(*, app=None, app_name=None, agent=None, plugins=None, session_service, ...)
Runner.run_async(*, user_id, session_id, invocation_id=None, new_message=None,
                 state_delta=None, run_config=None, yield_user_message=False)
    -> AsyncGenerator[Event, None]
```

- All parameters are **keyword-only**.
- `state_delta` lets state be injected into the turn without writing to the session beforehand — useful for passing the recalculated stage.
- We always use `run_async`, never `run` (gotcha: with `run` the OTel context doesn't reach the child spans).
- **Partial streaming:** `RunConfig(streaming_mode=StreamingMode.SSE)`. `StreamingMode` verified: `NONE`, `SSE`, `BIDI`.
- `RunConfig.max_llm_calls` exists and caps model calls per invocation (related to `MAX_TOOL_CALLS_PER_TURN`, spec 07 L3).

We build the Runner with `app=App(...)` (not `agent=`), because `App` is what accepts `plugins` and `events_compaction_config`.

## 3. Events

```python
from google.adk.events import Event
```

| Field/method | Use in our SSE (spec 02) |
|---|---|
| `event.partial: bool \| None` | `True` on text deltas → `message.delta` |
| `event.content: genai_types.Content \| None` | text in `content.parts[*].text` |
| `event.get_function_calls()` | → `tool.started` |
| `event.get_function_responses()` | → `tool.finished` |
| `event.usage_metadata` | the turn's tokens in/out → `message.completed` |
| `event.is_final_response()` | closes the turn |
| `event.turn_complete`, `event.finish_reason` | turn end / reason |
| `event.error_code`, `event.error_message` | → SSE `error` |
| `event.actions: EventActions` | see below |
| `event.invocation_id`, `event.author`, `event.id`, `event.timestamp` | correlation and traces |

`EventActions` (relevant fields): `state_delta`, `escalate`, `skip_summarization`, `transfer_to_agent`, `requested_tool_confirmations`, `compaction`.

## 4. Sessions and state

```python
from google.adk.sessions import DatabaseSessionService

DatabaseSessionService(db_url: str | None = None, db_engine: AsyncEngine | None = None, **kwargs)
```

Verified methods: `create_session(*, app_name, user_id, state=None, session_id=None) -> Session`, `get_session(*, app_name, user_id, session_id, config=None) -> Session | None`, `list_sessions(*, app_name, user_id=None) -> ListSessionsResponse`, `append_event(session, event)`, `get_user_state(*, app_name, user_id) -> dict[str, Any]`, `prepare_tables()`, `delete_session`, `close`, `flush`.

- `db_url` must be `postgresql+asyncpg://...` (spec 06 §1).
- `prepare_tables()` creates ADK's session schema: called during the app's lifespan.
- **`get_user_state`** is the supported way to read user-scoped state without opening a session: it's what makes greeting by name in a new session possible (AT-02).

### State scope prefixes (resolves the open question from spec 06 §1)

| Prefix | Scope |
|---|---|
| *(no prefix)* | that session only |
| `user:` | **persists across sessions for the same `user_id`** |
| `app:` | every user |
| `temp:` | current invocation only |

The stage and the flags go with no prefix (per session). The lead is **not** replicated under `user:`: the `leads` table is the single source of truth and the instruction provider queries it on every turn (spec 06 §1). `user:` remains available should some future flag need user-level scope.

## 5. Memory compaction (resolves the open question from spec 06 §2)

```python
from google.adk.apps import App
from google.adk.apps.app import EventsCompactionConfig

App(
    name=...,
    root_agent=...,
    plugins=[...],
    events_compaction_config=EventsCompactionConfig(
        token_threshold=...,        # MEMORY_COMPACTION_TOKEN_THRESHOLD
        event_retention_size=...,   # MEMORY_COMPACTION_KEEP_RECENT
        summarizer=None,            # optional: LlmEventSummarizer(llm=Gemini(model=...))
    ),
)
```

Verified fields of `EventsCompactionConfig`: `summarizer`, `compaction_interval`, `overlap_size`, `token_threshold`, `event_retention_size`.

## 6. Tools and HITL

```python
from google.adk.tools import ToolContext
```

`ToolContext` exposes (verified): `state`, `user_id`, `session`, `invocation_id`, `actions`, `function_call_id`, `agent_name`, **`request_confirmation`**, **`tool_confirmation`**, `search_memory`, `save_artifact`, …

- **`tool_context.user_id`** and **`tool_context.session.id`** are the source of `user_id`/`session_id` in the tools: never LLM parameters (spec 03, baseline gap #4).
- Function-tool rules: a clear docstring (sent to the LLM), mandatory type hints, **no default values**, return a serializable `dict`, never mention `tool_context` in the docstring.
- **HITL (F3):** `tool_context.request_confirmation(...)` + `EventActions.requested_tool_confirmations` is the primary path. Still marked experimental → the F3 spike settled it, and ADR-002 documents the result.

## 7. Models

```python
from google.adk.models import Gemini   # fields: model, client, client_kwargs, base_url, api_version, ...
```

- Gemini can be passed as a `str` (the model ID) directly in `Agent(model=...)`; we use the env string (`AGENT_MODEL`).
- AI Studio: `GOOGLE_API_KEY` (also accepts `GEMINI_API_KEY`). Vertex: `GOOGLE_GENAI_USE_VERTEXAI=True` + `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION`.
- **`LiteLlm` doesn't ship in the base install:** `from google.adk.models.lite_llm import LiteLlm` fails with `ImportError: LiteLLM support requires: pip install google-adk[extensions]`. F8 (Ollama, P2) would need to add the `google-adk[extensions]` extra to `pyproject.toml`.

## 8. Plugins (F6)

```python
from google.adk.plugins.base_plugin import BasePlugin
App(name=..., root_agent=..., plugins=[MyPlugin()])
```

Plugins run **before** the agent's own callbacks and apply to every sub-agent. Keyword-based hooks (parameter names must match exactly), e.g. `async def before_model_callback(self, *, callback_context, llm_request)`. Returning `None` observes; returning a value intervenes. This is the layer where L1/L2/L4 live (spec 07).

## 9. Evaluation (F7)

```python
from google.adk.evaluation.eval_case import EvalCase, Invocation, IntermediateData
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus, ToolTrajectoryCriterion
from google.adk.evaluation.trajectory_evaluator import TrajectoryEvaluator
```

- **`google.adk.evaluation.local_eval_service.LocalEvalService`** (the "official" runner for an `EvalSet`) **is deliberately not used here.** Importing it triggers, in a chain, `metric_evaluator_registry` → `multi_turn_task_success_evaluator` → `vertex_ai_eval_facade` → `import vertexai`, which **isn't installed** (it requires the `google-adk[eval]` extra, which drags in `google-cloud-aiplatform[evaluation]`, `pandas`, `nltk`, `rouge-score`, `gepa`, `tabulate`, `openpyxl`, `xlrd`, `google-cloud-texttospeech` — heavy and Vertex-oriented, the opposite of this project's "no API key at all"). The actual error for anyone reproducing it: `ModuleNotFoundError: No module named 'vertexai'`.
- **Alternative used (`backend/tests/evalset/`):** the individual evaluators do import cleanly without that extra — `trajectory_evaluator`, `llm_as_judge`, `rubric_based_evaluator`, `final_response_match_v2` (only `response_evaluator`/`final_response_match_v1` need `rouge_score`, and those aren't used). They're orchestrated by hand against the real `Runner` via HTTP/SSE (the same pattern as the rest of the suite, `tests/support/sse.py`), without `LocalEvalService`.
- **`Invocation`** (one per turn): `user_content: Content`, `final_response: Content | None`, `intermediate_data: IntermediateData(tool_uses: list[FunctionCall], ...)`. `EvalCase.conversation: list[Invocation]`.
- **`TrajectoryEvaluator(eval_metric=EvalMetric(criterion=ToolTrajectoryCriterion(threshold, match_type, ignore_args)))`**: deterministic, no LLM involved. `ToolTrajectoryCriterion.MatchType` (nested enum) is `EXACT | IN_ORDER | ANY_ORDER`. `evaluate_invocations(actual, expected)` requires lists of equal length (one per turn) — none of this needs `LocalEvalService`.
- **Any LLM-as-judge evaluator's judge (`JudgeModelOptions.judge_model: str`) resolves exactly like an agent model does**: `LLMRegistry().resolve(model_id)` — verified live that `"ollama_chat/qwen3:4b-instruct"` resolves to `LiteLlm`, just like `AGENT_MODEL`. In other words, `EVAL_MODEL` can be Ollama with no key at all, and that's how it's used in `backend/tests/evalset/`.
- **`RubricBasedFinalResponseQualityV1Evaluator` (rubric_based_final_response_quality_v1.py) is the only fully concrete rubric class** (`RubricBasedEvaluator` itself stays abstract, missing `format_auto_rater_prompt`) — **but it was dropped after testing it live**: its internal prompt asks for "evidence" (from tools/sources) to mark a rubric as met, and it flagged the rubric "greets briefly and warmly" as unmet on a perfectly correct greeting, just because the turn hadn't called any tool — it's built for faithfulness to retrieved evidence (RAG), not for tone/policy rules on a tool-free turn. On top of that, with `num_samples=1` (ADK's default is 5, meant for a cloud-hosted judge) the same question/answer pair produced different verdicts across two runs — noise to be expected from a local 4B judge, not unique to this class, but it confirms a single sample can be unstable for edge cases.
- **Decision:** `backend/tests/evalset/` uses its own single-call judge (`LlmRequest` + `judge_model.generate_content_async`, the same low-level mechanism as `TitleService`) asking for a JSON verdict per rule in Spanish, instead of ADK's rubric classes. Less code, no "evidence required" semantics, and full control over the judge's prompt.
