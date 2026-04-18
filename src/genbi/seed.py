"""Reset the database to a known, story-friendly state.

Run with ``uv run python -m genbi.seed`` or via the ``/seed-data`` skill.

Responsibilities:
1. Drop + recreate the ``sales_orders`` and ``tickets`` tables.
2. Generate synthetic rows with :mod:`faker`, biased toward demo-worthy stories
   (regional skew, a couple of hero products, one underperforming team).
3. Provision the ``genbi_reader`` role with ``USAGE`` + ``SELECT`` only.

Runs as ``genbi_admin``. Never call from app or agent code — use
:func:`genbi.db.get_engine` with its default (read-only) role instead.
"""

from __future__ import annotations

import os
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from dotenv import load_dotenv
from faker import Faker
from sqlalchemy import text
from sqlalchemy.engine import Engine

from genbi.db import get_engine

load_dotenv()

SALES_ORDERS_DDL = """
CREATE TABLE sales_orders (
    order_id      BIGSERIAL PRIMARY KEY,
    order_date    DATE        NOT NULL,
    customer      TEXT        NOT NULL,
    product       TEXT        NOT NULL,
    category      TEXT        NOT NULL,
    region        TEXT        NOT NULL,
    quantity      INTEGER     NOT NULL,
    unit_price    NUMERIC(10, 2) NOT NULL,
    amount        NUMERIC(12, 2) NOT NULL
);
CREATE INDEX idx_sales_orders_date   ON sales_orders (order_date);
CREATE INDEX idx_sales_orders_region ON sales_orders (region);
"""

TICKETS_DDL = """
CREATE TABLE tickets (
    ticket_id        BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL,
    resolved_at      TIMESTAMPTZ,
    category         TEXT        NOT NULL,
    priority         TEXT        NOT NULL,
    assigned_team    TEXT        NOT NULL,
    status           TEXT        NOT NULL,
    resolution_hours NUMERIC(8, 2)
);
CREATE INDEX idx_tickets_created_at    ON tickets (created_at);
CREATE INDEX idx_tickets_priority      ON tickets (priority);
CREATE INDEX idx_tickets_assigned_team ON tickets (assigned_team);
"""

REGIONS = ["North", "South", "East", "West", "Central"]
REGION_WEIGHTS = [0.28, 0.14, 0.22, 0.26, 0.10]

PRODUCTS = {
    "Electronics": [("Aurora Laptop", 1499), ("Nimbus Phone", 899), ("Echo Buds", 149)],
    "Home":        [("Hearth Blender", 79),  ("Lumen Lamp", 39),    ("Atlas Chair", 249)],
    "Outdoor":     [("Trail Tent", 329),     ("Summit Pack", 119),  ("River Kayak", 699)],
    "Apparel":     [("Coast Jacket", 179),   ("Ridge Boots", 139),  ("Horizon Tee", 29)],
}
HERO_PRODUCTS = {"Aurora Laptop", "Trail Tent"}

TICKET_CATEGORIES = ["Network", "Auth", "Billing", "Performance", "Data", "UI"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
PRIORITY_WEIGHTS = [0.45, 0.35, 0.15, 0.05]
TEAMS = ["Platform", "AppOps", "Data", "Security", "Support"]
STATUSES = ["Open", "In Progress", "Resolved", "Closed"]

READER_ROLE = "genbi_reader"


def _reset_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS sales_orders CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS tickets CASCADE"))
        conn.execute(text(SALES_ORDERS_DDL))
        conn.execute(text(TICKETS_DDL))


def _gen_sales(faker: Faker, n: int) -> list[dict]:
    rows: list[dict] = []
    today = date.today()
    for _ in range(n):
        category = random.choice(list(PRODUCTS))
        product, base_price = random.choice(PRODUCTS[category])
        region = random.choices(REGIONS, REGION_WEIGHTS, k=1)[0]
        qty = random.randint(1, 6 if product in HERO_PRODUCTS else 3)
        unit = Decimal(str(round(base_price * random.uniform(0.9, 1.05), 2)))
        rows.append({
            "order_date": faker.date_between(start_date=today - timedelta(days=365), end_date=today),
            "customer":   faker.company(),
            "product":    product,
            "category":   category,
            "region":     region,
            "quantity":   qty,
            "unit_price": unit,
            "amount":     unit * qty,
        })
    return rows


def _gen_tickets(faker: Faker, n: int) -> list[dict]:
    rows: list[dict] = []
    now = datetime.now()
    for _ in range(n):
        created = faker.date_time_between(start_date=now - timedelta(days=180), end_date=now)
        priority = random.choices(PRIORITIES, PRIORITY_WEIGHTS, k=1)[0]
        team = random.choice(TEAMS)
        is_resolved = random.random() < 0.8
        base_hours = {"Low": 40, "Medium": 18, "High": 6, "Critical": 2}[priority]
        # "Support" team resolves slower — a demo-worthy story.
        jitter = random.uniform(0.4, 1.8) * (1.6 if team == "Support" else 1.0)
        resolution_hours = round(base_hours * jitter, 2) if is_resolved else None
        resolved_at = created + timedelta(hours=resolution_hours) if resolution_hours else None
        status = random.choice(["Resolved", "Closed"]) if is_resolved else random.choice(["Open", "In Progress"])
        rows.append({
            "created_at":       created,
            "resolved_at":      resolved_at,
            "category":         random.choice(TICKET_CATEGORIES),
            "priority":         priority,
            "assigned_team":    team,
            "status":           status,
            "resolution_hours": resolution_hours,
        })
    return rows


def _insert(engine: Engine, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    stmt = text(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
    )
    with engine.begin() as conn:
        conn.execute(stmt, rows)


def _provision_reader(engine: Engine, password: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER_ROLE}') THEN
                    CREATE ROLE {READER_ROLE} LOGIN PASSWORD '{password}';
                END IF;
            END
            $$;
        """))
        conn.execute(text(f"ALTER ROLE {READER_ROLE} WITH PASSWORD '{password}'"))
        # Reset then grant: keep the role strictly read-only.
        conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {READER_ROLE}"))
        conn.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {READER_ROLE}"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {READER_ROLE}"))
        conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READER_ROLE}"))
        conn.execute(text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {READER_ROLE}"
        ))


def _reader_password() -> str:
    # Pull from READONLY_DATABASE_URL so there is one source of truth.
    url = os.environ.get("READONLY_DATABASE_URL", "")
    # postgresql+psycopg://genbi_reader:PASSWORD@host:port/db
    try:
        after_scheme = url.split("://", 1)[1]
        creds, _ = after_scheme.split("@", 1)
        _, password = creds.split(":", 1)
        return password
    except (IndexError, ValueError) as err:
        raise RuntimeError(
            "Could not parse READONLY_DATABASE_URL. Expected "
            "postgresql+psycopg://genbi_reader:<password>@host:port/db"
        ) from err


def main(*, sales_rows: int = 2_000, ticket_rows: int = 1_200, seed: int = 42) -> None:
    random.seed(seed)
    faker = Faker()
    Faker.seed(seed)

    engine = get_engine(admin=True)

    print(f"[seed] resetting tables in {engine.url.database!r}...")
    _reset_tables(engine)

    print(f"[seed] inserting {sales_rows} sales_orders, {ticket_rows} tickets...")
    _insert(engine, "sales_orders", _gen_sales(faker, sales_rows))
    _insert(engine, "tickets", _gen_tickets(faker, ticket_rows))

    print(f"[seed] provisioning {READER_ROLE} role (SELECT-only)...")
    _provision_reader(engine, _reader_password())

    print("[seed] done.")


if __name__ == "__main__":
    main()
