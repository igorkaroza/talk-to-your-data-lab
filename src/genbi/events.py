"""Typed events emitted by :func:`genbi.agent.stream_turn`.

The CLI and the Streamlit UI both consume this stream, so a single
shape describes a turn: assistant text chunks, tool calls with their
inputs, tool results (parsed JSON when possible), and a terminal summary
carrying the turn count and dollar cost.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class TextEvent(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class ToolUseEvent(BaseModel):
    kind: Literal["tool_use"] = "tool_use"
    name: str
    input: dict[str, Any]


class ToolResultEvent(BaseModel):
    kind: Literal["tool_result"] = "tool_result"
    name: str
    payload: dict[str, Any] | None
    raw_text: str
    is_error: bool


class KBSearchResultEvent(BaseModel):
    """Specialized event for ``kb_search`` results so the UI can render the
    retrieved snippets with their scores. Emitted in addition to the regular
    :class:`ToolResultEvent` for that tool — the sidebar trace still records
    every call uniformly.
    """

    kind: Literal["kb_search_result"] = "kb_search_result"
    query: str
    snippets: list[dict[str, Any]]
    error: str | None = None


class DoneEvent(BaseModel):
    kind: Literal["done"] = "done"
    num_turns: int
    cost_usd: float | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None


TurnEvent = TextEvent | ToolUseEvent | ToolResultEvent | KBSearchResultEvent | DoneEvent
