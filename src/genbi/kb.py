"""Knowledge-base RAG: chunking, Ollama embedding client, vector retrieval.

The :func:`search` helper is what the ``kb_search`` ``@tool`` calls into;
:func:`embed` and :func:`chunk_markdown` are also reused by
:mod:`genbi.seed_kb` to build the corpus.

Embeddings come from a locally-running Ollama (`/api/embeddings`) so the
PoC has zero third-party dependencies. The model name and base URL are
read from ``OLLAMA_BASE_URL`` and ``OLLAMA_EMBED_MODEL``; fix them in
``.env`` before running ``python -m genbi.seed_kb``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import httpx
from pgvector.sqlalchemy import Vector
from pydantic import BaseModel
from sqlalchemy import bindparam, text

from genbi.db import get_engine

EMBED_DIM = 768
EMBED_TIMEOUT_S = 30.0


class KBEmbedError(RuntimeError):
    """Raised when the Ollama embedding endpoint is unreachable or errors."""


class KBChunk(BaseModel):
    doc: str
    section: str
    body: str


def _ollama_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def _ollama_model() -> str:
    return os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")


def chunk_markdown(path: Path) -> list[KBChunk]:
    """Split a markdown file on ``## `` H2 headings, one chunk per section.

    The file's H1 (if present) and any preamble before the first H2 are
    discarded — the H2 sections are the retrievable unit. ``doc`` is the
    file name (e.g. ``glossary.md``); ``section`` is the H2 heading text.
    """
    raw = path.read_text(encoding="utf-8")
    parts = re.split(r"^## (.+)$", raw, flags=re.MULTILINE)
    chunks: list[KBChunk] = []
    # Re.split with a capture group yields: [preamble, heading, body, heading, body, ...]
    for i in range(1, len(parts), 2):
        section = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if section and body:
            chunks.append(KBChunk(doc=path.name, section=section, body=body))
    return chunks


async def embed(content: str) -> list[float]:
    """Embed ``content`` via Ollama. Raises :class:`KBEmbedError` on failure."""
    url = f"{_ollama_url()}/api/embeddings"
    payload = {"model": _ollama_model(), "prompt": content}
    try:
        async with httpx.AsyncClient(timeout=EMBED_TIMEOUT_S) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as err:
        raise KBEmbedError(f"Ollama embed call failed: {err}") from err
    vector = data.get("embedding")
    if not isinstance(vector, list) or len(vector) != EMBED_DIM:
        raise KBEmbedError(
            f"Ollama returned {type(vector).__name__} of length "
            f"{len(vector) if isinstance(vector, list) else '?'}; expected {EMBED_DIM} floats"
        )
    return [float(x) for x in vector]


async def search(query: str, k: int) -> list[dict[str, Any]]:
    """Top-k cosine-similarity search over ``kb_chunks``.

    The SQL is hardcoded here, not LLM-generated, so it intentionally
    bypasses :mod:`genbi.safety`. Defense-in-depth still applies: the
    connection runs as ``genbi_reader`` (SELECT-only).
    """
    vector = await embed(query)
    stmt = text(
        """
        SELECT doc, section, body,
               1 - (embedding <=> :q) AS score
          FROM kb_chunks
         ORDER BY embedding <=> :q
         LIMIT :k
        """
    ).bindparams(bindparam("q", type_=Vector(EMBED_DIM)))
    with get_engine().connect() as conn:
        rows = conn.execute(stmt, {"q": vector, "k": int(k)}).all()
    return [
        {"doc": doc, "section": section, "body": body, "score": float(score)}
        for (doc, section, body, score) in rows
    ]
