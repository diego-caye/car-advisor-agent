import logging
import re
from uuid import UUID

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from asesor.infrastructure.db.session_title_repository import SqlSessionTitleRepository

logger = logging.getLogger(__name__)

MAX_TITLE_CHARS = 48

_PROMPT = (
    "Summarize in a short title of 3 to 6 words what this customer's query to "
    "a car advisor is about. Write the title in the SAME language as the "
    "query below -- never translate it. Reply with ONLY the title: no "
    "quotes, no trailing period, no explanations.\n\nQuery: {message}\n\nTitle:"
)

_QUOTES = re.compile(r'^["\'`¿¡\s]+|["\'`.\s]+$')
_WHITESPACE = re.compile(r"\s+")


def clean_title(raw: str) -> str:
    """Small models add extra quotes, prefixes, and explanations."""
    first_line = next((line for line in raw.splitlines() if line.strip()), "")
    without_prefix = re.sub(r"^\s*(t[ií]tulo|title)\s*:\s*", "", first_line, flags=re.IGNORECASE)
    collapsed = _WHITESPACE.sub(" ", _QUOTES.sub("", without_prefix))
    return collapsed[:MAX_TITLE_CHARS].strip()


def fallback_title(message: str) -> str:
    """If the model doesn't give anything usable, the message itself serves as the title."""
    collapsed = _WHITESPACE.sub(" ", message).strip()
    if len(collapsed) <= MAX_TITLE_CHARS:
        return collapsed
    return collapsed[: MAX_TITLE_CHARS - 1].rstrip() + "…"


class TitleService:
    """Names the conversation from the user's first message.

    Runs in the background and with the lightweight model: it must never add
    latency to the turn or break it if it fails, because it's just a sidebar
    decoration.

    The title lives in its own table (session_title_repository), not in the
    ADK session's state: storing it there competed for the same optimistic
    lock as the chat turn, and a following turn that arrived while the title
    was being written would come back rejected with StaleSessionError — a
    decoration taking down the actual response (seen in production, not in
    theory).
    """

    def __init__(self, model: BaseLlm, titles: SqlSessionTitleRepository) -> None:
        self._model = model
        self._titles = titles

    async def ensure_title(self, user_id: UUID, session_id: str, first_message: str) -> str | None:
        if await self._titles.get(session_id) is not None:
            return None

        title = await self._generate(first_message) or fallback_title(first_message)
        await self._titles.upsert(session_id, user_id, title)
        return title

    async def _generate(self, message: str) -> str:
        request = LlmRequest(
            model=self._model.model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=_PROMPT.format(message=message))],
                )
            ],
        )

        try:
            chunks: list[str] = []
            async for response in self._model.generate_content_async(request, False):
                if response.partial or response.content is None or not response.content.parts:
                    continue
                chunks.extend(
                    part.text or "" for part in response.content.parts if not part.thought
                )
            return clean_title("".join(chunks))
        except Exception:
            logger.warning("could not generate the conversation title", exc_info=True)
            return ""
