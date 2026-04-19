"""GenBI agent runtime.

Wires the :mod:`genbi.tools` tools onto an in-process SDK MCP server and
runs a terminal chat loop through :class:`claude_agent_sdk.ClaudeSDKClient`.

Model and prompt are defined here so the CLI, evals, and Streamlit app
(M3) can import :func:`run_chat` or reuse :data:`OPTIONS` directly.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
)
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from genbi.events import (
    DoneEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
    TurnEvent,
)
from genbi.tools import chart_render, schema_introspect, sql_execute

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a GenBI analyst for a small Postgres database.

Workflow for every user question:
1. Call `schema_introspect` first to see what tables and columns exist.
2. Write a single PostgreSQL SELECT that answers the question. Prefer explicit
   column lists, avoid SELECT *, and always include a LIMIT if the result
   could be large. Use standard SQL date functions (e.g. date_trunc, interval).
3. Call `sql_execute` with that SQL. If it is rejected or returns nothing
   useful, revise the SQL and try again — do not guess numbers.
4. If the user asks for a chart, or the shape of the answer suggests one
   (trend over time, top-N ranking, breakdown by category), call
   `chart_render` instead of `sql_execute`. Pick chart_type from
   bar/line/pie/scatter and pass the column names as x and y.
5. Reply with a concise answer (one or two sentences) and a single line
   describing how you got it (which table(s) and which aggregation).

Rules:
- Never invent numbers. Every quantitative claim must come from a
  `sql_execute` or `chart_render` result.
- Never attempt INSERT/UPDATE/DELETE/DDL — the database is read-only and
  they will be rejected.
- Do not duplicate result data in your reply. If `chart_render` fired,
  the UI already shows the chart and the underlying rows (in a "data"
  expander) — never restate the same numbers as a Markdown table or
  bulleted list. If `sql_execute` fired and the UI is showing the table,
  same rule. Your reply is the *summary*, not a second rendering.
- Do not wrap monetary amounts in `$…$` — Markdown parses that as LaTeX.
  Write "USD 548,465" or escape the dollar sign ("\\$548,465").
"""

_MCP_SERVER = create_sdk_mcp_server(
    name="genbi",
    tools=[schema_introspect, sql_execute, chart_render],
)

OPTIONS = ClaudeAgentOptions(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
    mcp_servers={"genbi": _MCP_SERVER},
    allowed_tools=[
        "mcp__genbi__schema_introspect",
        "mcp__genbi__sql_execute",
        "mcp__genbi__chart_render",
    ],
)


def _short_tool_name(name: str) -> str:
    return name.replace("mcp__genbi__", "")


def _tool_result_event(block: ToolResultBlock, tool_names: dict[str, str]) -> ToolResultEvent:
    content = block.content
    if isinstance(content, list) and content and isinstance(content[0], dict):
        raw = content[0].get("text", "")
    else:
        raw = str(content) if content is not None else ""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    return ToolResultEvent(
        name=tool_names.get(block.tool_use_id, ""),
        payload=parsed if isinstance(parsed, dict) else None,
        raw_text=raw,
        is_error=bool(block.is_error),
    )


async def stream_turn(client: ClaudeSDKClient, prompt: str) -> AsyncIterator[TurnEvent]:
    """Drive one turn through ``client`` and yield typed events.

    Shared by the CLI and the Streamlit UI (M3) so both consume the same
    stream. The generator tracks ``tool_use_id`` → short name so that each
    :class:`ToolResultEvent` carries the name of the tool that produced it.
    """
    await client.query(prompt)
    tool_names: dict[str, str] = {}
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    yield TextEvent(text=block.text)
                elif isinstance(block, ToolUseBlock):
                    short = _short_tool_name(block.name)
                    tool_names[block.id] = short
                    yield ToolUseEvent(name=short, input=block.input or {})
        elif isinstance(message, UserMessage):
            if isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        yield _tool_result_event(block, tool_names)
        elif isinstance(message, ResultMessage):
            yield DoneEvent(
                num_turns=message.num_turns,
                cost_usd=message.total_cost_usd,
            )


def _render_tool_use(console: Console, event: ToolUseEvent) -> None:
    if event.name in {"sql_execute", "chart_render"} and "sql" in event.input:
        console.print(
            Panel(
                Syntax(event.input["sql"], "sql", theme="ansi_dark", word_wrap=True),
                title=f"[dim]tool →[/dim] [cyan]{event.name}[/cyan]",
                border_style="cyan",
            )
        )
    else:
        console.print(f"[dim]tool →[/dim] [cyan]{event.name}[/cyan]({event.input or ''})")


def _render_tool_result(console: Console, event: ToolResultEvent) -> None:
    payload = event.payload
    if payload is None:
        summary = event.raw_text[:200]
    elif "plotly_json" in payload:
        summary = (
            f"{payload.get('chart_type', '?')} chart, "
            f"{payload.get('row_count', 0)} row(s), columns: {payload.get('columns', [])}"
        )
    elif "row_count" in payload:
        summary = f"{payload['row_count']} row(s), columns: {payload.get('columns', [])}"
    elif "tables" in payload:
        tables = payload["tables"]
        summary = f"{len(tables)} table(s): {[t['name'] for t in tables]}"
    else:
        summary = event.raw_text[:200]
    marker = "[red]error[/red]" if event.is_error else "[dim]result[/dim]"
    console.print(f"{marker} {summary}")


async def _run_turn(client: ClaudeSDKClient, console: Console, prompt: str) -> None:
    async for event in stream_turn(client, prompt):
        if isinstance(event, TextEvent):
            console.print(event.text)
        elif isinstance(event, ToolUseEvent):
            _render_tool_use(console, event)
        elif isinstance(event, ToolResultEvent):
            _render_tool_result(console, event)
        elif isinstance(event, DoneEvent) and event.cost_usd is not None:
            console.print(f"[dim]— {event.num_turns} turn(s), ${event.cost_usd:.4f}[/dim]")


async def run_chat() -> None:
    """Terminal REPL. Type ``exit``, ``quit``, or Ctrl-D to leave."""
    console = Console()
    console.print(
        Panel(
            "[bold]GenBI[/bold] — ask me about sales_orders or tickets.\n"
            "[dim]Type 'exit' or Ctrl-D to quit.[/dim]",
            border_style="green",
        )
    )
    async with ClaudeSDKClient(options=OPTIONS) as client:
        while True:
            try:
                prompt = console.input("[bold green]you>[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                return
            if prompt.lower() in {"exit", "quit", ":q"}:
                return
            if not prompt:
                continue
            await _run_turn(client, console, prompt)
