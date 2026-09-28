"""Idempotent knowledge base ingestion.

Usage:  uv run python scripts/ingest_kb.py [--kb-dir ../kb] [--dry-run]

Only recomputes the embedding for chunks whose content changed (hash) or
that were ingested with a different model. Chunks that no longer exist in
kb/ are deleted, so the table always reflects the directory's state.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from asesor.config import get_settings
from asesor.infrastructure.container import build_embeddings
from asesor.infrastructure.db.engine import create_engine, create_session_factory
from asesor.infrastructure.db.models import KbChunkRow
from asesor.infrastructure.embeddings.fake import FakeEmbeddings
from asesor.infrastructure.kb_loader import load_chunks

BATCH_SIZE = 32


async def ingest(kb_dir: Path, *, dry_run: bool, use_fake: bool) -> int:
    settings = get_settings()
    embeddings = FakeEmbeddings() if use_fake else build_embeddings(settings)

    chunks = load_chunks(kb_dir)
    if not chunks:
        print(f"No .md files found in {kb_dir}")
        return 1

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            stored = {
                chunk_id: (content_hash, model)
                for chunk_id, content_hash, model in (
                    await session.execute(
                        select(
                            KbChunkRow.chunk_id,
                            KbChunkRow.content_hash,
                            KbChunkRow.embedding_model,
                        )
                    )
                ).all()
            }

        pending = [
            chunk
            for chunk in chunks
            if stored.get(chunk.chunk_id) != (chunk.content_hash, embeddings.model_name)
        ]
        obsolete = sorted(set(stored) - {chunk.chunk_id for chunk in chunks})

        print(
            f"{len(chunks)} chunks in {kb_dir.name}/ · "
            f"{len(pending)} to (re)embed · {len(obsolete)} obsolete · "
            f"model {embeddings.model_name}"
        )

        if dry_run:
            return 0

        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start : start + BATCH_SIZE]
            vectors = await embeddings.embed_documents([chunk.content for chunk in batch])

            async with session_factory() as session, session.begin():
                for chunk, vector in zip(batch, vectors, strict=True):
                    values = {
                        "chunk_id": chunk.chunk_id,
                        "title": chunk.title,
                        "categoria": chunk.categoria.value,
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

            print(f"  embedded {min(start + BATCH_SIZE, len(pending))}/{len(pending)}")

        if obsolete:
            async with session_factory() as session, session.begin():
                await session.execute(delete(KbChunkRow).where(KbChunkRow.chunk_id.in_(obsolete)))
            print(f"  removed {len(obsolete)} obsolete chunks")

        print("Ingestion complete.")
        return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-dir", type=Path, default=Path(__file__).parents[2] / "kb")
    parser.add_argument("--dry-run", action="store_true", help="only reports, doesn't write")
    parser.add_argument(
        "--fake-embeddings",
        action="store_true",
        help="use the deterministic embedder (no network), for local testing",
    )
    args = parser.parse_args()

    return asyncio.run(ingest(args.kb_dir, dry_run=args.dry_run, use_fake=args.fake_embeddings))


if __name__ == "__main__":
    sys.exit(main())
