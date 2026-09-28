"""AT-06 y AT-07 de specs/09-acceptance-tests.md."""

from uuid import UUID

from fastapi import FastAPI
from httpx import AsyncClient

from asesor.agent.instruction import CANNED_NO_KB_DATA
from asesor.infrastructure.container import Container
from asesor.infrastructure.db.engine import SessionFactory
from asesor.infrastructure.embeddings.fake import FakeEmbeddings
from asesor.infrastructure.llm.fake import FakeAdkLlm, FakeTurn
from tests.support.kb import seed_kb
from tests.support.sse import ReceivedEvent, reply_text, send_message, tool_names

CARROCERIAS = ["carrocerias-suv.md", "carrocerias-crossover.md"]


async def new_session(client: AsyncClient, user_id: UUID) -> str:
    response = await client.post("/api/v1/sessions", headers={"X-User-Id": str(user_id)})
    response.raise_for_status()
    session_id: str = response.json()["session_id"]
    return session_id


def tool_results(events: list[ReceivedEvent], name: str) -> list[ReceivedEvent]:
    return [e for e in events if e.event == "tool.finished" and e.data["name"] == name]


async def test_at06_pregunta_tecnica_consulta_la_kb(
    client: AsyncClient,
    fake_llm: FakeAdkLlm,
    fake_embeddings: FakeEmbeddings,
    session_factory: SessionFactory,
    user_id: UUID,
) -> None:
    await seed_kb(session_factory, fake_embeddings, CARROCERIAS)

    fake_llm.rules = {
        "crossover": [
            FakeTurn(
                tool_name="search_knowledge_base",
                tool_args={"query": "diferencia entre SUV y crossover monocasco chasis"},
            ),
            FakeTurn(text="La diferencia está en la plataforma: monocasco contra chasis."),
        ]
    }
    session_id = await new_session(client, user_id)

    events = await send_message(
        client, user_id, session_id, "¿cuál es la diferencia entre una SUV y un crossover?"
    )

    assert tool_names(events) == ["search_knowledge_base"]
    finished = tool_results(events, "search_knowledge_base")
    assert finished[0].data["status"] == "ok"
    assert "plataforma" in reply_text(events)


async def test_at06_los_resultados_llevan_titulo_fuente_y_score(
    app: FastAPI,
    fake_embeddings: FakeEmbeddings,
    session_factory: SessionFactory,
) -> None:
    await seed_kb(session_factory, fake_embeddings, CARROCERIAS)

    container: Container = app.state.container
    chunks = await container.knowledge_service.search(
        "diferencia entre SUV y crossover monocasco", category=None, top_k=4
    )

    assert chunks, "la búsqueda debería encontrar contenido de carrocerías"
    assert chunks[0].source in CARROCERIAS
    assert chunks[0].title
    assert 0.0 < chunks[0].score <= 1.0
    assert chunks == sorted(chunks, key=lambda c: c.score, reverse=True)


async def test_at07_sin_datos_en_la_kb_devuelve_no_results(
    client: AsyncClient,
    fake_llm: FakeAdkLlm,
    fake_embeddings: FakeEmbeddings,
    session_factory: SessionFactory,
    user_id: UUID,
) -> None:
    await seed_kb(session_factory, fake_embeddings, CARROCERIAS)

    fake_llm.rules = {
        "garantía del turbocompresor": [
            FakeTurn(
                tool_name="search_knowledge_base",
                tool_args={"query": "garantía específica del turbocompresor kilometraje exacto"},
            ),
            FakeTurn(text=CANNED_NO_KB_DATA),
        ]
    }
    session_id = await new_session(client, user_id)

    events = await send_message(
        client,
        user_id,
        session_id,
        "¿cuál es la garantía del turbocompresor de ese modelo en kilómetros?",
    )

    finished = tool_results(events, "search_knowledge_base")
    assert finished[0].data["status"] == "no_results"
    assert reply_text(events) == CANNED_NO_KB_DATA


async def test_at07_kb_vacia_tambien_devuelve_no_results(
    client: AsyncClient,
    fake_llm: FakeAdkLlm,
    user_id: UUID,
) -> None:
    fake_llm.rules = {
        "híbrido": [
            FakeTurn(tool_name="search_knowledge_base", tool_args={"query": "híbridos"}),
            FakeTurn(text=CANNED_NO_KB_DATA),
        ]
    }
    session_id = await new_session(client, user_id)

    events = await send_message(client, user_id, session_id, "cuéntame de los híbrido")

    finished = tool_results(events, "search_knowledge_base")
    assert finished[0].data["status"] == "no_results"
