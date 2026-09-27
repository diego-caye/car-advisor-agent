"""AT-08, AT-09 y AT-10 de specs/09-acceptance-tests.md."""

from uuid import UUID

import pytest
from httpx import AsyncClient

from asesor.infrastructure.llm.fake import FakeAdkLlm, FakeTurn
from tests.support.sse import ReceivedEvent, parse_sse, send_message

TEST_DRIVE_TURNS = [
    FakeTurn(
        tool_name="request_human_handoff",
        tool_args={
            "reason": "TEST_DRIVE",
            "requirement_summary": "Quiere agendar un test drive para el sábado",
            "preferred_channel": "WHATSAPP",
        },
    ),
    FakeTurn(text="Listo, un asesor te contacta."),
]

ADMIN = {"Authorization": "Bearer test-admin-token"}


async def new_session(client: AsyncClient, user_id: UUID) -> str:
    response = await client.post("/api/v1/sessions", headers={"X-User-Id": str(user_id)})
    response.raise_for_status()
    session_id: str = response.json()["session_id"]
    return session_id


async def confirm(
    client: AsyncClient, user_id: UUID, session_id: str, confirmation_id: str, approved: bool
) -> list[ReceivedEvent]:
    response = await client.post(
        "/api/v1/chat/confirmations",
        json={
            "session_id": session_id,
            "confirmation_id": confirmation_id,
            "approved": approved,
        },
        headers={"X-User-Id": str(user_id)},
    )
    response.raise_for_status()
    return parse_sse(response.text)


def confirmation_id_of(events: list[ReceivedEvent]) -> str:
    asked = [e for e in events if e.event == "hitl.confirmation_required"]
    assert asked, "no se emitió hitl.confirmation_required"
    return str(asked[0].data["confirmation_id"])


