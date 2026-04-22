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
import streamlit.components.v1 as components

import genbi.ui.render as _render_mod

importlib.reload(_render_mod)

from genbi.agent import format_done
from genbi.events import DoneEvent, TextEvent, ToolResultEvent, ToolUseEvent
from genbi.ui.render import (
    render_ask_user_form,
    render_result_in_chat,
    render_tool_result,
    render_tool_use,
)
from genbi.ui.runtime import DONE_SENTINEL, AgentRuntime

st.set_page_config(page_title="GenBI", layout="wide", initial_sidebar_state="collapsed")

HERO_QUESTIONS = [
    "Show me the top customers",
    "How many high-priority tickets closed this year grouped by month?",
    "Show revenue by region as a bar chart",
    "What are the top 5 products by total revenue this year?",
    "Plot tickets opened per day over the last 30 days as a line chart",
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
  /* Shrink the bottom padding on empty-state so the hero chips sit flush
     above the sticky chat input. The 9rem baseline is only needed once
     real turn content could be hidden behind the chat bar. */
  padding-bottom: 3rem !important;
}
[data-testid="stMainBlockContainer"] > div:first-child,
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {
  flex: 1 1 auto !important;
  display: flex !important;
  flex-direction: column !important;
}
/* Push the wrapper that contains the hero-buttons keyed block to the
   bottom of its flex-column parent, so the chips sit flush above the
   sticky chat input. Using :has() so we don't have to hardcode the DOM
   depth — it matches the nearest wrapper that contains
   .st-key-hero-buttons. Streamlit's layout wraps keyed containers in
   stLayoutWrapper, with stElementContainer / stVerticalBlockBorderWrapper
   used in older layouts; match all three. Baseline 2023. */
[data-testid="stMainBlockContainer"]
  > [data-testid="stVerticalBlock"]
  > [data-testid="stLayoutWrapper"]:has(div.st-key-hero-buttons),
[data-testid="stMainBlockContainer"]
  > [data-testid="stVerticalBlock"]
  > [data-testid="stElementContainer"]:has(div.st-key-hero-buttons),
[data-testid="stMainBlockContainer"]
  > [data-testid="stVerticalBlock"]
  > [data-testid="stVerticalBlockBorderWrapper"]:has(div.st-key-hero-buttons) {
  margin-top: auto !important;
}
</style>
"""

# Drawer-handle toggle for the sidebar tool-call log. Streamlit's native
# expand button lives inside `stHeader` — which `_PAGE_CSS` hides — so
# once the user collapses the sidebar there's no way back. Inject a
# left-edge vertical pull tab into the parent document via a components
# iframe: same-origin lets us reach `window.parent.document`, and a
# 400ms setInterval keeps the tab's count and visibility in sync with
# the sidebar's `aria-expanded` state across reruns. (Tried a
# MutationObserver first; observing doc.body for all mutations cascaded —
# each style write on the pull element re-triggered the observer.)
_TOOLS_DRAWER_JS = """
<script>
(() => {
  const doc = window.parent.document;

  if (!doc.getElementById('genbi-tools-pull-style')) {
    const styleEl = doc.createElement('style');
    styleEl.id = 'genbi-tools-pull-style';
    styleEl.textContent = `
      #genbi-tools-pull {
        position: fixed;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        z-index: 9999;
        writing-mode: vertical-rl;
        padding: 0.9rem 0.4rem;
        background: rgba(49, 51, 63, 0.88);
        color: #fff;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        border-radius: 0 0.4rem 0.4rem 0;
        cursor: pointer;
        user-select: none;
        box-shadow: 2px 0 6px rgba(0,0,0,0.14);
        transition: background 150ms;
        display: none;
        align-items: center;
        gap: 0.55rem;
      }
      #genbi-tools-pull:hover { background: rgba(49, 51, 63, 1); }
      #genbi-tools-pull .count {
        writing-mode: horizontal-tb;
        background: #fff;
        color: rgb(49, 51, 63);
        border-radius: 999px;
        padding: 1px 7px;
        font-size: 0.66rem;
        font-weight: 700;
        display: inline-block;
      }
    `;
    doc.head.appendChild(styleEl);
  }

  let pull = doc.getElementById('genbi-tools-pull');
  if (!pull) {
    pull = doc.createElement('div');
    pull.id = 'genbi-tools-pull';
    pull.title = 'Show tool call log';
    pull.innerHTML = 'tool calls<span class="count">0</span>';
    pull.addEventListener('click', () => {
      const btn = doc.querySelector('[data-testid="stExpandSidebarButton"]')
               || doc.querySelector('[data-testid="stSidebarCollapseButton"] button');
      if (btn) btn.click();
    });
    doc.body.appendChild(pull);
  }

  const refresh = () => {
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    const count = doc.querySelectorAll(
      '[data-testid="stSidebar"] [data-testid="stExpander"]'
    ).length;
    const countEl = pull.querySelector('.count');
    if (countEl && countEl.textContent !== String(count)) {
      countEl.textContent = String(count);
    }
    // aria-expanded is the canonical sidebar state. offsetWidth is unreliable —
    // the outer stSidebar element can report 0 while its inner content is visible.
    const collapsed = !sidebar || sidebar.getAttribute('aria-expanded') !== 'true';
    const next = count > 0 && collapsed ? 'inline-flex' : 'none';
    if (pull.style.display !== next) pull.style.display = next;
  };

  // MutationObserver on doc.body cascades — every pull.style.display write
  // triggers the observer that called it. A 400ms poll is cheap, bounded,
  // and stays in sync across Streamlit's per-interaction reruns.
  if (doc.__genbiToolsTick__) clearInterval(doc.__genbiToolsTick__);
  doc.__genbiToolsTick__ = setInterval(refresh, 400);
  refresh();
})();
</script>
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
                if event.payload.get("pending"):
                    chosen = render_ask_user_form(
                        event.payload,
                        key_prefix=f"{turn_id}-{index}",
                        interactive=explain_enabled,
                    )
                    if chosen is not None:
                        st.session_state["pending_prompt"] = chosen
                        st.rerun()
                else:
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
    elif isinstance(event, DoneEvent):
        line = format_done(event)
        if line is not None:
            st.caption(line)


def _render_turn(turn: dict[str, Any], *, explain_enabled: bool = False) -> None:
    # Wrap each turn in a keyed container so Streamlit reconciles the same
    # DOM subtree across reruns instead of leaving stale elements behind
    # while a new turn is still draining. Without this, the DoneEvent
    # caption from a past turn is re-emitted as a duplicate node during
    # the rerun that kicks off the next response, and Streamlit only
    # removes the duplicate once the drain finishes — which shows up as a
    # visibly duplicated meta line while the new request is in-flight.
    with st.container(key=f"turn-{turn['id']}"):
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
    components.html(_TOOLS_DRAWER_JS, height=0)

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

    chat_prompt = st.chat_input("Ask a question...")
    if chat_prompt:
        st.session_state["pending_prompt"] = chat_prompt
        st.rerun()


main()
