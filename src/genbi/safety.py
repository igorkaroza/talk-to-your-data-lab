"""SQL safety layer for the GenBI read path.

Every SQL string produced by the agent is passed through
:func:`validate_and_prepare` before it is executed. The validator is a
defence-in-depth companion to the read-only ``genbi_reader`` Postgres role:
the role stops writes at the database boundary, and this validator stops
them earlier in the stack with a clear error the agent can reason about.

Rules enforced:

1. Exactly one statement. ``SELECT 1; DROP TABLE t`` is rejected.
2. Root node must be ``SELECT`` (optionally with a ``WITH`` clause) or a
   top-level ``WITH ... SELECT``. Anything else — including malformed input —
   is rejected.
3. No node in the tree may be DML or DDL: ``INSERT``, ``UPDATE``, ``DELETE``,
   ``DROP``, ``ALTER``, ``CREATE``, ``GRANT``, ``TRUNCATE``, ``COPY``.
4. Trailing semicolons and whitespace are stripped.
5. If the statement has no ``LIMIT`` clause, one is appended with
   ``default_limit`` (1000 by default).
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class SafetyError(ValueError):
    """Raised when the validator rejects a statement."""


_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Grant,
    exp.TruncateTable,
    exp.Copy,
)


def validate_and_prepare(sql: str, *, default_limit: int = 1000) -> str:
    """Parse, validate, and rewrite ``sql`` for safe read-only execution.

    Returns the sanitized SQL string with a ``LIMIT`` clause appended if one
    was not already present. Raises :class:`SafetyError` on any violation.
    """
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise SafetyError("Empty SQL statement")

    try:
        parsed = sqlglot.parse(cleaned, read="postgres")
    except ParseError as err:
        raise SafetyError(f"Could not parse SQL: {err}") from err

    statements = [stmt for stmt in parsed if stmt is not None]
    if not statements:
        raise SafetyError("Empty SQL statement")
    if len(statements) > 1:
        raise SafetyError("Only a single statement is allowed")

    root = statements[0]
    if not isinstance(root, (exp.Select, exp.With)):
        raise SafetyError(
            f"Only SELECT / WITH ... SELECT statements are allowed (got {type(root).__name__})"
        )

    for node in root.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SafetyError(
                f"Statement contains forbidden operation: {type(node).__name__.upper()}"
            )

    outer = root.this if isinstance(root, exp.With) else root
    if outer.args.get("limit") is None:
        root = root.limit(default_limit)

    return root.sql(dialect="postgres")
