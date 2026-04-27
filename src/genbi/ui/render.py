"""Pure Streamlit rendering helpers.

Kept free of agent plumbing so the app module stays short and the
functions can be reused by the live-drain path and the replay path
without duplication.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.io as pio
import streamlit as st

from genbi.events import KBSearchResultEvent, ToolResultEvent, ToolUseEvent


def result_to_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    """Build a DataFrame from a ``sql_execute`` / ``chart_render`` payload."""
    columns = payload.get("columns") or []
    rows = payload.get("rows") or []
    return pd.DataFrame(rows, columns=columns)


def render_tool_use(event: ToolUseEvent) -> None:
    """Add a tool-call entry to the sidebar trace."""
    with st.sidebar.expander(f"tool — {event.name}", expanded=False):
        sql = event.input.get("sql")
        if sql:
            st.code(sql, language="sql")
        if not sql or len(event.input) > 1:
            other = {k: v for k, v in event.input.items() if k != "sql"}
            if other:
                st.json(other)


def render_tool_result(event: ToolResultEvent) -> None:
    """Add a tool-result entry to the sidebar trace."""
    kind = "error" if event.is_error else "result"
    with st.sidebar.expander(f"{kind} — {event.name}", expanded=False):
        payload = event.payload
        if payload is None:
            st.code((event.raw_text or "(empty)")[:2000])
            return
        if payload.get("pending"):
            st.write(f"**ask_user:** {payload.get('question', '')}")
            for opt in payload.get("options") or []:
                st.write(f"- {opt}")
            return
        if "tables" in payload:
            st.write(f"{len(payload['tables'])} table(s)")
            for t in payload["tables"]:
                cols = ", ".join(c["name"] for c in t["columns"])
                st.write(f"**{t['name']}** — {cols}")
            return
        if "plotly_json" in payload:
            st.write(
                f"{payload.get('chart_type', '?')} chart · {payload.get('row_count', 0)} row(s)"
            )
            return
        if "row_count" in payload:
            cols = ", ".join(payload.get("columns", []))
            st.write(f"{payload['row_count']} row(s) · {cols}")


def _render_action_row(
    df: pd.DataFrame,
    *,
    key_prefix: str,
    explain_key: str | None,
) -> bool:
    """Right-aligned row of action buttons (CSV + optional Explain).

    Returns True if the Explain button was clicked on this rerun.
    """
    has_csv = not df.empty
    if not has_csv and explain_key is None:
        return False
    n_btns = int(has_csv) + int(explain_key is not None)
    outer = st.columns([20, n_btns])
    inner = outer[1].columns(n_btns)
    slot = 0
    if has_csv:
        with inner[slot]:
            st.download_button(
                "\u2193",
                df.to_csv(index=False).encode("utf-8"),
                file_name="result.csv",
                mime="text/csv",
                key=f"{key_prefix}-csv",
                help="Download CSV",
            )
        slot += 1
    clicked = False
    if explain_key is not None:
        with inner[slot]:
            if st.button("\u2726", key=explain_key, help="Explain this result"):
                clicked = True
    return clicked


def render_result_in_chat(
    payload: dict[str, Any],
    *,
    key_prefix: str,
    explain_key: str | None = None,
) -> bool:
    """Render a tool-result payload into the main chat area.

    The action buttons (CSV download + optional Explain) render as a
    right-aligned row above the chart/table. ``key_prefix`` must be
    unique per call; ``explain_key`` is the widget key for the Explain
    button — pass ``None`` to hide it. Returns True iff Explain was
    clicked on this rerun.
    """
    if "plotly_json" in payload:
        fig = pio.from_json(payload["plotly_json"])
        df = result_to_dataframe(payload)
        clicked = _render_action_row(df, key_prefix=key_prefix, explain_key=explain_key)
        st.plotly_chart(fig, use_container_width=True)
        if not df.empty:
            with st.expander("data"):
                st.dataframe(df, use_container_width=True)
        return clicked
    if "row_count" in payload and payload.get("rows"):
        df = result_to_dataframe(payload)
        clicked = _render_action_row(df, key_prefix=key_prefix, explain_key=explain_key)
        st.dataframe(df, use_container_width=True)
        return clicked
    return False


def render_kb_snippets(event: KBSearchResultEvent) -> None:
    """Render retrieved KB snippets in the main chat area as a soft callout.

    Used so the user can see what business context the agent pulled in
    before writing SQL. Renders nothing if the embedding call failed and
    no snippets came back — the error case shows a small caption instead.
    """
    if event.error and not event.snippets:
        st.caption(f"kb_search skipped: {event.error}")
        return
    if not event.snippets:
        return
    with st.expander(f"context for: _{event.query}_", expanded=False):
        for snip in event.snippets:
            doc = snip.get("doc", "")
            section = snip.get("section", "")
            score = snip.get("score")
            score_str = f"  ·  score {score:.2f}" if isinstance(score, (int, float)) else ""
            st.markdown(f"**{doc} › {section}**{score_str}")
            body = snip.get("body") or ""
            if body:
                st.markdown(body)


def render_ask_user_form(
    payload: dict[str, Any],
    *,
    key_prefix: str,
    interactive: bool = True,
) -> str | None:
    """Render an `ask_user` clarification form in the main chat area.

    When ``interactive`` is True, options render as buttons and the chosen
    label is returned on click. Past turns pass ``interactive=False`` so
    the options render as static text — re-clicking a stale turn must not
    re-fire the prompt.
    """
    question = payload.get("question") or ""
    options = payload.get("options") or []
    if question:
        st.markdown(f"**{question}**")
    if not interactive:
        for opt in options:
            st.markdown(f"- {opt}")
        return None
    for i, opt in enumerate(options):
        if st.button(str(opt), key=f"{key_prefix}-opt-{i}"):
            return str(opt)
    return None
