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
from genbi.events import (
    DoneEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from genbi.kb_ingest import list_uploads
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
    "Show revenue from our VIP customers this quarter as a bar chart",
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
  justify-content: flex-end !important;
  padding: 0.5rem 1rem 0 !important;
}
/* Hide the native sidebar collapse arrow — the "TOOL CALLS" pull-tab is */
/* the single toggle for the drawer. The button itself is still in the  */
/* DOM so the JS click handler can fire it programmatically.            */
[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] {
  display: none !important;
}
/* KB panel — fixed-position right drawer that slides in when            */
/* body.kb-open is set by _KB_DRAWER_JS. Mirrors the native left sidebar */
/* visually but lives independently so its toggle is a separate button.  */
div.st-key-kb-panel {
  position: fixed !important;
  top: 0 !important;
  right: 0 !important;
  bottom: 0 !important;
  width: 320px !important;
  background: rgb(240, 242, 246) !important;
  padding: 1.25rem 1rem 1.5rem 1rem !important;
  z-index: 9998 !important;
  transform: translateX(100%) !important;
  transition: transform 200ms ease !important;
  overflow-y: auto !important;
  box-shadow: -2px 0 6px rgba(0,0,0,0.08) !important;
  box-sizing: border-box !important;
}
body.kb-open div.st-key-kb-panel {
  transform: translateX(0) !important;
}
div.st-key-kb-panel .kb-panel-header {
  font-size: 1.25rem;
  font-weight: 600;
  line-height: 1;
  padding: 0.75rem 0 1rem 0;
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

# Drawer-handle toggle for the right-edge KB panel. Streamlit doesn't
# expose a second native sidebar, so the panel is a regular st.container
# pinned via CSS (`div.st-key-kb-panel`) and toggled by adding/removing
# `body.kb-open`. The pull-tab follows the panel: closed → right:0,
# open → right:320px (just outside the panel's left edge). 400ms poll
# keeps the count badge in sync with whatever kb_search expanders the
# render path has appended.
_KB_DRAWER_JS = """
<script>
(() => {
  const doc = window.parent.document;

  if (!doc.getElementById('genbi-kb-pull-style')) {
    const styleEl = doc.createElement('style');
    styleEl.id = 'genbi-kb-pull-style';
    styleEl.textContent = `
      #genbi-kb-pull {
        position: fixed;
        right: 0;
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
        border-radius: 0.4rem 0 0 0.4rem;
        cursor: pointer;
        user-select: none;
        box-shadow: -2px 0 6px rgba(0,0,0,0.14);
        transition: background 150ms, right 200ms ease;
        display: inline-flex;
        align-items: center;
        gap: 0.55rem;
      }
      #genbi-kb-pull:hover { background: rgba(49, 51, 63, 1); }
      #genbi-kb-pull .count {
        writing-mode: horizontal-tb;
        background: #fff;
        color: rgb(49, 51, 63);
        border-radius: 999px;
        padding: 1px 7px;
        font-size: 0.66rem;
        font-weight: 700;
        display: inline-block;
      }
      body.kb-open #genbi-kb-pull {
        right: 320px;
        border-radius: 0.4rem 0 0 0.4rem;
      }
    `;
    doc.head.appendChild(styleEl);
  }

  let pull = doc.getElementById('genbi-kb-pull');
  if (!pull) {
    pull = doc.createElement('div');
    pull.id = 'genbi-kb-pull';
    pull.title = 'Toggle knowledge base';
    pull.innerHTML = 'knowledge base<span class="count">0</span>';
    pull.addEventListener('click', () => {
      doc.body.classList.toggle('kb-open');
    });
    doc.body.appendChild(pull);
  }

  // Pull-tab is always visible — KB is a peripheral resource the user
  // may want to consult before any kb_search has fired. The badge shows
  // the snippet count once the agent has populated the panel.
  const refresh = () => {
    const count = doc.querySelectorAll(
      'div.st-key-kb-panel [data-testid="stExpander"]'
    ).length;
    const countEl = pull.querySelector('.count');
    if (countEl && countEl.textContent !== String(count)) {
      countEl.textContent = String(count);
    }
  };

  if (doc.__genbiKbTick__) clearInterval(doc.__genbiKbTick__);
  doc.__genbiKbTick__ = setInterval(refresh, 400);
  refresh();
})();
</script>
"""

# Drawer-handle toggle for the sidebar tool-call log. Streamlit's native
# expand button lives inside `stHeader` — which `_PAGE_CSS` hides — so
# without this pull-tab there's no affordance to open or close the
# sidebar at all. The tab is always visible and doubles as a toggle:
# clicking it opens the drawer when collapsed and closes it when open,
# so the user can dismiss the tools panel with the same button they used
# to open it. When open, the tab slides to the sidebar's right edge so
# it doesn't overlap the panel. Injected into the parent document via a
# components iframe (same-origin → `window.parent.document`); a 400ms
# setInterval keeps badge count and tab position in sync with the
# sidebar's `aria-expanded` state across reruns. (Tried a
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
        transition: background 150ms, left 200ms ease;
        display: inline-flex;
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
    doc.body.appendChild(pull);
  }
  // Re-bind the click handler every iframe run. components.html re-renders
  // on each Streamlit rerun, which unloads the prior iframe; closures
  // captured by addEventListener in dead iframes go neutered in Chrome,
  // so the click silently no-ops. Reassigning onclick from the live
  // iframe context restores it. Pick the button based on actual state so
  // the pull-tab toggles cleanly — clicking expandBtn while expanded is
  // a no-op in some Streamlit builds.
  pull.onclick = () => {
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    const isOpen = sidebar?.getAttribute('aria-expanded') === 'true';
    const btn = isOpen
      ? doc.querySelector('[data-testid="stSidebarCollapseButton"] button')
      : doc.querySelector('[data-testid="stExpandSidebarButton"]');
    if (btn) btn.click();
  };

  const refresh = () => {
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    const count = doc.querySelectorAll(
      '[data-testid="stSidebar"] [data-testid="stExpander"]'
    ).length;
    const countEl = pull.querySelector('.count');
    if (countEl && countEl.textContent !== String(count)) {
      countEl.textContent = String(count);
    }
    // Pull-tab is always visible — it doubles as the toggle, so the user
    // can dismiss the drawer with the same button they used to open it.
    // When the sidebar is open, slide the tab to its right edge so it
    // doesn't sit on top of sidebar content. aria-expanded is the
    // canonical sidebar state (offsetWidth is unreliable — the outer
    // stSidebar element can report 0 while its inner content is visible).
    const isOpen = sidebar?.getAttribute('aria-expanded') === 'true';
    const left = isOpen ? `${Math.round(sidebar.getBoundingClientRect().width)}px` : '0px';
    if (pull.style.left !== left) pull.style.left = left;
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


def _render_event(  # noqa: PLR0912 — flat dispatch over event types is clearer than splitting
    event: Any,
    *,
    turn_id: str,
    index: int,
    state: dict[str, Any],
    explain_enabled: bool = False,
    tools_target: Any = None,
) -> None:
    """Render one event. Intermediate tool results are cleared when a later
    tool result arrives so only the turn's final chart/table stays in chat.
    Tool-trace expanders go into ``tools_target`` (the left sidebar) when
    provided; chart/table results stay in the main chat area.

    When ``explain_enabled`` is True (latest assistant turn), an "Explain
    this" button renders under the final result and queues a follow-up
    prompt on click.
    """
    if isinstance(event, TextEvent):
        if event.text:
            st.markdown(event.text)
    elif isinstance(event, ToolUseEvent):
        if tools_target is not None:
            with tools_target:
                render_tool_use(event)
        else:
            render_tool_use(event)
    elif isinstance(event, ToolResultEvent):
        if tools_target is not None:
            with tools_target:
                render_tool_result(event)
        else:
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


def _render_turn(
    turn: dict[str, Any],
    *,
    explain_enabled: bool = False,
    tools_target: Any = None,
) -> None:
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
                    tools_target=tools_target,
                )


