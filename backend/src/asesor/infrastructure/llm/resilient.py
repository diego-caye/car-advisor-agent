import asyncio
import logging
from collections.abc import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from pydantic import Field

from asesor.agent.guardrails.faults import Fault, InjectedModelError
from asesor.infrastructure.fault_context import current_fault

logger = logging.getLogger(__name__)

# The n8n baseline retried 3 times with a fixed 3 s delay (retryOnFail /
# maxTries). Here the backoff is exponential, which behaves better under a
# sustained 429.
DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.5

_RETRYABLE_MARKERS = (
    "429",
    "rate limit",
    "resource_exhausted",
    "quota",
    "500",
    "502",
    "503",
    "504",
    "unavailable",
    "deadline",
    "timeout",
)


def is_retryable(error: BaseException) -> bool:
    if isinstance(error, TimeoutError | InjectedModelError):
        return True
    message = str(error).casefold()
    return any(marker in message for marker in _RETRYABLE_MARKERS)


class ResilientLlm(BaseLlm):
    """Retries with backoff and falls back to the backup model (spec 07 §3).

    Only retries if it hasn't emitted anything yet: once it has started
    streaming text to the user, repeating the call would duplicate what was
    already delivered.
    """

    model: str = "resilient"
    primary: BaseLlm
    fallback: BaseLlm | None = None
    attempts: int = Field(default=DEFAULT_ATTEMPTS, ge=1)
    base_delay: float = Field(default=DEFAULT_BASE_DELAY, ge=0.0)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last_error: BaseException | None = None

        for attempt in range(1, self.attempts + 1):
            emitted = False
            try:
                async for response in self._call(self.primary, llm_request, stream, primary=True):
                    emitted = True
                    yield response
                return
            except Exception as error:
                if emitted:
                    # Text already went out to the user: retrying would
                    # duplicate it.
                    logger.error("model failed midway through the stream: %s", error)
                    raise
                if not is_retryable(error):
                    raise
                last_error = error
                logger.warning(
                    "primary model failed (attempt %s/%s): %s", attempt, self.attempts, error
                )
                if attempt < self.attempts:
                    await asyncio.sleep(self.base_delay * (2 ** (attempt - 1)))

        if self.fallback is None:
            raise last_error if last_error else RuntimeError("primary model failed")

        logger.warning("falling back to the backup model after %s attempts", self.attempts)
        async for response in self._call(self.fallback, llm_request, stream, primary=False):
            yield response

    async def _call(
        self, model: BaseLlm, llm_request: LlmRequest, stream: bool, *, primary: bool
    ) -> AsyncGenerator[LlmResponse, None]:
        if primary:
            fault = current_fault()
            if fault is Fault.MODEL_429:
                raise InjectedModelError(fault)
            if fault is Fault.MODEL_TIMEOUT:
                raise TimeoutError("fault injection: model_timeout")

        # LiteLlm resolves the provider from llm_request.model, not from its
        # own field. Without this it would see the wrapper's name and fail
        # with "LLM Provider NOT provided".
        llm_request.model = model.model

        async for response in model.generate_content_async(llm_request, stream):
            yield response
