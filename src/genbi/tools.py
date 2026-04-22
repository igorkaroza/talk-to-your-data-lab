"""Agent tools exposed to the runtime.

All tools connect through :func:`genbi.db.get_engine` with its default
read-only role. SQL tools route through :mod:`genbi.safety` before
execution. Results are serialized as JSON text inside the MCP content
envelope so the agent can read them verbatim.

The tool bodies live in private ``_*_impl`` coroutines so the standalone
Postgres MCP in :mod:`mcp_servers.postgres_readonly` can reuse them
without copying. The ``@tool`` wrappers below are one-liners that shape
the payload into the in-process SDK MCP envelope.

Registered on the SDK MCP server in :mod:`genbi.agent`.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import plotly.express as px
from claude_agent_sdk import tool
from sqlalchemy import text

from genbi.db import get_engine
from genbi.safety import validate_and_prepare

STATEMENT_TIMEOUT = "5s"
VALID_CHART_TYPES = ("bar", "line", "pie", "scatter")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _as_content(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=_json_safe)}]}


def _run_select(sql: str) -> tuple[str, list[str], list[list[Any]]]:
    prepared = validate_and_prepare(sql)
    with get_engine().connect() as conn:
        conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        result = conn.execute(text(prepared))
        columns = list(result.keys())
        rows = [[_json_safe(v) for v in row] for row in result.fetchall()]
    return prepared, columns, rows


async def _schema_introspect_impl(_args: dict[str, Any]) -> dict[str, Any]:
    # Pull table + column descriptions from pg_catalog so the agent can read
    # the in-DB comments set by genbi.seed._apply_comments. The regclass cast
    # uses quote_ident to stay safe under mixed-case or quoted table names.
    query = text(
        """
        SELECT
            c.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable,
            col_description(
                (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                c.ordinal_position
            ) AS column_description,
            obj_description(
                (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                'pg_class'
            ) AS table_description
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
        ORDER BY c.table_name, c.ordinal_position
        """
    )
    tables: dict[str, dict[str, Any]] = {}
    with get_engine().connect() as conn:
        for (
            table_name,
            column_name,
            data_type,
            is_nullable,
            column_description,
            table_description,
        ) in conn.execute(query):
            entry = tables.setdefault(
                table_name,
                {"description": table_description or None, "columns": []},
            )
            column: dict[str, Any] = {
                "name": column_name,
                "type": data_type,
                "nullable": is_nullable == "YES",
            }
            if column_description:
                column["description"] = column_description
            entry["columns"].append(column)

    def _format(name: str, entry: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"name": name}
        if entry["description"]:
            out["description"] = entry["description"]
        out["columns"] = entry["columns"]
        return out

    return {"tables": [_format(name, entry) for name, entry in tables.items()]}


async def _sql_execute_impl(args: dict[str, Any]) -> dict[str, Any]:
    prepared, columns, rows = _run_select(args["sql"])
    return {
        "sql_executed": prepared,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }


async def _chart_render_impl(args: dict[str, Any]) -> dict[str, Any]:
    chart_type = args["chart_type"]
    if chart_type not in VALID_CHART_TYPES:
        raise ValueError(
            f"Unknown chart_type {chart_type!r}. Must be one of: {', '.join(VALID_CHART_TYPES)}"
        )
    x = args["x"]
    y = args["y"]
    prepared, columns, rows = _run_select(args["sql"])
    df = pd.DataFrame(rows, columns=columns)
    if chart_type == "pie":
        fig = px.pie(df, names=x, values=y)
    else:
        fig = getattr(px, chart_type)(df, x=x, y=y)
    return {
        "sql_executed": prepared,
        "chart_type": chart_type,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "plotly_json": fig.to_json(),
    }


async def _ask_user_impl(args: dict[str, Any]) -> dict[str, Any]:
    question = args.get("question", "")
    options = args.get("options") or []
    if not isinstance(options, list):
        raise ValueError("options must be a list of short string labels")
    return {
        "question": str(question),
        "options": [str(o) for o in options],
        "pending": True,
    }


@tool(
    "schema_introspect",
    "Return the schema of all public tables as JSON. Call this first to learn the columns.",
    {},
)
async def schema_introspect(args: dict[str, Any]) -> dict[str, Any]:
    return _as_content(await _schema_introspect_impl(args))


@tool(
    "sql_execute",
    "Run a read-only SELECT. LIMIT is appended if missing; non-SELECT statements are rejected.",
    {"sql": str},
)
async def sql_execute(args: dict[str, Any]) -> dict[str, Any]:
    return _as_content(await _sql_execute_impl(args))


@tool(
    "chart_render",
    (
        "Render a Plotly chart from a SELECT result. Use for trend/ranking/breakdown questions. "
        "chart_type must be one of: bar, line, pie, scatter. For pie, x is the category column "
        "and y is the numeric column."
    ),
    {"sql": str, "chart_type": str, "x": str, "y": str},
)
async def chart_render(args: dict[str, Any]) -> dict[str, Any]:
    return _as_content(await _chart_render_impl(args))


@tool(
    "ask_user",
    (
        "Ask the user a clarifying question BEFORE running any SQL. Use ONLY when the "
        "question is genuinely ambiguous (e.g. 'top customers' — by revenue or by count?). "
        "Provide 2-4 short option labels; the user picks one and it becomes the next turn. "
        "After calling this tool, end your turn — do not emit further text."
    ),
    {"question": str, "options": list},
)
async def ask_user(args: dict[str, Any]) -> dict[str, Any]:
    return _as_content(await _ask_user_impl(args))
