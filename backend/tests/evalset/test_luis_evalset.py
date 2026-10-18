"""Golden dataset of conversations for Luis, run against real Ollama.

This project's equivalent of a LangSmith dataset: `luis.cases.json` is
editable by hand (adding a case doesn't touch this file), and each turn is
judged with two mechanisms:

- `TrajectoryEvaluator` (google.adk.evaluation, verified against
  google-adk==2.9.1, specs/notes/adk-api.md S8): compares the tool names
  called against the expected ones (ANY_ORDER/EXACT depending on the case).
  Deterministic, no LLM.
- A custom judge (`_judge_rubrics`), NOT ADK's
  `RubricBasedFinalResponseQualityV1Evaluator`: it was tried first
  (specs/notes/adk-api.md S8) and its internal prompt requires tool
  "evidence" to consider a rubric satisfied, which marked a simple greeting
  as unmet even when the text was correct — it's meant for faithfulness to
  retrieved evidence (RAG), not for tone/policy rules with no tools
  involved. The custom judge makes a single call to EVAL_MODEL (here Ollama,
  resolved the same way ADK's own LlmAsJudge does via LLMRegistry, with no
  key at all) asking for a JSON verdict per rule.

It's not compared against fixed text because an LLM doesn't always respond
the same way (explicit request from the human).

Outside of CI (the `evalset` marker, same as `live`): takes several minutes
because it hits a real local model turn by turn.
"""

import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from google.adk.evaluation.eval_case import IntermediateData, Invocation
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus, ToolTrajectoryCriterion
from google.adk.evaluation.trajectory_evaluator import TrajectoryEvaluator
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.genai import types as genai_types
from httpx import AsyncClient

from tests.support.sse import ReceivedEvent, reply_text, send_message, tool_names

pytestmark = pytest.mark.evalset

CASES_PATH = Path(__file__).parent / "luis.cases.json"
CASES: list[dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]

MATCH_TYPES = {
    "exact": ToolTrajectoryCriterion.MatchType.EXACT,
    "in_order": ToolTrajectoryCriterion.MatchType.IN_ORDER,
    "any_order": ToolTrajectoryCriterion.MatchType.ANY_ORDER,
}


def _invocation(message: str, reply: str, tools: list[str]) -> Invocation:
    return Invocation(
        user_content=genai_types.Content(parts=[genai_types.Part(text=message)]),
        final_response=genai_types.Content(parts=[genai_types.Part(text=reply)]),
        intermediate_data=IntermediateData(
            tool_uses=[genai_types.FunctionCall(name=name) for name in tools]
        ),
    )


def _assert_trajectory(
    turn: dict[str, Any], actual: Invocation, tools: list[str], case_id: str
) -> None:
    expected_tools = turn.get("expected_tools")
    if expected_tools is None:
        return  # this turn doesn't verify trajectory (see luis.cases.json)

    expected = _invocation(message=turn["message"], reply="", tools=list(expected_tools))
    evaluator = TrajectoryEvaluator(
        eval_metric=EvalMetric(
            metric_name="tool_trajectory_avg_score",
            criterion=ToolTrajectoryCriterion(
                threshold=1.0,
                match_type=MATCH_TYPES[turn["match_type"]],
                ignore_args=True,
            ),
        )
    )
    result = evaluator.evaluate_invocations([actual], [expected])
    assert result.overall_eval_status == EvalStatus.PASSED, (
        f"[{case_id}] trayectoria de tools no coincide: se esperaba "
        f"{expected_tools} ({turn['match_type']}), se llamaron {tools}"
    )


def _assert_forbidden_content(turn: dict[str, Any], reply: str, case_id: str) -> None:
    literal = turn.get("forbidden_literal")
    if literal:
        assert literal not in reply, (
            f"[{case_id}] la respuesta filtro el literal prohibido {literal!r}: {reply!r}"
        )

    pattern = turn.get("forbidden_pattern")
    if pattern:
        match = re.search(pattern, reply, flags=re.IGNORECASE)
        assert match is None, (
            f"[{case_id}] la respuesta matchea el patron prohibido {pattern!r} "
            f"(encontrado {match.group()!r}): {reply!r}"
        )


