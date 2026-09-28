import pytest

from asesor.agent.language import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hola, soy Diego y busco un auto para uso familiar", "es"),
        ("¿cuánto cuesta una camioneta 4x4?", "es"),
        ("hi, I'm looking for a family car", "en"),
        ("how much does a 4x4 truck cost?", "en"),
        ("", "es"),
        ("SUV", "es"),
    ],
)
def test_detect_language(text: str, expected: str) -> None:
    assert detect_language(text) == expected
