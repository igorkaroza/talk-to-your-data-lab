"""Unit tests for :mod:`genbi.safety`.

These are pure-sqlglot tests — no DB needed.
"""

from __future__ import annotations

import pytest

from genbi.safety import SafetyError, validate_and_prepare


class TestHappyPath:
    def test_simple_select_passes_through(self) -> None:
        out = validate_and_prepare("SELECT 1")
        assert out.upper().startswith("SELECT")
        assert "LIMIT" in out.upper()

    def test_joined_select_allowed(self) -> None:
        sql = (
            "SELECT s.product, t.priority FROM sales_orders s "
            "JOIN tickets t ON s.region = t.assigned_team"
        )
        out = validate_and_prepare(sql)
        assert "JOIN" in out.upper()
        assert "LIMIT" in out.upper()

    def test_cte_then_select_allowed(self) -> None:
        sql = (
            "WITH recent AS (SELECT * FROM tickets WHERE priority = 'High') "
            "SELECT COUNT(*) FROM recent"
        )
        out = validate_and_prepare(sql)
        assert out.upper().startswith("WITH")
        assert "LIMIT" in out.upper()


class TestLimitInjection:
    def test_limit_appended_when_missing(self) -> None:
        out = validate_and_prepare("SELECT * FROM sales_orders", default_limit=500)
        assert "LIMIT 500" in out.upper().replace("  ", " ")

    def test_existing_limit_is_preserved(self) -> None:
        out = validate_and_prepare("SELECT * FROM sales_orders LIMIT 10")
        upper = out.upper()
        # Only one LIMIT clause — we didn't double-append.
        assert upper.count("LIMIT") == 1
        assert "LIMIT 10" in upper


class TestSemicolonStripping:
    def test_trailing_semicolon_stripped(self) -> None:
        out = validate_and_prepare("SELECT 1;")
        assert ";" not in out

    def test_trailing_whitespace_semicolon_stripped(self) -> None:
        out = validate_and_prepare("SELECT 1 ;  ")
        assert ";" not in out


class TestDMLRejection:
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO sales_orders (customer) VALUES ('x')",
            "UPDATE sales_orders SET quantity = 0",
            "DELETE FROM sales_orders",
            "DROP TABLE sales_orders",
            "ALTER TABLE sales_orders ADD COLUMN foo TEXT",
            "CREATE TABLE foo (id INT)",
            "GRANT SELECT ON sales_orders TO public",
            "TRUNCATE TABLE sales_orders",
            "COPY sales_orders TO '/tmp/x.csv'",
        ],
    )
    def test_dml_and_ddl_rejected(self, sql: str) -> None:
        with pytest.raises(SafetyError):
            validate_and_prepare(sql)


class TestMultiStatement:
    def test_multi_statement_rejected(self) -> None:
        with pytest.raises(SafetyError):
            validate_and_prepare("SELECT 1; DROP TABLE sales_orders")

    def test_multi_select_rejected(self) -> None:
        with pytest.raises(SafetyError):
            validate_and_prepare("SELECT 1; SELECT 2")


class TestParsingFailures:
    def test_empty_rejected(self) -> None:
        with pytest.raises(SafetyError):
            validate_and_prepare("")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(SafetyError):
            validate_and_prepare("   \n\t")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(SafetyError):
            validate_and_prepare("this is not sql")

    def test_safety_error_is_value_error(self) -> None:
        # So callers can `except ValueError:` if they want to be tolerant.
        with pytest.raises(ValueError):
            validate_and_prepare("DROP TABLE sales_orders")
