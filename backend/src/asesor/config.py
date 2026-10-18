from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

OLLAMA_THINK_LEVELS = frozenset({"low", "medium", "high", "max"})

DEFAULT_MODEL_ID = "default"


class UnknownModelError(ValueError):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"Modelo desconocido: {model_id}")
        self.model_id = model_id


class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class LlmProviderName(StrEnum):
    GEMINI = "gemini"
    OLLAMA = "ollama"


class EmbeddingsProviderName(StrEnum):
    GEMINI = "gemini"
    OLLAMA = "ollama"


class ModelChoice(BaseModel):
    """An option in the UI's model selector.

    supports_tools/supports_thinking default to True (for hand-declared
    entries, typically Gemini): the configured model is assumed to have them
    unless stated otherwise. Ollama entries aren't declared by hand —
    infrastructure.container discovers them live against /api/show and puts
    the real value here (spec 11 §Local models).
    """

    id: str
    label: str
    provider: LlmProviderName
    model: str
    supports_tools: bool = True
    supports_thinking: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = AppEnv.DEV
    log_level: str = "INFO"
    frontend_origin: str = "http://localhost:5173"

    database_url: str
    admin_token: str

    llm_provider: LlmProviderName = LlmProviderName.GEMINI
    google_api_key: str | None = None
    google_genai_use_vertexai: bool = False
    ollama_api_base: str | None = None
    # Ollama silently truncates the context if it isn't told how much to use.
    # With 16 GB of VRAM, 16384 is comfortable for a ~10 GB model.
    ollama_context_length: int = Field(default=16384, gt=0)
    # Accepts a level ("low", "medium", "high") or a boolean. With no value
    # the parameter isn't sent: Ollama responds with 400 "does not support
    # thinking" if it's sent to a model that doesn't have it.
    # Small models with this capability ONLY call tools with thinking turned
    # on, so it isn't optional for them; "low" gives the same tool-calling as
    # true at less than half the latency (spec 05 §3, ADR-003).
    ollama_think: bool | str | None = None

    @field_validator("ollama_think", mode="before")
    @classmethod
    def _normalize_think(cls, value: object) -> object:
        """Ollama accepts the boolean or a level, but not the string "true".

        Without this, OLLAMA_THINK=true arrives as the string "true" and the
        API responds: invalid think value (must be high, medium, low, max,
        true, or false).
        """
        if not isinstance(value, str):
            return value

        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
        if lowered in OLLAMA_THINK_LEVELS:
            return lowered

        raise ValueError(
            f"OLLAMA_THINK must be true, false, or a level "
            f"({', '.join(sorted(OLLAMA_THINK_LEVELS))}); received: {value!r}"
        )

    agent_model: str
    guardrail_model: str
    eval_model: str
    fallback_model: str

    # Model selector catalog (JSON). Empty = a single option, AGENT_MODEL's,
    # and the selector isn't shown.
    model_choices: list[ModelChoice] = Field(default_factory=list)

    embeddings_provider: EmbeddingsProviderName = EmbeddingsProviderName.GEMINI
    embeddings_model: str
    rag_min_score: float = Field(default=0.55, ge=0.0, le=1.0)

    memory_compaction_token_threshold: int = Field(default=12000, gt=0)
    memory_compaction_keep_recent: int = Field(default=6, gt=0)

    guardrail_canary_token: str
    guardrail_l2_timeout_ms: int = Field(default=1500, gt=0)
    max_tool_calls_per_turn: int = Field(default=4, gt=0)
    enable_fault_injection: bool = False

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    langfuse_project_id: str | None = None
    eval_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def database_url_sync(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg")

    @property
    def fault_injection_active(self) -> bool:
        return self.enable_fault_injection and self.app_env is AppEnv.DEV

    @property
    def telemetry_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def gemini_usable(self) -> bool:
        return bool(self.google_api_key or self.google_genai_use_vertexai)

    # The catalog (what options exist, which is the default, resolving an id
    # to an option) lives in infrastructure.container.RunnerRegistry, not
    # here: it includes what Ollama reports having installed live, and
    # that's state discovered at startup, not static configuration. Settings
    # keeps only what's purely declarative.

    def is_usable(self, option: ModelChoice) -> bool:
        """Gemini needs credentials; local ones just need Ollama to respond."""
        if option.provider is LlmProviderName.GEMINI:
            return self.gemini_usable
        return bool(self.ollama_api_base)

    @model_validator(mode="after")
    def _check_async_driver(self) -> Self:
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use the async driver: postgresql+asyncpg://... "
                "(the sync DSN for Alembic is derived in database_url_sync)"
            )
        return self

    @model_validator(mode="after")
    def _check_provider_combination(self) -> Self:
        if self.llm_provider is LlmProviderName.GEMINI:
            if not self.google_genai_use_vertexai and not self.google_api_key:
                raise ValueError(
                    "LLM_PROVIDER=gemini requires GOOGLE_API_KEY "
                    "(or GOOGLE_GENAI_USE_VERTEXAI=true with GCP credentials)"
                )
        elif self.llm_provider is LlmProviderName.OLLAMA:
            if not self.ollama_api_base:
                raise ValueError("LLM_PROVIDER=ollama requires OLLAMA_API_BASE")
            # The ollama/ prefix can cause tool-calling loops and ignore
            # context; LiteLLM only treats ollama_chat/ as a conversational model.
            if self.agent_model.startswith("ollama/"):
                raise ValueError(
                    "AGENT_MODEL must use the 'ollama_chat/' prefix, not 'ollama/' "
                    f"(received: {self.agent_model})"
                )
            if not self.agent_model.startswith("ollama_chat/"):
                raise ValueError(
                    "With LLM_PROVIDER=ollama, AGENT_MODEL must start with 'ollama_chat/' "
                    f"(received: {self.agent_model})"
                )

        if self.embeddings_provider is EmbeddingsProviderName.OLLAMA and not self.ollama_api_base:
            raise ValueError("EMBEDDINGS_PROVIDER=ollama requires OLLAMA_API_BASE")

        if (
            self.embeddings_provider is EmbeddingsProviderName.GEMINI
            and not self.google_genai_use_vertexai
            and not self.google_api_key
        ):
            raise ValueError("EMBEDDINGS_PROVIDER=gemini requires GOOGLE_API_KEY")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
