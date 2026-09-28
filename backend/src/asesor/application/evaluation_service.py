import json
import logging
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from asesor.config import Settings
from asesor.infrastructure.db.evaluation_repository import SqlEvaluationRepository
from asesor.infrastructure.telemetry import send_langfuse_score

logger = logging.getLogger(__name__)

# The first 4 criteria from spec 08 S5 always run; fidelidad_rag is added
# only if the turn queried the knowledge base (it doesn't make sense to
# evaluate it on a response that never uses the KB).
_BASE_CRITERIA: dict[str, str] = {
    "tono_empatico": (
        "El tono es cordial y empatico, en espanol, tuteando -- coherente con "
        "un asesor automotriz llamado Luis (no un vendedor agresivo)."
    ),
    "brevedad": "La respuesta tiene entre 2 y 3 oraciones, sin listas ni markdown pesado.",
    "una_sola_pregunta": (
        "La respuesta hace como maximo una pregunta de seguimiento, no varias a la vez."
    ),
    "sin_precios": (
        "La respuesta no menciona ningun precio, cotizacion, stock ni cifra de financiamiento."
    ),
}

_RAG_CRITERION_NAME = "fidelidad_rag"
_RAG_CRITERION_TEXT = (
    "El agente consulto la base de conocimiento para responder. La respuesta es consistente "
    "con una consulta tecnica real sobre autos y no inventa cifras ni datos tecnicos "
    "especificos (potencia, precio, capacidad) que no vendrian de una fuente consultada."
)

_JUDGE_PROMPT = """Eres un evaluador de calidad de Luis, un asesor automotriz virtual.

Un cliente le envio este mensaje:
{message}

Luis respondio:
{reply}

Evalua la respuesta contra cada uno de los siguientes criterios, basandote
unicamente en el texto de la respuesta.

Criterios:
{criteria}

Responde EXCLUSIVAMENTE un JSON con esta forma exacta, sin texto alrededor ni
bloques de codigo:
{{"veredictos": [
  {{"criterio": "<nombre exacto del criterio, tal cual aparece arriba>",
    "cumple": true o false, "justificacion": "<una frase corta>"}}
]}}"""


class EvaluationService:
    """Post-execution evaluation in the background (spec 08 S5).

    Runs after the response has already been sent to the user (scheduled
    from the router once the final text is known) and must never break
    anything: a judge failure, malformed JSON, or Langfuse being down are
    logged and discarded, never propagated.
    """

    def __init__(
        self, model: BaseLlm, evaluations: SqlEvaluationRepository, settings: Settings
    ) -> None:
        self._model = model
        self._evaluations = evaluations
        self._settings = settings

    async def evaluate_turn(
        self,
        *,
        session_id: str,
        message_id: str,
        trace_id: str,
        user_message: str,
        agent_reply: str,
        used_rag: bool,
    ) -> None:
        criteria = dict(_BASE_CRITERIA)
        if used_rag:
            criteria[_RAG_CRITERION_NAME] = _RAG_CRITERION_TEXT

        try:
            verdicts = await self._judge(user_message, agent_reply, criteria)
        except Exception:
            logger.warning(
                "post-turn evaluation failed, discarding",
                exc_info=True,
                extra={"trace_id": trace_id},
            )
            return

        for verdict in verdicts:
            criterio = verdict.get("criterio")
            if criterio not in criteria:
                continue  # the judge made up or repeated a name; ignored

            score = 1.0 if verdict.get("cumple") else 0.0
            justificacion = str(verdict.get("justificacion") or "")

            await self._evaluations.add(
                session_id=session_id,
                message_id=message_id,
                criterio=criterio,
                score=score,
                justificacion=justificacion,
            )
            await send_langfuse_score(
                self._settings,
                trace_id=trace_id,
                name=f"quality.{criterio}",
                value=score,
                comment=justificacion or None,
            )

    async def _judge(
        self, message: str, reply: str, criteria: dict[str, str]
    ) -> list[dict[str, Any]]:
        criteria_text = "\n".join(f"- {name}: {text}" for name, text in criteria.items())
        prompt = _JUDGE_PROMPT.format(message=message, reply=reply, criteria=criteria_text)
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
        request = LlmRequest(model=self._model.model, contents=[content])

        chunks: list[str] = []
        async for response in self._model.generate_content_async(request, False):
            if response.partial or response.content is None or not response.content.parts:
                continue
            chunks.extend(part.text for part in response.content.parts if part.text)

        raw = "".join(chunks)
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"the judge didn't return JSON: {raw!r}")

        parsed: dict[str, Any] = json.loads(raw[start : end + 1])
        verdicts = parsed.get("veredictos")
        if not isinstance(verdicts, list):
            raise ValueError(f"the judge didn't return a list of verdicts: {parsed!r}")
        return verdicts
