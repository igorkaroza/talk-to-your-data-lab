"""Database engine factories.

Two roles live in Postgres:
- ``genbi_admin`` — created by docker-compose, used only by :mod:`genbi.seed`
  for DDL and data loading.
- ``genbi_reader`` — created by the seed step, used by the agent at runtime.
  Has ``USAGE`` on ``public`` and ``SELECT`` on tables. No write grants.

``get_engine`` returns the read-only engine by default so it is hard to hit the
DB with admin creds by accident.
"""

from __future__ import annotations

import os
from functools import cache

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

load_dotenv()


def _require(var: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise RuntimeError(f"{var} is not set. Copy .env.example to .env and fill it in.")
    return value


@cache
def get_engine(*, admin: bool = False) -> Engine:
    """Return a SQLAlchemy engine.

    ``admin=True`` only exists for the seed script. All other callers must
    leave it False so they connect as ``genbi_reader``.
    """
    url = _require("DATABASE_URL" if admin else "READONLY_DATABASE_URL")
    return create_engine(url, pool_pre_ping=True, future=True)