def _drain_turn(q: queue.Queue, turn_id: str, *, tools_target: Any = None) -> list:
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
            _render_event(
                item,
                turn_id=turn_id,
                index=i,
                state=state,
                explain_enabled=True,
                tools_target=tools_target,
            )
            i += 1
    finally:
        stop_style_slot.empty()
    return collected


def _latest_assistant_index(turns: list[dict[str, Any]]) -> int | None:
    for i in range(len(turns) - 1, -1, -1):
        if turns[i]["role"] == "assistant":
            return i
    return None


def _render_kb_panel() -> None:
    """Right-side KB drawer body: upload + recent results + currently uploaded list."""
    bump = st.session_state.get("kb_uploader_bump", 0)
    # Streamlit's normalize_upload_file_type lowercases extensions and the
    # server-side enforce_filename_restriction lowercases the filename before
    # matching, so ["md", "txt"] already accepts FOO.MD / FOO.MD case-blind.
    files = st.file_uploader(
        "Upload .md or .txt",
        type=["md", "txt"],
        accept_multiple_files=True,
        key=f"kb_uploader_{bump}",
        label_visibility="collapsed",
    )
    # Auto-ingest as soon as files are selected. Streamlit reruns on upload,
    # so we land here with `files` populated, ingest, then bump the uploader
    # key to clear the input — same pattern the old "Add" button used.
    if files:
        with st.spinner("Ingesting..."):
            results = get_runtime().ingest_files(files)
        st.session_state["kb_last_results"] = [r.model_dump() for r in results]
        st.session_state["kb_uploader_bump"] = bump + 1
        st.rerun()

    # Successful uploads show up in the "Currently uploaded" list below;
    # only surface errors here since they never make it into list_uploads().
    last = st.session_state.get("kb_last_results") or []
    for r in last:
        if r.get("error"):
            st.error(f"**{r['filename']}** — {r['error']}", icon="⚠️")

    st.divider()
    st.caption("Currently uploaded")
    uploads = list_uploads()
    if not uploads:
        st.caption("_No uploads yet._")
        return
    for info in uploads:
        when = info.uploaded_at.strftime("%Y-%m-%d %H:%M") if info.uploaded_at else "?"
        st.markdown(f"**{info.doc}** · {info.chunks} chunk(s) · {when}")


