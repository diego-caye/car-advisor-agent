from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert

from asesor.infrastructure.db.engine import SessionFactory
from asesor.infrastructure.db.models import KbChunkRow
from asesor.infrastructure.embeddings.fake import FakeEmbeddings
from asesor.infrastructure.kb_loader import load_chunks

KB_DIR = Path(__file__).parents[3] / "kb"


async def seed_kb(
    session_factory: SessionFactory,
    embeddings: FakeEmbeddings,
    sources: list[str],
) -> int:
    """Scoped ingestion of the real KB: only the files the test needs."""
    chunks = [chunk for chunk in load_chunks(KB_DIR) if chunk.source in sources]
    if not chunks:
        raise AssertionError(f"Ningún fragmento para {sources} en {KB_DIR}")

    vectors = await embeddings.embed_documents([chunk.content for chunk in chunks])

    async with session_factory() as session, session.begin():
        for chunk, vector in zip(chunks, vectors, strict=True):
            values = {
                "chunk_id": chunk.chunk_id,
                "title": chunk.title,
                "category": chunk.category.value,
                "source": chunk.source,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "embedding_model": embeddings.model_name,
                "embedding": vector,
            }
            await session.execute(
                pg_insert(KbChunkRow)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[KbChunkRow.chunk_id],
                    set_={k: v for k, v in values.items() if k != "chunk_id"},
                )
            )

    return len(chunks)
