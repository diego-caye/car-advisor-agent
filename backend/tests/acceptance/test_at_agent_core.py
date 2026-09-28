"""AT-01, AT-02, AT-03, AT-05, and AT-19 from specs/09-acceptance-tests.md."""

import asyncio
from uuid import UUID, uuid4

from httpx import AsyncClient

from asesor.agent.instruction import CANNED_SALUDO_SIN_NOMBRE, CANNED_SOLO_MIRANDO
from asesor.infrastructure.llm.fake import FakeAdkLlm, FakeTurn
from tests.support.sse import reply_text, send_message, tool_names


async def new_session(client: AsyncClient, user_id: UUID) -> str:
    response = await client.post("/api/v1/sessions", headers={"X-User-Id": str(user_id)})
    response.raise_for_status()
    session_id: str = response.json()["session_id"]
    return session_id


async def test_at01_saludo_sin_nombre(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.turns = [FakeTurn(text=CANNED_SALUDO_SIN_NOMBRE)]
    session_id = await new_session(client, user_id)

    events = await send_message(client, user_id, session_id, "hola")

    assert reply_text(events) == CANNED_SALUDO_SIN_NOMBRE
    assert tool_names(events) == []

    lead = await client.get(
        f"/api/v1/sessions/{session_id}/lead", headers={"X-User-Id": str(user_id)}
    )
    assert lead.json()["etapa"] == "NUEVO"
    assert lead.json()["lead"]["nombre"] is None

    instruction = fake_llm.instructions[0]
    assert "Nombre conocido: ninguno" in instruction
    assert "Etapa del diálogo: NUEVO" in instruction


async def test_at02_usuario_que_vuelve_es_saludado_por_nombre(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.turns = [
        FakeTurn(tool_name="guardar_lead", tool_args={"nombre": "Diego"}),
        FakeTurn(text="¡Un gusto, Diego!"),
    ]
    first_session = await new_session(client, user_id)
    await send_message(client, user_id, first_session, "me llamo Diego")

    second_session = await new_session(client, user_id)
    fake_llm.turns = [FakeTurn(text="¡Hola Diego! 👋 ¿En qué te ayudo hoy?")]
    await send_message(client, user_id, second_session, "hola de nuevo")

    instruction = fake_llm.instructions[-1]
    assert "Nombre conocido: Diego" in instruction
    assert "Etapa del diálogo: DESCUBRIMIENTO" in instruction

    lead = await client.get(
        f"/api/v1/sessions/{second_session}/lead", headers={"X-User-Id": str(user_id)}
    )
    assert lead.json()["lead"]["nombre"] == "Diego"


async def test_at03_no_repregunta_datos_que_ya_estan_en_la_ficha(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.turns = [
        FakeTurn(
            tool_name="guardar_lead",
            tool_args={"nombre": "Diego", "uso_principal": "FAMILIA"},
        ),
        FakeTurn(text="Anotado, Diego."),
        FakeTurn(text="Claro, te cuento."),
    ]
    session_id = await new_session(client, user_id)

    first = await send_message(client, user_id, session_id, "soy Diego, lo quiero para la familia")
    assert tool_names(first) == ["guardar_lead"]

    lead_events = [e for e in first if e.event == "lead.updated"]
    assert lead_events[0].data["lead"]["uso_principal"] == "FAMILIA"
    assert lead_events[0].data["etapa"] == "DESCUBRIMIENTO"

    await send_message(client, user_id, session_id, "y qué tal los híbridos")

    instruction = fake_llm.instructions[-1]
    assert '"uso_principal": "FAMILIA"' in instruction
    assert '"nombre": "Diego"' in instruction
    assert "Nunca vuelvas a preguntar un dato que ya aparece en la ficha" in instruction


async def test_at05_solo_estoy_mirando_activa_el_modo_y_persiste(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.turns = [
        FakeTurn(tool_name="guardar_lead", tool_args={"solo_mirando": True}),
        FakeTurn(text=CANNED_SOLO_MIRANDO),
    ]
    session_id = await new_session(client, user_id)

    events = await send_message(client, user_id, session_id, "por ahora solo estoy mirando")

    assert tool_names(events) == ["guardar_lead"]
    assert reply_text(events) == CANNED_SOLO_MIRANDO
    assert not any(e.event == "error" for e in events)

    lead = await client.get(
        f"/api/v1/sessions/{session_id}/lead", headers={"X-User-Id": str(user_id)}
    )
    assert lead.json()["solo_mirando"] is True
    # It didn't send any lead data: the record is still empty, only the intent changed.
    assert lead.json()["lead"]["nombre"] is None

    fake_llm.turns = [FakeTurn(text="Claro, aquí estoy si tienes dudas.")]
    await send_message(client, user_id, session_id, "ok")

    assert 'Modo "solo mirando" activo: sí' in fake_llm.instructions[-1]


async def test_at19_dos_sesiones_concurrentes_sin_fuga(
    client: AsyncClient, fake_llm: FakeAdkLlm
) -> None:
    ana, beto = uuid4(), uuid4()
    fake_llm.rules = {
        "soy Ana": [
            FakeTurn(tool_name="guardar_lead", tool_args={"nombre": "Ana"}),
            FakeTurn(text="Un gusto, Ana."),
        ],
        "soy Beto": [
            FakeTurn(tool_name="guardar_lead", tool_args={"nombre": "Beto"}),
            FakeTurn(text="Un gusto, Beto."),
        ],
    }

    ana_session, beto_session = await asyncio.gather(
        new_session(client, ana), new_session(client, beto)
    )

    await asyncio.gather(
        send_message(client, ana, ana_session, "soy Ana"),
        send_message(client, beto, beto_session, "soy Beto"),
    )

    ana_lead, beto_lead = await asyncio.gather(
        client.get(f"/api/v1/sessions/{ana_session}/lead", headers={"X-User-Id": str(ana)}),
        client.get(f"/api/v1/sessions/{beto_session}/lead", headers={"X-User-Id": str(beto)}),
    )

    assert ana_lead.json()["lead"]["nombre"] == "Ana"
    assert beto_lead.json()["lead"]["nombre"] == "Beto"

    ana_msgs, beto_msgs = await asyncio.gather(
        client.get(f"/api/v1/sessions/{ana_session}/messages", headers={"X-User-Id": str(ana)}),
        client.get(f"/api/v1/sessions/{beto_session}/messages", headers={"X-User-Id": str(beto)}),
    )
    ana_transcript = " ".join(m["content"] for m in ana_msgs.json())
    beto_transcript = " ".join(m["content"] for m in beto_msgs.json())

    assert "Ana" in ana_transcript and "Beto" not in ana_transcript
    assert "Beto" in beto_transcript and "Ana" not in beto_transcript


async def test_at19_una_sesion_ajena_no_es_accesible(client: AsyncClient) -> None:
    owner, intruder = uuid4(), uuid4()
    session_id = await new_session(client, owner)

    response = await client.get(
        f"/api/v1/sessions/{session_id}/messages", headers={"X-User-Id": str(intruder)}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_borrar_una_conversacion(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.rules = {"hola": [FakeTurn(text="¡Hola!")]}
    session_id = await new_session(client, user_id)
    await send_message(client, user_id, session_id, "hola")

    headers = {"X-User-Id": str(user_id)}
    assert (
        await client.delete(f"/api/v1/sessions/{session_id}", headers=headers)
    ).status_code == 204

    listed = await client.get("/api/v1/sessions", headers=headers)
    assert [s["session_id"] for s in listed.json()] == []

    gone = await client.get(f"/api/v1/sessions/{session_id}/messages", headers=headers)
    assert gone.status_code == 404


async def test_no_se_puede_borrar_una_conversacion_ajena(client: AsyncClient) -> None:
    owner, intruder = uuid4(), uuid4()
    session_id = await new_session(client, owner)

    response = await client.delete(
        f"/api/v1/sessions/{session_id}", headers={"X-User-Id": str(intruder)}
    )

    assert response.status_code == 404
    # It still exists for its owner.
    still = await client.get(
        f"/api/v1/sessions/{session_id}/messages", headers={"X-User-Id": str(owner)}
    )
    assert still.status_code == 200