def _render_hero_buttons() -> None:
    with st.container(key="hero-buttons"):
        for i, q in enumerate(HERO_QUESTIONS):
            if st.button(q, key=f"hero-{i}"):
                st.session_state["pending_prompt"] = q
                st.rerun()


def main() -> None:
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
    components.html(_TOOLS_DRAWER_JS, height=0)
    components.html(_KB_DRAWER_JS, height=0)

    # Right-side KB drawer. Hosts the upload UI and the "Currently uploaded"
    # list — pure KB management. All tool calls (including kb_search) render
    # in the left sidebar so the user has one consolidated tool-call log.
    with st.container(key="kb-panel"):
        st.markdown('<div class="kb-panel-header">Knowledge base</div>', unsafe_allow_html=True)
        _render_kb_panel()

    # Left sidebar is Tools-only. Use the sidebar itself as the render
    # target so tool-call expanders mount directly under the native
    # sidebar header. Drop an empty placeholder unconditionally so the
    # sidebar always exists in the DOM — Streamlit skips rendering an
    # empty sidebar entirely, which would leave the always-visible
    # pull-tab with nothing to toggle on first page load.
    with st.sidebar:
        st.empty()
    tools_target = st.sidebar

    if "turns" not in st.session_state:
        st.session_state["turns"] = []

    turns = st.session_state["turns"]
    if not turns and st.session_state.get("pending_prompt") is None:
        st.markdown(_EMPTY_STATE_CSS, unsafe_allow_html=True)
    latest_assistant = _latest_assistant_index(turns)
    for i, turn in enumerate(turns):
        _render_turn(
            turn,
            explain_enabled=(i == latest_assistant),
            tools_target=tools_target,
        )

    prompt = st.session_state.pop("pending_prompt", None)

    if prompt:
        user_id = f"u{len(turns)}"
        user_turn = {"id": user_id, "role": "user", "events": [TextEvent(text=prompt)]}
        turns.append(user_turn)
        _render_turn(user_turn, tools_target=tools_target)

        runtime = get_runtime()
        q = runtime.run_turn(prompt)
        assistant_id = f"a{len(turns)}"
        with st.chat_message("assistant"):
            events = _drain_turn(q, assistant_id, tools_target=tools_target)
        turns.append({"id": assistant_id, "role": "assistant", "events": events})

    if not turns:
        _render_hero_buttons()

    chat_prompt = st.chat_input("Ask a question...")
    if chat_prompt:
        st.session_state["pending_prompt"] = chat_prompt
        st.rerun()


main()