_JUDGE_PROMPT = """Eres un evaluador estricto de Luis, un asesor automotriz virtual.

Un cliente le envio este mensaje:
{message}

Luis respondio:
{reply}

Evalua la respuesta de Luis contra cada una de las siguientes reglas, basandote
UNICAMENTE en el texto de la respuesta. No exijas evidencia de herramientas ni
de fuentes externas para reglas de tono, brevedad o de contenido (por ejemplo,
"no menciona precios" se evalua solo leyendo el texto).

Reglas:
{reglas}

Responde EXCLUSIVAMENTE un JSON con esta forma exacta, sin texto alrededor ni
bloques de codigo:
{{"veredictos": [
  {{"regla": <numero de regla, empezando en 1>, "cumple": true o false, "motivo": "<una frase>"}}
]}}"""


def _extract_json(raw: str) -> dict[str, Any]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"la respuesta del juez no trae JSON: {raw!r}")
    parsed: dict[str, Any] = json.loads(raw[start : end + 1])
    return parsed


async def _judge_rubrics(
    judge_model: BaseLlm, message: str, reply: str, rubrics: list[str]
) -> list[dict[str, Any]]:
    reglas = "\n".join(f"{i}. {text}" for i, text in enumerate(rubrics, start=1))
    prompt = _JUDGE_PROMPT.format(message=message, reply=reply, reglas=reglas)
    content = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=prompt)])
    request = LlmRequest(model=judge_model.model, contents=[content])

    chunks: list[str] = []
    async for response in judge_model.generate_content_async(request, False):
        if response.partial or response.content is None or not response.content.parts:
            continue
        chunks.extend(part.text for part in response.content.parts if part.text)

    verdicts = _extract_json("".join(chunks))["veredictos"]
    assert isinstance(verdicts, list) and len(verdicts) == len(rubrics), (
        f"el juez devolvio {len(verdicts)} veredictos para {len(rubrics)} reglas: {verdicts}"
    )
    return verdicts


async def _assert_rubrics(
    turn: dict[str, Any], reply: str, case_id: str, judge_model: BaseLlm
) -> None:
    rubrics = turn.get("rubrics") or []
    if not rubrics:
        return

    verdicts = await _judge_rubrics(judge_model, turn["message"], reply, rubrics)
    incumplidas = [v for v in verdicts if not v.get("cumple")]
    assert not incumplidas, (
        f"[{case_id}] el juez ({judge_model.model}) marco reglas como no "
        f"cumplidas. Respuesta evaluada: {reply!r}. Reglas incumplidas: {incumplidas}"
    )


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_conversacion(
    case: dict[str, Any],
    client: AsyncClient,
    user_id: UUID,
    judge_model: BaseLlm,
) -> None:
    session_response = await client.post("/api/v1/sessions", headers={"X-User-Id": str(user_id)})
    session_response.raise_for_status()
    session_id = session_response.json()["session_id"]

    for turn in case["turns"]:
        events = await send_message(client, user_id, session_id, turn["message"])
        reply = reply_text(events)
        tools = tool_names(events)
        hitl_triggered = any(e.event == "hitl.confirmation_required" for e in events)
        error_triggered = any(e.event == "error" for e in events)

        if hitl_triggered:
            # A turn with hitl.confirmation_required closes the stream
            # without a message.delta (spec 02 S2): there's no final text to
            # judge. It's only a valid outcome if the case declared it
            # explicitly -- otherwise, an unexpected pause is itself a failure.
            assert turn.get("accepts_hitl"), (
                f"[{case['id']}] el turno disparo hitl.confirmation_required sin "
                f"esperarlo: {_hitl_payload(events)}"
            )
            continue

        if error_triggered:
            # event.error_code (e.g. MAX_TOKENS) is translated into a
            # retryable "error" SSE event (asesor/api/sse.py) instead of
            # text: it's spec 07's failure handling working, not a broken
            # turn. It's only tolerated if the case declared it explicitly.
            assert turn.get("tolerates_error"), (
                f"[{case['id']}] el turno termino en error sin esperarlo: "
                f"{[e.data for e in events if e.event == 'error']}"
            )
            print(f"[{case['id']}] note: the turn degraded to a retryable error, tolerated")
            if turn.get("expected_tools") is not None:
                _assert_trajectory(turn, _invocation(turn["message"], "", tools), tools, case["id"])
            continue

        assert reply, f"[{case['id']}] el turno no produjo ninguna respuesta de texto"

        actual = _invocation(turn["message"], reply, tools)

        _assert_forbidden_content(turn, reply, case["id"])
        _assert_trajectory(turn, actual, tools, case["id"])
        await _assert_rubrics(turn, reply, case["id"], judge_model)


def _hitl_payload(events: list[ReceivedEvent]) -> dict[str, Any] | None:
    return next((e.data for e in events if e.event == "hitl.confirmation_required"), None)
