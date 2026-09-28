import os
from collections.abc import AsyncIterator, Iterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# Compose publishes ports outside the usual ones so as not to clash with
# other projects. In CI the service listens on 5432 and is passed via
# TEST_DATABASE_URL.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://asesor:asesor@localhost:5490/asesor_test"
)

TEST_ENV = {
    # dev + ENABLE_FAULT_INJECTION so the fault ATs can be exercised. That
    # the header is ignored outside of dev is covered by test_config
    # (fault_injection_active).
    "APP_ENV": "dev",
    "ENABLE_FAULT_INJECTION": "true",
    "DATABASE_URL": TEST_DATABASE_URL,
    "ADMIN_TOKEN": "test-admin-token",
    "LLM_PROVIDER": "gemini",
    "GOOGLE_API_KEY": "test-key",
    "AGENT_MODEL": "gemini-3.8-flash",
    "GUARDRAIL_MODEL": "gemini-3.5-flash-lite",
    "EVAL_MODEL": "gemini-3.5-flash",
    "FALLBACK_MODEL": "gemini-3.7-flash",
    "EMBEDDINGS_PROVIDER": "gemini",
    "EMBEDDINGS_MODEL": "gemini-embedding-001",
    "GUARDRAIL_CANARY_TOKEN": "CANARY-TEST-0001",
    # Blank on purpose, even though the developer's real .env has real keys
    # (F7): without this, Settings falls back to the real ../.env and the
    # tests that assume "no Langfuse configured" (telemetry_enabled is
    # False) break -- or worse, they'd call the real Langfuse API by accident.
    "LANGFUSE_PUBLIC_KEY": "",
    "LANGFUSE_SECRET_KEY": "",
    "LANGFUSE_HOST": "",
    "LANGFUSE_PROJECT_ID": "",
    # FakeEmbeddings is a bag-of-words: its scores don't live in the same
    # range as a real embedder's, which production's 0.55 is calibrated for.
    # Measured against the real KB: relevant query ~0.55, irrelevant ~0.07,
    # so 0.35 separates both cases. What the test verifies is the
    # threshold's wiring (no_results, ordering, filter), not the embedding's
    # semantic quality.
    "RAG_MIN_SCORE": "0.35",
}

for _key, _value in TEST_ENV.items():
    os.environ[_key] = _value

from asesor.config import Settings, get_settings  # noqa: E402
from asesor.infrastructure.db.engine import (  # noqa: E402
    SessionFactory,
    create_engine,
    create_session_factory,
)
from asesor.infrastructure.db.models import Base  # noqa: E402
from asesor.infrastructure.embeddings.fake import FakeEmbeddings  # noqa: E402
from asesor.infrastructure.llm.fake import FakeAdkLlm  # noqa: E402
from asesor.main import create_app  # noqa: E402


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    yield monkeypatch


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def clean_database(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text("TRUNCATE TABLE leads, handoffs, kb_chunks, session_titles, feedback, evaluations")
        )
    await engine.dispose()


@pytest.fixture
def fake_llm() -> FakeAdkLlm:
    return FakeAdkLlm()


@pytest.fixture
def fake_embeddings() -> FakeEmbeddings:
    return FakeEmbeddings()


@pytest.fixture
def session_factory(settings: Settings, clean_database: None) -> SessionFactory:
    return create_session_factory(create_engine(settings.database_url))


@pytest.fixture
async def app(
    settings: Settings,
    fake_llm: FakeAdkLlm,
    fake_embeddings: FakeEmbeddings,
    clean_database: None,
) -> AsyncIterator[FastAPI]:
    application = create_app(settings, model=fake_llm, embeddings=fake_embeddings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def user_id() -> UUID:
    return uuid4()
