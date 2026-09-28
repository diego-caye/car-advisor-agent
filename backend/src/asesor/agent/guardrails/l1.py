import re
import unicodedata
from dataclasses import dataclass

MAX_MESSAGE_CHARS = 2000

# Cc = control, Cf = invisible formatting (zero-width, bidi overrides). These
# are used to hide instructions inside a message that looks innocent at a
# glance. Filtering by category covers more than a hand-written list of
# ranges.
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf"})
_KEEP_ANYWAY = frozenset({"\n", "\r", "\t"})

_WHITESPACE = re.compile(r"\s+")

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "injection",
        re.compile(
            r"\b(ignora|olvida|descarta|omite)\s+(todas?\s+)?(tus|las|mis|sus)?\s*"
            r"(anteriores\s+)?(instruccion|regla|directriz|orden|indicacion)"
        ),
    ),
    (
        "injection",
        re.compile(
            r"\bignore\s+(all\s+)?(your\s+|the\s+|previous\s+)*"
            r"(instructions?|rules?|directions?|prompts?)"
        ),
    ),
    (
        "injection",
        re.compile(
            r"\b(revela|muestra|dime|imprime|repite|comparte|dame)\s+"
            r"(me\s+)?(tus?|el|las?|los|sus?|mis?)?\s*"
            r"(system\s+)?(prompt|instruccion|instrucciones|reglas|configuracion|"
            r"mensaje\s+de\s+sistema)"
        ),
    ),
    (
        "injection",
        re.compile(
            r"\b(reveal|show|print|repeat|output|tell\s+me)\s+"
            r"(me\s+)?(your|the)?\s*(system\s+)?(prompt|instructions?|rules?)"
        ),
    ),
    (
        "injection",
        re.compile(
            r"\b(a\s+partir\s+de\s+ahora|de\s+ahora\s+en\s+adelante|desde\s+ahora)\s+"
            r"(eres|actuas|te\s+comportas|seras)"
        ),
    ),
    (
        "injection",
        re.compile(r"\b(you\s+are\s+now|from\s+now\s+on\s+you\s+are|act\s+as\s+if\s+you)\b"),
    ),
    ("injection", re.compile(r"\b(modo|mode)\s+(desarrollador|developer|dan|jailbreak)\b")),
    # Role labels: passing off user text as a system turn.
    ("injection", re.compile(r"(^|\s)(system|assistant|developer)\s*:")),
    ("injection", re.compile(r"<\s*/?\s*(system|assistant|instructions?)\s*>")),
    # Long encoded blocks, used to hide the payload.
    ("injection", re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b")),
    ("injection", re.compile(r"\b(?:[0-9a-f]{2}[\s:]){30,}")),
)


@dataclass(frozen=True, slots=True)
class L1Verdict:
    blocked: bool
    category: str | None = None
    reason: str | None = None


def strip_invisible(text: str) -> str:
    return "".join(
        char
        for char in text
        if char in _KEEP_ANYWAY or unicodedata.category(char) not in _INVISIBLE_CATEGORIES
    )


def normalize(text: str) -> str:
    """NFKC, without invisibles, and with collapsed whitespace.

    Normalization happens before pattern matching: without it, "ignora"
    written in full-width characters, or split with a zero-width character
    in the middle, would dodge the filter.
    """
    normalized = unicodedata.normalize("NFKC", strip_invisible(text))
    return _WHITESPACE.sub(" ", normalized).strip()


def fold(text: str) -> str:
    """Lowercase and without accents, so 'instrucción' and 'instruccion' match."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def inspect_message(text: str) -> L1Verdict:
    if len(text) > MAX_MESSAGE_CHARS:
        return L1Verdict(True, "too_long", f"{len(text)}-character message")

    haystack = fold(normalize(text))

    for category, pattern in _INJECTION_PATTERNS:
        if pattern.search(haystack):
            return L1Verdict(True, category, pattern.pattern[:60])

    return L1Verdict(False)
