import re
import unicodedata
from dataclasses import dataclass

from asesor.agent.language import detect_language

SAFE_PRICING_REPLY = {
    "es": (
        "No manejo precios ni condiciones de financiamiento, para no darte un dato "
        "equivocado 😊 Si quieres, puedo pasar tu consulta a un asesor que te dé cifras "
        "exactas. ¿Te parece?"
    ),
    "en": (
        "I don't handle pricing or financing terms, so I don't give you the wrong figure 😊 "
        "If you'd like, I can pass your question to an advisor who can give you exact "
        "numbers. Sound good?"
    ),
}

_PRICING_PATTERNS: tuple[re.Pattern[str], ...] = (
    # `$` alone can't get a `\b` boundary check the way the word-forms can: `$`
    # is a non-word char, so `\b` never fires when it's preceded by whitespace
    # or sits at the start of the string ("costs $25,000" silently failed to
    # match) -- a bare `$` followed by a digit is unambiguous enough to check
    # for on its own, no boundary needed.
    re.compile(r"(?:\b(?:s/\.?|pen|usd|us\$)|\$)\s?\d"),
    re.compile(r"\b\d[\d.,]{2,}\s?(soles|dolares|dollars|usd|pen)\b"),
    re.compile(
        r"\b(cuesta|costs?)\s+(aproximadamente\s+|cerca\s+de\s+|unos\s+|about\s+|around\s+)?\d"
    ),
    re.compile(
        r"\b(precio|costo|valor|price|cost)\s+(de\s+lista|final|aproximado|referencial|"
        r"list|final|approximate|estimated|reference)\b"
    ),
    re.compile(r"\b\d+\s*(cuotas?|installments?|payments?)\s+(de|of)\b"),
    re.compile(r"\b(cuota|letra|installment|payment)\s+mensual(mente)?\s+(de|of)\s+\d"),
    re.compile(
        r"\b(tasa|tea|tcea|interest\s+rate)\s+(de\s+|es\s+|del\s+|queda\s+en\s+|"
        r"is\s+|of\s+)?\d"
    ),
    re.compile(r"\b(descuento|discount)\s+(de\s+|of\s+)?\d+\s*%"),
    re.compile(r"\bhay\s+\d+\s+unidades?\s+(en\s+)?stock\b"),
    re.compile(r"\bthere\s+are\s+\d+\s+units?\s+(in\s+)?stock\b"),
)


TOOL_NAMES = ("save_lead", "request_human_handoff", "search_knowledge_base")

# Small models sometimes "write" the call instead of emitting it as a real
# function call. The text stays on screen and the tool never runs. Seen with
# Gemma 4 via Ollama (ADR-003).
#
# `tool(...)` on its own line isn't enough: it also writes it with braces and
# a made-up prefix, glued to the end of a paragraph, like
# `llama:guardar_lead{uso_principal:<|"|>VIAJES<|"|>}` (a real observed output,
# from before the domain vocabulary was renamed to English — kept verbatim
# since it's what the regex below was built to catch). Hence accepting all
# three bracket types plus an optional `something:` or `<|something|>:` prefix.
_PSEUDO_TOOL_CALL = re.compile(
    r"(?:^|\s)"
    r"(?:[<\[|]{0,2}[a-z_]{0,16}[>\]|]{0,2}\s*[:=]\s*)?"
    r"(?:" + "|".join(TOOL_NAMES) + r")"
    r"\s*(?:\([^()]*\)|\{[^{}]*\}|\[[^\[\]]*\])",
    re.IGNORECASE,
)

# Another way of "writing" the tool: a JSON object like
# {"name": "guardar_lead", "parameters": {...}} -- seen with the fallback
# model (llama3.2:3b) via LiteLLM. It sometimes comes out malformed (no ":"
# before "parameters", unclosed braces), so it's not worth trimming just that
# part with a regex: if this signature shows up, the whole reply is suspect
# and gets discarded entirely instead of trying to salvage the rest.
_JSON_ENVELOPE_TOOL_CALL = re.compile(
    r"""["']name["']\s*:\s*["'](?:""" + "|".join(TOOL_NAMES) + r")[\"']",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class L4Verdict:
    blocked: bool
    category: str | None = None
    replacement: str | None = None


def strip_pseudo_tool_calls(text: str) -> str:
    """Removes tool calls the model wrote out as text."""
    if _JSON_ENVELOPE_TOOL_CALL.search(text):
        return ""

    without = _PSEUDO_TOOL_CALL.sub("", text)
    # The pattern eats the separator that preceded it, so the spaces and line
    # breaks need to be put back the way they were before trimming.
    collapsed = re.sub(r"[ \t]{2,}", " ", without)
    return re.sub(r"\n{2,}", "\n", collapsed).strip()


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def inspect_reply(text: str, canary_token: str, jailbreak_reply: dict[str, str]) -> L4Verdict:
    """Checks the model's full reply before it reaches the user."""
    language = detect_language(text)

    if canary_token and canary_token.casefold() in text.casefold():
        return L4Verdict(True, "canary_leak", jailbreak_reply[language])

    haystack = _fold(text)
    for pattern in _PRICING_PATTERNS:
        if pattern.search(haystack):
            return L4Verdict(True, "pricing_leak", SAFE_PRICING_REPLY[language])

    return L4Verdict(False)
