"""Database engine factories.

Three roles live in Postgres:
- ``genbi_admin`` — created by docker-compose, used only by :mod:`genbi.seed`
  for DDL and data loading.
- ``genbi_reader`` — created by the seed step, used by the agent at runtime.
  Has ``USAGE`` on ``public`` and ``SELECT`` on tables. No write grants.
- ``genbi_kb_writer`` — created by the seed step, used by the Streamlit
  ingest path only. Has ``SELECT/INSERT/DELETE`` on ``kb_chunks`` only,
  plus ``USAGE/SELECT`` on its serial sequence. No other write grants.

``get_engine`` returns the read-only engine by default so it is hard to hit the
DB with a privileged role by accident.
"""

from __future__ import annotations

import os
from functools import cache
from typing import Literal

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

load_dotenv()

Role = Literal["reader", "admin", "kb_writer"]

_ENV_VAR: dict[Role, str] = {
    "reader": "READONLY_DATABASE_URL",
    "admin": "DATABASE_URL",
    "kb_writer": "KB_WRITER_DATABASE_URL",
}


def _require(var: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise RuntimeError(f"{var} is not set. Copy .env.example to .env and fill it in.")
    return value


@cache
def get_engine(*, role: Role = "reader", admin: bool = False) -> Engine:
    """Return a SQLAlchemy engine for the given role.

    ``role`` defaults to ``"reader"`` so callers connect SELECT-only by default.
    ``admin=True`` is a back-compat shim for the seed scripts (equivalent to
    ``role="admin"``); new callers should pass ``role`` explicitly.
    """
    if admin:
        role = "admin"
    url = _require(_ENV_VAR[role])
    return create_engine(url, pool_pre_ping=True, future=True)
