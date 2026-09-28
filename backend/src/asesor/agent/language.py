import re

# Lightweight heuristic, not a full language-detection library: this only has
# to pick between two languages for a handful of code-enforced canned replies
# (guardrail substitutions), not classify arbitrary text. Defaults to Spanish
# whenever the signal is weak or absent, matching the agent's default persona
# (Peru Spanish) when the user's language isn't clearly something else.
_SPANISH_CHARS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]")
_SPANISH_WORDS = re.compile(
    r"\b(hola|gracias|quiero|necesito|busco|auto|carro|precio|cuanto|cuesta|"
    r"como|que|donde|para|con|una|unos|unas|el|la|los|las|de|es|soy|tengo|"
    r"puedo|hablar|ayuda)\b",
    re.IGNORECASE,
)
_ENGLISH_WORDS = re.compile(
    r"\b(the|is|are|you|your|please|thanks|thank|want|need|looking|how|"
    r"what|where|why|car|price|cost|hello|hi|can|would|i'm|about|help)\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Returns "es" or "en". Spanish accented characters are a strong,
    unambiguous signal on their own; otherwise falls back to comparing how
    many common Spanish vs. English stopwords appear, defaulting to Spanish
    on a tie or empty input.
    """
    if not text:
        return "es"
    if _SPANISH_CHARS.search(text):
        return "es"

    spanish_hits = len(_SPANISH_WORDS.findall(text))
    english_hits = len(_ENGLISH_WORDS.findall(text))
    return "en" if english_hits > spanish_hits else "es"
