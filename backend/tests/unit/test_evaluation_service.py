import json
from typing import Any

import pytest

from asesor.application.evaluation_service import EvaluationService
from asesor.config import Settings
from asesor.infrastructure.llm.fake import FakeAdkLlm, FakeTurn


class _FakeEvaluationRepo:
    """The same contract as SqlEvaluationRepository, in memory: these tests
    are about evaluate_turn's logic (which criteria run, how failures are
    discarded), not about SQL.
    """

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def add(
        self, *, session_id: str, message_id: str, criterio: str, score: float, justificacion: str
    ) -> None:
        self.rows.append(
            {
                "session_id": session_id,
                "message_id": message_id,
                "criterio": criterio,
                "score": score,
                "justificacion": justificacion,
            }
        )


def _judge_json(veredictos: list[dict[str, Any]]) -> str:
    return json.dumps({"veredictos": veredictos})


async def test_evaluate_turn_guarda_un_criterio_por_veredicto(settings: Settings) -> None:
    veredictos = [
        {"criterio": "tono_empatico", "cumple": True, "justificacion": "saluda bien"},
        {"criterio": "brevedad", "cumple": False, "justificacion": "muy largo"},
        {"criterio": "una_sola_pregunta", "cumple": True, "justificacion": "una sola"},
        {"criterio": "sin_precios", "cumple": True, "justificacion": "no menciona precios"},
    ]
    model = FakeAdkLlm(turns=[FakeTurn(text=_judge_json(veredictos))])
    repo = _FakeEvaluationRepo()
    service = EvaluationService(model, repo, settings)  # type: ignore[arg-type]

    await service.evaluate_turn(
        session_id="s1",
        message_id="m1",
        trace_id="t1",
        user_message="hola",
        agent_reply="Hola, soy Luis",
        used_rag=False,
    )

    assert {row["criterio"]: row["score"] for row in repo.rows} == {
        "tono_empatico": 1.0,
        "brevedad": 0.0,
        "una_sola_pregunta": 1.0,
        "sin_precios": 1.0,
    }
    assert repo.rows[0]["session_id"] == "s1"
    assert repo.rows[0]["message_id"] == "m1"


async def test_evaluate_turn_incluye_fidelidad_rag_solo_si_used_rag(settings: Settings) -> None:
    # The judge "hallucinates" all 5 possible criteria in both runs; what's
    # being tested is that evaluate_turn discards fidelidad_rag when the
    # turn didn't query the KB, not that the prompt asks the judge differently.
    veredictos = [
        {"criterio": "tono_empatico", "cumple": True, "justificacion": "-"},
        {"criterio": "brevedad", "cumple": True, "justificacion": "-"},
        {"criterio": "una_sola_pregunta", "cumple": True, "justificacion": "-"},
        {"criterio": "sin_precios", "cumple": True, "justificacion": "-"},
        {"criterio": "fidelidad_rag", "cumple": True, "justificacion": "-"},
    ]

    model_sin_rag = FakeAdkLlm(turns=[FakeTurn(text=_judge_json(veredictos))])
    repo_sin_rag = _FakeEvaluationRepo()
    await EvaluationService(model_sin_rag, repo_sin_rag, settings).evaluate_turn(  # type: ignore[arg-type]
        session_id="s1",
        message_id="m1",
        trace_id="t1",
        user_message="hola",
        agent_reply="Hola",
        used_rag=False,
    )
    assert "fidelidad_rag" not in {row["criterio"] for row in repo_sin_rag.rows}

    model_con_rag = FakeAdkLlm(turns=[FakeTurn(text=_judge_json(veredictos))])
    repo_con_rag = _FakeEvaluationRepo()
    await EvaluationService(model_con_rag, repo_con_rag, settings).evaluate_turn(  # type: ignore[arg-type]
        session_id="s1",
        message_id="m1",
        trace_id="t1",
        user_message="diferencia entre SUV y crossover",
        agent_reply="Un SUV suele ser más grande...",
        used_rag=True,
    )
    assert "fidelidad_rag" in {row["criterio"] for row in repo_con_rag.rows}


async def test_evaluate_turn_ignora_un_criterio_que_el_juez_inventa(settings: Settings) -> None:
    veredictos = [
        {"criterio": "tono_empatico", "cumple": True, "justificacion": "-"},
        {"criterio": "criterio_que_no_existe", "cumple": False, "justificacion": "-"},
    ]
    model = FakeAdkLlm(turns=[FakeTurn(text=_judge_json(veredictos))])
    repo = _FakeEvaluationRepo()
    service = EvaluationService(model, repo, settings)  # type: ignore[arg-type]

    await service.evaluate_turn(
        session_id="s1",
        message_id="m1",
        trace_id="t1",
        user_message="hola",
        agent_reply="Hola",
        used_rag=False,
    )

    assert len(repo.rows) == 1
    assert repo.rows[0]["criterio"] == "tono_empatico"


@pytest.mark.parametrize("texto_del_juez", ["esto no es json", "{}", '{"veredictos": "no-lista"}'])
async def test_evaluate_turn_nunca_lanza_si_el_juez_no_devuelve_json_valido(
    settings: Settings, texto_del_juez: str
) -> None:
    model = FakeAdkLlm(turns=[FakeTurn(text=texto_del_juez)])
    repo = _FakeEvaluationRepo()
    service = EvaluationService(model, repo, settings)  # type: ignore[arg-type]

    await service.evaluate_turn(
        session_id="s1",
        message_id="m1",
        trace_id="t1",
        user_message="hola",
        agent_reply="Hola",
        used_rag=False,
    )

    assert repo.rows == []
