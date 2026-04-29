"""Tests for the KB module and the ``kb_search`` tool.

The chunking test is pure-Python and runs anywhere. The retrieval tests
need both Postgres (with the ``kb_chunks`` table populated) and a
reachable Ollama; they skip cleanly when either is unavailable so CI
without Ollama still passes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from genbi import kb
from genbi.db import get_engine
from genbi.tools import KB_K_MAX, kb_search


def _payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def test_chunk_markdown_splits_on_h2(tmp_path: Path) -> None:
    md = tmp_path / "demo.md"
    md.write_text(
        "# Title to ignore\n\n"
        "Preamble that should be dropped.\n\n"
        "## First section\n\n"
        "Body of first section.\n\n"
        "## Second section\n\n"
        "Body of second section\nwith two lines.\n",
        encoding="utf-8",
    )
    chunks = kb.chunk_markdown(md)
    assert [c.section for c in chunks] == ["First section", "Second section"]
    assert chunks[0].doc == "demo.md"
    assert chunks[0].body == "Body of first section."
    assert "two lines" in chunks[1].body


def test_chunk_markdown_skips_empty_sections(tmp_path: Path) -> None:
    md = tmp_path / "thin.md"
    md.write_text("## Empty\n\n## Real\n\nBody.\n", encoding="utf-8")
    chunks = kb.chunk_markdown(md)
    assert [c.section for c in chunks] == ["Real"]


def test_chunk_markdown_text_matches_path_variant(tmp_path: Path) -> None:
    body = "# Title\n\n## A\n\nbody-a.\n\n## B\n\nbody-b.\n"
    md = tmp_path / "demo.md"
    md.write_text(body, encoding="utf-8")
    from_path = kb.chunk_markdown(md)
    from_text = kb.chunk_markdown_text("demo.md", body)
    assert from_path == from_text


@pytest.fixture(scope="module")
def _kb_corpus_seeded() -> None:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM kb_chunks")).scalar() or 0
    except OperationalError as err:
        pytest.skip(f"Postgres not reachable — run `docker compose up -d postgres`. ({err})")
    except Exception as err:  # noqa: BLE001 — pre-flight, want any error to skip cleanly
        pytest.skip(f"kb_chunks not queryable — run `python -m genbi.seed`. ({err})")
    if count == 0:
        pytest.skip("kb_chunks is empty — run `python -m genbi.seed_kb`.")


def _ollama_reachable() -> bool:
    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        httpx.get(f"{base}/api/tags", timeout=1.0).raise_for_status()
    except (httpx.HTTPError, OSError):
        return False
    return True


async def test_kb_search_happy_path(_kb_corpus_seeded: None) -> None:
    if not _ollama_reachable():
        pytest.skip("Ollama not reachable on OLLAMA_BASE_URL.")
    result = await kb_search.handler({"query": "what counts as revenue?"})
    payload = _payload(result)
    assert "error" not in payload
    assert payload["snippet_count"] >= 1
    top = payload["snippets"][0]
    assert {"doc", "section", "body", "score"}.issubset(top)
    assert top["body"]
    assert isinstance(top["score"], float)


async def test_kb_search_handles_ollama_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)
    result = await kb_search.handler({"query": "anything"})
    payload = _payload(result)
    assert payload["snippet_count"] == 0
    assert payload["snippets"] == []
    assert "ollama unavailable" in payload["error"].lower()


async def test_kb_search_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        await kb_search.handler({"query": "   "})


async def test_kb_search_clamps_k(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}

    async def _fake_search(query: str, k: int) -> list[dict]:
        captured["k"] = k
        return []

    monkeypatch.setattr(kb, "search", _fake_search)
    await kb_search.handler({"query": "hi", "k": 999})
    assert captured["k"] == KB_K_MAX
    await kb_search.handler({"query": "hi", "k": 0})
    assert captured["k"] == 1
