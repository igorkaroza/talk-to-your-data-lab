"""Ingest user-uploaded ``.md`` / ``.txt`` documents into ``kb_chunks``.

Called from the Streamlit "Knowledge base" sidebar tab. This is the
**only** non-seed write path against the database: it connects as
``genbi_kb_writer`` (``SELECT/INSERT/DELETE`` on ``kb_chunks`` only) so
the relaxation of "the app is read-only" stays scoped to one table.

User-uploaded rows are tagged ``source='upload'`` and coexist with
``source='corpus'`` rows from :mod:`genbi.seed_kb`. Re-uploading the same
filename replaces only the prior upload rows for that ``doc``; corpus rows
of the same name are untouched. Note that ``genbi.seed`` (the full reset)
still drops ``kb_chunks`` and wipes uploads — only ``seed_kb`` preserves
them.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from genbi.db import get_engine
from genbi.kb import EMBED_DIM, KBChunk, KBEmbedError, chunk_markdown_text, embed

MAX_CONTENT_BYTES = 1_000_000
MAX_CHUNKS = 100
INGEST_TIMEOUT_S = 60.0
SUPPORTED_SUFFIXES = frozenset({".md", ".txt"})


class IngestResult(BaseModel):
    filename: str
    chunks_inserted: int = 0
    chunks_replaced: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.chunks_inserted > 0


def _sanitize_filename(name: str) -> str:
    return PurePosixPath(name).name.replace("\x00", "")


def _chunk_txt(name: str, text_body: str) -> list[KBChunk]:
    """Paragraph-split a plain-text upload. Each paragraph is one chunk."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text_body) if p.strip()]
    return [
        KBChunk(doc=name, section=f"Paragraph {i + 1}", body=para)
        for i, para in enumerate(paragraphs)
    ]


async def _ingest(filename: str, content: bytes) -> IngestResult:  # noqa: PLR0911 — flat early returns map 1:1 to validation cases
    safe_name = _sanitize_filename(filename)
    suffix = PurePosixPath(safe_name).suffix.lower()

    if suffix not in SUPPORTED_SUFFIXES:
        return IngestResult(
            filename=safe_name, error=f"unsupported file type: {suffix or '(none)'}"
        )
    if len(content) > MAX_CONTENT_BYTES:
        return IngestResult(filename=safe_name, error="file too large (max 1MB)")

    text_body = content.decode("utf-8", errors="replace").strip()
    if not text_body:
        return IngestResult(filename=safe_name, error="no content")

    if suffix == ".md":
        chunks = chunk_markdown_text(safe_name, text_body)
    else:
        chunks = _chunk_txt(safe_name, text_body)

    if not chunks:
        return IngestResult(filename=safe_name, error="no content")
    if len(chunks) > MAX_CHUNKS:
        return IngestResult(filename=safe_name, error=f"too many sections (max {MAX_CHUNKS})")

    try:
        embeddings = [await embed(f"{c.section}\n\n{c.body}") for c in chunks]
    except KBEmbedError as err:
        return IngestResult(filename=safe_name, error=f"ollama unavailable: {err}")

    now = datetime.now(UTC)
    rows = [
        {
            "doc": c.doc,
            "section": c.section,
            "body": c.body,
            "embedding": vec,
            "source": "upload",
            "uploaded_at": now,
        }
        for c, vec in zip(chunks, embeddings, strict=True)
    ]
    insert = text(
        "INSERT INTO kb_chunks (doc, section, body, embedding, source, uploaded_at) "
        "VALUES (:doc, :section, :body, :embedding, :source, :uploaded_at)"
    ).bindparams(bindparam("embedding", type_=Vector(EMBED_DIM)))

    try:
        with get_engine(role="kb_writer").begin() as conn:
            deleted = conn.execute(
                text("DELETE FROM kb_chunks WHERE source = 'upload' AND doc = :doc"),
                {"doc": safe_name},
            ).rowcount
            conn.execute(insert, rows)
    except SQLAlchemyError as err:
        return IngestResult(filename=safe_name, error=f"db error: {type(err).__name__}")

    return IngestResult(
        filename=safe_name,
        chunks_inserted=len(rows),
        chunks_replaced=int(deleted or 0),
    )


async def ingest_upload(filename: str, content: bytes) -> IngestResult:
    """Chunk + embed + insert a user-uploaded document.

    Returns an :class:`IngestResult` with ``error`` populated on any failure
    (unsupported type, oversize, empty, no chunks, Ollama down, db error,
    or timeout) — never raises. The whole pipeline is wrapped in a
    ``INGEST_TIMEOUT_S`` budget so a stuck Ollama can't hang the UI.
    """
    safe_name = _sanitize_filename(filename)
    try:
        return await asyncio.wait_for(_ingest(filename, content), timeout=INGEST_TIMEOUT_S)
    except TimeoutError:
        return IngestResult(filename=safe_name, error="ingest timed out")


class UploadInfo(BaseModel):
    doc: str
    chunks: int
    uploaded_at: datetime | None


def list_uploads() -> list[UploadInfo]:
    """Return one entry per user-uploaded ``doc`` for the sidebar listing.

    Reads via the default ``genbi_reader`` engine — this is a SELECT-only
    helper. Returns an empty list (not None) on a connection error so the
    UI can render "no uploads yet" without raising.
    """
    stmt = text(
        """
        SELECT doc, COUNT(*) AS chunks, MAX(uploaded_at) AS uploaded_at
          FROM kb_chunks
         WHERE source = 'upload'
         GROUP BY doc
         ORDER BY MAX(uploaded_at) DESC NULLS LAST, doc
        """
    )
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(stmt).all()
    except SQLAlchemyError:
        return []
    return [UploadInfo(doc=doc, chunks=int(chunks), uploaded_at=ts) for (doc, chunks, ts) in rows]
