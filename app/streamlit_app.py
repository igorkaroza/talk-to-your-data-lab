"""Streamlit chat UI for GenBI.

Runs the Claude Agent SDK on a persistent background thread via
:class:`genbi.ui.runtime.AgentRuntime` so the asyncio loop survives
Streamlit's per-interaction reruns. Turn events are drained from a
queue and rendered progressively; past turns replay from
``st.session_state['turns']`` without touching the agent.
"""

from __future__ import annotations

import importlib
import queue
from typing import Any

import streamlit as st

import genbi.ui.render as _render_mod
importlib.reload(_render_mod)

from genbi.events import DoneEvent, TextEvent, ToolResultEvent, ToolUseEvent
from genbi.ui.render import (
    render_result_in_chat,
    render_tool_result,
    render_tool_use,
)
from genbi.ui.runtime import DONE_SENTINEL, AgentRuntime

st.set_page_config(page_title="GenBI", layout="wide")

HERO_QUESTIONS = [
    "How many high-priority tickets closed this year grouped by month? Use a chart.",
    "Show revenue by region as a bar chart.",
    "What are the top 5 products by total revenue this year?",
    "Plot tickets opened per day over the last 30 days as a line chart.",
    "What's the average order amount by customer region?",
]

EXPLAIN_PROMPT = (
    "Explain the chart or table you just rendered in 2-3 sentences. "
    "Call out the headline insight and one caveat (data range, sample size, "
    "or anything a reader should be wary of). Do not re-run any SQL."
)

_STOP_BUTTON_CSS = """
<style>
[data-testid="stChatInput"] button[data-testid="stChatInputSubmitButton"] svg,
[data-testid="stChatInput"] button[kind="chatInputSubmit"] svg {
  display: none !important;
}
[data-testid="stChatInput"] button[data-testid="stChatInputSubmitButton"]::before,
[data-testid="stChatInput"] button[kind="chatInputSubmit"]::before {
  content: "";
  display: block;
  width: 12px;
  height: 12px;
  background: currentColor;
  border-radius: 2px;
}
</style>
"""

_PAGE_CSS = """
<style>
[data-testid="stHeader"] {
  display: none !important;
}
[data-testid="stAppViewContainer"] {
  top: 0 !important;
}
[data-testid="stMainBlockContainer"] {
  padding-top: 1rem !important;
  padding-bottom: 9rem !important;
}
html body div.st-key-hero-buttons,
html body div.st-key-hero-buttons > div,
html body div.st-key-hero-buttons [data-testid="stVerticalBlock"] {
  display: flex !important;
  flex-direction: row !important;
  flex-wrap: wrap !important;
  gap: 0.5rem !important;
  justify-content: flex-start !important;
  align-items: flex-start !important;
  width: 100% !important;
}
html body div.st-key-hero-buttons [data-testid="stElementContainer"] {
  width: auto !important;
  max-width: 100% !important;
  flex: 0 0 auto !important;
  display: inline-flex !important;
}
html body div.st-key-hero-buttons .stButton,
html body div.st-key-hero-buttons .stButton > button {
  width: auto !important;
  display: inline-flex !important;
  white-space: normal !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  padding: 0.75rem 1rem !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarHeader"]::before {
  content: "Tool calls";
  font-size: 1.25rem;
  font-weight: 600;
  line-height: 1;
}
/* Inline the st.status spinner — drop border/background so "thinking…" */
/* sits flush with the robot avatar. Scoped via the st-key-thinking-   */
/* status container key so it does not flatten the "data" expander     */
/* inside chart results.                                               */
div.st-key-thinking-status {
  gap: 0 !important;
}
div.st-key-thinking-status [data-testid="stExpander"],
div.st-key-thinking-status [data-testid="stExpander"] > details {
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  padding: 0 !important;
}
div.st-key-thinking-status [data-testid="stExpander"] summary {
  padding: 0 !important;
  border: none !important;
  background: transparent !important;
  min-height: 32px;
  align-items: center;
}
</style>
"""

# Only applied on the empty-state (no turns, no queued prompt). The flex
# layout pushes the hero buttons to sit just above the sticky chat input.
# It conflicts with padding-bottom once real content is rendered, so we
# drop it as soon as the first turn lands.
_EMPTY_STATE_CSS = """
<style>
[data-testid="stMainBlockContainer"] {
  min-height: calc(100vh - 5rem) !important;
  display: flex !important;
  flex-direction: column !important;
}
[data-testid="stMainBlockContainer"] > div:first-child,
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {
  flex: 1 1 auto !important;
  display: flex !important;
  flex-direction: column !important;
  justify-content: flex-end !important;
}
</style>
"""


