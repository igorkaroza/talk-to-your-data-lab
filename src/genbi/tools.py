"""Agent tools exposed to the runtime.

All tools connect through :func:`genbi.db.get_engine` with its default
read-only role. SQL tools route through :mod:`genbi.safety` before
execution. Results are serialized as JSON text inside the MCP content
envelope so the agent can read them verbatim.

Registered on the SDK MCP server in :mod:`genbi.agent`.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from claude_agent_sdk import tool
from sqlalchemy import text

from genbi.db import get_engine
from genbi.safety import validate_and_prepare

STATEMENT_TIMEOUT = "5s"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _as_content(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=_json_safe)}]}


@tool(
    "schema_introspect",
    "Return the schema of all public tables as JSON. Call this first to learn the columns.",
    {},
)
async def schema_introspect(_args: dict[str, Any]) -> dict[str, Any]:
    query = text(
        """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """
    )
    tables: dict[str, list[dict[str, Any]]] = {}
    with get_engine().connect() as conn:
        for table_name, column_name, data_type, is_nullable in conn.execute(query):
            tables.setdefault(table_name, []).append(
                {
                    "name": column_name,
                    "type": data_type,
                    "nullable": is_nullable == "YES",
                }
            )
    payload = {
        "tables": [{"name": name, "columns": cols} for name, cols in tables.items()],
    }
    return _as_content(payload)


@tool(
    "sql_execute",
    "Run a read-only SELECT. LIMIT is appended if missing; non-SELECT statements are rejected.",
    {"sql": str},
)
async def sql_execute(args: dict[str, Any]) -> dict[str, Any]:
    prepared = validate_and_prepare(args["sql"])
    with get_engine().connect() as conn:
        conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        result = conn.execute(text(prepared))
        columns = list(result.keys())
        rows = [[_json_safe(v) for v in row] for row in result.fetchall()]
    payload = {
        "sql_executed": prepared,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }
    return _as_content(payload)