async def test_at08_test_drive_confirmado_crea_handoff(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.rules = {"test drive": TEST_DRIVE_TURNS}
    session_id = await new_session(client, user_id)

    asked = await send_message(client, user_id, session_id, "quiero un test drive")

    pending = [e for e in asked if e.event == "hitl.confirmation_required"]
    assert pending[0].data["reason"] == "TEST_DRIVE"
    assert "test drive" in str(pending[0].data["resumen"]).lower()
    assert pending[0].data["preferred_channel"] == "WHATSAPP"

    lead = await client.get(
        f"/api/v1/sessions/{session_id}/lead", headers={"X-User-Id": str(user_id)}
    )
    assert lead.json()["stage"] == "HANDOFF_PENDING"

    resumed = await confirm(client, user_id, session_id, confirmation_id_of(asked), approved=True)

    created = [e for e in resumed if e.event == "handoff.created"]
    assert created, "no se emitió handoff.created"
    assert created[0].data["status"] == "OPEN"
    assert created[0].data["reason"] == "TEST_DRIVE"
    assert created[0].data["ticket"].startswith("TICK-")

    lead = await client.get(
        f"/api/v1/sessions/{session_id}/lead", headers={"X-User-Id": str(user_id)}
    )
    assert lead.json()["stage"] == "HANDED_OFF"

    listed = await client.get("/api/v1/handoffs?status=OPEN", headers=ADMIN)
    assert listed.status_code == 200
    assert [h["session_id"] for h in listed.json()] == [session_id]


async def test_at09_cancelar_la_confirmacion_no_crea_handoff(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.rules = {"test drive": TEST_DRIVE_TURNS}
    session_id = await new_session(client, user_id)

    asked = await send_message(client, user_id, session_id, "quiero un test drive")
    resumed = await confirm(client, user_id, session_id, confirmation_id_of(asked), approved=False)

    assert [e for e in resumed if e.event == "handoff.created"] == []

    lead = await client.get(
        f"/api/v1/sessions/{session_id}/lead", headers={"X-User-Id": str(user_id)}
    )
    assert lead.json()["stage"] == "NEW"

    listed = await client.get("/api/v1/handoffs", headers=ADMIN)
    assert listed.json() == []


async def test_at10_segundo_pedido_con_handoff_abierto_es_idempotente(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.rules = {
        "test drive": TEST_DRIVE_TURNS,
        "cotización": [
            FakeTurn(
                tool_name="request_human_handoff",
                tool_args={
                    "reason": "FORMAL_QUOTE",
                    "requirement_summary": "Ahora pide una cotización formal por escrito",
                },
            ),
            FakeTurn(text="Ya tienes una solicitud en curso."),
        ],
    }
    session_id = await new_session(client, user_id)

    asked = await send_message(client, user_id, session_id, "quiero un test drive")
    first = await confirm(client, user_id, session_id, confirmation_id_of(asked), approved=True)
    first_ticket = next(e for e in first if e.event == "handoff.created").data["ticket"]

    asked_again = await send_message(client, user_id, session_id, "también quiero una cotización")
    second = await confirm(
        client, user_id, session_id, confirmation_id_of(asked_again), approved=True
    )

    created = [e for e in second if e.event == "handoff.created"]
    assert created[0].data["ticket"] == first_ticket
    assert created[0].data["ya_existia"] is True
    assert created[0].data["reason"] == "TEST_DRIVE"

    listed = await client.get("/api/v1/handoffs", headers=ADMIN)
    assert len(listed.json()) == 1


async def test_confirmar_deja_la_decision_en_el_historial(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.rules = {"test drive": TEST_DRIVE_TURNS}
    session_id = await new_session(client, user_id)

    asked = await send_message(client, user_id, session_id, "quiero un test drive")
    resumed = await confirm(client, user_id, session_id, confirmation_id_of(asked), approved=True)
    ticket = next(e for e in resumed if e.event == "handoff.created").data["ticket"]

    messages = (
        await client.get(
            f"/api/v1/sessions/{session_id}/messages", headers={"X-User-Id": str(user_id)}
        )
    ).json()

    with_decision = [m for m in messages if m.get("decision")]
    assert len(with_decision) == 1
    assert with_decision[0]["decision"] == {
        "kind": "handoff",
        "ticket": ticket,
        "ya_existia": False,
    }


async def test_declinar_deja_la_decision_en_el_historial(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.rules = {"test drive": TEST_DRIVE_TURNS}
    session_id = await new_session(client, user_id)

    asked = await send_message(client, user_id, session_id, "quiero un test drive")
    await confirm(client, user_id, session_id, confirmation_id_of(asked), approved=False)

    messages = (
        await client.get(
            f"/api/v1/sessions/{session_id}/messages", headers={"X-User-Id": str(user_id)}
        )
    ).json()

    with_decision = [m for m in messages if m.get("decision")]
    assert len(with_decision) == 1
    assert with_decision[0]["decision"] == {"kind": "declined", "reason": "TEST_DRIVE"}


async def test_admin_endpoints_requieren_token(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/handoffs")).status_code == 401
    assert (
        await client.get("/api/v1/handoffs", headers={"Authorization": "Bearer nope"})
    ).status_code == 401


async def test_transicion_invalida_de_handoff_devuelve_409(
    client: AsyncClient, fake_llm: FakeAdkLlm, user_id: UUID
) -> None:
    fake_llm.rules = {"test drive": TEST_DRIVE_TURNS}
    session_id = await new_session(client, user_id)
    asked = await send_message(client, user_id, session_id, "quiero un test drive")
    events = await confirm(client, user_id, session_id, confirmation_id_of(asked), approved=True)
    handoff_id = next(e for e in events if e.event == "handoff.created").data["handoff_id"]

    closed = await client.patch(
        f"/api/v1/handoffs/{handoff_id}", json={"status": "CLOSED"}, headers=ADMIN
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"

    again = await client.patch(
        f"/api/v1/handoffs/{handoff_id}", json={"status": "IN_PROGRESS"}, headers=ADMIN
    )
    assert again.status_code == 409
    assert again.json()["code"] == "CONFLICT"


@pytest.mark.parametrize("handoff_id", [999999])
async def test_patch_de_handoff_inexistente_devuelve_404(
    client: AsyncClient, handoff_id: int
) -> None:
    response = await client.patch(
        f"/api/v1/handoffs/{handoff_id}", json={"status": "CLOSED"}, headers=ADMIN
    )
    assert response.status_code == 404
