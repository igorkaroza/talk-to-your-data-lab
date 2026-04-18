"""Streamlit chat UI for GenBI.

Runs the Claude Agent SDK on a persistent background thread via
:class:`genbi.ui.runtime.AgentRuntime` so the asyncio loop survives
Streamlit's per-interaction reruns. Turn events are drained from a
queue and rendered progressively; past turns replay from
``st.session_state['turns']`` without touching the agent.
"""

from __future__ import annotations

import queue
from typing import Any

import streamlit as st

from genbi.events import DoneEvent, TextEvent, ToolResultEvent, ToolUseEvent
from genbi.ui.render import (
    render_result_in_chat,
    render_tool_result,
    render_tool_use,
)
from genbi.ui.runtime import DONE_SENTINEL, AgentRuntime

st.set_page_config(page_title="GenBI", layout="wide")


@st.cache_resource
def get_runtime() -> AgentRuntime:
    return AgentRuntime()


def _render_event(event: Any, *, turn_id: str, index: int) -> None:
    if isinstance(event, TextEvent):
        if event.text:
            st.markdown(event.text)
    elif isinstance(event, ToolUseEvent):
        render_tool_use(event)
    elif isinstance(event, ToolResultEvent):
        render_tool_result(event)
        if event.payload and not event.is_error:
            render_result_in_chat(event.payload, key_prefix=f"{turn_id}-{index}")
    elif isinstance(event, DoneEvent):
        if event.cost_usd is not None:
            st.caption(f"— {event.num_turns} turn(s), ${event.cost_usd:.4f}")


def _render_turn(turn: dict[str, Any]) -> None:
    with st.chat_message(turn["role"]):
        for i, event in enumerate(turn["events"]):
            _render_event(event, turn_id=turn["id"], index=i)


def _drain_turn(q: queue.Queue, turn_id: str) -> list:
    collected: list = []
    i = 0
    while True:
        item = q.get()
        if item is DONE_SENTINEL:
            break
        if isinstance(item, Exception):
            st.error(f"agent error: {item!r}")
            collected.append(TextEvent(text=f"[error: {item!r}]"))
            break
        collected.append(item)
        _render_event(item, turn_id=turn_id, index=i)
        i += 1
    return collected


def main() -> None:
    st.title("GenBI")
    st.caption("Ask about sales_orders or tickets — answers come with SQL, tables, or charts.")
    st.sidebar.header("agent trace")

    if "turns" not in st.session_state:
        st.session_state["turns"] = []

    for turn in st.session_state["turns"]:
        _render_turn(turn)

    prompt = st.chat_input("ask a question…")
    if not prompt:
        return

    user_id = f"u{len(st.session_state['turns'])}"
    user_turn = {"id": user_id, "role": "user", "events": [TextEvent(text=prompt)]}
    st.session_state["turns"].append(user_turn)
    _render_turn(user_turn)

    runtime = get_runtime()
    q = runtime.run_turn(prompt)
    assistant_id = f"a{len(st.session_state['turns'])}"
    with st.chat_message("assistant"):
        events = _drain_turn(q, assistant_id)
    st.session_state["turns"].append({"id": assistant_id, "role": "assistant", "events": events})


main()
