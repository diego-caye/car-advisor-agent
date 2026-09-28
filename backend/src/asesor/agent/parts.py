from google.genai import types


def visible_text(content: types.Content | None) -> str:
    """Text shown to the user, without the model's reasoning.

    Models with "thinking" (Gemini, and Gemma 4 via Ollama) return their
    reasoning as parts marked with thought=True. Concatenating all the parts
    would show the user the model's internal monologue.
    """
    if content is None or not content.parts:
        return ""

    return "".join(part.text or "" for part in content.parts if not part.thought)
