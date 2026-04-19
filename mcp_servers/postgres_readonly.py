"""Standalone stdio MCP exposing the GenBI read-only Postgres tools.

Mirrors the in-process ``@tool`` surface from :mod:`genbi.tools` (same
names, same input schemas, same payload shape) but runs as a separate
process over stdio. Registered in the repo's ``.mcp.json`` so any Claude
Code session opened in the repo inherits the three tools.

The tool bodies live in :mod:`genbi.tools` as private ``_*_impl``
coroutines — this module only handles the MCP framing. Routes every
connection through :func:`genbi.db.get_engine` with its default
read-only role, so the safety story (role isolation, sqlglot validator,
statement timeout, row cap) is identical across both paths.

Run with::

    uv run python -m mcp_servers.postgres_readonly
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import types as mcp_types
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

from genbi.tools import (
    _chart_render_impl,
    _json_safe,
    _schema_introspect_impl,
    _sql_execute_impl,
)

SERVER_NAME = "postgres-readonly"

TOOLS: list[mcp_types.Tool] = [
    mcp_types.Tool(
        name="schema_introspect",
        description=(
            "Return the schema of all public tables as JSON. Call this first to learn the columns."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    mcp_types.Tool(
        name="sql_execute",
        description=(
            "Run a read-only SELECT. LIMIT is appended if missing; "
            "non-SELECT statements are rejected."
        ),
        inputSchema={
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    ),
    mcp_types.Tool(
        name="chart_render",
        description=(
            "Render a Plotly chart from a SELECT result. Use for trend/ranking/breakdown "
            "questions. chart_type must be one of: bar, line, pie, scatter. For pie, x is "
            "the category column and y is the numeric column."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "chart_type": {"type": "string"},
                "x": {"type": "string"},
                "y": {"type": "string"},
            },
            "required": ["sql", "chart_type", "x", "y"],
            "additionalProperties": False,
        },
    ),
]

IMPLS = {
    "schema_introspect": _schema_introspect_impl,
    "sql_execute": _sql_execute_impl,
    "chart_render": _chart_render_impl,
}


def _text(payload: dict[str, Any]) -> list[mcp_types.TextContent]:
    return [mcp_types.TextContent(type="text", text=json.dumps(payload, default=_json_safe))]


def build_server() -> Server:
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return TOOLS

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[mcp_types.TextContent]:
        impl = IMPLS.get(name)
        if impl is None:
            raise ValueError(f"Unknown tool: {name!r}")
        return _text(await impl(arguments))

    return server


async def main() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