@st.cache_resource
def get_runtime() -> AgentRuntime:
    return AgentRuntime()


def _render_event(
    event: Any,
    *,
    turn_id: str,
    index: int,
    state: dict[str, Any],
    explain_enabled: bool = False,
) -> None:
    """Render one event. Intermediate tool results are cleared when a later
    tool result arrives so only the turn's final chart/table stays in chat.
    The sidebar trace (``render_tool_result``) still records every call.

    When ``explain_enabled`` is True (latest assistant turn), an "Explain
    this" button renders under the final result and queues a follow-up
    prompt on click.
    """
    if isinstance(event, TextEvent):
        if event.text:
            st.markdown(event.text)
    elif isinstance(event, ToolUseEvent):
        render_tool_use(event)
    elif isinstance(event, ToolResultEvent):
        render_tool_result(event)
        if event.payload and not event.is_error:
            prev = state.get("result_slot")
            if prev is not None:
                prev.empty()
            slot = st.empty()
            with slot.container():
                explain_key = f"{turn_id}-{index}-explain" if explain_enabled else None
                clicked = render_result_in_chat(
                    event.payload,
                    key_prefix=f"{turn_id}-{index}",
                    explain_key=explain_key,
                )
                if clicked:
                    st.session_state["pending_prompt"] = EXPLAIN_PROMPT
                    st.rerun()
            state["result_slot"] = slot
    elif isinstance(event, DoneEvent) and event.cost_usd is not None:
        st.caption(f"— {event.num_turns} turn(s), ${event.cost_usd:.4f}")


def _render_turn(turn: dict[str, Any], *, explain_enabled: bool = False) -> None:
    state: dict[str, Any] = {}
    with st.chat_message(turn["role"]):
        for i, event in enumerate(turn["events"]):
            _render_event(
                event,
                turn_id=turn["id"],
                index=i,
                state=state,
                explain_enabled=explain_enabled,
            )


def _drain_turn(q: queue.Queue, turn_id: str) -> list:
    collected: list = []
    state: dict[str, Any] = {}
    with st.container(key="thinking-status"):
        stop_style_slot = st.empty()
        stop_style_slot.markdown(_STOP_BUTTON_CSS, unsafe_allow_html=True)
        status_slot = st.empty()
        status = status_slot.status("thinking…", expanded=False)
    i = 0
    try:
        while True:
            item = q.get()
            if item is DONE_SENTINEL:
                status_slot.empty()
                break
            if isinstance(item, Exception):
                status.update(label=f"error: {item!r}", state="error")
                st.error(f"agent error: {item!r}")
                collected.append(TextEvent(text=f"[error: {item!r}]"))
                break
            if isinstance(item, ToolUseEvent):
                status.update(label=f"running {item.name}…")
            elif isinstance(item, ToolResultEvent):
                status.update(label=f"processing {item.name}…")
            collected.append(item)
            _render_event(item, turn_id=turn_id, index=i, state=state, explain_enabled=True)
            i += 1
    finally:
        stop_style_slot.empty()
    return collected


def _latest_assistant_index(turns: list[dict[str, Any]]) -> int | None:
    for i in range(len(turns) - 1, -1, -1):
        if turns[i]["role"] == "assistant":
            return i
    return None


def _render_hero_buttons() -> None:
    with st.container(key="hero-buttons"):
        for i, q in enumerate(HERO_QUESTIONS):
            if st.button(q, key=f"hero-{i}"):
                st.session_state["pending_prompt"] = q
                st.rerun()


def main() -> None:
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)

    if "turns" not in st.session_state:
        st.session_state["turns"] = []

    turns = st.session_state["turns"]
    if not turns and st.session_state.get("pending_prompt") is None:
        st.markdown(_EMPTY_STATE_CSS, unsafe_allow_html=True)
    latest_assistant = _latest_assistant_index(turns)
    for i, turn in enumerate(turns):
        _render_turn(turn, explain_enabled=(i == latest_assistant))

    prompt = st.session_state.pop("pending_prompt", None)

    if prompt:
        user_id = f"u{len(turns)}"
        user_turn = {"id": user_id, "role": "user", "events": [TextEvent(text=prompt)]}
        turns.append(user_turn)
        _render_turn(user_turn)

        runtime = get_runtime()
        q = runtime.run_turn(prompt)
        assistant_id = f"a{len(turns)}"
        with st.chat_message("assistant"):
            events = _drain_turn(q, assistant_id)
        turns.append({"id": assistant_id, "role": "assistant", "events": events})

    if not turns:
        _render_hero_buttons()

    chat_prompt = st.chat_input("ask a question…")
    if chat_prompt:
        st.session_state["pending_prompt"] = chat_prompt
        st.rerun()


main()
