from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from asesor.infrastructure.llm.fake import FALLBACK_TEXT, FakeAdkLlm, FakeTurn


def request_with_instruction(text: str = "instrucción de prueba") -> LlmRequest:
    return LlmRequest(
        model="fake-llm",
        config=types.GenerateContentConfig(system_instruction=text),
    )


async def collect(llm: FakeAdkLlm, *, stream: bool = False) -> list[LlmResponse]:
    return [
        response
        async for response in llm.generate_content_async(request_with_instruction(), stream=stream)
    ]


async def test_yields_scripted_text_turns_in_order() -> None:
    llm = FakeAdkLlm(turns=[FakeTurn(text="primero"), FakeTurn(text="segundo")])

    first = await collect(llm)
    second = await collect(llm)

    assert first[-1].content is not None
    assert first[-1].content.parts is not None
    assert first[-1].content.parts[0].text == "primero"
    assert second[-1].content is not None
    assert second[-1].content.parts is not None
    assert second[-1].content.parts[0].text == "segundo"


async def test_streaming_emits_partials_then_a_final_response() -> None:
    llm = FakeAdkLlm(turns=[FakeTurn(text="hola, soy Luis y te acompaño")])

    responses = await collect(llm, stream=True)

    assert [r.partial for r in responses[:-1]] == [True] * (len(responses) - 1)
    assert responses[-1].partial is not True
    joined = "".join(
        part.text or ""
        for r in responses[:-1]
        if r.content and r.content.parts
        for part in r.content.parts
    )
    assert joined == "hola, soy Luis y te acompaño"


async def test_tool_turn_yields_a_function_call() -> None:
    llm = FakeAdkLlm(turns=[FakeTurn(tool_name="save_lead", tool_args={"name": "Diego"})])

    responses = await collect(llm)

    assert len(responses) == 1
    content = responses[0].content
    assert content is not None and content.parts is not None
    call = content.parts[0].function_call
    assert call is not None
    assert call.name == "save_lead"
    assert call.args == {"name": "Diego"}


async def test_falls_back_when_the_script_runs_out() -> None:
    llm = FakeAdkLlm(turns=[])

    responses = await collect(llm)

    assert responses[-1].content is not None
    assert responses[-1].content.parts is not None
    assert responses[-1].content.parts[0].text == FALLBACK_TEXT


async def test_records_the_system_instruction_of_every_call() -> None:
    llm = FakeAdkLlm(turns=[FakeTurn(text="a"), FakeTurn(text="b")])

    await collect(llm)
    await collect(llm)

    assert llm.instructions == ["instrucción de prueba", "instrucción de prueba"]
    assert llm.calls == 2
