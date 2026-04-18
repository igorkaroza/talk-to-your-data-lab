"""Integration tests for :mod:`genbi.tools`.

These hit the local docker Postgres via the read-only role. Assumes
``docker compose up -d postgres`` and ``uv run python -m genbi.seed`` have
run; otherwise the fixture skips the test with a clear message instead of
failing with an opaque connection error.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import OperationalError

from genbi.db import get_engine
from genbi.safety import SafetyError
from genbi.tools import chart_render, schema_introspect, sql_execute

DEFAULT_LIMIT = 1000


@pytest.fixture(scope="module", autouse=True)
def _require_db() -> None:
    try:
        engine = get_engine()
        with engine.connect():
            pass
    except OperationalError as err:
        pytest.skip(f"Postgres not reachable — run `docker compose up -d postgres`. ({err})")


def _payload(result: dict) -> dict:
    """Unwrap the MCP content envelope to the JSON payload we shipped."""
    text = result["content"][0]["text"]
    return json.loads(text)


class TestSchemaIntrospect:
    async def test_returns_sales_orders_and_tickets(self) -> None:
        result = await schema_introspect.handler({})
        payload = _payload(result)
        table_names = {t["name"] for t in payload["tables"]}
        assert {"sales_orders", "tickets"}.issubset(table_names)

    async def test_columns_have_name_type_nullable(self) -> None:
        result = await schema_introspect.handler({})
        payload = _payload(result)
        tickets = next(t for t in payload["tables"] if t["name"] == "tickets")
        col_names = {c["name"] for c in tickets["columns"]}
        assert {"ticket_id", "priority", "status"}.issubset(col_names)
        sample = tickets["columns"][0]
        assert {"name", "type", "nullable"}.issubset(sample)


class TestSqlExecuteHappyPath:
    async def test_select_returns_rows(self) -> None:
        result = await sql_execute.handler(
            {"sql": "SELECT priority, COUNT(*) AS n FROM tickets GROUP BY priority"}
        )
        payload = _payload(result)
        assert payload["row_count"] > 0
        assert payload["columns"] == ["priority", "n"]
        assert "LIMIT" in payload["sql_executed"].upper()

    async def test_limit_is_appended_when_missing(self) -> None:
        result = await sql_execute.handler({"sql": "SELECT * FROM sales_orders"})
        payload = _payload(result)
        assert payload["row_count"] <= DEFAULT_LIMIT
        assert "LIMIT" in payload["sql_executed"].upper()


class TestSqlExecuteSafety:
    async def test_insert_rejected(self) -> None:
        with pytest.raises(SafetyError):
            await sql_execute.handler({"sql": "INSERT INTO sales_orders (customer) VALUES ('x')"})

    async def test_drop_rejected(self) -> None:
        with pytest.raises(SafetyError):
            await sql_execute.handler({"sql": "DROP TABLE sales_orders"})

    async def test_multi_statement_rejected(self) -> None:
        with pytest.raises(SafetyError):
            await sql_execute.handler({"sql": "SELECT 1; DROP TABLE sales_orders"})


class TestChartRender:
    async def test_bar_chart_happy_path(self) -> None:
        result = await chart_render.handler(
            {
                "sql": "SELECT priority, COUNT(*) AS n FROM tickets GROUP BY priority",
                "chart_type": "bar",
                "x": "priority",
                "y": "n",
            }
        )
        payload = _payload(result)
        assert payload["chart_type"] == "bar"
        assert payload["columns"] == ["priority", "n"]
        assert payload["row_count"] > 0
        fig = json.loads(payload["plotly_json"])
        assert "data" in fig and len(fig["data"]) >= 1

    async def test_pie_chart_uses_names_values(self) -> None:
        result = await chart_render.handler(
            {
                "sql": "SELECT region, SUM(amount) AS total FROM sales_orders GROUP BY region",
                "chart_type": "pie",
                "x": "region",
                "y": "total",
            }
        )
        payload = _payload(result)
        assert payload["chart_type"] == "pie"
        fig = json.loads(payload["plotly_json"])
        assert fig["data"][0]["type"] == "pie"

    async def test_unknown_chart_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown chart_type"):
            await chart_render.handler(
                {
                    "sql": "SELECT region, SUM(amount) AS total FROM sales_orders GROUP BY region",
                    "chart_type": "heatmap",
                    "x": "region",
                    "y": "total",
                }
            )

    async def test_bad_sql_propagates_safety_error(self) -> None:
        with pytest.raises(SafetyError):
            await chart_render.handler(
                {
                    "sql": "DROP TABLE sales_orders",
                    "chart_type": "bar",
                    "x": "region",
                    "y": "total",
                }
            )
