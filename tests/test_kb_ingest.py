"""Tests for the user-upload ingest pipeline (``genbi.kb_ingest``).

Pure-Python: ``embed`` and ``get_engine`` are monkeypatched so the suite
doesn't need Postgres or Ollama. The early-return cases (unsupported
extension, oversize, no content, chunk cap, ollama down) never reach the
DB; the happy-path tests stub the engine with a ``MagicMock`` and assert
on the captured INSERT rows.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from genbi import kb_ingest
from genbi.kb import EMBED_DIM, KBEmbedError


@pytest.fixture
def _stub_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(_content: str) -> list[float]:
        return [0.0] * EMBED_DIM

    monkeypatch.setattr(kb_ingest, "embed", _fake)


@pytest.fixture
def _capture_engine(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Fake ``get_engine(role='kb_writer')`` so happy-path tests can run offline.

    Returns the inner ``conn`` mock so tests can inspect ``execute`` calls
    (the DELETE statement, the bulk INSERT rows). ``rowcount`` defaults to 0
    on the DELETE; tests can override before triggering ingest.
    """
    conn = MagicMock(name="conn")
    delete_result = MagicMock(name="delete_result")
    delete_result.rowcount = 0
    conn.execute.return_value = delete_result

    engine = MagicMock(name="engine")
    engine.begin.return_value.__enter__.return_value = conn

    monkeypatch.setattr(kb_ingest, "get_engine", lambda **_kwargs: engine)
    return conn


async def test_unsupported_extension() -> None:
    r = await kb_ingest.ingest_upload("notes.pdf", b"x")
    assert r.error and "unsupported" in r.error.lower()
    assert r.chunks_inserted == 0


async def test_file_too_large() -> None:
    big = b"## H\n\n" + b"x" * (kb_ingest.MAX_CONTENT_BYTES)
    r = await kb_ingest.ingest_upload("big.md", big)
    assert r.error and "too large" in r.error.lower()


async def test_empty_md() -> None:
    r = await kb_ingest.ingest_upload("empty.md", b"")
    assert r.error == "no content"


async def test_md_without_h2() -> None:
    r = await kb_ingest.ingest_upload("flat.md", b"just some prose with no headings\n")
    assert r.error == "no content"


async def test_chunk_count_cap() -> None:
    body = "\n\n".join(f"## Sec {i}\n\nbody {i}" for i in range(kb_ingest.MAX_CHUNKS + 1))
    r = await kb_ingest.ingest_upload("many.md", body.encode("utf-8"))
    assert r.error and "too many sections" in r.error.lower()


async def test_ollama_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(_content: str) -> list[float]:
        raise KBEmbedError("connection refused")

    monkeypatch.setattr(kb_ingest, "embed", _boom)
    r = await kb_ingest.ingest_upload("g.md", b"## A\n\nbody.\n")
    assert r.error and "ollama unavailable" in r.error.lower()
    assert r.chunks_inserted == 0


async def test_md_happy_path(_stub_embed: None, _capture_engine: MagicMock) -> None:
    md = b"## First\n\none.\n\n## Second\n\ntwo.\n"
    r = await kb_ingest.ingest_upload("g.md", md)
    assert r.error is None
    assert r.chunks_inserted == 2
    assert r.chunks_replaced == 0
    assert r.ok
    # First execute is the DELETE; second is the bulk INSERT with the rows list.
    delete_call, insert_call = _capture_engine.execute.call_args_list
    assert delete_call.args[1] == {"doc": "g.md"}
    rows = insert_call.args[1]
    assert [row["section"] for row in rows] == ["First", "Second"]
    assert all(row["source"] == "upload" for row in rows)
    assert all(row["uploaded_at"] is not None for row in rows)


async def test_txt_paragraph_split(_stub_embed: None, _capture_engine: MagicMock) -> None:
    txt = b"first paragraph.\n\nsecond paragraph,\nwith two lines.\n"
    r = await kb_ingest.ingest_upload("notes.txt", txt)
    assert r.error is None
    assert r.chunks_inserted == 2
    rows = _capture_engine.execute.call_args_list[1].args[1]
    assert [row["section"] for row in rows] == ["Paragraph 1", "Paragraph 2"]
    assert "two lines" in rows[1]["body"]


async def test_replace_semantics(_stub_embed: None, _capture_engine: MagicMock) -> None:
    _capture_engine.execute.return_value.rowcount = 3
    r = await kb_ingest.ingest_upload("g.md", b"## A\n\nbody.\n")
    assert r.chunks_replaced == 3
    assert r.chunks_inserted == 1


async def test_filename_sanitized(_stub_embed: None, _capture_engine: MagicMock) -> None:
    r = await kb_ingest.ingest_upload("../../etc/passwd.md", b"## A\n\nbody.\n")
    assert r.filename == "passwd.md"
    delete_call = _capture_engine.execute.call_args_list[0]
    assert delete_call.args[1] == {"doc": "passwd.md"}
