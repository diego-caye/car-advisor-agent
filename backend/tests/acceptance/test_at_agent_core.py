"""AT-01, AT-02, AT-03, AT-05 y AT-19 de specs/09-acceptance-tests.md."""

import asyncio
from uuid import UUID, uuid4

from httpx import AsyncClient

from asesor.agent.instruction import CANNED_GREETING_NO_NAME, CANNED_JUST_BROWSING
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
    fake_llm.turns = [FakeTurn(text=CANNED_GREETING_NO_NAME)]
    session_id = await new_session(client, user_id)

    events = await send_message(client, user_id, session_id, "hola")

    assert reply_text(events) == CANNED_GREETING_NO_NAME
    assert tool_names(events) == []

    lead = await client.get(
        f"/api/v1/sessions/{session_id}/lead", headers={"X-User-Id": str(user_id)}
    )
    assert lead.json()["stage"] == "NEW"
    assert lead.json()["lead"]["name"] is None

    instruction = fake_llm.instructions[0]
    assert "Known name: none" in instruction
    assert "Dialog stage: NEW" in instruction


async def test_at02_usuario_que_vuelve_es_saludado_por_nombre(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.turns = [
        FakeTurn(tool_name="save_lead", tool_args={"name": "Diego"}),
        FakeTurn(text="¡Un gusto, Diego!"),
    ]
    first_session = await new_session(client, user_id)
    await send_message(client, user_id, first_session, "me llamo Diego")

    second_session = await new_session(client, user_id)
    fake_llm.turns = [FakeTurn(text="¡Hola Diego! 👋 ¿En qué te ayudo hoy?")]
    await send_message(client, user_id, second_session, "hola de nuevo")

    instruction = fake_llm.instructions[-1]
    assert "Known name: Diego" in instruction
    assert "Dialog stage: DISCOVERY" in instruction

    lead = await client.get(
        f"/api/v1/sessions/{second_session}/lead", headers={"X-User-Id": str(user_id)}
    )
    assert lead.json()["lead"]["name"] == "Diego"


async def test_at03_no_repregunta_datos_que_ya_estan_en_la_ficha(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.turns = [
        FakeTurn(
            tool_name="save_lead",
            tool_args={"name": "Diego", "primary_use": "FAMILY"},
        ),
        FakeTurn(text="Anotado, Diego."),
        FakeTurn(text="Claro, te cuento."),
    ]
    session_id = await new_session(client, user_id)

    first = await send_message(client, user_id, session_id, "soy Diego, lo quiero para la familia")
    assert tool_names(first) == ["save_lead"]

    lead_events = [e for e in first if e.event == "lead.updated"]
    assert lead_events[0].data["lead"]["primary_use"] == "FAMILY"
    assert lead_events[0].data["stage"] == "DISCOVERY"

    await send_message(client, user_id, session_id, "y qué tal los híbridos")

    instruction = fake_llm.instructions[-1]
    assert '"primary_use": "FAMILY"' in instruction
    assert '"name": "Diego"' in instruction
    assert "Never ask again for a piece of data that's already in the lead" in instruction


async def test_at05_solo_estoy_mirando_activa_el_modo_y_persiste(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.turns = [
        FakeTurn(tool_name="save_lead", tool_args={"just_browsing": True}),
        FakeTurn(text=CANNED_JUST_BROWSING),
    ]
    session_id = await new_session(client, user_id)

    events = await send_message(client, user_id, session_id, "por ahora solo estoy mirando")

    assert tool_names(events) == ["save_lead"]
    assert reply_text(events) == CANNED_JUST_BROWSING
    assert not any(e.event == "error" for e in events)

    lead = await client.get(
        f"/api/v1/sessions/{session_id}/lead", headers={"X-User-Id": str(user_id)}
    )
    assert lead.json()["just_browsing"] is True
    # No mandó ningún dato del lead: la ficha sigue vacía, solo cambió la intención.
    assert lead.json()["lead"]["name"] is None

    fake_llm.turns = [FakeTurn(text="Claro, aquí estoy si tienes dudas.")]
    await send_message(client, user_id, session_id, "ok")

    assert '"Just browsing" mode active: yes' in fake_llm.instructions[-1]


async def test_at19_dos_sesiones_concurrentes_sin_fuga(
    client: AsyncClient, fake_llm: FakeAdkLlm
) -> None:
    ana, beto = uuid4(), uuid4()
    fake_llm.rules = {
        "soy Ana": [
            FakeTurn(tool_name="save_lead", tool_args={"name": "Ana"}),
            FakeTurn(text="Un gusto, Ana."),
        ],
        "soy Beto": [
            FakeTurn(tool_name="save_lead", tool_args={"name": "Beto"}),
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

    assert ana_lead.json()["lead"]["name"] == "Ana"
    assert beto_lead.json()["lead"]["name"] == "Beto"

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
    # Sigue existiendo para su dueño.
    still = await client.get(
        f"/api/v1/sessions/{session_id}/messages", headers={"X-User-Id": str(owner)}
    )
    assert still.status_code == 200
