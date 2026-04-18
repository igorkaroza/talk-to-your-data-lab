"""GenBI agent runtime.

Wires the :mod:`genbi.tools` tools onto an in-process SDK MCP server and
runs a terminal chat loop through :class:`claude_agent_sdk.ClaudeSDKClient`.

Model and prompt are defined here so the CLI, evals, and Streamlit app
(M3) can import :func:`run_chat` or reuse :data:`OPTIONS` directly.
"""

from __future__ import annotations

import json

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
)
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from genbi.tools import schema_introspect, sql_execute

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a GenBI analyst for a small Postgres database.

Workflow for every user question:
1. Call `schema_introspect` first to see what tables and columns exist.
2. Write a single PostgreSQL SELECT that answers the question. Prefer explicit
   column lists, avoid SELECT *, and always include a LIMIT if the result
   could be large. Use standard SQL date functions (e.g. date_trunc, interval).
3. Call `sql_execute` with that SQL. If it is rejected or returns nothing
   useful, revise the SQL and try again — do not guess numbers.
4. Reply with a concise answer (one or two sentences) and a single line
   describing how you got it (which table(s) and which aggregation).

Rules:
- Never invent numbers. Every quantitative claim must come from a
  `sql_execute` result.
- Never attempt INSERT/UPDATE/DELETE/DDL — the database is read-only and
  they will be rejected.
"""

_MCP_SERVER = create_sdk_mcp_server(
    name="genbi",
    tools=[schema_introspect, sql_execute],
)

OPTIONS = ClaudeAgentOptions(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
    mcp_servers={"genbi": _MCP_SERVER},
    allowed_tools=[
        "mcp__genbi__schema_introspect",
        "mcp__genbi__sql_execute",
    ],
)


def _render_tool_use(console: Console, block: ToolUseBlock) -> None:
    short_name = block.name.replace("mcp__genbi__", "")
    if short_name == "sql_execute" and "sql" in block.input:
        console.print(
            Panel(
                Syntax(block.input["sql"], "sql", theme="ansi_dark", word_wrap=True),
                title=f"[dim]tool →[/dim] [cyan]{short_name}[/cyan]",
                border_style="cyan",
            )
        )
    else:
        console.print(f"[dim]tool →[/dim] [cyan]{short_name}[/cyan]({block.input or ''})")


def _render_tool_result(console: Console, block: ToolResultBlock) -> None:
    content = block.content
    if isinstance(content, list) and content and isinstance(content[0], dict):
        text = content[0].get("text", "")
    else:
        text = str(content)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        summary = text[:200]
    else:
        if "row_count" in parsed:
            summary = f"{parsed['row_count']} row(s), columns: {parsed.get('columns', [])}"
        elif "tables" in parsed:
            summary = f"{len(parsed['tables'])} table(s): {[t['name'] for t in parsed['tables']]}"
        else:
            summary = text[:200]
    marker = "[red]error[/red]" if block.is_error else "[dim]result[/dim]"
    console.print(f"{marker} {summary}")


async def _run_turn(client: ClaudeSDKClient, console: Console, prompt: str) -> None:
    await client.query(prompt)
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    console.print(block.text)
                elif isinstance(block, ToolUseBlock):
                    _render_tool_use(console, block)
                elif isinstance(block, ToolResultBlock):
                    _render_tool_result(console, block)
        elif isinstance(message, ResultMessage) and message.total_cost_usd is not None:
            console.print(
                f"[dim]— {message.num_turns} turn(s), ${message.total_cost_usd:.4f}[/dim]"
            )


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
