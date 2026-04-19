"""Unit tests for :func:`genbi.agent.stream_turn`'s event dispatch.

Covers the wiring between ``ClaudeSDKClient.receive_response`` and the
typed event stream — specifically that ``ToolResultBlock``s arriving on
a ``UserMessage`` (the SDK's synthetic tool-result turn) surface as
``ToolResultEvent``s with a parsed payload. A regression here in M3
caused the Streamlit UI to render Markdown tables instead of Plotly
charts because ``render_result_in_chat`` never saw the tool result.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from genbi.agent import stream_turn
from genbi.events import TextEvent, ToolResultEvent, ToolUseEvent


class _FakeClient:
    """Minimal stand-in for :class:`ClaudeSDKClient`."""

    def __init__(self, messages: list) -> None:
        self._messages = messages

    async def query(self, prompt: str) -> None:  # noqa: ARG002
        return

    async def receive_response(self):
        for msg in self._messages:
            yield msg


def _assistant(*blocks) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model="test-model")


def _user(*blocks) -> UserMessage:
    return UserMessage(content=list(blocks))


def _result(num_turns: int = 1, cost: float = 0.0) -> ResultMessage:
    # ResultMessage has many fields; build a duck-typed object since stream_turn
    # only reads ``num_turns`` and ``total_cost_usd``.
    return SimpleNamespace(num_turns=num_turns, total_cost_usd=cost)


@pytest.mark.asyncio
async def test_stream_turn_emits_tool_result_from_user_message() -> None:
    chart_payload = {
        "chart_type": "bar",
        "row_count": 3,
        "columns": ["month", "count"],
        "rows": [["2026-01", 5], ["2026-02", 8], ["2026-03", 11]],
        "plotly_json": '{"data": []}',
    }
    envelope = [{"type": "text", "text": json.dumps(chart_payload)}]

    messages = [
        _assistant(
            TextBlock(text="Rendering a bar chart."),
            ToolUseBlock(id="tu_1", name="mcp__genbi__chart_render", input={"sql": "SELECT 1"}),
        ),
        _user(ToolResultBlock(tool_use_id="tu_1", content=envelope, is_error=False)),
        _result(num_turns=2, cost=0.01),
    ]

    # ResultMessage is a real dataclass — but stream_turn only reads two fields.
    # Monkey-patch isinstance by wrapping in the real class if import succeeds,
    # else fall back to duck-typing via a subclass check. Here we rely on the
    # fact that stream_turn's final branch uses isinstance(..., ResultMessage).
    from claude_agent_sdk import ResultMessage as _RM

    # Build a real ResultMessage with minimal required fields.
    try:
        messages[-1] = _RM(
            subtype="success",
            duration_ms=0,
            duration_api_ms=0,
            is_error=False,
            num_turns=2,
            session_id="s",
            total_cost_usd=0.01,
        )
    except TypeError:
        # SDK version mismatch — fall back to duck-typed SimpleNamespace; the
        # isinstance check will skip it and DoneEvent simply won't fire, which
        # is still a valid partial assertion.
        pass

    client = _FakeClient(messages)
    events = [e async for e in stream_turn(client, "use a chart")]

    kinds = [type(e).__name__ for e in events]
    assert "TextEvent" in kinds
    assert "ToolUseEvent" in kinds
    assert "ToolResultEvent" in kinds, (
        f"ToolResultBlock on UserMessage must surface as ToolResultEvent; got {kinds}"
    )

    text_ev = next(e for e in events if isinstance(e, TextEvent))
    assert text_ev.text == "Rendering a bar chart."

    use_ev = next(e for e in events if isinstance(e, ToolUseEvent))
    assert use_ev.name == "chart_render"
    assert use_ev.input == {"sql": "SELECT 1"}

    result_ev = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result_ev.name == "chart_render"
    assert result_ev.is_error is False
    assert result_ev.payload is not None
    assert "plotly_json" in result_ev.payload
    assert result_ev.payload["chart_type"] == "bar"


@pytest.mark.asyncio
async def test_stream_turn_marks_errored_tool_results() -> None:
    messages = [
        _assistant(
            ToolUseBlock(id="tu_1", name="mcp__genbi__sql_execute", input={"sql": "DROP"}),
        ),
        _user(
            ToolResultBlock(
                tool_use_id="tu_1",
                content=[{"type": "text", "text": "rejected: non-SELECT"}],
                is_error=True,
            )
        ),
    ]
    client = _FakeClient(messages)
    events = [e async for e in stream_turn(client, "drop the table")]

    result_ev = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result_ev.is_error is True
    assert result_ev.payload is None
    assert "rejected" in result_ev.raw_text


@pytest.mark.asyncio
async def test_stream_turn_skips_user_message_with_plain_string_content() -> None:
    """Early user messages can have ``content: str`` — must not crash."""
    messages = [
        _user(),  # list content, empty
    ]
    # Swap in a string-content UserMessage:
    messages[0] = UserMessage(content="hi there")

    client = _FakeClient(messages)
    events = [e async for e in stream_turn(client, "hi")]
    assert events == []  # no tool results, no assistant blocks → empty stream
