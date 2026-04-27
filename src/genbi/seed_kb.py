"""Populate the ``kb_chunks`` RAG table from the markdown corpus in ``kb/``.

Run with ``uv run python -m genbi.seed_kb`` after ``genbi.seed`` has
created the table. Requires a running Ollama with the embedding model
pulled (``ollama pull nomic-embed-text``). Idempotent — truncates and
reinserts on every run.

Runs as ``genbi_admin``. Never call from app or agent code; this is the
only writer to ``kb_chunks``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv
from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text

from genbi.db import get_engine
from genbi.kb import EMBED_DIM, chunk_markdown, embed

load_dotenv()

KB_DIR = Path(__file__).resolve().parents[2] / "kb"


async def main() -> None:
    if not KB_DIR.is_dir():
        raise SystemExit(f"[seed_kb] {KB_DIR} not found — nothing to seed.")

    md_files = sorted(KB_DIR.glob("*.md"))
    if not md_files:
        raise SystemExit(f"[seed_kb] no .md files under {KB_DIR}.")

    rows: list[dict] = []
    for path in md_files:
        chunks = chunk_markdown(path)
        print(f"[seed_kb] {path.name}: {len(chunks)} chunk(s)")
        for chunk in chunks:
            vector = await embed(f"{chunk.section}\n\n{chunk.body}")
            rows.append(
                {
                    "doc": chunk.doc,
                    "section": chunk.section,
                    "body": chunk.body,
                    "embedding": vector,
                }
            )

    if not rows:
        raise SystemExit("[seed_kb] corpus produced 0 chunks — check H2 headings.")

    insert = text(
        "INSERT INTO kb_chunks (doc, section, body, embedding) "
        "VALUES (:doc, :section, :body, :embedding)"
    ).bindparams(bindparam("embedding", type_=Vector(EMBED_DIM)))

    engine = get_engine(admin=True)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE kb_chunks RESTART IDENTITY"))
        conn.execute(insert, rows)

    print(f"[seed_kb] inserted {len(rows)} chunk(s) into kb_chunks. done.")


if __name__ == "__main__":
    asyncio.run(main())
