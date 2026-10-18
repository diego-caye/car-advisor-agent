from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from asesor.infrastructure.db.engine import SessionFactory
from asesor.infrastructure.db.models import FeedbackRow


async def new_session(client: AsyncClient, user_id: UUID) -> str:
    response = await client.post("/api/v1/sessions", headers={"X-User-Id": str(user_id)})
    response.raise_for_status()
    session_id: str = response.json()["session_id"]
    return session_id


async def test_feedback_se_guarda_y_devuelve_ok(
    client: AsyncClient, user_id: UUID, session_factory: SessionFactory
) -> None:
    session_id = await new_session(client, user_id)

    response = await client.post(
        "/api/v1/feedback",
        json={
            "session_id": session_id,
            "trace_id": "abc123",
            "score": 1,
            "message": "¡Hola! ¿En qué te ayudo hoy?",
            "comment": "muy útil",
        },
        headers={"X-User-Id": str(user_id)},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    async with session_factory() as db_session:
        row = await db_session.scalar(
            select(FeedbackRow).where(FeedbackRow.session_id == session_id)
        )
    assert row is not None
    assert row.score == 1
    assert row.message == "¡Hola! ¿En qué te ayudo hoy?"
    assert row.comment == "muy útil"
    assert row.trace_id == "abc123"
    assert row.user_id == user_id


async def test_feedback_sin_comentario_es_opcional(client: AsyncClient, user_id: UUID) -> None:
    session_id = await new_session(client, user_id)

    response = await client.post(
        "/api/v1/feedback",
        json={"session_id": session_id, "trace_id": "abc123", "score": -1, "message": "Listo."},
        headers={"X-User-Id": str(user_id)},
    )

    assert response.status_code == 200


async def test_feedback_requiere_mensaje(client: AsyncClient, user_id: UUID) -> None:
    session_id = await new_session(client, user_id)

    response = await client.post(
        "/api/v1/feedback",
        json={"session_id": session_id, "trace_id": "abc123", "score": 1},
        headers={"X-User-Id": str(user_id)},
    )

    assert response.status_code == 422


async def test_feedback_404_si_la_sesion_no_es_del_usuario(
    client: AsyncClient, user_id: UUID
) -> None:
    session_id = await new_session(client, user_id)
    otro_usuario = uuid4()

    response = await client.post(
        "/api/v1/feedback",
        json={"session_id": session_id, "trace_id": "abc123", "score": 1, "message": "Listo."},
        headers={"X-User-Id": str(otro_usuario)},
    )

    assert response.status_code == 404


async def test_feedback_404_si_la_sesion_no_existe(client: AsyncClient, user_id: UUID) -> None:
    response = await client.post(
        "/api/v1/feedback",
        json={"session_id": "no-existe", "trace_id": "abc123", "score": 1, "message": "Listo."},
        headers={"X-User-Id": str(user_id)},
    )

    assert response.status_code == 404


async def test_feedback_rechaza_un_score_fuera_de_rango(client: AsyncClient, user_id: UUID) -> None:
    session_id = await new_session(client, user_id)

    response = await client.post(
        "/api/v1/feedback",
        json={"session_id": session_id, "trace_id": "abc123", "score": 5},
        headers={"X-User-Id": str(user_id)},
    )

    assert response.status_code == 422


async def test_feedback_rechaza_un_comentario_demasiado_largo(
    client: AsyncClient, user_id: UUID
) -> None:
    session_id = await new_session(client, user_id)

    response = await client.post(
        "/api/v1/feedback",
        json={
            "session_id": session_id,
            "trace_id": "abc123",
            "score": 1,
            "comment": "x" * 501,
        },
        headers={"X-User-Id": str(user_id)},
    )

    assert response.status_code == 422


async def test_feedback_requiere_x_user_id(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/feedback",
        json={"session_id": "s1", "trace_id": "abc123", "score": 1},
    )

    assert response.status_code == 401


async def test_borrar_la_sesion_borra_tambien_su_feedback(
    client: AsyncClient, user_id: UUID, session_factory: SessionFactory
) -> None:
    session_id = await new_session(client, user_id)
    await client.post(
        "/api/v1/feedback",
        json={
            "session_id": session_id,
            "trace_id": "trace-a-borrar",
            "score": 1,
            "message": "este feedback debe desaparecer con la sesion",
        },
        headers={"X-User-Id": str(user_id)},
    )

    delete_response = await client.delete(
        f"/api/v1/sessions/{session_id}", headers={"X-User-Id": str(user_id)}
    )
    assert delete_response.status_code == 204

    async with session_factory() as db_session:
        row = await db_session.scalar(
            select(FeedbackRow).where(FeedbackRow.session_id == session_id)
        )
    assert row is None


async def test_listar_feedback_devuelve_lo_mas_reciente_primero_con_mensaje(
    client: AsyncClient, user_id: UUID
) -> None:
    session_id = await new_session(client, user_id)
    await client.post(
        "/api/v1/feedback",
        json={
            "session_id": session_id,
            "trace_id": "trace-1",
            "score": 1,
            "message": "primer mensaje",
        },
        headers={"X-User-Id": str(user_id)},
    )
    await client.post(
        "/api/v1/feedback",
        json={
            "session_id": session_id,
            "trace_id": "trace-2",
            "score": -1,
            "message": "segundo mensaje",
        },
        headers={"X-User-Id": str(user_id)},
    )

    # No special header: listing feedback doesn't require a token (spec 02).
    response = await client.get("/api/v1/feedback")

    assert response.status_code == 200
    entries = response.json()
    assert len(entries) >= 2
    assert entries[0]["message"] == "segundo mensaje"
    assert entries[0]["session_id"] == session_id
    assert entries[1]["message"] == "primer mensaje"


async def test_borrar_feedback_por_id(client: AsyncClient, user_id: UUID) -> None:
    session_id = await new_session(client, user_id)
    await client.post(
        "/api/v1/feedback",
        json={
            "session_id": session_id,
            "trace_id": "trace-borrar",
            "score": 1,
            "message": "este feedback se borra solo",
        },
        headers={"X-User-Id": str(user_id)},
    )
    entries = (await client.get("/api/v1/feedback")).json()
    feedback_id = next(e["id"] for e in entries if e["trace_id"] == "trace-borrar")

    delete_response = await client.delete(f"/api/v1/feedback/{feedback_id}")
    assert delete_response.status_code == 204

    entries_after = (await client.get("/api/v1/feedback")).json()
    assert all(e["id"] != feedback_id for e in entries_after)


async def test_borrar_feedback_404_si_no_existe(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/feedback/999999")
    assert response.status_code == 404
