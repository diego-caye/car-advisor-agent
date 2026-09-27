import re
import unicodedata
from dataclasses import dataclass

SAFE_PRICING_REPLY = (
    "No manejo precios ni condiciones de financiamiento, para no darte un dato "
    "equivocado 😊 Si quieres, puedo pasar tu consulta a un asesor que te dé cifras "
    "exactas. ¿Te parece?"
)

_PRICING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(s/\.?|pen|usd|us\$|\$)\s?\d"),
    re.compile(r"\b\d[\d.,]{2,}\s?(soles|dolares|dollars|usd|pen)\b"),
    re.compile(r"\bcuesta\s+(aproximadamente\s+|cerca\s+de\s+|unos\s+)?\d"),
    re.compile(r"\b(precio|costo|valor)\s+(de\s+lista|final|aproximado|referencial)\b"),
    re.compile(r"\b\d+\s*cuotas?\s+de\b"),
    re.compile(r"\b(cuota|letra)\s+mensual\s+de\s+\d"),
    re.compile(r"\b(tasa|tea|tcea)\s+(de\s+|es\s+|del\s+|queda\s+en\s+)?\d"),
    re.compile(r"\bdescuento\s+de\s+\d+\s*%"),
    re.compile(r"\bhay\s+\d+\s+unidades?\s+(en\s+)?stock\b"),
)


TOOL_NAMES = ("save_lead", "request_human_handoff", "search_knowledge_base")

# Los modelos pequeños a veces "escriben" la llamada en vez de emitirla como
# function call. El texto queda en pantalla y la tool nunca se ejecuta. Visto
# con Gemma 4 vía Ollama (ADR-003).
#
# No basta con `tool(...)` en su propia línea: también la escribe con llaves y
# con un prefijo inventado, pegada al final de un párrafo, como
# `llama:guardar_lead{uso_principal:<|"|>VIAJES<|"|>}`. De ahí que se acepten
# los tres tipos de paréntesis y un prefijo opcional `algo:` o `<|algo|>:`.
_PSEUDO_TOOL_CALL = re.compile(
    r"(?:^|\s)"
    r"(?:[<\[|]{0,2}[a-z_]{0,16}[>\]|]{0,2}\s*[:=]\s*)?"
    r"(?:" + "|".join(TOOL_NAMES) + r")"
    r"\s*(?:\([^()]*\)|\{[^{}]*\}|\[[^\[\]]*\])",
    re.IGNORECASE,
)

# Otra forma de "escribir" la tool: un objeto JSON tipo
# {"name": "guardar_lead", "parameters": {...}} -- visto con el modelo de
# respaldo (llama3.2:3b) vía LiteLLM. A veces sale mal formado (sin ":" antes
# de "parameters", llaves sin cerrar), así que no vale la pena recortar solo
# esa parte con un regex: si aparece esta firma, toda la respuesta es
# sospechosa y se descarta entera en vez de intentar salvar el resto.
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
    """Quita las llamadas a tools que el modelo escribió como texto."""
    if _JSON_ENVELOPE_TOOL_CALL.search(text):
        return ""

    without = _PSEUDO_TOOL_CALL.sub("", text)
    # El patrón se come el separador que iba delante, así que hay que dejar los
    # espacios y los saltos como estaban antes de recortar.
    collapsed = re.sub(r"[ \t]{2,}", " ", without)
    return re.sub(r"\n{2,}", "\n", collapsed).strip()


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def inspect_reply(text: str, canary_token: str, jailbreak_reply: str) -> L4Verdict:
    """Revisa la respuesta completa del modelo antes de entregarla al usuario."""
    if canary_token and canary_token.casefold() in text.casefold():
        return L4Verdict(True, "canary_leak", jailbreak_reply)

    haystack = _fold(text)
    for pattern in _PRICING_PATTERNS:
        if pattern.search(haystack):
            return L4Verdict(True, "pricing_leak", SAFE_PRICING_REPLY)

    return L4Verdict(False)
