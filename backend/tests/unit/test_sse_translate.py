from collections.abc import AsyncIterator

from google.adk.events import Event
from google.genai import types

from asesor.api.sse import EMPTY_REPLY_FALLBACK, SseEvent, translate


async def feed(*events: Event) -> AsyncIterator[Event]:
    for event in events:
        yield event


def model_event(*parts: types.Part, partial: bool = False) -> Event:
    return Event(
        author="luis",
        content=types.Content(role="model", parts=list(parts)),
        partial=partial or None,
    )


async def collect(*events: Event) -> list[SseEvent]:
    return [item async for item in translate(feed(*events), "trace-1")]


async def test_el_razonamiento_no_llega_al_usuario() -> None:
    event = model_event(
        types.Part(text="Thinking: el usuario saluda...", thought=True),
        types.Part.from_text(text="Hola 👋 Soy Luis."),
    )

    deltas = [e.data["delta"] for e in await collect(event) if e.event == "message.delta"]

    assert deltas == ["Hola 👋 Soy Luis."]


async def test_un_turno_solo_de_razonamiento_no_deja_burbuja_vacia() -> None:
    event = model_event(types.Part(text="Thinking: ...", thought=True))

    deltas = [e.data["delta"] for e in await collect(event) if e.event == "message.delta"]

    assert deltas == [EMPTY_REPLY_FALLBACK]


async def test_un_turno_que_pide_confirmacion_no_recibe_relleno() -> None:
    call = types.Part.from_function_call(
        name="adk_request_confirmation",
        args={"toolConfirmation": {"payload": {"reason": "TEST_DRIVE", "resumen": "x"}}},
    )

    events = await collect(model_event(call))

    assert [e.event for e in events if e.event == "message.delta"] == []
    assert any(e.event == "hitl.confirmation_required" for e in events)


async def test_un_turno_con_confirmacion_ignora_todo_lo_que_llegue_despues() -> None:
    """Reproduces live with gemma4:12b: after requesting confirmation, the
    SAME invocation sometimes keeps producing events (a function response,
    more text) instead of stopping to wait for the user. Spec 02 §2 says the
    turn closes right there -- this test pins down that `translate` really
    does that, no matter what else `events` brings afterward.
    """
    call = types.Part.from_function_call(
        name="adk_request_confirmation",
        args={"toolConfirmation": {"payload": {"reason": "TEST_DRIVE", "resumen": "x"}}},
    )
    response_after = Event(
        author="user",
        content=types.Content(
            role="user",
            parts=[
                types.Part.from_function_response(
                    name="adk_request_confirmation", response={"status": "ok"}
                )
            ],
        ),
    )
    text_after = model_event(types.Part.from_text(text="Ya te conecto con un asesor."))

    events = await collect(model_event(call), response_after, text_after)

    assert [e.event for e in events] == ["hitl.confirmation_required"]


async def test_el_texto_se_entrega_una_vez_revisado_por_l4() -> None:
    """Partials are buffered: nothing goes out before L4 sees the complete response.

    Once a delta has been streamed there's no way to retract it from the
    client, so the output filter only works if the text is held back until
    the end.
    """
    events = await collect(
        model_event(types.Part.from_text(text="Hola "), partial=True),
        model_event(types.Part.from_text(text="Diego"), partial=True),
        model_event(types.Part.from_text(text="Hola Diego")),
    )

    deltas = [e.data["delta"] for e in events if e.event == "message.delta"]

    assert deltas == ["Hola Diego"]


async def test_si_no_llega_la_respuesta_final_se_usa_lo_acumulado() -> None:
    events = await collect(
        model_event(types.Part.from_text(text="Hola "), partial=True),
        model_event(types.Part.from_text(text="Diego"), partial=True),
    )

    deltas = [e.data["delta"] for e in events if e.event == "message.delta"]

    assert deltas == ["Hola Diego"]


async def test_l4_descarta_lo_acumulado_y_entrega_su_reemplazo() -> None:
    filtrado = Event(
        author="luis",
        content=types.Content(role="model", parts=[types.Part.from_text(text="Texto seguro")]),
        custom_metadata={"temp:guardrail": {"layer": "L4", "category": "pricing_leak"}},
    )

    events = await collect(
        model_event(types.Part.from_text(text="cuesta S/ 89,900"), partial=True),
        filtrado,
    )

    deltas = [e.data["delta"] for e in events if e.event == "message.delta"]

    assert deltas == ["Texto seguro"]
    assert any(e.event == "guardrail.triggered" for e in events)
